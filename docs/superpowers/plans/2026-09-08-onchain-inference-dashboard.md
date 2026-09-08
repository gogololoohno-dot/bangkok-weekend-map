# Onchain Inference Dashboard Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** A daily scraper that accumulates requests/tokens/money metrics for 7 onchain inference players into SQLite, and a single-file HTML dashboard that charts them side by side.

**Architecture:** One adapter module per source, each exposing `fetch() -> list[(day, metric, value)]` and a pure `parse()` that tests exercise against saved fixtures. `store.py` owns the SQLite write rule (insert-if-missing, update only trailing 3 days). `build.py` flattens the store into `dashboard/data.json`; `dashboard/index.html` renders it with inline SVG.

**Tech Stack:** Python 3.11 stdlib only at runtime (`urllib`, `sqlite3`, `re`, `json`); `pytest` for tests via `uv`; vanilla HTML/JS/SVG for the dashboard. No runtime dependencies.

**Spec:** `docs/superpowers/specs/2026-09-08-onchain-inference-dashboard-design.md`

---

## File structure

```
onchain-inference-dashboard/
  pyproject.toml            # uv project, pytest config, no runtime deps
  .gitignore                # data/*.db, dashboard/data.json
  web.py                    # get(url) -> bytes with browser UA (NOT http.py: shadows stdlib)
  store.py                  # connect(), upsert_daily(), upsert_gm_epochs(), queries
  scrape.py                 # runs every source in isolation, exit 1 if any failed
  build.py                  # store -> dashboard/data.json
  sources/
    __init__.py             # SOURCES: list of adapter modules
    chutes.py               # api   player=chutes
    venice.py               # api   player=venice
    blockrun.py             # api   player=blockrun
    surplus.py              # scrape player=surplus
    engy.py                 # scrape player=engy   (requests, tokens)
    engy_emissions.py       # api   player=engy   (capture_emissions via taostats)
    antseed.py              # scrape player=antseed
    gm.py                   # scrape player=gm     (epoch grain -> daily)
  dashboard/
    index.html
  data/                     # inference.db lives here (gitignored)
  tests/
    fixtures/               # surplus.html antseed.html engy_requests.html engy_tokens.html gm_miners.html
    test_store.py test_chutes.py test_venice.py test_blockrun.py test_surplus.py
    test_engy.py test_engy_emissions.py test_antseed.py test_gm.py test_scrape.py test_build.py
```

Every adapter module declares two constants and two functions:

```python
PLAYER = "chutes"        # row player name
KIND = "api"             # "api" | "scrape"  -> UI badge
def parse(...) -> list[tuple[str, str, float]]   # pure, tested against fixtures
def fetch() -> list[tuple[str, str, float]]      # HTTP + parse
```

Metric names used across the system (build.py groups them into charts):

| metric | chart | players |
|---|---|---|
| `requests` | requests | chutes, antseed, surplus, engy, gm, blockrun |
| `tokens`, `tokens_in`, `tokens_out`, `tokens_cache` | tokens (summed) | chutes (in/out), surplus (in/out/cache), antseed, engy (`tokens`) |
| `spend_usd`, `spend_gmv` | spend | chutes, gm (`spend_usd`); antseed (`spend_gmv`) |
| `capture_fees`, `capture_emissions`, `capture_burns` | capture | antseed, engy, venice |
| `dau`, `settles`, `settlements`, `settlements_failed`, `credits_count`, `subs_count` | stored, off-chart | antseed, blockrun, venice |

---

### Task 1: Project scaffold

**Files:**
- Create: `onchain-inference-dashboard/pyproject.toml`
- Create: `onchain-inference-dashboard/.gitignore`
- Create: `onchain-inference-dashboard/web.py`
- Create: `onchain-inference-dashboard/sources/__init__.py` (empty for now)
- Create: `onchain-inference-dashboard/tests/__init__.py` (empty)
- Create: `onchain-inference-dashboard/data/.gitkeep`

- [ ] **Step 1: Write pyproject.toml**

```toml
[project]
name = "onchain-inference-dashboard"
version = "0.1.0"
description = "Daily scraper + single-file dashboard for onchain inference players"
requires-python = ">=3.11"
dependencies = []

[dependency-groups]
dev = ["pytest>=8.0"]

[tool.pytest.ini_options]
pythonpath = ["."]
testpaths = ["tests"]
```

- [ ] **Step 2: Write .gitignore**

```
data/*.db
dashboard/data.json
__pycache__/
.pytest_cache/
.venv/
```

- [ ] **Step 3: Write web.py**

The module is named `web`, not `http` — a root-level `http.py` would shadow the stdlib package and break `urllib` itself.

```python
"""Single HTTP entrypoint for every adapter.

venicestats.com returns 403 to Python's default User-Agent, so every request goes
out with a browser-style UA.
"""

import urllib.request

UA = ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
      "(KHTML, like Gecko) Chrome/128.0 Safari/537.36")


def get(url: str, timeout: int = 90, headers: dict | None = None) -> bytes:
    req = urllib.request.Request(url, headers={"User-Agent": UA, **(headers or {})})
    with urllib.request.urlopen(req, timeout=timeout) as r:
        return r.read()
```

- [ ] **Step 4: Create empty files and verify pytest runs**

```powershell
New-Item -ItemType File onchain-inference-dashboard/sources/__init__.py, onchain-inference-dashboard/tests/__init__.py, onchain-inference-dashboard/data/.gitkeep
```

