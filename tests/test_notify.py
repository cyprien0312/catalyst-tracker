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
