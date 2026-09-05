import os
import tempfile
import unittest
from werkzeug.security import generate_password_hash

_tmp = tempfile.NamedTemporaryFile(suffix=".db", delete=False)
_tmp.close()
os.environ["DATABASE_URL"] = f"sqlite:///{_tmp.name}"
os.environ["FLASK_ENV"] = "testing"
os.environ["SECRET_KEY"] = "test-secret-key-not-for-production"
os.environ["ADMIN_EMAIL"] = "admin-test@example.com"
os.environ["ADMIN_PASSWORD"] = "AdminTest12345"

import app as app_module
from app.operations import init_operations
from app.rbac_runtime import install_runtime_rbac

PROFILE = {
    "zone": {"main": "Roma", "km": 20},
    "budget": {"ideal": 250000, "max": 300000, "flex": 5},
    "spaces": {"sqm": 80, "beds": 2, "baths": 1},
    "timing": "Entro 6 mesi",
    "style": "Moderno",
    "must": ["Balcone"],
    "houseTypes": ["Appartamento"],
    "purchase": ["Capitale proprio"],
}


class SecurityBaselineTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        # Re-assert test environment here because unittest discovery imports all
        # modules before running setUpClass and another module must never change
        # the database/admin identity used by this suite.
        os.environ["DATABASE_URL"] = f"sqlite:///{_tmp.name}"
        os.environ["FLASK_ENV"] = "testing"
        os.environ["SECRET_KEY"] = "test-secret-key-not-for-production"
        os.environ["ADMIN_EMAIL"] = "admin-test@example.com"
        os.environ["ADMIN_PASSWORD"] = "AdminTest12345"

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

    def register_client(self, client, email):
        return client.post("/api/register", json={
            "name": "Cliente Test", "email": email, "phone": "+39 333 1234567",
            "password": "Cliente12345", "profile": PROFILE,
        })

    def login_client(self, client, email, password="Cliente12345"):
        return client.post("/api/client/login", json={"email": email, "password": password})

    def login_admin(self, client):
        return client.post("/api/staff/login", json={
            "email": "admin-test@example.com", "password": "AdminTest12345"
        })

    def make_role_session(self, role, email):
        with self.app.app_context():
            u = app_module.User.query.filter_by(email=email).first()
            if not u:
                u = app_module.User(
                    role=role, name=f"Test {role}", email=email, phone="",
                    password_hash=generate_password_hash("RoleTest12345", method="scrypt")
                )
                app_module.db.session.add(u)
                app_module.db.session.commit()
            uid = u.id
        c = self.app.test_client()
        with c.session_transaction() as s:
            s["uid"] = uid
            s["nonce"] = f"{role}-test"
            s.permanent = True
        return c

    def test_health_is_public(self):
        r = self.app.test_client().get("/api/health")
        self.assertEqual(r.status_code, 200)
        self.assertEqual(r.get_json()["status"], "online")

    def test_staff_dashboard_rejects_anonymous(self):
        self.assertEqual(self.app.test_client().get("/api/staff/dashboard").status_code, 401)

    def test_staff_operations_rejects_anonymous(self):
        self.assertEqual(self.app.test_client().get("/api/staff/operations").status_code, 401)

    def test_client_cannot_access_staff_area(self):
        c = self.app.test_client()
        self.assertEqual(self.register_client(c, "client1@example.com").status_code, 201)
        self.assertEqual(c.get("/api/staff/dashboard").status_code, 401)
        self.assertEqual(c.get("/api/staff/operations").status_code, 401)
        self.assertEqual(c.get("/api/staff/audit").status_code, 401)

    def test_client_cannot_modify_staff_operation(self):
        c = self.app.test_client()
        self.assertEqual(self.register_client(c, "nostaffwrite@example.com").status_code, 201)
        with self.app.app_context():
            uid = app_module.User.query.filter_by(email="nostaffwrite@example.com").first().id
        r = c.post(f"/api/staff/client/{uid}/operation", json={
            "phase": "Ricerca attiva", "financial_state": "capitale_verificato", "next_action": "Test"
        })
        self.assertEqual(r.status_code, 401)

    def test_client_login_works_with_registered_credentials(self):
        registrar = self.app.test_client()
        self.assertEqual(self.register_client(registrar, "logincheck@example.com").status_code, 201)
        c = self.app.test_client()
        r = self.login_client(c, "logincheck@example.com")
        self.assertEqual(r.status_code, 200, r.get_json())
        self.assertEqual(r.get_json()["client"]["email"], "logincheck@example.com")

    def test_client_session_only_returns_own_profile(self):
        registrar = self.app.test_client()
        self.assertEqual(self.register_client(registrar, "alice@example.com").status_code, 201)
        registrar.post("/api/logout", json={})
        self.assertEqual(self.register_client(registrar, "bob@example.com").status_code, 201)
        with self.app.app_context():
            alice = app_module.User.query.filter_by(email="alice@example.com").first()
            bob = app_module.User.query.filter_by(email="bob@example.com").first()
            self.assertIsNotNone(alice)
            self.assertIsNotNone(bob)
            alice_id = alice.id
            bob_id = bob.id
        a = self.app.test_client()
        b = self.app.test_client()
        with a.session_transaction() as s:
            s["uid"] = alice_id
            s["nonce"] = "alice-test"
            s.permanent = True
        with b.session_transaction() as s:
            s["uid"] = bob_id
            s["nonce"] = "bob-test"
            s.permanent = True
        ra = a.get("/api/client/me")
        rb = b.get("/api/client/me")
        self.assertEqual(ra.status_code, 200, ra.get_json())
        self.assertEqual(rb.status_code, 200, rb.get_json())
        self.assertEqual(ra.get_json()["client"]["email"], "alice@example.com")
        self.assertEqual(rb.get_json()["client"]["email"], "bob@example.com")

    def test_logout_invalidates_client_session(self):
        c = self.app.test_client()
        self.assertEqual(self.register_client(c, "logoutcheck@example.com").status_code, 201)
        self.assertEqual(c.get("/api/client/me").status_code, 200)
        self.assertEqual(c.post("/api/logout", json={}).status_code, 200)
        self.assertEqual(c.get("/api/client/me").status_code, 401)

    def test_failed_login_rate_limit_blocks_sixth_attempt(self):
        c = self.app.test_client()
        for i in range(app_module.LOGIN_MAX_ATTEMPTS):
            r = self.login_client(c, "missing-rate@example.com", password="WrongPassword1")
            self.assertEqual(r.status_code, 401, f"tentativo {i + 1}: {r.get_json()}")
        r = self.login_client(c, "missing-rate@example.com", password="WrongPassword1")
        self.assertEqual(r.status_code, 429)

    def test_staff_session_does_not_grant_client_access(self):
        c = self.app.test_client()
        self.assertEqual(self.login_admin(c).status_code, 200)
        self.assertEqual(c.get("/api/client/me").status_code, 401)

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

    def test_operator_can_read_operations_but_not_audit(self):
        operator = self.make_role_session("operator", "operator-test@example.com")
        self.assertEqual(operator.get("/api/staff/operations").status_code, 200)
        self.assertEqual(operator.get("/api/staff/audit").status_code, 401)

    def test_operator_can_update_client_operation(self):
        registrar = self.app.test_client()
        self.assertEqual(self.register_client(registrar, "operator-client@example.com").status_code, 201)
        with self.app.app_context():
            uid = app_module.User.query.filter_by(email="operator-client@example.com").first().id
        operator = self.make_role_session("operator", "operator-write@example.com")
        r = operator.post(f"/api/staff/client/{uid}/operation", json={
            "phase": "Ricerca attiva", "financial_state": "pre_delibera", "next_action": "Richiamare cliente"
        })
        self.assertEqual(r.status_code, 200, r.get_json())

    def test_wrong_origin_is_rejected(self):
        r = self.app.test_client().post(
            "/api/client/login",
            json={"email": "nobody@example.com", "password": "WrongPassword1"},
            headers={"Origin": "https://evil.example"},
        )
        self.assertEqual(r.status_code, 403)

    def test_non_json_write_is_rejected(self):
        self.assertEqual(self.app.test_client().post("/api/client/login", data="email=x").status_code, 415)

    def test_security_headers_present(self):
        r = self.app.test_client().get("/")
        self.assertEqual(r.headers.get("X-Content-Type-Options"), "nosniff")
        self.assertEqual(r.headers.get("X-Frame-Options"), "DENY")
        self.assertIn("frame-ancestors 'none'", r.headers.get("Content-Security-Policy", ""))

    def test_api_responses_are_not_cached(self):
        self.assertEqual(self.app.test_client().get("/api/health").headers.get("Cache-Control"), "no-store")

    def test_admin_can_login_and_read_audit(self):
        c = self.app.test_client()
        r = self.login_admin(c)
        self.assertEqual(r.status_code, 200, r.get_json())
        self.assertEqual(c.get("/api/staff/dashboard").status_code, 200)
        self.assertEqual(c.get("/api/staff/audit").status_code, 200)

    def test_staff_operation_update_is_recorded_in_audit(self):
        registrar = self.app.test_client()
        self.assertEqual(self.register_client(registrar, "auditclient@example.com").status_code, 201)
        with self.app.app_context():
            uid = app_module.User.query.filter_by(email="auditclient@example.com").first().id
        admin = self.app.test_client()
        self.assertEqual(self.login_admin(admin).status_code, 200)
        r = admin.post(f"/api/staff/client/{uid}/operation", json={
            "phase": "Ricerca attiva", "financial_state": "capitale_verificato",
            "next_action": "Contattare cliente", "assigned_to": "Admin"
        })
        self.assertEqual(r.status_code, 200, r.get_json())
        audit = admin.get("/api/staff/audit?limit=20")
        self.assertEqual(audit.status_code, 200)
        self.assertTrue(any(
            e.get("action") == "client_operation_update" and e.get("object_id") == str(uid)
            for e in audit.get_json().get("events", [])
        ))

    def test_admin_alias_bypasses_lock_on_long_email(self):
        blocked = self.app.test_client()
        for _ in range(app_module.LOGIN_MAX_ATTEMPTS):
            blocked.post("/api/staff/login", json={
                "email": "admin-test@example.com", "password": "WrongPassword1"
            })
        self.assertEqual(self.login_admin(blocked).status_code, 429)

        recovered = self.app.test_client().post("/api/staff/login", json={
            "email": "admin@aplsai.it", "password": "AdminTest12345"
        })
        self.assertEqual(recovered.status_code, 200, recovered.get_json())


if __name__ == "__main__":
    unittest.main()