Run: `cd onchain-inference-dashboard; uv run pytest`
Expected: `no tests ran` with exit code 5 (pytest's "no tests collected") — proves uv resolved pytest and pythonpath config is loaded.

- [ ] **Step 5: Commit**

```bash
git add onchain-inference-dashboard
git commit -m "Scaffold onchain-inference-dashboard project"
```

---

### Task 2: store.py — write rule

**Files:**
- Create: `onchain-inference-dashboard/store.py`
- Test: `onchain-inference-dashboard/tests/test_store.py`

The write rule is the most important correctness property in the system: insert any missing `(player, day, metric)`; update an existing row only if `day` is within the trailing 3 days (today, yesterday, day before); never touch anything older.

- [ ] **Step 1: Write the failing tests**

```python
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
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `uv run pytest tests/test_store.py -v`
Expected: all FAIL with `ModuleNotFoundError: No module named 'store'`

- [ ] **Step 3: Write store.py**

```python
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
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `uv run pytest tests/test_store.py -v`
Expected: 8 passed

- [ ] **Step 5: Commit**

```bash
git add store.py tests/test_store.py
git commit -m "Add SQLite store with 3-day update window write rule"
```

---

### Task 3: Chutes adapter

**Files:**
- Create: `onchain-inference-dashboard/sources/chutes.py`
- Test: `onchain-inference-dashboard/tests/test_chutes.py`

Two public endpoints. `/invocations/stats/llm` is per-model-per-day (~20MB, 587 days); `/invocations/usage` is per-chute-per-day USD (12 days). Both are summed by date. Fixtures are inline — the real payloads are too large to commit and the shape is simple.

- [ ] **Step 1: Write the failing tests**

```python
import json
import pytest
from sources import chutes

STATS = json.dumps([
    {"chute_id": "a", "name": "GLM", "date": "2026-09-07", "total_requests": 100,
     "total_input_tokens": 1000, "total_output_tokens": 50, "average_tps": 1, "average_ttft": 1},
    {"chute_id": "b", "name": "Kimi", "date": "2026-09-07", "total_requests": 20,
     "total_input_tokens": 200, "total_output_tokens": 10, "average_tps": 1, "average_ttft": 1},
    {"chute_id": "a", "name": "GLM", "date": "2026-09-06", "total_requests": 7,
     "total_input_tokens": 70, "total_output_tokens": 3, "average_tps": 1, "average_ttft": 1},
]).encode()

USAGE = json.dumps([
    {"chute_id": "a", "date": "2026-09-07", "usd_amount": 1.5, "invocation_count": 100},
    {"chute_id": "b", "date": "2026-09-07", "usd_amount": 2.25, "invocation_count": 20},
]).encode()


def test_parse_stats_sums_models_per_day():
    rows = set(chutes.parse_stats(STATS))
    assert ("2026-09-07", "requests", 120.0) in rows
    assert ("2026-09-07", "tokens_in", 1200.0) in rows
    assert ("2026-09-07", "tokens_out", 60.0) in rows
    assert ("2026-09-06", "requests", 7.0) in rows
    assert len(rows) == 6


def test_parse_usage_sums_chutes_per_day():
    assert chutes.parse_usage(USAGE) == [("2026-09-07", "spend_usd", 3.75)]


def test_empty_payload_raises():
    with pytest.raises(ValueError):
        chutes.parse_stats(b"[]")
    with pytest.raises(ValueError):
        chutes.parse_usage(b"[]")


def test_declares_contract():
    assert chutes.PLAYER == "chutes"
    assert chutes.KIND == "api"
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `uv run pytest tests/test_chutes.py -v`
Expected: FAIL with `ImportError: cannot import name 'chutes'`

- [ ] **Step 3: Write sources/chutes.py**

```python
"""Chutes (Bittensor SN64). Public REST, documented at api.chutes.ai/openapi.json.

/invocations/stats/llm  -> per model per day: requests, input/output tokens (587 days)
/invocations/usage      -> per chute per day: usd_amount (rolling ~12 days)
/daily_revenue_summary returns 401 and is not used.
"""

import collections
import json

from web import get

PLAYER = "chutes"
KIND = "api"

STATS_URL = "https://api.chutes.ai/invocations/stats/llm"
USAGE_URL = "https://api.chutes.ai/invocations/usage"


def parse_stats(raw: bytes):
    agg = collections.defaultdict(lambda: [0, 0, 0])
    for r in json.loads(raw):
        a = agg[r["date"]]
        a[0] += r["total_requests"]
        a[1] += r["total_input_tokens"]
        a[2] += r["total_output_tokens"]
    if not agg:
        raise ValueError("chutes stats/llm: no rows")
    rows = []
    for day, (req, tin, tout) in agg.items():
        rows += [(day, "requests", float(req)),
                 (day, "tokens_in", float(tin)),
                 (day, "tokens_out", float(tout))]
    return rows


def parse_usage(raw: bytes):
    agg = collections.defaultdict(float)
    for r in json.loads(raw):
        agg[r["date"]] += r["usd_amount"]
    if not agg:
        raise ValueError("chutes usage: no rows")
    return [(day, "spend_usd", v) for day, v in agg.items()]


def fetch():
    return parse_stats(get(STATS_URL, timeout=180)) + parse_usage(get(USAGE_URL))
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `uv run pytest tests/test_chutes.py -v`
Expected: 4 passed

- [ ] **Step 5: Commit**

```bash
git add sources/chutes.py tests/test_chutes.py
git commit -m "Add Chutes adapter (public REST, requests/tokens/spend)"
```

---

### Task 4: Venice adapter

**Files:**
- Create: `onchain-inference-dashboard/sources/venice.py`
- Test: `onchain-inference-dashboard/tests/test_venice.py`

`creditsUsdThen` and `proSubUsdThen` are the USD value **burned** (~$5/credit burn, ~$2.2/sub), not purchase value. They go on the protocol-capture chart as `capture_burns`. Use `*UsdThen`, never `*UsdNow` — `Now` revalues history at today's VVV price. `discUsdThen` (treasury buyback) is not ingested.

- [ ] **Step 1: Write the failing tests**

```python
import json
import pytest
from sources import venice

RAW = json.dumps({"granularity": "daily", "range": "all", "buckets": [
    {"t": 1788739200000, "discUsdThen": 5000.0, "discUsdNow": 9999.0,
     "proSubUsdThen": 4288.0, "proSubUsdNow": 9999.0, "proSubCount": 1850,
     "creditsUsdThen": 10130.0, "creditsUsdNow": 9999.0, "creditsCount": 2026, "hasOneOff": False},
]}).encode()


def test_parse_maps_burn_value_to_capture():
    rows = set(venice.parse(RAW))
    assert ("2026-09-06", "capture_burns", 14418.0) in rows       # credits + subs, "Then" only
    assert ("2026-09-06", "credits_count", 2026.0) in rows
    assert ("2026-09-06", "subs_count", 1850.0) in rows
    assert len(rows) == 3


def test_empty_raises():
    with pytest.raises(ValueError):
        venice.parse(json.dumps({"buckets": []}).encode())


def test_declares_contract():
    assert venice.PLAYER == "venice" and venice.KIND == "api"
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `uv run pytest tests/test_venice.py -v`
Expected: FAIL with ImportError

- [ ] **Step 3: Write sources/venice.py**

```python
"""Venice. Public REST at venicestats.com (403s Python's default UA; web.get sets one).

burns-timeline daily buckets from 2025-11-07. The USD fields are the value BURNED per
programmatic burn event (~$5 per credit purchase, ~$2.2 per subscription), not the
purchase amount, so they are protocol capture, not buyer spend. "*UsdThen" is USD at
burn time; "*UsdNow" revalues at today's price and would rewrite history daily.
"""

import datetime as dt
import json

from web import get

PLAYER = "venice"
KIND = "api"

URL = "https://venicestats.com/api/burns-timeline?granularity=daily&range=all"


def _day(ms: int) -> str:
    return dt.datetime.fromtimestamp(ms / 1000, dt.timezone.utc).date().isoformat()


def parse(raw: bytes):
    buckets = json.loads(raw).get("buckets", [])
    if not buckets:
        raise ValueError("venice burns-timeline: no buckets")
    rows = []
    for b in buckets:
        day = _day(b["t"])
        rows += [(day, "capture_burns", float(b["creditsUsdThen"]) + float(b["proSubUsdThen"])),
                 (day, "credits_count", float(b["creditsCount"])),
                 (day, "subs_count", float(b["proSubCount"]))]
    return rows


def fetch():
    return parse(get(URL))
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `uv run pytest tests/test_venice.py -v`
Expected: 3 passed

- [ ] **Step 5: Commit**

```bash
git add sources/venice.py tests/test_venice.py
git commit -m "Add Venice adapter (burn value as protocol capture)"
```

---

### Task 5: BlockRun adapter

**Files:**
- Create: `onchain-inference-dashboard/sources/blockrun.py`
- Test: `onchain-inference-dashboard/tests/test_blockrun.py`

Rolling-24h snapshot, no history. Assigned to the UTC day **preceding** the scrape (the window ending ~08:10 UTC mostly covers it), so `build.py`'s exclusion of the partial current day does not hide it.

- [ ] **Step 1: Write the failing tests**

```python
import datetime as dt
import json
import pytest
from sources import blockrun

OVERVIEW = json.dumps({"timestamp": "2026-09-08T08:40:39.357Z", "overall": "degraded",
                       "models": {"total": 78}, "chain": {"status": "healthy"},
                       "totalCalls24h": 914}).encode()
CHAIN = json.dumps({"timestamp": "2026-09-08T08:40:39.897Z", "successRate24h": 0.997,
                    "avgSettlementTimeMs": 1420, "totalSettlements24h": 8293,
                    "failedSettlements24h": 24, "recentFailures": []}).encode()
NOW = dt.datetime(2026, 9, 8, 8, 10, tzinfo=dt.timezone.utc)


def test_parse_assigns_to_preceding_day():
    rows = set(blockrun.parse(OVERVIEW, CHAIN, now=NOW))
    assert rows == {("2026-09-07", "requests", 914.0),
                    ("2026-09-07", "settlements", 8293.0),
                    ("2026-09-07", "settlements_failed", 24.0)}


def test_missing_field_raises():
    with pytest.raises(KeyError):
        blockrun.parse(b"{}", CHAIN, now=NOW)


def test_declares_contract():
    assert blockrun.PLAYER == "blockrun" and blockrun.KIND == "api"
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `uv run pytest tests/test_blockrun.py -v`
Expected: FAIL with ImportError

- [ ] **Step 3: Write sources/blockrun.py**

```python
"""BlockRun (x402 pay-per-use gateway). Public health API, rolling 24h figures only.

No history is exposed, so each scrape banks one point. The 24h window ending at scrape
time mostly covers the previous UTC day, which is where the point is written. A missed
day is a permanent gap and must not be interpolated.
"""

import datetime as dt
import json

from web import get

PLAYER = "blockrun"
KIND = "api"

OVERVIEW_URL = "https://blockrun.ai/api/v1/health/overview"
CHAIN_URL = "https://blockrun.ai/api/v1/health/chain"


def parse(overview_raw: bytes, chain_raw: bytes, now: dt.datetime | None = None):
    now = now or dt.datetime.now(dt.timezone.utc)
    day = (now.date() - dt.timedelta(days=1)).isoformat()
    overview = json.loads(overview_raw)
    chain = json.loads(chain_raw)
    return [(day, "requests", float(overview["totalCalls24h"])),
            (day, "settlements", float(chain["totalSettlements24h"])),
            (day, "settlements_failed", float(chain["failedSettlements24h"]))]


def fetch():
    return parse(get(OVERVIEW_URL), get(CHAIN_URL))
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `uv run pytest tests/test_blockrun.py -v`
Expected: 3 passed

- [ ] **Step 5: Commit**

```bash
git add sources/blockrun.py tests/test_blockrun.py
git commit -m "Add BlockRun adapter (24h snapshot to preceding day)"
```

---

### Task 6: Fixtures for the scraped sources

**Files:**
- Create: `onchain-inference-dashboard/tests/fixtures/surplus.html`
- Create: `onchain-inference-dashboard/tests/fixtures/antseed.html`
- Create: `onchain-inference-dashboard/tests/fixtures/engy_requests.html`
- Create: `onchain-inference-dashboard/tests/fixtures/engy_tokens.html`
- Create: `onchain-inference-dashboard/tests/fixtures/gm_miners.html`
- Create: `onchain-inference-dashboard/tests/conftest.py`

The expected values in Tasks 7–10 were read from captures taken **2026-09-08 ~08:00 UTC**. Re-capturing produces different numbers; the captures used are in this session's scratchpad. If they are unavailable, re-capture with the curl commands below and update every expected value in Tasks 7–10 from the new files.

- [ ] **Step 1: Copy the captured fixtures**

```powershell
$src = "C:\Users\punth\AppData\Local\Temp\claude\C--Users-punth-New-folder\28f5919b-b2de-4b12-9832-03464a5a0780\scratchpad"
New-Item -ItemType Directory -Force tests/fixtures
Copy-Item "$src\surplus.html"     tests/fixtures/surplus.html
Copy-Item "$src\antseed.html"     tests/fixtures/antseed.html
Copy-Item "$src\engy.html"        tests/fixtures/engy_requests.html
Copy-Item "$src\engy_tokens.html" tests/fixtures/engy_tokens.html
Copy-Item "$src\gm.html"          tests/fixtures/gm_miners.html
```

Re-capture commands if the scratchpad is gone (expected values will then need updating):

```bash
UA="Mozilla/5.0"
curl -s -A "$UA" https://www.surplusintelligence.ai/analytics   -o tests/fixtures/surplus.html
curl -s -A "$UA" https://antseedstats.com/                       -o tests/fixtures/antseed.html
curl -s -A "$UA" https://provider.engy.ai/requests               -o tests/fixtures/engy_requests.html
curl -s -A "$UA" "https://provider.engy.ai/requests?m=tokens"    -o tests/fixtures/engy_tokens.html
curl -s -A "$UA" https://saygm.com/miners                        -o tests/fixtures/gm_miners.html
```

- [ ] **Step 2: Write tests/conftest.py**

```python
from pathlib import Path
import pytest

FIXTURES = Path(__file__).parent / "fixtures"


@pytest.fixture
def fixture():
    def load(name: str) -> bytes:
        return (FIXTURES / name).read_bytes()
    return load
```

- [ ] **Step 3: Verify sizes are sane**

Run: `Get-ChildItem tests/fixtures | Select-Object Name, Length`
Expected: surplus ~209KB, antseed ~343KB, engy_requests ~43KB, engy_tokens ~43KB, gm_miners ~1.9MB

- [ ] **Step 4: Commit**

```bash
git add tests/fixtures tests/conftest.py
git commit -m "Add captured HTML fixtures for scraped sources (2026-09-08)"
```

---

### Task 7: Surplus adapter

**Files:**
- Create: `onchain-inference-dashboard/sources/surplus.py`
- Test: `onchain-inference-dashboard/tests/test_surplus.py`

The Next.js RSC payload embeds the chart data as JSON with escaped quotes (`\"day\":\"2026-09-05\"`). One regex extracts every day record.

- [ ] **Step 1: Write the failing tests**

```python
import pytest
from sources import surplus


def test_parse_extracts_28_days(fixture):
    rows = surplus.parse(fixture("surplus.html"))
    days = sorted({d for d, _, _ in rows})
    assert len(days) == 28
    assert days[0] == "2026-08-12" and days[-1] == "2026-09-08"


def test_parse_known_day(fixture):
    rows = set(surplus.parse(fixture("surplus.html")))
    assert ("2026-09-05", "requests", 1464868.0) in rows
    assert ("2026-09-05", "tokens_in", 72484554369.0) in rows
    assert ("2026-09-05", "tokens_out", 1457577822.0) in rows
    assert ("2026-09-05", "tokens_cache", 58873521207.0) in rows


def test_no_match_raises():
    with pytest.raises(ValueError):
        surplus.parse(b"<html>nothing here</html>")


def test_declares_contract():
    assert surplus.PLAYER == "surplus" and surplus.KIND == "scrape"
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `uv run pytest tests/test_surplus.py -v`
Expected: FAIL with ImportError

- [ ] **Step 3: Write sources/surplus.py**

```python
"""Surplus Intelligence. Server-rendered Next.js; chart data is embedded in the RSC
payload as escaped JSON. Rolling 28 UTC days; the current day is partial.
"""

import re

from web import get

PLAYER = "surplus"
KIND = "scrape"

URL = "https://www.surplusintelligence.ai/analytics"

_DAY = re.compile(
    r'\\"day\\":\\"(\d{4}-\d\d-\d\d)\\",'
    r'\\"requests\\":(\d+),'
    r'\\"inputTokens\\":(\d+),'
    r'\\"outputTokens\\":(\d+),'
    r'\\"cacheTokens\\":(\d+)'
)


def parse(raw: bytes):
    text = raw.decode("utf-8", errors="replace")
    matches = _DAY.findall(text)
    if not matches:
        raise ValueError("surplus: no day records found in payload (format changed?)")
    rows = []
    for day, req, tin, tout, tcache in matches:
        rows += [(day, "requests", float(req)),
                 (day, "tokens_in", float(tin)),
                 (day, "tokens_out", float(tout)),
                 (day, "tokens_cache", float(tcache))]
    return rows


def fetch():
    return parse(get(URL))
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `uv run pytest tests/test_surplus.py -v`
Expected: 4 passed

- [ ] **Step 5: Commit**

```bash
git add sources/surplus.py tests/test_surplus.py
git commit -m "Add Surplus adapter (RSC payload scrape)"
```

---

### Task 8: Engy adapter (requests + tokens)

**Files:**
- Create: `onchain-inference-dashboard/sources/engy.py`
- Test: `onchain-inference-dashboard/tests/test_engy.py`

Payload shape: `\"buckets\":[<epoch s> x31],\"series\":[{\"model\":\"...\",\"counts\":[...]}]`. `buckets[i]` is the UTC midnight of day `i`. Two pages, same shape: `/requests` and `/requests?m=tokens`. Sum counts across models per bucket.

- [ ] **Step 1: Write the failing tests**

```python
import pytest
from sources import engy


def test_parse_requests_page(fixture):
    rows = engy.parse(fixture("engy_requests.html"), "requests")
    assert len(rows) == 31
    days = [d for d, _, _ in rows]
    assert days[0] == "2026-08-09" and days[-1] == "2026-09-08"
    # first bucket: qwen3.6-35b-a3b=615485 + deepseek=8680 + glm-5.2=31471 + others
    by_day = dict((d, v) for d, _, v in rows)
    assert by_day["2026-08-09"] > 615485
    assert all(m == "requests" for _, m, _ in rows)


def test_parse_tokens_page(fixture):
    rows = engy.parse(fixture("engy_tokens.html"), "tokens")
    assert len(rows) == 31
    by_day = dict((d, v) for d, _, v in rows)
    assert by_day["2026-08-09"] > 6077651372          # first model's first bucket alone


def test_length_mismatch_raises():
    bad = (b'\\"buckets\\":[1788739200,1788825600],'
           b'\\"series\\":[{\\"model\\":\\"x\\",\\"counts\\":[1,2,3]}]')
    with pytest.raises(ValueError):
        engy.parse(bad, "requests")


def test_no_buckets_raises():
    with pytest.raises(ValueError):
        engy.parse(b"<html></html>", "requests")


def test_declares_contract():
    assert engy.PLAYER == "engy" and engy.KIND == "scrape"
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `uv run pytest tests/test_engy.py -v`
Expected: FAIL with ImportError

- [ ] **Step 3: Write sources/engy.py**

```python
"""Engy (Bittensor SN53) provider gateway. Server-rendered; the RSC payload carries an
explicit "buckets" date axis (epoch seconds, UTC midnight) and per-model "counts".
Rolling 31 days; the last bucket is the current, partial day.
"""

import datetime as dt
import re

from web import get

PLAYER = "engy"
KIND = "scrape"

REQUESTS_URL = "https://provider.engy.ai/requests"
TOKENS_URL = "https://provider.engy.ai/requests?m=tokens"

_BUCKETS = re.compile(r'\\"buckets\\":\[([\d,]+)\],\\"series\\"')
_SERIES = re.compile(r'\\"model\\":\\"([^\\"]+)\\",\\"counts\\":\[([\d,]*)\]')


def _day(sec: int) -> str:
    return dt.datetime.fromtimestamp(sec, dt.timezone.utc).date().isoformat()


def parse(raw: bytes, metric: str):
    text = raw.decode("utf-8", errors="replace")
    m = _BUCKETS.search(text)
    if not m:
        raise ValueError("engy: no buckets axis found (format changed?)")
    buckets = [int(x) for x in m.group(1).split(",")]
    series = _SERIES.findall(text)
    if not series:
        raise ValueError("engy: no model series found")
    totals = [0] * len(buckets)
    for model, counts in series:
        vals = [int(x) for x in counts.split(",")] if counts else []
        if len(vals) != len(buckets):
            raise ValueError(f"engy: {model} has {len(vals)} counts for {len(buckets)} buckets")
        for i, v in enumerate(vals):
            totals[i] += v
    return [(_day(b), metric, float(t)) for b, t in zip(buckets, totals)]


def fetch():
    return parse(get(REQUESTS_URL), "requests") + parse(get(TOKENS_URL), "tokens")
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `uv run pytest tests/test_engy.py -v`
Expected: 5 passed

- [ ] **Step 5: Commit**

```bash
git add sources/engy.py tests/test_engy.py
git commit -m "Add Engy adapter (explicit bucket axis, requests + tokens)"
```

---

### Task 9: Engy emissions adapter (taostats)

**Files:**
- Create: `onchain-inference-dashboard/sources/engy_emissions.py`
- Test: `onchain-inference-dashboard/tests/test_engy_emissions.py`

Reuses the pricing math from `inference-farm/scripts/poll_sn53.py`: sum `daily_mining_alpha / 1e9` across miners × `pool.price` (alpha in TAO) × TAO/USD. This is a daily-rate snapshot, assigned to the preceding UTC day like BlockRun. Kept as a separate source so a missing taostats key cannot block Engy's requests/tokens.

Key lookup: `TAOSTATS_API_KEY` env var, else `inference-farm/.env` (already exists in this repo).

- [ ] **Step 1: Write the failing tests**

```python
import datetime as dt
import pytest
from sources import engy_emissions as em

NOW = dt.datetime(2026, 9, 8, 8, 10, tzinfo=dt.timezone.utc)
NEURONS = [{"daily_mining_alpha": "1000000000000"},    # 1000 alpha
           {"daily_mining_alpha": "2000000000000"},    # 2000 alpha
           {"daily_mining_alpha": "0"}]
POOL = {"price": "0.03"}          # alpha in TAO
TAO_USD = 200.0


def test_compute_prices_miner_pool():
    rows = em.compute(NEURONS, POOL, TAO_USD, now=NOW)
    # 3000 alpha * 0.03 TAO * $200 = $18,000
    assert rows == [("2026-09-07", "capture_emissions", 18000.0)]


def test_no_miners_raises():
    with pytest.raises(ValueError):
        em.compute([{"daily_mining_alpha": "0"}], POOL, TAO_USD, now=NOW)


def test_declares_contract():
    assert em.PLAYER == "engy" and em.KIND == "api"
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `uv run pytest tests/test_engy_emissions.py -v`
Expected: FAIL with ImportError

- [ ] **Step 3: Write sources/engy_emissions.py**

```python
"""Engy (SN53) miner emissions in USD, via taostats. Same math as
inference-farm/scripts/poll_sn53.py. A daily-rate snapshot, not a settlement figure:
this is token issuance to miners, not buyer money, and sits on the capture chart.
"""

import datetime as dt
import json
import os
import time
import urllib.request
from pathlib import Path

PLAYER = "engy"
KIND = "api"

NETUID = 53
BASE = "https://api.taostats.io/api"
RAO = 1e9
ENV_FILE = Path(__file__).resolve().parents[2] / "inference-farm" / ".env"


def load_key() -> str:
    if os.environ.get("TAOSTATS_API_KEY"):
        return os.environ["TAOSTATS_API_KEY"]
    if ENV_FILE.exists():
        for line in ENV_FILE.read_text().splitlines():
            if line.startswith("TAOSTATS_API_KEY="):
                return line.split("=", 1)[1].strip()
    raise RuntimeError(f"No TAOSTATS_API_KEY in env or {ENV_FILE}")


def _get(path, key, **params):
    qs = "&".join(f"{k}={v}" for k, v in params.items())
    req = urllib.request.Request(f"{BASE}/{path}?{qs}", headers={
        "Authorization": key, "accept": "application/json",
        # Cloudflare rejects the default urllib UA before auth is checked.
        "User-Agent": "onchain-inference-dashboard/0.1",
    })
    with urllib.request.urlopen(req, timeout=30) as r:
        return json.load(r)


def compute(neurons, pool, tao_usd: float, now: dt.datetime | None = None):
    now = now or dt.datetime.now(dt.timezone.utc)
    day = (now.date() - dt.timedelta(days=1)).isoformat()
    total_alpha = sum(float(n.get("daily_mining_alpha") or 0) for n in neurons) / RAO
    if total_alpha <= 0:
        raise ValueError("engy emissions: no miner alpha reported")
    alpha_usd = float(pool["price"]) * tao_usd
    return [(day, "capture_emissions", total_alpha * alpha_usd)]


def fetch():
    key = load_key()
    resp = _get("metagraph/latest/v1", key, netuid=NETUID, limit=256)
    neurons = resp["data"]
    total = resp.get("pagination", {}).get("total_items", len(neurons))
    if len(neurons) < total:
        raise ValueError(f"engy emissions: got {len(neurons)} of {total} neurons")
    time.sleep(2)  # free tier rate-limits bursts
    pool = _get("dtao/pool/latest/v1", key, netuid=NETUID)["data"][0]
    time.sleep(2)
    tao_usd = float(_get("price/latest/v1", key, asset="tao")["data"][0]["price"])
    return compute(neurons, pool, tao_usd)
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `uv run pytest tests/test_engy_emissions.py -v`
Expected: 3 passed

- [ ] **Step 5: Commit**

```bash
git add sources/engy_emissions.py tests/test_engy_emissions.py
git commit -m "Add Engy emissions adapter (taostats, capture chart)"
```

---

### Task 10: AntSeed adapter

**Files:**
- Create: `onchain-inference-dashboard/sources/antseed.py`
- Test: `onchain-inference-dashboard/tests/test_antseed.py`

Day records are embedded as escaped JSON with `day` in epoch milliseconds. 153 days in the fixture (2026-04-09 → 2026-09-08).

- [ ] **Step 1: Write the failing tests**

```python
import pytest
from sources import antseed


def test_parse_extracts_full_history(fixture):
    rows = antseed.parse(fixture("antseed.html"))
    days = sorted({d for d, _, _ in rows})
    assert len(days) == 153
    assert days[0] == "2026-04-09" and days[-1] == "2026-09-08"


def test_parse_known_day(fixture):
    rows = set(antseed.parse(fixture("antseed.html")))
    assert ("2026-09-04", "requests", 75859.0) in rows
    assert ("2026-09-04", "tokens", 1368778609.0) in rows
    assert ("2026-09-04", "spend_gmv", 1842.858222) in rows
    assert ("2026-09-04", "capture_fees", 73.713038) in rows
    assert ("2026-09-04", "dau", 148.0) in rows
    assert ("2026-09-04", "settles", 2958.0) in rows


def test_no_match_raises():
    with pytest.raises(ValueError):
        antseed.parse(b"<html></html>")


def test_declares_contract():
    assert antseed.PLAYER == "antseed" and antseed.KIND == "scrape"
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `uv run pytest tests/test_antseed.py -v`
Expected: FAIL with ImportError

- [ ] **Step 3: Write sources/antseed.py**

```python
"""AntSeed marketplace stats (antseedstats.com). Server-rendered; full daily history since
genesis (2026-04-09) is embedded as escaped JSON. `volume` is settlement GMV (buyer spend);
`fees` is the protocol take (capture).
"""

import datetime as dt
import re

from web import get

PLAYER = "antseed"
KIND = "scrape"

URL = "https://antseedstats.com/"

_DAY = re.compile(
    r'\\"day\\":(\d{13}),'
    r'\\"dau\\":(\d+),'
    r'\\"freeDau\\":\d+,'
    r'\\"newUsers\\":\d+,'
    r'\\"newFree\\":\d+,'
    r'\\"volume\\":([\d.]+),'
    r'\\"fees\\":([\d.]+),'
    r'\\"settles\\":(\d+),'
    r'\\"requests\\":(\d+),'
    r'\\"tokens\\":(\d+)'
)


def _day(ms: int) -> str:
    return dt.datetime.fromtimestamp(ms / 1000, dt.timezone.utc).date().isoformat()


def parse(raw: bytes):
    text = raw.decode("utf-8", errors="replace")
    matches = _DAY.findall(text)
    if not matches:
        raise ValueError("antseed: no day records found (format changed?)")
    rows = []
    for ms, dau, volume, fees, settles, requests, tokens in matches:
        day = _day(int(ms))
        rows += [(day, "requests", float(requests)),
                 (day, "tokens", float(tokens)),
                 (day, "spend_gmv", float(volume)),
                 (day, "capture_fees", float(fees)),
                 (day, "dau", float(dau)),
                 (day, "settles", float(settles))]
    return rows


def fetch():
    return parse(get(URL))
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `uv run pytest tests/test_antseed.py -v`
Expected: 4 passed

- [ ] **Step 5: Commit**

```bash
git add sources/antseed.py tests/test_antseed.py
git commit -m "Add AntSeed adapter (full history, GMV + fees)"
```

---

### Task 11: gm adapter (epoch grain → daily)

**Files:**
- Create: `onchain-inference-dashboard/sources/gm.py`
- Test: `onchain-inference-dashboard/tests/test_gm.py`

The "Finalized epochs" table is real HTML (not RSC JSON): 20 rows, ~72 min each ≈ 24h. `parse_epochs` extracts `(epoch, finalized_at_iso, requests, value_usd)`. `rollup` is pure and enforces the completeness rule: a day is emitted only if an epoch exists on a later day AND every epoch number from the last one before the day through the first one after it is present. `fetch()` upserts epochs into the store, then rolls up everything banked.

- [ ] **Step 1: Write the failing tests**

```python
import pytest
from sources import gm


def test_parse_epochs_from_fixture(fixture):
    epochs = gm.parse_epochs(fixture("gm_miners.html"))
    assert len(epochs) == 20
    assert epochs[0] == (24989, "2026-09-08T08:16:00+00:00", 10455, 652.99)
    assert epochs[-1] == (24970, "2026-09-07T09:23:00+00:00", 13288, 554.53)


def test_parse_no_table_raises():
    with pytest.raises(ValueError):
        gm.parse_epochs(b"<html></html>")


def _ep(n, ts, req=10, usd=1.0):
    return (n, ts, req, usd)


def test_rollup_emits_only_fully_bracketed_days():
    epochs = [
        _ep(100, "2026-09-06T23:30:00+00:00"),      # last before 09-07
        _ep(101, "2026-09-07T00:42:00+00:00"),
        _ep(102, "2026-09-07T01:54:00+00:00"),
        _ep(103, "2026-09-07T23:50:00+00:00"),
        _ep(104, "2026-09-08T01:02:00+00:00"),      # first after 09-07
    ]
    rows = gm.rollup(epochs)
    assert ("2026-09-07", "requests", 30.0) in rows
    assert ("2026-09-07", "spend_usd", 3.0) in rows
    # 09-06 has nothing before it; 09-08 has nothing after it -> both withheld
    assert {d for d, _, _ in rows} == {"2026-09-07"}


def test_rollup_withholds_day_with_missing_epoch():
    epochs = [
        _ep(100, "2026-09-06T23:30:00+00:00"),
        _ep(101, "2026-09-07T00:42:00+00:00"),
        # 102 missing
        _ep(103, "2026-09-07T23:50:00+00:00"),
        _ep(104, "2026-09-08T01:02:00+00:00"),
    ]
    assert gm.rollup(epochs) == []


def test_rollup_withholds_first_observed_day():
    epochs = [_ep(101, "2026-09-07T00:42:00+00:00"), _ep(102, "2026-09-08T01:02:00+00:00")]
    assert gm.rollup(epochs) == []


def test_declares_contract():
    assert gm.PLAYER == "gm" and gm.KIND == "scrape"
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `uv run pytest tests/test_gm.py -v`
Expected: FAIL with ImportError

- [ ] **Step 3: Write sources/gm.py**

```python
"""gm (Bittensor SN28) gateway. The miners page renders a "Finalized epochs" HTML table of
the last 20 epochs (~72 min each, ~24h total, no back history). Epochs are banked by number
in gm_epochs and rolled up into UTC days; a day is emitted only when its epoch range is
contiguous and bracketed on both sides, so a scrape gap becomes a visible hole rather than
an understated day. Scrape twice daily: 20 epochs is exactly one day with zero margin.
"""

import collections
import datetime as dt
import html
import re

import store
from web import get

PLAYER = "gm"
KIND = "scrape"

URL = "https://saygm.com/miners"

_CAPTION = "Finalized epochs, newest first"
_ROW = re.compile(r"<tr[^>]*>(.*?)</tr>", re.S)
_CELL = re.compile(r"<t[dh][^>]*>(.*?)</t[dh]>", re.S)
_TAG = re.compile(r"<[^>]+>")
_TS = re.compile(r"(\d{4}-\d\d-\d\d \d\d:\d\d) UTC")


def _text(cell: str) -> str:
    return html.unescape(_TAG.sub("", cell)).strip()


def parse_epochs(raw: bytes):
    text = raw.decode("utf-8", errors="replace")
    i = text.find(_CAPTION)
    if i < 0:
        raise ValueError("gm: epochs table not found (format changed?)")
    body_start = text.find("<tbody", i)
    body_end = text.find("</tbody>", body_start)
    if body_start < 0 or body_end < 0:
        raise ValueError("gm: epochs tbody not found")
    epochs = []
    for row in _ROW.findall(text[body_start:body_end]):
        cells = [_text(c) for c in _CELL.findall(row)]
        if len(cells) < 6:
            continue
        epoch = int(cells[0].replace(",", ""))
        ts = _TS.search(cells[1])
        if not ts:
            raise ValueError(f"gm: unparseable timestamp {cells[1]!r}")
        finalized = dt.datetime.strptime(ts.group(1), "%Y-%m-%d %H:%M").replace(
            tzinfo=dt.timezone.utc).isoformat()
        requests = int(cells[4].replace(",", ""))
        value = float(cells[5].replace("$", "").replace(",", ""))
        epochs.append((epoch, finalized, requests, value))
    if not epochs:
        raise ValueError("gm: epochs table had no rows")
    return epochs


def rollup(epochs):
    epochs = sorted(epochs)
    have = {e[0] for e in epochs}
    by_day = collections.defaultdict(list)
    for e in epochs:
        by_day[e[1][:10]].append(e)
    rows = []
    for day in sorted(by_day):
        before = [e[0] for e in epochs if e[1][:10] < day]
        after = [e[0] for e in epochs if e[1][:10] > day]
        if not before or not after:
            continue
        lo, hi = max(before), min(after)
        if any(n not in have for n in range(lo, hi + 1)):
            continue
        rows.append((day, "requests", float(sum(e[2] for e in by_day[day]))))
        rows.append((day, "spend_usd", float(sum(e[3] for e in by_day[day]))))
    return rows


def fetch():
    conn = store.connect()
    store.upsert_gm_epochs(conn, parse_epochs(get(URL)))
    return rollup(store.all_gm_epochs(conn))
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `uv run pytest tests/test_gm.py -v`
Expected: 6 passed

- [ ] **Step 5: Commit**

```bash
git add sources/gm.py tests/test_gm.py
git commit -m "Add gm adapter (epoch table, contiguity-checked daily rollup)"
```

---

### Task 12: Source registry and scrape.py

**Files:**
- Modify: `onchain-inference-dashboard/sources/__init__.py`
- Create: `onchain-inference-dashboard/scrape.py`
- Test: `onchain-inference-dashboard/tests/test_scrape.py`

`scrape.py` runs every source in isolation: one failing source does not block the others, successful sources still commit, and the process exits 1 if anything failed so Task Scheduler surfaces it. `--only gm` supports the second daily gm-only run.

- [ ] **Step 1: Write sources/__init__.py**

```python
"""Registry. Adding a player = one module + one line here."""

from sources import antseed, blockrun, chutes, engy, engy_emissions, gm, surplus, venice

SOURCES = [chutes, venice, blockrun, surplus, engy, engy_emissions, antseed, gm]

PLAYERS = {
    "chutes":   {"label": "Chutes (SN64)",  "kind": "api"},
    "antseed":  {"label": "AntSeed",        "kind": "scrape"},
    "surplus":  {"label": "Surplus",        "kind": "scrape"},
    "engy":     {"label": "Engy (SN53)",    "kind": "scrape"},
    "venice":   {"label": "Venice",         "kind": "api"},
    "gm":       {"label": "gm (SN28)",      "kind": "scrape"},
    "blockrun": {"label": "BlockRun",       "kind": "api"},
}
```

- [ ] **Step 2: Write the failing tests**

```python
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
```

- [ ] **Step 3: Run tests to verify they fail**

Run: `uv run pytest tests/test_scrape.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'scrape'`

- [ ] **Step 4: Write scrape.py**

```python
"""Fetch every source and bank the rows. Usage:

    python scrape.py            # all sources
    python scrape.py --only gm  # one source (second daily gm run)

Each source is isolated: a failure is logged and the rest still commit. Exit code is 1 if
any source failed, so the scheduled task shows red instead of silently writing gaps.
"""

import argparse
import sys
import traceback

import store
from sources import SOURCES


def select(sources, only: str | None):
    if not only:
        return list(sources)
    return [s for s in sources if s.__name__.rsplit(".", 1)[-1] == only]


def run(sources, conn) -> list[str]:
    failed = []
    for src in sources:
        name = src.__name__
        try:
            rows = src.fetch()
            store.upsert_daily(conn, src.PLAYER, rows)
            print(f"ok    {name:<28} {len(rows)} rows")
        except Exception:
            failed.append(name)
            print(f"FAIL  {name}", file=sys.stderr)
            traceback.print_exc()
    return failed


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--only", help="run a single source module, e.g. gm")
    args = ap.parse_args()
    conn = store.connect()
    failed = run(select(SOURCES, args.only), conn)
    if failed:
        print(f"{len(failed)} source(s) failed: {', '.join(failed)}", file=sys.stderr)
        sys.exit(1)


if __name__ == "__main__":
    main()
```

- [ ] **Step 5: Run tests to verify they pass**

Run: `uv run pytest tests/test_scrape.py -v`
Expected: 3 passed

- [ ] **Step 6: Run the full suite**

Run: `uv run pytest -q`
Expected: all tests pass (8 + 4 + 3 + 3 + 4 + 5 + 3 + 4 + 6 + 3 = 43 passed)

- [ ] **Step 7: Commit**

```bash
git add sources/__init__.py scrape.py tests/test_scrape.py
git commit -m "Add source registry and isolated scrape runner"
```

---

### Task 13: build.py — store → data.json

**Files:**
- Create: `onchain-inference-dashboard/build.py`
- Test: `onchain-inference-dashboard/tests/test_build.py`

Groups metrics into the five charts, sums token sub-metrics per (player, day), derives tokens-per-request where both exist, excludes the current UTC day, and emits per-player "data through" dates.

Output shape:

```json
{
  "generated_at": "2026-09-08T08:12:00+00:00",
  "players": {"chutes": {"label": "Chutes (SN64)", "kind": "api"}, ...},
  "charts": {
    "requests":           {"chutes": [["2025-01-30", 1234.0], ...], ...},
    "tokens":             {...},
    "spend":              {...},
    "capture":            {...},
    "tokens_per_request": {...}
  },
  "through": {"chutes": "2026-09-07", ...}
}
```

- [ ] **Step 1: Write the failing tests**

```python
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
    store.upsert_daily(conn, "venice", [("2026-09-07", "capture_burns", 9.0)], now=NOW)


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
    assert ch["capture"]["venice"] == [["2026-09-07", 9.0]]
    assert ch["tokens_per_request"]["chutes"] == [["2026-09-06", 10.0], ["2026-09-07", 10.0]]
    assert ch["tokens_per_request"]["antseed"] == [["2026-09-07", 3.0]]
    assert "dau" not in json.dumps(ch)


def test_build_excludes_today_and_reports_through(tmp_path):
    conn = store.connect(tmp_path / "t.db")
    _seed(conn)
    out = build.build(conn, now=NOW)
    assert all(d < "2026-09-08" for series in out["charts"]["requests"].values() for d, _ in series)
    assert out["through"] == {"chutes": "2026-09-07", "antseed": "2026-09-07", "venice": "2026-09-07"}


def test_build_absent_player_absent_from_chart(tmp_path):
    conn = store.connect(tmp_path / "t.db")
    _seed(conn)
    out = build.build(conn, now=NOW)
    assert "venice" not in out["charts"]["requests"]
    assert "venice" in out["players"]


def test_write_creates_file(tmp_path):
    conn = store.connect(tmp_path / "t.db")
    _seed(conn)
    target = tmp_path / "data.json"
    build.write(conn, target, now=NOW)
    assert json.loads(target.read_text())["generated_at"].startswith("2026-09-08")
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `uv run pytest tests/test_build.py -v`
Expected: FAIL with ModuleNotFoundError

- [ ] **Step 3: Write build.py**

```python
"""Flatten the store into dashboard/data.json. Usage: python build.py"""

import collections
import datetime as dt
import json
from pathlib import Path

import store
from sources import PLAYERS

OUT_PATH = Path(__file__).parent / "dashboard" / "data.json"

# chart -> metrics summed per (player, day)
CHARTS = {
    "requests": {"requests"},
    "tokens":   {"tokens", "tokens_in", "tokens_out", "tokens_cache"},
    "spend":    {"spend_usd", "spend_gmv"},
    "capture":  {"capture_fees", "capture_emissions", "capture_burns"},
}


def build(conn, now: dt.datetime | None = None) -> dict:
    now = now or dt.datetime.now(dt.timezone.utc)
    today = now.date().isoformat()
    # chart -> player -> day -> value
    acc = {c: collections.defaultdict(lambda: collections.defaultdict(float)) for c in CHARTS}
    through = {}
    for player, day, metric, value in store.all_daily(conn):
        if day >= today:
            continue
        through[player] = max(through.get(player, ""), day)
        for chart, metrics in CHARTS.items():
            if metric in metrics:
                acc[chart][player][day] += value

    charts = {}
    for chart, per_player in acc.items():
        charts[chart] = {p: [[d, v] for d, v in sorted(days.items())]
                         for p, days in per_player.items()}

    tpr = {}
    for player, days in acc["tokens"].items():
        reqs = acc["requests"].get(player, {})
        pts = [[d, days[d] / reqs[d]] for d in sorted(days) if reqs.get(d)]
        if pts:
            tpr[player] = pts
    charts["tokens_per_request"] = tpr

    return {
        "generated_at": now.isoformat(timespec="seconds"),
        "players": PLAYERS,
        "charts": charts,
        "through": through,
    }


def write(conn, path: Path = OUT_PATH, now: dt.datetime | None = None) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(build(conn, now)), encoding="utf-8")


