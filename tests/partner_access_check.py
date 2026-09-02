import json
import os
import tempfile
import unittest

from werkzeug.security import generate_password_hash

_tmp = tempfile.NamedTemporaryFile(suffix=".db", delete=False)
_tmp.close()
os.environ["DATABASE_URL"] = f"sqlite:///{_tmp.name}"
os.environ["FLASK_ENV"] = "testing"
os.environ["SECRET_KEY"] = "partner-access-test-secret"
os.environ["ADMIN_EMAIL"] = "admin-partner@example.com"
os.environ["ADMIN_PASSWORD"] = "AdminPartner12345"

import app as app_module
from app.operations import init_operations
from app.rbac_runtime import install_runtime_rbac
from app.staff_accounts import init_staff_accounts
from app.partner_access import init_partner_access


class PartnerAccessCheck(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = app_module.create_app()
        cls.app.config.update(TESTING=True)
        init_operations(cls.app, app_module)
        install_runtime_rbac(cls.app, app_module)
        init_staff_accounts(cls.app, app_module)
        init_partner_access(cls.app, app_module)

        profile = {
            "zone": {"main": "Milano", "km": 10},
            "budget": {"ideal": 250000, "max": 300000, "flex": 5},
            "spaces": {"sqm": 80, "beds": 2, "baths": 1},
            "timing": "3-6 mesi",
            "style": "Appartamento",
            "must": ["Balcone"],
            "houseTypes": ["Appartamento"],
            "purchase": ["Buono stato"],
        }
        with cls.app.app_context():
            cls.client_ids = []
            for idx in (1, 2):
                email = f"partner-client-{idx}@example.com"
                u = app_module.User.query.filter_by(email=email).first()
                if not u:
                    u = app_module.User(
                        role="client", name=f"Cliente Partner {idx}", email=email,
                        phone="+3900000000", active=True,
                        password_hash=generate_password_hash("ClientPartner12345", method="scrypt"),
                    )
                    app_module.db.session.add(u)
                    app_module.db.session.flush()
                    app_module.db.session.add(app_module.ClientProfile(
                        user_id=u.id, profile_json=json.dumps(profile), status="Ricerca attiva"
                    ))
                cls.client_ids.append(u.id)
            app_module.db.session.commit()

    @classmethod
    def tearDownClass(cls):
        try:
            os.unlink(_tmp.name)
        except OSError:
            pass

    def setUp(self):
        app_module._login_attempts.clear()

    def login_admin(self):
        c = self.app.test_client()
        r = c.post("/api/staff/login", json={
            "email": "admin-partner@example.com",
            "password": "AdminPartner12345",
        })
        self.assertEqual(r.status_code, 200, r.get_json())
        return c

    def test_partner_requires_initial_assignment(self):
        admin = self.login_admin()
        r = admin.post("/api/admin/partners", json={
            "name": "Partner Senza Pratica",
            "email": "partner-no-case@example.com",
            "password": "PartnerNoCase12345",
        })
        self.assertEqual(r.status_code, 400)

    def test_partner_sees_only_assigned_cases_and_documents(self):
        admin = self.login_admin()
        r = admin.post("/api/admin/partners", json={
            "name": "Partner Isolato",
            "email": "partner-isolated@example.com",
            "password": "PartnerIsolated12345",
            "client_id": self.client_ids[0],
        })
        self.assertEqual(r.status_code, 201, r.get_json())
        partner_id = r.get_json()["partner"]["id"]

        with self.app.app_context():
            app_module.db.session.add(app_module.Document(
                client_id=self.client_ids[0], title="Documento assegnato", url="https://example.com/a"
            ))
            app_module.db.session.add(app_module.Document(
                client_id=self.client_ids[1], title="Documento non assegnato", url="https://example.com/b"
            ))
            app_module.db.session.commit()

        p = self.app.test_client()
        login = p.post("/api/partner/login", json={
            "email": "partner-isolated@example.com",
            "password": "PartnerIsolated12345",
        })
        self.assertEqual(login.status_code, 200, login.get_json())
        self.assertEqual(login.get_json().get("role"), "partner")

        cases = p.get("/api/partner/cases")
        self.assertEqual(cases.status_code, 200, cases.get_json())
        ids = [x["client"]["id"] for x in cases.get_json().get("results", [])]
        self.assertIn(self.client_ids[0], ids)
        self.assertNotIn(self.client_ids[1], ids)

        allowed = p.get(f"/api/partner/cases/{self.client_ids[0]}/documents")
        self.assertEqual(allowed.status_code, 200, allowed.get_json())
        self.assertEqual([d["title"] for d in allowed.get_json()["documents"]], ["Documento assegnato"])

        denied = p.get(f"/api/partner/cases/{self.client_ids[1]}/documents")
        self.assertEqual(denied.status_code, 403)

        assign = admin.post(f"/api/admin/partners/{partner_id}/assignments", json={"client_id": self.client_ids[1]})
        self.assertEqual(assign.status_code, 201, assign.get_json())
        now_allowed = p.get(f"/api/partner/cases/{self.client_ids[1]}/documents")
        self.assertEqual(now_allowed.status_code, 200, now_allowed.get_json())

    def test_non_admin_cannot_create_partner(self):
        p = self.app.test_client()
        self.assertEqual(p.post("/api/admin/partners", json={}).status_code, 401)


if __name__ == "__main__":
    unittest.main()
