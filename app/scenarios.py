import json
import math
from datetime import datetime, timezone

from flask import jsonify, request, session

from . import db
from .rbac import has_permission


SCENARIO_TYPES = {"Essenziale", "Equilibrato", "Evolutivo"}
SCENARIO_STATUSES = {"Bozza", "Da verificare", "Validato dal tecnico", "Approvato"}
RELIABILITY_LEVELS = {"Da verificare", "Dichiarato", "Documentato", "Verificato"}
TECHNICAL_STATES = {"Da verificare", "Verifica in corso", "Verificato", "Criticità rilevate"}
COST_CATEGORIES = {
    "Demolizioni e opere edili", "Impianti", "Infissi", "Finiture",
    "Tecnici e pratiche", "Imposte, notaio e agenzia", "Costi finanziari",
    "Costi di mantenimento", "Vendita", "Fondo imprevisti", "Altro",
}


def init_scenarios(app, app_module):
    if app.extensions.get("aplsai_scenarios"):
        return

    class PropertyScenario(db.Model):
        __tablename__ = "property_scenario"
        id = db.Column(db.Integer, primary_key=True)
        property_id = db.Column(db.Integer, db.ForeignKey("property.id"), nullable=False, index=True)
        client_id = db.Column(db.Integer, db.ForeignKey("user.id"), nullable=True, index=True)
        name = db.Column(db.String(160), nullable=False)
        scenario_type = db.Column(db.String(40), nullable=False, default="Equilibrato")
        status = db.Column(db.String(50), nullable=False, default="Da verificare")
        description = db.Column(db.Text, nullable=False, default="")
        projected_sqm = db.Column(db.Float)
        projected_beds = db.Column(db.Integer)
        projected_baths = db.Column(db.Integer)
        months_min = db.Column(db.Integer)
        months_max = db.Column(db.Integer)
        assumptions = db.Column(db.Text, nullable=False, default="")
        constraints = db.Column(db.Text, nullable=False, default="")
        technical_validation = db.Column(db.String(80), nullable=False, default="Da verificare")
        version = db.Column(db.Integer, nullable=False, default=1)
        archived_at = db.Column(db.DateTime(timezone=True))
        created_at = db.Column(db.DateTime(timezone=True), nullable=False, default=app_module.utcnow)
        updated_at = db.Column(db.DateTime(timezone=True), nullable=False, default=app_module.utcnow)

    class ScenarioCostItem(db.Model):
        __tablename__ = "scenario_cost_item"
        id = db.Column(db.Integer, primary_key=True)
        scenario_id = db.Column(db.Integer, db.ForeignKey("property_scenario.id"), nullable=False, index=True)
        category = db.Column(db.String(100), nullable=False)
        description = db.Column(db.String(500), nullable=False)
        quantity = db.Column(db.Float, nullable=False)
        unit = db.Column(db.String(30), nullable=False)
        unit_price_min = db.Column(db.Float, nullable=False)
        unit_price_max = db.Column(db.Float, nullable=False)
        source = db.Column(db.String(160), nullable=False, default="Da verificare")
        reliability = db.Column(db.String(40), nullable=False, default="Da verificare")
        created_at = db.Column(db.DateTime(timezone=True), nullable=False, default=app_module.utcnow)

        def to_dict(self):
            return {
                "id": self.id, "scenario_id": self.scenario_id, "category": self.category,
                "description": self.description, "quantity": self.quantity, "unit": self.unit,
                "unit_price_min": self.unit_price_min, "unit_price_max": self.unit_price_max,
                "total_min": round(self.quantity * self.unit_price_min, 2),
                "total_max": round(self.quantity * self.unit_price_max, 2),
                "source": self.source, "reliability": self.reliability,
                "created_at": self.created_at.isoformat() if self.created_at else None,
            }

    class ScenarioRevision(db.Model):
        __tablename__ = "scenario_revision"
        id = db.Column(db.Integer, primary_key=True)
        scenario_id = db.Column(db.Integer, db.ForeignKey("property_scenario.id"), nullable=False, index=True)
        version = db.Column(db.Integer, nullable=False)
        snapshot_json = db.Column(db.Text, nullable=False)
        changed_by_user_id = db.Column(db.Integer, db.ForeignKey("user.id"), nullable=False)
        change_note = db.Column(db.String(255), nullable=False)
        created_at = db.Column(db.DateTime(timezone=True), nullable=False, default=app_module.utcnow)
        __table_args__ = (db.UniqueConstraint("scenario_id", "version", name="uq_scenario_revision_version"),)

        def to_dict(self):
            return {
                "id": self.id, "scenario_id": self.scenario_id, "version": self.version,
                "snapshot": json.loads(self.snapshot_json), "changed_by_user_id": self.changed_by_user_id,
                "change_note": self.change_note,
                "created_at": self.created_at.isoformat() if self.created_at else None,
            }

    with app.app_context():
        db.create_all()

    def staff_user():
        uid = session.get("uid")
        actor = db.session.get(app_module.User, uid) if uid else None
        if not actor:
            return None, (jsonify(error="Non autenticato."), 401)
        if getattr(actor, "active", True) is False:
            session.clear()
            return None, (jsonify(error="Account disattivato."), 401)
        if not has_permission(actor.role, "scenario_manage"):
            return None, (jsonify(error="Permesso insufficiente."), 403)
        return actor, None

    def audit(actor, action, object_id, detail=""):
        fn = (app.extensions.get("aplsai_operations") or {}).get("audit")
        if fn:
            fn(actor, action, "scenario", object_id, detail)

    def optional_number(data, key, cast=float):
        if key not in data or data.get(key) in (None, ""):
            return None
        return cast(data[key])

    def items_for(scenario_id):
        return ScenarioCostItem.query.filter_by(scenario_id=scenario_id).order_by(ScenarioCostItem.id.asc()).all()

    def totals_for(scenario, items=None):
        items = items if items is not None else items_for(scenario.id)
        prop = db.session.get(app_module.Property, scenario.property_id)
        purchase = float(prop.price) if prop else 0
        items_min = round(sum(item.quantity * item.unit_price_min for item in items), 2)
        items_max = round(sum(item.quantity * item.unit_price_max for item in items), 2)
        categories = {item.category for item in items}
        work_categories = {"Demolizioni e opere edili", "Impianti", "Infissi", "Finiture"}
        missing = []
        if not categories.intersection(work_categories):
            missing.append("Lavori")
        for category, label in (
            ("Tecnici e pratiche", "Tecnici e pratiche"),
            ("Imposte, notaio e agenzia", "Imposte, notaio e agenzia"),
            ("Costi finanziari", "Costi finanziari"),
            ("Fondo imprevisti", "Fondo imprevisti"),
        ):
            if category not in categories:
                missing.append(label)
        budget = None
        if scenario.client_id:
            client = app_module.client_obj(scenario.client_id)
            if client:
                data = client.get("budget") or {}
                maximum = float(data.get("max") or 0)
                flex = float(data.get("flex") or 0)
                ceiling = maximum * (1 + flex / 100)
                known_max = purchase + items_max
                budget = {
                    "maximum": maximum, "with_flex": round(ceiling, 2),
                    "known_margin": round(ceiling - known_max, 2),
                    "status": "parziale_da_verificare" if missing else ("compatibile" if known_max <= ceiling else "fuori_budget"),
                }
        return {
            "purchase_price": purchase, "items_min": items_min, "items_max": items_max,
            "known_total_min": round(purchase + items_min, 2),
            "known_total_max": round(purchase + items_max, 2),
            "missing_categories": missing, "complete": not missing, "budget": budget,
        }

    def scenario_dict(scenario, include_history=False):
        items = items_for(scenario.id)
        prop = db.session.get(app_module.Property, scenario.property_id)
        client = app_module.client_obj(scenario.client_id) if scenario.client_id else None
        result = {
            "id": scenario.id, "property_id": scenario.property_id, "property_ref": prop.ref if prop else None,
            "client_id": scenario.client_id, "client_name": client.get("name") if client else None,
            "name": scenario.name, "scenario_type": scenario.scenario_type, "status": scenario.status,
            "description": scenario.description, "projected_sqm": scenario.projected_sqm,
            "projected_beds": scenario.projected_beds, "projected_baths": scenario.projected_baths,
            "months_min": scenario.months_min, "months_max": scenario.months_max,
            "assumptions": scenario.assumptions, "constraints": scenario.constraints,
            "technical_validation": scenario.technical_validation, "version": scenario.version,
            "archived_at": scenario.archived_at.isoformat() if scenario.archived_at else None,
            "created_at": scenario.created_at.isoformat() if scenario.created_at else None,
            "updated_at": scenario.updated_at.isoformat() if scenario.updated_at else None,
            "items": [item.to_dict() for item in items], "totals": totals_for(scenario, items),
        }
        if include_history:
            revisions = ScenarioRevision.query.filter_by(scenario_id=scenario.id).order_by(ScenarioRevision.version.desc()).limit(20).all()
            result["revisions"] = [row.to_dict() for row in revisions]
        return result

    def record_revision(scenario, actor, note):
        snapshot = scenario_dict(scenario)
        db.session.add(ScenarioRevision(
            scenario_id=scenario.id, version=scenario.version,
            snapshot_json=json.dumps(snapshot, ensure_ascii=False),
            changed_by_user_id=actor.id,
            change_note=app_module.clean_text(note or "Scenario aggiornato", 255),
        ))

    def apply_payload(scenario, data):
        if "name" in data:
            scenario.name = app_module.clean_text(data.get("name"), 160)
        if "scenario_type" in data:
            scenario.scenario_type = app_module.clean_text(data.get("scenario_type"), 40)
        if "status" in data:
            scenario.status = app_module.clean_text(data.get("status"), 50)
        for field, limit in {"description": 4000, "assumptions": 4000, "constraints": 4000, "technical_validation": 80}.items():
            if field in data:
                setattr(scenario, field, app_module.clean_text(data.get(field), limit))
        for field, cast in {"projected_sqm": float, "projected_beds": int, "projected_baths": int, "months_min": int, "months_max": int}.items():
            if field in data:
                value = optional_number(data, field, cast)
                if value is not None and (not math.isfinite(value) or value < 0):
                    raise ValueError("Superfici, vani e tempi non possono essere negativi.")
                setattr(scenario, field, value)
        if not scenario.name:
            raise ValueError("Nome scenario obbligatorio.")
        if scenario.scenario_type not in SCENARIO_TYPES:
            raise ValueError("Tipo scenario non valido.")
        if scenario.status not in SCENARIO_STATUSES:
            raise ValueError("Stato scenario non valido.")
        if scenario.technical_validation not in TECHNICAL_STATES:
            raise ValueError("Validazione tecnica non valida.")
        if scenario.months_min is not None and scenario.months_max is not None and scenario.months_min > scenario.months_max:
            raise ValueError("La durata minima non può superare quella massima.")

    @app.get("/api/staff/scenarios")
    def scenario_list():
        actor, denied = staff_user()
        if denied:
            return denied
        query = PropertyScenario.query
        property_id = request.args.get("property_id", type=int)
        if property_id:
            query = query.filter_by(property_id=property_id)
        if request.args.get("include_archived") != "1":
            query = query.filter(PropertyScenario.archived_at.is_(None))
        rows = query.order_by(PropertyScenario.updated_at.desc()).all()
        return jsonify(scenarios=[scenario_dict(row) for row in rows])

    @app.get("/api/staff/scenarios/<int:scenario_id>")
    def scenario_detail(scenario_id):
        actor, denied = staff_user()
        if denied:
            return denied
        scenario = db.session.get(PropertyScenario, scenario_id)
        if not scenario:
            return jsonify(error="Scenario non trovato."), 404
        return jsonify(scenario=scenario_dict(scenario, include_history=True))

    @app.post("/api/staff/scenarios")
    def scenario_create():
        actor, denied = staff_user()
        if denied:
            return denied
        data = request.get_json(silent=True) or {}
        try:
            property_id = int(data.get("property_id"))
            client_id = int(data["client_id"]) if data.get("client_id") not in (None, "") else None
        except (TypeError, ValueError):
            return jsonify(error="Immobile o cliente non valido."), 400
        prop = db.session.get(app_module.Property, property_id)
        if not prop or prop.archived_at:
            return jsonify(error="Immobile non disponibile."), 404
        if client_id and not app_module.ClientProfile.query.filter_by(user_id=client_id).first():
            return jsonify(error="Cliente non trovato."), 404
        scenario = PropertyScenario(
            property_id=prop.id, client_id=client_id, name="",
            scenario_type="Equilibrato", status="Da verificare",
            technical_validation="Da verificare",
        )
        try:
            apply_payload(scenario, data)
        except (TypeError, ValueError) as exc:
            return jsonify(error=str(exc)), 400
        db.session.add(scenario)
        db.session.flush()
        record_revision(scenario, actor, "Creazione scenario")
        audit(actor, "scenario_create", scenario.id, f"property={prop.id}")
        db.session.commit()
        return jsonify(scenario=scenario_dict(scenario)), 201

    @app.patch("/api/staff/scenarios/<int:scenario_id>")
    def scenario_update(scenario_id):
        actor, denied = staff_user()
        if denied:
            return denied
        scenario = db.session.get(PropertyScenario, scenario_id)
        if not scenario:
            return jsonify(error="Scenario non trovato."), 404
        data = request.get_json(silent=True) or {}
        try:
            apply_payload(scenario, data)
        except (TypeError, ValueError) as exc:
            return jsonify(error=str(exc)), 400
        scenario.version += 1
        scenario.updated_at = datetime.now(timezone.utc)
        record_revision(scenario, actor, data.get("change_note") or "Scenario aggiornato")
        audit(actor, "scenario_update", scenario.id)
        db.session.commit()
        return jsonify(scenario=scenario_dict(scenario))

    @app.patch("/api/staff/scenarios/<int:scenario_id>/archive")
    def scenario_archive(scenario_id):
        actor, denied = staff_user()
        if denied:
            return denied
        data = request.get_json(silent=True) or {}
        if not isinstance(data.get("archived"), bool):
            return jsonify(error="Stato archivio non valido."), 400
        scenario = db.session.get(PropertyScenario, scenario_id)
        if not scenario:
            return jsonify(error="Scenario non trovato."), 404
        scenario.archived_at = datetime.now(timezone.utc) if data["archived"] else None
        scenario.version += 1
        scenario.updated_at = datetime.now(timezone.utc)
        record_revision(scenario, actor, "Scenario archiviato" if data["archived"] else "Scenario ripristinato")
        audit(actor, "scenario_archive" if data["archived"] else "scenario_restore", scenario.id)
        db.session.commit()
        return jsonify(scenario=scenario_dict(scenario))

    @app.post("/api/staff/scenarios/<int:scenario_id>/cost-items")
    def cost_item_create(scenario_id):
        actor, denied = staff_user()
        if denied:
            return denied
        scenario = db.session.get(PropertyScenario, scenario_id)
        if not scenario or scenario.archived_at:
            return jsonify(error="Scenario non disponibile."), 404
        data = request.get_json(silent=True) or {}
        try:
            category = app_module.clean_text(data.get("category"), 100)
            description = app_module.clean_text(data.get("description"), 500)
            quantity = float(data.get("quantity"))
            unit = app_module.clean_text(data.get("unit"), 30)
            price_min = float(data.get("unit_price_min"))
            price_max = float(data.get("unit_price_max"))
            reliability = app_module.clean_text(data.get("reliability") or "Da verificare", 40)
            if category not in COST_CATEGORIES or reliability not in RELIABILITY_LEVELS:
                raise ValueError("Categoria o affidabilità non valida.")
            if not all(math.isfinite(value) for value in (quantity, price_min, price_max)):
                raise ValueError("Quantità e prezzi devono essere numeri finiti.")
            if not description or not unit or quantity <= 0 or price_min < 0 or price_max < price_min:
                raise ValueError("Voce di costo incompleta o non valida.")
        except (TypeError, ValueError) as exc:
            return jsonify(error=str(exc) or "Voce di costo non valida."), 400
        item = ScenarioCostItem(
            scenario_id=scenario.id, category=category, description=description,
            quantity=quantity, unit=unit, unit_price_min=price_min, unit_price_max=price_max,
            source=app_module.clean_text(data.get("source") or "Da verificare", 160), reliability=reliability,
        )
        db.session.add(item)
        db.session.flush()
        scenario.version += 1
        scenario.updated_at = datetime.now(timezone.utc)
        record_revision(scenario, actor, f"Aggiunta voce: {description}")
        audit(actor, "scenario_cost_add", scenario.id, f"item={item.id}")
        db.session.commit()
        return jsonify(scenario=scenario_dict(scenario)), 201

    @app.delete("/api/staff/scenarios/<int:scenario_id>/cost-items/<int:item_id>")
    def cost_item_delete(scenario_id, item_id):
        actor, denied = staff_user()
        if denied:
            return denied
        scenario = db.session.get(PropertyScenario, scenario_id)
        item = db.session.get(ScenarioCostItem, item_id)
        if not scenario or not item or item.scenario_id != scenario.id:
            return jsonify(error="Voce di costo non trovata."), 404
        description = item.description
        db.session.delete(item)
        db.session.flush()
        scenario.version += 1
        scenario.updated_at = datetime.now(timezone.utc)
        record_revision(scenario, actor, f"Rimossa voce: {description}")
        audit(actor, "scenario_cost_delete", scenario.id, f"item={item_id}")
        db.session.commit()
        return jsonify(scenario=scenario_dict(scenario))

    app.extensions["aplsai_scenarios"] = {
        "PropertyScenario": PropertyScenario,
        "ScenarioCostItem": ScenarioCostItem,
        "ScenarioRevision": ScenarioRevision,
        "scenario_dict": scenario_dict,
    }