if __name__ == "__main__":
    write(store.connect())
    print(f"wrote {OUT_PATH}")
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `uv run pytest tests/test_build.py -v`
Expected: 4 passed

- [ ] **Step 5: Commit**

```bash
git add build.py tests/test_build.py
git commit -m "Add build.py: store to chart-grouped data.json"
```

---

### Task 14: First real scrape

**Files:** none new; produces `data/inference.db` and `dashboard/data.json` (both gitignored)

This is the first contact with live sources. Every adapter was tested against a fixture; this verifies the live payloads still match.

- [ ] **Step 1: Run the scraper**

Run: `uv run python scrape.py`
Expected: seven `ok` lines and no `FAIL`. Chutes takes ~30–60s (20MB). If `engy_emissions` fails with `No TAOSTATS_API_KEY`, that is a config issue, not a parse failure — confirm `inference-farm/.env` exists; the other seven still commit.

- [ ] **Step 2: Verify idempotence (spec success criterion 1)**

Run:
```powershell
uv run python -c "import store; c=store.connect(); print(c.execute('select count(*) from daily').fetchone())"
uv run python scrape.py
uv run python -c "import store; c=store.connect(); print(c.execute('select count(*) from daily').fetchone())"
```
Expected: the two counts are identical.

- [ ] **Step 3: Inspect coverage per player**

