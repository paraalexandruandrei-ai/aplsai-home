import json
from datetime import datetime, timezone

from flask import jsonify, request, session

from . import Property, db
from .rbac import has_permission
from .schema_migrations import ensure_property_profile_columns


ensure_property_profile_columns()


PROPERTY_TYPES = {
    "Da definire", "Appartamento", "Villa", "Casa indipendente",
    "Terreno", "Fabbricato", "Locale da trasformare", "Altro",
}
RELIABILITY_LEVELS = {"Da verificare", "Dichiarato", "Documentato", "Verificato"}
VERIFICATION_STATES = {"Da verificare", "Verifica in corso", "Verificato", "Criticità rilevate"}
TRANSFORMATION_STATES = {"Da verificare", "Verifica in corso", "Trasformabile", "Parzialmente trasformabile", "Non trasformabile"}
AVAILABILITY_STATES = {"Da verificare", "Disponibile", "Occupato", "In trattativa", "Non disponibile"}


def _optional_number(data, key, cast=float):
    if key not in data or data[key] in (None, ""):
        return None
    return cast(data[key])


def init_property_profiles(app, app_module):
    if app.extensions.get("aplsai_property_profiles"):
        return

    class PropertyRevision(db.Model):
        __tablename__ = "property_revision"
        id = db.Column(db.Integer, primary_key=True)
        property_id = db.Column(db.Integer, db.ForeignKey("property.id"), nullable=False, index=True)
        version = db.Column(db.Integer, nullable=False)
        snapshot_json = db.Column(db.Text, nullable=False)
        changed_by_user_id = db.Column(db.Integer, db.ForeignKey("user.id"), nullable=False)
        change_note = db.Column(db.String(255), nullable=False, default="Aggiornamento scheda")
        created_at = db.Column(db.DateTime(timezone=True), nullable=False, default=app_module.utcnow)
        __table_args__ = (db.UniqueConstraint("property_id", "version", name="uq_property_revision_version"),)

        def to_dict(self):
            return {
                "id": self.id, "property_id": self.property_id, "version": self.version,
                "snapshot": json.loads(self.snapshot_json),
                "changed_by_user_id": self.changed_by_user_id,
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

    def audit(actor, action, property_id, detail=""):
        fn = (app.extensions.get("aplsai_operations") or {}).get("audit")
        if fn:
            fn(actor, action, "property", property_id, detail)

    def apply_advanced_payload(prop, data):
        text_fields = {
            "property_type": 80, "address": 255, "floor": 40, "exposure": 100,
            "outdoor_spaces": 255, "parking": 160, "energy_class": 20,
            "systems_status": 120, "availability": 80, "known_constraints": 3000,
            "transformation_status": 80, "planned_works": 3000,
            "data_reliability": 40, "technical_verification": 80, "notes": 5000,
        }
        for field, limit in text_fields.items():
            if field in data:
                setattr(prop, field, app_module.clean_text(data.get(field), limit))

        if "elevator" in data:
            if data["elevator"] not in {True, False, None}:
                raise ValueError("Ascensore non valido.")
            prop.elevator = data["elevator"]

        for field, cast in {
            "renovation_cost_min": float, "renovation_cost_max": float,
            "renovation_months_min": int, "renovation_months_max": int,
        }.items():
            if field in data:
                value = _optional_number(data, field, cast)
                if value is not None and value < 0:
                    raise ValueError("Costi e tempi non possono essere negativi.")
                setattr(prop, field, value)

        if prop.property_type not in PROPERTY_TYPES:
            raise ValueError("Tipologia immobile non valida.")
        if prop.data_reliability not in RELIABILITY_LEVELS:
            raise ValueError("Affidabilità dati non valida.")
        if prop.technical_verification not in VERIFICATION_STATES:
            raise ValueError("Verifica tecnica non valida.")
        if prop.transformation_status not in TRANSFORMATION_STATES:
            raise ValueError("Stato trasformabilità non valido.")
        if prop.availability not in AVAILABILITY_STATES:
            raise ValueError("Disponibilità non valida.")
        if (
            prop.renovation_cost_min is not None and prop.renovation_cost_max is not None
            and prop.renovation_cost_min > prop.renovation_cost_max
        ):
            raise ValueError("Il costo minimo non può superare il costo massimo.")
        if (
            prop.renovation_months_min is not None and prop.renovation_months_max is not None
            and prop.renovation_months_min > prop.renovation_months_max
        ):
            raise ValueError("Il tempo minimo non può superare il tempo massimo.")

    def record_revision(prop, actor, note):
        latest = db.session.query(db.func.max(PropertyRevision.version)).filter_by(
            property_id=prop.id
        ).scalar() or 0
        db.session.add(PropertyRevision(
            property_id=prop.id,
            version=latest + 1,
            snapshot_json=json.dumps(prop.to_dict(), ensure_ascii=False),
            changed_by_user_id=actor.id,
            change_note=app_module.clean_text(note or "Aggiornamento scheda", 255),
        ))

    @app.get("/api/staff/properties/<int:property_id>")
    def property_detail(property_id):
        actor, denied = staff_user("dashboard_full")
        if denied:
            return denied
        prop = db.session.get(app_module.Property, property_id)
        if not prop:
            return jsonify(error="Immobile non trovato."), 404
        revisions = PropertyRevision.query.filter_by(property_id=property_id).order_by(
            PropertyRevision.version.desc()
        ).limit(20).all()
        return jsonify(property=prop.to_dict(), revisions=[row.to_dict() for row in revisions])

    @app.patch("/api/staff/properties/<int:property_id>")
    def property_update(property_id):
        actor, denied = staff_user("property_update")
        if denied:
            return denied
        prop = db.session.get(app_module.Property, property_id)
        if not prop:
            return jsonify(error="Immobile non trovato."), 404
        data = request.get_json(silent=True) or {}

        try:
            ref = app_module.clean_text(data.get("ref", prop.ref), 120)
            zone = app_module.clean_text(data.get("zone", prop.zone), 200)
            state = app_module.clean_text(data.get("state", prop.state), 100)
            source = app_module.clean_text(data.get("source", prop.source), 100)
            price = float(data.get("price", prop.price))
            sqm = float(data.get("sqm", prop.sqm))
            beds = int(data.get("beds", prop.beds) or 0)
            baths = int(data.get("baths", prop.baths) or 0)
            if not ref or not zone or price <= 0 or sqm <= 0 or not (0 <= beds <= 30) or not (0 <= baths <= 30):
                raise ValueError("Dati immobile incompleti o non validi.")
            prop.ref, prop.zone, prop.state, prop.source = ref, zone, state, source
            prop.price, prop.sqm, prop.beds, prop.baths = price, sqm, beds, baths
            apply_advanced_payload(prop, data)
        except (TypeError, ValueError) as exc:
            return jsonify(error=str(exc) or "Dati immobile non validi."), 400

        prop.updated_at = datetime.now(timezone.utc)
        record_revision(prop, actor, data.get("change_note") or "Scheda immobile aggiornata")
        audit(actor, "property_update", prop.id, f"ref={prop.ref}")
        db.session.commit()
        return jsonify(property=prop.to_dict())

    @app.patch("/api/staff/properties/<int:property_id>/archive")
    def property_archive(property_id):
        actor, denied = staff_user("property_update")
        if denied:
            return denied
        data = request.get_json(silent=True) or {}
        if not isinstance(data.get("archived"), bool):
            return jsonify(error="Stato archivio non valido."), 400
        prop = db.session.get(app_module.Property, property_id)
        if not prop:
            return jsonify(error="Immobile non trovato."), 404
        prop.archived_at = datetime.now(timezone.utc) if data["archived"] else None
        prop.updated_at = datetime.now(timezone.utc)
        record_revision(prop, actor, "Immobile archiviato" if data["archived"] else "Immobile ripristinato")
        audit(actor, "property_archive" if data["archived"] else "property_restore", prop.id)
        db.session.commit()
        return jsonify(property=prop.to_dict())

    app.extensions["aplsai_property_profiles"] = {
        "PropertyRevision": PropertyRevision,
        "apply_payload": apply_advanced_payload,
        "record_revision": record_revision,
    }
