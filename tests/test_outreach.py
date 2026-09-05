import os
import tempfile
import unittest

from werkzeug.security import generate_password_hash


_tmp = tempfile.NamedTemporaryFile(suffix=".db", delete=False)
_tmp.close()
os.environ["DATABASE_URL"] = f"sqlite:///{_tmp.name}"
os.environ["FLASK_ENV"] = "testing"
os.environ["SECRET_KEY"] = "outreach-test-secret"
os.environ["ADMIN_EMAIL"] = "outreach-admin@example.com"
os.environ["ADMIN_PASSWORD"] = "OutreachAdmin12345"

import app as app_module
from app.operations import init_operations
from app.rbac_runtime import install_runtime_rbac
from app.opportunities import init_opportunities
from app.outreach import init_outreach


class OutreachCheck(unittest.TestCase):
    opportunity_counter = 100
    @classmethod
    def setUpClass(cls):
        cls.app = app_module.create_app()
        cls.app.config.update(TESTING=True)
        init_operations(cls.app, app_module)
        install_runtime_rbac(cls.app, app_module)
        init_opportunities(cls.app, app_module)
        init_outreach(cls.app, app_module)
        with cls.app.app_context():
            if not app_module.User.query.filter_by(email="outreach-admin@example.com").first():
                app_module.db.session.add(app_module.User(
                    role="staff", name="Admin Outreach",
                    email="outreach-admin@example.com", phone="",
                    password_hash=generate_password_hash("OutreachAdmin12345", method="scrypt"),
                ))
            if not app_module.User.query.filter_by(email="outreach-operator@example.com").first():
                app_module.db.session.add(app_module.User(
                    role="operator", name="Operatore Outreach",
                    email="outreach-operator@example.com", phone="",
                    password_hash=generate_password_hash("OutreachOperator12345", method="scrypt"),
                ))
                app_module.db.session.commit()

    @classmethod
    def tearDownClass(cls):
        try:
            os.unlink(_tmp.name)
        except OSError:
            pass

    def client_for(self, email):
        with self.app.app_context():
            uid = app_module.User.query.filter_by(email=email).first().id
        client = self.app.test_client()
        with client.session_transaction() as state:
            state["uid"] = uid
            state["nonce"] = "outreach-check"
        return client

    def create_opportunity(self, client, contact="Agenzia Uno <case@example.com>"):
        type(self).opportunity_counter += 1
        ref = type(self).opportunity_counter
        response = client.post("/api/staff/opportunities", json={
            "title": "Immobile test contatti", "source_type": "Agenzia",
            "source_name": "Agenzia Uno", "source_url": f"https://example.com/immobile-{ref}",
            "external_ref": f"TEST-{ref}", "contact_name": "Mario Rossi",
            "contact_details": contact, "zone": "Roma Nord",
        })
        self.assertEqual(response.status_code, 201, response.get_json())
        return response.get_json()["opportunity"]

    def test_generates_questions_only_for_missing_information(self):
        operator = self.client_for("outreach-operator@example.com")
        opportunity = self.create_opportunity(operator)
        response = operator.post(f"/api/staff/opportunities/{opportunity['id']}/inquiries", json={
            "recipient_verified": True,
        })
        self.assertEqual(response.status_code, 201, response.get_json())
        inquiry = response.get_json()["inquiry"]
        self.assertEqual(inquiry["recipient_email"], "case@example.com")
        self.assertEqual(inquiry["status"], "Bozza")
        codes = {item["code"] for item in inquiry["missing_fields"]}
        self.assertIn("availability", codes)
        self.assertIn("price", codes)
        self.assertIn("planimetry_status", codes)
        self.assertIn("APLSAI-OPP-", inquiry["body"])

    def test_operator_cannot_approve_and_admin_can(self):
        operator = self.client_for("outreach-operator@example.com")
        opportunity = self.create_opportunity(operator, "case2@example.com")
        inquiry = operator.post(f"/api/staff/opportunities/{opportunity['id']}/inquiries", json={
            "recipient_verified": True,
        }).get_json()["inquiry"]
        response = operator.patch(f"/api/staff/inquiries/{inquiry['id']}", json={
            "recipient_email": "case2@example.com", "recipient_verified": True,
            "subject": inquiry["subject"], "body": inquiry["body"], "request_approval": True,
        })
        self.assertEqual(response.status_code, 200, response.get_json())
        self.assertEqual(response.get_json()["inquiry"]["status"], "Da approvare")
        self.assertEqual(operator.post(f"/api/staff/inquiries/{inquiry['id']}/approve", json={}).status_code, 403)
        admin = self.client_for("outreach-admin@example.com")
        approved = admin.post(f"/api/staff/inquiries/{inquiry['id']}/approve", json={})
        self.assertEqual(approved.status_code, 200, approved.get_json())
        self.assertEqual(approved.get_json()["inquiry"]["status"], "Approvata")

    def test_reply_is_extracted_but_requires_human_confirmation(self):
        operator = self.client_for("outreach-operator@example.com")
        opportunity = self.create_opportunity(operator, "reply@example.com")
        inquiry = operator.post(f"/api/staff/opportunities/{opportunity['id']}/inquiries", json={
            "recipient_verified": True,
        }).get_json()["inquiry"]
        response = operator.post(f"/api/staff/inquiries/{inquiry['id']}/replies", json={
            "sender_email": "reply@example.com",
            "body": "Buongiorno, l'immobile è ancora disponibile. Il prezzo è 245.000 euro e la metratura è 98 mq. La planimetria è disponibile.",
        })
        self.assertEqual(response.status_code, 201, response.get_json())
        reply = response.get_json()["reply"]
        suggested = reply["extracted"]["suggested_updates"]
        self.assertEqual(suggested["availability"], "Disponibile")
        self.assertEqual(suggested["price"], 245000.0)
        self.assertEqual(suggested["sqm"], 98.0)
        self.assertTrue(reply["extracted"]["requires_confirmation"])
        with self.app.app_context():
            model = self.app.extensions["aplsai_opportunities"]["PropertyOpportunity"]
            self.assertIsNone(app_module.db.session.get(model, opportunity["id"]).price)
        applied = operator.post(f"/api/staff/inquiry-replies/{reply['id']}/apply", json={
            "confirmed_updates": suggested,
        })
        self.assertEqual(applied.status_code, 200, applied.get_json())
        self.assertEqual(applied.get_json()["opportunity"]["price"], 245000.0)
        self.assertEqual(applied.get_json()["reply"]["status"], "Dati confermati")

    def test_notifications_show_missing_contact(self):
        operator = self.client_for("outreach-operator@example.com")
        self.create_opportunity(operator, "solo telefono 061234567")
        response = operator.get("/api/staff/outreach")
        self.assertEqual(response.status_code, 200, response.get_json())
        self.assertTrue(any(item["type"] == "missing_contact" for item in response.get_json()["notifications"]))


if __name__ == "__main__":
    unittest.main()