Run:
```powershell
uv run python -c "import store; c=store.connect(); [print(r) for r in c.execute('select player, count(distinct day), min(day), max(day) from daily group by player')]"
```
Expected roughly: chutes ~587 days from 2025-01-30; antseed ~153 from 2026-04-09; venice ~306 from 2025-11-07; surplus 28; engy 31; blockrun 1; gm 0 (no bracketed day until the second scrape tomorrow).

- [ ] **Step 4: Build data.json**

Run: `uv run python build.py`
Expected: `wrote ...dashboard\data.json`; file is a few hundred KB.

No commit — both outputs are gitignored.

---

### Task 15: Dashboard

**Files:**
- Create: `onchain-inference-dashboard/dashboard/index.html`
- Create: `.claude/launch.json` entry (repo root)

Single self-contained page, inline SVG, no libraries. Same type family as `inference-capital-markets-map.html` (Anton / Archivo). Five stacked charts on one shared time axis; shared crosshair; legend toggles; range selector; header strip with latest value, 7d change, data-through date and an api/scrape badge per player; greyed legend entries where a player has no data on a chart.

- [ ] **Step 1: Write dashboard/index.html**

```html
<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>Onchain Inference Dashboard</title>
<link rel="preconnect" href="https://fonts.googleapis.com">
<link rel="preconnect" href="https://fonts.gstatic.com" crossorigin>
<link href="https://fonts.googleapis.com/css2?family=Anton&family=Archivo:wght@400;500;600;700&display=swap" rel="stylesheet">
<style>
  :root { --paper:#fff; --ink:#111; --gray:#6b6b6b; --line:#d9d9d9; --grid:#ececec; }
  * { margin:0; padding:0; box-sizing:border-box; }
  body { background:var(--paper); color:var(--ink); font-family:'Archivo',sans-serif; }
  .wrap { max-width:1480px; margin:0 auto; padding:0 28px 80px; }
  header { display:flex; align-items:flex-end; gap:24px; padding:34px 0 10px; flex-wrap:wrap; }
  h1 { font-family:'Anton',sans-serif; font-size:clamp(40px,5.5vw,76px); line-height:.92; text-transform:uppercase; font-weight:400; }
  .sub { font-size:11px; letter-spacing:.14em; text-transform:uppercase; color:var(--gray); margin-top:8px; }
  .spacer { flex:1; }
  .ranges { display:flex; gap:6px; padding-bottom:6px; }
  .tbtn { border:1.5px solid var(--ink); background:var(--paper); color:var(--ink); font:700 10px/1 'Archivo'; letter-spacing:.1em; text-transform:uppercase; padding:10px 14px; cursor:pointer; }
  .tbtn.on, .tbtn:hover { background:var(--ink); color:var(--paper); }

  .strip { display:grid; grid-template-columns:repeat(auto-fill,minmax(190px,1fr)); gap:10px; margin:18px 0 30px; }
  .tile { border:1.5px solid var(--ink); padding:12px 14px; cursor:pointer; user-select:none; }
  .tile.off { opacity:.35; }
  .tile .name { display:flex; align-items:center; gap:8px; font-weight:700; font-size:13px; }
  .tile .sw { width:12px; height:12px; border-radius:2px; }
  .tile .badge { margin-left:auto; font-size:9px; letter-spacing:.1em; text-transform:uppercase; border:1px solid var(--gray); color:var(--gray); padding:2px 5px; }
  .tile .badge.scrape { border-style:dashed; }
  .tile .big { font-family:'Anton'; font-size:26px; margin-top:8px; }
  .tile .meta { font-size:10px; color:var(--gray); margin-top:4px; letter-spacing:.06em; text-transform:uppercase; }
  .tile .meta .up { color:#087f3f; } .tile .meta .dn { color:#c1121f; }

  .chart { margin-bottom:28px; }
  .chart h2 { font-family:'Anton'; font-size:20px; text-transform:uppercase; letter-spacing:.02em; }
  .chart .note { font-size:11px; color:var(--gray); margin:2px 0 8px; }
  .chart .absent { font-size:10px; color:var(--gray); letter-spacing:.08em; text-transform:uppercase; margin-top:4px; }
  svg { width:100%; height:240px; display:block; overflow:visible; }
  .gridline { stroke:var(--grid); stroke-width:1; }
  .axis { font-size:10px; fill:var(--gray); font-family:'Archivo'; }
  .series { fill:none; stroke-width:1.8; stroke-linejoin:round; }
  .series.snapshot { stroke-dasharray:3 3; }
  .cross { stroke:var(--ink); stroke-width:1; stroke-dasharray:2 3; pointer-events:none; }
  .tip { position:fixed; pointer-events:none; background:var(--ink); color:var(--paper); font-size:11px; padding:8px 10px; line-height:1.5; display:none; z-index:9; white-space:nowrap; }
  .tip b { font-family:'Anton'; font-weight:400; letter-spacing:.04em; }
</style>
</head>
<body>
<div class="wrap">
  <header>
    <div>
      <h1>Onchain Inference</h1>
      <div class="sub" id="gen">loading…</div>
    </div>
    <div class="spacer"></div>
    <div class="ranges" id="ranges">
      <button class="tbtn" data-days="30">30d</button>
      <button class="tbtn on" data-days="90">90d</button>
      <button class="tbtn" data-days="0">All</button>
    </div>
  </header>
  <div class="strip" id="strip"></div>
  <div id="charts"></div>
</div>
<div class="tip" id="tip"></div>

<script>
const COLORS = { chutes:'#111111', antseed:'#c1121f', surplus:'#1d4ed8', engy:'#e08a00',
                 venice:'#7c3aed', gm:'#059669', blockrun:'#db2777' };
const SNAPSHOT = new Set(['blockrun']);     // dashed: rolling-24h figures, not calendar days
const CHARTS = [
  { key:'requests', title:'Requests / day', log:true,
    note:'Chutes, AntSeed, Surplus, Engy: calendar-day totals. gm: epoch rollup. BlockRun: rolling 24h snapshot (dashed).' },
  { key:'tokens', title:'Tokens / day', log:true,
    note:'Input + output (+ cache where reported). Surplus cache tokens are prompt tokens served from cache.' },
  { key:'spend', title:'Buyer spend / day (USD)', log:true,
    note:'What demand paid. Chutes: buyer USD. AntSeed: settlement GMV. gm: traffic value served.' },
  { key:'capture', title:'Protocol capture / day (USD)', log:true,
    note:'What the network kept. AntSeed: fees. Venice: value burned per purchase/sub. Engy: SN53 miner emissions — issuance, not buyer money.' },
  { key:'tokens_per_request', title:'Tokens per request', log:false,
    note:'Workload shape. Separates chat routers from long-context / agent traffic.' },
];
const M = { t:8, r:16, b:24, l:64 };

let DATA, days = 90, hidden = new Set();

const fmt = (v) => {
  if (v == null) return '—';
  const a = Math.abs(v);
  if (a >= 1e12) return (v/1e12).toFixed(2)+'T';
  if (a >= 1e9)  return (v/1e9).toFixed(2)+'B';
  if (a >= 1e6)  return (v/1e6).toFixed(2)+'M';
  if (a >= 1e3)  return (v/1e3).toFixed(1)+'K';
  return v >= 100 ? v.toFixed(0) : v.toFixed(2);
};
const usd = (v) => v == null ? '—' : '$' + fmt(v);

function visible(series) {
  if (!days) return series;
  const cut = new Date(); cut.setUTCDate(cut.getUTCDate() - days);
  const c = cut.toISOString().slice(0,10);
  return series.filter(([d]) => d >= c);
}

function renderStrip() {
  const el = document.getElementById('strip'); el.innerHTML = '';
  for (const [p, info] of Object.entries(DATA.players)) {
    const req = DATA.charts.requests[p] || [];
    const cap = DATA.charts.capture[p] || [];
    const spend = DATA.charts.spend[p] || [];
    const main = req.length ? req : (spend.length ? spend : cap);
    const isMoney = !req.length;
    const last = main[main.length-1], prev = main[main.length-8];
    const chg = last && prev && prev[1] ? (last[1]/prev[1]-1)*100 : null;
    const tile = document.createElement('div');
    tile.className = 'tile' + (hidden.has(p) ? ' off' : '');
    tile.innerHTML = `
      <div class="name"><span class="sw" style="background:${COLORS[p]}"></span>${info.label}
        <span class="badge ${info.kind}">${info.kind}</span></div>
      <div class="big">${last ? (isMoney ? usd(last[1]) : fmt(last[1])) : '—'}</div>
      <div class="meta">${req.length ? 'req/day' : (spend.length ? 'spend/day' : 'capture/day')}
        ${chg == null ? '' : `· <span class="${chg>=0?'up':'dn'}">${chg>=0?'+':''}${chg.toFixed(0)}% 7d</span>`}</div>
      <div class="meta">through ${DATA.through[p] || '—'}</div>`;
    tile.onclick = () => { hidden.has(p) ? hidden.delete(p) : hidden.add(p); render(); };
    el.appendChild(tile);
  }
}

function renderChart(cfg) {
  const box = document.createElement('div'); box.className = 'chart';
  const data = DATA.charts[cfg.key] || {};
  const present = Object.keys(DATA.players).filter(p => (data[p]||[]).length);
  const absent = Object.keys(DATA.players).filter(p => !(data[p]||[]).length);
  box.innerHTML = `<h2>${cfg.title}</h2><div class="note">${cfg.note}</div>`;

  const W = Math.min(1424, box.clientWidth || 1200), H = 240;
  const iw = W - M.l - M.r, ih = H - M.t - M.b;
  const shown = present.filter(p => !hidden.has(p)).map(p => [p, visible(data[p])]).filter(([,s]) => s.length);
  if (!shown.length) { box.innerHTML += '<div class="absent">no data in range</div>'; return box; }

  const allDays = [...new Set(shown.flatMap(([,s]) => s.map(([d]) => d)))].sort();
  const x = (d) => M.l + (allDays.indexOf(d) / Math.max(1, allDays.length-1)) * iw;
  let vals = shown.flatMap(([,s]) => s.map(([,v]) => v)).filter(v => cfg.log ? v > 0 : true);
  let lo = Math.min(...vals), hi = Math.max(...vals);
  if (cfg.log) { lo = Math.pow(10, Math.floor(Math.log10(lo))); hi = Math.pow(10, Math.ceil(Math.log10(hi))); }
  else { lo = 0; hi = hi * 1.05 || 1; }
  const y = (v) => cfg.log
    ? M.t + ih - ((Math.log10(v) - Math.log10(lo)) / (Math.log10(hi) - Math.log10(lo))) * ih
    : M.t + ih - ((v - lo) / (hi - lo)) * ih;

  let ticks = [];
  if (cfg.log) for (let e = Math.log10(lo); e <= Math.log10(hi); e++) ticks.push(Math.pow(10, e));
  else for (let i = 0; i <= 4; i++) ticks.push(lo + (hi - lo) * i / 4);

  let svg = `<svg viewBox="0 0 ${W} ${H}" preserveAspectRatio="none">`;
  for (const t of ticks) svg += `<line class="gridline" x1="${M.l}" x2="${W-M.r}" y1="${y(t)}" y2="${y(t)}"/>
    <text class="axis" x="${M.l-6}" y="${y(t)+3}" text-anchor="end">${cfg.key==='spend'||cfg.key==='capture' ? usd(t) : fmt(t)}</text>`;
  const step = Math.max(1, Math.floor(allDays.length / 8));
  allDays.forEach((d, i) => { if (i % step === 0 || i === allDays.length-1)
    svg += `<text class="axis" x="${x(d)}" y="${H-6}" text-anchor="middle">${d.slice(5)}</text>`; });
  for (const [p, s] of shown) {
    const pts = s.filter(([,v]) => !cfg.log || v > 0).map(([d,v]) => `${x(d).toFixed(1)},${y(v).toFixed(1)}`);
    svg += `<polyline class="series${SNAPSHOT.has(p)?' snapshot':''}" stroke="${COLORS[p]}" points="${pts.join(' ')}"/>`;
  }
  svg += `<line class="cross" id="cross-${cfg.key}" y1="${M.t}" y2="${M.t+ih}" x1="-10" x2="-10"/></svg>`;
  box.innerHTML += svg;
  if (absent.length) box.innerHTML += `<div class="absent">not reported: ${absent.map(p => DATA.players[p].label).join(' · ')}</div>`;

  const el = box.querySelector('svg');
  el.onmousemove = (ev) => {
    const r = el.getBoundingClientRect();
    const px = (ev.clientX - r.left) / r.width * W;
    const i = Math.round((px - M.l) / iw * (allDays.length-1));
    const d = allDays[Math.max(0, Math.min(allDays.length-1, i))];
    document.querySelectorAll('.cross').forEach(c => { c.setAttribute('x1', x(d)); c.setAttribute('x2', x(d)); });
    const rows = shown.map(([p, s]) => { const hit = s.find(([dd]) => dd === d);
      return hit ? `<span style="color:${COLORS[p]}">■</span> ${DATA.players[p].label}: ${cfg.key==='spend'||cfg.key==='capture' ? usd(hit[1]) : fmt(hit[1])}` : null; }).filter(Boolean);
    const tip = document.getElementById('tip');
    tip.innerHTML = `<b>${d}</b><br>${rows.join('<br>')}`;
    tip.style.display = 'block'; tip.style.left = (ev.clientX + 14) + 'px'; tip.style.top = (ev.clientY + 14) + 'px';
  };
  el.onmouseleave = () => { document.getElementById('tip').style.display = 'none';
    document.querySelectorAll('.cross').forEach(c => { c.setAttribute('x1', -10); c.setAttribute('x2', -10); }); };
  return box;
}

function render() {
  renderStrip();
  const root = document.getElementById('charts'); root.innerHTML = '';
  for (const cfg of CHARTS) root.appendChild(renderChart(cfg));
}

document.getElementById('ranges').onclick = (e) => {
  const b = e.target.closest('button'); if (!b) return;
  days = +b.dataset.days;
  document.querySelectorAll('#ranges .tbtn').forEach(x => x.classList.toggle('on', x === b));
  render();
};

fetch('data.json').then(r => r.json()).then(d => {
  DATA = d;
  document.getElementById('gen').textContent = `generated ${d.generated_at.replace('T',' ').slice(0,16)} UTC · ${Object.keys(d.players).length} players · click a tile to toggle`;
  render();
}).catch(err => { document.getElementById('gen').textContent = 'data.json missing — run scrape.py then build.py'; console.error(err); });
</script>
</body>
</html>
```

