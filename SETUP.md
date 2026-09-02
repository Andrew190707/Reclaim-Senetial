# Setup

## Requirements

- Python 3.11+
- Flask, NumPy, scikit-learn, NetworkX, and joblib (declared in `pyproject.toml`)

## Start

```bash
python3 main.py
```

Reclaim Sentinel binds to `0.0.0.0:5000`, which works in the Replit preview. The application creates its SQLite file under `data/` on first start. It is intentionally ignored by git because it is a generated artifact.

## Authentication

The prototype uses a session cookie. Demo credentials are shown in the login screen and are intentionally non-production. In a real deployment, replace the demo login with the merchant's identity provider and keep `SESSION_SECRET` in the environment.

## Reset generated state

Stop the process, remove `data/reclaim_sentinel.db`, and run the start command again. The same seed regenerates the same 12,000 records and model evaluation.

## Optional test command

```bash
python3 -m unittest discover -s tests -v
```