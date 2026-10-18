"""Outbound email via the Resend HTTP API.

Replaces the old Gmail SMTP path. Both the per-alert sender (`lib/notify.py`)
and the daily digest (`scripts/daily_report.py`) route through `send_email`.

Env:
- RESEND_API_KEY  (required) — Resend API key, e.g. `re_...`
- RESEND_FROM     (optional) — From header. Default `Catalyst Tracker
  <onboarding@resend.dev>`. NOTE: Resend only delivers to arbitrary recipients
  from a *verified domain*; the `onboarding@resend.dev` sandbox sender can only
  reach the Resend account owner's own address.
- ALERT_TO        (required) — comma-separated list of recipients.
- CATALYST_EMAIL_OFF (optional) — `1` = global kill switch: nothing is sent
  (alerts, digest, news roll-up). Monitoring and alert persistence continue.
"""
import os

import requests

from lib.config import require_env

RESEND_ENDPOINT = "https://api.resend.com/emails"
DEFAULT_FROM = "Catalyst Tracker <onboarding@resend.dev>"


def email_off() -> bool:
    """Global kill switch: CATALYST_EMAIL_OFF=1 suppresses every outbound email."""
    return os.environ.get("CATALYST_EMAIL_OFF", "").strip().lower() in {"1", "true", "yes", "on"}


def recipients() -> list[str]:
    """Parse ALERT_TO into a list of trimmed, non-empty addresses."""
    raw = require_env("ALERT_TO")
    return [a.strip() for a in raw.split(",") if a.strip()]


def send_email(subject: str, *, text: str, html: str | None = None,
               headers: dict[str, str] | None = None,
               timeout: int = 30) -> None:
    """Send an email through Resend. Raises on transport/API failure.

    No-op when the global kill switch (CATALYST_EMAIL_OFF) is on.
    """
    if email_off():
        return
    api_key = require_env("RESEND_API_KEY")
    sender = os.environ.get("RESEND_FROM") or DEFAULT_FROM

    payload: dict = {
        "from": sender,
        "to": recipients(),
        "subject": subject,
        "text": text,
    }
    if html is not None:
        payload["html"] = html
    if headers:
        payload["headers"] = headers

    resp = requests.post(
        RESEND_ENDPOINT,
        json=payload,
        headers={"Authorization": f"Bearer {api_key}"},
        timeout=timeout,
    )
    if resp.status_code >= 300:
        raise RuntimeError(
            f"Resend send failed: HTTP {resp.status_code} {resp.text[:300]}"
        )