- [ ] **Step 2: Add the launch.json entry**

Read `.claude/launch.json` at the repo root. Append this configuration to its `configurations` array (keep existing entries):

```json
{
  "name": "inference-dashboard",
  "runtimeExecutable": "python",
  "runtimeArgs": ["-m", "http.server", "8792", "--directory", "onchain-inference-dashboard/dashboard"],
  "port": 8792
}
```

- [ ] **Step 3: Verify in the browser**

Start the `inference-dashboard` preview, open `http://localhost:8792/`. Check:
- header reads `generated 2026-09-08 …` (not the "data.json missing" fallback)
- seven tiles, each with a through-date and an `api`/`scrape` badge
- five charts; requests chart shows Chutes, AntSeed, Surplus, Engy lines (gm/BlockRun may be a single point or absent on day 1)
- capture chart shows AntSeed, Venice (and Engy if the taostats key was present); "not reported" line lists Surplus, Chutes, gm, BlockRun
- hovering any chart moves the crosshair on all five and shows the tooltip
- clicking a tile removes that player from every chart
- browser console has no errors

Take a screenshot for the record.

- [ ] **Step 4: Commit**

```bash
git add onchain-inference-dashboard/dashboard/index.html .claude/launch.json
git commit -m "Add single-file SVG dashboard and launch.json entry"
```

