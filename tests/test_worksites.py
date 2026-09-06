import json
import os
import tempfile
import unittest


_tmp = tempfile.NamedTemporaryFile(suffix=".db", delete=False); _tmp.close()
os.environ.update(DATABASE_URL=f"sqlite:///{_tmp.name}", FLASK_ENV="testing", SECRET_KEY="worksite-test",
                  ADMIN_EMAIL="worksite-admin@example.com", ADMIN_PASSWORD="WorksiteAdmin12345")

import app as app_module
from app.staff_accounts import init_staff_accounts
from app.scenarios import init_scenarios
from app.feasibility import init_feasibility
from app.launch_control import init_launch_control
from app.worksites import init_worksites


class WorksiteTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = app_module.create_app(); cls.app.config.update(TESTING=True)
        init_staff_accounts(cls.app, app_module); init_scenarios(cls.app, app_module)
        init_feasibility(cls.app, app_module); init_launch_control(cls.app, app_module); init_worksites(cls.app, app_module)
        with cls.app.app_context():
            prop = app_module.Property(ref="CANTIERE-01", zone="Roma", price=100000, sqm=80)
            app_module.db.session.add(prop); app_module.db.session.flush()
            Scenario = cls.app.extensions["aplsai_scenarios"]["PropertyScenario"]
            scenario = Scenario(property_id=prop.id, name="Scenario", scenario_type="Equilibrato", status="Da verificare", technical_validation="Da verificare")
            app_module.db.session.add(scenario); app_module.db.session.flush()
            Analysis = cls.app.extensions["aplsai_feasibility"]["FeasibilityAnalysis"]
            assumptions = {k:{"revenue_reduction_percent":i*5,"cost_increase_percent":i*5,"delay_months":i} for i,k in enumerate(("base","prudente","stress","doppio_stress"))}
            analysis = Analysis(property_id=prop.id, scenario_id=scenario.id, name="Analisi cantiere", status="Approvata",
                                expected_sale_value=200000, ap_capital=150000, external_financing=0, risk_budget=30000,
                                target_margin_percent=10, base_duration_months=6, assumptions_json=json.dumps(assumptions))
            app_module.db.session.add(analysis); app_module.db.session.flush()
            Launch = cls.app.extensions["aplsai_launch_control"]["OperationLaunch"]
            authorized = Launch(analysis_id=analysis.id, status="Autorizzato", final_decision="AVVIO AUTORIZZATO")
            app_module.db.session.add(authorized); app_module.db.session.flush()
            other_prop = app_module.Property(ref="CANTIERE-02", zone="Roma", price=90000, sqm=70)
            app_module.db.session.add(other_prop); app_module.db.session.flush()
            other_scenario = Scenario(property_id=other_prop.id, name="Altro", scenario_type="Equilibrato", status="Da verificare", technical_validation="Da verificare")
            app_module.db.session.add(other_scenario); app_module.db.session.flush()
            other_analysis = Analysis(property_id=other_prop.id, scenario_id=other_scenario.id, name="Non autorizzata", status="Bozza",
                                      expected_sale_value=180000, ap_capital=120000, external_financing=0, risk_budget=20000,
                                      target_margin_percent=10, base_duration_months=6, assumptions_json=json.dumps(assumptions))
            app_module.db.session.add(other_analysis); app_module.db.session.flush()
            blocked = Launch(analysis_id=other_analysis.id, final_decision="NON AUTORIZZATO")
            app_module.db.session.add(blocked); app_module.db.session.commit()
            cls.launch_id, cls.blocked_launch_id = authorized.id, blocked.id

    @classmethod
    def tearDownClass(cls):
        try: os.unlink(_tmp.name)
        except OSError: pass

    def admin(self):
        with self.app.app_context(): uid = app_module.User.query.filter_by(email="worksite-admin@example.com").first().id
        client = self.app.test_client()
        with client.session_transaction() as sess: sess["uid"], sess["nonce"] = uid, "worksite"
        return client

    def test_authorized_gate_phase_variation_and_closure(self):
        client = self.admin()
        blocked = client.post("/api/staff/worksites", json={"launch_id": self.blocked_launch_id, "initial_budget": 100000})
        self.assertEqual(blocked.status_code, 409)
        created = client.post("/api/staff/worksites", json={"launch_id": self.launch_id, "name": "Cantiere pilota", "initial_budget": 100000})
        self.assertEqual(created.status_code, 201, created.get_json()); project = created.get_json()["worksite"]
        phase_response = client.post(f"/api/staff/worksites/{project['id']}/phases", json={
            "code":"F01", "title":"Demolizioni", "planned_cost":50000, "committed_cost":45000,
            "spent_cost":10000, "cost_to_complete":45000, "acceptance_threshold":"Verbale tecnico conforme",
        })
        self.assertEqual(phase_response.status_code, 201, phase_response.get_json()); phase = phase_response.get_json()["worksite"]["phases"][0]
        denied = client.post(f"/api/admin/worksite-phases/{phase['id']}/decision", json={"approved":True,"note":"Ok"})
        self.assertEqual(denied.status_code, 409)
        update = client.patch(f"/api/staff/worksite-phases/{phase['id']}", json={
            "status":"In verifica", "progress_percent":100, "spent_cost":48000, "cost_to_complete":0,
            "test_result":"Superata", "observed_result":"Misure entro soglia", "evidence_ref":"VERBALE-F01",
            "technical_validation":"Conforme", "critical_defects":"", "residual_defects":"",
        })
        self.assertEqual(update.status_code, 200, update.get_json())
        approved = client.post(f"/api/admin/worksite-phases/{phase['id']}/decision", json={"approved":True,"note":"Fase verificata"})
        self.assertEqual(approved.status_code, 200, approved.get_json())
        variation = client.post(f"/api/staff/worksites/{project['id']}/variations", json={
            "code":"VAR-01", "description":"Rinforzo aggiuntivo", "reason":"Prescrizione tecnica",
            "cost_impact":60000, "delay_days":10, "margin_impact":-60000, "evidence_ref":"REL-STRUTTURA",
        })
        self.assertEqual(variation.status_code, 201); var = variation.get_json()["worksite"]["variations"][0]
        self.assertIn("varianti da decidere", " ".join(variation.get_json()["worksite"]["alerts"]).lower())
        decided = client.post(f"/api/admin/worksite-variations/{var['id']}/decision", json={"approved":True,"note":"Necessaria per sicurezza"})
        self.assertEqual(decided.status_code, 200); self.assertGreater(decided.get_json()["worksite"]["forecast_final_cost"], 100000)
        closed = client.post(f"/api/admin/worksites/{project['id']}/close", json={"evidence_ref":"VERBALE-FINALE","note":"Collaudo concluso"})
        self.assertEqual(closed.status_code, 200, closed.get_json()); self.assertEqual(closed.get_json()["worksite"]["status"], "Chiuso")


if __name__ == "__main__": unittest.main()
