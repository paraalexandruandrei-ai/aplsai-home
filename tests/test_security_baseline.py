import os
import tempfile
import unittest

# Ambiente test isolato: nessun segreto o database di produzione.
_tmp = tempfile.NamedTemporaryFile(suffix=".db", delete=False)
_tmp.close()
os.environ["DATABASE_URL"] = f"sqlite:///{_tmp.name}"
os.environ["FLASK_ENV"] = "testing"
os.environ["SECRET_KEY"] = "test-secret-key-not-for-production"
os.environ["ADMIN_EMAIL"] = "admin-test@example.com"
os.environ["ADMIN_PASSWORD"] = "AdminTest12345"

import app as app_module
from app.operations import init_operations


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
        cls.app = app_module.create_app()
        cls.app.config.update(TESTING=True)
        init_operations(cls.app, app_module)

    @classmethod
    def tearDownClass(cls):
        try:
            os.unlink(_tmp.name)
        except OSError:
            pass

    def register_client(self, client, email):
        return client.post("/api/register", json={
            "name": "Cliente Test",
            "email": email,
            "phone": "+39 333 1234567",
            "password": "Cliente12345",
            "profile": PROFILE,
        })

    def test_health_is_public(self):
        r = self.app.test_client().get("/api/health")
        self.assertEqual(r.status_code, 200)
        self.assertEqual(r.get_json()["status"], "online")

    def test_staff_dashboard_rejects_anonymous(self):
        r = self.app.test_client().get("/api/staff/dashboard")
        self.assertEqual(r.status_code, 401)

    def test_staff_operations_rejects_anonymous(self):
        r = self.app.test_client().get("/api/staff/operations")
        self.assertEqual(r.status_code, 401)

    def test_client_cannot_access_staff_area(self):
        c = self.app.test_client()
        self.assertEqual(self.register_client(c, "client1@example.com").status_code, 201)
        self.assertEqual(c.get("/api/staff/dashboard").status_code, 401)
        self.assertEqual(c.get("/api/staff/operations").status_code, 401)
        self.assertEqual(c.get("/api/staff/audit").status_code, 401)

    def test_client_session_only_returns_own_profile(self):
        a = self.app.test_client()
        b = self.app.test_client()
        self.assertEqual(self.register_client(a, "alice@example.com").status_code, 201)
        self.assertEqual(self.register_client(b, "bob@example.com").status_code, 201)
        self.assertEqual(a.get("/api/client/me").get_json()["client"]["email"], "alice@example.com")
        self.assertEqual(b.get("/api/client/me").get_json()["client"]["email"], "bob@example.com")

    def test_wrong_origin_is_rejected(self):
        c = self.app.test_client()
        r = c.post(
            "/api/client/login",
            json={"email": "nobody@example.com", "password": "WrongPassword1"},
            headers={"Origin": "https://evil.example"},
        )
        self.assertEqual(r.status_code, 403)

    def test_non_json_write_is_rejected(self):
        r = self.app.test_client().post("/api/client/login", data="email=x")
        self.assertEqual(r.status_code, 415)

    def test_security_headers_present(self):
        r = self.app.test_client().get("/")
        self.assertEqual(r.headers.get("X-Content-Type-Options"), "nosniff")
        self.assertEqual(r.headers.get("X-Frame-Options"), "DENY")
        self.assertIn("frame-ancestors 'none'", r.headers.get("Content-Security-Policy", ""))

    def test_api_responses_are_not_cached(self):
        r = self.app.test_client().get("/api/health")
        self.assertEqual(r.headers.get("Cache-Control"), "no-store")

    def test_admin_can_login_and_read_audit(self):
        c = self.app.test_client()
        r = c.post("/api/staff/login", json={
            "email": "admin-test@example.com",
            "password": "AdminTest12345",
        })
        self.assertEqual(r.status_code, 200)
        self.assertEqual(c.get("/api/staff/audit").status_code, 200)


if __name__ == "__main__":
    unittest.main()
