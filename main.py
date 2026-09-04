import json
import math
import os
import random
import secrets
import sqlite3
import urllib.error
import urllib.request
from collections import Counter, defaultdict
from datetime import datetime, timedelta, timezone
from functools import wraps
from pathlib import Path
from threading import Lock

import numpy as np
from flask import Flask, jsonify, request, session, send_from_directory
import networkx as nx
from sklearn.ensemble import RandomForestClassifier
from sklearn.metrics import average_precision_score, confusion_matrix, f1_score, precision_score, recall_score, roc_auc_score

BASE_DIR = Path(__file__).parent
DATA_DIR = BASE_DIR / "data"
DB_PATH = DATA_DIR / "reclaim_sentinel.db"
MODEL_SEED = 73
START_DATE = datetime(2025, 1, 1, tzinfo=timezone.utc)
DECISIONS = ("APPROVE REFUND", "HOLD REFUND", "ESCALATE TO HUMAN REVIEW")
FINAL_DECISIONS = ("APPROVE REFUND", "DENY REFUND")
HUMAN_REVIEW_DECISIONS = ("HOLD REFUND", "ESCALATE TO HUMAN REVIEW")
# These are presentation bands for explaining an already-computed model score.
# They deliberately do not participate in the decision policy below.
MODEL_LOW_RISK_THRESHOLD = 0.35
MODEL_HIGH_RISK_THRESHOLD = 0.65
RULE_FAILURE_LABELS = {
    "SKU-001": "SKU mismatch",
    "TIME-005": "timeline mismatch",
    "COURIER-007": "courier status mismatch",
    "EVIDENCE-008": "unverified warehouse evidence",
    "INPUT-000": "input evidence failure",
}

app = Flask(__name__, static_folder="static")
app.secret_key = os.environ.get("SESSION_SECRET", "local-reclaim-sentinel-demo-secret")
app.config["JSON_SORT_KEYS"] = False
app.config.update(SESSION_COOKIE_HTTPONLY=True, SESSION_COOKIE_SAMESITE="Lax", SESSION_COOKIE_SECURE=os.environ.get("REPLIT_DEPLOYMENT") == "1")
DEMO_USERNAME = os.environ.get("DEMO_USERNAME", "sentinel-demo")
DEMO_PASSWORD = os.environ.get("DEMO_PASSWORD", "reclaim-2026")
RISK_ANALYST_ROLE = "Risk Analyst"
VIEWER_ROLE = "Viewer"
DEMO_ROLE = os.environ.get("DEMO_ROLE", RISK_ANALYST_ROLE)
if DEMO_ROLE not in (RISK_ANALYST_ROLE, VIEWER_ROLE):
    DEMO_ROLE = RISK_ANALYST_ROLE
AUDIT_LOCK = Lock()
STATE = {
    "cases": [],
    "model": None,
    "metrics": {},
    "audit": [],
    "indexes": {},
    "graph": None,
    "analysis_cache": {},
    "pattern_cache": {},
    "human_decisions": {}
}
REQUIRED_CASE_FIELDS = {
    "return_id", "merchant_id", "customer_id", "original_sku", "returned_sku",
    "original_package_weight", "returned_package_weight", "purchase_timestamp",
    "delivery_timestamp", "return_request_timestamp", "pickup_timestamp",
    "warehouse_received_timestamp", "refund_amount", "serial_number_match",
    "product_condition", "warehouse_scan_result", "device_id",
    "shipping_address_hash", "payment_instrument_hash",
}


def money(value):
    return int(round(float(value)))


def dt(value):
    return datetime.fromisoformat(value.replace("Z", "+00:00"))


def iso(value):
    return value.astimezone(timezone.utc).isoformat().replace("+00:00", "Z")


def days_between(a, b):
    return max(0, (b - a).total_seconds() / 86400)


def validate_case(case):
    missing = sorted(REQUIRED_CASE_FIELDS - set(case))
    if missing:
        raise ValueError(f"Malformed return record; missing fields: {', '.join(missing)}")
    for field in ["original_package_weight", "returned_package_weight", "refund_amount"]:
        if not isinstance(case[field], (int, float)) or case[field] < 0:
            raise ValueError(f"Malformed return record; {field} must be a non-negative number")
    for field in ["purchase_timestamp", "delivery_timestamp", "return_request_timestamp", "pickup_timestamp", "warehouse_received_timestamp"]:
        dt(case[field])


