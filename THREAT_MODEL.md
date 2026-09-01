# Threat model

## Assets

- Merchant refund value
- Synthetic return records and relationship identifiers
- Audit trail integrity
- Dashboard sessions

## Defensive controls

- Session authentication for the dashboard
- Input validation on login and human verdict override
- Environment-backed session secret
- Synthetic identifiers only
- No API keys or credentials committed to the repository
- Immutable append-only audit behavior within the prototype
- Conservative failure behavior
- Deterministic rules for factual evidence
- Human review for conflicting or insufficient signals

## Abuse cases

1. **Malformed case input** — fields are generated and the override API rejects unsupported verdicts. Production ingestion should add schema validation at the boundary.
2. **ML outage** — analysis records a failure and escalates or holds; it never approves blindly.
3. **Graph/spike outage** — the missing layer is recorded and policy escalates when certainty is reduced.
4. **Investigator hallucination** — the investigator receives structured evidence only and cannot change the verdict.
5. **Credential misuse** — demo credentials are intentionally temporary; deploy behind a real identity provider.
6. **Audit tampering** — the prototype exposes append-only events through the API; production should move this to a WORM or signed event store.

This project contains no offensive security, exploit generation, credential harvesting, or attack automation.