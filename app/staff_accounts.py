from flask import jsonify, request, session
from werkzeug.security import generate_password_hash

from .rbac import has_permission


def init_staff_accounts(app, app_module):
    if app.extensions.get("aplsai_staff_accounts"):
        return

    db = app_module.db

    def admin_user():
        uid = session.get("uid")
        if not uid:
            return None
        u = db.session.get(app_module.User, uid)
        if not u or not has_permission(u.role, "staff_manage"):
            return None
        return u

    def audit(actor, action, object_id, detail=""):
        ext = app.extensions.get("aplsai_operations") or {}
        fn = ext.get("audit")
        if fn:
            fn(actor, action, "staff_account", object_id, detail)

    @app.get("/api/admin/operators")
    def list_operators():
        u = admin_user()
        if not u:
            return jsonify(error="Permesso insufficiente."), 403
        rows = app_module.User.query.filter_by(role="operator").order_by(app_module.User.id.asc()).all()
        return jsonify(operators=[{
            "id": x.id,
            "name": x.name,
            "email": x.email,
            "active": bool(getattr(x, "active", True)),
        } for x in rows])

    @app.post("/api/admin/operators")
    def create_operator():
        u = admin_user()
        if not u:
            return jsonify(error="Permesso insufficiente."), 403
        d = request.get_json(silent=True) or {}
        name = app_module.clean_text(d.get("name"), 160)
        email = app_module.clean_email(d.get("email"))
        password = d.get("password") or ""
        if not name or not app_module.valid_email(email):
            return jsonify(error="Nome o email non validi."), 400
        if not app_module.strong_password(password):
            return jsonify(error="La password deve avere almeno 10 caratteri, con lettere e numeri."), 400
        if app_module.User.query.filter_by(email=email).first():
            return jsonify(error="Email già registrata."), 409
        op = app_module.User(role="operator", name=name, email=email, phone="",
                             password_hash=generate_password_hash(password, method="scrypt"))
        db.session.add(op)
        db.session.flush()
        audit(u, "operator_create", op.id, f"email={email}")
        db.session.commit()
        return jsonify(operator={"id":op.id,"name":op.name,"email":op.email,"active":True}), 201

    app.extensions["aplsai_staff_accounts"] = {"installed": True}
