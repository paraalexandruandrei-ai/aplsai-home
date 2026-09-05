import copy
import unittest

from app.matching_engine import ENGINE_VERSION, evaluate_match


class MatchingEngineTest(unittest.TestCase):
    def setUp(self):
        self.client = {
            "zone": {"main": "Roma Nord", "km": 15},
            "budget": {"ideal": 300000, "max": 330000, "flex": 5},
            "spaces": {"sqm": 80, "beds": 2, "baths": 1},
            "must": ["Ascensore"],
            "houseTypes": ["Appartamento"],
            "timing": "6-12 mesi",
        }
        self.property = {
            "price": 280000, "zone": "Roma Nord", "sqm": 85, "beds": 2, "baths": 1,
            "property_type": "Appartamento", "state": "Chiavi in mano", "elevator": True,
            "outdoor_spaces": "", "parking": "", "exposure": "Sud",
            "planned_works": "", "notes": "", "renovation_cost_min": None,
            "renovation_cost_max": None, "transformation_status": "Da verificare",
            "technical_verification": "Verificato", "data_reliability": "Verificato",
        }

    def test_perfect_current_match_is_explainable(self):
        result = evaluate_match(self.client, self.property)
        self.assertEqual(result["engine_version"], ENGINE_VERSION)
        self.assertEqual(result["score_current"], 100)
        self.assertEqual(result["score_potential"], 100)
        self.assertEqual(sum(row["weight"] for row in result["criteria"]), 100)
        self.assertEqual(result["confidence"], 100)

    def test_transformable_property_improves_space_potential_without_inventing_result(self):
        prop = copy.deepcopy(self.property)
        prop.update({
            "sqm": 60, "beds": 1, "planned_works": "Ridistribuzione interna da progettare",
            "renovation_cost_min": 30000, "renovation_cost_max": 45000,
            "transformation_status": "Trasformabile", "technical_verification": "Da verificare",
        })
        result = evaluate_match(self.client, prop)
        self.assertGreater(result["score_potential"], result["score_current"])
        self.assertIn("Validare la trasformazione con rilievo e progetto tecnico.", result["verifications"])
        sqm = next(row for row in result["criteria"] if row["key"] == "sqm")
        self.assertEqual(sqm["potential_status"], "da_verificare")

    def test_missing_work_costs_keep_total_to_verify(self):
        prop = copy.deepcopy(self.property)
        prop.update({"state": "Da ristrutturare", "planned_works": "Lavori da definire"})
        result = evaluate_match(self.client, prop)
        self.assertIsNone(result["economics"]["known_total_min"])
        self.assertEqual(result["economics"]["potential_status"], "da_verificare")
        self.assertLessEqual(result["confidence"], 40)

    def test_same_inputs_produce_same_result(self):
        first = evaluate_match(copy.deepcopy(self.client), copy.deepcopy(self.property))
        second = evaluate_match(copy.deepcopy(self.client), copy.deepcopy(self.property))
        self.assertEqual(first, second)


if __name__ == "__main__":
    unittest.main()
