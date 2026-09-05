from datetime import datetime, timezone

from flask import jsonify, request, session

from .rbac import has_permission
from .schema_migrations import ensure_client_classification_columns


# Run before create_app() calls db.create_all() so an existing database is
# upgraded before the model queries the new columns.
ensure_client_classification_columns()


def init_client_classification(app, app_module):
    if app.extensions.get("aplsai_client_classification"):
        return

    def admin_user():
        uid = session.get("uid")
        actor = app_module.db.session.get(app_module.User, uid) if uid else None
        if not actor:
            return None, (jsonify(error="Non autenticato."), 401)
        if getattr(actor, "active", True) is False:
            session.clear()
            return None, (jsonify(error="Account disattivato."), 401)
        if not has_permission(actor.role, "staff_manage"):
            return None, (jsonify(error="Permesso insufficiente."), 403)
        return actor, None

    @app.patch("/api/admin/clients/<int:client_id>/classification")
    def update_client_classification(client_id):
        actor, denied = admin_user()
        if denied:
            return denied

        profile = app_module.ClientProfile.query.filter_by(user_id=client_id).first()
        client = app_module.db.session.get(app_module.User, client_id)
        if not profile or not client or client.role != "client":
            return jsonify(error="Cliente non trovato."), 404

        data = request.get_json(silent=True) or {}
        if "is_test" in data and not isinstance(data["is_test"], bool):
            return jsonify(error="Classificazione non valida."), 400
        if "archived" in data and not isinstance(data["archived"], bool):
            return jsonify(error="Stato archivio non valido."), 400

        if "is_test" in data:
            profile.is_test = data["is_test"]
        if "archived" in data:
            profile.archived_at = datetime.now(timezone.utc) if data["archived"] else None

        extensions = app.extensions.get("aplsai_operations") or {}
        audit = extensions.get("audit")
        if audit:
            audit(
                actor,
                "client_classification_update",
                "client",
                client_id,
                f"is_test={str(bool(profile.is_test)).lower()}; "
                f"archived={str(bool(profile.archived_at)).lower()}",
            )
        app_module.db.session.commit()
        return jsonify(client=app_module.client_obj(client_id))

    @app.delete("/api/admin/clients/<int:client_id>/test-data")
    def delete_test_client(client_id):
        actor, denied = admin_user()
        if denied:
            return denied

        data = request.get_json(silent=True) or {}
        if data.get("confirm") != "ELIMINA":
            return jsonify(error="Conferma eliminazione non valida."), 400

        profile = app_module.ClientProfile.query.filter_by(user_id=client_id).first()
        client = app_module.db.session.get(app_module.User, client_id)
        if not profile or not client or client.role != "client":
            return jsonify(error="Cliente non trovato."), 404
        if not bool(profile.is_test):
            return jsonify(error="Un cliente reale non può essere eliminato da questa funzione."), 409

        operations_ext = app.extensions.get("aplsai_operations") or {}
        Operation = operations_ext.get("ClientOperation")
        Audit = operations_ext.get("AuditEvent")
        partner_ext = app.extensions.get("aplsai_partner_access") or {}
        Assignment = partner_ext.get("PartnerAssignment")

        if Assignment is not None:
            Assignment.query.filter_by(client_id=client_id).delete(synchronize_session=False)
        if Operation is not None:
            Operation.query.filter_by(client_id=client_id).delete(synchronize_session=False)
        app_module.Deal.query.filter_by(client_id=client_id).delete(synchronize_session=False)
        app_module.Referral.query.filter_by(owner_id=client_id).delete(synchronize_session=False)
        app_module.Document.query.filter_by(client_id=client_id).delete(synchronize_session=False)
        app_module.Update.query.filter_by(client_id=client_id).delete(synchronize_session=False)
        if Audit is not None:
            Audit.query.filter_by(actor_user_id=client_id).update(
                {Audit.actor_user_id: None}, synchronize_session=False
            )

        audit = operations_ext.get("audit")
        if audit:
            audit(actor, "test_client_delete", "client", client_id, "Dati di prova eliminati")
        app_module.db.session.delete(profile)
        app_module.db.session.delete(client)
        app_module.db.session.commit()
        return jsonify(ok=True, deleted_client_id=client_id)

    app.extensions["aplsai_client_classification"] = {"installed": True}
