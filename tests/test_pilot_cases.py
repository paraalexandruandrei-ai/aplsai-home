import json
import os
import tempfile
import unittest

from werkzeug.security import generate_password_hash


_tmp = tempfile.NamedTemporaryFile(suffix=".db", delete=False)
_tmp.close()
os.environ["DATABASE_URL"] = f"sqlite:///{_tmp.name}"
os.environ["FLASK_ENV"] = "testing"
os.environ["SECRET_KEY"] = "pilot-case-test-secret"
os.environ["ADMIN_EMAIL"] = "pilot-admin@example.com"
os.environ["ADMIN_PASSWORD"] = "PilotAdmin12345"

import app as app_module
from app.operations import init_operations
from app.pilot_cases import init_pilot_cases
from app.rbac_runtime import install_runtime_rbac
from app.staff_accounts import init_staff_accounts


class PilotCasesTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = app_module.create_app()
        cls.app.config.update(TESTING=True)
        init_operations(cls.app, app_module)
        install_runtime_rbac(cls.app, app_module)
        init_staff_accounts(cls.app, app_module)
        init_pilot_cases(cls.app, app_module)
        with cls.app.app_context():
            operator = app_module.User(
                role="operator", name="Operatore Collaudo",
                email="pilot-operator@example.com", phone="",
                password_hash=generate_password_hash("PilotOperator12345", method="scrypt"),
                permissions_json=json.dumps(["pilot_read", "pilot_manage"]),
            )
            app_module.db.session.add(operator)
            app_module.db.session.commit()
            cls.operator_id = operator.id

    @classmethod
    def tearDownClass(cls):
        try:
            os.unlink(_tmp.name)
        except OSError:
            pass

    def client_for(self, email):
        with self.app.app_context():
            user = app_module.User.query.filter_by(email=email).first()
            uid = user.id
        client = self.app.test_client()
        with client.session_transaction() as session:
            session["uid"] = uid
            session["nonce"] = "pilot-test"
        return client

    def admin(self):
        return self.client_for("pilot-admin@example.com")

    def operator(self):
        return self.client_for("pilot-operator@example.com")

    def test_01_seed_contains_three_cases_and_twenty_eight_checks(self):
        response = self.admin().get("/api/staff/pilot-cases")
        self.assertEqual(response.status_code, 200, response.get_json())
        data = response.get_json()
        self.assertEqual([row["code"] for row in data["cases"]], ["CO 01", "CO 02", "CO 03"])
        self.assertEqual(data["summary"]["checks"], 28)
        self.assertEqual(data["summary"]["approved"], 0)

    def test_02_result_requires_evidence_and_note(self):
        check_id = self.admin().get("/api/staff/pilot-cases").get_json()["cases"][0]["checks"][0]["id"]
        response = self.operator().patch(
            f"/api/staff/pilot-checks/{check_id}", json={"status": "Superata"},
        )
        self.assertEqual(response.status_code, 400)

    def test_03_operator_executes_and_only_admin_verifies(self):
        case = self.admin().get("/api/staff/pilot-cases").get_json()["cases"][0]
        self.assertEqual(self.admin().patch(
            f"/api/staff/pilot-cases/{case['id']}",
            json={"assigned_to_user_id": self.operator_id},
        ).status_code, 200)
        check_id = case["checks"][0]["id"]
        executed = self.operator().patch(f"/api/staff/pilot-checks/{check_id}", json={
            "status": "Superata", "evidence_ref": "Verbale prova 01",
            "result_note": "Risultato atteso verificato sul caso reale.",
        })
        self.assertEqual(executed.status_code, 200, executed.get_json())
        self.assertEqual(executed.get_json()["case"]["status"], "In lavorazione")
        denied = self.operator().post(
            f"/api/admin/pilot-checks/{check_id}/verify", json={"approved": True},
        )
        self.assertEqual(denied.status_code, 403)
        approved = self.admin().post(
            f"/api/admin/pilot-checks/{check_id}/verify", json={"approved": True},
        )
        self.assertEqual(approved.status_code, 200, approved.get_json())
        self.assertEqual(approved.get_json()["check"]["verification_status"], "Approvata")


if __name__ == "__main__":
    unittest.main()
