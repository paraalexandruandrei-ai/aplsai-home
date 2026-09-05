import os
import tempfile
import unittest
from datetime import datetime, timedelta, timezone

from werkzeug.security import generate_password_hash


_tmp = tempfile.NamedTemporaryFile(suffix=".db", delete=False)
_tmp.close()
os.environ["DATABASE_URL"] = f"sqlite:///{_tmp.name}"
os.environ["FLASK_ENV"] = "testing"
os.environ["SECRET_KEY"] = "work-task-test-secret"
os.environ["ADMIN_EMAIL"] = "task-admin@example.com"
os.environ["ADMIN_PASSWORD"] = "TaskAdmin12345"

import app as app_module
from app.operations import init_operations
from app.rbac_runtime import install_runtime_rbac
from app.staff_protocol import init_staff_protocol
from app.work_tasks import init_work_tasks


class WorkTaskCheck(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = app_module.create_app()
        cls.app.config.update(TESTING=True)
        init_operations(cls.app, app_module)
        install_runtime_rbac(cls.app, app_module)
        init_staff_protocol(cls.app, app_module)
        init_work_tasks(cls.app, app_module)
        with cls.app.app_context():
            for name, email in [
                ("Operatore Uno", "task-operator-1@example.com"),
                ("Operatore Due", "task-operator-2@example.com"),
                ("Operatore Non Conforme", "task-pending@example.com"),
            ]:
                app_module.db.session.add(app_module.User(
                    role="operator", name=name, email=email, phone="",
                    password_hash=generate_password_hash("TaskOperator12345", method="scrypt"),
                ))
            app_module.db.session.commit()
            ext = cls.app.extensions["aplsai_staff_protocol"]
            rules = ext["StaffRule"].query.filter_by(active=True, mandatory=True).all()
            for email in ["task-operator-1@example.com", "task-operator-2@example.com"]:
                user = app_module.User.query.filter_by(email=email).first()
                for rule in rules:
                    if rule.audience in {"Tutto lo staff", "Operatori"}:
                        app_module.db.session.add(ext["StaffRuleAcknowledgement"](
                            rule_id=rule.id, user_id=user.id, rule_version=rule.version,
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
            user_id = app_module.User.query.filter_by(email=email).first().id
        client = self.app.test_client()
        with client.session_transaction() as state:
            state["uid"] = user_id
            state["nonce"] = "task-check"
        return client

    def create_task(self, assignee_email, suffix):
        with self.app.app_context():
            assignee_id = app_module.User.query.filter_by(email=assignee_email).first().id
        response = self.role_client("task-admin@example.com").post("/api/admin/tasks", json={
            "title": f"Verifica pratica {suffix}",
            "description": "Controllare i dati e registrare l’esito.",
            "category": "Documenti", "priority": "Alta",
            "assigned_to_user_id": assignee_id,
            "due_at": (datetime.now(timezone.utc) + timedelta(days=2)).isoformat(),
            "link_type": "Cliente", "link_id": suffix,
        })
        self.assertEqual(response.status_code, 201, response.get_json())
        return response.get_json()["task"]

    def test_admin_assigns_and_operator_sees_only_own_tasks(self):
        own = self.create_task("task-operator-1@example.com", "A")
        self.create_task("task-operator-2@example.com", "B")
        response = self.role_client("task-operator-1@example.com").get("/api/staff/tasks")
        self.assertEqual(response.status_code, 200, response.get_json())
        ids = {row["id"] for row in response.get_json()["tasks"]}
        self.assertIn(own["id"], ids)
        self.assertTrue(all(row["assigned_to_name"] == "Operatore Uno" for row in response.get_json()["tasks"]))

    def test_unassigned_operator_cannot_open_task(self):
        task = self.create_task("task-operator-1@example.com", "C")
        response = self.role_client("task-operator-2@example.com").get(f"/api/staff/tasks/{task['id']}")
        self.assertEqual(response.status_code, 403, response.get_json())

    def test_completion_requires_admin_approval(self):
        task = self.create_task("task-operator-1@example.com", "D")
        operator = self.role_client("task-operator-1@example.com")
        missing = operator.patch(f"/api/staff/tasks/{task['id']}", json={"status": "In verifica"})
        self.assertEqual(missing.status_code, 400, missing.get_json())
        ready = operator.patch(f"/api/staff/tasks/{task['id']}", json={
            "status": "In verifica", "completion_note": "Documenti controllati e completi.",
        })
        self.assertEqual(ready.status_code, 200, ready.get_json())
        self.assertEqual(ready.get_json()["task"]["status"], "In verifica")
        approved = self.role_client("task-admin@example.com").post(
            f"/api/admin/tasks/{task['id']}/decision", json={"approved": True, "note": "Verificato."},
        )
        self.assertEqual(approved.status_code, 200, approved.get_json())
        self.assertEqual(approved.get_json()["task"]["status"], "Completata")

    def test_rejection_requires_correction_note(self):
        task = self.create_task("task-operator-1@example.com", "E")
        operator = self.role_client("task-operator-1@example.com")
        operator.patch(f"/api/staff/tasks/{task['id']}", json={
            "status": "In verifica", "completion_note": "Prima consegna.",
        })
        admin = self.role_client("task-admin@example.com")
        missing = admin.post(f"/api/admin/tasks/{task['id']}/decision", json={"approved": False, "note": ""})
        self.assertEqual(missing.status_code, 400, missing.get_json())
        rejected = admin.post(f"/api/admin/tasks/{task['id']}/decision", json={
            "approved": False, "note": "Integrare la planimetria.",
        })
        self.assertEqual(rejected.status_code, 200, rejected.get_json())
        self.assertEqual(rejected.get_json()["task"]["status"], "In corso")

    def test_protocol_blocks_non_compliant_operator_update(self):
        task = self.create_task("task-pending@example.com", "F")
        response = self.role_client("task-pending@example.com").patch(
            f"/api/staff/tasks/{task['id']}", json={"status": "In corso"},
        )
        self.assertEqual(response.status_code, 428, response.get_json())
        self.assertEqual(response.get_json().get("code"), "STAFF_PROTOCOL_REQUIRED")


if __name__ == "__main__":
    unittest.main()
