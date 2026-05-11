import hashlib
import smtplib
from email.message import EmailMessage

from lib.config import require_env
from lib.state import State

DEDUP_TTL_SECONDS = 7 * 86400


def _fingerprint(subject: str, body: str) -> str:
    return hashlib.sha256(f"{subject}|{body[:500]}".encode()).hexdigest()


def send_alert(subject: str, body: str, severity: str = "MED",
               state: State | None = None) -> bool:
    st = state or State("notify")
    fp = _fingerprint(subject, body)
    if st.seen("alerts_dedup", fp, ttl_seconds=DEDUP_TTL_SECONDS):
        return False

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

    st.mark_seen("alerts_dedup", fp)
    return True
