import os
import tempfile
import unittest


_tmp = tempfile.NamedTemporaryFile(suffix=".db", delete=False)
_tmp.close()
os.environ["DATABASE_URL"] = f"sqlite:///{_tmp.name}"
os.environ["FLASK_ENV"] = "testing"
os.environ["SECRET_KEY"] = "investor-test-secret"
os.environ["ADMIN_EMAIL"] = "admin-investors@example.com"
os.environ["ADMIN_PASSWORD"] = "AdminInvestors12345"

import app as app_module
from app.feasibility import init_feasibility
from app.investors import init_investors
from app.operations import init_operations
from app.rbac_runtime import install_runtime_rbac
from app.scenarios import init_scenarios


class InvestorModuleTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = app_module.create_app()
        cls.app.config.update(TESTING=True)
        init_operations(cls.app, app_module)
        install_runtime_rbac(cls.app, app_module)
        init_scenarios(cls.app, app_module)
        init_feasibility(cls.app, app_module)
        init_investors(cls.app, app_module)

    @classmethod
    def tearDownClass(cls):
        try:
            os.unlink(_tmp.name)
        except OSError:
            pass

    def admin(self):
        client = self.app.test_client()
        response = client.post("/api/staff/login", json={
            "email": "admin-investors@example.com",
            "password": "AdminInvestors12345",
        })
        self.assertEqual(response.status_code, 200, response.get_json())
        return client

    def create_analysis(self, client):
        prop = client.post("/api/staff/properties", json={
            "ref": "INV-001", "zone": "Roma Nord", "price": 100000,
            "sqm": 100, "beds": 2, "baths": 1, "state": "Da ristrutturare",
        })
        self.assertEqual(prop.status_code, 201, prop.get_json())
        property_id = prop.get_json()["id"]
        scenario = client.post("/api/staff/scenarios", json={
            "property_id": property_id, "name": "Divisione in due unità",
            "scenario_type": "Equilibrato", "status": "Da verificare",
            "technical_validation": "Da verificare",
        })
        self.assertEqual(scenario.status_code, 201, scenario.get_json())
        scenario_id = scenario.get_json()["scenario"]["id"]
        cost = client.post(f"/api/staff/scenarios/{scenario_id}/cost-items", json={
            "category": "Demolizioni e opere edili", "description": "Lavori",
            "quantity": 1, "unit": "corpo", "unit_price_min": 50000,
            "unit_price_max": 50000, "source": "Preventivo", "reliability": "Documentato",
        })
        self.assertEqual(cost.status_code, 201, cost.get_json())
        assumptions = {
            "base": {"revenue_reduction_percent": 0, "cost_increase_percent": 0, "delay_months": 0},
            "prudente": {"revenue_reduction_percent": 5, "cost_increase_percent": 5, "delay_months": 1},
            "stress": {"revenue_reduction_percent": 10, "cost_increase_percent": 10, "delay_months": 2},
            "doppio_stress": {"revenue_reduction_percent": 20, "cost_increase_percent": 20, "delay_months": 4},
        }
        response = client.post("/api/staff/feasibility", json={
            "property_id": property_id, "scenario_id": scenario_id,
            "name": "Operazione investitori", "status": "Approvata",
            "expected_sale_value": 250000, "other_income": 0,
            "ap_capital": 15000, "external_financing": 50000,
            "risk_budget": 20000, "target_margin_percent": 15,
            "base_duration_months": 12, "assumptions": assumptions,
        })
        self.assertEqual(response.status_code, 201, response.get_json())
        return response.get_json()["analysis"]["id"]

    def test_interest_is_not_coverage_and_confirmed_capital_is(self):
        client = self.admin()
        analysis_id = self.create_analysis(client)
        created = client.post("/api/staff/investors", json={
            "name": "Investitore Uno", "email": "investitore@example.com",
            "available_capital": 150000, "status": "Potenziale",
            "verification": "Da verificare", "nda_signed": False,
        })
        self.assertEqual(created.status_code, 201, created.get_json())
        investor_id = created.get_json()["investor"]["id"]

        interest = client.post("/api/staff/investor-commitments", json={
            "investor_id": investor_id, "analysis_id": analysis_id,
            "amount": 100000, "status": "Manifestazione di interesse",
        })
        self.assertEqual(interest.status_code, 201, interest.get_json())
        self.assertEqual(interest.get_json()["coverage"]["confirmed_investor_capital"], 0)
        self.assertEqual(interest.get_json()["coverage"]["interest_not_counted"], 100000)

        rejected = client.post("/api/staff/investor-commitments", json={
            "investor_id": investor_id, "analysis_id": analysis_id,
            "amount": 100000, "status": "Confermato",
        })
        self.assertEqual(rejected.status_code, 409, rejected.get_json())

        approved = client.patch(f"/api/staff/investors/{investor_id}", json={
            "status": "Approvato", "verification": "Verificato", "nda_signed": True,
        })
        self.assertEqual(approved.status_code, 200, approved.get_json())
        confirmed = client.post("/api/staff/investor-commitments", json={
            "investor_id": investor_id, "analysis_id": analysis_id,
            "amount": 100000, "status": "Confermato", "source": "Contratto firmato",
        })
        self.assertEqual(confirmed.status_code, 201, confirmed.get_json())
        coverage = confirmed.get_json()["coverage"]
        self.assertEqual(coverage["confirmed_investor_capital"], 100000)
        self.assertEqual(coverage["coverage_percent"], 100)
        self.assertEqual(coverage["decision"], "PRONTA PER APPROVAZIONE")

        plan = client.patch(f"/api/staff/investor-funding/{analysis_id}", json={
            "contingency_percent": 10, "status": "Approvato",
        })
        self.assertEqual(plan.status_code, 200, plan.get_json())
        self.assertEqual(plan.get_json()["coverage"]["decision"], "ESEGUIBILE")


if __name__ == "__main__":
    unittest.main()
