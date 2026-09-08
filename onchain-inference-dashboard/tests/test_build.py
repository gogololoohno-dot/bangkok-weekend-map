import datetime as dt
import json
import store
import build

NOW = dt.datetime(2026, 9, 8, 8, 10, tzinfo=dt.timezone.utc)


def _seed(conn):
    store.upsert_daily(conn, "chutes", [
        ("2026-09-06", "requests", 100.0), ("2026-09-06", "tokens_in", 900.0),
        ("2026-09-06", "tokens_out", 100.0), ("2026-09-06", "spend_usd", 5.0),
        ("2026-09-07", "requests", 200.0), ("2026-09-07", "tokens_in", 1800.0),
        ("2026-09-07", "tokens_out", 200.0),
        ("2026-09-08", "requests", 50.0),                       # today: excluded
    ], now=NOW)
    store.upsert_daily(conn, "antseed", [
        ("2026-09-07", "requests", 10.0), ("2026-09-07", "tokens", 30.0),
        ("2026-09-07", "spend_gmv", 7.0), ("2026-09-07", "capture_fees", 0.3),
        ("2026-09-07", "dau", 4.0),
    ], now=NOW)
    store.upsert_daily(conn, "engy", [("2026-09-07", "capture_emissions", 9.0)], now=NOW)


def test_build_groups_and_derives(tmp_path):
    conn = store.connect(tmp_path / "t.db")
    _seed(conn)
    out = build.build(conn, now=NOW)
    ch = out["charts"]
    assert ch["requests"]["chutes"] == [["2026-09-06", 100.0], ["2026-09-07", 200.0]]
    assert ch["tokens"]["chutes"] == [["2026-09-06", 1000.0], ["2026-09-07", 2000.0]]
    assert ch["spend"]["chutes"] == [["2026-09-06", 5.0]]
    assert ch["spend"]["antseed"] == [["2026-09-07", 7.0]]
    assert ch["capture"]["antseed"] == [["2026-09-07", 0.3]]
    assert ch["capture"]["engy"] == [["2026-09-07", 9.0]]
    assert ch["tokens_per_request"]["chutes"] == [["2026-09-06", 10.0], ["2026-09-07", 10.0]]
    assert ch["tokens_per_request"]["antseed"] == [["2026-09-07", 3.0]]
    assert "dau" not in json.dumps(ch)


def test_build_excludes_today_and_reports_through(tmp_path):
    conn = store.connect(tmp_path / "t.db")
    _seed(conn)
    out = build.build(conn, now=NOW)
    assert all(d < "2026-09-08" for series in out["charts"]["requests"].values() for d, _ in series)
    assert out["through"] == {"chutes": "2026-09-07", "antseed": "2026-09-07", "engy": "2026-09-07"}


def test_build_absent_player_absent_from_chart(tmp_path):
    conn = store.connect(tmp_path / "t.db")
    _seed(conn)
    out = build.build(conn, now=NOW)
    assert "engy" not in out["charts"]["requests"]      # seeded with capture only
    assert "engy" in out["players"]


def test_write_creates_file(tmp_path):
    conn = store.connect(tmp_path / "t.db")
    _seed(conn)
    target = tmp_path / "data.json"
    build.write(conn, target, now=NOW)
    assert json.loads(target.read_text())["generated_at"].startswith("2026-09-08")


def test_write_standalone_inlines_data(tmp_path):
    conn = store.connect(tmp_path / "t.db")
    _seed(conn)
    (tmp_path / "index.html").write_text("<body>\n<!-- DATA -->\n<script>x</script>", encoding="utf-8")
    out = build.write_standalone(conn, tmp_path / "index.html", tmp_path / "standalone.html", now=NOW)
    html = out.read_text(encoding="utf-8")
    assert "<!-- DATA -->" not in html
    assert "window.__DATA__" in html and '"generated_at": "2026-09-08' in html or '"generated_at":"2026-09-08' in html
    assert html.endswith("<script>x</script>")