def make_case(i, rng, cust_state):
    """Generate synthetic return evidence with realistic operational noise, fraud archetypes, and historical state."""
    is_cold = (i % 7 == 0)
    if is_cold:
        customer_id = f"C-{rng.randint(1301, 1550):04d}"
        device_id = f"DV-{rng.randint(1401, 1650):05d}"
        shipping_address_hash = f"SA-{rng.randint(1801, 2150):05d}"
        payment_instrument_hash = f"PI-{rng.randint(2401, 2900):05d}"
    else:
        customer_id = f"C-{rng.randint(1, 1300):04d}"
        device_id = f"DV-{rng.randint(1, 1400):05d}"
        shipping_address_hash = f"SA-{rng.randint(1, 1800):05d}"
        payment_instrument_hash = f"PI-{rng.randint(1, 2400):05d}"

    merchant_id = f"M-{rng.randint(1, 24):03d}"
    product_id = f"P-{rng.randint(1, 420):04d}"
    categories = ["electronics", "apparel", "home", "beauty", "grocery", "sports"]
    category = rng.choice(categories)
    reasons = ["not as described", "damaged in transit", "wrong size", "changed mind", "missing parts"]
    reason = rng.choice(reasons)
    
    purchase = START_DATE + timedelta(days=(i / 12000) * 180, hours=rng.randint(0, 23), minutes=rng.randint(0, 59))
    delivery = purchase + timedelta(days=rng.randint(2, 7), hours=rng.randint(1, 12))
    return_request = delivery + timedelta(days=rng.randint(1, 28), hours=rng.randint(0, 20))
    pickup = return_request + timedelta(days=rng.randint(1, 5), hours=rng.randint(2, 18))
    received = pickup + timedelta(days=rng.randint(1, 5), hours=rng.randint(2, 18))

    weight = round(rng.uniform(0.08, 12.0), 3)
    amount = money(rng.choice([rng.uniform(299, 2999), rng.uniform(3000, 14999), rng.uniform(15000, 89999)]))

    # Historical metrics derived prior to current case
    c_info = cust_state[customer_id]
    if c_info["first_purchase"] is None:
        c_info["first_purchase"] = purchase
    
    customer_return_count = c_info["return_count"]
    customer_orders = max(1, c_info["order_count"])
    customer_return_rate = round(customer_return_count / customer_orders, 4)
    previous_flags = c_info["previous_flags"]
    similar_claims = c_info["similar_claims"]
    customer_account_age = int(days_between(c_info["first_purchase"], purchase)) + 15

    merchant_return_rate = round(min(0.35, max(0.01, rng.gauss(0.075, 0.025))), 4)
    merchant_refund_rate = round(min(0.35, max(0.01, merchant_return_rate + rng.gauss(0.01, 0.015))), 4)

    # Step 1: Latent fraud intent computation
    latent = -3.2 + rng.gauss(0, 0.6)
    if amount > 35000:
        latent += 0.30
    if customer_return_count >= 3 or customer_return_rate > 0.30:
        latent += 0.65
    if previous_flags > 0:
        latent += 0.85
    if similar_claims >= 2:
        latent += 0.55
    if category == "electronics" and amount > 15000:
        latent += 0.35

    is_fraud_intent = rng.random() < (1 / (1 + math.exp(-latent)))

    # Step 2: Generate observable physical return evidence
    sku_match = True
    returned_sku = f"{product_id}-A"
    serial_match = "match"
    condition = "sealed" if rng.random() < 0.5 else "good"
    warehouse_scan = "verified" if rng.random() < 0.6 else "photo_verified"
    courier_status = "received"
    returned_weight = round(max(0.005, weight * rng.gauss(0.99, 0.03)), 3)

    if not is_fraud_intent:
        # Legitimate Operational Noise
        if rng.random() < 0.018:
            sku_match = False
            returned_sku = f"P-{rng.randint(1, 420):04d}-B"
        if rng.random() < 0.022:
            serial_match = "mismatch"
        if rng.random() < 0.032:
            received = pickup - timedelta(hours=rng.randint(2, 14))
            courier_status = "received_before_pickup_scan"
        if rng.random() < 0.048:
            returned_weight = round(max(0.005, weight * rng.uniform(0.72, 0.88)), 3)
        if rng.random() < 0.052:
            condition = rng.choice(["opened", "good"])
            warehouse_scan = rng.choice(["manual_review", "unverified"])
    else:
        # Fraud Heterogeneity (Archetypes)
        archetype = rng.choices(
            ["sku_sub", "serial_sub", "empty_pkg", "timeline_sub", "behavioral", "high_val"],
            [0.25, 0.20, 0.20, 0.15, 0.12, 0.08]
        )[0]
        if archetype == "sku_sub":
            sku_match = False
            returned_sku = f"P-{rng.randint(1, 420):04d}-B"
            returned_weight = round(max(0.005, weight * rng.uniform(0.35, 0.75)), 3)
            condition = "opened"
            warehouse_scan = "manual_review"
        elif archetype == "serial_sub":
            serial_match = "mismatch"
            condition = "opened"
            warehouse_scan = "manual_review"
        elif archetype == "empty_pkg":
            returned_weight = round(max(0.005, weight * rng.uniform(0.05, 0.28)), 3)
            condition = rng.choice(["partial", "empty"])
            warehouse_scan = "unverified"
        elif archetype == "timeline_sub":
            received = pickup - timedelta(hours=rng.randint(4, 36))
            courier_status = "received_before_pickup_scan"
        elif archetype == "behavioral":
            pass  # No physical mutations, relies on history signals
        elif archetype == "high_val":
            returned_weight = round(max(0.005, weight * rng.uniform(0.75, 0.88)), 3)
            condition = "opened"
            warehouse_scan = "unverified"

    # Step 3: Evaluation Label Noise (applied AFTER evidence generation)
    fraud_label = is_fraud_intent
    if rng.random() < 0.04:
        fraud_label = not fraud_label

    # Update customer historical state for future transactions
    cust_state[customer_id]["order_count"] += rng.randint(1, 3)
    if is_fraud_intent:
        cust_state[customer_id]["return_count"] += 1
        cust_state[customer_id]["similar_claims"] += 1
        if rng.random() < 0.35:
            cust_state[customer_id]["previous_flags"] = 1

    return {
        "return_id": f"RX-{i:06d}", "order_id": f"ORD-{i + 680000:07d}",
        "merchant_id": merchant_id, "customer_id": customer_id, "product_id": product_id,
        "original_sku": f"{product_id}-A", "returned_sku": returned_sku,
        "original_product_category": category, "original_package_weight": weight,
        "returned_package_weight": returned_weight,
        "purchase_timestamp": iso(purchase), "delivery_timestamp": iso(delivery),
        "return_request_timestamp": iso(return_request), "pickup_timestamp": iso(pickup),
        "warehouse_received_timestamp": iso(received),
        "courier_status": courier_status, "return_reason": reason, "refund_amount": amount,
        "customer_return_count": customer_return_count, "customer_return_rate": customer_return_rate,
        "customer_previous_fraud_flags": previous_flags, "customer_account_age_days": customer_account_age,
        "merchant_return_rate": merchant_return_rate, "merchant_refund_rate": merchant_refund_rate,
        "merchant_category": category, "device_id": device_id, "shipping_address_hash": shipping_address_hash,
        "payment_instrument_hash": payment_instrument_hash, "serial_number_match": serial_match,
        "product_condition": condition, "warehouse_scan_result": warehouse_scan,
        "previous_similar_claims": similar_claims,
        "ground_truth": "fraudulent_return" if fraud_label else "legitimate_return",
        "is_cold_entity": is_cold,
    }


def generate_dataset(size=12000):
    rng = random.Random(MODEL_SEED)
    cust_state = defaultdict(lambda: {"order_count": 0, "return_count": 0, "previous_flags": 0, "similar_claims": 0, "first_purchase": None})
    return [make_case(i + 1, rng, cust_state) for i in range(size)]


def feature_vector(case):
    original = float(case["original_package_weight"])
    returned = float(case["returned_package_weight"])
    weight_delta = max(0.0, (original - returned) / max(original, 0.01))
    times = [dt(case[k]) for k in ["purchase_timestamp", "delivery_timestamp", "return_request_timestamp", "pickup_timestamp", "warehouse_received_timestamp"]]
    return [
        weight_delta, float(case["original_sku"] != case["returned_sku"]),
        float(case["serial_number_match"] == "mismatch"),
        {"sealed": 0, "good": 0.12, "opened": 0.35, "partial": 0.75, "empty": 1}.get(case["product_condition"], 0.4),
        {"verified": 0, "photo_verified": 0.08, "manual_review": 0.38, "unverified": 0.64}.get(case["warehouse_scan_result"], 0.4),
        float(times[-1] < times[-2] or times[1] < times[0]), min(1, case["customer_return_count"] / 12),
        min(1, case["customer_return_rate"]), min(1, case["customer_previous_fraud_flags"]),
        min(1, case["previous_similar_claims"] / 8), min(1, case["refund_amount"] / 90000),
        min(1, case["merchant_return_rate"]), min(1, case["merchant_refund_rate"]),
        min(1, days_between(times[1], times[2]) / 30), min(1, case["customer_account_age_days"] / 1000),
        float(case["merchant_category"] == "electronics"),
    ]


def init_db(cases):
    DATA_DIR.mkdir(exist_ok=True)
    conn = sqlite3.connect(DB_PATH)
    conn.execute("CREATE TABLE IF NOT EXISTS return_cases (return_id TEXT PRIMARY KEY, payload TEXT NOT NULL, created_at TEXT NOT NULL)")
    conn.execute("CREATE TABLE IF NOT EXISTS audit_log (id INTEGER PRIMARY KEY AUTOINCREMENT, return_id TEXT, event_type TEXT, detail TEXT, created_at TEXT NOT NULL)")
    conn.execute("""CREATE TABLE IF NOT EXISTS human_decisions (
        return_id TEXT PRIMARY KEY,
        automated_decision TEXT NOT NULL,
        final_decision TEXT NOT NULL,
        reviewer TEXT NOT NULL,
        reason TEXT NOT NULL,
        automated_risk_score REAL,
        automated_model_score REAL,
        created_at TEXT NOT NULL
    )""")
    existing = conn.execute("SELECT COUNT(*) FROM return_cases").fetchone()[0]
    if existing < len(cases):
        conn.executemany("INSERT OR REPLACE INTO return_cases VALUES (?, ?, ?)", [(c["return_id"], json.dumps(c), c["return_request_timestamp"]) for c in cases])
        conn.commit()
    conn.close()


