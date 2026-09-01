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

app = Flask(__name__, static_folder="static")
app.secret_key = os.environ.get("SESSION_SECRET", "local-reclaim-sentinel-demo-secret")
app.config["JSON_SORT_KEYS"] = False
app.config.update(SESSION_COOKIE_HTTPONLY=True, SESSION_COOKIE_SAMESITE="Lax", SESSION_COOKIE_SECURE=os.environ.get("REPLIT_DEPLOYMENT") == "1")
DEMO_USERNAME = os.environ.get("DEMO_USERNAME", "sentinel-demo")
DEMO_PASSWORD = os.environ.get("DEMO_PASSWORD", "reclaim-2026")
AUDIT_LOCK = Lock()
STATE = {"cases": [], "model": None, "metrics": {}, "audit": [], "indexes": {}, "graph": None}
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


def make_case(i, rng):
    """Generate pre-refund synthetic evidence with a noisy multi-signal label."""
    merchant_id = f"M-{rng.randint(1, 24):03d}"
    customer_id = f"C-{rng.randint(1, 1550):04d}"
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
    merchant_return_rate = round(min(0.35, max(0.01, rng.gauss(0.075, 0.025))), 4)
    merchant_refund_rate = round(min(0.35, max(0.01, merchant_return_rate + rng.gauss(0.01, 0.015))), 4)
    customer_return_count = max(0, int(rng.gauss(2.8, 2.2)))
    customer_account_age = max(15, int(rng.gauss(410, 240)))
    customer_return_rate = round(min(0.75, max(0.01, rng.gauss(0.15, 0.1))), 4)
    previous_flags = 1 if rng.random() < 0.035 else 0
    serial_match = "match"
    sku_match = True
    condition = rng.choices(["sealed", "good", "opened", "partial", "empty"], [0.25, 0.39, 0.22, 0.11, 0.03])[0]
    warehouse_scan = rng.choices(["verified", "photo_verified", "manual_review", "unverified"], [0.55, 0.25, 0.12, 0.08])[0]
    similar_claims = max(0, int(rng.gauss(0.5, 0.9)))
    returned_weight = round(max(0.005, weight * rng.gauss(0.98, 0.07)), 3)
    repeated_cluster = rng.random() < 0.042
    if repeated_cluster:
        customer_id = f"C-{rng.randint(1, 75):04d}"
    latent = -3.5 + rng.gauss(0, 0.65)
    if amount > 35000:
        latent += 0.28
    if customer_return_count >= 7 or customer_return_rate > 0.4:
        latent += 0.62
    if previous_flags:
        latent += 0.85
    if similar_claims >= 3:
        latent += 0.58
    if condition in ("partial", "empty"):
        latent += 0.68
    if category == "electronics" and amount > 18000:
        latent += 0.25
    if repeated_cluster:
        latent += 0.62
    # The label has intentional overlap/noise: a legitimate return can look
    # suspicious and a fraudster can submit clean-looking evidence. This keeps
    # held-out metrics honest rather than making one field a perfect proxy.
    fraud = rng.random() < (1 / (1 + math.exp(-latent)))
    if rng.random() < 0.055:
        fraud = not fraud
    if fraud:
        mutations = rng.sample(["sku", "weight", "serial", "condition", "timestamps", "claims"], rng.randint(1, 3))
        if "sku" in mutations:
            sku_match = False
        if "weight" in mutations:
            returned_weight = round(max(0.005, weight * rng.uniform(0.15, 0.57)), 3)
        if "serial" in mutations:
            serial_match = "mismatch"
        if "condition" in mutations:
            condition = rng.choice(["partial", "empty", "opened"])
            warehouse_scan = rng.choice(["manual_review", "unverified"])
        if "timestamps" in mutations:
            received = pickup - timedelta(hours=rng.randint(2, 24))
        if "claims" in mutations:
            similar_claims = max(similar_claims, rng.randint(3, 7))
            customer_return_count = max(customer_return_count, rng.randint(6, 13))
    else:
        if rng.random() < 0.04:
            mutated_field = rng.choice(["sku", "serial", "condition"])
            if mutated_field == "sku":
                returned_weight = round(weight * rng.uniform(0.5, 0.7), 3)
            elif mutated_field == "serial":
                serial_match = "mismatch"
            else:
                condition = "opened"
        if rng.random() < 0.025:
            returned_weight = round(weight * rng.uniform(0.62, 0.78), 3)
        if rng.random() < 0.012:
            condition = "opened"
        if rng.random() < 0.01:
            similar_claims += 2
    device_number = rng.randint(1, 1650 if not repeated_cluster else 100)
    address_number = rng.randint(1, 2150 if not repeated_cluster else 130)
    payment_number = rng.randint(1, 2900 if not repeated_cluster else 180)
    return {
        "return_id": f"RX-{i:06d}", "order_id": f"ORD-{i + 680000:07d}",
        "merchant_id": merchant_id, "customer_id": customer_id, "product_id": product_id,
        "original_sku": f"{product_id}-A", "returned_sku": f"{product_id}-A" if sku_match else f"P-{rng.randint(1, 420):04d}-B",
        "original_product_category": category, "original_package_weight": weight, "returned_package_weight": returned_weight,
        "purchase_timestamp": iso(purchase), "delivery_timestamp": iso(delivery), "return_request_timestamp": iso(return_request),
        "pickup_timestamp": iso(pickup), "warehouse_received_timestamp": iso(received),
        "courier_status": "received" if received >= pickup else "received_before_pickup_scan",
        "return_reason": reason, "refund_amount": amount, "customer_return_count": customer_return_count,
        "customer_return_rate": customer_return_rate, "customer_previous_fraud_flags": previous_flags,
        "customer_account_age_days": customer_account_age, "merchant_return_rate": merchant_return_rate,
        "merchant_refund_rate": merchant_refund_rate, "merchant_category": category,
        "device_id": f"DV-{device_number:05d}", "shipping_address_hash": f"SA-{address_number:05d}",
        "payment_instrument_hash": f"PI-{payment_number:05d}", "serial_number_match": serial_match,
        "product_condition": condition, "warehouse_scan_result": warehouse_scan,
        "previous_similar_claims": similar_claims, "ground_truth": "fraudulent_return" if fraud else "legitimate_return",
    }


