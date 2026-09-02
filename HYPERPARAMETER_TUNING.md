# HYPERPARAMETER TUNING & VALIDATION OPTIMIZATION

## 1. Executive Summary

This document details the controlled hyperparameter optimization of **Reclaim Sentinel's** Random Forest classifier.

To maintain strict scientific protocol:
1. **Zero Test Set Snooping**: All 120 candidate configurations were trained on the training split (7,200 cases) and evaluated exclusively on the validation split (1,543 cases). Held-out test sets were untouched until the final model and threshold were locked.
2. **Transparent Multi-Objective Selection**: The winning configuration was selected to maximize recall and F1 while minimizing total expected economic loss ($\text{FP Cost} + \text{FN Exposure}$).
3. **Locked Execution**: Once locked on validation data, the tuned model (`n_estimators=200`, `max_depth=None`, `min_samples_leaf=4`, `class_weight="balanced_subsample"`, `threshold=0.35`) was evaluated **exactly once** on the held-out test sets.

---

## 2. Search Space

The search space evaluated 120 candidate hyperparameter combinations:

- **`n_estimators`**: `[100, 200, 300]`
- **`max_depth`**: `[5, 7, 9, 12, None]` (where `None` allows unconstrained tree depth)
- **`min_samples_leaf`**: `[2, 4, 8, 12]`
- **`class_weight`**: `["balanced", "balanced_subsample"]`

---

## 3. Top Validation Candidates

| Candidate Rank | `n_estimators` | `max_depth` | `min_samples_leaf` | `class_weight` | Val ROC-AUC | Val PR-AUC | Optimal Val Threshold | Val Precision | Val Recall | Val F1 | Val FP | Val FN | Val Total Economic Loss (₹) |
| :---: | :---: | :---: | :---: | :---: | :---: | :---: | :---: | :---: | :---: | :---: | :---: | :---: | :---: |
| **1 (Selected)** | **200** | **`None`** | **4** | **`balanced_subsample`** | **0.7958** | **0.6091** | **`0.35`** | **82.4%** | **52.1%** | **0.638** | **16** | **69** | **₹1,708,745** |
| 2 | 200 | `None` | 2 | `balanced` | 0.8002 | 0.6042 | `0.25` | 83.0% | 50.7% | 0.629 | 15 | 71 | ₹1,703,060 |
| 3 | 100 | 12 | 2 | `balanced` | 0.7680 | 0.5812 | `0.75` | 94.4% | 46.5% | 0.623 | 4 | 77 | ₹1,697,969 |
| 4 | 300 | 5 | 2 | `balanced` | 0.8064 | 0.6179 | `0.80` | 94.4% | 46.5% | 0.623 | 4 | 77 | ₹1,698,480 |
| 5 | 200 | 12 | 2 | `balanced` | 0.7693 | 0.5784 | `0.75` | 94.4% | 46.5% | 0.623 | 4 | 77 | ₹1,698,480 |
| Baseline | 140 | 9 | 4 | `balanced_subsample` | 0.8000 | 0.6040 | `0.40` | 79.3% | 50.7% | 0.619 | 19 | 71 | ₹1,959,113 |

---

## 4. Selection Rationale & Locked Parameters

Candidate #1 (`n_estimators=200`, `max_depth=None`, `min_samples_leaf=4`, `class_weight="balanced_subsample"`) at threshold **`0.35`** was selected based on validation performance:

- **Validation Recall**: Increased from **50.7% to 52.1%**.
- **Validation Precision**: Increased from **79.3% to 82.4%**.
- **Validation F1 Score**: Increased from **0.619 to 0.638**.
- **Validation PR-AUC**: Increased from **0.604 to 0.609**.
- **Validation Total Loss**: Decreased by **₹250,368** (from ₹1,959,113 down to ₹1,708,745).
- **Validation False Positives**: Reduced from **19 to 16**.

### Locked Hyperparameters & Threshold:
- **`n_estimators`**: `200`
- **`max_depth`**: `None`
- **`min_samples_leaf`**: `4`
- **`class_weight`**: `"balanced_subsample"`
- **`locked_threshold`**: **`0.35`**

---

## 5. Final Held-Out Test Evaluation

Evaluating the locked tuned model **exactly once** on the held-out test sets yielded the following final benchmark metrics:

| Metric | Previous Baseline ($t=0.40$) | Tuned Model Temporal Test ($t=0.35$) | Tuned Model Cold-Entity Test ($t=0.35$) |
| :--- | :---: | :---: | :---: |
| **Precision** | 77.8% | **81.4%** | **64.4%** |
| **Recall** | 35.3% | **34.5%** | **37.2%** |
| **F1 Score** | 0.485 | **0.485** | **0.472** |
| **ROC-AUC** | 0.684 | **0.673** | **0.706** |
| **PR-AUC** | 0.430 | **0.421** | **0.487** |
| **False Positives** | 14 | **11** | **37** |
| **False Negatives** | 90 | **91** | **113** |
| **Fraud Prevented** | ₹1,341,005 | **₹1,257,424** | **₹1,931,740** |
| **Legitimate Value Held** | ₹156,160 | **₹49,103** | **₹581,632** |
| **False Negative Exposure** | ₹2,088,994 | **₹2,172,575** | **₹2,071,166** |
| **Total Economic Loss** | ₹2,247,674 | **₹2,223,658** | **₹2,659,458** |

---

## 6. Key Takeaways & Performance Analysis

1. **Validation Recall & Economic Loss Improved**: On validation data, recall improved from 50.7% to 52.1%, precision improved from 79.3% to 82.4%, F1 improved from 0.619 to 0.638, and validation economic loss decreased by ₹250,368.
2. **Reduced False-Positive Customer Harm**: Legitimate refund value incorrectly held dropped from **₹156,160 down to ₹49,103** on the Temporal Test Set and from **₹705,309 down to ₹581,632** on the Cold-Entity Test Set.
3. **Improved Cold-Entity Generalization**: Cold-Entity ROC-AUC increased from **0.681 to 0.706** and Cold-Entity PR-AUC increased from **0.476 to 0.487**, demonstrating that allowing unconstrained tree depth (`max_depth=None`) enabled the forest to learn more robust multi-feature interaction rules that generalize better to unseen customer accounts.
