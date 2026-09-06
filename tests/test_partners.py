import os
import tempfile
import unittest


_tmp=tempfile.NamedTemporaryFile(suffix=".db",delete=False);_tmp.close()
os.environ.update(DATABASE_URL=f"sqlite:///{_tmp.name}",FLASK_ENV="testing",SECRET_KEY="partner-test",
                  ADMIN_EMAIL="partner-admin@example.com",ADMIN_PASSWORD="PartnerAdmin12345")

import app as app_module
from app.staff_accounts import init_staff_accounts
from app.partners import init_partners


class PartnerRegistryTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app=app_module.create_app();cls.app.config.update(TESTING=True)
        init_staff_accounts(cls.app,app_module);init_partners(cls.app,app_module)

    @classmethod
    def tearDownClass(cls):
        try:os.unlink(_tmp.name)
        except OSError:pass

    def admin(self):
        with self.app.app_context():uid=app_module.User.query.filter_by(email="partner-admin@example.com").first().id
        c=self.app.test_client()
        with c.session_transaction() as s:s["uid"],s["nonce"]=uid,"partner"
        return c

    def test_qualification_and_measured_performance(self):
        c=self.admin();created=c.post("/api/staff/partners",json={"name":"Impresa reale","partner_type":"Impresa"})
        self.assertEqual(created.status_code,201,created.get_json());partner=created.get_json()["partner"]
        blocked=c.post(f"/api/admin/partners/{partner['id']}/decision",json={"status":"Idoneo","note":"Valutata","evidence_ref":"VERBALE-01"})
        self.assertEqual(blocked.status_code,409)
        updated=c.patch(f"/api/staff/partners/{partner['id']}",json={"nda_status":"Firmato","nda_ref":"NDA-01","documents_status":"Verificati","documents_ref":"DOC-01","conflict_declaration":"Nessun conflitto dichiarato"})
        self.assertEqual(updated.status_code,200)
        approved=c.post(f"/api/admin/partners/{partner['id']}/decision",json={"status":"Idoneo","note":"Requisiti verificati","evidence_ref":"VERBALE-01"})
        self.assertEqual(approved.status_code,200,approved.get_json())
        assignment=c.post(f"/api/staff/partners/{partner['id']}/assignments",json={"role":"Opere edili","scope":"Esecuzione da capitolato","quoted_cost":10000,"promised_end_at":"2026-09-10"})
        self.assertEqual(assignment.status_code,201);job=assignment.get_json()["partner"]["assignments"][0]
        c.patch(f"/api/staff/partner-assignments/{job['id']}",json={"status":"Consegnato","final_cost":10500,"extra_cost":500,"delay_cost":200,"nonconformity_cost":100,"operational_cost":50,"actual_end_at":"2026-09-12","quality_validation":"Conforme","documentation_validation":"Conforme","evidence_ref":"VERBALE-LAVORI","critical_defects":1})
        denied=c.post(f"/api/admin/partner-assignments/{job['id']}/accept",json={"note":"Verificato"});self.assertEqual(denied.status_code,409)
        c.patch(f"/api/staff/partner-assignments/{job['id']}",json={"critical_defects":0})
        accepted=c.post(f"/api/admin/partner-assignments/{job['id']}/accept",json={"note":"Prestazione verificata e accettata"})
        self.assertEqual(accepted.status_code,200,accepted.get_json());result=accepted.get_json()["partner"]
        self.assertEqual(result["indicators"]["average_delay_days"],2)
        self.assertEqual(result["indicators"]["supplier_cost_total"],11350)
        self.assertEqual(result["indicators"]["cost_variance"],1350)


if __name__=="__main__":unittest.main()