def generate_dataset(size=12000):
    rng = random.Random(MODEL_SEED)
    return [make_case(i + 1, rng) for i in range(size)]


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
        float(case["merchant_category"] == "electronics"), 1 / 3,
    ]


def init_db(cases):
    DATA_DIR.mkdir(exist_ok=True)
    conn = sqlite3.connect(DB_PATH)
    conn.execute("CREATE TABLE IF NOT EXISTS return_cases (return_id TEXT PRIMARY KEY, payload TEXT NOT NULL, created_at TEXT NOT NULL)")
    conn.execute("CREATE TABLE IF NOT EXISTS audit_log (id INTEGER PRIMARY KEY AUTOINCREMENT, return_id TEXT, event_type TEXT, detail TEXT, created_at TEXT NOT NULL)")
    existing = conn.execute("SELECT COUNT(*) FROM return_cases").fetchone()[0]
    if existing < len(cases):
        conn.executemany("INSERT OR REPLACE INTO return_cases VALUES (?, ?, ?)", [(c["return_id"], json.dumps(c), c["return_request_timestamp"]) for c in cases])
        conn.commit()
    conn.close()


def train_model(cases):
    ordered = sorted(cases, key=lambda c: c["purchase_timestamp"])
    n = len(ordered)
    train, validation, test = ordered[:int(n * .70)], ordered[int(n * .70):int(n * .85)], ordered[int(n * .85):]
    model = RandomForestClassifier(n_estimators=140, max_depth=9, min_samples_leaf=4, class_weight="balanced_subsample", random_state=MODEL_SEED, n_jobs=-1)
    model.fit(np.array([feature_vector(c) for c in train]), np.array([c["ground_truth"] == "fraudulent_return" for c in train]))
    test_y = np.array([c["ground_truth"] == "fraudulent_return" for c in test])
    test_p = model.predict_proba(np.array([feature_vector(c) for c in test]))[:, 1]
    test_pred = test_p >= .5
    fp = int(((test_pred == 1) & (test_y == 0)).sum())
    fn = int(((test_pred == 0) & (test_y == 1)).sum())
    thresholds = []
    for threshold in [.25, .35, .45, .50, .60, .70, .80]:
        pred = test_p >= threshold
        thresholds.append({"threshold": threshold, "precision": round(float(precision_score(test_y, pred, zero_division=0)), 3), "recall": round(float(recall_score(test_y, pred, zero_division=0)), 3), "f1": round(float(f1_score(test_y, pred, zero_division=0)), 3), "false_positives": int(((pred == 1) & (test_y == 0)).sum()), "false_negatives": int(((pred == 0) & (test_y == 1)).sum())})
    fraud_amount = sum(c["refund_amount"] for c, p in zip(test, test_pred) if p and c["ground_truth"] == "fraudulent_return")
    fp_amount = sum(c["refund_amount"] for c, p in zip(test, test_pred) if p and c["ground_truth"] == "legitimate_return")
    fn_amount = sum(c["refund_amount"] for c, p in zip(test, test_pred) if not p and c["ground_truth"] == "fraudulent_return")
    metrics = {
        "dataset_size": len(cases), "train_size": len(train), "validation_size": len(validation), "test_size": len(test),
        "fraud_rate": round(sum(test_y) / len(test_y) * 100, 2), "precision": round(float(precision_score(test_y, test_pred, zero_division=0)), 3),
        "recall": round(float(recall_score(test_y, test_pred, zero_division=0)), 3), "f1": round(float(f1_score(test_y, test_pred, zero_division=0)), 3),
        "roc_auc": round(float(roc_auc_score(test_y, test_p)), 3), "pr_auc": round(float(average_precision_score(test_y, test_p)), 3),
        "confusion_matrix": confusion_matrix(test_y, test_pred).tolist(), "false_positives": fp, "false_negatives": fn,
        "fraudulent_refunds_prevented": money(fraud_amount), "legitimate_value_held": money(fp_amount), "false_negative_exposure": money(fn_amount),
        "false_positive_cost_per_case": 180, "thresholds": thresholds,
        "split": "Time-aware: first 70% purchase time train, next 15% validation, final 15% untouched held-out test.",
    }
    return model, metrics


