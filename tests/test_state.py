import time
from lib.state import State


def test_seen_returns_false_before_mark(tmp_path):
    st = State("test", db_path=tmp_path / "t.sqlite")
    assert st.seen("foo", "k1") is False


def test_mark_then_seen_returns_true(tmp_path):
    st = State("test", db_path=tmp_path / "t.sqlite")
    st.mark_seen("foo", "k1")
    assert st.seen("foo", "k1") is True


def test_seen_expires_with_ttl(tmp_path):
    st = State("test", db_path=tmp_path / "t.sqlite")
    st.mark_seen("foo", "k1")
    with st.connection() as c:
        c.execute(
            "UPDATE seen SET ts = ? WHERE table_name=? AND key=?",
            (int(time.time()) - 100, "foo", "k1"),
        )
    assert st.seen("foo", "k1", ttl_seconds=50) is False
    assert st.seen("foo", "k1", ttl_seconds=500) is True


def test_mark_seen_idempotent(tmp_path):
    st = State("test", db_path=tmp_path / "t.sqlite")
    st.mark_seen("foo", "k1")
    st.mark_seen("foo", "k1")
    assert st.seen("foo", "k1") is True


def test_connection_is_usable_for_custom_tables(tmp_path):
    st = State("test", db_path=tmp_path / "t.sqlite")
    with st.connection() as c:
        c.execute("CREATE TABLE x(a INTEGER PRIMARY KEY)")
        c.execute("INSERT INTO x(a) VALUES (1)")
    with st.connection() as c:
        rows = list(c.execute("SELECT a FROM x"))
    assert rows == [(1,)]


def test_alerts_table_created():
    import tempfile, sqlite3
    from pathlib import Path
    from lib.state import State
    with tempfile.TemporaryDirectory() as d:
        db = Path(d) / "t.sqlite"
        State("x", db_path=db)
        with sqlite3.connect(db) as c:
            cols = {r[1] for r in c.execute("PRAGMA table_info(alerts)")}
        assert {"id", "ts", "catalyst", "severity", "subject", "body", "emailed", "fingerprint"} <= cols