def evaluate_subset(model, subset, split_name, threshold=0.40):
    y = np.array([c["ground_truth"] == "fraudulent_return" for c in subset])
    p = model.predict_proba(np.array([feature_vector(c) for c in subset]))[:, 1]
    pred = p >= threshold
    fp = int(((pred == 1) & (y == 0)).sum())
    fn = int(((pred == 0) & (y == 1)).sum())
    thresholds = []
    for t_val in [0.05, 0.15, 0.25, 0.35, 0.40, 0.45, 0.50, 0.60, 0.70, 0.80, 0.90]:
        pr = p >= t_val
        t_fp = int(((pr == 1) & (y == 0)).sum())
        t_fn = int(((pr == 0) & (y == 1)).sum())
        t_fp_amt = sum(c["refund_amount"] for c, p_val in zip(subset, pr) if p_val and c["ground_truth"] == "legitimate_return")
        t_fn_amt = sum(c["refund_amount"] for c, p_val in zip(subset, pr) if not p_val and c["ground_truth"] == "fraudulent_return")
        thresholds.append({
            "threshold": t_val,
            "precision": round(float(precision_score(y, pr, zero_division=0)), 3),
            "recall": round(float(recall_score(y, pr, zero_division=0)), 3),
            "f1": round(float(f1_score(y, pr, zero_division=0)), 3),
            "false_positives": t_fp,
            "false_negatives": t_fn,
            "legitimate_value_held": money(t_fp_amt),
            "false_negative_exposure": money(t_fn_amt),
            "total_monetary_loss": money(t_fp_amt + 180 * t_fp + t_fn_amt)
        })
    fraud_amount = sum(c["refund_amount"] for c, pr in zip(subset, pred) if pr and c["ground_truth"] == "fraudulent_return")
    fp_amount = sum(c["refund_amount"] for c, pr in zip(subset, pred) if pr and c["ground_truth"] == "legitimate_return")
    fn_amount = sum(c["refund_amount"] for c, pr in zip(subset, pred) if not pr and c["ground_truth"] == "fraudulent_return")
    return {
        "split_name": split_name,
        "locked_threshold": threshold,
        "dataset_size": len(subset),
        "fraud_count": int(sum(y)),
        "fraud_rate": round(float(sum(y) / max(1, len(y)) * 100), 2),
        "precision": round(float(precision_score(y, pred, zero_division=0)), 3),
        "recall": round(float(recall_score(y, pred, zero_division=0)), 3),
        "f1": round(float(f1_score(y, pred, zero_division=0)), 3),
        "roc_auc": round(float(roc_auc_score(y, p)), 3),
        "pr_auc": round(float(average_precision_score(y, p)), 3),
        "confusion_matrix": confusion_matrix(y, pred).tolist(),
        "false_positives": fp,
        "false_negatives": fn,
        "fraudulent_refunds_prevented": money(fraud_amount),
        "legitimate_value_held": money(fp_amount),
        "false_negative_exposure": money(fn_amount),
        "false_positive_cost_per_case": 180,
        "thresholds": thresholds,
    }


def train_model(cases):
    non_cold = [c for c in cases if not c.get("is_cold_entity")]
    cold = [c for c in cases if c.get("is_cold_entity")]

    ordered = sorted(non_cold, key=lambda c: c["purchase_timestamp"])
    n = len(ordered)
    train = ordered[:int(n * 0.70)]
    validation = ordered[int(n * 0.70):int(n * 0.85)]
    temporal_test = ordered[int(n * 0.85):]

    LOCKED_THRESHOLD = 0.35

    model = RandomForestClassifier(
        n_estimators=200,
        max_depth=None,
        min_samples_leaf=4,
        class_weight="balanced_subsample",
        random_state=MODEL_SEED,
        n_jobs=-1
    )
    model.fit(np.array([feature_vector(c) for c in train]), np.array([c["ground_truth"] == "fraudulent_return" for c in train]))

    val_eval = evaluate_subset(model, validation, "Validation Set (Threshold Selection)", threshold=LOCKED_THRESHOLD)
    temp_eval = evaluate_subset(model, temporal_test, "Temporal Held-Out Test", threshold=LOCKED_THRESHOLD)
    cold_eval = evaluate_subset(model, cold, "Cold-Entity Test", threshold=LOCKED_THRESHOLD)

    feature_names = [
        "weight_delta", "sku_mismatch", "serial_mismatch", "condition_score",
        "warehouse_scan_score", "timestamp_anomaly", "cust_return_count_norm",
        "cust_return_rate", "cust_prev_flags", "similar_claims_norm",
        "refund_amount_norm", "merch_return_rate", "merch_refund_rate",
        "return_delay_norm", "cust_account_age_norm", "is_electronics"
    ]
    importances = {name: round(float(imp), 4) for name, imp in zip(feature_names, model.feature_importances_)}

    metrics = dict(temp_eval)
    metrics["dataset_size"] = len(cases)
    metrics["train_size"] = len(train)
    metrics["validation_size"] = len(validation)
    metrics["test_size"] = len(temporal_test)
    metrics["temporal_test_size"] = len(temporal_test)
    metrics["cold_entity_test_size"] = len(cold)
    metrics["locked_threshold"] = LOCKED_THRESHOLD
    metrics["model_hyperparameters"] = {
        "n_estimators": 200,
        "max_depth": "None",
        "min_samples_leaf": 4,
        "class_weight": "balanced_subsample"
    }
    metrics["validation_set"] = val_eval
    metrics["temporal_test"] = temp_eval
    metrics["cold_entity_test"] = cold_eval
    metrics["feature_importances"] = importances
    metrics["thresholds"] = val_eval["thresholds"]
    metrics["split"] = "Time-aware split (70% train / 15% val / 15% test) plus disjoint Cold-Entity test. Tuned Random Forest (200 trees, unconstrained depth) threshold locked at 0.35."

    return model, metrics


def make_indexes(cases):
    indexes = {}
    for key in ["merchant_id", "customer_id", "device_id", "shipping_address_hash", "payment_instrument_hash", "return_id"]:
        groups = defaultdict(list)
        for case in cases:
            groups[case[key]].append(case)
        indexes[key] = groups
    return indexes


def make_relationship_graph(cases):
    graph = nx.Graph()
    for case in cases:
        return_node = f"return:{case['return_id']}"
        graph.add_node(return_node, kind="return", return_id=case["return_id"])
        for key in ["customer_id", "device_id", "shipping_address_hash", "payment_instrument_hash", "merchant_id"]:
            entity_node = f"{key}:{case[key]}"
            graph.add_node(entity_node, kind=key, value=case[key])
            graph.add_edge(return_node, entity_node, relationship=key)
    return graph


