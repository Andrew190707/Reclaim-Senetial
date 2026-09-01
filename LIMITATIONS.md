# Limitations

- Data is synthetic. Held-out metrics demonstrate a functioning evaluation path, not production performance.
- The baseline model is global rather than merchant-calibrated.
- The demo login is not production authentication.
- SQLite and in-memory indexes are suitable for a prototype, not a high-volume multi-tenant service.
- The graph view uses shared identifiers as supporting evidence; shared households or fulfillment centers can create legitimate links.
- The investigator is deterministic offline text generation. An optional LLM should be constrained to structured evidence and remain non-authoritative.
- Policy thresholds require review with merchant false-positive tolerance, refund economics, and customer-protection requirements.
- A real deployment needs signed audit events, retention policy, access logging, rate limiting, CSRF protection, schema validation at ingestion, and a production secret manager.