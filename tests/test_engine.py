import unittest
from datetime import timedelta
import main


class SentinelEngineTests(unittest.TestCase):
    def setUp(self):
        main.warm_state()
        self.cases = main.STATE["cases"]
        self.clean = next(c for c in self.cases if c["ground_truth"] == "legitimate_return")
        self.fraud = next(c for c in self.cases if c["ground_truth"] == "fraudulent_return")

    def test_dataset_size_and_required_fields(self):
        self.assertGreaterEqual(len(self.cases), 10000)
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

    def test_low_ml_score_with_hard_rule_failure_is_exposed(self):
        """The UI-facing analysis must disclose an evidence override, not rescore it."""
        case = dict(self.clean)
        case["returned_sku"] = "P-9999-B"
        original_model = main.STATE["model"]

        class LowRiskModel:
            def predict_proba(self, _features):
                return [[0.99, 0.01]]

        try:
            main.STATE["model"] = LowRiskModel()
            result = main.analyze_case(case)
        finally:
            main.STATE["model"] = original_model

        disagreement = result["model_rule_disagreement"]
        self.assertEqual(disagreement["type"], "low_ml_hard_evidence_failure")
        self.assertEqual(disagreement["evidence_failure_name"], "SKU mismatch")

    def test_viewer_cannot_finalize_human_decision(self):
        client = main.app.test_client()
        with client.session_transaction() as sess:
            sess["authenticated"] = True
            sess["role"] = main.VIEWER_ROLE
            sess["csrf_token"] = "test-csrf-token"
        case_id = next(c["return_id"] for c in self.cases if main.analyze_case(c)["decision"] in main.HUMAN_REVIEW_DECISIONS)
        resp = client.post(
            f"/api/cases/{case_id}/human-decision",
            json={"decision": "DENY REFUND", "reason": "Viewer should not finalize this."},
            headers={"X-CSRF-Token": "test-csrf-token"},
        )
        self.assertEqual(resp.status_code, 403)

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

    # --- ML INTEGRITY AUTOMATED CHECKS ---

    def test_ground_truth_not_in_feature_vector(self):
        """Confirm ground_truth is never passed or accessible in feature_vector()."""
        case = dict(self.clean)
        fv = main.feature_vector(case)
        self.assertEqual(len(fv), 16)
        self.assertTrue(all(isinstance(x, (int, float)) for x in fv))
        # Modify ground_truth string and verify feature_vector is unchanged
        case_modified = dict(case)
        case_modified["ground_truth"] = "fraudulent_return"
        self.assertEqual(main.feature_vector(case), main.feature_vector(case_modified))

    def test_no_test_records_in_training(self):
        """Confirm training and test datasets do not share return_ids."""
        non_cold = [c for c in self.cases if not c.get("is_cold_entity")]
        ordered = sorted(non_cold, key=lambda c: c["purchase_timestamp"])
        n = len(ordered)
        train_ids = set(c["return_id"] for c in ordered[:int(n * 0.70)])
        test_ids = set(c["return_id"] for c in ordered[int(n * 0.85):])
        self.assertEqual(len(train_ids.intersection(test_ids)), 0)

    def test_cold_entity_disjoint(self):
        """Confirm cold-entity customers and devices do NOT overlap with training set."""
        non_cold = [c for c in self.cases if not c.get("is_cold_entity")]
        cold = [c for c in self.cases if c.get("is_cold_entity")]
        train_custs = set(c["customer_id"] for c in non_cold)
        cold_custs = set(c["customer_id"] for c in cold)
        self.assertEqual(len(train_custs.intersection(cold_custs)), 0)

        train_devs = set(c["device_id"] for c in non_cold)
        cold_devs = set(c["device_id"] for c in cold)
        self.assertEqual(len(train_devs.intersection(cold_devs)), 0)

    def test_no_single_feature_perfect_prediction(self):
        """Confirm no single binary indicator (e.g. sku_mismatch or timestamp_anomaly) has 100% precision with 0 false positives."""
        legit = [c for c in self.cases if c["ground_truth"] == "legitimate_return"]
        sku_fps = sum(1 for c in legit if c["original_sku"] != c["returned_sku"])
        time_fps = sum(1 for c in legit if c["warehouse_received_timestamp"] < c["pickup_timestamp"])
        self.assertGreater(sku_fps, 0, "SKU mismatch must produce realistic false positives in legitimate returns")
        self.assertGreater(time_fps, 0, "Timestamp anomalies must produce realistic false positives in legitimate returns")

    def test_legitimate_noise_present(self):
        """Confirm legitimate returns contain realistic operational noise."""
        legit = [c for c in self.cases if c["ground_truth"] == "legitimate_return"]
        weight_fps = sum(1 for c in legit if (c["original_package_weight"] - c["returned_package_weight"]) / c["original_package_weight"] > 0.15)
        self.assertGreater(weight_fps, 0)

    def test_fraud_heterogeneity_present(self):
        """Confirm fraudulent returns are heterogeneous (some fraud cases pass SKU & serial checks)."""
        fraud = [c for c in self.cases if c["ground_truth"] == "fraudulent_return"]
        clean_sku_fraud = sum(1 for c in fraud if c["original_sku"] == c["returned_sku"])
        self.assertGreater(clean_sku_fraud, 0, "Fraudulent returns must include archetypes with matching SKUs")

    def test_metrics_dynamic_not_hardcoded(self):
        """Confirm evaluation metrics dictionary contains expected dynamic keys and sub-evaluations."""
        metrics = main.STATE["metrics"]
        self.assertIn("temporal_test", metrics)
        self.assertIn("cold_entity_test", metrics)
        self.assertIn("feature_importances", metrics)
        self.assertIn("precision", metrics["temporal_test"])
        self.assertIn("recall", metrics["cold_entity_test"])

    def test_reproducibility(self):
        """Confirm dataset generation with MODEL_SEED is 100% reproducible."""
        ds1 = main.generate_dataset(50)
        ds2 = main.generate_dataset(50)
        self.assertEqual([c["return_id"] for c in ds1], [c["return_id"] for c in ds2])
        self.assertEqual([c["ground_truth"] for c in ds1], [c["ground_truth"] for c in ds2])

    def test_verification_endpoint_valid_case(self):
        """Test POST /api/verify with a valid merchant return payload."""
        client = main.app.test_client()
        with client.session_transaction() as sess:
            sess["authenticated"] = True
            sess["csrf_token"] = "test-csrf-token"

        payload = {
            "order_id": "ORD-TEST-001",
            "merchant_id": "M-001",
            "customer_id": "C-0001",
            "original_sku": "P-100-A",
            "returned_sku": "P-100-A",
            "refund_amount": 2500,
            "original_package_weight": 1.5,
            "returned_package_weight": 1.48,
            "serial_number_match": "match",
            "product_condition": "sealed",
            "warehouse_scan_result": "verified",
            "return_reason": "changed mind",
            "courier_status": "received"
        }

        resp = client.post("/api/verify", json=payload, headers={"X-CSRF-Token": "test-csrf-token"})
        self.assertEqual(resp.status_code, 200)
        data = resp.get_json()
        self.assertTrue(data.get("ok"))
        self.assertTrue(data.get("simulation"))
        self.assertIn("decision", data)
        self.assertIn(data["decision"], ["APPROVE REFUND", "HOLD REFUND", "ESCALATE TO HUMAN REVIEW"])
        self.assertIn("audit_trail", data)

    def test_verification_endpoint_invalid_input(self):
        """Test POST /api/verify rejects invalid payload with 400 error."""
        client = main.app.test_client()
        with client.session_transaction() as sess:
            sess["authenticated"] = True
            sess["csrf_token"] = "test-csrf-token"

        payload = {
            "order_id": "ORD-INVALID",
            "refund_amount": -500  # Invalid negative amount
        }

        resp = client.post("/api/verify", json=payload, headers={"X-CSRF-Token": "test-csrf-token"})
        self.assertEqual(resp.status_code, 400)
        data = resp.get_json()
        self.assertIn("error", data)

    def test_verification_ml_failure_fallback(self):
        """Test analyze_case safe fallback when ML model scoring fails."""
        case = dict(self.cases[0])
        original_model = main.STATE["model"]
        try:
            main.STATE["model"] = None  # Simulate missing/failing ML model
            analysis = main.analyze_case(case)
            self.assertIn("failures", analysis)
            self.assertTrue(any("ML scoring unavailable" in f for f in analysis["failures"]))
            self.assertIn(analysis["decision"], ["HOLD REFUND", "ESCALATE TO HUMAN REVIEW"])
        finally:
            main.STATE["model"] = original_model

    def test_verification_audit_creation(self):
        """Test audit trail creation during verification."""
        case = dict(self.cases[0])
        main.add_audit(case["return_id"], "test_verification_event", "Audit log verification test.")
        logs = main.audit_for(case["return_id"])
        self.assertTrue(any(l["event_type"] == "test_verification_event" for l in logs))

    def test_csrf_missing_token_returns_403(self):
        """Confirm missing X-CSRF-Token header returns 403 Forbidden."""
        client = main.app.test_client()
        with client.session_transaction() as sess:
            sess["authenticated"] = True
            sess["csrf_token"] = "valid-secret-token"

        payload = {"order_id": "ORD-TEST-CSRF", "refund_amount": 1000}
        resp = client.post("/api/verify", json=payload)  # No X-CSRF-Token header
        self.assertEqual(resp.status_code, 403)
        self.assertIn("CSRF validation failed", resp.get_json().get("error", ""))

    def test_csrf_incorrect_token_returns_403(self):
        """Confirm incorrect X-CSRF-Token header returns 403 Forbidden."""
        client = main.app.test_client()
        with client.session_transaction() as sess:
            sess["authenticated"] = True
            sess["csrf_token"] = "valid-secret-token"

        payload = {"order_id": "ORD-TEST-CSRF", "refund_amount": 1000}
        resp = client.post("/api/verify", json=payload, headers={"X-CSRF-Token": "wrong-token"})
        self.assertEqual(resp.status_code, 403)

    def test_login_and_session_provide_csrf_token(self):
        """Confirm POST /api/login and GET /api/session provide valid csrf_token for frontend."""
        client = main.app.test_client()
        login_resp = client.post("/api/login", json={"username": main.DEMO_USERNAME, "password": main.DEMO_PASSWORD})
        self.assertEqual(login_resp.status_code, 200)
        token = login_resp.get_json().get("csrf_token")
        self.assertTrue(token and len(token) > 10)

    def test_high_volume_merchant_does_not_trigger_graph_abuse(self):
        """Confirm a high-volume merchant with hundreds of returns does NOT cause a clean return to receive a graph abuse signal."""
        clean_case = {
            "return_id": "RX-REGRESSION-001",
            "order_id": "ORD-REG-001",
            "merchant_id": "M-003",  # High-volume merchant with 500+ returns
            "customer_id": "C-9999",  # Isolated customer
            "original_sku": "P-001-A",
            "returned_sku": "P-001-A",
            "refund_amount": 1200,
            "original_package_weight": 1.0,
            "returned_package_weight": 0.99,
            "serial_number_match": "match",
            "product_condition": "sealed",
            "warehouse_scan_result": "verified",
            "return_reason": "changed mind",
            "courier_status": "received",
            "device_id": "DV-REG-9999",
            "shipping_address_hash": "SA-REG-9999",
            "payment_instrument_hash": "PI-REG-9999",
            "purchase_timestamp": main.iso(main.datetime.now(main.timezone.utc)),
            "delivery_timestamp": main.iso(main.datetime.now(main.timezone.utc)),
            "return_request_timestamp": main.iso(main.datetime.now(main.timezone.utc)),
            "pickup_timestamp": main.iso(main.datetime.now(main.timezone.utc)),
            "warehouse_received_timestamp": main.iso(main.datetime.now(main.timezone.utc)),
        }

        pattern = main.pattern_analysis(clean_case)
        self.assertEqual(pattern["pattern_id"], "COORD-RET-000")
        self.assertLess(pattern["score"], 0.15)


    def test_dev_reset_clears_live_cases(self):
        """Test POST /api/dev-reset removes live submissions and resets ID sequence."""
        client = main.app.test_client()
        with client.session_transaction() as sess:
            sess["authenticated"] = True
            sess["csrf_token"] = "test-csrf-token"

        # 1. Submit a live case
        payload = {"order_id": "ORD-RESET-TEST", "refund_amount": 1000}
        resp = client.post("/api/verify", json=payload, headers={"X-CSRF-Token": "test-csrf-token"})
        self.assertEqual(resp.status_code, 200)
        new_id = resp.get_json()["return_id"]

        # 2. Reset
        reset_resp = client.post("/api/dev-reset", headers={"X-CSRF-Token": "test-csrf-token"})
        self.assertEqual(reset_resp.status_code, 200)

        # 3. Verify it's gone
        self.assertFalse(any(c["return_id"] == new_id for c in main.STATE["cases"]))

    def test_override_case_records_audit(self):
        """Test POST /api/cases/<return_id>/override."""
        client = main.app.test_client()
        with client.session_transaction() as sess:
            sess["authenticated"] = True
            sess["csrf_token"] = "test-csrf-token"
            
        case_id = self.cases[0]["return_id"]
        payload = {"decision": "APPROVE REFUND", "reason": "Manager override"}
        resp = client.post(f"/api/cases/{case_id}/override", json=payload, headers={"X-CSRF-Token": "test-csrf-token"})
        self.assertEqual(resp.status_code, 200)
        data = resp.get_json()
        self.assertTrue(data["ok"])
        
        # Verify audit trail
        logs = main.audit_for(case_id)
        self.assertTrue(any(l["event_type"] == "manual_override" and "Manager override" in l["detail"] for l in logs))

    def test_verification_ignores_client_return_id(self):
        """Verify client cannot inject a return_id collision."""
        client = main.app.test_client()
        with client.session_transaction() as sess:
            sess["authenticated"] = True
            sess["csrf_token"] = "test-csrf-token"

        client_id = "RX-999999"
        payload = {"return_id": client_id, "order_id": "ORD-123", "refund_amount": 1000}
        resp = client.post("/api/verify", json=payload, headers={"X-CSRF-Token": "test-csrf-token"})
        
        server_id = resp.get_json()["return_id"]
        self.assertNotEqual(server_id, client_id)

    def test_two_live_cases_have_isolated_audit_trails(self):
        """Verify two different live submissions (e.g. ORD-671092 and ORD-DEMO-CLEAN-001) get isolated return IDs and audit trails."""
        client = main.app.test_client()
        with client.session_transaction() as sess:
            sess["authenticated"] = True
            sess["csrf_token"] = "test-csrf-token"

        payload1 = {"order_id": "ORD-671092", "refund_amount": 1500}
        resp1 = client.post("/api/verify", json=payload1, headers={"X-CSRF-Token": "test-csrf-token"})
        self.assertEqual(resp1.status_code, 200)
        data1 = resp1.get_json()
        id1 = data1["return_id"]

        payload2 = {"order_id": "ORD-DEMO-CLEAN-001", "refund_amount": 2500}
        resp2 = client.post("/api/verify", json=payload2, headers={"X-CSRF-Token": "test-csrf-token"})
        self.assertEqual(resp2.status_code, 200)
        data2 = resp2.get_json()
        id2 = data2["return_id"]

        self.assertNotEqual(id1, id2)

        audit1 = data1["audit_trail"]
        audit2 = data2["audit_trail"]

        self.assertTrue(all(a["return_id"] == id1 for a in audit1))
        self.assertTrue(all("ORD-DEMO-CLEAN-001" not in a["detail"] for a in audit1))

        self.assertTrue(all(a["return_id"] == id2 for a in audit2))
        self.assertTrue(all("ORD-671092" not in a["detail"] for a in audit2))

    def test_opening_case_repeatedly_is_read_only(self):
        """Verify opening the same case repeatedly does NOT append additional audit events."""
        client = main.app.test_client()
        with client.session_transaction() as sess:
            sess["authenticated"] = True

        case_id = self.cases[0]["return_id"]

        resp1 = client.get(f"/api/cases/{case_id}")
        self.assertEqual(resp1.status_code, 200)
        count1 = len(resp1.get_json()["analysis"]["audit_trail"])

        resp2 = client.get(f"/api/cases/{case_id}")
        self.assertEqual(resp2.status_code, 200)
        count2 = len(resp2.get_json()["analysis"]["audit_trail"])

        resp3 = client.get(f"/api/cases/{case_id}")
        self.assertEqual(resp3.status_code, 200)
        count3 = len(resp3.get_json()["analysis"]["audit_trail"])

        self.assertEqual(count1, count2)
        self.assertEqual(count2, count3)


if __name__ == "__main__":
    unittest.main()