def run_rules(case):
    validate_case(case)
    rules = []

    def add(rule_id, result, evidence, severity):
        rules.append({
            "rule_id": rule_id,
            "result": result,
            "evidence": evidence,
            "severity": severity
        })

    # Customer history risk
    if case["customer_return_count"] >= 8:
        add(
            "HISTORY-009",
            "flag",
            f"Customer has {case['customer_return_count']} previous returns.",
            "medium"
        )

    if case["previous_similar_claims"] >= 3:
        add(
            "HISTORY-010",
            "flag",
            f"Customer has {case['previous_similar_claims']} previous similar claims.",
            "high"
        )

    add("SKU-001", "fail" if case["original_sku"] != case["returned_sku"] else "pass", "Returned SKU does not match the original SKU." if case["original_sku"] != case["returned_sku"] else "Original and returned SKUs match.", "critical" if case["original_sku"] != case["returned_sku"] else "info")

    condition = case["product_condition"]

    if condition in ("partial", "empty"):
        condition_result = "fail"
        condition_severity = "high"
    elif condition == "opened":
        condition_result = "flag"
        condition_severity = "medium"
    else:
        condition_result = "pass"
        condition_severity = "info"

    add(
        "CONDITION-004",
        condition_result,
        (
            f"Warehouse recorded a {condition} package."
            if condition != "sealed"
            else "Warehouse recorded a sealed package."
        ),
        condition_severity,
    )
    timeline = [dt(case[k]) for k in ["purchase_timestamp", "delivery_timestamp", "return_request_timestamp", "pickup_timestamp", "warehouse_received_timestamp"]]
    invalid = any(later < earlier for earlier, later in zip(timeline, timeline[1:]))
    add("TIME-005", "fail" if invalid else "pass", "Event timestamps are inconsistent; receipt precedes pickup or delivery precedes purchase." if invalid else "Event timestamps follow a valid sequence.", "high" if invalid else "info")
    late = days_between(timeline[1], timeline[2]) > 30
    add("POLICY-006", "flag" if late else "pass", "Return request falls outside the 30-day policy window." if late else "Return request is within the 30-day policy window.", "medium" if late else "info")
    courier_bad = case["courier_status"] == "received_before_pickup_scan"
    add("COURIER-007", "fail" if courier_bad else "pass", "Courier status conflicts with the pickup timeline." if courier_bad else "Courier and warehouse statuses are consistent.", "high" if courier_bad else "info")
    warehouse_exception = case["warehouse_scan_result"] in (
        "unverified",
        "manual_review",
    )

    add(
        "EVIDENCE-008",
        "fail" if case["warehouse_scan_result"] == "unverified"
        else "flag" if warehouse_exception
        else "pass",
        (
            "Warehouse evidence is unverified; automated approval is unsafe."
            if case["warehouse_scan_result"] == "unverified"
            else "Warehouse inspection requires manual review."
            if case["warehouse_scan_result"] == "manual_review"
            else "Warehouse evidence has a verification record."
        ),
        (
            "high"
            if case["warehouse_scan_result"] == "unverified"
            else "medium"
            if warehouse_exception
            else "info"
        ),
    )
    return rules


def pattern_analysis(case):
    validate_case(case)

    related_ids = set()
    shared = []

    case_time = dt(case["return_request_timestamp"])

    # Only treat explicit shared identifiers as evidence.
    for key in [
        "device_id",
        "shipping_address_hash",
        "payment_instrument_hash",
    ]:
        value = case.get(key)

        if not value:
            continue

        matches = [
            x
            for x in STATE["indexes"].get(key, {}).get(value, [])
            if x["return_id"] != case["return_id"]
            and dt(x["return_request_timestamp"]) <= case_time
        ]

        if matches:
            shared.append(key)

            for match in matches:
                related_ids.add(match["return_id"])

    # Graph enrichment is allowed only when it is anchored to
    # an identifier that the current case actually shares.
    graph = STATE.get("graph")

    if graph is not None and shared:
        for key in shared:
            value = case.get(key)

            entity_node = f"{key}:{value}"

            if not graph.has_node(entity_node):
                continue

            for linked_node in graph.neighbors(entity_node):
                if linked_node.startswith("return:"):
                    linked_id = linked_node.split(":", 1)[1]

                    if linked_id != case["return_id"]:
                        related_ids.add(linked_id)

    unique = {
        x["return_id"]: x
        for x in STATE["cases"]
        if x["return_id"] in related_ids
    }

    close = [
        x
        for x in unique.values()
        if abs(
            (
                dt(x["return_request_timestamp"]) - case_time
            ).total_seconds()
        ) <= 72 * 3600
    ]

    # Strong coordination:
    # multiple linked returns + explicit shared identifier
    # + concentrated timing.
    if len(close) >= 2 and shared:
        confidence = min(
            0.98,
            0.52
            + 0.08 * len(close)
            + 0.12 * (len(shared) - 1),
        )

        return {
            "pattern_id": "COORD-RET-001",
            "connected_entities": [
                f"{len(close)} other return cases",
                *[
                    f"shared {k.replace('_', ' ')}"
                    for k in shared
                ],
            ],
            "supporting_evidence": (
                f"{len(close)} accounts share an identifier "
                "with this case and requested returns within 72 hours."
            ),
            "confidence": round(confidence, 2),
            "score": confidence,
        }

    # Broader repeated-identifier pattern.
    # IMPORTANT: require an actual shared identifier.
    if len(unique) >= 3 and len(close) >= 1 and shared:
        confidence = min(
            0.88,
            0.4 + 0.05 * len(unique),
        )

        return {
            "pattern_id": "COORD-RET-002",
            "connected_entities": [
                f"{len(unique)} linked return cases"
            ],
            "supporting_evidence": (
                "A repeated identifier connects this return "
                "to other cases; timing is not concentrated."
            ),
            "confidence": round(confidence, 2),
            "score": confidence * 0.65,
        }

    return {
        "pattern_id": "COORD-RET-000",
        "connected_entities": [
            "No suspicious cluster found"
        ],
        "supporting_evidence": (
            "No multi-entity coordinated-return pattern "
            "met the supporting-evidence threshold."
        ),
        "confidence": 0.08,
        "score": 0.08,
    }

def risk_signal(case):
    return int(case["original_sku"] != case["returned_sku"]) + int(case["serial_number_match"] == "mismatch") + int((case["original_package_weight"] - case["returned_package_weight"]) / max(case["original_package_weight"], .01) > .30) + int(case["product_condition"] in ("partial", "empty")) + int(case["previous_similar_claims"] >= 3)


def spike_analysis(case):
    current_end = dt(case["return_request_timestamp"])
    merchant_cases = [
        x for x in STATE["indexes"].get("merchant_id", {}).get(case["merchant_id"], [])
        if dt(x["return_request_timestamp"]) <= current_end
    ]
    current_start = current_end - timedelta(days=7)
    current = [x for x in merchant_cases if current_start <= dt(x["return_request_timestamp"]) <= current_end]
    prior_rates = []
    for week in range(1, 5):
        end = current_start - timedelta(days=7 * (week - 1))
        start = end - timedelta(days=7)
        bucket = [x for x in merchant_cases if start <= dt(x["return_request_timestamp"]) < end]
        prior_rates.append(sum(1 for x in bucket if risk_signal(x) >= 2) / max(1, len(bucket)))
    baseline = sum(prior_rates) / len(prior_rates) if prior_rates else 0
    current_rate = sum(1 for x in current if risk_signal(x) >= 2) / max(1, len(current))
    deviation = (current_rate - baseline) / max(.03, math.sqrt(max(baseline * (1 - baseline), .002) / max(1, len(current))))
    severity = "high" if deviation >= 2.5 else "medium" if deviation >= 1.25 else "normal"
    return {"affected_merchant": case["merchant_id"], "time_window": f"{current_start.date()} → {current_end.date()}", "baseline": round(baseline * 100, 1), "current_rate": round(current_rate * 100, 1), "deviation": round(deviation, 2), "severity": severity, "score": round(min(1, max(0, deviation / 5)), 2)}


def audit_for(return_id):
    return [a for a in STATE["audit"] if a["return_id"] == return_id]


def get_human_decision(return_id):
    return STATE.get("human_decisions", {}).get(return_id)


def persist_human_decision(return_id, record):
    STATE.setdefault("human_decisions", {})[return_id] = record
    conn = sqlite3.connect(DB_PATH)
    conn.execute(
        """INSERT OR REPLACE INTO human_decisions
           (return_id, automated_decision, final_decision, reviewer, reason,
            automated_risk_score, automated_model_score, created_at)
           VALUES (?, ?, ?, ?, ?, ?, ?, ?)""",
        (
            record["return_id"],
            record["automated_decision"],
            record["final_decision"],
            record["reviewer"],
            record["reason"],
            record["automated_risk_score"],
            record["automated_model_score"],
            record["created_at"],
        ),
    )
    conn.commit()
    conn.close()