---

### Task 16: Scheduling and README

**Files:**
- Create: `onchain-inference-dashboard/run_daily.ps1`
- Create: `onchain-inference-dashboard/register_tasks.ps1`
- Create: `onchain-inference-dashboard/README.md`

Two Task Scheduler jobs, local time (Asia/Bangkok = UTC+7): full run at 15:10 (08:10 UTC, after Surplus generates ~08:01 UTC), gm-only at 03:10 (20:10 UTC). **Registering scheduled tasks changes the machine; run `register_tasks.ps1` only after the user confirms.**

- [ ] **Step 1: Write run_daily.ps1**

```powershell
# Full daily run: scrape all sources, rebuild data.json. Exit code propagates to Task Scheduler.
param([string]$Only)
Set-Location $PSScriptRoot
$log = Join-Path $PSScriptRoot "scrape.log"
"=== $(Get-Date -Format o) only=$Only ===" | Out-File -Append -Encoding utf8 $log
if ($Only) { uv run python scrape.py --only $Only 2>&1 | Out-File -Append -Encoding utf8 $log }
else       { uv run python scrape.py                2>&1 | Out-File -Append -Encoding utf8 $log }
$rc = $LASTEXITCODE
uv run python build.py 2>&1 | Out-File -Append -Encoding utf8 $log
exit $rc
```

