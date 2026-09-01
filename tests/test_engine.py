import unittest
from datetime import timedelta

import main


class SentinelEngineTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        main.warm_state()
        cls.clean = next(c for c in main.STATE["cases"] if c["ground_truth"] == "legitimate_return")
        cls.fraud = next(c for c in main.STATE["cases"] if c["ground_truth"] == "fraudulent_return")

    def test_dataset_size_and_required_fields(self):
        self.assertGreaterEqual(len(main.STATE["cases"]), 10000)
        required = {"return_id", "original_sku", "returned_sku", "refund_amount", "ground_truth", "device_id"}
        self.assertTrue(required.issubset(self.clean))

    def test_deterministic_rule_catches_wrong_sku(self):
        case = dict(self.clean)
        case["returned_sku"] = "P-9999-B"
        rules = main.run_rules(case)
        self.assertEqual(next(r for r in rules if r["rule_id"] == "SKU-001")["result"], "fail")

    def test_model_inference_returns_probability(self):
        result = main.analyze_case(self.fraud)
        self.assertGreaterEqual(result["risk_score"], 0)
        self.assertLessEqual(result["risk_score"], 1)
        self.assertIn(result["decision"], main.DECISIONS)

    def test_failure_fallback_never_approves(self):
        original = main.STATE["model"]
        main.STATE["model"] = None
        result = main.analyze_case(self.clean)
        self.assertNotEqual(result["decision"], "APPROVE REFUND")
        main.STATE["model"] = original

    def test_malformed_timestamp_is_safe(self):
        case = dict(self.clean)
        case["warehouse_received_timestamp"] = "not-a-timestamp"
        with self.assertRaises(ValueError):
            main.run_rules(case)


if __name__ == "__main__":
    unittest.main()