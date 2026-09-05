import json
import math
from datetime import date, datetime, timezone
from urllib.parse import parse_qsl, urlencode, urlsplit, urlunsplit

from flask import jsonify, request, session

from . import db
from .rbac import has_permission


SOURCE_TYPES = {"Portale", "Agenzia", "Proprietario", "Costruttore o partner", "Segnalazione", "Fonte pubblica", "Altro"}
STATUSES = {"Nuova", "Da verificare", "Documenti mancanti", "Analisi tecnica", "Match trovato", "Proposta inviata", "In trattativa", "Scartata"}
DOCUMENT_STATES = {"Da verificare", "Mancanti", "Parziali", "Completi"}
PLAN_STATES = {"Da verificare", "Mancante", "Disponibile", "Verificata"}
ANALYSIS_STATES = {"Non iniziata", "In corso", "Preliminare completata", "Criticità rilevate"}
DECISIONS = {"Da decidere", "Procedere", "Non procedere", "Sospesa"}
RELIABILITY_LEVELS = {"Da verificare", "Dichiarato", "Documentato", "Verificato"}


def init_opportunities(app, app_module):
    if app.extensions.get("aplsai_opportunities"):
        return

    class PropertyOpportunity(db.Model):
        __tablename__ = "property_opportunity"
        id = db.Column(db.Integer, primary_key=True)
        title = db.Column(db.String(200), nullable=False)
        source_type = db.Column(db.String(60), nullable=False)
        source_name = db.Column(db.String(160), nullable=False, default="")
        source_url = db.Column(db.Text, nullable=False, default="")
        normalized_url = db.Column(db.Text, nullable=False, default="", index=True)
        external_ref = db.Column(db.String(160), nullable=False, default="")
        contact_name = db.Column(db.String(160), nullable=False, default="")
        contact_details = db.Column(db.String(500), nullable=False, default="")
        zone = db.Column(db.String(200), nullable=False)
        address = db.Column(db.String(255), nullable=False, default="")
        price = db.Column(db.Float)
        sqm = db.Column(db.Float)
        property_type = db.Column(db.String(80), nullable=False, default="Da definire")
        state = db.Column(db.String(100), nullable=False, default="Da verificare")
        availability = db.Column(db.String(80), nullable=False, default="Da verificare")
        documents_status = db.Column(db.String(40), nullable=False, default="Da verificare")
        planimetry_status = db.Column(db.String(40), nullable=False, default="Da verificare")
        analysis_status = db.Column(db.String(50), nullable=False, default="Non iniziata")
        data_reliability = db.Column(db.String(40), nullable=False, default="Da verificare")
        status = db.Column(db.String(50), nullable=False, default="Nuova")
        risks = db.Column(db.Text, nullable=False, default="")
        potential = db.Column(db.Text, nullable=False, default="")
        notes = db.Column(db.Text, nullable=False, default="")
        decision = db.Column(db.String(40), nullable=False, default="Da decidere")
        decision_note = db.Column(db.Text, nullable=False, default="")
        rejection_reason = db.Column(db.Text, nullable=False, default="")
        last_checked_on = db.Column(db.Date)
        linked_property_id = db.Column(db.Integer, db.ForeignKey("property.id"), index=True)
        version = db.Column(db.Integer, nullable=False, default=1)
        archived_at = db.Column(db.DateTime(timezone=True))
        created_by_user_id = db.Column(db.Integer, db.ForeignKey("user.id"), nullable=False)
        created_at = db.Column(db.DateTime(timezone=True), nullable=False, default=app_module.utcnow)
        updated_at = db.Column(db.DateTime(timezone=True), nullable=False, default=app_module.utcnow)

    class OpportunityRevision(db.Model):
        __tablename__ = "property_opportunity_revision"
        id = db.Column(db.Integer, primary_key=True)
        opportunity_id = db.Column(db.Integer, db.ForeignKey("property_opportunity.id"), nullable=False, index=True)
        version = db.Column(db.Integer, nullable=False)
        snapshot_json = db.Column(db.Text, nullable=False)
        changed_by_user_id = db.Column(db.Integer, db.ForeignKey("user.id"), nullable=False)
        change_note = db.Column(db.String(255), nullable=False)
        created_at = db.Column(db.DateTime(timezone=True), nullable=False, default=app_module.utcnow)
        __table_args__ = (db.UniqueConstraint("opportunity_id", "version", name="uq_opportunity_revision_version"),)

        def to_dict(self):
            return {
                "id": self.id, "opportunity_id": self.opportunity_id, "version": self.version,
                "snapshot": json.loads(self.snapshot_json), "changed_by_user_id": self.changed_by_user_id,
                "change_note": self.change_note,
                "created_at": self.created_at.isoformat() if self.created_at else None,
            }

    with app.app_context():
        db.create_all()

    def staff_user(permission):
        uid = session.get("uid")
        actor = db.session.get(app_module.User, uid) if uid else None
        if not actor:
            return None, (jsonify(error="Non autenticato."), 401)
        if getattr(actor, "active", True) is False:
            session.clear()
            return None, (jsonify(error="Account disattivato."), 401)
        if not has_permission(actor.role, permission):
            return None, (jsonify(error="Permesso insufficiente."), 403)
        return actor, None

    def audit(actor, action, object_id, detail=""):
        fn = (app.extensions.get("aplsai_operations") or {}).get("audit")
        if fn:
            fn(actor, action, "opportunity", object_id, detail)

    def normalize_url(value):
        value = app_module.clean_text(value, 2000)
        if not value:
            return ""
        if not app_module.valid_http_url(value):
            raise ValueError("Collegamento annuncio non valido.")
        parts = urlsplit(value)
        query = urlencode(sorted((k, v) for k, v in parse_qsl(parts.query, keep_blank_values=True) if not k.lower().startswith("utm_")))
        return urlunsplit((parts.scheme.lower(), parts.netloc.lower(), parts.path.rstrip("/"), query, ""))

    def possible_duplicates(opportunity):
        query = PropertyOpportunity.query.filter(PropertyOpportunity.id != opportunity.id)
        candidates = []
        for row in query.order_by(PropertyOpportunity.updated_at.desc()).limit(200).all():
            reasons = []
            if opportunity.normalized_url and row.normalized_url == opportunity.normalized_url:
                reasons.append("stesso collegamento")
            if opportunity.external_ref and row.external_ref and opportunity.source_name.lower() == row.source_name.lower() and opportunity.external_ref.lower() == row.external_ref.lower():
                reasons.append("stesso riferimento della fonte")
            if opportunity.address and row.address and opportunity.address.strip().lower() == row.address.strip().lower():
                reasons.append("stesso indirizzo")
            if opportunity.price and opportunity.sqm and row.price == opportunity.price and row.sqm == opportunity.sqm and opportunity.zone.lower() == row.zone.lower():
                reasons.append("stessa zona, prezzo e metratura")
            if reasons:
                candidates.append({"id": row.id, "title": row.title, "reasons": reasons, "linked_property_id": row.linked_property_id})
        return candidates

    def preliminary_matches(opportunity):
        rows = []
        profiles = app_module.ClientProfile.query.filter(
            app_module.ClientProfile.is_test.is_(False), app_module.ClientProfile.archived_at.is_(None),
            app_module.ClientProfile.status == "Ricerca attiva",
        ).all()
        for profile in profiles:
            client = app_module.client_obj(profile.user_id)
            if not client:
                continue
            checks = []
            client_zone = str((client.get("zone") or {}).get("main") or "").strip().lower()
            opportunity_zone = opportunity.zone.strip().lower()
            if client_zone and opportunity_zone:
                zone_ok = client_zone in opportunity_zone or opportunity_zone in client_zone
                checks.append({"criterion": "Zona", "status": "compatibile" if zone_ok else "non compatibile"})
            else:
                checks.append({"criterion": "Zona", "status": "da verificare"})
            maximum_budget = (client.get("budget") or {}).get("max")
            if opportunity.price is not None and maximum_budget is not None:
                budget_ok = opportunity.price <= float(maximum_budget)
                checks.append({"criterion": "Budget", "status": "compatibile" if budget_ok else "non compatibile"})
            else:
                checks.append({"criterion": "Budget", "status": "da verificare"})
            desired_sqm = (client.get("spaces") or {}).get("sqm")
            if opportunity.sqm is not None and desired_sqm is not None:
                checks.append({"criterion": "Metratura attuale", "status": "compatibile" if opportunity.sqm >= float(desired_sqm) else "da trasformare o verificare"})
            else:
                checks.append({"criterion": "Metratura attuale", "status": "da verificare"})
            wanted_types = [str(value).lower() for value in (client.get("houseTypes") or [])]
            if opportunity.property_type != "Da definire" and wanted_types:
                checks.append({"criterion": "Tipologia", "status": "compatibile" if opportunity.property_type.lower() in wanted_types else "da verificare"})
            else:
                checks.append({"criterion": "Tipologia", "status": "da verificare"})
            hard = {row["criterion"]: row["status"] for row in checks}
            if hard.get("Zona") == "compatibile" and hard.get("Budget") == "compatibile":
                recommendation = "COMPATIBILITÀ PRELIMINARE"
            elif "non compatibile" in {hard.get("Zona"), hard.get("Budget")}:
                recommendation = "BASSA COMPATIBILITÀ"
            else:
                recommendation = "DA VERIFICARE"
            rows.append({"client_id": client["id"], "client_name": client["name"], "recommendation": recommendation, "checks": checks})
        order = {"COMPATIBILITÀ PRELIMINARE": 0, "DA VERIFICARE": 1, "BASSA COMPATIBILITÀ": 2}
        rows.sort(key=lambda row: (order[row["recommendation"]], row["client_name"].lower()))
        return rows

    def opportunity_dict(opportunity, include_details=False):
        result = {
            "id": opportunity.id, "title": opportunity.title, "source_type": opportunity.source_type,
            "source_name": opportunity.source_name, "source_url": opportunity.source_url,
            "external_ref": opportunity.external_ref, "contact_name": opportunity.contact_name,
            "contact_details": opportunity.contact_details, "zone": opportunity.zone,
            "address": opportunity.address, "price": opportunity.price, "sqm": opportunity.sqm,
            "property_type": opportunity.property_type, "state": opportunity.state,
            "availability": opportunity.availability, "documents_status": opportunity.documents_status,
            "planimetry_status": opportunity.planimetry_status, "analysis_status": opportunity.analysis_status,
            "data_reliability": opportunity.data_reliability, "status": opportunity.status,
            "risks": opportunity.risks, "potential": opportunity.potential, "notes": opportunity.notes,
            "decision": opportunity.decision, "decision_note": opportunity.decision_note,
            "rejection_reason": opportunity.rejection_reason,
            "last_checked_on": opportunity.last_checked_on.isoformat() if opportunity.last_checked_on else None,
            "linked_property_id": opportunity.linked_property_id, "version": opportunity.version,
            "archived_at": opportunity.archived_at.isoformat() if opportunity.archived_at else None,
            "created_by_user_id": opportunity.created_by_user_id,
            "created_at": opportunity.created_at.isoformat() if opportunity.created_at else None,
            "updated_at": opportunity.updated_at.isoformat() if opportunity.updated_at else None,
        }
        if include_details:
            result["possible_duplicates"] = possible_duplicates(opportunity)
            result["preliminary_matches"] = preliminary_matches(opportunity)
            revisions = OpportunityRevision.query.filter_by(opportunity_id=opportunity.id).order_by(OpportunityRevision.version.desc()).limit(20).all()
            result["revisions"] = [revision.to_dict() for revision in revisions]
        return result

    def apply_payload(opportunity, data):
        text_fields = {
            "title": 200, "source_name": 160, "external_ref": 160,
            "contact_name": 160, "contact_details": 500, "zone": 200, "address": 255,
            "property_type": 80, "state": 100, "availability": 80, "status": 50,
            "documents_status": 40, "planimetry_status": 40, "analysis_status": 50,
            "data_reliability": 40, "risks": 4000, "potential": 4000, "notes": 5000,
            "decision": 40, "decision_note": 4000, "rejection_reason": 4000,
        }
        for field, limit in text_fields.items():
            if field in data:
                setattr(opportunity, field, app_module.clean_text(data.get(field), limit))
        if "source_type" in data:
            opportunity.source_type = app_module.clean_text(data.get("source_type"), 60)
        if "source_url" in data:
            opportunity.source_url = app_module.clean_text(data.get("source_url"), 2000)
            opportunity.normalized_url = normalize_url(opportunity.source_url)
        for field in ("price", "sqm"):
            if field in data:
                value = data.get(field)
                if value in (None, ""):
                    setattr(opportunity, field, None)
                else:
                    try:
                        value = float(value)
                    except (TypeError, ValueError):
                        raise ValueError("Prezzo o metratura non validi.")
                    if not math.isfinite(value) or value <= 0:
                        raise ValueError("Prezzo e metratura devono essere maggiori di zero.")
                    setattr(opportunity, field, value)
        if "last_checked_on" in data:
            value = data.get("last_checked_on")
            try:
                opportunity.last_checked_on = date.fromisoformat(value) if value else None
            except (TypeError, ValueError):
                raise ValueError("Data ultimo controllo non valida.")
        if not opportunity.title or not opportunity.zone or opportunity.source_type not in SOURCE_TYPES:
            raise ValueError("Titolo, zona o tipo fonte non validi.")
        if opportunity.status not in STATUSES or opportunity.documents_status not in DOCUMENT_STATES or opportunity.planimetry_status not in PLAN_STATES:
            raise ValueError("Stato opportunità o documenti non valido.")
        if opportunity.analysis_status not in ANALYSIS_STATES or opportunity.decision not in DECISIONS or opportunity.data_reliability not in RELIABILITY_LEVELS:
            raise ValueError("Analisi, decisione o affidabilità non valida.")
        if opportunity.decision == "Non procedere" and not opportunity.rejection_reason:
            raise ValueError("Indicare il motivo per cui non si procede.")

    def exact_duplicate(opportunity):
        query = PropertyOpportunity.query.filter(PropertyOpportunity.id != opportunity.id)
        if opportunity.normalized_url:
            found = query.filter_by(normalized_url=opportunity.normalized_url).first()
            if found:
                return found
        if opportunity.external_ref and opportunity.source_name:
            for row in query.filter_by(external_ref=opportunity.external_ref).all():
                if row.source_name.lower() == opportunity.source_name.lower():
                    return row
        return None

    def record_revision(opportunity, actor, note):
        db.session.add(OpportunityRevision(
            opportunity_id=opportunity.id, version=opportunity.version,
            snapshot_json=json.dumps(opportunity_dict(opportunity), ensure_ascii=False),
            changed_by_user_id=actor.id,
            change_note=app_module.clean_text(note or "Opportunità aggiornata", 255),
        ))

    @app.get("/api/staff/opportunities")
    def opportunity_list():
        actor, denied = staff_user("opportunity_read")
        if denied:
            return denied
        query = PropertyOpportunity.query
        if request.args.get("include_archived") != "1":
            query = query.filter(PropertyOpportunity.archived_at.is_(None))
        status = app_module.clean_text(request.args.get("status"), 50)
        if status:
            query = query.filter_by(status=status)
        rows = query.order_by(PropertyOpportunity.updated_at.desc()).all()
        return jsonify(opportunities=[opportunity_dict(row) for row in rows])

    @app.get("/api/staff/opportunities/<int:opportunity_id>")
    def opportunity_detail(opportunity_id):
        actor, denied = staff_user("opportunity_read")
        if denied:
            return denied
        opportunity = db.session.get(PropertyOpportunity, opportunity_id)
        if not opportunity:
            return jsonify(error="Opportunità non trovata."), 404
        return jsonify(opportunity=opportunity_dict(opportunity, include_details=True))

    @app.post("/api/staff/opportunities")
    def opportunity_create():
        actor, denied = staff_user("opportunity_manage")
        if denied:
            return denied
        data = request.get_json(silent=True) or {}
        opportunity = PropertyOpportunity(
            title="", source_type="", zone="", created_by_user_id=actor.id,
            source_name="", source_url="", normalized_url="", external_ref="",
            property_type="Da definire", state="Da verificare", availability="Da verificare",
            documents_status="Da verificare", planimetry_status="Da verificare",
            analysis_status="Non iniziata", data_reliability="Da verificare",
            status="Nuova", decision="Da decidere",
        )
        try:
            apply_payload(opportunity, data)
        except ValueError as exc:
            return jsonify(error=str(exc)), 400
        duplicate = exact_duplicate(opportunity)
        if duplicate:
            return jsonify(error="Opportunità già presente.", duplicate_id=duplicate.id), 409
        db.session.add(opportunity)
        db.session.flush()
        record_revision(opportunity, actor, "Creazione opportunità")
        audit(actor, "opportunity_create", opportunity.id, f"source={opportunity.source_type}")
        db.session.commit()
        return jsonify(opportunity=opportunity_dict(opportunity, include_details=True)), 201

    @app.patch("/api/staff/opportunities/<int:opportunity_id>")
    def opportunity_update(opportunity_id):
        actor, denied = staff_user("opportunity_manage")
        if denied:
            return denied
        opportunity = db.session.get(PropertyOpportunity, opportunity_id)
        if not opportunity:
            return jsonify(error="Opportunità non trovata."), 404
        data = request.get_json(silent=True) or {}
        try:
            apply_payload(opportunity, data)
        except ValueError as exc:
            return jsonify(error=str(exc)), 400
        duplicate = exact_duplicate(opportunity)
        if duplicate:
            return jsonify(error="Il collegamento o riferimento appartiene a un’altra opportunità.", duplicate_id=duplicate.id), 409
        opportunity.version += 1
        opportunity.updated_at = datetime.now(timezone.utc)
        record_revision(opportunity, actor, data.get("change_note") or "Opportunità aggiornata")
        audit(actor, "opportunity_update", opportunity.id)
        db.session.commit()
        return jsonify(opportunity=opportunity_dict(opportunity, include_details=True))

    @app.post("/api/staff/opportunities/<int:opportunity_id>/promote")
    def opportunity_promote(opportunity_id):
        actor, denied = staff_user("opportunity_manage")
        if denied:
            return denied
        opportunity = db.session.get(PropertyOpportunity, opportunity_id)
        if not opportunity:
            return jsonify(error="Opportunità non trovata."), 404
        if opportunity.linked_property_id:
            return jsonify(error="Opportunità già inserita nella banca dati immobili.", property_id=opportunity.linked_property_id), 409
        missing = []
        if not opportunity.price:
            missing.append("prezzo")
        if not opportunity.sqm:
            missing.append("metratura")
        if opportunity.analysis_status != "Preliminare completata":
            missing.append("analisi preliminare")
        if opportunity.documents_status not in {"Parziali", "Completi"}:
            missing.append("documenti disponibili")
        if opportunity.decision != "Procedere" or not opportunity.decision_note:
            missing.append("decisione motivata")
        if missing:
            return jsonify(error="Prima di procedere completare: " + ", ".join(missing) + ".", missing=missing), 409
        source = f"{opportunity.source_type}: {opportunity.source_name or 'fonte registrata'}"[:100]
        prop = app_module.Property(
            ref=f"OPP-{opportunity.id:05d}", zone=opportunity.zone, price=opportunity.price,
            sqm=opportunity.sqm, beds=0, baths=0, state=opportunity.state, source=source,
            property_type=opportunity.property_type, address=opportunity.address,
            availability=opportunity.availability, known_constraints=opportunity.risks,
            transformation_status="Da verificare", data_reliability=opportunity.data_reliability,
            technical_verification="Verifica in corso",
            notes=("Origine: opportunità #" + str(opportunity.id) + ". " + opportunity.notes)[:5000],
        )
        db.session.add(prop)
        db.session.flush()
        property_ext = app.extensions.get("aplsai_property_profiles") or {}
        record_property_revision = property_ext.get("record_revision")
        if record_property_revision:
            record_property_revision(prop, actor, f"Inserimento da opportunità #{opportunity.id}")
        opportunity.linked_property_id = prop.id
        opportunity.version += 1
        opportunity.updated_at = datetime.now(timezone.utc)
        record_revision(opportunity, actor, "Inserita nella banca dati immobili")
        audit(actor, "opportunity_promote", opportunity.id, f"property={prop.id}")
        db.session.commit()
        return jsonify(opportunity=opportunity_dict(opportunity, include_details=True), property=prop.to_dict()), 201

    @app.patch("/api/staff/opportunities/<int:opportunity_id>/archive")
    def opportunity_archive(opportunity_id):
        actor, denied = staff_user("opportunity_manage")
        if denied:
            return denied
        opportunity = db.session.get(PropertyOpportunity, opportunity_id)
        if not opportunity:
            return jsonify(error="Opportunità non trovata."), 404
        data = request.get_json(silent=True) or {}
        if not isinstance(data.get("archived"), bool):
            return jsonify(error="Stato archivio non valido."), 400
        opportunity.archived_at = datetime.now(timezone.utc) if data["archived"] else None
        opportunity.version += 1
        opportunity.updated_at = datetime.now(timezone.utc)
        record_revision(opportunity, actor, "Opportunità archiviata" if data["archived"] else "Opportunità ripristinata")
        audit(actor, "opportunity_archive" if data["archived"] else "opportunity_restore", opportunity.id)
        db.session.commit()
        return jsonify(opportunity=opportunity_dict(opportunity, include_details=True))

    app.extensions["aplsai_opportunities"] = {
        "PropertyOpportunity": PropertyOpportunity, "OpportunityRevision": OpportunityRevision,
        "opportunity_dict": opportunity_dict,
    }