def make_indexes(cases):
    indexes = {}
    for key in ["merchant_id", "customer_id", "device_id", "shipping_address_hash", "payment_instrument_hash"]:
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
        rules.append({"rule_id": rule_id, "result": result, "evidence": evidence, "severity": severity})
    add("SKU-001", "fail" if case["original_sku"] != case["returned_sku"] else "pass", "Returned SKU does not match the original SKU." if case["original_sku"] != case["returned_sku"] else "Original and returned SKUs match.", "critical" if case["original_sku"] != case["returned_sku"] else "info")
    weight_delta = (case["original_package_weight"] - case["returned_package_weight"]) / max(case["original_package_weight"], .01)
    add("WEIGHT-002", "fail" if weight_delta > .30 else "flag" if weight_delta > .18 else "pass", f"Returned package is {round(weight_delta * 100)}% lighter than the original shipment." if weight_delta > .30 else f"Package weight is {round(weight_delta * 100)}% below the original." if weight_delta > .18 else "Package weight is within verification tolerance.", "high" if weight_delta > .30 else "medium" if weight_delta > .18 else "info")
    add("SERIAL-003", "fail" if case["serial_number_match"] == "mismatch" else "pass", "Serial number does not match the sold unit." if case["serial_number_match"] == "mismatch" else "Serial number matches the sold unit.", "critical" if case["serial_number_match"] == "mismatch" else "info")
    add("CONDITION-004", "fail" if case["product_condition"] in ("partial", "empty") else "pass", f"Warehouse recorded a {case['product_condition']} package.", "high" if case["product_condition"] in ("partial", "empty") else "info")
    timeline = [dt(case[k]) for k in ["purchase_timestamp", "delivery_timestamp", "return_request_timestamp", "pickup_timestamp", "warehouse_received_timestamp"]]
    invalid = any(later < earlier for earlier, later in zip(timeline, timeline[1:]))
    add("TIME-005", "fail" if invalid else "pass", "Event timestamps are inconsistent; receipt precedes pickup or delivery precedes purchase." if invalid else "Event timestamps follow a valid sequence.", "high" if invalid else "info")
    late = days_between(timeline[1], timeline[2]) > 30
    add("POLICY-006", "flag" if late else "pass", "Return request falls outside the 30-day policy window." if late else "Return request is within the 30-day policy window.", "medium" if late else "info")
    courier_bad = case["courier_status"] == "received_before_pickup_scan"
    add("COURIER-007", "fail" if courier_bad else "pass", "Courier status conflicts with the pickup timeline." if courier_bad else "Courier and warehouse statuses are consistent.", "high" if courier_bad else "info")
    unverified = case["warehouse_scan_result"] == "unverified"
    add("EVIDENCE-008", "flag" if unverified else "pass", "Warehouse evidence is unverified; automated approval is unsafe." if unverified else "Warehouse evidence has a verification record.", "medium" if unverified else "info")
    return rules


