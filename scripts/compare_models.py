"""
scripts/compare_models.py

Reproduces the Random Forest vs LightGBM vs XGBoost comparison referenced in
MODEL_SELECTION.md. Trains all three on the identical 70% training split used
by main.py, sweeps the same threshold grid on the validation split, and
reports validation + held-out metrics for each.

This script is the source of truth for the numbers in MODEL_SELECTION.md.
If you change feature_vector(), generate_dataset(), or MODEL_SEED in main.py,
re-run this script and update MODEL_SELECTION.md with the new output.

Usage:
    pip install lightgbm xgboost   # not required for the main app, only this script
    python3 scripts/compare_models.py
"""
import json
import os
import sys

import numpy as np
from sklearn.ensemble import RandomForestClassifier
from sklearn.metrics import average_precision_score, f1_score, precision_score, recall_score, roc_auc_score

# Ensure the repo root (parent of this scripts/ folder) is importable as a
# module path, regardless of whether this file is run as
# `python scripts/compare_models.py` from the repo root, `python compare_models.py`
# from inside scripts/, or via `python -m scripts.compare_models`.
_REPO_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if _REPO_ROOT not in sys.path:
    sys.path.insert(0, _REPO_ROOT)

import main as sentinel  # uses generate_dataset / feature_vector / MODEL_SEED from the app itself

try:
    from lightgbm import LGBMClassifier
    HAVE_LGBM = True
except ImportError:
    HAVE_LGBM = False
    print("LightGBM not installed - skipping. Install with: pip install lightgbm")

try:
    from xgboost import XGBClassifier
    HAVE_XGB = True
except ImportError:
    HAVE_XGB = False
    print("XGBoost not installed - skipping. Install with: pip install xgboost")

THRESHOLDS = [0.05, 0.15, 0.25, 0.35, 0.40, 0.45, 0.50, 0.60, 0.70, 0.80, 0.90]


def money(value):
    return int(round(float(value)))


def build_splits():
    cases = sentinel.generate_dataset(12000)
    non_cold = [c for c in cases if not c.get("is_cold_entity")]
    cold = [c for c in cases if c.get("is_cold_entity")]
    ordered = sorted(non_cold, key=lambda c: c["purchase_timestamp"])
    n = len(ordered)
    train = ordered[:int(n * 0.70)]
    validation = ordered[int(n * 0.70):int(n * 0.85)]
    temporal_test = ordered[int(n * 0.85):]
    return train, validation, temporal_test, cold


def to_xy(subset):
    X = np.array([sentinel.feature_vector(c) for c in subset])
    y = np.array([c["ground_truth"] == "fraudulent_return" for c in subset])
    return X, y


def best_threshold_by_economic_loss(y, p, refund_amounts):
    best = None
    for t in THRESHOLDS:
        pred = p >= t
        fp_amt = sum(a for a, pr, yy in zip(refund_amounts, pred, y) if pr and not yy)
        fn_amt = sum(a for a, pr, yy in zip(refund_amounts, pred, y) if not pr and yy)
        fp = int(((pred == 1) & (y == 0)).sum())
        fn = int(((pred == 0) & (y == 1)).sum())
        loss = fp_amt + 180 * fp + fn_amt
        if best is None or loss < best["_loss_raw"]:
            best = {"threshold": t, "loss": money(loss), "fp": fp, "fn": fn, "_loss_raw": loss}
    return best


def evaluate(name, model, X_val, y_val, X_temp, y_temp, X_cold, y_cold, refund_amounts_val, locked_threshold=None):
    p_val, p_temp, p_cold = (model.predict_proba(X)[:, 1] for X in (X_val, X_temp, X_cold))
    best = best_threshold_by_economic_loss(y_val, p_val, refund_amounts_val)
    t = locked_threshold if locked_threshold is not None else best["threshold"]

    def at(y, p):
        pred = p >= t
        return {
            "precision": round(float(precision_score(y, pred, zero_division=0)), 4),
            "recall": round(float(recall_score(y, pred, zero_division=0)), 4),
            "f1": round(float(f1_score(y, pred, zero_division=0)), 4),
        }

    return {
        "model": name,
        "val_roc_auc": round(float(roc_auc_score(y_val, p_val)), 4),
        "val_pr_auc": round(float(average_precision_score(y_val, p_val)), 4),
        "temporal_roc_auc": round(float(roc_auc_score(y_temp, p_temp)), 4),
        "temporal_pr_auc": round(float(average_precision_score(y_temp, p_temp)), 4),
        "cold_roc_auc": round(float(roc_auc_score(y_cold, p_cold)), 4),
        "cold_pr_auc": round(float(average_precision_score(y_cold, p_cold)), 4),
        "threshold_used": t,
        "val_metrics": at(y_val, p_val),
        "temporal_metrics": at(y_temp, p_temp),
        "cold_metrics": at(y_cold, p_cold),
        "val_economic_loss_at_best_threshold": best,
    }


def main():
    train, validation, temporal_test, cold = build_splits()
    X_train, y_train = to_xy(train)
    X_val, y_val = to_xy(validation)
    X_temp, y_temp = to_xy(temporal_test)
    X_cold, y_cold = to_xy(cold)
    refund_amounts_val = [c["refund_amount"] for c in validation]

    results = {}

    rf = RandomForestClassifier(n_estimators=200, max_depth=None, min_samples_leaf=4,
                                 class_weight="balanced_subsample", random_state=sentinel.MODEL_SEED, n_jobs=-1)
    rf.fit(X_train, y_train)
    results["RandomForest (locked, main.py)"] = evaluate(
        "RandomForest", rf, X_val, y_val, X_temp, y_temp, X_cold, y_cold, refund_amounts_val, locked_threshold=0.35
    )

    if HAVE_LGBM:
        lgbm = LGBMClassifier(n_estimators=200, max_depth=-1, min_child_samples=4,
                               class_weight="balanced", random_state=sentinel.MODEL_SEED, verbosity=-1)
        lgbm.fit(X_train, y_train)
        results["LightGBM"] = evaluate(
            "LightGBM", lgbm, X_val, y_val, X_temp, y_temp, X_cold, y_cold, refund_amounts_val
        )

    if HAVE_XGB:
        scale_pos_weight = (len(y_train) - y_train.sum()) / max(1, y_train.sum())
        xgbm = XGBClassifier(n_estimators=200, max_depth=6, min_child_weight=4,
                              scale_pos_weight=scale_pos_weight, random_state=sentinel.MODEL_SEED,
                              eval_metric="logloss")
        xgbm.fit(X_train, y_train)
        results["XGBoost"] = evaluate(
            "XGBoost", xgbm, X_val, y_val, X_temp, y_temp, X_cold, y_cold, refund_amounts_val
        )

    print(json.dumps(results, indent=2))
    with open("comparison_results.json", "w") as f:
        json.dump(results, f, indent=2)
    print("\nWrote comparison_results.json")


if __name__ == "__main__":
    main()

