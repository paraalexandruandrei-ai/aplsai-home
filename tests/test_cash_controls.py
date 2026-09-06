import json
import os
import tempfile
import unittest


_tmp = tempfile.NamedTemporaryFile(suffix=".db", delete=False); _tmp.close()
os.environ.update(DATABASE_URL=f"sqlite:///{_tmp.name}", FLASK_ENV="testing", SECRET_KEY="cash-control-test",
                  ADMIN_EMAIL="cash-admin@example.com", ADMIN_PASSWORD="CashAdmin12345")

import app as app_module
from app.staff_accounts import init_staff_accounts
from app.scenarios import init_scenarios
from app.feasibility import init_feasibility
from app.cashflow import init_cashflow
from app.cash_controls import init_cash_controls


class CashControlTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = app_module.create_app(); cls.app.config.update(TESTING=True)
        init_staff_accounts(cls.app, app_module); init_scenarios(cls.app, app_module)
        init_feasibility(cls.app, app_module); init_cashflow(cls.app, app_module); init_cash_controls(cls.app, app_module)
        with cls.app.app_context():
            prop = app_module.Property(ref="SAL-REAL", zone="Roma", price=100000, sqm=80)
            app_module.db.session.add(prop); app_module.db.session.flush()
            Scenario = cls.app.extensions["aplsai_scenarios"]["PropertyScenario"]
            scenario = Scenario(property_id=prop.id, name="Scenario", scenario_type="Equilibrato", status="Da verificare", technical_validation="Da verificare")
            app_module.db.session.add(scenario); app_module.db.session.flush()
            Analysis = cls.app.extensions["aplsai_feasibility"]["FeasibilityAnalysis"]
            assumptions = {k:{"revenue_reduction_percent":i*5,"cost_increase_percent":i*5,"delay_months":i} for i,k in enumerate(("base","prudente","stress","doppio_stress"))}
            analysis = Analysis(property_id=prop.id, scenario_id=scenario.id, name="Analisi SAL", status="Approvata", expected_sale_value=200000, ap_capital=150000, external_financing=0, risk_budget=30000, target_margin_percent=10, base_duration_months=6, assumptions_json=json.dumps(assumptions))
            app_module.db.session.add(analysis); app_module.db.session.flush()
            Plan = cls.app.extensions["aplsai_cashflow"]["CashFlowPlan"]
            plan = Plan(analysis_id=analysis.id, name="Piano SAL", start_month="2026-09", opening_cash=150000, additional_credit_limit=0, status="Approvato")
            app_module.db.session.add(plan); app_module.db.session.commit(); cls.plan_id=plan.id

    @classmethod
    def tearDownClass(cls):
        try: os.unlink(_tmp.name)
        except OSError: pass

    def admin(self):
        with self.app.app_context(): uid=app_module.User.query.filter_by(email="cash-admin@example.com").first().id
        c=self.app.test_client()
        with c.session_transaction() as s: s["uid"],s["nonce"]=uid,"cash"
        return c

    def test_sal_requires_evidence_and_admin_authorization(self):
        c=self.admin(); control=c.put(f"/api/staff/cash-controls/{self.plan_id}",json={"mode":"A - Senza anticipazione","contingency_percent":10,"reserve_months":6}).get_json()["control"]
        self.assertEqual(control["advance_percent"],0); self.assertEqual(control["required_reserve"],10000)
        created=c.post(f"/api/staff/cash-controls/{control['id']}/milestones",json={"number":1,"title":"Consegna fase","deliverable":"Opere verificate","planned_amount":10000})
        self.assertEqual(created.status_code,201); milestone=created.get_json()["control"]["milestones"][0]
        blocked=c.post(f"/api/admin/cash-milestones/{milestone['id']}/authorize",json={}); self.assertEqual(blocked.status_code,409)
        c.patch(f"/api/staff/cash-milestones/{milestone['id']}",json={"status":"Accettata","evidence_ref":"VERBALE-01","critical_defects":""})
        approved=c.post(f"/api/admin/cash-milestones/{milestone['id']}/authorize",json={}); self.assertEqual(approved.status_code,200)
        bad_payment=c.post(f"/api/admin/cash-milestones/{milestone['id']}/paid",json={"amount":10000,"reference":""}); self.assertEqual(bad_payment.status_code,400)
        paid=c.post(f"/api/admin/cash-milestones/{milestone['id']}/paid",json={"amount":10000,"reference":"BONIFICO-01"})
        self.assertEqual(paid.status_code,200); self.assertEqual(paid.get_json()["control"]["paid_total"],10000)

    def test_advance_and_unpaid_titles_limits(self):
        c=self.admin(); response=c.put(f"/api/staff/cash-controls/{self.plan_id}",json={"mode":"B - Anticipazione fino al 40%","advance_percent":41,"unpaid_titles_percent":31})
        self.assertEqual(response.status_code,400)


if __name__ == "__main__": unittest.main()
