import json
import os
import tempfile
import unittest
from unittest.mock import patch

from cryptography.fernet import Fernet


_tmp = tempfile.NamedTemporaryFile(suffix=".db", delete=False)
_tmp.close()
os.environ["DATABASE_URL"] = f"sqlite:///{_tmp.name}"
os.environ["FLASK_ENV"] = "testing"
os.environ["SECRET_KEY"] = "gmail-integration-test-secret"
os.environ["ADMIN_EMAIL"] = "gmail-admin@example.com"
os.environ["ADMIN_PASSWORD"] = "GmailAdmin12345"
os.environ["APLSAI_OFFICIAL_EMAIL"] = "aplsaihome.srl@gmail.com"
os.environ["GOOGLE_OAUTH_CLIENT_ID"] = "test-client-id"
os.environ["GOOGLE_OAUTH_CLIENT_SECRET"] = "test-client-secret"
os.environ["GMAIL_TOKEN_ENCRYPTION_KEY"] = Fernet.generate_key().decode("ascii")

import app as app_module
from app.gmail_integration import init_gmail_integration
from app.operations import init_operations
from app.opportunities import init_opportunities
from app.outreach import init_outreach
from app.rbac_runtime import install_runtime_rbac


class FakeResponse:
    def __init__(self, payload):
        self.payload = json.dumps(payload).encode("utf-8")

    def __enter__(self):
        return self

    def __exit__(self, *_):
        return False

    def read(self):
        return self.payload


class GmailIntegrationCheck(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = app_module.create_app()
        cls.app.config.update(TESTING=True)
        init_operations(cls.app, app_module)
        install_runtime_rbac(cls.app, app_module)
        init_opportunities(cls.app, app_module)
        init_outreach(cls.app, app_module)
        init_gmail_integration(cls.app, app_module)

    @classmethod
    def tearDownClass(cls):
        try:
            os.unlink(_tmp.name)
        except OSError:
            pass

    def admin(self):
        with self.app.app_context():
            uid = app_module.User.query.filter_by(email="gmail-admin@example.com").first().id
        client = self.app.test_client()
        with client.session_transaction() as state:
            state["uid"] = uid
            state["nonce"] = "gmail-check"
        return client

    def test_status_identifies_official_account(self):
        response = self.admin().get("/api/admin/gmail/status")
        self.assertEqual(response.status_code, 200)
        gmail = response.get_json()["gmail"]
        self.assertTrue(gmail["configured"])
        self.assertEqual(gmail["official_email"], "aplsaihome.srl@gmail.com")

    def test_approved_inquiry_is_sent_and_thread_is_stored(self):
        client = self.admin()
        opportunity = client.post("/api/staff/opportunities", json={
            "title": "Immobile Gmail test",
            "source_type": "Agenzia",
            "source_name": "Agenzia Test",
            "source_url": "https://example.com/gmail-test",
            "external_ref": "GMAIL-TEST",
            "contact_name": "Mario Rossi",
            "contact_details": "destinatario@example.com",
            "zone": "Roma",
        }).get_json()["opportunity"]
        inquiry = client.post(
            f"/api/staff/opportunities/{opportunity['id']}/inquiries",
            json={"recipient_verified": True},
        ).get_json()["inquiry"]
        inquiry = client.patch(f"/api/staff/inquiries/{inquiry['id']}", json={
            "recipient_email": "destinatario@example.com",
            "recipient_verified": True,
            "subject": inquiry["subject"],
            "body": inquiry["body"],
            "request_approval": True,
        }).get_json()["inquiry"]
        client.post(f"/api/staff/inquiries/{inquiry['id']}/approve", json={})

        with self.app.app_context():
            extension = self.app.extensions["aplsai_gmail"]
            row = extension["GmailConnection"](
                email="aplsaihome.srl@gmail.com",
                encrypted_refresh_token=extension["encrypt_token"]("refresh-token-test"),
            )
            app_module.db.session.add(row)
            app_module.db.session.commit()

        responses = [
            FakeResponse({"access_token": "access-token-test"}),
            FakeResponse({"id": "gmail-message-1", "threadId": "gmail-thread-1"}),
        ]
        with patch("app.gmail_integration.urlopen", side_effect=responses):
            sent = client.post(f"/api/staff/inquiries/{inquiry['id']}/send-email", json={})

        self.assertEqual(sent.status_code, 200, sent.get_json())
        self.assertEqual(sent.get_json()["inquiry"]["status"], "Inviata")
        self.assertEqual(sent.get_json()["inquiry"]["external_thread_id"], "gmail-thread-1")


if __name__ == "__main__":
    unittest.main()
