import hashlib
import os
import smtplib
import time
from email.message import EmailMessage

from lib.config import require_env
from lib.state import State

DEDUP_TTL_SECONDS = 7 * 86400


def _fingerprint(subject: str, body: str) -> str:
    return hashlib.sha256(f"{subject}|{body[:500]}".encode()).hexdigest()


def _email_disabled_for(catalyst: str | None) -> bool:
    if not catalyst:
        return False
    raw = os.environ.get("CATALYST_EMAIL_DISABLE", "")
    disabled = {p.strip().lower() for p in raw.split(",") if p.strip()}
    return catalyst.lower() in disabled


def _persist_alert(st: State, *, ts: int, catalyst: str, severity: str,
                   subject: str, body: str, emailed: bool, fingerprint: str) -> None:
    with st.connection() as c:
        c.execute(
            "INSERT INTO alerts(ts, catalyst, severity, subject, body, emailed, fingerprint) "
            "VALUES (?,?,?,?,?,?,?)",
            (ts, catalyst, severity, subject, body, 1 if emailed else 0, fingerprint),
        )


def send_alert(subject: str, body: str, severity: str = "MED",
               catalyst: str | None = None,
               state: State | None = None) -> bool:
    """Send an alert. Returns True iff an email was sent.

    Always persists a row to `alerts` table on first sighting (regardless of
    whether the email was sent), respecting the 7-day dedup window on
    (subject, body[:500]).
    """
    st = state or State("notify")
    fp = _fingerprint(subject, body)
    if st.seen("alerts_dedup", fp, ttl_seconds=DEDUP_TTL_SECONDS):
        return False

    tag = (catalyst or "").lower() or "unknown"
    email_muted = _email_disabled_for(catalyst)
    emailed = False

    if not email_muted:
        gmail_user = require_env("GMAIL_USER")
        gmail_pw = require_env("GMAIL_APP_PASSWORD")
        alert_to = require_env("ALERT_TO")

        msg = EmailMessage()
        msg["Subject"] = subject
        msg["From"] = gmail_user
        msg["To"] = alert_to
        msg["X-Catalyst-Severity"] = severity
        msg.set_content(body)

        with smtplib.SMTP_SSL("smtp.gmail.com", 465, timeout=30) as s:
            s.login(gmail_user, gmail_pw)
            s.send_message(msg)
        emailed = True

    _persist_alert(
        st,
        ts=int(time.time()),
        catalyst=tag,
        severity=severity,
        subject=subject,
        body=body,
        emailed=emailed,
        fingerprint=fp,
    )
    st.mark_seen("alerts_dedup", fp)
    return emailed