- [ ] **Step 2: Write register_tasks.ps1**

```powershell
# Registers two Task Scheduler jobs. Times are LOCAL (Asia/Bangkok, UTC+7).
$here = $PSScriptRoot
$ps = "powershell.exe"
$full = "-NoProfile -ExecutionPolicy Bypass -File `"$here\run_daily.ps1`""
$gm   = "-NoProfile -ExecutionPolicy Bypass -File `"$here\run_daily.ps1`" -Only gm"

schtasks /Create /F /SC DAILY /ST 15:10 /TN "OnchainInferenceDaily" /TR "$ps $full"
schtasks /Create /F /SC DAILY /ST 03:10 /TN "OnchainInferenceGmEvening" /TR "$ps $gm"
schtasks /Query /TN "OnchainInferenceDaily"
schtasks /Query /TN "OnchainInferenceGmEvening"
```

- [ ] **Step 3: Write README.md**

```markdown
# Onchain Inference Dashboard

Daily scraper + single-file dashboard tracking 7 onchain inference players.
Design: `../docs/superpowers/specs/2026-09-08-onchain-inference-dashboard-design.md`

## Run

    uv run python scrape.py        # all sources -> data/inference.db
    uv run python scrape.py --only gm
    uv run python build.py         # -> dashboard/data.json
    uv run pytest                  # fixtures under tests/fixtures

Serve `dashboard/` with any static server (launch.json entry `inference-dashboard`, port 8792).

## Schedule

`register_tasks.ps1` creates two Task Scheduler jobs (local time, UTC+7):
15:10 full run, 03:10 gm-only. Logs append to `scrape.log`. A nonzero exit means at
least one source failed — check the log before trusting that day.

## Sources

| player | kind | metrics |
|---|---|---|
| chutes | api | requests, tokens_in/out, spend_usd |
| antseed | scrape | requests, tokens, spend_gmv, capture_fees, dau, settles |
| surplus | scrape | requests, tokens_in/out/cache |
| engy | scrape + api | requests, tokens; capture_emissions (taostats key from `../inference-farm/.env`) |
| venice | api | capture_burns, credits_count, subs_count |
| gm | scrape | requests, spend_usd (epoch rollup; needs two scrapes to emit a day) |
| blockrun | api | requests, settlements (rolling 24h, previous UTC day) |

Scraped sources parse undocumented Next.js payloads. When one breaks, its adapter raises,
the run exits 1, and the other sources still commit. Fix the regex, refresh the fixture,
update the test expectations.
```

