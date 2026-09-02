import re
from flask import request
import app as app_module
from app.operations import init_operations
from app.rbac_runtime import install_runtime_rbac
from app.staff_accounts import init_staff_accounts

app = app_module.create_app()
init_operations(app, app_module)
install_runtime_rbac(app, app_module)
init_staff_accounts(app, app_module)


# Difesa aggiuntiva per i campi testuali ricevuti dal browser.
def _sanitize_value(value, key=None):
    if key == "password":
        return value
    if isinstance(value, dict):
        return {k: _sanitize_value(v, k) for k, v in value.items()}
    if isinstance(value, list):
        return [_sanitize_value(v) for v in value]
    if isinstance(value, str):
        value = re.sub(r"[\x00-\x08\x0b\x0c\x0e-\x1f\x7f]", "", value)
        return value.replace("<", "").replace(">", "")
    return value


@app.before_request
def aplsai_sanitize_json_input():
    if request.method in {"POST", "PUT", "PATCH"} and request.is_json:
        payload = request.get_json(silent=True)
        if isinstance(payload, dict):
            sanitized = _sanitize_value(payload)
            request._cached_json = (sanitized, sanitized)