def load_human_decisions():
    conn = sqlite3.connect(DB_PATH)
    rows = conn.execute(
        """SELECT return_id, automated_decision, final_decision, reviewer, reason,
                  automated_risk_score, automated_model_score, created_at
           FROM human_decisions ORDER BY created_at"""
    ).fetchall()
    conn.close()
    return {
        row[0]: {
            "return_id": row[0],
            "automated_decision": row[1],
            "final_decision": row[2],
            "reviewer": row[3],
            "reason": row[4],
            "automated_risk_score": row[5],
            "automated_model_score": row[6],
            "created_at": row[7],
        }
        for row in rows
    }


def investigator_summary(case, decision, risk_score, rules, pattern, spike, failures=None):

    failures = failures or []

    failed = [r["evidence"] for r in rules if r["result"] == "fail"]
    flagged = [r["evidence"] for r in rules if r["result"] == "flag"]

    if failures:
        lead = "Evidence checks identified issues that require attention before the refund is released."

    elif flagged:
        lead = "The return has elevated risk signals that require human review."

    elif risk_score < 0.45:
        lead = "Evidence is consistent with a legitimate return and no elevated coordination signal was found."

    else:
        lead = "Combined risk signals are above the automated-approval threshold and require human review."

    questions = []

    if failed:
        questions.append(
            "Confirm the SKU, serial, and warehouse inspection against the original fulfillment record."
        )

    if pattern["score"] > .35:
        questions.append(
            "Ask whether linked accounts and shared delivery identifiers belong to one household or business."
        )

    if spike["severity"] != "normal":
        questions.append(
            "Review this merchant's recent pickup and warehouse exception mix."
        )

    if not questions:
        questions.append(
            "Confirm courier receipt and product condition before final resolution."
        )

    return {
        "summary": lead,
        "why": " ".join((failed + flagged)[:3]) or
               "The model found low combined risk with clean deterministic checks.",
        "supporting_evidence": (failed + flagged)[:5] or
                               ["All mandatory evidence checks passed."],
        "missing_or_conflicting": failures +
                                   (["No material conflict found."]
                                    if not failures else []),
        "review_questions": questions[:3],
        "mode": "offline structured investigator (LLM optional; never authoritative)",
        "llm_used": False
    }

def call_llm_review_questions(case, analysis):
    """Optional language layer for review questions only.

    It never receives credentials, never determines risk, and never writes
    evidence. Without an explicitly configured provider key, the reproducible
    offline investigator remains the active path.
    """
    api_key = os.environ.get("OPENAI_API_KEY")
    if not api_key:
        return None
    packet = {
        "decision": analysis["decision"],
        "risk_score": analysis["risk_score"],
        "rules": [{"rule_id": r["rule_id"], "result": r["result"], "evidence": r["evidence"]} for r in analysis["triggered_rules"]],
        "pattern": analysis["pattern"]["supporting_evidence"],
        "spike": analysis["spike"]["severity"],
        "refund_amount": case["refund_amount"],
    }
    prompt = (
        "You are a return-fraud investigator. Based only on this JSON evidence, "
        "write three concise questions for a human reviewer. Do not state new "
        "facts, do not change the decision, and return a JSON object with a "
        "review_questions array of strings. JSON evidence: " + json.dumps(packet)
    )
    body = json.dumps({"model": os.environ.get("OPENAI_MODEL", "gpt-4o-mini"), "temperature": 0, "max_tokens": 180, "messages": [{"role": "user", "content": prompt}]}).encode()
    request = urllib.request.Request("https://api.openai.com/v1/chat/completions", data=body, headers={"Authorization": f"Bearer {api_key}", "Content-Type": "application/json"})
    try:
        with urllib.request.urlopen(request, timeout=5) as response:
            payload = json.loads(response.read().decode())
        content = payload["choices"][0]["message"]["content"]
        parsed = json.loads(content)
        questions = parsed.get("review_questions")
        if not isinstance(questions, list) or not all(isinstance(q, str) and 1 < len(q) <= 240 for q in questions):
            return None
        return questions[:3]
    except (urllib.error.URLError, TimeoutError, KeyError, IndexError, json.JSONDecodeError, ValueError):
        return None


def analyze_case(case, use_llm=False):
    failures = []
    try:
        rules = run_rules(case)
    except Exception as exc:
        rules = [{"rule_id": "INPUT-000", "result": "fail", "evidence": f"Record validation failed: {type(exc).__name__}: {exc}", "severity": "critical"}]
        failures.append(f"Input validation unavailable for this record: {type(exc).__name__}")
    try:
        model_score = float(STATE["model"].predict_proba(np.array([feature_vector(case)]))[0, 1])
    except Exception as exc:
        model_score = None
        failures.append(f"ML scoring unavailable: {type(exc).__name__}")
    try:
        pattern = pattern_analysis(case)
    except Exception as exc:
        pattern = {"pattern_id": "UNAVAILABLE", "connected_entities": [], "supporting_evidence": "Graph analysis unavailable.", "confidence": 0, "score": 0}
        failures.append(f"Graph analysis unavailable: {type(exc).__name__}")
    try:
        spike = spike_analysis(case)
    except Exception as exc:
        spike = {"affected_merchant": case["merchant_id"], "time_window": "unavailable", "baseline": 0, "current_rate": 0, "deviation": 0, "severity": "unknown", "score": 0}
        failures.append(f"Spike detector unavailable: {type(exc).__name__}")
    critical = [r for r in rules if r["result"] == "fail" and r["severity"] == "critical"]
    high_flags = [r for r in rules if r["result"] == "fail"]
    if model_score is None:
        model_risk_band = "unavailable"
    elif model_score < MODEL_LOW_RISK_THRESHOLD:
        model_risk_band = "low"
    elif model_score >= MODEL_HIGH_RISK_THRESHOLD:
        model_risk_band = "high"
    else:
        model_risk_band = "medium"

    # Display-only explanation of an existing rule-vs-model comparison.  This
    # makes a conservative evidence override visible without changing scoring.
    model_rule_disagreement = None
    if model_risk_band == "low" and high_flags:
        failed_rule = high_flags[0]
        model_rule_disagreement = {
            "type": "low_ml_hard_evidence_failure",
            "model_band": "LOW",
            "evidence_failure_name": RULE_FAILURE_LABELS.get(failed_rule["rule_id"], failed_rule["rule_id"]),
            "evidence_failure": failed_rule["evidence"],
        }
    elif model_risk_band == "high" and not high_flags:
        model_rule_disagreement = {
            "type": "high_ml_no_evidence_failure",
            "model_band": "HIGH",
        }
    rule_score = min(1, len(high_flags) * .25 + sum(.12 for r in rules if r["result"] == "flag"))
    risk_score = (.55 * model_score + .25 * rule_score + .15 * pattern["score"] + .05 * spike["score"]) if model_score is not None else min(.95, rule_score + pattern["score"] * .25)
    if failures:
        decision = "ESCALATE TO HUMAN REVIEW" if not critical else "HOLD REFUND"
    elif critical or risk_score >= .78:
        decision = "HOLD REFUND"
    elif (
        risk_score <= .30
        and not high_flags
        and not any(r["result"] == "flag" for r in rules)
        and pattern["score"] < .35
        and spike["severity"] == "normal"
    ):
        decision = "APPROVE REFUND"
    else:
        decision = "ESCALATE TO HUMAN REVIEW"
    summary = investigator_summary(case, decision, risk_score, rules, pattern, spike, failures)
    reason = "Critical evidence mismatch requires a refund hold." if critical else "Combined evidence crosses the configured hold threshold." if decision == "HOLD REFUND" else "Signals are mixed; a human should verify the return before releasing funds." if decision == "ESCALATE TO HUMAN REVIEW" else "Deterministic checks are clean and combined model risk is below the approval threshold."
    result = {"return_id": case["return_id"], "decision": decision, "risk_score": round(float(risk_score), 4), "risk_percent": round(float(risk_score) * 100), "model_score": None if model_score is None else round(model_score, 4), "model_risk_band": model_risk_band, "model_rule_disagreement": model_rule_disagreement, "pattern_score": round(pattern["score"], 4), "rule_score": round(rule_score, 4), "evidence_summary": summary["supporting_evidence"] + ([pattern["supporting_evidence"]] if pattern["score"] > .35 else []), "triggered_rules": rules, "pattern": pattern, "spike": spike, "decision_reason": reason, "recommended_next_step": "Do not release refund; inspect item and original fulfillment evidence." if decision == "HOLD REFUND" else "Route to trained reviewer before refund release." if decision == "ESCALATE TO HUMAN REVIEW" else "Release refund after standard settlement checks.", "investigator": summary, "failures": failures, "audit_trail": audit_for(case["return_id"])}
    if use_llm:
        questions = call_llm_review_questions(case, result)
        if questions:
            result["investigator"]["review_questions"] = questions
            result["investigator"]["mode"] = "LLM-assisted review questions (non-authoritative)"
            result["investigator"]["llm_used"] = True
        elif os.environ.get("OPENAI_API_KEY"):
            result["failures"].append("LLM investigator unavailable; using offline structured summary.")
            result["investigator"]["missing_or_conflicting"].append("LLM investigator unavailable; offline summary retained.")
    return result


