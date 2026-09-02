from flask_migrate import Migrate
import app as app_module
from app.operations import init_operations
from app.rbac_runtime import install_runtime_rbac
from app.staff_accounts import init_staff_accounts

app = app_module.create_app()
init_operations(app, app_module)
install_runtime_rbac(app, app_module)
init_staff_accounts(app, app_module)

migrate = Migrate(app, app_module.db, compare_type=True, render_as_batch=True)
