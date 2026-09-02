from flask import jsonify, request, session
from werkzeug.security import check_password_hash, generate_password_hash

from .rbac import has_permission
from .document_security import init_document_security


def init_partner_access(app, app_module):
    if app.extensions.get("aplsai_partner_access"):
        return

    db = app_module.db

    class PartnerAssignment(db.Model):
        __tablename__ = "partner_assignment"
        id = db.Column(db.Integer, primary_key=True)
        partner_user_id = db.Column(db.Integer, db.ForeignKey("user.id"), nullable=False, index=True)
        client_id = db.Column(db.Integer, db.ForeignKey("user.id"), nullable=False, index=True)
        created_at = db.Column(db.DateTime(timezone=True), nullable=False, default=app_module.utcnow)
        __table_args__ = (db.UniqueConstraint("partner_user_id", "client_id", name="uq_partner_client"),)

        def to_dict(self):
            return {
                "id": self.id,
                "partner_user_id": self.partner_user_id,
                "client_id": self.client_id,
                "created_at": self.created_at.isoformat() if self.created_at else None,
            }

    with app.app_context():
        db.create_all()

    def audit(actor, action, object_id, detail=""):
        ext = app.extensions.get("aplsai_operations") or {}
        fn = ext.get("audit")
        if fn:
            fn(actor, action, "partner_assignment", object_id, detail)

    def admin_user():
        uid = session.get("uid")
        if not uid:
            return None, (jsonify(error="Non autenticato."), 401)
        u = db.session.get(app_module.User, uid)
        if not u:
            session.clear()
            return None, (jsonify(error="Sessione non valida."), 401)
        if getattr(u, "active", True) is False:
            session.clear()
            return None, (jsonify(error="Account disattivato."), 401)
        if not has_permission(u.role, "staff_manage"):
            return None, (jsonify(error="Permesso insufficiente."), 403)
        return u, None

    def partner_user():
        uid = session.get("uid")
        if not uid:
            return None
        u = db.session.get(app_module.User, uid)
        if not u or u.role != "partner" or getattr(u, "active", True) is False:
            session.clear()
            return None
        return u

    @app.post("/api/partner/login")
    def partner_login():
        data = request.get_json(silent=True) or {}
        email = app_module.clean_email(data.get("email"))
        password = data.get("password") or ""
        key = app_module.login_key("partner", email)
        if app_module.login_blocked(key):
            return jsonify(error="Troppi tentativi. Riprova tra qualche minuto."), 429
        u = app_module.User.query.filter_by(email=email, role="partner").first()
        if not u or getattr(u, "active", True) is False or not check_password_hash(u.password_hash, password):
            app_module.register_login_failure(key)
            return jsonify(error="Credenziali partner errate."), 401
        app_module.clear_login_failures(key)
        app_module.establish_session(u.id)
        return jsonify(ok=True, role="partner")

    @app.get("/api/partner/me")
    def partner_me():
        u = partner_user()
        if not u:
            return jsonify(error="Non autorizzato."), 401
        return jsonify(partner={"id": u.id, "name": u.name, "email": u.email})

    @app.get("/api/partner/cases")
    def partner_cases():
        u = partner_user()
        if not u or not has_permission(u.role, "assigned_case_read"):
            return jsonify(error="Non autorizzato."), 401
        assignments = PartnerAssignment.query.filter_by(partner_user_id=u.id).all()
        rows = []
        op_model = (app.extensions.get("aplsai_operations") or {}).get("ClientOperation")
        for assignment in assignments:
            client = app_module.client_obj(assignment.client_id)
            if not client:
                continue
            operation = op_model.query.filter_by(client_id=assignment.client_id).first() if op_model else None
            rows.append({
                "assignment": assignment.to_dict(),
                "client": {
                    "id": client.get("id"),
                    "name": client.get("name"),
                    "status": client.get("status"),
                    "zone": client.get("zone"),
                    "budget": client.get("budget"),
                    "timing": client.get("timing"),
                },
                "operation": operation.to_dict() if operation else None,
            })
        return jsonify(results=rows)

    @app.get("/api/partner/cases/<int:client_id>/documents")
    def partner_case_documents(client_id):
        u = partner_user()
        if not u or not has_permission(u.role, "assigned_document_read"):
            return jsonify(error="Non autorizzato."), 401
        assignment = PartnerAssignment.query.filter_by(partner_user_id=u.id, client_id=client_id).first()
        if not assignment:
            return jsonify(error="Pratica non assegnata."), 403
        docs = app_module.Document.query.filter_by(client_id=client_id).order_by(app_module.Document.created_at.desc()).all()
        return jsonify(documents=[d.to_dict() for d in docs])

    @app.get("/api/admin/partners")
    def admin_list_partners():
        actor, denied = admin_user()
        if denied:
            return denied
        rows = app_module.User.query.filter_by(role="partner").order_by(app_module.User.id.asc()).all()
        return jsonify(partners=[{
            "id": u.id,
            "name": u.name,
            "email": u.email,
            "active": bool(getattr(u, "active", True)),
            "assigned_client_ids": [a.client_id for a in PartnerAssignment.query.filter_by(partner_user_id=u.id).all()],
        } for u in rows])

    @app.post("/api/admin/partners")
    def admin_create_partner():
        actor, denied = admin_user()
        if denied:
            return denied
        data = request.get_json(silent=True) or {}
        name = app_module.clean_text(data.get("name"), 160)
        email = app_module.clean_email(data.get("email"))
        password = data.get("password") or ""
        try:
            client_id = int(data.get("client_id"))
        except (TypeError, ValueError):
            return jsonify(error="Una pratica valida è obbligatoria."), 400
        if not app_module.ClientProfile.query.filter_by(user_id=client_id).first():
            return jsonify(error="Pratica cliente non trovata."), 404
        if not name or not app_module.valid_email(email):
            return jsonify(error="Nome o email non validi."), 400
        if not app_module.strong_password(password):
            return jsonify(error="La password deve avere almeno 10 caratteri, con lettere e numeri."), 400
        if app_module.User.query.filter_by(email=email).first():
            return jsonify(error="Email già registrata."), 409
        partner = app_module.User(
            role="partner", name=name, email=email, phone="", active=True,
            password_hash=generate_password_hash(password, method="scrypt"),
        )
        db.session.add(partner)
        db.session.flush()
        assignment = PartnerAssignment(partner_user_id=partner.id, client_id=client_id)
        db.session.add(assignment)
        audit(actor, "partner_create_assign", partner.id, f"email={email}; client_id={client_id}")
        db.session.commit()
        return jsonify(partner={"id": partner.id, "name": partner.name, "email": partner.email, "active": True}, assignment=assignment.to_dict()), 201

    @app.post("/api/admin/partners/<int:partner_id>/assignments")
    def admin_assign_partner(partner_id):
        actor, denied = admin_user()
        if denied:
            return denied
        partner = db.session.get(app_module.User, partner_id)
        if not partner or partner.role != "partner":
            return jsonify(error="Partner non trovato."), 404
        data = request.get_json(silent=True) or {}
        try:
            client_id = int(data.get("client_id"))
        except (TypeError, ValueError):
            return jsonify(error="Pratica non valida."), 400
        if not app_module.ClientProfile.query.filter_by(user_id=client_id).first():
            return jsonify(error="Pratica cliente non trovata."), 404
        existing = PartnerAssignment.query.filter_by(partner_user_id=partner.id, client_id=client_id).first()
        if existing:
            return jsonify(assignment=existing.to_dict())
        assignment = PartnerAssignment(partner_user_id=partner.id, client_id=client_id)
        db.session.add(assignment)
        db.session.flush()
        audit(actor, "partner_assign", partner.id, f"client_id={client_id}")
        db.session.commit()
        return jsonify(assignment=assignment.to_dict()), 201

    app.extensions["aplsai_partner_access"] = {"installed": True, "PartnerAssignment": PartnerAssignment}
    init_document_security(app, app_module)