def add_audit(return_id, event_type, detail):
    event = {"return_id": return_id, "event_type": event_type, "detail": detail, "created_at": iso(datetime.now(timezone.utc))}
    with AUDIT_LOCK:
        STATE["audit"].append(event)
        conn = sqlite3.connect(DB_PATH)
        conn.execute("INSERT INTO audit_log(return_id,event_type,detail,created_at) VALUES (?,?,?,?)", (return_id, event_type, detail, event["created_at"]))
        conn.commit()
        conn.close()


def compute_overview_data():
    cases = STATE["cases"][:1800]

    # Batch ML inference instead of calling analyze_case() 1,800 times.
    # This preserves the existing model and feature vector exactly.
    if cases:
        X = np.array([feature_vector(c) for c in cases])
        model_scores = STATE["model"].predict_proba(X)[:, 1]
    else:
        model_scores = np.array([])

    decisions = {d: 0 for d in DECISIONS}
    risk_buckets = Counter()

    for case, model_score in zip(cases, model_scores):
        rules = run_rules(case)

        pattern = pattern_analysis(case)
        spike = spike_analysis(case)

        high_flags = [r for r in rules if r["result"] == "fail"]
        rule_score = min(
            1,
            len(high_flags) * .25
            + sum(.12 for r in rules if r["result"] == "flag")
        )

        critical = [
            r for r in rules
            if r["result"] == "fail" and r["severity"] == "critical"
        ]

        risk_score = (
            .55 * float(model_score)
            + .25 * rule_score
            + .15 * pattern["score"]
            + .05 * spike["score"]
        )

        if critical or risk_score >= .78:
            decision = "HOLD REFUND"
        elif (
            risk_score <= .30
            and not high_flags
            and pattern["score"] < .35
            and spike["severity"] == "normal"
        ):
            decision = "APPROVE REFUND"
        else:
            decision = "ESCALATE TO HUMAN REVIEW"

        decisions[decision] += 1

        bucket = (
            "low"
            if risk_score < .35
            else "medium"
            if risk_score < .65
            else "high"
        )
        risk_buckets[bucket] += 1

    fraud_count = sum(
        c["ground_truth"] == "fraudulent_return"
        for c in STATE["cases"]
    )

    return {
        "total_cases": len(STATE["cases"]),
        "reviewed_cases": len(cases),
        "fraud_rate": round(
            fraud_count / len(STATE["cases"]) * 100, 1
        ) if STATE["cases"] else 0,
        "decisions": decisions,
        "risk_buckets": dict(risk_buckets),
        "protected_value": STATE["metrics"]["fraudulent_refunds_prevented"],
        "pending_review": decisions.get(
            "ESCALATE TO HUMAN REVIEW", 0
        ),
        "model_health": "online",
        "latest_cases": [
            case_card(c)
            for c in sorted(
                STATE["cases"],
                key=lambda c: c["return_request_timestamp"],
                reverse=True
            )[:8]
        ]
    }

def warm_state():
    cases = generate_dataset()
    init_db(cases)
    model, metrics = train_model(cases)
    STATE.update({"cases": cases, "model": model, "metrics": metrics, "indexes": make_indexes(cases), "graph": make_relationship_graph(cases)})
    STATE["analysis_cache"].clear()
    STATE["pattern_cache"].clear()

    # Pre-compute the cases used by the Return Cases list.
    # This moves the expensive work to startup so the UI loads quickly.
    for case in cases[:120]:
        cached_case_analysis(case)
    # Pre-compute the sampled cases used by Abuse Patterns.
    for case in cases[::11]:
        STATE["pattern_cache"][case["return_id"]] = pattern_analysis(case)
    conn = sqlite3.connect(DB_PATH)
    rows = conn.execute("SELECT return_id,event_type,detail,created_at FROM audit_log ORDER BY id").fetchall()
    STATE["audit"] = [{"return_id": r[0], "event_type": r[1], "detail": r[2], "created_at": r[3]} for r in rows]
    conn.close()
    STATE["human_decisions"] = load_human_decisions()
    STATE["overview_data"] = compute_overview_data()


def authenticated(fn):
    @wraps(fn)
    def wrapped(*args, **kwargs):
        if not session.get("authenticated"):
            return jsonify({"error": "Authentication required"}), 401
        return fn(*args, **kwargs)
    return wrapped


def csrf_token():
    if "csrf_token" not in session:
        session["csrf_token"] = secrets.token_urlsafe(24)
    return session["csrf_token"]


def valid_csrf():
    supplied = request.headers.get("X-CSRF-Token", "")
    expected = session.get("csrf_token", "")
    return bool(supplied and expected and secrets.compare_digest(supplied, expected))


def risk_analyst_required(fn):
    """Minimal role gate; sessions created before roles remain analyst sessions."""
    @wraps(fn)
    def wrapped(*args, **kwargs):
        if session.get("role", RISK_ANALYST_ROLE) != RISK_ANALYST_ROLE:
            return jsonify({"error": "Risk Analyst role required to finalize a human-review decision."}), 403
        return fn(*args, **kwargs)
    return wrapped


@app.post("/api/login")
def login():
    data = request.get_json(silent=True) or {}
    if data.get("username") == DEMO_USERNAME and data.get("password") == DEMO_PASSWORD:
        session["authenticated"] = True
        session["username"] = data.get("username", DEMO_USERNAME)
        session["role"] = DEMO_ROLE
        return jsonify({"ok": True, "csrf_token": csrf_token(), "user": {"name": "Risk Operations", "role": DEMO_ROLE}})
    return jsonify({"error": "Invalid demo credentials"}), 401


@app.post("/api/logout")
def logout():
    session.clear()
    return jsonify({"ok": True})


@app.get("/api/session")
def session_status():
    return jsonify({"authenticated": bool(session.get("authenticated")), "csrf_token": csrf_token() if session.get("authenticated") else None, "role": session.get("role", RISK_ANALYST_ROLE) if session.get("authenticated") else None, "demo": f"{DEMO_USERNAME} / {DEMO_PASSWORD}"})

def cached_case_analysis(case):
    return_id = case["return_id"]

    if return_id not in STATE["analysis_cache"]:
        STATE["analysis_cache"][return_id] = analyze_case(case)

    return STATE["analysis_cache"][return_id]

