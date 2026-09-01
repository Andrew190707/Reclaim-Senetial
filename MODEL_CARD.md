# Model card

## Model

Random Forest classifier, 140 trees, maximum depth 9, minimum leaf size 4, balanced subsampling, fixed random seed 73. It predicts the probability that a return is fraudulent before refund release.

## Intended use

Supporting evidence for merchant return verification. It is not an autonomous payment authority, customer score, chargeback model, or general-purpose fraud detector.

## Data

12,000 deterministically generated synthetic return records. Features include package evidence, timeline consistency, customer and merchant historical behavior, refund amount, and category. The ground truth is synthetic and created from several latent signals with noise.

## Split

Records are ordered by purchase time: 70% train, 15% validation, and 15% untouched held-out test. No resolution, refund settlement, or ground-truth feature is used.

## Safety

The model can be unavailable without stopping the application. The policy switches to a deterministic safe fallback and holds or escalates when evidence is not strong enough. The model score cannot override critical rule failures.

## Known risks

Synthetic distributions are not a substitute for merchant-specific calibration. Historical return behavior can encode unfair proxies. The system should be monitored by merchant, category, geography, and customer segment before production use.