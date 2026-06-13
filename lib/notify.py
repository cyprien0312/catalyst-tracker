import hashlib
import os
import smtplib
import time
from email.message import EmailMessage

from lib.config import require_env
from lib.state import State

DEDUP_TTL_SECONDS = 7 * 86400

_SEVERITY_ORDER = {"LOG": 0, "MED": 1, "HIGH": 2, "CRITICAL": 3}


def _fingerprint(subject: str, body: str) -> str:
    return hashlib.sha256(f"{subject}|{body[:500]}".encode()).hexdigest()


def _min_severity_for(catalyst: str | None) -> str | None:
    """Per-catalyst email floor from CATALYST_EMAIL_MIN_SEVERITY.

    Format: 'c6:HIGH,c3:CRITICAL' — for that catalyst, only alerts at or above
    the named severity email; quieter ones are muted (but still persisted).
    Returns the floor name (e.g. 'HIGH') or None if no floor is set.
    """
    if not catalyst:
        return None
    raw = os.environ.get("CATALYST_EMAIL_MIN_SEVERITY", "")
    for part in raw.split(","):
        part = part.strip()
        if not part or ":" not in part:
            continue
        tag, _, floor = part.partition(":")
        if tag.strip().lower() == catalyst.lower():
            floor = floor.strip().upper()
            if floor in _SEVERITY_ORDER:
                return floor
    return None


def _email_muted_for(catalyst: str | None, severity: str) -> bool:
    """Decide whether to suppress the email for this alert.

    A per-catalyst floor (CATALYST_EMAIL_MIN_SEVERITY) takes precedence: when
    set, the alert emails iff its severity is at or above the floor. Otherwise
    the blanket CATALYST_EMAIL_DISABLE list mutes the catalyst entirely.
    """
    floor = _min_severity_for(catalyst)
    if floor is not None:
        return _SEVERITY_ORDER.get(severity, 1) < _SEVERITY_ORDER[floor]
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
    email_muted = _email_muted_for(catalyst, severity)
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