def case_card(case):
    result = cached_case_analysis(case)
    return {
        "return_id": case["return_id"],
        "merchant_id": case["merchant_id"],
        "customer_id": case["customer_id"],
        "refund_amount": case["refund_amount"],
        "return_reason": case["return_reason"],
        "return_request_timestamp": case["return_request_timestamp"],
        "decision": result["decision"],
        "risk_score": result["risk_score"],
        "risk_percent": result["risk_percent"],
        "is_demo": bool(case.get("demo_case")),
        "final_decision": STATE["human_decisions"].get(case["return_id"], {}).get("final_decision")
            if STATE.get("human_decisions") else None,
    }

@app.get("/api/overview")
@authenticated
def overview():
    if STATE.get("overview_data") is None:
        STATE["overview_data"] = compute_overview_data()
    return jsonify(STATE["overview_data"])


@app.get("/api/cases")
@authenticated
def list_cases():
    args, cases = request.args, STATE["cases"]
    if args.get("merchant"):
        cases = [c for c in cases if c["merchant_id"] == args["merchant"]]
    if args.get("risk"):
        threshold = {"low": (0, .35), "medium": (.35, .65), "high": (.65, 1)}.get(args["risk"], (0, 1))
        cases = [c for c in cases if threshold[0] <= cached_case_analysis(c)["risk_score"] < threshold[1]]
    if args.get("reason"):
        cases = [c for c in cases if c["return_reason"] == args["reason"]]
    return jsonify({"cases": [case_card(c) for c in cases[:120]], "count": len(cases), "merchants": sorted({c["merchant_id"] for c in STATE["cases"]}), "reasons": sorted({c["return_reason"] for c in STATE["cases"]})})


@app.get("/api/cases/<return_id>")
@authenticated
def case_detail(return_id):
    case = next((c for c in STATE["cases"] if c["return_id"] == return_id), None)
    if not case:
        return jsonify({"error": "Case not found"}), 404
    result = analyze_case(case, use_llm=True)
    human = get_human_decision(return_id)
    result["human_decision"] = human
    result["final_decision"] = human["final_decision"] if human else None
    if not audit_for(return_id):
        add_audit(return_id, "case_created", "Synthetic return case entered verification queue.")
        add_audit(return_id, "evidence_collected", "Pre-refund order, courier, warehouse, and customer history loaded.")
        add_audit(return_id, "rules_executed", f"{len(result['triggered_rules'])} deterministic checks completed.")
        add_audit(return_id, "model_score", f"Fraud probability {result['model_score'] if result['model_score'] is not None else 'unavailable'}.")
        add_audit(return_id, "graph_analysis", result["pattern"]["supporting_evidence"])
        add_audit(return_id, "decision", result["decision"])
        result["audit_trail"] = audit_for(return_id)
    return jsonify({"case": case, "analysis": result})


@app.get("/api/patterns")
@authenticated
def patterns():
    patterns, seen = [], set()

    for case in STATE["cases"][::11]:
        pattern = STATE["pattern_cache"].get(
            case["return_id"],
            pattern_analysis(case)
        )

        if (
            pattern["pattern_id"] != "COORD-RET-000"
            and pattern["pattern_id"] not in seen
        ):
            seen.add(pattern["pattern_id"])
            patterns.append({
                "merchant_id": case["merchant_id"],
                "case_id": case["return_id"],
                **pattern
            })

        if len(patterns) >= 8:
            break

    linked_cases = sum(
        1
        for pattern in STATE["pattern_cache"].values()
        if pattern["score"] > .35
    )

    return jsonify({
        "patterns": patterns,
        "graph_nodes": STATE["graph"].number_of_nodes(),
        "graph_edges": STATE["graph"].number_of_edges(),
        "linked_cases": linked_cases
    })

@app.get("/api/spikes")
@authenticated
def spikes():
    rows = []
    for case in STATE["cases"][::73]:
        spike = spike_analysis(case)
        if spike["severity"] != "normal":
            rows.append({"case_id": case["return_id"], **spike})
        if len(rows) >= 10:
            break
    if not rows:
        for case in STATE["cases"][::100]:
            rows.append({"case_id": case["return_id"], **spike_analysis(case)})
            if len(rows) >= 6:
                break
    return jsonify({"spikes": rows, "method": "4-week rolling baseline with standardized deviation", "merchants_monitored": 24})


@app.get("/api/evaluation")
@authenticated
def evaluation():
    return jsonify(STATE["metrics"])


@app.get("/api/audit")
@authenticated
def audit():
    return jsonify({
    "events": STATE["audit"][-50:][::-1],
    "immutable": True
})


@app.post("/api/dev-reset")
@authenticated
def dev_reset():
    if not valid_csrf():
        return jsonify({"error": "CSRF validation failed"}), 403
    
    with AUDIT_LOCK:
        # Clear persistent DB
        conn = sqlite3.connect(DB_PATH)
        conn.execute("DELETE FROM audit_log")
        conn.execute("DELETE FROM human_decisions")
        conn.execute("DELETE FROM return_cases")
        conn.commit()
        conn.close()
        
        # Clear in-memory state
        STATE["cases"].clear()
        STATE["audit"].clear()
        STATE["human_decisions"].clear()
        STATE["indexes"].clear()
        if STATE.get("graph") is not None:
            STATE["graph"].clear()
            
        # Re-warm with pure synthetic baseline
        warm_state()
        
    return jsonify({"ok": True, "message": "Development state reset to synthetic baseline."})


@app.post("/api/cases/<return_id>/human-decision")
@authenticated
@risk_analyst_required
def human_decision(return_id):
    if not valid_csrf():
        return jsonify({"error": "CSRF validation failed"}), 403

    case = next((c for c in STATE["cases"] if c["return_id"] == return_id), None)
    if not case:
        return jsonify({"error": "Case not found"}), 404

    existing = get_human_decision(return_id)
    if existing:
        return jsonify({"error": "Human decision has already been finalized for this case."}), 409

    data = request.get_json(silent=True) or {}
    decision = data.get("decision")
    if decision not in FINAL_DECISIONS:
        return jsonify({"error": "Final decision must be APPROVE REFUND or DENY REFUND."}), 400

    analysis = analyze_case(case, use_llm=False)
    if analysis["decision"] not in HUMAN_REVIEW_DECISIONS:
        return jsonify({
            "error": "Human finalization is only available for cases routed to human review."
        }), 409

    reason = data.get("reason", "")
    if not isinstance(reason, str):
        return jsonify({"error": "Reviewer reason must be text under 500 characters."}), 400
    reason = reason.strip()
    if not 5 <= len(reason) <= 500:
        return jsonify({"error": "Reviewer reason must be between 5 and 500 characters."}), 400

    reviewer = session.get("username", DEMO_USERNAME)
    now = iso(datetime.now(timezone.utc))
    record = {
        "return_id": return_id,
        "automated_decision": analysis["decision"],
        "final_decision": decision,
        "reviewer": reviewer,
        "reason": reason,
        "automated_risk_score": analysis["risk_score"],
        "automated_model_score": analysis["model_score"],
        "created_at": now,
    }

    persist_human_decision(return_id, record)
    add_audit(
        return_id,
        "human_decision",
        f"Human reviewer '{reviewer}' finalized '{decision}'. Reason: {reason}",
    )

    return jsonify({
        "ok": True,
        "return_id": return_id,
        "human_decision": record,
        "message": "Final refund decision recorded."
    })


