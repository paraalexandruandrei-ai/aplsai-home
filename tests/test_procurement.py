import os
import tempfile
import unittest


_tmp = tempfile.NamedTemporaryFile(suffix=".db", delete=False); _tmp.close()
os.environ.update(DATABASE_URL=f"sqlite:///{_tmp.name}", FLASK_ENV="testing", SECRET_KEY="procurement-test",
                  ADMIN_EMAIL="procurement-admin@example.com", ADMIN_PASSWORD="ProcurementAdmin12345")

import app as app_module
from app.staff_accounts import init_staff_accounts
from app.partners import init_partners
from app.procurement import init_procurement


class ProcurementTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = app_module.create_app(); cls.app.config.update(TESTING=True)
        init_staff_accounts(cls.app, app_module); init_partners(cls.app, app_module); init_procurement(cls.app, app_module)

    @classmethod
    def tearDownClass(cls):
        try: os.unlink(_tmp.name)
        except OSError: pass

    def admin(self):
        with self.app.app_context(): uid = app_module.User.query.filter_by(email="procurement-admin@example.com").first().id
        client = self.app.test_client()
        with client.session_transaction() as sess: sess["uid"], sess["nonce"] = uid, "procurement"
        return client

    def test_comparable_offer_tco_review_and_human_decision(self):
        client = self.admin()
        partner = client.post("/api/staff/partners", json={"name":"Software house verificabile", "partner_type":"Software house"}).get_json()["partner"]
        case_response = client.post("/api/staff/procurements", json={"title":"Piattaforma APLSAI", "case_type":"Software e tecnologia",
            "requirement_ref":"MASTER-2026-V2", "common_specification":"Capitolato tecnico comune completo",
            "budget_reference":575000, "budget_source":"Piano Investimenti"})
        self.assertEqual(case_response.status_code, 201, case_response.get_json()); case = case_response.get_json()["case"]
        created = client.post(f"/api/staff/procurements/{case['id']}/offers", json={"partner_id":partner["id"]})
        offer = created.get_json()["case"]["offers"][0]
        blocked = client.post(f"/api/admin/procurement-offers/{offer['id']}/review", json={"status":"Verificata","note":"Controllata","evidence_ref":"VERBALE-1"})
        self.assertEqual(blocked.status_code, 409)
        payload = {"offer_ref":"OFFERTA-1", "modules_detail":"Moduli quotati separatamente", "deliverables":"Risultati e collaudi",
            "duration_days":180, "person_days":420, "profiles_rates":"Profili, giornate e tariffe", "technologies":"Tecnologie dichiarate",
            "dependencies":"Dipendenze dichiarate", "exclusions":"Esclusioni dichiarate", "assumptions":"Assunzioni dichiarate",
            "vat_note":"IVA esclusa", "payment_milestones":"Pagamenti legati ai collaudi", "capacity_status":"Disponibile",
            "capacity_evidence":"Piano risorse firmato", "one_time_cost":100000, "recurring_monthly_cost":1000,
            "maintenance_24m":10000, "cloud_24m":5000, "ai_24m":5000, "licenses_24m":2000,
            "third_party_24m":3000, "subcontractors_24m":1000, "estimated_excluded_costs":4000,
            "repository_aplsai":True, "accounts_aplsai":True, "documentation_transferable":True,
            "third_party_separable":True, "ai_replaceable":True, "exit_clause":True,
            "functional_score":80, "technical_score":70, "ai_data_score":90, "cybersecurity_score":80,
            "ip_score":100, "team_score":70, "capacity_score":60, "tco_score":75, "score_evidence":"GRIGLIA-1"}
        updated = client.patch(f"/api/staff/procurement-offers/{offer['id']}", json=payload)
        self.assertEqual(updated.status_code, 200, updated.get_json()); result = updated.get_json()["case"]["offers"][0]
        self.assertEqual(result["tco_24m"], 154000); self.assertEqual(result["weighted_score"], 79)
        self.assertEqual(result["completeness"], "Completa"); self.assertEqual(result["lock_in_missing"], [])
        reviewed = client.post(f"/api/admin/procurement-offers/{offer['id']}/review", json={"status":"Verificata","note":"Criteri verificati","evidence_ref":"VERBALE-1"})
        self.assertEqual(reviewed.status_code, 200, reviewed.get_json())
        decided = client.post(f"/api/admin/procurements/{case['id']}/decision", json={"offer_id":offer["id"],"note":"Scelta motivata sui risultati complessivi","evidence_ref":"DECISIONE-1"})
        self.assertEqual(decided.status_code, 200, decided.get_json()); self.assertEqual(decided.get_json()["case"]["status"], "Decisa")


if __name__ == "__main__": unittest.main()
