import os
import tempfile
import unittest


_tmp = tempfile.NamedTemporaryFile(suffix=".db", delete=False)
_tmp.close()
os.environ["DATABASE_URL"] = f"sqlite:///{_tmp.name}"
os.environ["FLASK_ENV"] = "testing"
os.environ["SECRET_KEY"] = "quote-test-secret"
os.environ["ADMIN_EMAIL"] = "quote-admin@example.com"
os.environ["ADMIN_PASSWORD"] = "QuoteAdmin12345"

import app as app_module
from app.operations import init_operations
from app.rbac_runtime import install_runtime_rbac
from app.staff_accounts import init_staff_accounts
from app.pilot_cases import init_pilot_cases
from app.quotes import init_quotes


class QuoteTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = app_module.create_app(); cls.app.config.update(TESTING=True)
        init_operations(cls.app, app_module); install_runtime_rbac(cls.app, app_module)
        init_staff_accounts(cls.app, app_module); init_pilot_cases(cls.app, app_module); init_quotes(cls.app, app_module)
        with cls.app.app_context():
            prop = app_module.Property(ref="CO01-REALE", zone="Roma", price=238000, sqm=90)
            app_module.db.session.add(prop); app_module.db.session.flush()
            PilotCase = cls.app.extensions["aplsai_pilot_cases"]["PilotCase"]
            PilotCase.query.filter_by(code="CO 01").first().property_id = prop.id
            app_module.db.session.commit()
        cls.sent = []
        cls.app.extensions["aplsai_gmail"] = {"send_plain_email": lambda to, subject, body: cls.sent.append((to, subject, body)) or {"id": "test"}}

    @classmethod
    def tearDownClass(cls):
        try: os.unlink(_tmp.name)
        except OSError: pass

    def admin(self):
        with self.app.app_context(): uid = app_module.User.query.filter_by(email="quote-admin@example.com").first().id
        client = self.app.test_client()
        with client.session_transaction() as state: state["uid"], state["nonce"] = uid, "quote-test"
        return client

    def test_01_prepare_exact_eight_without_fake_recipients(self):
        response = self.admin().post("/api/staff/quotes/prepare-co01", json={})
        self.assertEqual(response.status_code, 200); rows = response.get_json()["quotes"]
        self.assertEqual(len(rows), 8); self.assertEqual(rows[0]["code"], "RP-01")
        self.assertEqual(rows[-1]["estimate_v1"], 3000); self.assertTrue(all(x["recipient_company"] == "DA ASSEGNARE" for x in rows))

    def test_02_verified_recipient_sends_automatically(self):
        quote = self.admin().get("/api/staff/quotes").get_json()["quotes"][1]
        response = self.admin().patch(f"/api/staff/quotes/{quote['id']}", json={
            "recipient_company": "Impresa Verificata", "recipient_email": "preventivi@example.com",
            "recipient_verified": True, "due_at": "2030-01-31T12:00:00Z", "auto_send": True,
        })
        self.assertEqual(response.status_code, 200); self.assertTrue(response.get_json()["sent"])
        self.assertEqual(response.get_json()["quote"]["send_status"], "Inviata"); self.assertEqual(len(self.sent), 1)

    def test_03_incomplete_offer_cannot_be_approved(self):
        quote = self.admin().get("/api/staff/quotes").get_json()["quotes"][0]
        response = self.admin().post(f"/api/admin/quotes/{quote['id']}/verify", json={"status": "Verificata"})
        self.assertEqual(response.status_code, 400); self.assertIn("mancano", response.get_json()["error"])


if __name__ == "__main__": unittest.main()
