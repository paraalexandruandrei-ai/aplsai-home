import os
from urllib.parse import urlparse

from flask import jsonify, request, session

from .rbac import has_permission


def init_document_security(app, app_module):
    """Protect document references exposed to external Partner accounts.

    Partner document lists never expose raw storage URLs. A dedicated access
    endpoint re-checks both role permission and case assignment. Until a real
    private object-storage provider is configured, external/public links are
    refused instead of silently treating them as private files.
    """
    if app.extensions.get("aplsai_document_security"):
        return

    db = app_module.db

    def trusted_hosts():
        raw = os.environ.get("PRIVATE_DOCUMENT_HOSTS", "")
        return {x.strip().lower() for x in raw.split(",") if x.strip()}

    def partner_user():
        uid = session.get("uid")
        if not uid:
            return None
        u = db.session.get(app_module.User, uid)
        if not u or u.role != "partner" or getattr(u, "active", True) is False:
            session.clear()
            return None
        return u

    def assigned(partner_id, client_id):
        assignment_model = (app.extensions.get("aplsai_partner_access") or {}).get("PartnerAssignment")
        if not assignment_model:
            return False
        return assignment_model.query.filter_by(
            partner_user_id=partner_id,
            client_id=client_id,
        ).first() is not None

    def audit(actor, action, object_id, detail="", outcome="ok"):
        ext = app.extensions.get("aplsai_operations") or {}
        fn = ext.get("audit")
        if fn:
            fn(actor, action, "document", object_id, detail, outcome)
            db.session.commit()

    @app.after_request
    def redact_partner_document_urls(response):
        if not (
            request.method == "GET"
            and request.path.startswith("/api/partner/cases/")
            and request.path.endswith("/documents")
            and response.status_code == 200
            and response.is_json
        ):
            return response
        payload = response.get_json(silent=True) or {}
        docs = payload.get("documents")
        if not isinstance(docs, list):
            return response
        redacted = []
        for d in docs:
            if not isinstance(d, dict):
                continue
            item = {k: v for k, v in d.items() if k != "url"}
            doc_id = item.get("id")
            item["access_url"] = f"/api/partner/documents/{doc_id}" if doc_id is not None else None
            redacted.append(item)
        payload["documents"] = redacted
        response.set_data(app.json.dumps(payload))
        response.headers["Content-Type"] = "application/json"
        response.headers["Cache-Control"] = "no-store"
        return response

    @app.get("/api/partner/documents/<int:document_id>")
    def partner_document_access(document_id):
        u = partner_user()
        if not u or not has_permission(u.role, "assigned_document_read"):
            return jsonify(error="Non autorizzato."), 401

        doc = db.session.get(app_module.Document, document_id)
        if not doc:
            return jsonify(error="Documento non trovato."), 404
        if not assigned(u.id, doc.client_id):
            audit(u, "partner_document_denied", document_id, f"client_id={doc.client_id}", "denied")
            return jsonify(error="Documento non assegnato."), 403

        url = (getattr(doc, "url", "") or "").strip()
        if not url:
            return jsonify(error="Documento non ancora disponibile nello storage privato."), 409
        host = (urlparse(url).hostname or "").lower()
        allowed = trusted_hosts()
        if not allowed or host not in allowed:
            audit(u, "partner_document_storage_block", document_id, f"host={host}", "denied")
            return jsonify(error="Documento da migrare nello storage privato prima della condivisione."), 409

        audit(u, "partner_document_access", document_id, f"client_id={doc.client_id}")
        return jsonify(document={
            "id": doc.id,
            "client_id": doc.client_id,
            "title": doc.title,
            "url": url,
        })

    app.extensions["aplsai_document_security"] = {"installed": True}
