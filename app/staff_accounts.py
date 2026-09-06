import json

from flask import jsonify, request, session
from werkzeug.security import check_password_hash, generate_password_hash

from . import User, db
from .rbac import has_permission
from .schema_migrations import ensure_operator_access_columns, ensure_user_active_column


# The schema migration must run before create_app() touches the User table.
ensure_user_active_column()
ensure_operator_access_columns()
if not hasattr(User, "active"):
    User.active = db.Column(db.Boolean, nullable=False, default=True, server_default=db.true())
if not hasattr(User, "permissions_json"):
    User.permissions_json = db.Column(db.Text, nullable=False, default="[]", server_default="[]")
if not hasattr(User, "must_change_password"):
    User.must_change_password = db.Column(db.Boolean, nullable=False, default=False, server_default=db.false())


ACCESS_AREAS = [
    {"id": "today", "label": "Oggi e panoramica", "permissions": ["dashboard_full"]},
    {"id": "tasks", "label": "Incarichi assegnati", "permissions": ["task_read"]},
    {"id": "clients", "label": "Clienti", "permissions": ["client_read_all", "client_update_operation"]},
    {"id": "opportunities", "label": "Opportunità", "permissions": ["opportunity_read", "opportunity_manage"]},
    {"id": "outreach", "label": "Contatti immobili", "permissions": ["outreach_read", "outreach_manage"]},
    {"id": "properties", "label": "Immobili", "permissions": ["property_create", "property_update"]},
    {"id": "scenarios", "label": "Scenari", "permissions": ["scenario_manage"]},
    {"id": "quotes", "label": "Preventivi", "permissions": ["quote_read", "quote_manage"]},
    {"id": "procurements", "label": "Confronto offerte", "permissions": ["procurement_read", "procurement_manage"]},
    {"id": "contracts", "label": "Contratti fornitori", "permissions": ["supplier_contract_read", "supplier_contract_manage"]},
    {"id": "feasibility", "label": "Fattibilità", "permissions": ["feasibility_manage"]},
    {"id": "investors", "label": "Investitori", "permissions": ["investor_read", "investor_manage"]},
    {"id": "cashflow", "label": "Cassa", "permissions": ["cashflow_manage", "cash_control_read", "cash_control_manage"]},
    {"id": "portfolio", "label": "Portafoglio", "permissions": ["portfolio_read"]},
    {"id": "capacity", "label": "Capacità", "permissions": ["capacity_read", "capacity_manage"]},
    {"id": "partners", "label": "Rete partner", "permissions": ["partner_registry_read", "partner_registry_manage"]},
    {"id": "matching", "label": "Matching", "permissions": ["matching_run"]},
    {"id": "launch", "label": "Avvio operazione", "permissions": ["launch_read", "launch_manage"]},
    {"id": "worksites", "label": "Cantieri", "permissions": ["worksite_read", "worksite_manage"]},
    {"id": "deliveries", "label": "Consegne", "permissions": ["delivery_read", "delivery_manage"]},
    {"id": "deals", "label": "Trattative", "permissions": ["transaction_read", "transaction_manage"]},
    {"id": "documents", "label": "Documenti", "permissions": ["document_share"]},
    {"id": "protocol", "label": "Regole staff", "permissions": ["protocol_read"]},
    {"id": "pilot", "label": "Collaudo", "permissions": ["pilot_read", "pilot_manage"]},
]
ASSIGNABLE_PERMISSIONS = {p for area in ACCESS_AREAS for p in area["permissions"]}


def operator_permissions(user):
    if not user or user.role != "operator":
        return set()
    try:
        values = json.loads(user.permissions_json or "[]")
    except (TypeError, ValueError):
        return set()
    return {str(value) for value in values if str(value) in ASSIGNABLE_PERMISSIONS}


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

    def permissions_for(user):
        if user.role == "staff":
            return sorted(ASSIGNABLE_PERMISSIONS | {"staff_manage", "audit_read"})
        return sorted(operator_permissions(user))

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
            "permissions": permissions_for(u),
            "must_change_password": bool(getattr(u, "must_change_password", False)),
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
        u.must_change_password = False
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
            "permissions": sorted(operator_permissions(x)),
            "must_change_password": bool(x.must_change_password),
        } for x in rows], access_areas=ACCESS_AREAS)

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
            permissions_json="[]",
            must_change_password=True,
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
            "permissions": [],
            "must_change_password": True,
        }), 201

    @app.patch("/api/admin/operators/<int:operator_id>/access")
    def set_operator_access(operator_id):
        actor, denied = authorization_result()
        if denied:
            return denied
        d = request.get_json(silent=True) or {}
        permissions = d.get("permissions")
        if not isinstance(permissions, list):
            return jsonify(error="Elenco autorizzazioni non valido."), 400
        cleaned = {str(value) for value in permissions}
        if not cleaned.issubset(ASSIGNABLE_PERMISSIONS):
            return jsonify(error="Una o più autorizzazioni non sono consentite."), 400
        op = dbx.session.get(app_module.User, operator_id)
        if not op or op.role != "operator":
            return jsonify(error="Operatore non trovato."), 404
        op.permissions_json = json.dumps(sorted(cleaned), ensure_ascii=False)
        audit(actor, "operator_access_update", op.id, f"permissions={','.join(sorted(cleaned))}")
        dbx.session.commit()
        return jsonify(ok=True, permissions=sorted(cleaned))

    @app.post("/api/admin/operators/<int:operator_id>/reset-password")
    def reset_operator_password(operator_id):
        actor, denied = authorization_result()
        if denied:
            return denied
        d = request.get_json(silent=True) or {}
        password = d.get("password") or ""
        if not app_module.strong_password(password):
            return jsonify(error="La password temporanea deve avere almeno 10 caratteri, con lettere e numeri."), 400
        op = dbx.session.get(app_module.User, operator_id)
        if not op or op.role != "operator":
            return jsonify(error="Operatore non trovato."), 404
        op.password_hash = generate_password_hash(password, method="scrypt")
        op.must_change_password = True
        app_module.clear_login_failures(app_module.login_key("staff", op.email))
        audit(actor, "operator_password_reset", op.id, f"email={op.email}")
        dbx.session.commit()
        return jsonify(ok=True, must_change_password=True)

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

    app.extensions["aplsai_staff_accounts"] = {
        "installed": True,
        "operator_permissions": operator_permissions,
        "assignable_permissions": ASSIGNABLE_PERMISSIONS,
        "access_areas": ACCESS_AREAS,
    }
