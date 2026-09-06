import json
import os
import tempfile
import unittest


_tmp = tempfile.NamedTemporaryFile(suffix=".db", delete=False); _tmp.close()
os.environ.update(DATABASE_URL=f"sqlite:///{_tmp.name}", FLASK_ENV="testing", SECRET_KEY="delivery-test",
                  ADMIN_EMAIL="delivery-admin@example.com", ADMIN_PASSWORD="DeliveryAdmin12345")

import app as app_module
from app.staff_accounts import init_staff_accounts
from app.scenarios import init_scenarios
from app.feasibility import init_feasibility
from app.launch_control import init_launch_control
from app.worksites import init_worksites
from app.deliveries import init_deliveries


class DeliveryTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = app_module.create_app(); cls.app.config.update(TESTING=True)
        init_staff_accounts(cls.app, app_module); init_scenarios(cls.app, app_module); init_feasibility(cls.app, app_module)
        init_launch_control(cls.app, app_module); init_worksites(cls.app, app_module); init_deliveries(cls.app, app_module)
        with cls.app.app_context():
            admin = app_module.User.query.filter_by(email="delivery-admin@example.com").first()
            prop = app_module.Property(ref="CONSEGNA-01", zone="Roma", price=100000, sqm=80); app_module.db.session.add(prop); app_module.db.session.flush()
            Scenario = cls.app.extensions["aplsai_scenarios"]["PropertyScenario"]
            scenario = Scenario(property_id=prop.id, name="Scenario", scenario_type="Equilibrato", status="Da verificare", technical_validation="Da verificare")
            app_module.db.session.add(scenario); app_module.db.session.flush()
            Analysis = cls.app.extensions["aplsai_feasibility"]["FeasibilityAnalysis"]
            assumptions = {k:{"revenue_reduction_percent":i*5,"cost_increase_percent":i*5,"delay_months":i} for i,k in enumerate(("base","prudente","stress","doppio_stress"))}
            analysis = Analysis(property_id=prop.id, scenario_id=scenario.id, name="Analisi consegna", status="Approvata",
                                expected_sale_value=230000, ap_capital=180000, external_financing=0, risk_budget=30000,
                                target_margin_percent=10, base_duration_months=6, assumptions_json=json.dumps(assumptions))
            app_module.db.session.add(analysis); app_module.db.session.flush()
            Launch = cls.app.extensions["aplsai_launch_control"]["OperationLaunch"]
            launch = Launch(analysis_id=analysis.id, status="Autorizzato", final_decision="AVVIO AUTORIZZATO")
            app_module.db.session.add(launch); app_module.db.session.flush()
            Worksite = cls.app.extensions["aplsai_worksites"]["WorksiteProject"]
            Phase = cls.app.extensions["aplsai_worksites"]["WorksitePhase"]
            worksite = Worksite(launch_id=launch.id, analysis_id=analysis.id, name="Cantiere consegnabile", status="Chiuso",
                                responsible_user_id=admin.id, initial_budget=180000, closing_evidence="VERBALE-C", closing_note="Chiuso")
            app_module.db.session.add(worksite); app_module.db.session.flush()
            app_module.db.session.add(Phase(project_id=worksite.id, code="F01", title="Lavori", responsible_user_id=admin.id,
                                            planned_cost=80000, spent_cost=80000, progress_percent=100, status="Approvata",
                                            acceptance_threshold="Conforme", test_result="Superata", evidence_ref="EV-F01",
                                            observed_result="Conforme", technical_validation="Conforme", admin_decision="Approvata"))
            app_module.db.session.commit(); cls.worksite_id = worksite.id

    @classmethod
    def tearDownClass(cls):
        try: os.unlink(_tmp.name)
        except OSError: pass

    def admin(self):
        with self.app.app_context(): uid = app_module.User.query.filter_by(email="delivery-admin@example.com").first().id
        client = self.app.test_client()
        with client.session_transaction() as sess: sess["uid"], sess["nonce"] = uid, "delivery"
        return client

    def test_controlled_delivery_defect_and_final_close(self):
        client = self.admin()
        created = client.post("/api/staff/deliveries", json={"worksite_id":self.worksite_id,"recipient_name":"Cliente reale"})
        self.assertEqual(created.status_code, 201, created.get_json()); delivery = created.get_json()["delivery"]
        updated = client.patch(f"/api/staff/deliveries/{delivery['id']}", json={
            "recipient_name":"Cliente reale", "required_documents":20, "complete_documents":19,
            "technical_documents_ref":"FASCICOLO-TECNICO", "keys_expected":4, "keys_delivered":4,
            "warranty_ref":"GARANZIE-01", "assistance_contact":"AP Lavori",
            "planned_total_cost":180000, "acquisition_cost":100000, "work_cost":70000, "other_cost":10000,
            "final_value":230000, "comprehension_percent":85, "satisfaction_percent":90,
        })
        self.assertEqual(updated.status_code, 200, updated.get_json()); delivery = updated.get_json()["delivery"]
        self.assertEqual(delivery["documents_percent"], 95); self.assertEqual(delivery["final_margin"], 50000)
        for check in delivery["checks"]:
            saved = client.patch(f"/api/staff/delivery-checks/{check['id']}", json={"evidence_ref":f"EV-{check['code']}"})
            self.assertEqual(saved.status_code, 200, saved.get_json())
            verified = client.post(f"/api/admin/delivery-checks/{check['id']}/verify", json={"approved":True,"note":"Verificato"})
            self.assertEqual(verified.status_code, 200, verified.get_json())
        delivered = client.post(f"/api/admin/deliveries/{delivery['id']}/deliver", json={"evidence_ref":"VERBALE-CONSEGNA","note":"Chiavi e fascicolo consegnati"})
        self.assertEqual(delivered.status_code, 200, delivered.get_json())
        defect = client.post(f"/api/staff/deliveries/{delivery['id']}/defects", json={"title":"Regolazione infisso","description":"Intervento necessario","severity":"Critica"})
        self.assertEqual(defect.status_code, 201); defect_id = defect.get_json()["delivery"]["defects"][0]["id"]
        blocked = client.post(f"/api/admin/deliveries/{delivery['id']}/close", json={"note":"Chiudere"}); self.assertEqual(blocked.status_code, 409)
        resolved = client.patch(f"/api/staff/delivery-defects/{defect_id}", json={"status":"Risolto","evidence_ref":"FOTO-01","resolution_note":"Regolato e provato"})
        self.assertEqual(resolved.status_code, 200)
        verified = client.post(f"/api/admin/delivery-defects/{defect_id}/verify", json={}); self.assertEqual(verified.status_code, 200)
        closed = client.post(f"/api/admin/deliveries/{delivery['id']}/close", json={"note":"Operazione conclusa e consuntivo verificato"})
        self.assertEqual(closed.status_code, 200, closed.get_json()); self.assertEqual(closed.get_json()["delivery"]["status"], "Chiusa")


if __name__ == "__main__": unittest.main()
