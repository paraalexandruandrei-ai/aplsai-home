import os
import tempfile
import unittest

from werkzeug.security import generate_password_hash


_tmp = tempfile.NamedTemporaryFile(suffix=".db", delete=False)
_tmp.close()
os.environ["DATABASE_URL"] = f"sqlite:///{_tmp.name}"
os.environ["FLASK_ENV"] = "testing"
os.environ["SECRET_KEY"] = "staff-protocol-test-secret"
os.environ["ADMIN_EMAIL"] = "protocol-admin@example.com"
os.environ["ADMIN_PASSWORD"] = "ProtocolAdmin12345"

import app as app_module
from app.operations import init_operations
from app.rbac_runtime import install_runtime_rbac
from app.staff_protocol import init_staff_protocol


class StaffProtocolCheck(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = app_module.create_app()
        cls.app.config.update(TESTING=True)
        init_operations(cls.app, app_module)
        install_runtime_rbac(cls.app, app_module)
        init_staff_protocol(cls.app, app_module)
        with cls.app.app_context():
            if not app_module.User.query.filter_by(email="protocol-admin@example.com").first():
                app_module.db.session.add(app_module.User(
                    role="staff", name="Admin Protocollo", email="protocol-admin@example.com",
                    phone="", password_hash=generate_password_hash("ProtocolAdmin12345", method="scrypt"),
                ))
            if not app_module.User.query.filter_by(email="protocol-operator@example.com").first():
                app_module.db.session.add(app_module.User(
                    role="operator", name="Operatore Protocollo", email="protocol-operator@example.com",
                    phone="", password_hash=generate_password_hash("ProtocolOperator12345", method="scrypt"),
                ))
            app_module.db.session.commit()

    @classmethod
    def tearDownClass(cls):
        try:
            os.unlink(_tmp.name)
        except OSError:
            pass

    def role_client(self, email):
        with self.app.app_context():
            uid = app_module.User.query.filter_by(email=email).first().id
        client = self.app.test_client()
        with client.session_transaction() as state:
            state["uid"] = uid
            state["nonce"] = "protocol-check"
        return client

    def test_default_protocol_is_available_to_operator(self):
        operator = self.role_client("protocol-operator@example.com")
        response = operator.get("/api/staff/protocol")
        self.assertEqual(response.status_code, 200, response.get_json())
        self.assertGreaterEqual(response.get_json()["summary"]["mandatory"], 8)
        self.assertTrue(any(row["priority"] == "Bloccante" for row in response.get_json()["rules"]))

    def test_operator_can_acknowledge_current_version(self):
        operator = self.role_client("protocol-operator@example.com")
        first = operator.get("/api/staff/protocol").get_json()["rules"][0]
        response = operator.post(f"/api/staff/protocol/{first['id']}/acknowledge", json={})
        self.assertEqual(response.status_code, 200, response.get_json())
        self.assertTrue(response.get_json()["rule"]["acknowledged"])

    def test_admin_update_requires_new_acknowledgement(self):
        operator = self.role_client("protocol-operator@example.com")
        first = operator.get("/api/staff/protocol").get_json()["rules"][0]
        operator.post(f"/api/staff/protocol/{first['id']}/acknowledge", json={})
        admin = self.role_client("protocol-admin@example.com")
        updated = admin.patch(f"/api/admin/staff-rules/{first['id']}", json={
            "instructions": first["instructions"] + " Registrare anche l’esito del controllo.",
        })
        self.assertEqual(updated.status_code, 200, updated.get_json())
        self.assertEqual(updated.get_json()["rule"]["version"], first["version"] + 1)
        refreshed = operator.get("/api/staff/protocol").get_json()["rules"][0]
        self.assertFalse(refreshed["acknowledged"])

    def test_operator_cannot_create_or_modify_rules(self):
        operator = self.role_client("protocol-operator@example.com")
        response = operator.post("/api/admin/staff-rules", json={
            "category": "Qualità", "title": "Regola non autorizzata",
            "instructions": "Non deve essere creata.", "priority": "Normale",
            "audience": "Tutto lo staff", "mandatory": True,
        })
        self.assertEqual(response.status_code, 403)

    def test_pending_protocol_blocks_operator_work_until_acknowledged(self):
        operator = self.role_client("protocol-operator@example.com")
        blocked = operator.post("/api/staff/properties", json={})
        self.assertEqual(blocked.status_code, 428, blocked.get_json())
        self.assertEqual(blocked.get_json().get("code"), "STAFF_PROTOCOL_REQUIRED")
        self.assertTrue(blocked.get_json().get("pending_rules"))

        protocol = operator.get("/api/staff/protocol").get_json()
        for rule in protocol["rules"]:
            if rule["mandatory"] and not rule["acknowledged"]:
                acknowledged = operator.post(f"/api/staff/protocol/{rule['id']}/acknowledge", json={})
                self.assertEqual(acknowledged.status_code, 200, acknowledged.get_json())

        passed_gate = operator.post("/api/staff/properties", json={})
        self.assertNotEqual(passed_gate.status_code, 428, passed_gate.get_json())

    def test_admin_can_monitor_operator_compliance(self):
        admin = self.role_client("protocol-admin@example.com")
        response = admin.get("/api/admin/staff-compliance")
        self.assertEqual(response.status_code, 200, response.get_json())
        operator = next(row for row in response.get_json()["operators"] if row["email"] == "protocol-operator@example.com")
        self.assertIn("compliant", operator)
        self.assertEqual(operator["required"], operator["acknowledged"] + len(operator["pending"]))


if __name__ == "__main__":
    unittest.main()
