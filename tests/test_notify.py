from unittest.mock import MagicMock, patch
from lib.notify import send_alert
from lib.state import State

ENV = {
    "GMAIL_USER": "alerts@example.com",
    "GMAIL_APP_PASSWORD": "pw",
    "ALERT_TO": "dest@example.com",
}


@patch("lib.notify.smtplib.SMTP_SSL")
def test_send_alert_sends_email(smtp_cls, tmp_path, monkeypatch):
    for k, v in ENV.items():
        monkeypatch.setenv(k, v)
    st = State("notify", db_path=tmp_path / "t.sqlite")
    smtp = smtp_cls.return_value.__enter__.return_value = MagicMock()
    sent = send_alert("subj", "body", state=st)
    assert sent is True
    smtp.login.assert_called_once_with("alerts@example.com", "pw")
    assert smtp.send_message.called


@patch("lib.notify.smtplib.SMTP_SSL")
def test_send_alert_dedups_within_ttl(smtp_cls, tmp_path, monkeypatch):
    for k, v in ENV.items():
        monkeypatch.setenv(k, v)
    st = State("notify", db_path=tmp_path / "t.sqlite")
    smtp_cls.return_value.__enter__.return_value = MagicMock()
    assert send_alert("subj", "body", state=st) is True
    assert send_alert("subj", "body", state=st) is False


@patch("lib.notify.smtplib.SMTP_SSL")
def test_send_alert_sends_when_body_differs(smtp_cls, tmp_path, monkeypatch):
    for k, v in ENV.items():
        monkeypatch.setenv(k, v)
    st = State("notify", db_path=tmp_path / "t.sqlite")
    smtp_cls.return_value.__enter__.return_value = MagicMock()
    assert send_alert("subj", "body A", state=st) is True
    assert send_alert("subj", "body B", state=st) is True


@patch("lib.notify.smtplib.SMTP_SSL")
def test_send_alert_severity_header(smtp_cls, tmp_path, monkeypatch):
    for k, v in ENV.items():
        monkeypatch.setenv(k, v)
    st = State("notify", db_path=tmp_path / "t.sqlite")
    smtp = smtp_cls.return_value.__enter__.return_value = MagicMock()
    send_alert("subj", "body", severity="HIGH", state=st)
    msg = smtp.send_message.call_args.args[0]
    assert msg["X-Catalyst-Severity"] == "HIGH"


import sqlite3

@patch("lib.notify.smtplib.SMTP_SSL")
def test_send_alert_persists_row(smtp_cls, tmp_path, monkeypatch):
    for k, v in ENV.items():
        monkeypatch.setenv(k, v)
    st = State("notify", db_path=tmp_path / "t.sqlite")
    smtp_cls.return_value.__enter__.return_value = MagicMock()
    send_alert("subj", "body", severity="HIGH", catalyst="c3", state=st)
    with sqlite3.connect(tmp_path / "t.sqlite") as c:
        rows = c.execute("SELECT catalyst, severity, subject, emailed FROM alerts").fetchall()
    assert rows == [("c3", "HIGH", "subj", 1)]


@patch("lib.notify.smtplib.SMTP_SSL")
def test_send_alert_skips_email_when_catalyst_disabled(smtp_cls, tmp_path, monkeypatch):
    for k, v in ENV.items():
        monkeypatch.setenv(k, v)
    monkeypatch.setenv("CATALYST_EMAIL_DISABLE", "c3")
    st = State("notify", db_path=tmp_path / "t.sqlite")
    smtp = smtp_cls.return_value.__enter__.return_value = MagicMock()
    sent = send_alert("subj", "body", severity="HIGH", catalyst="c3", state=st)
    assert sent is False
    smtp.send_message.assert_not_called()
    with sqlite3.connect(tmp_path / "t.sqlite") as c:
        rows = c.execute("SELECT catalyst, emailed FROM alerts").fetchall()
    assert rows == [("c3", 0)]


@patch("lib.notify.smtplib.SMTP_SSL")
def test_send_alert_disable_list_is_csv(smtp_cls, tmp_path, monkeypatch):
    for k, v in ENV.items():
        monkeypatch.setenv(k, v)
    monkeypatch.setenv("CATALYST_EMAIL_DISABLE", "c2, c3 ,c5")
    st = State("notify", db_path=tmp_path / "t.sqlite")
    smtp = smtp_cls.return_value.__enter__.return_value = MagicMock()
    send_alert("a", "body", catalyst="c3", state=st)
    send_alert("b", "body", catalyst="c1", state=st)
    assert smtp.send_message.call_count == 1


@patch("lib.notify.smtplib.SMTP_SSL")
def test_min_severity_floor_mutes_below_and_emails_at_or_above(smtp_cls, tmp_path, monkeypatch):
    for k, v in ENV.items():
        monkeypatch.setenv(k, v)
    monkeypatch.setenv("CATALYST_EMAIL_MIN_SEVERITY", "c6:HIGH")
    st = State("notify", db_path=tmp_path / "t.sqlite")
    smtp = smtp_cls.return_value.__enter__.return_value = MagicMock()
    # MED is below the floor -> muted but persisted.
    assert send_alert("med", "body", severity="MED", catalyst="c6", state=st) is False
    # HIGH is at the floor -> emails.
    assert send_alert("high", "body2", severity="HIGH", catalyst="c6", state=st) is True
    # CRITICAL is above the floor -> emails.
    assert send_alert("crit", "body3", severity="CRITICAL", catalyst="c6", state=st) is True
    assert smtp.send_message.call_count == 2
    with sqlite3.connect(tmp_path / "t.sqlite") as c:
        rows = dict(c.execute("SELECT severity, emailed FROM alerts").fetchall())
    assert rows == {"MED": 0, "HIGH": 1, "CRITICAL": 1}


@patch("lib.notify.smtplib.SMTP_SSL")
def test_min_severity_floor_overrides_blanket_disable(smtp_cls, tmp_path, monkeypatch):
    """A floor for c6 wins even if c6 is also in the blanket disable list."""
    for k, v in ENV.items():
        monkeypatch.setenv(k, v)
    monkeypatch.setenv("CATALYST_EMAIL_DISABLE", "c3,c6")
    monkeypatch.setenv("CATALYST_EMAIL_MIN_SEVERITY", "c6:HIGH")
    st = State("notify", db_path=tmp_path / "t.sqlite")
    smtp_cls.return_value.__enter__.return_value = MagicMock()
    assert send_alert("a", "body", severity="HIGH", catalyst="c6", state=st) is True
    # c3 has no floor and stays fully muted.
    assert send_alert("b", "body", severity="CRITICAL", catalyst="c3", state=st) is False


@patch("lib.notify.smtplib.SMTP_SSL")
def test_send_alert_dedup_prevents_second_db_row(smtp_cls, tmp_path, monkeypatch):
    for k, v in ENV.items():
        monkeypatch.setenv(k, v)
    st = State("notify", db_path=tmp_path / "t.sqlite")
    smtp_cls.return_value.__enter__.return_value = MagicMock()
    send_alert("subj", "body", catalyst="c1", state=st)
    send_alert("subj", "body", catalyst="c1", state=st)
    with sqlite3.connect(tmp_path / "t.sqlite") as c:
        n = c.execute("SELECT COUNT(*) FROM alerts").fetchone()[0]
    assert n == 1
