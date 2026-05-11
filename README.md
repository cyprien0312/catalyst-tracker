# catalyst-tracker

AI Infrastructure Bubble-Stress catalyst tracker. See `docs/source-spec.md` for full design.

## Local dev

    python3 -m venv .venv
    . .venv/bin/activate
    pip install -r requirements-dev.txt
    pytest

## Send a test email

Set `GMAIL_USER`, `GMAIL_APP_PASSWORD`, `ALERT_TO` in env, then:

    python scripts/test_alert.py
