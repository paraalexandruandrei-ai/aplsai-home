import os
import tempfile
import unittest

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
        try: os.unlink(_tmp.name)
        except OSError: pass

    def setUp(self):
        app_module._login_attempts.clear()

    def register_client(self, client, email):
        return client.post("/api/register", json={
            "name": "Cliente Test", "email": email, "phone": "+39 333 1234567",
            "password": "Cliente12345", "profile": PROFILE,
        })

    def login_client(self, client, email):
        return client.post("/api/client/login", json={"email": email, "password": "Cliente12345"})

    def test_health_is_public(self):
        r=self.app.test_client().get("/api/health")
        self.assertEqual(r.status_code,200); self.assertEqual(r.get_json()["status"],"online")

    def test_staff_dashboard_rejects_anonymous(self):
        self.assertEqual(self.app.test_client().get("/api/staff/dashboard").status_code,401)

    def test_staff_operations_rejects_anonymous(self):
        self.assertEqual(self.app.test_client().get("/api/staff/operations").status_code,401)

    def test_client_cannot_access_staff_area(self):
        c=self.app.test_client(); self.assertEqual(self.register_client(c,"client1@example.com").status_code,201)
        self.assertEqual(c.get("/api/staff/dashboard").status_code,401)
        self.assertEqual(c.get("/api/staff/operations").status_code,401)
        self.assertEqual(c.get("/api/staff/audit").status_code,401)

    def test_client_login_works_with_registered_credentials(self):
        registrar=self.app.test_client()
        self.assertEqual(self.register_client(registrar,"logincheck@example.com").status_code,201)
        c=self.app.test_client()
        r=self.login_client(c,"logincheck@example.com")
        self.assertEqual(r.status_code,200, r.get_json())
        self.assertEqual(r.get_json()["client"]["email"],"logincheck@example.com")

    def test_client_session_only_returns_own_profile(self):
        registrar=self.app.test_client()
        self.assertEqual(self.register_client(registrar,"alice@example.com").status_code,201)
        registrar.post("/api/logout",json={})
        self.assertEqual(self.register_client(registrar,"bob@example.com").status_code,201)
        with self.app.app_context():
            alice=app_module.User.query.filter_by(email="alice@example.com").first()
            bob=app_module.User.query.filter_by(email="bob@example.com").first()
            self.assertIsNotNone(alice); self.assertIsNotNone(bob)
            alice_id=alice.id; bob_id=bob.id
        a=self.app.test_client(); b=self.app.test_client()
        with a.session_transaction() as s:
            s["uid"]=alice_id; s["nonce"]="alice-test"; s.permanent=True
        with b.session_transaction() as s:
            s["uid"]=bob_id; s["nonce"]="bob-test"; s.permanent=True
        ra=a.get("/api/client/me"); rb=b.get("/api/client/me")
        self.assertEqual(ra.status_code,200,ra.get_json()); self.assertEqual(rb.status_code,200,rb.get_json())
        self.assertEqual(ra.get_json()["client"]["email"],"alice@example.com")
        self.assertEqual(rb.get_json()["client"]["email"],"bob@example.com")

    def test_wrong_origin_is_rejected(self):
        r=self.app.test_client().post("/api/client/login",json={"email":"nobody@example.com","password":"WrongPassword1"},headers={"Origin":"https://evil.example"})
        self.assertEqual(r.status_code,403)

    def test_non_json_write_is_rejected(self):
        self.assertEqual(self.app.test_client().post("/api/client/login",data="email=x").status_code,415)

    def test_security_headers_present(self):
        r=self.app.test_client().get("/")
        self.assertEqual(r.headers.get("X-Content-Type-Options"),"nosniff")
        self.assertEqual(r.headers.get("X-Frame-Options"),"DENY")
        self.assertIn("frame-ancestors 'none'",r.headers.get("Content-Security-Policy",""))

    def test_api_responses_are_not_cached(self):
        self.assertEqual(self.app.test_client().get("/api/health").headers.get("Cache-Control"),"no-store")

    def test_admin_can_login_and_read_audit(self):
        c=self.app.test_client(); r=c.post("/api/staff/login",json={"email":"admin-test@example.com","password":"AdminTest12345"})
        self.assertEqual(r.status_code,200); self.assertEqual(c.get("/api/staff/audit").status_code,200)

if __name__ == "__main__": unittest.main()
