import os
import tempfile
import unittest

_tmp = tempfile.NamedTemporaryFile(suffix=".db", delete=False)
_tmp.close()
os.environ["DATABASE_URL"] = f"sqlite:///{_tmp.name}"
os.environ["FLASK_ENV"] = "testing"
os.environ["SECRET_KEY"] = "beta-e2e-test-secret"
os.environ["ADMIN_EMAIL"] = "admin-beta@example.com"
os.environ["ADMIN_PASSWORD"] = "AdminBeta12345"
os.environ.pop("PRIVATE_DOCUMENT_HOSTS", None)

import app as app_module
from app.operations import init_operations
from app.rbac_runtime import install_runtime_rbac
from app.staff_accounts import init_staff_accounts
from app.partner_access import init_partner_access
from app.document_security import init_document_security


class BetaV1E2ECheck(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = app_module.create_app()
        cls.app.config.update(TESTING=True)
        init_operations(cls.app, app_module)
        install_runtime_rbac(cls.app, app_module)
        init_staff_accounts(cls.app, app_module)
        init_partner_access(cls.app, app_module)
        init_document_security(cls.app, app_module)

    @classmethod
    def tearDownClass(cls):
        try:
            os.unlink(_tmp.name)
        except OSError:
            pass

    def setUp(self):
        app_module._login_attempts.clear()

    def test_client_staff_partner_document_flow(self):
        profile = {
            "zone": {"main": "Roma", "km": 10},
            "budget": {"ideal": 300000, "max": 350000, "flex": 5},
            "spaces": {"sqm": 85, "beds": 2, "baths": 1},
            "timing": "3-6 mesi",
            "style": "Appartamento",
            "must": ["Balcone"],
            "houseTypes": ["Appartamento"],
            "purchase": ["Buono stato"],
        }

        # 1. Cliente: registrazione e sessione reale.
        client = self.app.test_client()
        reg = client.post("/api/register", json={
            "name": "Cliente Beta",
            "email": "client-beta@example.com",
            "phone": "+393331234567",
            "password": "ClientBeta12345",
            "profile": profile,
        })
        self.assertEqual(reg.status_code, 201, reg.get_json())
        client_id = reg.get_json()["client"]["id"]
        self.assertEqual(client.get("/api/client/me").status_code, 200)

        # 2. Admin/Staff: vede la pratica e la porta in lavorazione.
        admin = self.app.test_client()
        login = admin.post("/api/staff/login", json={
            "email": "admin-beta@example.com",
            "password": "AdminBeta12345",
        })
        self.assertEqual(login.status_code, 200, login.get_json())

        ops = admin.get("/api/staff/operations")
        self.assertEqual(ops.status_code, 200, ops.get_json())
        self.assertIn(client_id, [r["client"]["id"] for r in ops.get_json()["results"]])

        upd = admin.post(f"/api/staff/client/{client_id}/operation", json={
            "phase": "In lavorazione",
            "financial_state": "capitale_verificato",
            "next_action": "Verificare opportunità prioritaria",
            "assigned_to": "Operatore Beta",
        })
        self.assertEqual(upd.status_code, 200, upd.get_json())
        self.assertEqual(upd.get_json()["operation"]["phase"], "In lavorazione")

        # 3. Documento: viene registrato, ma un link pubblico non viene considerato privato.
        doc_create = admin.post("/api/staff/documents", json={
            "client_id": client_id,
            "title": "Documento Beta",
            "url": "https://example.com/documento-beta.pdf",
        })
        self.assertEqual(doc_create.status_code, 201, doc_create.get_json())
        document_id = doc_create.get_json()["id"]

        # 4. Partner: non può nascere senza pratica e viene creato già assegnato.
        no_case = admin.post("/api/admin/partners", json={
            "name": "Partner Senza Pratica",
            "email": "partner-nocase-beta@example.com",
            "password": "PartnerBeta12345",
        })
        self.assertEqual(no_case.status_code, 400)

        partner_create = admin.post("/api/admin/partners", json={
            "name": "Partner Beta",
            "email": "partner-beta@example.com",
            "password": "PartnerBeta12345",
            "client_id": client_id,
        })
        self.assertEqual(partner_create.status_code, 201, partner_create.get_json())

        # 5. Partner: vede solo la pratica assegnata e non riceve il raw URL del documento.
        partner = self.app.test_client()
        plogin = partner.post("/api/partner/login", json={
            "email": "partner-beta@example.com",
            "password": "PartnerBeta12345",
        })
        self.assertEqual(plogin.status_code, 200, plogin.get_json())

        cases = partner.get("/api/partner/cases")
        self.assertEqual(cases.status_code, 200, cases.get_json())
        self.assertEqual([x["client"]["id"] for x in cases.get_json()["results"]], [client_id])

        docs = partner.get(f"/api/partner/cases/{client_id}/documents")
        self.assertEqual(docs.status_code, 200, docs.get_json())
        row = next(d for d in docs.get_json()["documents"] if d["id"] == document_id)
        self.assertNotIn("url", row)
        self.assertEqual(row["access_url"], f"/api/partner/documents/{document_id}")

        # 6. Accesso effettivo: fail-closed finché manca storage privato autorizzato.
        access = partner.get(row["access_url"])
        self.assertEqual(access.status_code, 409, access.get_json())

        # 7. Audit: il tentativo storage viene tracciato.
        audit = admin.get("/api/staff/audit?limit=100")
        self.assertEqual(audit.status_code, 200, audit.get_json())
        actions = [e["action"] for e in audit.get_json()["events"]]
        self.assertIn("partner_document_storage_block", actions)
        self.assertIn("client_operation_update", actions)


if __name__ == "__main__":
    unittest.main()
