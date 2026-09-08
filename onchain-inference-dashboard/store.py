"""SQLite store. Owns the write rule that protects banked history."""

import datetime as dt
import sqlite3
from pathlib import Path

DB_PATH = Path(__file__).parent / "data" / "inference.db"

# Rows whose day is within this many days of "now" (inclusive of today) may be updated.
# Older rows are frozen: their source window has rolled past them and they can never be
# re-derived, so a bad fetch must not be allowed to overwrite them.
UPDATE_WINDOW_DAYS = 3

SCHEMA = """
CREATE TABLE IF NOT EXISTS daily (
  player     TEXT NOT NULL,
  day        TEXT NOT NULL,
  metric     TEXT NOT NULL,
  value      REAL NOT NULL,
  scraped_at TEXT NOT NULL,
  PRIMARY KEY (player, day, metric)
);
CREATE TABLE IF NOT EXISTS gm_epochs (
  epoch        INTEGER PRIMARY KEY,
  finalized_at TEXT NOT NULL,
  requests     INTEGER NOT NULL,
  value_usd    REAL NOT NULL
);
"""


def connect(path: Path = DB_PATH) -> sqlite3.Connection:
    path.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(path)
    conn.executescript(SCHEMA)
    return conn


def upsert_daily(conn, player: str, rows, now: dt.datetime | None = None) -> None:
    now = now or dt.datetime.now(dt.timezone.utc)
    cutoff = (now.date() - dt.timedelta(days=UPDATE_WINDOW_DAYS - 1)).isoformat()
    stamp = now.isoformat(timespec="seconds")
    conn.executemany(
        """
        INSERT INTO daily (player, day, metric, value, scraped_at) VALUES (?, ?, ?, ?, ?)
        ON CONFLICT(player, day, metric) DO UPDATE
          SET value = excluded.value, scraped_at = excluded.scraped_at
          WHERE excluded.day >= ?
        """,
        [(player, day, metric, float(value), stamp, cutoff) for day, metric, value in rows],
    )
    conn.commit()


def all_daily(conn):
    return conn.execute(
        "SELECT player, day, metric, value FROM daily ORDER BY player, day, metric"
    ).fetchall()


def upsert_gm_epochs(conn, epochs) -> None:
    conn.executemany(
        "INSERT OR REPLACE INTO gm_epochs (epoch, finalized_at, requests, value_usd) "
        "VALUES (?, ?, ?, ?)",
        epochs,
    )
    conn.commit()


def all_gm_epochs(conn):
    return conn.execute(
        "SELECT epoch, finalized_at, requests, value_usd FROM gm_epochs ORDER BY epoch"
    ).fetchall()
