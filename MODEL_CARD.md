# Model card

## Model

Random Forest classifier, 200 trees, unconstrained max depth, minimum leaf size 4, balanced subsampling, fixed random seed 73. It predicts the probability that a return is fraudulent before refund release. Selected over LightGBM and XGBoost candidates on identical validation data (see `MODEL_SELECTION.md`); the comparison is reproducible via `scripts/compare_models.py`.

## Intended use

Supporting evidence for merchant return verification. It is not an autonomous payment authority, customer score, chargeback model, or general-purpose fraud detector.

## Data

12,000 deterministically generated synthetic return records. Features include package evidence, timeline consistency, customer and merchant historical behavior, refund amount, and category. The ground truth is synthetic and created from several latent signals with noise.

## Split

Records are ordered by purchase time: 70% train, 15% validation, and 15% untouched held-out test, plus a fully disjoint Cold-Entity test set (customers and devices never seen in training). No resolution, refund settlement, or ground-truth feature is used.

## Performance and its ceiling

At the locked threshold (0.35), the model achieves roughly 81% precision but only ~35% recall on the temporal held-out test, and ~64% precision / ~37% recall on the cold-entity test. This recall ceiling is understood and documented, not an unexamined weakness — see `LIMITATIONS.md` for the diagnostic finding. In short: the fraud cases the model misses are almost entirely ones with no physical evidence anomaly and minimal customer history, which are close to statistically indistinguishable from legitimate first-time returns using pre-refund signals alone. Feature engineering (interaction terms) was tested and did not meaningfully change this.

This means the model should be read as **one input among several**, not the primary recall mechanism for the system as a whole — deterministic rules and the coordinated-abuse graph engine are designed to catch fraud patterns the classifier structurally cannot.

## Safety

The model can be unavailable without stopping the application. The policy switches to a deterministic safe fallback and holds or escalates when evidence is not strong enough. The model score cannot override critical rule failures.

## Known risks

Synthetic distributions are not a substitute for merchant-specific calibration. Historical return behavior can encode unfair proxies. The system should be monitored by merchant, category, geography, and customer segment before production use. The ~35% recall ceiling means a meaningful share of low-signal fraud will pass through the ML layer regardless of tuning; merchants relying on this system should treat it as a filter that raises the cost of the easiest fraud, not a guarantee that all fraud is caught.
