import sqlite3
import time
from contextlib import contextmanager
from pathlib import Path

DEFAULT_DB = Path("state/tracker.sqlite")

_SCHEMA = """
CREATE TABLE IF NOT EXISTS seen (
    table_name TEXT NOT NULL,
    key        TEXT NOT NULL,
    ts         INTEGER NOT NULL,
    PRIMARY KEY(table_name, key)
);
CREATE TABLE IF NOT EXISTS alerts (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    ts          INTEGER NOT NULL,
    catalyst    TEXT NOT NULL,
    severity    TEXT NOT NULL,
    subject     TEXT NOT NULL,
    body        TEXT NOT NULL,
    emailed     INTEGER NOT NULL DEFAULT 0,
    fingerprint TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_alerts_ts ON alerts(ts DESC);
"""


class State:
    def __init__(self, namespace: str, db_path: Path | str = DEFAULT_DB):
        self.namespace = namespace
        self.db_path = Path(db_path)
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        with self.connection() as c:
            c.executescript(_SCHEMA)

    @contextmanager
    def connection(self):
        conn = sqlite3.connect(self.db_path, isolation_level=None)
        conn.execute("PRAGMA journal_mode=WAL")
        conn.execute("PRAGMA synchronous=NORMAL")
        try:
            yield conn
        finally:
            conn.close()

    def seen(self, table: str, key: str, ttl_seconds: int | None = None) -> bool:
        with self.connection() as c:
            row = c.execute(
                "SELECT ts FROM seen WHERE table_name=? AND key=?",
                (table, key),
            ).fetchone()
        if row is None:
            return False
        if ttl_seconds is None:
            return True
        return (int(time.time()) - int(row[0])) <= ttl_seconds

    def mark_seen(self, table: str, key: str) -> None:
        with self.connection() as c:
            c.execute(
                "INSERT INTO seen(table_name, key, ts) VALUES(?,?,?) "
                "ON CONFLICT(table_name, key) DO UPDATE SET ts=excluded.ts",
                (table, key, int(time.time())),
            )