def pattern_analysis(case):
    validate_case(case)
    related_ids, shared = set(), []
    case_time = dt(case["return_request_timestamp"])
    for key in ["device_id", "shipping_address_hash", "payment_instrument_hash"]:
        matches = [
            x for x in STATE["indexes"].get(key, {}).get(case[key], [])
            if x["return_id"] != case["return_id"] and dt(x["return_request_timestamp"]) <= case_time
        ]
        if matches:
            shared.append(key)
    graph = STATE.get("graph")
    if graph is not None:
        return_node = f"return:{case['return_id']}"
        if graph.has_node(return_node):
            for entity_node in graph.neighbors(return_node):
                for linked_node in graph.neighbors(entity_node):
                    if linked_node.startswith("return:") and linked_node != return_node:
                        related_ids.add(linked_node.split(":", 1)[1])
    unique = {x["return_id"]: x for x in STATE["cases"] if x["return_id"] in related_ids}
    close = [x for x in unique.values() if abs((dt(x["return_request_timestamp"]) - case_time).total_seconds()) <= 72 * 3600]
    if len(close) >= 2 and shared:
        confidence = min(.98, .52 + .08 * len(close) + .12 * (len(shared) - 1))
        return {"pattern_id": "COORD-RET-001", "connected_entities": [f"{len(close)} other return cases", *[f"shared {k.replace('_', ' ')}" for k in shared]], "supporting_evidence": f"{len(close)} accounts share an identifier with this case and requested returns within 72 hours.", "confidence": round(confidence, 2), "score": confidence}
    if len(unique) >= 3:
        confidence = min(.88, .4 + .05 * len(unique))
        return {"pattern_id": "COORD-RET-002", "connected_entities": [f"{len(unique)} linked return cases"], "supporting_evidence": "A repeated identifier connects this return to other cases; timing is not concentrated.", "confidence": round(confidence, 2), "score": confidence * .65}
    return {"pattern_id": "COORD-RET-000", "connected_entities": ["No suspicious cluster found"], "supporting_evidence": "No multi-entity coordinated-return pattern met the supporting-evidence threshold.", "confidence": .08, "score": .08}


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


