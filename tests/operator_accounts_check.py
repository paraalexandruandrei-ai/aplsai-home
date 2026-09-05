import os
import tempfile
import unittest
from io import BytesIO

from openpyxl import load_workbook
from sqlalchemy import text
from werkzeug.security import generate_password_hash

_tmp = tempfile.NamedTemporaryFile(suffix=".db", delete=False)
_tmp.close()
os.environ["DATABASE_URL"] = f"sqlite:///{_tmp.name}"
os.environ["FLASK_ENV"] = "testing"
os.environ["SECRET_KEY"] = "operator-account-test-secret"
os.environ["ADMIN_EMAIL"] = "admin-accounts@example.com"
os.environ["ADMIN_PASSWORD"] = "AdminAccounts12345"

import app as app_module
from app.operations import init_operations
from app.rbac_runtime import install_runtime_rbac
from app.staff_accounts import init_staff_accounts
from app.operational_export import init_operational_export
from app.client_classification import init_client_classification
from app.property_profiles import init_property_profiles


class OperatorAccountsCheck(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = app_module.create_app()
        cls.app.config.update(TESTING=True)
        init_operations(cls.app, app_module)
        install_runtime_rbac(cls.app, app_module)
        init_staff_accounts(cls.app, app_module)
        init_operational_export(cls.app, app_module)
        init_client_classification(cls.app, app_module)
        init_property_profiles(cls.app, app_module)

        with cls.app.app_context():
            for role, email in [
                ("operator", "existing-operator@example.com"),
                ("operator", "toggle-operator@example.com"),
                ("client", "account-client@example.com"),
            ]:
                if not app_module.User.query.filter_by(email=email).first():
                    app_module.db.session.add(app_module.User(
                        role=role,
                        name=f"Test {role}",
                        email=email,
                        phone="",
                        active=True,
                        password_hash=generate_password_hash("RoleTest12345", method="scrypt"),
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
        with self.app.app_context():
            u = app_module.User.query.filter_by(email="toggle-operator@example.com").first()
            if u:
                u.active = True
                app_module.db.session.commit()

    def login_admin(self):
        c = self.app.test_client()
        r = c.post("/api/staff/login", json={
            "email": "admin-accounts@example.com",
            "password": "AdminAccounts12345",
        })
        self.assertEqual(r.status_code, 200, r.get_json())
        return c

    def role_client(self, email):
        with self.app.app_context():
            u = app_module.User.query.filter_by(email=email).first()
            uid = u.id
        c = self.app.test_client()
        with c.session_transaction() as s:
            s["uid"] = uid
            s["nonce"] = "role-check"
            s.permanent = True
        return c

    def test_anonymous_get_is_401(self):
        self.assertEqual(self.app.test_client().get("/api/admin/operators").status_code, 401)

    def test_operator_and_client_are_403(self):
        self.assertEqual(self.role_client("existing-operator@example.com").get("/api/admin/operators").status_code, 403)
        self.assertEqual(self.role_client("account-client@example.com").get("/api/admin/operators").status_code, 403)

    def test_admin_can_list_and_create_operator(self):
        admin = self.login_admin()
        self.assertEqual(admin.get("/api/admin/operators").status_code, 200)
        r = admin.post("/api/admin/operators", json={
            "name": "Nuovo Operatore",
            "email": "new-operator@example.com",
            "password": "NewOperator12345",
        })
        self.assertEqual(r.status_code, 201, r.get_json())
        self.assertTrue(r.get_json()["operator"]["active"])

        login = self.app.test_client().post("/api/staff/login", json={
            "email": "new-operator@example.com",
            "password": "NewOperator12345",
        })
        self.assertEqual(login.status_code, 200, login.get_json())
        self.assertEqual(login.get_json().get("role"), "operator")

    def test_admin_can_deactivate_and_reactivate_operator(self):
        admin = self.login_admin()
        with self.app.app_context():
            op_id = app_module.User.query.filter_by(email="toggle-operator@example.com").first().id

        r = admin.patch(f"/api/admin/operators/{op_id}/active", json={"active": False})
        self.assertEqual(r.status_code, 200, r.get_json())
        self.assertFalse(r.get_json()["operator"]["active"])

        denied = self.app.test_client().post("/api/staff/login", json={
            "email": "toggle-operator@example.com",
            "password": "RoleTest12345",
        })
        self.assertEqual(denied.status_code, 403, denied.get_json())

        r = admin.patch(f"/api/admin/operators/{op_id}/active", json={"active": True})
        self.assertEqual(r.status_code, 200, r.get_json())
        self.assertTrue(r.get_json()["operator"]["active"])

        allowed = self.app.test_client().post("/api/staff/login", json={
            "email": "toggle-operator@example.com",
            "password": "RoleTest12345",
        })
        self.assertEqual(allowed.status_code, 200, allowed.get_json())

    def test_deactivation_invalidates_existing_session_on_next_request(self):
        c = self.app.test_client()
        login = c.post("/api/staff/login", json={
            "email": "toggle-operator@example.com",
            "password": "RoleTest12345",
        })
        self.assertEqual(login.status_code, 200, login.get_json())
        self.assertEqual(c.get("/api/staff/dashboard").status_code, 200)

        admin = self.login_admin()
        with self.app.app_context():
            op_id = app_module.User.query.filter_by(email="toggle-operator@example.com").first().id
        self.assertEqual(admin.patch(f"/api/admin/operators/{op_id}/active", json={"active": False}).status_code, 200)
        self.assertEqual(c.get("/api/staff/dashboard").status_code, 401)

    def test_deactivation_is_audited(self):
        admin = self.login_admin()
        with self.app.app_context():
            op_id = app_module.User.query.filter_by(email="toggle-operator@example.com").first().id
        self.assertEqual(admin.patch(f"/api/admin/operators/{op_id}/active", json={"active": False}).status_code, 200)
        audit = admin.get("/api/staff/audit?limit=50")
        self.assertEqual(audit.status_code, 200)
        self.assertTrue(any(
            e.get("action") == "operator_deactivate" and e.get("object_id") == str(op_id)
            for e in audit.get_json().get("events", [])
        ))

    def test_duplicate_email_is_rejected(self):
        admin = self.login_admin()
        r = admin.post("/api/admin/operators", json={
            "name": "Duplicato",
            "email": "existing-operator@example.com",
            "password": "Duplicate12345",
        })
        self.assertEqual(r.status_code, 409)

    def test_weak_password_is_rejected(self):
        admin = self.login_admin()
        r = admin.post("/api/admin/operators", json={
            "name": "Debole",
            "email": "weak-operator@example.com",
            "password": "debole",
        })
        self.assertEqual(r.status_code, 400)

    def test_creation_is_audited(self):
        admin = self.login_admin()
        r = admin.post("/api/admin/operators", json={
            "name": "Audit Operatore",
            "email": "audit-operator@example.com",
            "password": "AuditOperator12345",
        })
        self.assertEqual(r.status_code, 201, r.get_json())
        operator_id = str(r.get_json()["operator"]["id"])
        audit = admin.get("/api/staff/audit?limit=50")
        self.assertEqual(audit.status_code, 200)
        self.assertTrue(any(
            e.get("action") == "operator_create" and e.get("object_id") == operator_id
            for e in audit.get_json().get("events", [])
        ))

    def test_staff_identity_and_password_change(self):
        admin = self.login_admin()
        me = admin.get("/api/staff/me")
        self.assertEqual(me.status_code, 200, me.get_json())
        self.assertEqual(me.get_json()["staff"]["role"], "admin")

        wrong = admin.post("/api/staff/password", json={
            "current_password": "WrongPassword1",
            "new_password": "ChangedAdmin12345",
        })
        self.assertEqual(wrong.status_code, 401)

        changed = admin.post("/api/staff/password", json={
            "current_password": "AdminAccounts12345",
            "new_password": "ChangedAdmin12345",
        })
        self.assertEqual(changed.status_code, 200, changed.get_json())

        old_login = self.app.test_client().post("/api/staff/login", json={
            "email": "admin-accounts@example.com",
            "password": "AdminAccounts12345",
        })
        self.assertEqual(old_login.status_code, 401)
        new_login = self.app.test_client().post("/api/staff/login", json={
            "email": "admin-accounts@example.com",
            "password": "ChangedAdmin12345",
        })
        self.assertEqual(new_login.status_code, 200, new_login.get_json())

        with self.app.app_context():
            u = app_module.User.query.filter_by(email="admin-accounts@example.com").first()
            u.password_hash = generate_password_hash("AdminAccounts12345", method="scrypt")
            app_module.db.session.commit()

    def test_admin_password_recovery_runs_once(self):
        with self.app.app_context():
            admin = app_module.User.query.filter_by(email="admin-accounts@example.com").first()
            admin.password_hash = generate_password_hash("StaleAdmin12345", method="scrypt")
            app_module.db.session.execute(
                text("DELETE FROM aplsai_schema_migration WHERE id=:id"),
                {"id": app_module.ADMIN_PASSWORD_RECOVERY_MIGRATION},
            )
            app_module.db.session.commit()
            app_module.seed_admin()

        recovered = self.login_admin()
        changed = recovered.post("/api/staff/password", json={
            "current_password": "AdminAccounts12345",
            "new_password": "RecoveredAdmin12345",
        })
        self.assertEqual(changed.status_code, 200, changed.get_json())

        with self.app.app_context():
            app_module.seed_admin()

        survived = self.app.test_client().post("/api/staff/login", json={
            "email": "admin-accounts@example.com",
            "password": "RecoveredAdmin12345",
        })
        self.assertEqual(survived.status_code, 200, survived.get_json())

        with self.app.app_context():
            admin = app_module.User.query.filter_by(email="admin-accounts@example.com").first()
            admin.password_hash = generate_password_hash("AdminAccounts12345", method="scrypt")
            app_module.db.session.commit()

    def test_operator_can_change_own_password_but_not_manage_operators(self):
        operator = self.role_client("existing-operator@example.com")
        me = operator.get("/api/staff/me")
        self.assertEqual(me.status_code, 200, me.get_json())
        self.assertEqual(me.get_json()["staff"]["role"], "operator")
        self.assertEqual(operator.get("/api/admin/operators").status_code, 403)

        changed = operator.post("/api/staff/password", json={
            "current_password": "RoleTest12345",
            "new_password": "OperatorChanged12345",
        })
        self.assertEqual(changed.status_code, 200, changed.get_json())
        with self.app.app_context():
            u = app_module.User.query.filter_by(email="existing-operator@example.com").first()
            u.password_hash = generate_password_hash("RoleTest12345", method="scrypt")
            app_module.db.session.commit()

    def test_admin_can_download_operational_excel(self):
        admin = self.login_admin()
        response = admin.get("/api/admin/operational-export.xlsx")
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.data[:2], b"PK")
        self.assertIn("application/vnd.openxmlformats", response.content_type)
        workbook = load_workbook(BytesIO(response.data), read_only=True)
        self.assertIn("Immobili", workbook.sheetnames)
        self.assertIn("Storico immobili", workbook.sheetnames)
        headers = [cell.value for cell in next(workbook["Immobili"].iter_rows(max_row=1))]
        self.assertIn("Trasformabilità", headers)
        self.assertIn("Costo lavori minimo", headers)

        operator = self.role_client("existing-operator@example.com")
        self.assertEqual(operator.get("/api/admin/operational-export.xlsx").status_code, 403)

    def test_advanced_property_profile_history_validation_and_archive(self):
        admin = self.login_admin()
        created = admin.post("/api/staff/properties", json={
            "ref": "IMM-PROFILO-TEST",
            "property_type": "Appartamento",
            "address": "Da verificare",
            "zone": "Roma",
            "price": 240000,
            "sqm": 82,
            "beds": 2,
            "baths": 1,
            "state": "Da ristrutturare",
            "availability": "Da verificare",
            "elevator": None,
            "energy_class": "Da verificare",
            "systems_status": "Da verificare",
            "transformation_status": "Verifica in corso",
            "planned_works": "Riduzione rischi e ridistribuzione interna da validare.",
            "renovation_cost_min": 45000,
            "renovation_cost_max": 70000,
            "renovation_months_min": 4,
            "renovation_months_max": 7,
            "data_reliability": "Dichiarato",
            "technical_verification": "Da verificare",
        })
        self.assertEqual(created.status_code, 201, created.get_json())
        prop = created.get_json()["property"]
        property_id = prop["id"]
        self.assertEqual(prop["transformation_status"], "Verifica in corso")
        self.assertEqual(prop["renovation_cost_min"], 45000)

        invalid = admin.patch(f"/api/staff/properties/{property_id}", json={
            "renovation_cost_min": 80000,
            "renovation_cost_max": 60000,
        })
        self.assertEqual(invalid.status_code, 400, invalid.get_json())

        updated = admin.patch(f"/api/staff/properties/{property_id}", json={
            "transformation_status": "Trasformabile",
            "technical_verification": "Verificato",
            "data_reliability": "Verificato",
            "renovation_cost_min": 50000,
            "renovation_cost_max": 68000,
            "change_note": "Validazione tecnica completata",
        })
        self.assertEqual(updated.status_code, 200, updated.get_json())
        self.assertEqual(updated.get_json()["property"]["transformation_status"], "Trasformabile")

        detail = admin.get(f"/api/staff/properties/{property_id}")
        self.assertEqual(detail.status_code, 200, detail.get_json())
        revisions = detail.get_json()["revisions"]
        self.assertEqual([row["version"] for row in revisions[:2]], [2, 1])
        self.assertEqual(revisions[0]["change_note"], "Validazione tecnica completata")

        archived = admin.patch(f"/api/staff/properties/{property_id}/archive", json={"archived": True})
        self.assertEqual(archived.status_code, 200, archived.get_json())
        self.assertIsNotNone(archived.get_json()["property"]["archived_at"])
        self.assertEqual(admin.get(f"/api/staff/match/property/{property_id}").status_code, 409)

        restored = admin.patch(f"/api/staff/properties/{property_id}/archive", json={"archived": False})
        self.assertEqual(restored.status_code, 200, restored.get_json())
        self.assertIsNone(restored.get_json()["property"]["archived_at"])

    def test_admin_can_separate_test_clients_and_archive_without_deleting(self):
        profile = {
            "zone": {"main": "Roma", "km": 10},
            "budget": {"ideal": 250000, "max": 300000, "flex": 5},
            "spaces": {"sqm": 75, "beds": 2, "baths": 1},
            "timing": "3-6 mesi", "style": "Moderno",
            "must": ["Balcone"], "houseTypes": ["Appartamento"],
            "purchase": ["Mutuo"],
        }
        registration = self.app.test_client().post("/api/register", json={
            "name": "Cliente Classificazione",
            "email": "classification-client@example.com",
            "phone": "+393331234567",
            "password": "Classification12345",
            "profile": profile,
        })
        self.assertEqual(registration.status_code, 201, registration.get_json())
        client_id = registration.get_json()["client"]["id"]
        self.assertFalse(registration.get_json()["client"]["is_test"])

        admin = self.login_admin()
        protected = admin.delete(f"/api/admin/clients/{client_id}/test-data", json={
            "confirm": "ELIMINA",
        })
        self.assertEqual(protected.status_code, 409)

        marked = admin.patch(f"/api/admin/clients/{client_id}/classification", json={
            "is_test": True, "archived": False,
        })
        self.assertEqual(marked.status_code, 200, marked.get_json())
        self.assertTrue(marked.get_json()["client"]["is_test"])

        operations = admin.get("/api/staff/operations").get_json()["results"]
        self.assertNotIn(client_id, [row["client"]["id"] for row in operations])

        archived = admin.patch(f"/api/admin/clients/{client_id}/classification", json={
            "is_test": True, "archived": True,
        })
        self.assertEqual(archived.status_code, 200, archived.get_json())
        self.assertIsNotNone(archived.get_json()["client"]["archived_at"])

        operator = self.role_client("existing-operator@example.com")
        self.assertEqual(operator.patch(
            f"/api/admin/clients/{client_id}/classification",
            json={"is_test": False, "archived": False},
        ).status_code, 403)

        deleted = admin.delete(f"/api/admin/clients/{client_id}/test-data", json={
            "confirm": "ELIMINA",
        })
        self.assertEqual(deleted.status_code, 200, deleted.get_json())
        with self.app.app_context():
            self.assertIsNone(app_module.db.session.get(app_module.User, client_id))


if __name__ == "__main__":
    unittest.main()