- [ ] **Step 4: Test run_daily.ps1 manually**

Run: `powershell -NoProfile -ExecutionPolicy Bypass -File onchain-inference-dashboard/run_daily.ps1 -Only blockrun`
Expected: exit code 0; `scrape.log` gains a header line and `ok    sources.blockrun 3 rows`; `dashboard/data.json` timestamp updates.

- [ ] **Step 5: Ask the user before registering the scheduled tasks**

Do not run `register_tasks.ps1` unprompted. Show the two task names and times and wait for confirmation. After confirmation, run it and verify both `schtasks /Query` lines print `Ready`.

- [ ] **Step 6: Commit**

```bash
git add onchain-inference-dashboard/run_daily.ps1 onchain-inference-dashboard/register_tasks.ps1 onchain-inference-dashboard/README.md
git commit -m "Add daily runner, task registration script, and README"
```

---

## Self-review against the spec

**Spec coverage:**
- Roster of 7 with per-player metrics → Tasks 3–5, 7–11 ✔
- Long-format `daily` table, `gm_epochs` table → Task 2 ✔
- Write rule (insert-if-missing, trailing-3-day update, freeze older) → Task 2, tested explicitly ✔
- Chutes: two endpoints, no ETag short-circuit → Task 3 ✔
- Venice: `*UsdThen`, burns as capture, counts stored, no `discUsdThen`, browser UA → Tasks 1, 4 ✔
- Surplus regex → Task 7 ✔
- Engy explicit `buckets` axis, length-mismatch guard → Task 8 ✔
- Engy emissions via taostats, separate source → Task 9 ✔
- AntSeed full history → Task 10 ✔
- gm epoch staging, contiguity rule, first-day withheld, twice-daily → Tasks 11, 16 ✔
- BlockRun preceding-day assignment → Task 5 ✔
- Failure isolation, nonzero exit, partial commit → Task 12 ✔
- build.py: chart grouping, tokens/request derived, today excluded, through-dates → Task 13 ✔
- Dashboard: 5 charts, log axes, shared crosshair, legend toggle, range selector, header strip with through-date and kind badge, absent players listed not zeroed, snapshot series dashed → Task 15 ✔
- Scheduling 08:10 / 20:10 UTC as 15:10 / 03:10 local → Task 16 ✔
- Success criteria 1–7 → criterion 1 Task 14 step 2; 2 Tasks 7–11; 3 Task 12; 4 Task 8 (`test_length_mismatch_raises`); 5 Task 11; 6 Task 13; 7 Task 15 step 3 ✔

**Placeholder scan:** no TBD/TODO; every code step carries full code; every run step carries the command and expected result.

**Type consistency:** `store.upsert_daily(conn, player, rows, now=)`, `store.all_daily`, `store.upsert_gm_epochs`, `store.all_gm_epochs` used identically in Tasks 2, 11, 12, 13. `scrape.run(sources, conn) -> list[str]` and `scrape.select(sources, only)` match between Task 12 test and implementation. `build.build(conn, now=)` / `build.write(conn, path, now=)` match. Every adapter exposes `PLAYER`, `KIND`, `fetch()`; `sources.PLAYERS` keys match `COLORS` keys in the dashboard.