def investigator_summary(case, decision, risk_score, rules, pattern, spike, failures=None):
    failures = failures or []
    failed = [r["evidence"] for r in rules if r["result"] == "fail"]
    flagged = [r["evidence"] for r in rules if r["result"] == "flag"]
    if failures or (not failed and not flagged and risk_score < .45):
        lead = "Insufficient evidence for an automated decision."
    elif decision == "HOLD REFUND":
        lead = "The return has contradictory evidence that makes releasing the refund unsafe."
    elif decision == "APPROVE REFUND":
        lead = "Evidence is consistent with a legitimate return and no elevated coordination signal was found."
    else:
        lead = "Signals conflict or are not strong enough for an automatic money decision."
    questions = []
    if failed:
        questions.append("Confirm the SKU, serial, and warehouse inspection against the original fulfillment record.")
    if pattern["score"] > .35:
        questions.append("Ask whether linked accounts and shared delivery identifiers belong to one household or business.")
    if spike["severity"] != "normal":
        questions.append("Review this merchant's recent pickup and warehouse exception mix.")
    if not questions:
        questions.append("Confirm courier receipt and product condition before final resolution.")
    return {"summary": lead, "why": " ".join((failed + flagged)[:3]) or "The model found low combined risk with clean deterministic checks.", "supporting_evidence": (failed + flagged)[:5] or ["All mandatory evidence checks passed."], "missing_or_conflicting": failures + (["No material conflict found."] if not failures else []), "review_questions": questions[:3], "mode": "offline structured investigator (LLM optional; never authoritative)", "llm_used": False}


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
    rule_score = min(1, len(high_flags) * .25 + sum(.12 for r in rules if r["result"] == "flag"))
    risk_score = (.55 * model_score + .25 * rule_score + .15 * pattern["score"] + .05 * spike["score"]) if model_score is not None else min(.95, rule_score + pattern["score"] * .25)
    if failures:
        decision = "ESCALATE TO HUMAN REVIEW" if not critical else "HOLD REFUND"
    elif critical or risk_score >= .78:
        decision = "HOLD REFUND"
    elif risk_score <= .30 and not high_flags and pattern["score"] < .35 and spike["severity"] == "normal":
        decision = "APPROVE REFUND"
    else:
        decision = "ESCALATE TO HUMAN REVIEW"
    summary = investigator_summary(case, decision, risk_score, rules, pattern, spike, failures)
    reason = "Critical evidence mismatch requires a refund hold." if critical else "Combined evidence crosses the configured hold threshold." if decision == "HOLD REFUND" else "Signals are mixed; a human should verify the return before releasing funds." if decision == "ESCALATE TO HUMAN REVIEW" else "Deterministic checks are clean and combined model risk is below the approval threshold."
    result = {"return_id": case["return_id"], "decision": decision, "risk_score": round(float(risk_score), 4), "risk_percent": round(float(risk_score) * 100), "model_score": None if model_score is None else round(model_score, 4), "pattern_score": round(pattern["score"], 4), "rule_score": round(rule_score, 4), "evidence_summary": summary["supporting_evidence"] + ([pattern["supporting_evidence"]] if pattern["score"] > .35 else []), "triggered_rules": rules, "pattern": pattern, "spike": spike, "decision_reason": reason, "recommended_next_step": "Do not release refund; inspect item and original fulfillment evidence." if decision == "HOLD REFUND" else "Route to trained reviewer before refund release." if decision == "ESCALATE TO HUMAN REVIEW" else "Release refund after standard settlement checks.", "investigator": summary, "failures": failures, "audit_trail": audit_for(case["return_id"])}
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


def warm_state():
    cases = generate_dataset()
    init_db(cases)
    model, metrics = train_model(cases)
    STATE.update({"cases": cases, "model": model, "metrics": metrics, "indexes": make_indexes(cases), "graph": make_relationship_graph(cases)})
    conn = sqlite3.connect(DB_PATH)
    rows = conn.execute("SELECT return_id,event_type,detail,created_at FROM audit_log ORDER BY id").fetchall()
    STATE["audit"] = [{"return_id": r[0], "event_type": r[1], "detail": r[2], "created_at": r[3]} for r in rows]
    conn.close()


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


