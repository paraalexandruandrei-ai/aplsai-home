import json
import os
import tempfile
import unittest


_tmp = tempfile.NamedTemporaryFile(suffix=".db", delete=False); _tmp.close()
os.environ.update(DATABASE_URL=f"sqlite:///{_tmp.name}", FLASK_ENV="testing",
                  SECRET_KEY="feasibility-quotes-secret", ADMIN_EMAIL="fq-admin@example.com",
                  ADMIN_PASSWORD="FeasibilityQuotes123")

import app as app_module
from app.operations import init_operations
from app.staff_accounts import init_staff_accounts
from app.scenarios import init_scenarios
from app.feasibility import init_feasibility
from app.pilot_cases import init_pilot_cases
from app.quotes import init_quotes


class FeasibilityQuoteTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = app_module.create_app(); cls.app.config.update(TESTING=True)
        init_operations(cls.app, app_module); init_staff_accounts(cls.app, app_module); init_scenarios(cls.app, app_module)
        init_feasibility(cls.app, app_module); init_pilot_cases(cls.app, app_module); init_quotes(cls.app, app_module)
        with cls.app.app_context():
            prop = app_module.Property(ref="CO01-FQ", zone="Roma", price=200000, sqm=90)
            app_module.db.session.add(prop); app_module.db.session.flush()
            Scenario = cls.app.extensions["aplsai_scenarios"]["PropertyScenario"]
            scenario = Scenario(property_id=prop.id, name="Equilibrato", scenario_type="Equilibrato",
                                status="Da verificare", technical_validation="Da verificare")
            app_module.db.session.add(scenario); app_module.db.session.flush()
            Analysis = cls.app.extensions["aplsai_feasibility"]["FeasibilityAnalysis"]
            assumptions = {k: {"revenue_reduction_percent": i*5, "cost_increase_percent": i*5, "delay_months": i}
                           for i, k in enumerate(("base", "prudente", "stress", "doppio_stress"))}
            analysis = Analysis(property_id=prop.id, scenario_id=scenario.id, name="CO 01", status="Approvata",
                                expected_sale_value=400000, ap_capital=400000, external_financing=0,
                                risk_budget=50000, target_margin_percent=10, base_duration_months=5,
                                assumptions_json=json.dumps(assumptions))
            app_module.db.session.add(analysis); app_module.db.session.flush()
            PilotCase = cls.app.extensions["aplsai_pilot_cases"]["PilotCase"]
            case = PilotCase.query.filter_by(code="CO 01").first()
            case.property_id, case.scenario_id, case.feasibility_id = prop.id, scenario.id, analysis.id
            app_module.db.session.commit(); cls.analysis_id = analysis.id

    @classmethod
    def tearDownClass(cls):
        try: os.unlink(_tmp.name)
        except OSError: pass

    def admin(self):
        with self.app.app_context(): uid = app_module.User.query.filter_by(email="fq-admin@example.com").first().id
        c = self.app.test_client()
        with c.session_transaction() as s: s["uid"], s["nonce"] = uid, "fq"
        return c

    def test_verified_quotes_replace_estimates_and_are_versioned(self):
        c = self.admin(); c.post("/api/staff/quotes/prepare-co01", json={})
        before = c.get(f"/api/staff/feasibility/{self.analysis_id}").get_json()["analysis"]
        self.assertEqual(before["results"]["decision"], "DATI INCOMPLETI")
        for q in c.get("/api/staff/quotes").get_json()["quotes"]:
            c.patch(f"/api/staff/quotes/{q['id']}", json={
                "recipient_company": "Emittente verificato", "offer_at": "2026-09-06T12:00:00Z",
                "offered_total": q["estimate_v1"], "validity": "30 giorni",
                "document_ref": f"DOC-{q['code']}", "notes": "Perimetro completo",
            })
            approved = c.post(f"/api/admin/quotes/{q['id']}/verify", json={"status": "Verificata"})
            self.assertEqual(approved.status_code, 200, approved.get_json())
        after = c.get(f"/api/staff/feasibility/{self.analysis_id}").get_json()["analysis"]
        self.assertTrue(after["results"]["quote_basis"]["applied"])
        self.assertEqual(after["results"]["known_cost_base"], 311000)
        decision = c.post(f"/api/admin/feasibility/{self.analysis_id}/decision", json={
            "decision": "GO", "evidence_ref": "VERBALE-CO01", "cost_to_complete": 0,
        })
        self.assertEqual(decision.status_code, 201, decision.get_json())
        self.assertEqual(decision.get_json()["analysis"]["decisions"][0]["analysis_version"], 1)


if __name__ == "__main__": unittest.main()
