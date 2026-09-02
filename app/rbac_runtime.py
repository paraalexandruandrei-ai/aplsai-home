from flask import jsonify, request, session
from werkzeug.security import check_password_hash

from .rbac import effective_role, has_permission


ROUTE_PERMISSIONS = {
    "/api/staff/dashboard": "dashboard_full",
    "/api/staff/properties": "property_create",
    "/api/staff/proposals": "proposal_create",
    "/api/staff/documents": "document_share",
}

PREFIX_PERMISSIONS = {
    "/api/staff/match/": "matching_run",
}


def install_runtime_rbac(app, app_module):
    """Bridge legacy staff routes to granular permissions during migration.

    Existing role='staff' remains Admin-compatible. Operator sessions can use only
    explicitly mapped staff routes. Unknown staff routes fail closed for Operator.
    Client/Partner behavior remains denied by the legacy routes or their own APIs.
    """
    if app.extensions.get("aplsai_rbac_runtime"):
        return

    original_require_role = app_module.require_role

    def compatible_require_role(role):
        if role != "staff":
            return original_require_role(role)

        uid = session.get("uid")
        if not uid:
            return None
        u = app_module.db.session.get(app_module.User, uid)
        if not u:
            return None
        canonical = effective_role(u.role)
        if canonical in {"admin", "operator"}:
            return u
        return None

    app_module.require_role = compatible_require_role

    def required_permission_for_path(path):
        permission = ROUTE_PERMISSIONS.get(path)
        if permission:
            return permission
        for prefix, value in PREFIX_PERMISSIONS.items():
            if path.startswith(prefix):
                return value
        return None

    @app.before_request
    def operator_staff_login_gate():
        """Allow Operator accounts to use the existing Staff login form.

        Legacy Admin/Staff authentication remains handled by the original route.
        We intercept only when the submitted email belongs to role='operator'.
        """
        if request.path != "/api/staff/login" or request.method != "POST":
            return None

        data = request.get_json(silent=True) or {}
        email = app_module.clean_email(data.get("email"))
        password = data.get("password") or ""
        u = app_module.User.query.filter_by(email=email, role="operator").first()
        if not u:
            return None

        key = app_module.login_key("staff", email)
        if app_module.login_blocked(key):
            return jsonify(error="Troppi tentativi. Riprova tra qualche minuto."), 429
        if not check_password_hash(u.password_hash, password):
            app_module.register_login_failure(key)
            return jsonify(error="Credenziali staff errate."), 401

        app_module.clear_login_failures(key)
        app_module.establish_session(u.id)
        return jsonify(ok=True, role="operator")

    @app.before_request
    def granular_staff_permission_gate():
        path = request.path
        if not path.startswith("/api/staff/"):
            return None

        # These endpoints already enforce their own granular permission checks.
        if path == "/api/staff/operations" or path == "/api/staff/audit" or (
            path.startswith("/api/staff/client/") and path.endswith("/operation")
        ):
            return None

        # Login must remain public to unauthenticated staff/operator accounts.
        if path == "/api/staff/login":
            return None

        uid = session.get("uid")
        if not uid:
            return None  # legacy route returns 401
        u = app_module.db.session.get(app_module.User, uid)
        if not u:
            return None

        canonical = effective_role(u.role)
        if canonical == "admin":
            return None
        if canonical != "operator":
            return None  # legacy route denies client/partner

        permission = required_permission_for_path(path)
        if not permission or not has_permission(u.role, permission):
            return jsonify(error="Permesso insufficiente."), 403
        return None

    app.extensions["aplsai_rbac_runtime"] = {
        "installed": True,
        "required_permission_for_path": required_permission_for_path,
    }