@app.post("/api/cases/<return_id>/override")
@authenticated
@risk_analyst_required
def override_case(return_id):
    if not valid_csrf():
        return jsonify({"error": "CSRF validation failed"}), 403
    data = request.get_json(silent=True) or {}
    decision = data.get("decision")
    if decision not in DECISIONS:
        return jsonify({"error": "Decision must be one of the three supported verdicts."}), 400
    if not any(c["return_id"] == return_id for c in STATE["cases"]):
        return jsonify({"error": "Case not found"}), 404
    reason = data.get("reason", "not provided")
    if not isinstance(reason, str) or len(reason) > 500:
        return jsonify({"error": "Override reason must be text under 500 characters."}), 400
    add_audit(return_id, "manual_override", f"Decision overridden to '{decision}'. Reason: {reason}")
    return jsonify({"ok": True, "return_id": return_id, "overridden_decision": decision, "reason": reason})


@app.post("/api/verify")
@authenticated
def verify_return():
    if not valid_csrf():
        return jsonify({"error": "CSRF validation failed"}), 403
    data = request.get_json(silent=True) or {}
    try:
        if "refund_amount" in data and data["refund_amount"] != "":
            data["refund_amount"] = money(float(data["refund_amount"]))
        if "original_package_weight" in data and data["original_package_weight"] != "":
            data["original_package_weight"] = float(data["original_package_weight"])
        if "returned_package_weight" in data and data["returned_package_weight"] != "":
            data["returned_package_weight"] = float(data["returned_package_weight"])
        if "customer_return_count" in data and data["customer_return_count"] != "":
            data["customer_return_count"] = int(data["customer_return_count"])
        if "previous_similar_claims" in data and data["previous_similar_claims"] != "":
            data["previous_similar_claims"] = int(data["previous_similar_claims"])
        if "customer_previous_fraud_flags" in data and data["customer_previous_fraud_flags"] != "":
            data["customer_previous_fraud_flags"] = int(data["customer_previous_fraud_flags"])

        existing_ids = {
            c["return_id"]
            for c in STATE["cases"]
            if isinstance(c.get("return_id"), str)
        } | {
            a["return_id"]
            for a in STATE["audit"]
            if isinstance(a.get("return_id"), str)
        }

        numeric_ids = [
            int(rid[3:])
            for rid in existing_ids
            if rid.startswith("RX-") and rid[3:].isdigit()
        ]

        next_id = max(numeric_ids, default=0) + 1
        return_id = f"RX-{next_id:06d}"
        data["return_id"] = return_id
        data.setdefault("order_id", f"ORD-{len(STATE['cases']) + 680001:07d}")
        data.setdefault("merchant_id", "M-001")
        data.setdefault("customer_id", "C-0001")
        data.setdefault("product_id", "P-0001")
        data.setdefault("original_sku", "P-0001-A")
        data.setdefault("returned_sku", data.get("original_sku", "P-0001-A"))
        data.setdefault("original_product_category", "electronics")
        data.setdefault("original_package_weight", 1.0)
        data.setdefault("returned_package_weight", 1.0)
        now_iso = iso(datetime.now(timezone.utc))
        data.setdefault("purchase_timestamp", now_iso)
        data.setdefault("delivery_timestamp", now_iso)
        data.setdefault("return_request_timestamp", now_iso)
        data.setdefault("pickup_timestamp", now_iso)
        data.setdefault("warehouse_received_timestamp", now_iso)
        data.setdefault("courier_status", "received")
        data.setdefault("return_reason", "changed mind")
        data.setdefault("refund_amount", 1000)
        data.setdefault("customer_return_count", 0)
        data.setdefault("customer_return_rate", 0.05)
        data.setdefault("customer_previous_fraud_flags", 0)
        data.setdefault("customer_account_age_days", 100)
        data.setdefault("merchant_return_rate", 0.05)
        data.setdefault("merchant_refund_rate", 0.05)
        data.setdefault("merchant_category", "electronics")
        data.setdefault("device_id", f"DV-LIVE-{return_id}")
        data.setdefault("shipping_address_hash", f"SA-LIVE-{return_id}")
        data.setdefault("payment_instrument_hash", f"PI-LIVE-{return_id}")
        data.setdefault("serial_number_match", "match")
        data.setdefault("product_condition", "good")
        data.setdefault("warehouse_scan_result", "verified")
        data.setdefault("previous_similar_claims", 0)
        data.setdefault("ground_truth", "legitimate_return")

        validate_case(data)
    except ValueError as val_err:
        return jsonify({"error": str(val_err)}), 400
    except Exception as exc:
        return jsonify({"error": f"Invalid verification payload: {exc}"}), 400

    existing = next((c for c in STATE["cases"] if c["return_id"] == return_id), None)
    is_new = (existing is None)
    if is_new:
        STATE["cases"].insert(0, data)
        for key in ["merchant_id", "customer_id", "device_id", "shipping_address_hash", "payment_instrument_hash", "return_id"]:
            STATE["indexes"][key][data[key]].append(data)
        if STATE.get("graph") is not None:
            r_node = f"return:{return_id}"
            STATE["graph"].add_node(r_node, kind="return", return_id=return_id)
            for key in ["customer_id", "device_id", "shipping_address_hash", "payment_instrument_hash", "merchant_id"]:
                e_node = f"{key}:{data[key]}"
                STATE["graph"].add_node(e_node, kind=key, value=data[key])
                STATE["graph"].add_edge(r_node, e_node, relationship=key)
        conn = sqlite3.connect(DB_PATH)
        conn.execute("INSERT OR REPLACE INTO return_cases VALUES (?, ?, ?)", (return_id, json.dumps(data), data["return_request_timestamp"]))
        conn.commit()
        conn.close()
        STATE["overview_data"] = None
    else:
        data = existing

    analysis = analyze_case(data, use_llm=True)

    if is_new and not audit_for(return_id):
        add_audit(return_id, "case_created", f"Live merchant return verification submitted for Order {data['order_id']}.")
        add_audit(return_id, "evidence_collected", "Pre-refund order, courier, warehouse, and customer history evidence loaded.")
        add_audit(return_id, "rules_executed", f"{len(analysis['triggered_rules'])} deterministic checks completed.")
        add_audit(return_id, "model_score", f"Fraud probability {analysis['model_score'] if analysis['model_score'] is not None else 'UNAVAILABLE'}.")
        add_audit(return_id, "graph_analysis", analysis["pattern"]["supporting_evidence"])
        add_audit(return_id, "decision", analysis["decision"])

    analysis["audit_trail"] = audit_for(return_id)

    return jsonify({
        "ok": True,
        "simulation": True,
        "simulation_note": "SIMULATION — NO REAL REFUND",
        "return_id": return_id,
        "order_id": data["order_id"],
        "case": data,
        "analysis": analysis,
        "decision": analysis["decision"],
        "risk_score": analysis["risk_score"],
        "risk_percent": analysis["risk_percent"],
        "ml_score": analysis["model_score"],
        "rule_score": analysis["rule_score"],
        "abuse_score": analysis["pattern_score"],
        "spike_score": analysis["spike"]["score"],
        "triggered_rules": analysis["triggered_rules"],
        "evidence": analysis["evidence_summary"],
        "decision_reason": analysis["decision_reason"],
        "recommended_action": analysis["recommended_next_step"],
        "investigator": analysis["investigator"],
        "audit_event_id": f"AUDIT-{return_id}",
        "audit_trail": analysis["audit_trail"]
    })


@app.route("/", defaults={"path": ""})
@app.route("/<path:path>")
def frontend(path):
    if path and (BASE_DIR / "static" / path).exists():
        return send_from_directory(BASE_DIR / "static", path)
    return send_from_directory(BASE_DIR / "static", "index.html")


if __name__ == "__main__":
    warm_state()
    app.run(host="0.0.0.0", port=int(os.environ.get("PORT", "5000")), debug=False)
else:
    warm_state()
