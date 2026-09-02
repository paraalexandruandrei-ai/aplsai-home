import os
import tempfile
import unittest

from werkzeug.security import generate_password_hash

_tmp = tempfile.NamedTemporaryFile(suffix=".db", delete=False)
_tmp.close()
os.environ["DATABASE_URL"] = f"sqlite:///{_tmp.name}"
os.environ["FLASK_ENV"] = "testing"
os.environ["SECRET_KEY"] = "test-secret-key-not-for-production"
os.environ["ADMIN_EMAIL"] = "admin-operator-login@example.com"
os.environ["ADMIN_PASSWORD"] = "AdminTest12345"

import app as app_module
from app.operations import init_operations
from app.rbac_runtime import install_runtime_rbac


class OperatorLoginTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = app_module.create_app()
        cls.app.config.update(TESTING=True)
        init_operations(cls.app, app_module)
        install_runtime_rbac(cls.app, app_module)
        with cls.app.app_context():
            if not app_module.User.query.filter_by(email="operator-real@example.com").first():
                app_module.db.session.add(app_module.User(
                    role="operator",
                    name="Operatore Test",
                    email="operator-real@example.com",
                    phone="",
                    password_hash=generate_password_hash("Operator12345", method="scrypt"),
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

    def test_operator_can_login_with_staff_gateway(self):
        c = self.app.test_client()
        r = c.post("/api/staff/login", json={
            "email": "operator-real@example.com",
            "password": "Operator12345",
        })
        self.assertEqual(r.status_code, 200, r.get_json())
        self.assertEqual(r.get_json().get("role"), "operator")
        self.assertEqual(c.get("/api/staff/dashboard").status_code, 200)
        self.assertEqual(c.get("/api/staff/audit").status_code, 401)

    def test_operator_wrong_password_is_rejected(self):
        c = self.app.test_client()
        r = c.post("/api/staff/login", json={
            "email": "operator-real@example.com",
            "password": "WrongOperator12345",
        })
        self.assertEqual(r.status_code, 401)

    def test_legacy_admin_login_still_works(self):
        c = self.app.test_client()
        r = c.post("/api/staff/login", json={
            "email": "admin-operator-login@example.com",
            "password": "AdminTest12345",
        })
        self.assertEqual(r.status_code, 200, r.get_json())
        self.assertEqual(c.get("/api/staff/dashboard").status_code, 200)
        self.assertEqual(c.get("/api/staff/audit").status_code, 200)


if __name__ == "__main__":
    unittest.main()
