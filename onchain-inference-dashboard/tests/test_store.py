import datetime as dt
import store

NOW = dt.datetime(2026, 9, 8, 8, 10, tzinfo=dt.timezone.utc)


def fresh(tmp_path):
    return store.connect(tmp_path / "t.db")


def rows(conn):
    return sorted(conn.execute("SELECT player, day, metric, value FROM daily").fetchall())


def test_connect_creates_tables(tmp_path):
    conn = fresh(tmp_path)
    names = {r[0] for r in conn.execute("SELECT name FROM sqlite_master WHERE type='table'")}
    assert {"daily", "gm_epochs"} <= names


def test_upsert_inserts_new_rows(tmp_path):
    conn = fresh(tmp_path)
    store.upsert_daily(conn, "chutes", [("2026-09-07", "requests", 10.0)], now=NOW)
    assert rows(conn) == [("chutes", "2026-09-07", "requests", 10.0)]


def test_upsert_updates_within_window(tmp_path):
    conn = fresh(tmp_path)
    store.upsert_daily(conn, "chutes", [("2026-09-06", "requests", 10.0)], now=NOW)   # today-2
    store.upsert_daily(conn, "chutes", [("2026-09-06", "requests", 12.0)], now=NOW)
    assert rows(conn) == [("chutes", "2026-09-06", "requests", 12.0)]


def test_upsert_freezes_older_days(tmp_path):
    conn = fresh(tmp_path)
    store.upsert_daily(conn, "chutes", [("2026-09-05", "requests", 10.0)], now=NOW)   # today-3
    store.upsert_daily(conn, "chutes", [("2026-09-05", "requests", 999.0)], now=NOW)
    assert rows(conn) == [("chutes", "2026-09-05", "requests", 10.0)]


def test_upsert_backfills_missing_old_days(tmp_path):
    conn = fresh(tmp_path)
    store.upsert_daily(conn, "chutes", [("2025-01-30", "requests", 1.0)], now=NOW)
    assert rows(conn) == [("chutes", "2025-01-30", "requests", 1.0)]


def test_upsert_is_idempotent(tmp_path):
    conn = fresh(tmp_path)
    batch = [("2026-09-07", "requests", 10.0), ("2026-09-07", "tokens", 5.0)]
    store.upsert_daily(conn, "chutes", batch, now=NOW)
    store.upsert_daily(conn, "chutes", batch, now=NOW)
    assert len(rows(conn)) == 2


def test_gm_epochs_upsert_dedupes(tmp_path):
    conn = fresh(tmp_path)
    e = [(24989, "2026-09-08T08:16:00+00:00", 10455, 652.99)]
    store.upsert_gm_epochs(conn, e)
    store.upsert_gm_epochs(conn, e)
    assert store.all_gm_epochs(conn) == e


def test_all_daily_returns_everything(tmp_path):
    conn = fresh(tmp_path)
    store.upsert_daily(conn, "a", [("2026-09-07", "requests", 1.0)], now=NOW)
    store.upsert_daily(conn, "b", [("2026-09-07", "requests", 2.0)], now=NOW)
    assert store.all_daily(conn) == [("a", "2026-09-07", "requests", 1.0),
                                     ("b", "2026-09-07", "requests", 2.0)]
