import types
import store
import scrape


def _src(name, player, rows=None, error=None):
    m = types.ModuleType(name)
    m.PLAYER = player
    m.KIND = "api"
    def fetch():
        if error:
            raise error
        return rows
    m.fetch = fetch
    return m


def test_run_commits_good_sources_and_reports_failures(tmp_path):
    conn = store.connect(tmp_path / "t.db")
    good = _src("sources.good", "a", rows=[("2026-09-07", "requests", 1.0)])
    bad = _src("sources.bad", "b", error=ValueError("format changed"))
    failed = scrape.run([good, bad], conn)
    assert failed == ["sources.bad"]
    assert store.all_daily(conn) == [("a", "2026-09-07", "requests", 1.0)]


def test_run_returns_empty_when_all_succeed(tmp_path):
    conn = store.connect(tmp_path / "t.db")
    good = _src("sources.good", "a", rows=[("2026-09-07", "requests", 1.0)])
    assert scrape.run([good], conn) == []


def test_select_filters_by_module_name():
    a = _src("sources.gm", "gm", rows=[])
    b = _src("sources.chutes", "chutes", rows=[])
    assert scrape.select([a, b], only="gm") == [a]
    assert scrape.select([a, b], only=None) == [a, b]
