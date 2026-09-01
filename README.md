# Reclaim Sentinel

Reclaim Sentinel is a defense-only, pre-refund return verification system for merchants. It answers one narrow question: **should this refund be released, held, or sent to a human reviewer?**

The prototype combines:

- deterministic evidence rules for SKU, serial, weight, timing, policy, courier, and warehouse checks;
- a real Random Forest classifier trained on 12,000 synthetic return records;
- time-aware train / validation / untouched held-out test splits;
- NetworkX-backed coordinated-return analysis across customers, devices, addresses, and payments;
- a transparent four-week rolling baseline spike detector;
- a conservative policy layer with exactly three possible verdicts;
- a structured investigator explanation that cannot override the money decision;
- immutable-in-prototype audit events and safe failure paths.

No real customer data is used. No offensive security functionality is included.

## Run locally

```bash
python3 main.py
```

The first start deterministically generates the dataset, trains the model, computes held-out metrics, initializes `data/reclaim_sentinel.db`, and starts the dashboard on port 5000.

Demo credentials: `sentinel-demo` / `reclaim-2026`

## Dashboard

The dashboard includes Overview, Return Cases, Case Details, Abuse Patterns, Return Abuse Spikes, Model Evaluation, and Audit Logs. Open any case to see actual generated fields, triggered rule evidence, the model score, graph context, spike context, decision reason, investigator summary, and audit trail.

## Reproducibility

The random seed is fixed in `main.py`. The dataset is synthetic and created from combinations of noisy, pre-refund fields; the ground-truth label is never passed to the feature generator. The classifier trains on the first 70% of purchase time, validates conceptually on the next 15%, and evaluates on the final untouched 15%.

Supporting documentation:

- [SETUP.md](SETUP.md)
- [ARCHITECTURE.md](ARCHITECTURE.md)
- [MODEL_CARD.md](MODEL_CARD.md)
- [EVALUATION.md](EVALUATION.md)
- [THREAT_MODEL.md](THREAT_MODEL.md)
- [LIMITATIONS.md](LIMITATIONS.md)

## AI boundary

Numerical risk and final refund authority are intentionally not LLM-driven. Deterministic rules are used for facts, the ML model is used for calibrated pattern scoring, and the investigator layer turns structured evidence into a concise review brief. An external LLM can be added behind the investigator boundary, but it must receive only structured evidence and cannot override the policy engine. When evidence is insufficient, the investigator explicitly returns: **“Insufficient evidence for an automated decision.”**