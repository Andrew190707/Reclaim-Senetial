# Architecture

```text
Synthetic generator → SQLite return_cases
                          ↓
          time-aware split → RandomForest model
                          ↓
case → deterministic rules ─┐
      graph patterns       ├→ transparent policy → verdict + audit log
      rolling spike        ┘          ↓
                              structured investigator brief
                          ↓
                 Flask JSON API → dashboard
```

## Data layer

`generate_dataset()` creates 12,000 synthetic records with realistic identifiers, fulfillment timestamps, product evidence, customer history, merchant baselines, and refund values. Fraud is a latent combination of noisy signals, not a direct copy of one field. Only pre-refund data is exposed to the model.

## Deterministic verification

Rules answer questions that should not require a language model: SKU/serial consistency, package-weight discrepancy, condition, event order, policy timing, courier consistency, and warehouse evidence. Each returns `rule_id`, `result`, `evidence`, and `severity`.

## Machine learning

The Random Forest uses a numeric feature vector derived from the raw case. Model output is `fraud_probability`; it is one weighted input to policy, not an authorization. Time-aware splitting prevents future behavior from entering the training period.

**Why this is a multi-layer system rather than a single classifier**: a diagnostic on held-out predictions found the ML model has a structural recall ceiling of roughly 35% — almost every fraud case it misses has no physical evidence anomaly and minimal customer history, which is genuinely indistinguishable from a legitimate first-time return using pre-refund signals alone (see `LIMITATIONS.md` and `MODEL_CARD.md` for the full finding). Feature engineering was tested and did not close this gap in any meaningful way. This is expected, not a defect: it's why fraud detection here isn't ML-alone. Deterministic rules catch physical-evidence fraud regardless of model score, and the graph and spike engines below catch coordination patterns across multiple cases that no single-case classifier could ever see, since they depend on relationships between returns rather than features of one return in isolation.

## Graph and spike engines

NetworkX stores a bipartite return/entity graph (returns connected to customers, devices, addresses, payments, and merchants); the API exposes connected-return evidence and confidence. Keyed indexes keep case inspection fast. Spike detection compares a current seven-day suspicious-return rate with four prior weekly rates and emits a standardized deviation.

## Decision policy

- Critical deterministic contradiction → `HOLD REFUND`.
- High combined risk → `HOLD REFUND`.
- Low risk, clean rules, and no coordination/spike signal → `APPROVE REFUND`.
- Conflicting or insufficient evidence → `ESCALATE TO HUMAN REVIEW`.
- Dependency failures never silently approve a refund.

Thresholds and weights are visible in code and evaluation output. The locked ML threshold (0.35) is chosen to minimize total economic loss, not to maximize recall; the full precision/recall trade-off table is exposed at `/api/evaluation` so a merchant can reason about the recall-vs-false-positive trade-off explicitly rather than trusting one hardcoded cutoff.

## AI boundary

The investigator creates a review brief from structured, already-computed evidence. It does not see arbitrary external content, invent facts, or make the final money decision. The current offline implementation provides a deterministic structured investigator mode so the prototype remains reproducible without an API key.
