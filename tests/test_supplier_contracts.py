import os
import tempfile
import unittest


_tmp=tempfile.NamedTemporaryFile(suffix=".db",delete=False);_tmp.close()
os.environ.update(DATABASE_URL=f"sqlite:///{_tmp.name}",FLASK_ENV="testing",SECRET_KEY="contracts-test",
                  ADMIN_EMAIL="contracts-admin@example.com",ADMIN_PASSWORD="ContractsAdmin12345")

import app as app_module
from app.staff_accounts import init_staff_accounts
from app.partners import init_partners
from app.procurement import init_procurement
from app.supplier_contracts import init_supplier_contracts


class SupplierContractsTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app=app_module.create_app();cls.app.config.update(TESTING=True)
        init_staff_accounts(cls.app,app_module);init_partners(cls.app,app_module)
        init_procurement(cls.app,app_module);init_supplier_contracts(cls.app,app_module)

    @classmethod
    def tearDownClass(cls):
        try:os.unlink(_tmp.name)
        except OSError:pass

    def admin(self):
        with self.app.app_context():uid=app_module.User.query.filter_by(email="contracts-admin@example.com").first().id
        client=self.app.test_client()
        with client.session_transaction() as sess:sess["uid"],sess["nonce"]=uid,"contracts"
        return client

    def decided_procurement(self,client):
        partner=client.post("/api/staff/partners",json={"name":"Fornitore contrattuale","partner_type":"Software house"}).get_json()["partner"]
        case=client.post("/api/staff/procurements",json={"title":"Software APLSAI","case_type":"Software e tecnologia",
            "requirement_ref":"MASTER-V2","common_specification":"Capitolato comune"}).get_json()["case"]
        offer=client.post(f"/api/staff/procurements/{case['id']}/offers",json={"partner_id":partner["id"]}).get_json()["case"]["offers"][0]
        full={"offer_ref":"OFF-1","modules_detail":"Moduli","deliverables":"Risultati","duration_days":180,"person_days":300,
              "profiles_rates":"Profili e tariffe","technologies":"Tecnologie","dependencies":"Dipendenze","exclusions":"Esclusioni",
              "assumptions":"Assunzioni","vat_note":"IVA esclusa","payment_milestones":"Pagamenti a collaudo","capacity_status":"Disponibile",
              "capacity_evidence":"Piano risorse","functional_score":80,"technical_score":80,"ai_data_score":80,"cybersecurity_score":80,
              "ip_score":80,"team_score":80,"capacity_score":80,"tco_score":80,"score_evidence":"GRIGLIA-1"}
        client.patch(f"/api/staff/procurement-offers/{offer['id']}",json=full)
        client.post(f"/api/admin/procurement-offers/{offer['id']}/review",json={"status":"Verificata","note":"Verificata","evidence_ref":"VERBALE-OFFERTA"})
        client.post(f"/api/admin/procurements/{case['id']}/decision",json={"offer_id":offer["id"],"note":"Scelta verificata","evidence_ref":"DECISIONE-1"})
        return case

    def test_contract_start_acceptance_and_payment_gates(self):
        client=self.admin();case=self.decided_procurement(client)
        created=client.post("/api/staff/supplier-contracts",json={"procurement_case_id":case["id"]})
        self.assertEqual(created.status_code,201,created.get_json());contract=created.get_json()["contract"]
        self.assertEqual(len(contract["documents"]),10)
        blocked=client.post(f"/api/admin/supplier-contracts/{contract['id']}/start",json={"note":"Avvio"})
        self.assertEqual(blocked.status_code,409)
        conditions={"contract_ref":"CONTRATTO-1","signed_evidence":"FIRMA-1","requirements_frozen_ref":"REQ-1",
            "golden_cases_ref":"ORO-1","sources_criteria_signed_ref":"CRITERI-1","professional_verification_ref":"PROF-1",
            "ip_assignment_ref":"IP-1","preexisting_components_ref":"PRE-1","repository_control_ref":"REPO-1",
            "cloud_control_ref":"CLOUD-1","credentials_control_ref":"CRED-1","data_control_ref":"DATA-1","exit_plan_ref":"EXIT-1"}
        client.patch(f"/api/staff/supplier-contracts/{contract['id']}",json=conditions)
        started=client.post(f"/api/admin/supplier-contracts/{contract['id']}/start",json={"note":"Condizioni documentate"})
        self.assertEqual(started.status_code,200,started.get_json());self.assertEqual(started.get_json()["contract"]["status"],"Attivo")
        milestone=client.post(f"/api/staff/supplier-contracts/{contract['id']}/milestones",json={"code":"M1","title":"Primo modulo",
            "module_scope":"Modulo operativo","deliverable":"Versione collaudabile","acceptance_criteria":"Casi Oro superati",
            "planned_amount":50000,"due_at":"2026-12-01"}).get_json()["contract"]["milestones"][0]
        client.patch(f"/api/staff/contract-milestones/{milestone['id']}",json={"status":"Consegnata","evidence_ref":"BUILD-1",
            "test_result":"Casi Oro superati","critical_defects":1,"cost_to_complete":0,"requested_amount":50000})
        denied=client.post(f"/api/admin/contract-milestones/{milestone['id']}/accept",json={"note":"Collaudo"});self.assertEqual(denied.status_code,409)
        client.patch(f"/api/staff/contract-milestones/{milestone['id']}",json={"critical_defects":0})
        accepted=client.post(f"/api/admin/contract-milestones/{milestone['id']}/accept",json={"note":"Collaudo verificato"})
        self.assertEqual(accepted.status_code,200,accepted.get_json())
        authorized=client.post(f"/api/admin/contract-milestones/{milestone['id']}/authorize-payment",json={"evidence_ref":"AUT-1"})
        self.assertEqual(authorized.status_code,200,authorized.get_json())
        excessive=client.post(f"/api/admin/contract-milestones/{milestone['id']}/paid",json={"paid_amount":51000,"paid_ref":"BONIFICO-1"})
        self.assertEqual(excessive.status_code,409)
        paid=client.post(f"/api/admin/contract-milestones/{milestone['id']}/paid",json={"paid_amount":50000,"paid_ref":"BONIFICO-1"})
        self.assertEqual(paid.status_code,200,paid.get_json());self.assertEqual(paid.get_json()["contract"]["paid_total"],50000)


if __name__=="__main__":unittest.main()
