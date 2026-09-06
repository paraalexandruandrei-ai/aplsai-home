import json
import os
import tempfile
import unittest


_tmp=tempfile.NamedTemporaryFile(suffix=".db",delete=False);_tmp.close()
os.environ.update(DATABASE_URL=f"sqlite:///{_tmp.name}",FLASK_ENV="testing",SECRET_KEY="launch-test",
                  ADMIN_EMAIL="launch-admin@example.com",ADMIN_PASSWORD="LaunchAdmin12345")

import app as app_module
from app.staff_accounts import init_staff_accounts
from app.scenarios import init_scenarios
from app.feasibility import init_feasibility
from app.launch_control import init_launch_control


class LaunchControlTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app=app_module.create_app();cls.app.config.update(TESTING=True)
        init_staff_accounts(cls.app,app_module);init_scenarios(cls.app,app_module);init_feasibility(cls.app,app_module);init_launch_control(cls.app,app_module)
        with cls.app.app_context():
            prop=app_module.Property(ref="AVVIO-01",zone="Roma",price=100000,sqm=80);app_module.db.session.add(prop);app_module.db.session.flush()
            Scenario=cls.app.extensions["aplsai_scenarios"]["PropertyScenario"]
            scenario=Scenario(property_id=prop.id,name="Scenario",scenario_type="Equilibrato",status="Da verificare",technical_validation="Da verificare");app_module.db.session.add(scenario);app_module.db.session.flush()
            Analysis=cls.app.extensions["aplsai_feasibility"]["FeasibilityAnalysis"]
            assumptions={k:{"revenue_reduction_percent":i*5,"cost_increase_percent":i*5,"delay_months":i} for i,k in enumerate(("base","prudente","stress","doppio_stress"))}
            analysis=Analysis(property_id=prop.id,scenario_id=scenario.id,name="Controllo avvio",status="Approvata",expected_sale_value=200000,ap_capital=150000,external_financing=0,risk_budget=30000,target_margin_percent=10,base_duration_months=6,assumptions_json=json.dumps(assumptions));app_module.db.session.add(analysis);app_module.db.session.commit();cls.analysis_id=analysis.id

    @classmethod
    def tearDownClass(cls):
        try:os.unlink(_tmp.name)
        except OSError:pass

    def admin(self):
        with self.app.app_context():uid=app_module.User.query.filter_by(email="launch-admin@example.com").first().id
        c=self.app.test_client()
        with c.session_transaction() as s:s["uid"],s["nonce"]=uid,"launch"
        return c

    def test_gate_collects_seven_checks_and_blocks_premature_start(self):
        c=self.admin();created=c.post("/api/staff/launch-controls",json={"analysis_id":self.analysis_id})
        self.assertEqual(created.status_code,201,created.get_json());launch=created.get_json()["launch"]
        self.assertEqual(len(launch["checks"]),7);self.assertEqual(launch["status"],"Bloccato")
        denied=c.post(f"/api/admin/launch-controls/{launch['id']}/authorize",json={"note":"Avviare"})
        self.assertEqual(denied.status_code,409);self.assertEqual(denied.get_json()["error"].split(':')[0],"Avvio bloccato")


if __name__=="__main__":unittest.main()
