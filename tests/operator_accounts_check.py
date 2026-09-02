import os
import tempfile
import unittest

from werkzeug.security import generate_password_hash

_tmp = tempfile.NamedTemporaryFile(suffix=".db", delete=False)
_tmp.close()
os.environ["DATABASE_URL"] = f"sqlite:///{_tmp.name}"
os.environ["FLASK_ENV"] = "testing"
os.environ["SECRET_KEY"] = "operator-account-test-secret"
os.environ["ADMIN_EMAIL"] = "admin-accounts@example.com"
os.environ["ADMIN_PASSWORD"] = "AdminAccounts12345"

import app as app_module
from app.operations import init_operations
from app.rbac_runtime import install_runtime_rbac
from app.staff_accounts import init_staff_accounts


class OperatorAccountsCheck(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = app_module.create_app()
        cls.app.config.update(TESTING=True)
        init_operations(cls.app, app_module)
        install_runtime_rbac(cls.app, app_module)
        init_staff_accounts(cls.app, app_module)

        with cls.app.app_context():
            for role, email in [
                ("operator", "existing-operator@example.com"),
                ("client", "account-client@example.com"),
            ]:
                if not app_module.User.query.filter_by(email=email).first():
                    app_module.db.session.add(app_module.User(
                        role=role,
                        name=f"Test {role}",
                        email=email,
                        phone="",
                        password_hash=generate_password_hash("RoleTest12345", method="scrypt"),
                    ))
            app_module.db.session.commit()

    @classmethod
    def tearDownClass(cls):
        try:
            os.unlink(_tmp.name)
        except OSError:
            pass

    def setUp(self):
        app_module._login_attempts.clear()

    def login_admin(self):
        c = self.app.test_client()
        r = c.post("/api/staff/login", json={
            "email": "admin-accounts@example.com",
            "password": "AdminAccounts12345",
        })
        self.assertEqual(r.status_code, 200, r.get_json())
        return c

    def role_client(self, email):
        with self.app.app_context():
            u = app_module.User.query.filter_by(email=email).first()
            uid = u.id
        c = self.app.test_client()
        with c.session_transaction() as s:
            s["uid"] = uid
            s["nonce"] = "role-check"
            s.permanent = True
        return c

    def test_anonymous_get_is_401(self):
        self.assertEqual(self.app.test_client().get("/api/admin/operators").status_code, 401)

    def test_operator_and_client_are_403(self):
        self.assertEqual(self.role_client("existing-operator@example.com").get("/api/admin/operators").status_code, 403)
        self.assertEqual(self.role_client("account-client@example.com").get("/api/admin/operators").status_code, 403)

    def test_admin_can_list_and_create_operator(self):
        admin = self.login_admin()
        self.assertEqual(admin.get("/api/admin/operators").status_code, 200)
        r = admin.post("/api/admin/operators", json={
            "name": "Nuovo Operatore",
            "email": "new-operator@example.com",
            "password": "NewOperator12345",
        })
        self.assertEqual(r.status_code, 201, r.get_json())
        self.assertEqual(r.get_json()["operator"]["email"], "new-operator@example.com")

        login = self.app.test_client().post("/api/staff/login", json={
            "email": "new-operator@example.com",
            "password": "NewOperator12345",
        })
        self.assertEqual(login.status_code, 200, login.get_json())
        self.assertEqual(login.get_json().get("role"), "operator")

    def test_duplicate_email_is_rejected(self):
        admin = self.login_admin()
        r = admin.post("/api/admin/operators", json={
            "name": "Duplicato",
            "email": "existing-operator@example.com",
            "password": "Duplicate12345",
        })
        self.assertEqual(r.status_code, 409)

    def test_weak_password_is_rejected(self):
        admin = self.login_admin()
        r = admin.post("/api/admin/operators", json={
            "name": "Debole",
            "email": "weak-operator@example.com",
            "password": "debole",
        })
        self.assertEqual(r.status_code, 400)

    def test_creation_is_audited(self):
        admin = self.login_admin()
        r = admin.post("/api/admin/operators", json={
            "name": "Audit Operatore",
            "email": "audit-operator@example.com",
            "password": "AuditOperator12345",
        })
        self.assertEqual(r.status_code, 201, r.get_json())
        operator_id = str(r.get_json()["operator"]["id"])
        audit = admin.get("/api/staff/audit?limit=50")
        self.assertEqual(audit.status_code, 200)
        self.assertTrue(any(
            e.get("action") == "operator_create" and e.get("object_id") == operator_id
            for e in audit.get_json().get("events", [])
        ))


if __name__ == "__main__":
    unittest.main()
