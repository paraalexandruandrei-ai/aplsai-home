from datetime import datetime, timezone
from flask import jsonify, request, session
from .rbac import has_permission
from .rbac_runtime import install_runtime_rbac


FINANCIAL_STATES = {
    "da_verificare", "mutuo_da_richiedere", "pre_delibera",
    "mutuo_deliberato", "capitale_dichiarato", "capitale_verificato",
}
PHASES = {
    "Nuovo", "Profilo completo", "Da qualificare", "Ricerca attiva",
    "Opportunità individuata", "Verifica", "Proposta", "Interesse confermato",
    "Definizione", "Contrattualizzazione", "In lavorazione", "Chiuso",
    "In pausa", "Bloccato", "Non idoneo al momento",
}


def utcnow():
    return datetime.now(timezone.utc)


def init_operations(app, app_module):
    db = app_module.db

    class ClientOperation(db.Model):
        __tablename__ = "client_operation"
        id = db.Column(db.Integer, primary_key=True)
        client_id = db.Column(db.Integer, db.ForeignKey("user.id"), unique=True, nullable=False, index=True)
        phase = db.Column(db.String(80), nullable=False, default="Da qualificare")
        financial_state = db.Column(db.String(40), nullable=False, default="da_verificare")
        financial_verified_at = db.Column(db.DateTime(timezone=True))
        next_action = db.Column(db.String(255), nullable=False, default="Qualificare la pratica")
        next_action_due_at = db.Column(db.DateTime(timezone=True))
        assigned_to = db.Column(db.String(160), default="")
        blocked_reason = db.Column(db.String(500), default="")
        updated_at = db.Column(db.DateTime(timezone=True), nullable=False, default=utcnow, onupdate=utcnow)

        def to_dict(self):
            return {
                "client_id": self.client_id,
                "phase": self.phase,
                "financial_state": self.financial_state,
                "financial_verified_at": self.financial_verified_at.isoformat() if self.financial_verified_at else None,
                "next_action": self.next_action,
                "next_action_due_at": self.next_action_due_at.isoformat() if self.next_action_due_at else None,
                "assigned_to": self.assigned_to,
                "blocked_reason": self.blocked_reason,
                "updated_at": self.updated_at.isoformat() if self.updated_at else None,
            }

    class AuditEvent(db.Model):
        __tablename__ = "audit_event"
        id = db.Column(db.Integer, primary_key=True)
        actor_user_id = db.Column(db.Integer, db.ForeignKey("user.id"), index=True)
        action = db.Column(db.String(120), nullable=False, index=True)
        object_type = db.Column(db.String(80), nullable=False)
        object_id = db.Column(db.String(80), nullable=False)
        outcome = db.Column(db.String(30), nullable=False, default="ok")
        detail = db.Column(db.String(500), default="")
        created_at = db.Column(db.DateTime(timezone=True), nullable=False, default=utcnow, index=True)

        def to_dict(self):
            return {
                "id": self.id,
                "actor_user_id": self.actor_user_id,
                "action": self.action,
                "object_type": self.object_type,
                "object_id": self.object_id,
                "outcome": self.outcome,
                "detail": self.detail,
                "created_at": self.created_at.isoformat(),
            }

    with app.app_context():
        db.create_all()

    # Bridge temporaneo: mantiene staff=Admin e abilita Operator solo sulle API
    # esplicitamente autorizzate dalla matrice RBAC.
    install_runtime_rbac(app, app_module)

    def permission_user(permission):
        uid = session.get("uid")
        if not uid:
            return None
        u = db.session.get(app_module.User, uid)
        if not u or not has_permission(u.role, permission):
            return None
        return u

    def parse_iso_datetime(value):
        if not value:
            return None
        if not isinstance(value, str) or len(value) > 40:
            raise ValueError("data non valida")
        dt = datetime.fromisoformat(value.replace("Z", "+00:00"))
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=timezone.utc)
        return dt.astimezone(timezone.utc)

    def audit(actor, action, object_type, object_id, detail="", outcome="ok"):
        db.session.add(AuditEvent(
            actor_user_id=actor.id if actor else None,
            action=action,
            object_type=object_type,
            object_id=str(object_id),
            detail=(detail or "")[:500],
            outcome=outcome,
        ))

    @app.get("/api/staff/operations")
    def staff_operations():
        u = permission_user("client_read_all")
        if not u:
            return jsonify(error="Non autorizzato."), 401
        rows = []
        for cp in app_module.ClientProfile.query.all():
            op = ClientOperation.query.filter_by(client_id=cp.user_id).first()
            if not op:
                op = ClientOperation(client_id=cp.user_id)
                db.session.add(op)
                db.session.flush()
            rows.append({"client": app_module.client_obj(cp.user_id), "operation": op.to_dict()})
        db.session.commit()
        return jsonify(results=rows)

    @app.post("/api/staff/client/<int:client_id>/operation")
    def update_client_operation(client_id):
        u = permission_user("client_update_operation")
        if not u:
            return jsonify(error="Non autorizzato."), 401
        if not app_module.ClientProfile.query.filter_by(user_id=client_id).first():
            return jsonify(error="Cliente non trovato."), 404

        data = request.get_json(silent=True) or {}
        op = ClientOperation.query.filter_by(client_id=client_id).first()
        if not op:
            op = ClientOperation(client_id=client_id)
            db.session.add(op)

        phase = data.get("phase", op.phase)
        fs = data.get("financial_state", op.financial_state)
        next_action = str(data.get("next_action", op.next_action) or "").strip()[:255]
        assigned = str(data.get("assigned_to", op.assigned_to) or "").strip()[:160]
        blocked = str(data.get("blocked_reason", op.blocked_reason) or "").strip()[:500]

        if phase not in PHASES:
            return jsonify(error="Fase operativa non valida."), 400
        if fs not in FINANCIAL_STATES:
            return jsonify(error="Stato finanziario non valido."), 400
        if not next_action and phase not in {"Chiuso", "Non idoneo al momento"}:
            return jsonify(error="La prossima azione è obbligatoria per una pratica attiva."), 400

        try:
            due = parse_iso_datetime(data.get("next_action_due_at")) if "next_action_due_at" in data else op.next_action_due_at
        except (ValueError, TypeError):
            return jsonify(error="Scadenza prossima azione non valida."), 400

        prev = op.financial_state
        op.phase = phase
        op.financial_state = fs
        op.next_action = next_action
        op.next_action_due_at = due
        op.assigned_to = assigned
        op.blocked_reason = blocked
        op.updated_at = utcnow()
        if fs != prev and fs in {"capitale_verificato", "mutuo_deliberato", "pre_delibera"}:
            op.financial_verified_at = utcnow()

        audit(u, "client_operation_update", "client", client_id, f"phase={phase}; financial_state={fs}")
        db.session.commit()
        return jsonify(operation=op.to_dict())

    @app.after_request
    def audit_staff_business_actions(response):
        if response.status_code >= 400 or request.method != "POST":
            return response

        path = request.path
        route_permissions = {
            "/api/staff/properties": "property_create",
            "/api/staff/proposals": "proposal_create",
            "/api/staff/documents": "document_share",
        }
        permission = route_permissions.get(path)
        if not permission:
            return response

        u = permission_user(permission)
        if not u:
            return response

        action = None
        obj_type = "system"
        obj_id = "-"
        detail = ""
        try:
            payload = request.get_json(silent=True) or {}
            if path == "/api/staff/properties":
                action = "property_create"
                obj_type = "property"
                detail = f"ref={str(payload.get('ref') or '')[:120]}"
            elif path == "/api/staff/proposals":
                action = "proposal_create"
                obj_type = "deal"
                obj_id = str(payload.get("client_id") or "-")
                detail = f"property_id={payload.get('property_id') or '-'}"
            elif path == "/api/staff/documents":
                action = "document_share"
                obj_type = "document"
                obj_id = str(payload.get("client_id") or "-")
                detail = f"title={str(payload.get('title') or '')[:180]}"

            if action:
                audit(u, action, obj_type, obj_id, detail)
                db.session.commit()
        except Exception:
            db.session.rollback()
        return response

    @app.get("/api/staff/audit")
    def staff_audit():
        u = permission_user("audit_read")
        if not u:
            return jsonify(error="Non autorizzato."), 401
        try:
            limit = max(1, min(200, int(request.args.get("limit", "100"))))
        except ValueError:
            limit = 100
        events = AuditEvent.query.order_by(AuditEvent.created_at.desc()).limit(limit).all()
        return jsonify(events=[e.to_dict() for e in events])

    app.extensions["aplsai_operations"] = {
        "ClientOperation": ClientOperation,
        "AuditEvent": AuditEvent,
        "audit": audit,
    }
