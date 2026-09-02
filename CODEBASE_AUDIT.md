# CODEBASE AUDIT

## 1. Executive Summary

Reclaim Sentinel is a defense-only, pre-refund return verification system designed to protect merchants from invalid or fraudulent return refunds before money is disbursed. This audit provides an exhaustive forensic analysis of the repository exported from Replit, evaluating architectural structure, operational code, mathematical correctness, data splitting, ML design, evaluation integrity, AI boundary enforcement, failure handling, security, and compliance with **Razorpay AI Buildathon Track 02 (AI Risk Manager)** requirements.

The codebase is functional, self-contained, and runnable. It successfully implements a multi-layered verification strategy combining 8 deterministic evidence rules, a Random Forest classifier trained on 12,000 synthetic return records, NetworkX bipartite graph coordination analysis, a 4-week rolling baseline spike detector, a strict 3-verdict decision policy (`APPROVE REFUND`, `HOLD REFUND`, `ESCALATE TO HUMAN REVIEW`), an offline structured investigator, and optional non-authoritative LLM integration.

However, the architecture is monolithic—contained almost entirely inside a single file ([main.py](file:///c:/Users/Moses%20Andrew%20Raymond/Downloads/Reclaim-Senetial-main/Reclaim-Senetial-main/main.py))—and lacks modular component separation, comprehensive integration tests, interactive merchant verification endpoints, and advanced gradient boosted trees (e.g. LightGBM/XGBoost).

---

## 2. Existing Architecture

The current system follows a single-process Flask architecture where data generation, ML training, feature extraction, rule evaluation, graph indexing, statistical anomaly calculation, decision synthesis, and API hosting all occur in [main.py](file:///c:/Users/Moses%20Andrew%20Raymond/Downloads/Reclaim-Senetial-main/Reclaim-Senetial-main/main.py).

```text
Synthetic Generator [generate_dataset()] 
       │
       ├──> SQLite Storage [data/reclaim_sentinel.db]
       │
       ├──> Time-Aware Split (70% Train / 15% Val / 15% Held-Out Test)
       │         │
       │         └──> RandomForestClassifier [train_model()] ──> Evaluation Metrics
       │
       └──> In-Memory State [STATE dictionary]
                 │
                 ├──> Deterministic Rules [run_rules()] ────────────┐
                 ├──> ML Feature Vector [feature_vector()] ─────────┼──> Decision Policy [analyze_case()]
                 ├──> NetworkX Graph [make_relationship_graph()] ──┤         │
                 └──> Rolling Spike Engine [spike_analysis()] ──────┘         ├──> Verdict (APPROVE/HOLD/ESCALATE)
                                                                             ├──> Audit Logger [add_audit()]
                                                                             └──> Structured Investigator [investigator_summary()]
                                                                                       │ (Optional OpenAI LLM)
                                                                                       └──> Flask REST API & Web Dashboard
```

### Key Repository Files:
- **[main.py](file:///c:/Users/Moses%20Andrew%20Raymond/Downloads/Reclaim-Senetial-main/Reclaim-Senetial-main/main.py)**: Single entrypoint containing all backend logic, ML, data generation, rule engine, graph engine, and REST routes.
- **[static/index.html](file:///c:/Users/Moses%20Andrew%20Raymond/Downloads/Reclaim-Senetial-main/Reclaim-Senetial-main/static/index.html)**: Single-page application UI with 7 navigation views (Overview, Cases, Detail, Patterns, Spikes, Evaluation, Audit).
- **[static/app.js](file:///c:/Users/Moses%20Andrew%20Raymond/Downloads/Reclaim-Senetial-main/Reclaim-Senetial-main/static/app.js)**: Vanilla JavaScript frontend handling API fetches, chart rendering, filters, case modal details, and overrides.
- **[static/styles.css](file:///c:/Users/Moses%20Andrew%20Raymond/Downloads/Reclaim-Senetial-main/Reclaim-Senetial-main/static/styles.css)**: Modern dark-mode aesthetic styling.
- **[tests/test_engine.py](file:///c:/Users/Moses%20Andrew%20Raymond/Downloads/Reclaim-Senetial-main/Reclaim-Senetial-main/tests/test_engine.py)**: 5 basic unit tests for data size, SKU rule, model scoring, failure fallback, and timestamp parsing.
- **[pyproject.toml](file:///c:/Users/Moses%20Andrew%20Raymond/Downloads/Reclaim-Senetial-main/Reclaim-Senetial-main/pyproject.toml)**: Project configuration specifying dependencies (`flask`, `joblib`, `networkx`, `numpy`, `scikit-learn`).

---

## 3. Working Components

1. **Synthetic Data Generator** ([main.py:L178-180](file:///c:/Users/Moses%20Andrew%20Raymond/Downloads/Reclaim-Senetial-main/Reclaim-Senetial-main/main.py#L178-L180), `generate_dataset` & `make_case`):
   - Generates 12,000 deterministic return records using fixed random seed (`73`).
   - Ground truth is computed via a non-linear latent sigmoid function combined with noise.
2. **Deterministic Verification Engine** ([main.py:L267-286](file:///c:/Users/Moses%20Andrew%20Raymond/Downloads/Reclaim-Senetial-main/Reclaim-Senetial-main/main.py#L267-L286), `run_rules`):
   - Correctly evaluates 8 rules: SKU mismatch (`SKU-001`), weight delta (`WEIGHT-002`), serial number mismatch (`SERIAL-003`), product condition (`CONDITION-004`), timeline order (`TIME-005`), policy window (`POLICY-006`), courier consistency (`COURIER-007`), and warehouse scan verification (`EVIDENCE-008`).
3. **ML Risk Scoring & Evaluation** ([main.py:L214-243](file:///c:/Users/Moses%20Andrew%20Raymond/Downloads/Reclaim-Senetial-main/Reclaim-Senetial-main/main.py#L214-L243), `train_model`):
   - Trains `RandomForestClassifier` (140 estimators, depth 9, balanced subsampling).
   - Computes precision, recall, F1, ROC-AUC, PR-AUC, confusion matrix, threshold trade-off table, prevented fraud value, and incorrectly held legitimate value on 1,800 held-out test cases.
4. **Graph Abuse Pattern Engine** ([main.py:L255-265](file:///c:/Users/Moses%20Andrew%20Raymond/Downloads/Reclaim-Senetial-main/Reclaim-Senetial-main/main.py#L255-L265) & [L289-316](file:///c:/Users/Moses%20Andrew%20Raymond/Downloads/Reclaim-Senetial-main/Reclaim-Senetial-main/main.py#L289-L316), `make_relationship_graph` & `pattern_analysis`):
   - NetworkX bipartite graph linking returns with entities (`customer_id`, `device_id`, `shipping_address_hash`, `payment_instrument_hash`, `merchant_id`).
   - Identifies multi-account clusters sharing identifiers within 72-hour windows.
5. **Return-Abuse Spike Detector** ([main.py:L323-341](file:///c:/Users/Moses%20Andrew%20Raymond/Downloads/Reclaim-Senetial-main/Reclaim-Senetial-main/main.py#L323-L341), `spike_analysis`):
   - Calculates 4-week rolling baselines of merchant suspicious return rates and computes standardized z-score deviations.
6. **Decision Engine & Policy Layer** ([main.py:L411-458](file:///c:/Users/Moses%20Andrew%20Raymond/Downloads/Reclaim-Senetial-main/Reclaim-Senetial-main/main.py#L411-L458), `analyze_case`):
   - Weighted risk composite: 55% ML + 25% Rule + 15% Pattern + 5% Spike.
   - Enforces 3 verdicts: `APPROVE REFUND`, `HOLD REFUND`, `ESCALATE TO HUMAN REVIEW`.
7. **Offline Investigator & Optional LLM** ([main.py:L348-408](file:///c:/Users/Moses%20Andrew%20Raymond/Downloads/Reclaim-Senetial-main/Reclaim-Senetial-main/main.py#L348-L408), `investigator_summary` & `call_llm_review_questions`):
   - Provides deterministic evidence briefs offline. When `OPENAI_API_KEY` is present, fetches non-authoritative human review questions without changing decisions.
8. **Audit Trail & SQLite Persistence** ([main.py:L202-211](file:///c:/Users/Moses%20Andrew%20Raymond/Downloads/Reclaim-Senetial-main/Reclaim-Senetial-main/main.py#L202-L211) & [L460-467](file:///c:/Users/Moses%20Andrew%20Raymond/Downloads/Reclaim-Senetial-main/Reclaim-Senetial-main/main.py#L460-L467), `init_db` & `add_audit`):
   - Records append-only audit events into SQLite (`data/reclaim_sentinel.db`) with thread locks.
9. **Dashboard UI** ([static/index.html](file:///c:/Users/Moses%20Andrew%20Raymond/Downloads/Reclaim-Senetial-main/Reclaim-Senetial-main/static/index.html) & [static/app.js](file:///c:/Users/Moses%20Andrew%20Raymond/Downloads/Reclaim-Senetial-main/Reclaim-Senetial-main/static/app.js)):
   - Complete 7-page interactive dashboard with CSRF protection, live statistics, case inspector, pattern queue, spike list, model evaluation metrics, and audit log.

---

## 4. Broken Components

1. **Dependency Lock & Project Config Mismatch**:
   - `pyproject.toml` missing dependencies for XGBoost/LightGBM (preferred in track spec). `networkx` is specified in `pyproject.toml` but wasn't installed in default system environments until explicitly added.
2. **Hardcoded Feature Constant in Feature Vector** ([main.py:L198](file:///c:/Users/Moses%20Andrew%20Raymond/Downloads/Reclaim-Senetial-main/Reclaim-Senetial-main/main.py#L198)):
   - In `feature_vector()`, feature index 16 is hardcoded to `1 / 3` (0.33333). This is a dead constant feature that adds noise to decision tree splitting.
3. **Frontend "+ Verify a case" Action** ([static/app.js:L77](file:///c:/Users/Moses%20Andrew%20Raymond/Downloads/Reclaim-Senetial-main/Reclaim-Senetial-main/static/app.js#L77)):
   - Clicking "+ Verify a case" on the Return Cases page simply re-opens an existing latest case instead of presenting an interactive modal or form to submit a new return case for real-time verification.
4. **Lack of Dynamic Scale Parameters in Feature Preprocessing**:
   - In `feature_vector()` ([main.py:L183-199](file:///c:/Users/Moses%20Andrew%20Raymond/Downloads/Reclaim-Senetial-main/Reclaim-Senetial-main/main.py#L183-L199)), normalization factors (`/ 12`, `/ 8`, `/ 90000`, `/ 30`, `/ 1000`) are static hardcoded magic numbers rather than fitted parameters computed from the training split.

---

## 5. Incomplete Components

1. **Monolithic Code Base**:
   - Entire application (dataset generation, ML training, graph analysis, rule engine, decision policy, API routes, database operations) is crammed into a single 644-line file ([main.py](file:///c:/Users/Moses%20Andrew%20Raymond/Downloads/Reclaim-Senetial-main/Reclaim-Senetial-main/main.py)), instead of modular directories (`ml/`, `rules/`, `graph/`, `backend/`, `frontend/`, `docs/`, `scripts/`).
2. **Missing Real-Time Case Verification Endpoint**:
   - There is no `POST /api/verify` endpoint allowing merchants to submit custom return payloads JSON for verification. Current system only analyzes existing synthetic cases in `STATE["cases"]`.
3. **Limited Unit Test Coverage**:
   - [tests/test_engine.py](file:///c:/Users/Moses%20Andrew%20Raymond/Downloads/Reclaim-Senetial-main/Reclaim-Senetial-main/tests/test_engine.py) contains only 5 unit tests. It lacks tests for graph analysis, spike detection, business impact monetary calculations, API route authentication, CSRF validation, human override, or LLM fallback handling.
4. **No Advanced Gradient Boosting (LightGBM/XGBoost)**:
   - The project uses `RandomForestClassifier` from `scikit-learn` instead of LightGBM/XGBoost as suggested by the buildathon specification.
5. **No Production Database Migration / Multi-tenant Auth**:
   - Uses single-file SQLite database without connection pooling, migrations, or real multi-tenant merchant isolation.

---

## 6. Mocked / Hardcoded Components

1. **Synthetic Dataset Generation** ([main.py:L73-180](file:///c:/Users/Moses%20Andrew%20Raymond/Downloads/Reclaim-Senetial-main/Reclaim-Senetial-main/main.py#L73-L180)):
   - 100% of data is synthetic, generated deterministically from seed 73.
2. **Demo Credentials** ([main.py:L32-33](file:///c:/Users/Moses%20Andrew%20Raymond/Downloads/Reclaim-Senetial-main/Reclaim-Senetial-main/main.py#L32-L33)):
   - Hardcoded demo credentials `sentinel-demo` / `reclaim-2026`. Default `SESSION_SECRET` fallback is `"local-reclaim-sentinel-demo-secret"`.
3. **False Positive Cost Assumption** ([main.py:L239](file:///c:/Users/Moses%20Andrew%20Raymond/Downloads/Reclaim-Senetial-main/Reclaim-Senetial-main/main.py#L239)):
   - Hardcoded cost of ₹180 per false positive case in `metrics`.
4. **Offline Investigator Summaries** ([main.py:L348-370](file:///c:/Users/Moses%20Andrew%20Raymond/Downloads/Reclaim-Senetial-main/Reclaim-Senetial-main/main.py#L348-L370)):
   - Deterministic rule-based template strings when LLM is unavailable.
5. **Feature 17** ([main.py:L198](file:///c:/Users/Moses%20Andrew%20Raymond/Downloads/Reclaim-Senetial-main/Reclaim-Senetial-main/main.py#L198)):
   - Hardcoded constant `1 / 3` in feature vector array.

---

## 7. Data Pipeline

### Audit Analysis:
- **Generation Method**: `generate_dataset(size=12000)` calls `make_case(i, rng)` using `random.Random(73)`.
- **Fields Included**: 33 total fields including `return_id`, `order_id`, `merchant_id`, `customer_id`, `product_id`, `original_sku`, `returned_sku`, `original_product_category`, `original_package_weight`, `returned_package_weight`, `purchase_timestamp`, `delivery_timestamp`, `return_request_timestamp`, `pickup_timestamp`, `warehouse_received_timestamp`, `courier_status`, `return_reason`, `refund_amount`, `customer_return_count`, `customer_return_rate`, `customer_previous_fraud_flags`, `customer_account_age_days`, `merchant_return_rate`, `merchant_refund_rate`, `merchant_category`, `device_id`, `shipping_address_hash`, `payment_instrument_hash`, `serial_number_match`, `product_condition`, `warehouse_scan_result`, `previous_similar_claims`, `ground_truth`.
- **Labeling Mechanism**: Ground truth is computed via a multi-signal latent variable formula:
  $$ \text{latent} = -3.5 + \mathcal{N}(0, 0.65) + \text{penalties} $$
  Ground-truth label is assigned via logistic probability $P(\text{fraud}) = \frac{1}{1 + e^{-\text{latent}}}$ with a 5.5% random label noise flip.
- **Fraud Mutators**: Fraudulent records undergo realistic physical/timeline mutations (e.g. SKU swap, weight reduction to 15%-57%, serial number mismatch, timestamp inversion, high claim counts).
- **Ground Truth Separation**: Ground-truth label (`ground_truth`) is strictly excluded from `feature_vector()`.

---

## 8. ML Pipeline

### Model Details:
- **Algorithm**: `sklearn.ensemble.RandomForestClassifier` ([main.py:L218](file:///c:/Users/Moses%20Andrew%20Raymond/Downloads/Reclaim-Senetial-main/Reclaim-Senetial-main/main.py#L218))
- **Parameters**: `n_estimators=140`, `max_depth=9`, `min_samples_leaf=4`, `class_weight="balanced_subsample"`, `random_state=73`, `n_jobs=-1`.
- **Features Used (17 total)**:
  1. `weight_delta` ($\max(0, \frac{\text{orig} - \text{ret}}{\text{orig}})$)
  2. `sku_mismatch` ($1$ if mismatched else $0$)
  3. `serial_mismatch` ($1$ if mismatch else $0$)
  4. `product_condition_score` (`sealed`: 0, `good`: 0.12, `opened`: 0.35, `partial`: 0.75, `empty`: 1.0)
  5. `warehouse_scan_score` (`verified`: 0, `photo_verified`: 0.08, `manual_review`: 0.38, `unverified`: 0.64)
  6. `timestamp_anomaly` ($1$ if received < pickup or delivery < purchase)
  7. `customer_return_count_normalized` ($\min(1, \frac{\text{count}}{12})$)
  8. `customer_return_rate` ($\min(1, \text{rate})$)
  9. `customer_previous_fraud_flags` ($1$ or $0$)
  10. `previous_similar_claims_normalized` ($\min(1, \frac{\text{claims}}{8})$)
  11. `refund_amount_normalized` ($\min(1, \frac{\text{amount}}{90000})$)
  12. `merchant_return_rate` ($\min(1, \text{rate})$)
  13. `merchant_refund_rate` ($\min(1, \text{rate})$)
  14. `return_delay_days_normalized` ($\min(1, \frac{\text{delay}}{30})$)
  15. `customer_account_age_days_normalized` ($\min(1, \frac{\text{age}}{1000})$)
  16. `is_electronics_category` ($1$ if electronics else $0$)
  17. `1 / 3` (hardcoded constant)

### Train / Validation / Test Splitting:
- Records are sorted chronologically by `purchase_timestamp` ([main.py:L215](file:///c:/Users/Moses%20Andrew%20Raymond/Downloads/Reclaim-Senetial-main/Reclaim-Senetial-main/main.py#L215)).
- **Train Set**: First 70% (8,400 records)
- **Validation Set**: Next 15% (1,800 records)
- **Untouched Held-Out Test Set**: Final 15% (1,800 records)
- **Leakage Audit**: No future information leaks into training features. Ground truth is omitted from feature vector. Time-aware split preserves real-world temporal evaluation boundaries.

---

## 9. Evaluation Pipeline

The evaluation pipeline ([main.py:L220-242](file:///c:/Users/Moses%20Andrew%20Raymond/Downloads/Reclaim-Senetial-main/Reclaim-Senetial-main/main.py#L220-L242)) executes on server startup against the 1,800 held-out test records:

- **Metrics Calculated Dynamically**:
  - Precision: `precision_score(test_y, test_pred)`
  - Recall: `recall_score(test_y, test_pred)`
  - F1 Score: `f1_score(test_y, test_pred)`
  - ROC-AUC: `roc_auc_score(test_y, test_p)`
  - PR-AUC: `average_precision_score(test_y, test_p)`
  - Confusion Matrix: `confusion_matrix(test_y, test_pred)`
  - Threshold Analysis: Evaluates thresholds `[0.25, 0.35, 0.45, 0.50, 0.60, 0.70, 0.80]` generating precision, recall, F1, FP, FN for each.

- **Financial & Monetary Impact Calculations**:
  - `fraudulent_refunds_prevented` = $\sum \text{refund\_amount}$ for True Positives (actual fraud correctly predicted fraud)
  - `legitimate_value_held` = $\sum \text{refund\_amount}$ for False Positives (actual legitimate incorrectly predicted fraud)
  - `false_negative_exposure` = $\sum \text{refund\_amount}$ for False Negatives (actual fraud missed by model)
  - `false_positive_cost_per_case` = ₹180 (explicitly reported assumption)

---

## 10. AI / LLM Usage

### Architectural Boundaries:
- **Is LLM in the money path?** **NO.** The LLM never makes or overrides financial refund decisions.
- **Where is LLM used?** In `call_llm_review_questions()` ([main.py:L372-408](file:///c:/Users/Moses%20Andrew%20Raymond/Downloads/Reclaim-Senetial-main/Reclaim-Senetial-main/main.py#L372-L408)), the LLM is invoked only when `OPENAI_API_KEY` is provided to generate 3 non-authoritative human reviewer questions based strictly on a JSON evidence summary.
- **Prompt Isolation**: Prompt explicitly instructs: *"write three concise questions for a human reviewer. Do not state new facts, do not change the decision..."*
- **Offline Fallback**: If `OPENAI_API_KEY` is missing or the API call fails/times out, the system falls back seamlessly to `investigator_summary()` ([main.py:L348-370](file:///c:/Users/Moses%20Andrew%20Raymond/Downloads/Reclaim-Senetial-main/Reclaim-Senetial-main/main.py#L348-L370)) which yields:
  `"Insufficient evidence for an automated decision."` when evidence is ambiguous or missing.

---

## 11. Decision Engine

The decision engine (`analyze_case()`, [main.py:L411-458](file:///c:/Users/Moses%20Andrew%20Raymond/Downloads/Reclaim-Senetial-main/Reclaim-Senetial-main/main.py#L411-L458)) computes a composite risk score and maps it to exactly one of 3 verdicts:

$$ \text{Risk Score} = 0.55 \times \text{ML Score} + 0.25 \times \text{Rule Score} + 0.15 \times \text{Pattern Score} + 0.05 \times \text{Spike Score} $$

### Decision Logic:
1. **Dependency / Execution Failures Present**:
   - If critical rule fail exists $\rightarrow$ `HOLD REFUND`
   - Else $\rightarrow$ `ESCALATE TO HUMAN REVIEW` (Never silently approves on failure).
2. **Critical Rule Fail OR Risk Score $\ge 0.78$**:
   - $\rightarrow$ `HOLD REFUND`
3. **Risk Score $\le 0.30$ AND No High Rule Flags AND Pattern Score $< 0.35$ AND Normal Spike**:
   - $\rightarrow$ `APPROVE REFUND`
4. **All Other Conditions (Mixed or Conflicting Signals)**:
   - $\rightarrow$ `ESCALATE TO HUMAN REVIEW`

---

## 12. Abuse Pattern Detection

1. **NetworkX Bipartite Graph Engine** ([main.py:L255-265](file:///c:/Users/Moses%20Andrew%20Raymond/Downloads/Reclaim-Senetial-main/Reclaim-Senetial-main/main.py#L255-L265)):
   - Builds an in-memory graph connecting return cases to entity nodes (`customer_id`, `device_id`, `shipping_address_hash`, `payment_instrument_hash`, `merchant_id`).
2. **Coordinated Return Cluster Detection** ([main.py:L289-316](file:///c:/Users/Moses%20Andrew%20Raymond/Downloads/Reclaim-Senetial-main/Reclaim-Senetial-main/main.py#L289-L316)):
   - Traverses 2-hop graph neighbors to identify distinct return cases sharing physical/digital entities within a 72-hour window.
   - Computes cluster confidence scores (`COORD-RET-001`, `COORD-RET-002`, `COORD-RET-000`).
3. **Return-Abuse Spike Detection Engine** ([main.py:L323-341](file:///c:/Users/Moses%20Andrew%20Raymond/Downloads/Reclaim-Senetial-main/Reclaim-Senetial-main/main.py#L323-L341)):
   - Monitored across 24 synthetic merchants.
   - Compares suspicious return rate ($\text{risk\_signal} \ge 2$) in current 7-day window against 4 prior 7-day baseline windows.
   - Outputs standardized $z$-deviation $\sigma$ and assigns severity (`high` if $\ge 2.5\sigma$, `medium` if $\ge 1.25\sigma$, else `normal`).

---

## 13. Failure Recovery

- `analyze_case()` wraps `run_rules()`, ML prediction, `pattern_analysis()`, `spike_analysis()`, and `call_llm_review_questions()` in independent `try...except` blocks ([main.py:L413-432](file:///c:/Users/Moses%20Andrew%20Raymond/Downloads/Reclaim-Senetial-main/Reclaim-Senetial-main/main.py#L413-L432)).
- **ML Failure**: Model score drops to `None`. Risk score uses rule and graph fallbacks (`min(0.95, rule_score + pattern_score * 0.25)`). Decision forces `ESCALATE TO HUMAN REVIEW` or `HOLD REFUND`.
- **Graph / Spike Failure**: Default to score 0 with warning string logged.
- **LLM Failure**: Falls back immediately to offline structured summary.
- **Rule Failure / Malformed Data**: Captures exception, flags critical failure, and forces `ESCALATE TO HUMAN REVIEW` or `HOLD REFUND`.
- **Conservative Money Policy**: **No failure path ever defaults to `APPROVE REFUND`.**

---

## 14. Security

- **Defense-Only Scope**: System contains zero offensive capabilities, exploit code, credential harvesting, or automated payment execution.
- **Authentication**: Dashboard routes protected via `@authenticated` decorator enforcing Flask session cookie ([main.py:L481-487](file:///c:/Users/Moses%20Andrew%20Raymond/Downloads/Reclaim-Senetial-main/Reclaim-Senetial-main/main.py#L481-L487)).
- **CSRF Defense**: State-changing POST endpoint (`/api/cases/<return_id>/override`) verifies `X-CSRF-Token` header using `secrets.compare_digest` ([main.py:L496-499](file:///c:/Users/Moses%20Andrew%20Raymond/Downloads/Reclaim-Senetial-main/Reclaim-Senetial-main/main.py#L496-L499)).
- **Secrets Management**: No API keys or passwords hardcoded in repository files. `OPENAI_API_KEY` and `SESSION_SECRET` read from environment variables.
- **Audit Immutability**: Verification events and human overrides logged into SQLite `audit_log` table via thread-safe lock (`AUDIT_LOCK`).

---

## 15. Razorpay Buildathon Compliance

| Requirement | Status | Evidence / Location |
| :--- | :---: | :--- |
| **Working Detector / Verifier** | **PASS** | Fully functional rule engine, ML classifier, and graph analysis ([main.py](file:///c:/Users/Moses%20Andrew%20Raymond/Downloads/Reclaim-Senetial-main/Reclaim-Senetial-main/main.py)) |
| **One Class of Loss** | **PASS** | Narrowly focused on invalid/fraudulent merchant return refunds ([README.md](file:///c:/Users/Moses%20Andrew%20Raymond/Downloads/Reclaim-Senetial-main/Reclaim-Senetial-main/README.md#L26-L27)) |
| **Held-Out Test Set** | **PASS** | Final 15% (1,800 records) of purchase-time sorted data ([main.py:L217](file:///c:/Users/Moses%20Andrew%20Raymond/Downloads/Reclaim-Senetial-main/Reclaim-Senetial-main/main.py#L217)) |
| **Precision, Recall, F1** | **PASS** | Computed dynamically via `sklearn.metrics` ([main.py:L234-236](file:///c:/Users/Moses%20Andrew%20Raymond/Downloads/Reclaim-Senetial-main/Reclaim-Senetial-main/main.py#L234-L236)) |
| **Honest False-Positive Cost** | **PASS** | Calculates legitimate refund value held + ₹180 per case ([main.py:L230](file:///c:/Users/Moses%20Andrew%20Raymond/Downloads/Reclaim-Senetial-main/Reclaim-Senetial-main/main.py#L230)) |
| **Defense-Only** | **PASS** | Defensive return verification only; zero offensive functionality ([THREAT_MODEL.md](file:///c:/Users/Moses%20Andrew%20Raymond/Downloads/Reclaim-Senetial-main/Reclaim-Senetial-main/THREAT_MODEL.md#L30)) |
| **Meaningful AI Usage** | **PASS** | ML for probability risk; LLM strictly for review questions ([main.py:L372](file:///c:/Users/Moses%20Andrew%20Raymond/Downloads/Reclaim-Senetial-main/Reclaim-Senetial-main/main.py#L372)) |
| **Build Quality & Architecture**| **PARTIAL**| Single monolithic file ([main.py](file:///c:/Users/Moses%20Andrew%20Raymond/Downloads/Reclaim-Senetial-main/Reclaim-Senetial-main/main.py)); lacks clean package modularity |
| **Failure Recovery** | **PASS** | Try-except wrapped sub-engines; safe default to HOLD/ESCALATE ([main.py:L437](file:///c:/Users/Moses%20Andrew%20Raymond/Downloads/Reclaim-Senetial-main/Reclaim-Senetial-main/main.py#L437)) |
| **Reproducibility** | **PASS** | Fixed random seed 73; single startup command `python main.py` ([SETUP.md](file:///c:/Users/Moses%20Andrew%20Raymond/Downloads/Reclaim-Senetial-main/Reclaim-Senetial-main/SETUP.md#L10)) |

---

## 16. Critical Gaps

1. **Monolithic Architecture**: Entire logic in a single file ([main.py](file:///c:/Users/Moses%20Andrew%20Raymond/Downloads/Reclaim-Senetial-main/Reclaim-Senetial-main/main.py)) instead of clean modular modules (`ml/`, `rules/`, `graph/`, `backend/`, `frontend/`).
2. **Missing Real-Time Verification Submission API**: No interactive API route (`POST /api/verify`) or frontend form allowing users to submit new custom return cases for live verification.
3. **Dead / Constant Feature Vector Component**: `feature_vector()` contains hardcoded constant `1 / 3` at index 16.
4. **Sub-optimal Baseline ML Classifier**: Uses basic `RandomForestClassifier` rather than LightGBM/XGBoost as recommended in Track 02 specifications.
5. **Inadequate Test Coverage**: [tests/test_engine.py](file:///c:/Users/Moses%20Andrew%20Raymond/Downloads/Reclaim-Senetial-main/Reclaim-Senetial-main/tests/test_engine.py) tests only 5 basic assertions; lacks coverage for API endpoints, graph engine, spike engine, or money calculations.

---

## 17. P0 Requirements (Must Fix Before Submission)

1. **Refactor Codebase into Clean Modular Architecture**:
   - Break `main.py` into `reclaim_sentinel/` package with submodules: `data/`, `rules/`, `ml/`, `graph/`, `spike/`, `engine/`, `api/`.
2. **Implement Interactive Single-Case Verification Endpoint & UI Modal**:
   - Add `POST /api/verify` REST endpoint and an interactive "+ Verify Return Case" form/modal in UI to allow verifying custom return payloads.
3. **Clean Up Feature Vector & Upgrade ML Model**:
   - Remove hardcoded constant `1 / 3` from `feature_vector()`.
   - Upgrade classifier to LightGBM or XGBoost (with scikit-learn fallback) for improved PR-AUC and F1.
4. **Expand Test Suite**:
   - Add comprehensive tests in `tests/` covering rules, ML inference, graph patterns, spike detection, decision policy, failure fallbacks, API routes, and CSRF protection.

---

## 18. P1 Improvements (High Priority Polish)

1. **Dynamic Feature Normalization**:
   - Fit feature scalers (min/max or quantiles) strictly on the 70% training set split to avoid heuristic static constants (`/ 90000`, `/ 12`).
2. **Enhanced Graph Entity Matching**:
   - Expand NetworkX graph visualization and detailed multi-hop relationship metrics in UI.
3. **Export & Reporting Enhancements**:
   - Add full CSV/JSON report download capabilities for evaluation metrics and audit logs.

---

## 19. P2 Polish (Nice to Have)

1. **Dark/Light Mode Toggle & UI Animations**:
   - Add theme switching and subtle micro-interactions to dashboard panels.
2. **Interactive Threshold Simulator**:
   - Allow users on the Model Evaluation page to adjust the decision threshold slider dynamically and see live impact on false positives and protected merchant value.

---

## Direct Audit Answers to 30 Specific Forensic Questions

1. **What has actually been implemented?** Single monolithic Flask app in [main.py](file:///c:/Users/Moses%20Andrew%20Raymond/Downloads/Reclaim-Senetial-main/Reclaim-Senetial-main/main.py) containing synthetic data generation, ML training/evaluation, 8 deterministic rules, NetworkX graph analysis, 4-week rolling spike detector, 3-verdict decision policy, offline/online investigator, SQLite audit logging, session/CSRF auth, and a single-page HTML/JS dashboard.
2. **What currently runs?** `python main.py` runs synchronously, initializes DB, trains RF classifier, computes held-out metrics, builds graph, and hosts server on port 5000. `unittest` passes 5 unit tests.
3. **What is incomplete?** Modular code structure, real-time custom case submission API (`POST /api/verify`), frontend custom case input form, integration tests, and LightGBM/XGBoost model.
4. **What is broken?** Hardcoded feature constant `1 / 3` in `feature_vector()` ([main.py:L198](file:///c:/Users/Moses%20Andrew%20Raymond/Downloads/Reclaim-Senetial-main/Reclaim-Senetial-main/main.py#L198)), "+ Verify a case" button opens old case instead of new verification form ([static/app.js:L77](file:///c:/Users/Moses%20Andrew%20Raymond/Downloads/Reclaim-Senetial-main/Reclaim-Senetial-main/static/app.js#L77)).
5. **What is mocked or hardcoded?** Synthetic dataset (seed 73), demo credentials (`sentinel-demo`/`reclaim-2026`), ₹180 FP cost assumption, offline investigator template strings, feature index 16 constant `1 / 3`.
6. **What dataset currently exists?** 12,000 synthetic return records generated deterministically and stored in `STATE["cases"]` and `data/reclaim_sentinel.db`.
7. **How is the dataset generated?** `generate_dataset()` calling `make_case()` with fixed seed 73, producing realistic timestamps, fulfillment evidence, customer history, and mutations.
8. **What are the ground-truth labels?** `legitimate_return` or `fraudulent_return`, generated via non-linear sigmoid formula of latent risk factors plus 5.5% label flip noise.
9. **What ML model exists?** `RandomForestClassifier` (140 trees, depth 9, balanced subsampling).
10. **What features does the model use?** 17 features: weight delta, SKU mismatch, serial mismatch, condition score, scan result score, timestamp anomaly, customer return count/rate, previous flags, similar claims, refund amount, merchant rates, return delay, account age, category flag, and constant 1/3.
11. **Is there train/validation/test separation?** Yes: 70% train (8,400), 15% validation (1,800), 15% test (1,800) sorted chronologically by purchase timestamp.
12. **Is there a genuine untouched held-out test set?** Yes, the final 1,800 chronologically sorted cases are never seen during model training.
13. **Is there any data leakage?** No target leakage; ground truth is excluded from features and time-aware split prevents future leakage.
14. **Are precision, recall and F1 actually calculated?** Yes, dynamically via `sklearn.metrics` on held-out test predictions ([main.py:L234-236](file:///c:/Users/Moses%20Andrew%20Raymond/Downloads/Reclaim-Senetial-main/Reclaim-Senetial-main/main.py#L234-L236)).
15. **Is false-positive monetary cost actually calculated?** Yes, calculated by summing actual `refund_amount` of false-positive test cases + ₹180/case fee ([main.py:L230](file:///c:/Users/Moses%20Andrew%20Raymond/Downloads/Reclaim-Senetial-main/Reclaim-Senetial-main/main.py#L230)).
16. **Does the return verification engine actually work?** Yes, `run_rules()` evaluates 8 deterministic evidence checks and assigns severity ([main.py:L267](file:///c:/Users/Moses%20Andrew%20Raymond/Downloads/Reclaim-Senetial-main/Reclaim-Senetial-main/main.py#L267)).
17. **Does the system produce APPROVE / HOLD / ESCALATE decisions?** Yes, `analyze_case()` synthesizes evidence into exactly these 3 verdicts ([main.py:L439-444](file:///c:/Users/Moses%20Andrew%20Raymond/Downloads/Reclaim-Senetial-main/Reclaim-Senetial-main/main.py#L439-L444)).
18. **Does abuse-pattern analysis actually work?** Yes, NetworkX graph identifies multi-account clusters sharing devices/addresses/payments within 72 hours ([main.py:L289](file:///c:/Users/Moses%20Andrew%20Raymond/Downloads/Reclaim-Senetial-main/Reclaim-Senetial-main/main.py#L289)).
19. **Does return-abuse spike detection actually work?** Yes, 4-week rolling baseline compares 7-day suspicious rates and outputs z-score deviation $\sigma$ ([main.py:L323](file:///c:/Users/Moses%20Andrew%20Raymond/Downloads/Reclaim-Senetial-main/Reclaim-Senetial-main/main.py#L323)).
20. **Is an LLM actually integrated?** Yes, optionally via OpenAI ChatCompletions API ([main.py:L372](file:///c:/Users/Moses%20Andrew%20Raymond/Downloads/Reclaim-Senetial-main/Reclaim-Senetial-main/main.py#L372)).
21. **Where is the LLM being used?** Exclusively in case detail view to generate 3 non-authoritative human review questions.
22. **Is the LLM incorrectly being used as the final financial decision maker?** No. Decision logic is strictly deterministic and ML-based; LLM cannot change verdicts or amounts.
23. **What failure recovery exists?** Independent `try...except` blocks around sub-engines force default to `ESCALATE TO HUMAN REVIEW` or `HOLD REFUND` on errors ([main.py:L437](file:///c:/Users/Moses%20Andrew%20Raymond/Downloads/Reclaim-Senetial-main/Reclaim-Senetial-main/main.py#L437)).
24. **What happens if the ML model fails?** Model score drops to `None`, fallback risk formula runs, decision defaults to `ESCALATE` or `HOLD`. Never approves.
25. **What happens if the LLM fails?** System catches exception silently and falls back to offline structured summary ([main.py:L407-408](file:///c:/Users/Moses%20Andrew%20Raymond/Downloads/Reclaim-Senetial-main/Reclaim-Senetial-main/main.py#L407-L408)).
26. **What happens if evidence is missing or contradictory?** Missing mandatory evidence triggers rule flags/fails, forcing `HOLD` or `ESCALATE`.
27. **Are financial-impact metrics calculated from real predictions?** Yes, calculated directly from held-out test predictions and actual case refund amounts ([main.py:L229-230](file:///c:/Users/Moses%20Andrew%20Raymond/Downloads/Reclaim-Senetial-main/Reclaim-Senetial-main/main.py#L229-L230)).
28. **Are API keys/secrets present anywhere?** No hardcoded secrets. Environment variables (`OPENAI_API_KEY`, `SESSION_SECRET`) are used.
29. **Can the project be reproduced from this repository?** Yes, running `python main.py` fully recreates dataset, model, database, and web server.
30. **What automated tests exist and do they pass?** 5 unit tests in [tests/test_engine.py](file:///c:/Users/Moses%20Andrew%20Raymond/Downloads/Reclaim-Senetial-main/Reclaim-Senetial-main/tests/test_engine.py); all pass cleanly.
