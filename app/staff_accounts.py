from flask import jsonify, request, session
from werkzeug.security import check_password_hash, generate_password_hash

from . import User, db
from .rbac import has_permission
from .schema_migrations import ensure_user_active_column


# The schema migration must run before create_app() touches the User table.
ensure_user_active_column()
if not hasattr(User, "active"):
    User.active = db.Column(db.Boolean, nullable=False, default=True, server_default=db.true())


def init_staff_accounts(app, app_module):
    if app.extensions.get("aplsai_staff_accounts"):
        return

    dbx = app_module.db

    @app.before_request
    def reject_inactive_session():
        uid = session.get("uid")
        if not uid:
            return None
        u = dbx.session.get(app_module.User, uid)
        if not u:
            session.clear()
            return jsonify(error="Sessione non valida."), 401
        if getattr(u, "active", True) is False:
            session.clear()
            return jsonify(error="Account disattivato."), 401
        return None

    def authorization_result():
        uid = session.get("uid")
        if not uid:
            return None, (jsonify(error="Non autenticato."), 401)
        u = dbx.session.get(app_module.User, uid)
        if not u:
            session.clear()
            return None, (jsonify(error="Sessione non valida."), 401)
        if getattr(u, "active", True) is False:
            session.clear()
            return None, (jsonify(error="Account disattivato."), 401)
        if not has_permission(u.role, "staff_manage"):
            return None, (jsonify(error="Permesso insufficiente."), 403)
        return u, None

    def audit(actor, action, object_id, detail=""):
        ext = app.extensions.get("aplsai_operations") or {}
        fn = ext.get("audit")
        if fn:
            fn(actor, action, "staff_account", object_id, detail)

    def authenticated_staff():
        uid = session.get("uid")
        if not uid:
            return None, (jsonify(error="Non autenticato."), 401)
        u = dbx.session.get(app_module.User, uid)
        if not u or u.role not in {"staff", "operator"}:
            session.clear()
            return None, (jsonify(error="Sessione staff non valida."), 401)
        if getattr(u, "active", True) is False:
            session.clear()
            return None, (jsonify(error="Account disattivato."), 401)
        return u, None

    @app.get("/api/staff/me")
    def staff_me():
        u, denied = authenticated_staff()
        if denied:
            return denied
        return jsonify(staff={
            "id": u.id,
            "name": u.name,
            "email": u.email,
            "role": "admin" if u.role == "staff" else "operator",
        })

    @app.post("/api/staff/password")
    def change_staff_password():
        u, denied = authenticated_staff()
        if denied:
            return denied
        d = request.get_json(silent=True) or {}
        current_password = d.get("current_password") or ""
        new_password = d.get("new_password") or ""
        if not check_password_hash(u.password_hash, current_password):
            return jsonify(error="Password attuale errata."), 401
        if not app_module.strong_password(new_password):
            return jsonify(error="La nuova password deve avere almeno 10 caratteri, con lettere e numeri."), 400
        if check_password_hash(u.password_hash, new_password):
            return jsonify(error="La nuova password deve essere diversa da quella attuale."), 400
        u.password_hash = generate_password_hash(new_password, method="scrypt")
        audit(u, "staff_password_change", u.id)
        dbx.session.commit()
        return jsonify(ok=True)

    @app.get("/api/admin/operators")
    def list_operators():
        u, denied = authorization_result()
        if denied:
            return denied
        rows = app_module.User.query.filter_by(role="operator").order_by(app_module.User.id.asc()).all()
        return jsonify(operators=[{
            "id": x.id,
            "name": x.name,
            "email": x.email,
            "active": bool(x.active),
        } for x in rows])

    @app.post("/api/admin/operators")
    def create_operator():
        u, denied = authorization_result()
        if denied:
            return denied
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
        op = app_module.User(
            role="operator",
            name=name,
            email=email,
            phone="",
            active=True,
            password_hash=generate_password_hash(password, method="scrypt"),
        )
        dbx.session.add(op)
        dbx.session.flush()
        audit(u, "operator_create", op.id, f"email={email}")
        dbx.session.commit()
        return jsonify(operator={
            "id": op.id,
            "name": op.name,
            "email": op.email,
            "active": True,
        }), 201

    @app.patch("/api/admin/operators/<int:operator_id>/active")
    def set_operator_active(operator_id):
        actor, denied = authorization_result()
        if denied:
            return denied
        d = request.get_json(silent=True) or {}
        if not isinstance(d.get("active"), bool):
            return jsonify(error="Stato active non valido."), 400
        op = dbx.session.get(app_module.User, operator_id)
        if not op or op.role != "operator":
            return jsonify(error="Operatore non trovato."), 404
        new_state = d["active"]
        if bool(op.active) == new_state:
            return jsonify(operator={
                "id": op.id, "name": op.name, "email": op.email, "active": bool(op.active)
            })
        op.active = new_state
        audit(
            actor,
            "operator_activate" if new_state else "operator_deactivate",
            op.id,
            f"email={op.email}; active={str(new_state).lower()}",
        )
        dbx.session.commit()
        return jsonify(operator={
            "id": op.id, "name": op.name, "email": op.email, "active": bool(op.active)
        })

    app.extensions["aplsai_staff_accounts"] = {"installed": True}
