from unittest.mock import MagicMock, patch
from lib.notify import send_alert
from lib.state import State

ENV = {
    "RESEND_API_KEY": "re_test",
    "ALERT_TO": "dest@example.com, other@example.com",
}


def _ok_response():
    r = MagicMock()
    r.status_code = 200
    r.text = '{"id":"x"}'
    return r


@patch("lib.email_send.requests.post")
def test_send_alert_sends_email(post, tmp_path, monkeypatch):
    for k, v in ENV.items():
        monkeypatch.setenv(k, v)
    st = State("notify", db_path=tmp_path / "t.sqlite")
    post.return_value = _ok_response()
    sent = send_alert("subj", "body", state=st)
    assert sent is True
    assert post.called
    payload = post.call_args.kwargs["json"]
    assert payload["to"] == ["dest@example.com", "other@example.com"]
    assert payload["subject"] == "subj"
    assert payload["text"] == "body"
    auth = post.call_args.kwargs["headers"]["Authorization"]
    assert auth == "Bearer re_test"


@patch("lib.email_send.requests.post")
def test_send_alert_dedups_within_ttl(post, tmp_path, monkeypatch):
    for k, v in ENV.items():
        monkeypatch.setenv(k, v)
    st = State("notify", db_path=tmp_path / "t.sqlite")
    post.return_value = _ok_response()
    assert send_alert("subj", "body", state=st) is True
    assert send_alert("subj", "body", state=st) is False


@patch("lib.email_send.requests.post")
def test_send_alert_sends_when_body_differs(post, tmp_path, monkeypatch):
    for k, v in ENV.items():
        monkeypatch.setenv(k, v)
    st = State("notify", db_path=tmp_path / "t.sqlite")
    post.return_value = _ok_response()
    assert send_alert("subj", "body A", state=st) is True
    assert send_alert("subj", "body B", state=st) is True


@patch("lib.email_send.requests.post")
def test_send_alert_severity_header(post, tmp_path, monkeypatch):
    for k, v in ENV.items():
        monkeypatch.setenv(k, v)
    st = State("notify", db_path=tmp_path / "t.sqlite")
    post.return_value = _ok_response()
    send_alert("subj", "body", severity="HIGH", state=st)
    payload = post.call_args.kwargs["json"]
    assert payload["headers"]["X-Catalyst-Severity"] == "HIGH"


import sqlite3

@patch("lib.email_send.requests.post")
def test_send_alert_persists_row(post, tmp_path, monkeypatch):
    for k, v in ENV.items():
        monkeypatch.setenv(k, v)
    st = State("notify", db_path=tmp_path / "t.sqlite")
    post.return_value = _ok_response()
    send_alert("subj", "body", severity="HIGH", catalyst="c3", state=st)
    with sqlite3.connect(tmp_path / "t.sqlite") as c:
        rows = c.execute("SELECT catalyst, severity, subject, emailed FROM alerts").fetchall()
    assert rows == [("c3", "HIGH", "subj", 1)]


@patch("lib.email_send.requests.post")
def test_send_alert_skips_email_when_catalyst_disabled(post, tmp_path, monkeypatch):
    for k, v in ENV.items():
        monkeypatch.setenv(k, v)
    monkeypatch.setenv("CATALYST_EMAIL_DISABLE", "c3")
    st = State("notify", db_path=tmp_path / "t.sqlite")
    post.return_value = _ok_response()
    sent = send_alert("subj", "body", severity="HIGH", catalyst="c3", state=st)
    assert sent is False
    post.assert_not_called()
    with sqlite3.connect(tmp_path / "t.sqlite") as c:
        rows = c.execute("SELECT catalyst, emailed FROM alerts").fetchall()
    assert rows == [("c3", 0)]


@patch("lib.email_send.requests.post")
def test_send_alert_disable_list_is_csv(post, tmp_path, monkeypatch):
    for k, v in ENV.items():
        monkeypatch.setenv(k, v)
    monkeypatch.setenv("CATALYST_EMAIL_DISABLE", "c2, c3 ,c5")
    st = State("notify", db_path=tmp_path / "t.sqlite")
    post.return_value = _ok_response()
    send_alert("a", "body", catalyst="c3", state=st)
    send_alert("b", "body", catalyst="c1", state=st)
    assert post.call_count == 1


@patch("lib.email_send.requests.post")
def test_min_severity_floor_mutes_below_and_emails_at_or_above(post, tmp_path, monkeypatch):
    for k, v in ENV.items():
        monkeypatch.setenv(k, v)
    monkeypatch.setenv("CATALYST_EMAIL_MIN_SEVERITY", "c6:HIGH")
    st = State("notify", db_path=tmp_path / "t.sqlite")
    post.return_value = _ok_response()
    # MED is below the floor -> muted but persisted.
    assert send_alert("med", "body", severity="MED", catalyst="c6", state=st) is False
    # HIGH is at the floor -> emails.
    assert send_alert("high", "body2", severity="HIGH", catalyst="c6", state=st) is True
    # CRITICAL is above the floor -> emails.
    assert send_alert("crit", "body3", severity="CRITICAL", catalyst="c6", state=st) is True
    assert post.call_count == 2
    with sqlite3.connect(tmp_path / "t.sqlite") as c:
        rows = dict(c.execute("SELECT severity, emailed FROM alerts").fetchall())
    assert rows == {"MED": 0, "HIGH": 1, "CRITICAL": 1}


@patch("lib.email_send.requests.post")
def test_min_severity_floor_overrides_blanket_disable(post, tmp_path, monkeypatch):
    """A floor for c6 wins even if c6 is also in the blanket disable list."""
    for k, v in ENV.items():
        monkeypatch.setenv(k, v)
    monkeypatch.setenv("CATALYST_EMAIL_DISABLE", "c3,c6")
    monkeypatch.setenv("CATALYST_EMAIL_MIN_SEVERITY", "c6:HIGH")
    st = State("notify", db_path=tmp_path / "t.sqlite")
    post.return_value = _ok_response()
    assert send_alert("a", "body", severity="HIGH", catalyst="c6", state=st) is True
    # c3 has no floor and stays fully muted.
    assert send_alert("b", "body", severity="CRITICAL", catalyst="c3", state=st) is False


@patch("lib.email_send.requests.post")
def test_send_alert_dedup_prevents_second_db_row(post, tmp_path, monkeypatch):
    for k, v in ENV.items():
        monkeypatch.setenv(k, v)
    st = State("notify", db_path=tmp_path / "t.sqlite")
    post.return_value = _ok_response()
    send_alert("subj", "body", catalyst="c1", state=st)
    send_alert("subj", "body", catalyst="c1", state=st)
    with sqlite3.connect(tmp_path / "t.sqlite") as c:
        n = c.execute("SELECT COUNT(*) FROM alerts").fetchone()[0]
    assert n == 1