@app.post("/api/login")
def login():
    data = request.get_json(silent=True) or {}
    if data.get("username") == DEMO_USERNAME and data.get("password") == DEMO_PASSWORD:
        session["authenticated"] = True
        return jsonify({"ok": True, "csrf_token": csrf_token(), "user": {"name": "Risk Operations", "role": "merchant_admin"}})
    return jsonify({"error": "Invalid demo credentials"}), 401


@app.post("/api/logout")
def logout():
    session.clear()
    return jsonify({"ok": True})


@app.get("/api/session")
def session_status():
    return jsonify({"authenticated": bool(session.get("authenticated")), "csrf_token": csrf_token() if session.get("authenticated") else None, "demo": f"{DEMO_USERNAME} / {DEMO_PASSWORD}"})


def case_card(case):
    result = analyze_case(case)
    return {"return_id": case["return_id"], "merchant_id": case["merchant_id"], "customer_id": case["customer_id"], "refund_amount": case["refund_amount"], "return_reason": case["return_reason"], "return_request_timestamp": case["return_request_timestamp"], "decision": result["decision"], "risk_score": result["risk_score"], "risk_percent": result["risk_percent"]}


@app.get("/api/overview")
@authenticated
def overview():
    analyzed = [analyze_case(c) for c in STATE["cases"][:1800]]
    decisions = Counter(x["decision"] for x in analyzed)
    risk_buckets = Counter("low" if x["risk_score"] < .35 else "medium" if x["risk_score"] < .65 else "high" for x in analyzed)
    fraud_count = sum(c["ground_truth"] == "fraudulent_return" for c in STATE["cases"])
    return jsonify({"total_cases": len(STATE["cases"]), "reviewed_cases": len(analyzed), "fraud_rate": round(fraud_count / len(STATE["cases"]) * 100, 1), "decisions": dict(decisions), "risk_buckets": dict(risk_buckets), "protected_value": STATE["metrics"]["fraudulent_refunds_prevented"], "pending_review": decisions["ESCALATE TO HUMAN REVIEW"], "model_health": "online", "latest_cases": [case_card(c) for c in sorted(STATE["cases"], key=lambda c: c["return_request_timestamp"], reverse=True)[:8]]})


@app.get("/api/cases")
@authenticated
def list_cases():
    args, cases = request.args, STATE["cases"]
    if args.get("merchant"):
        cases = [c for c in cases if c["merchant_id"] == args["merchant"]]
    if args.get("risk"):
        threshold = {"low": (0, .35), "medium": (.35, .65), "high": (.65, 1)}.get(args["risk"], (0, 1))
        cases = [c for c in cases if threshold[0] <= analyze_case(c)["risk_score"] < threshold[1]]
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
        pattern = pattern_analysis(case)
        if pattern["pattern_id"] != "COORD-RET-000" and pattern["pattern_id"] not in seen:
            seen.add(pattern["pattern_id"])
            patterns.append({"merchant_id": case["merchant_id"], "case_id": case["return_id"], **pattern})
        if len(patterns) >= 8:
            break
    return jsonify({"patterns": patterns, "graph_nodes": STATE["graph"].number_of_nodes(), "graph_edges": STATE["graph"].number_of_edges(), "linked_cases": sum(1 for c in STATE["cases"] if pattern_analysis(c)["score"] > .35)})


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
    return jsonify({"events": STATE["audit"][-200:][::-1], "immutable": True})


@app.post("/api/cases/<return_id>/override")
@authenticated
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
    add_audit(return_id, "human_override", f"Human reviewer set verdict to {decision}. Reason: {reason}")
    return jsonify({"ok": True, "decision": decision, "audit_trail": audit_for(return_id)})


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
