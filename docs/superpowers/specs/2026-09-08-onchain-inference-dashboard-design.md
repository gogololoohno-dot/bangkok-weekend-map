# Onchain Inference Dashboard — Design

**Date:** 2026-09-08
**Status:** Approved, pending implementation plan

## Purpose

Track the operating performance of onchain inference players side by side on shared
charts: requests/day, tokens/day, and money/day. Successor to
`inference-capital-markets-map.html`, which maps who exists; this measures how they
are actually doing.

## Roster and coverage

Seven players. No player covers every metric, and the gaps are load-bearing
information — they are rendered, not hidden.

| Player | req/day | tok/day | buyer spend | protocol capture | History at build time | Access |
|---|---|---|---|---|---|---|
| Chutes (SN64) | yes | yes | yes | — | 587 days (from 2025-01-30) | public REST |
| AntSeed | yes | yes | yes (GMV) | yes (fees) | 153 days (from 2026-04-09) | HTML scrape |
| Surplus | yes | yes | — | — | 28 days rolling | HTML scrape |
| Engy (SN53) | yes | yes | — | yes (emissions) | 31 days rolling | HTML scrape + taostats |
| Venice | — | — | yes (implied) | — | 305 days (from 2025-11-07) | public REST |
| gm (SN28) | yes | — | yes | — | none — forward only | HTML scrape |
| BlockRun | yes | — | — | — | none — forward only | public REST |

Rejected after checking: Targon (hardware sales page, no usage stats), Nineteen (403),
inference.net, Dolphin, UsePod, OpenVecta, DGrid, SolRouter, Actual, Instant, Verathos,
OpenGradient, Warden, Kite, OpenServ, Hyre, Gitlawb, Darkbloom. None publish usable
daily operating metrics.

## Architecture

```
onchain-inference-dashboard/
  scrape.py           # entrypoint — fetch all sources, upsert
  sources/
    __init__.py       # SOURCES registry
    chutes.py  venice.py  blockrun.py      # kind="api"
    surplus.py engy.py antseed.py gm.py    # kind="scrape"
  store.py            # SQLite open / upsert / query
  build.py            # store -> dashboard/data.json
  data/inference.db
  dashboard/
    index.html        # self-contained, reads data.json
    data.json
```

Adding a player is one file in `sources/` plus one registry line. Nothing else changes.

### Adapter contract

Every adapter — API or scrape, daily or epoch-grain — exposes one function:

```python
def fetch() -> list[tuple[str, str, float]]:   # (day 'YYYY-MM-DD' UTC, metric, value)
```

Per-source shape differences (gm's epoch rollup, BlockRun's 24h snapshot, Engy's
date-less arrays) are absorbed inside the adapter. `store.py` and `build.py` never learn
that sources differ.

The registry records `kind: "api" | "scrape"` and the metrics each source declares. `kind`
drives a badge in the UI: a flat line from an API source and a flat line from a scraped
source warrant different suspicion.

### Store

```sql
CREATE TABLE daily (
  player TEXT NOT NULL,
  day    TEXT NOT NULL,          -- 'YYYY-MM-DD' UTC
  metric TEXT NOT NULL,
  value  REAL NOT NULL,
  scraped_at TEXT NOT NULL,
  PRIMARY KEY (player, day, metric)
);
```

Long format, not wide. The seven players expose genuinely different metric sets; a wide
table would be mostly NULL and would need a migration every time a player adds a field or
a player is added.

gm additionally gets an epoch-grain staging table, since its rollup needs dedupe across
scrapes:

```sql
CREATE TABLE gm_epochs (
  epoch INTEGER PRIMARY KEY,
  finalized_at TEXT NOT NULL,    -- ISO UTC
  requests INTEGER NOT NULL,
  value_usd REAL NOT NULL
);
```

**Write rule: upsert the trailing 3 days; never modify anything older.**

The current day is always partial — Surplus explicitly draws a projected cap on it — so it
must stay revisable. But days that have aged out of a source's rolling window can never be
re-derived. Freezing them means a source outage, a format change, or a partial fetch cannot
retroactively destroy history that has already been banked. This asymmetry is the single
most important correctness property in the system.

## Sources

### Chutes — `kind="api"`

- `GET https://api.chutes.ai/invocations/stats/llm`
  Array of `{chute_id, name, date, total_requests, total_input_tokens, total_output_tokens,
  average_tps, average_ttft}`. ~90.9K rows / 587 days / ~20MB.
  Sum by `date` -> `requests`, `tokens_in`, `tokens_out`.
- `GET https://api.chutes.ai/invocations/usage`
  Array of `{chute_id, date, usd_amount, invocation_count}`. ~836 rows / 12 days.
  Sum by `date` -> `spend_usd`.

`/daily_revenue_summary` returns 401 and is not used.

The 20MB daily fetch is the largest cost in the pipeline. Send `If-None-Match` and skip the
parse on 304.

### Venice — `kind="api"`

- `GET https://venicestats.com/api/burns-timeline?granularity=daily&range=all`
  `{buckets: [{t (epoch ms), discUsdThen, discUsdNow, proSubUsdThen, creditsUsdThen,
  creditsCount, ...}]}`, daily from 2025-11-07 (305 days as of 2026-09-08).

Mapping:
- `spend_credits` <- `creditsUsdThen` — implied API credit purchases. This is the inference
  spend series and the one that appears on the buyer-spend chart.
- `spend_subs` <- `proSubUsdThen` — consumer subscriptions. Stored, off-chart by default;
  it is not API inference demand.
- `discUsdThen` (discretionary treasury buyback) is **not** revenue and is not ingested.

**Use the `*UsdThen` fields, never `*UsdNow`.** `Now` revalues past burns at today's VVV
price, so every historical point would silently move each time the token repriced. That
would make the chart lie about the past.

### Surplus — `kind="scrape"`

- `GET https://www.surplusintelligence.ai/analytics`
- Parse the embedded RSC payload for
  `{"day":"YYYY-MM-DD","requests":N,"inputTokens":N,"outputTokens":N,"cacheTokens":N, ...}`
- -> `requests`, `tokens_in`, `tokens_out`, `tokens_cache`. 28 days rolling.

### Engy — `kind="scrape"`

- `GET https://provider.engy.ai/requests` -> per-model `{"model": str, "counts": [int x31]}`
- `GET https://provider.engy.ai/requests?m=tokens` -> same shape, token counts
- Sum across models per index -> `requests`, `tokens`.

**The `counts` arrays carry no dates.** Position must be mapped to a date:
`day[i] = today_utc - (30 - i)`. This is the most fragile parse in the system — if the window
length ever changes from 31 the whole series shifts silently, corrupting every day it writes.
Guard: assert `len(counts) == 31` for every model and raise otherwise. Where the rendered
axis labels are extractable, cross-check the first and last against the derived dates.

`capture_emissions`: SN53 alpha emissions valued in USD, reusing the math already in
`inference-farm/scripts/poll_sn53.py` (`miner_pool_usd_day`). Requires the taostats key that
project already uses.

### AntSeed — `kind="scrape"`

- `GET https://antseedstats.com/`
- Parse `{"day":<epoch ms>,"dau":N,"freeDau":N,"newUsers":N,"newFree":N,"volume":F,
  "fees":F,"settles":N,"requests":N,"tokens":N}` — 153 days present.
- -> `requests`, `tokens`, `spend_gmv` (volume), `capture_fees` (fees), `dau`, `settles`.

### gm — `kind="scrape"`

- `GET https://saygm.com/miners`
- The "Finalized epochs" table is server-rendered HTML with columns
  Epoch / Finalized / Miners / Gateways / Requests / Value.
- **Only 20 epochs are exposed** — at ~72 min each that is almost exactly 24 hours, with no
  back history and no margin.

Rollup: upsert rows into `gm_epochs` keyed on epoch number (dedupes across scrapes), then
bucket by the UTC day of `finalized_at` -> `requests`, `spend_usd`. Emit only days whose
epochs are fully covered; drop the current partial day, since a half-summed day is
indistinguishable from a collapse in traffic.

**Scrape gm twice daily.** A single daily scrape has exactly zero margin — one late or failed
run drops epochs permanently, and a gap in `gm_epochs` silently understates a day rather than
erroring.

### BlockRun — `kind="api"`

- `GET https://blockrun.ai/api/v1/health/overview` -> `totalCalls24h`
- `GET https://blockrun.ai/api/v1/health/chain` -> `totalSettlements24h`,
  `failedSettlements24h`, `successRate24h`

These are **rolling 24h snapshots, not calendar-day totals.** Written to the day of the scrape
and never revised. A missed day is permanently lost — it cannot be interpolated, and must not
be. Series carries a distinct marker so it is never read as a true daily total.

## Failure behaviour

Four of seven adapters parse undocumented payloads that will change without notice. The
governing rule: **a silently zeroed day is far worse than a visible gap**, because it corrupts
history that cannot be rebuilt.

- An adapter whose pattern matches zero rows raises. It does not write an empty day.
- An adapter that returns fewer rows than the source's known window raises.
- `scrape.py` isolates each source: one failure does not block the other six.
- `scrape.py` exits nonzero if any source failed, so the scheduled task surfaces it.
- Partial success still commits the sources that succeeded.

## Dashboard

Single self-contained HTML reading `data.json`. Inline SVG, no chart library, consistent with
`inference-capital-markets-map.html`. Served locally via a `launch.json` entry, matching the
existing `oil-dashboard` pattern.

Five charts, one shared UTC x-axis, one shared hover crosshair. Player = colour, consistent
across every chart; legend doubles as show/hide.

1. **Requests/day** — log y — Chutes, AntSeed, Surplus, Engy, gm, BlockRun
2. **Tokens/day** — log y — Chutes, AntSeed, Surplus, Engy
3. **Buyer spend/day** — log y — Chutes USD, AntSeed GMV, Venice implied credits, gm value
4. **Protocol capture/day** — log y — AntSeed fees, Engy emissions
5. **Tokens per request** — linear y — Chutes, AntSeed, Surplus, Engy (the four with both
   inputs); derived at build time, not stored

Log scale on 1–4 because the players span ~three orders of magnitude (Chutes ~3.6M req/day
against gm ~10K/epoch); linear would flatten everything but the leader into the axis.

Charts 3 and 4 are split deliberately. "Revenue" means five different things across this
roster — actual buyer USD (Chutes), marketplace settlement GMV (AntSeed), implied purchases
back-derived from onchain burns (Venice), traffic value served (gm), and token emissions that
are not buyer money at all (Engy). One axis labelled "revenue/day" would be the most misleading
chart on the page. Buyer spend vs protocol capture is the honest cut, and the gap between the
two is itself the interesting quantity.

Supporting UI:
- Range selector: 30d / 90d / All
- Header strip: per player, latest value, 7-day change, and **data-through timestamp**, so a
  dead scraper reads as dead rather than as a plateau
- Absent players render as greyed legend entries with the reason on hover — never as zero,
  never silently dropped
- Scraped series badged distinctly from API series

Scheduled daily ~08:10 UTC (after Surplus generates ~08:01 UTC and Engy's hourly rollup lands),
plus a second gm-only run ~20:10 UTC. Windows Task Scheduler, matching the existing
`BangkokWeekendUpdate` pattern.

## Success criteria

1. `python scrape.py` twice in succession -> identical row count, no duplicates
2. Saved HTML/JSON fixture per adapter -> parses to known row count and known values.
   This is the tripwire for format drift and the main regression guard.
3. Corrupt a fixture -> that adapter raises, process exits nonzero, DB unchanged, **other six
   sources still commit**
4. Engy fixture with 30 instead of 31 buckets -> raises rather than writing shifted dates
5. gm fixture scraped twice with overlapping epochs -> no double-counting; partial current day
   excluded
6. `build.py` -> every series date-sorted; no gaps within a player's covered range
7. Dashboard opens -> all five charts render; each player present only where it has data;
   Surplus greyed on charts 3 and 4

## Known limitations

- Surplus and Engy start at ~30 days and deepen only from first run. Chutes, Venice and AntSeed
  carry real back history, so the "All" view is uneven for roughly two months.
- gm and BlockRun start empty and are snapshot-derived; BlockRun's series is a rolling 24h
  figure, not a calendar day.
- Venice appears only on buyer spend. It publishes no usage data.
- Engy's emissions series measures token issuance, not customer payment. It sits on the
  capture chart for that reason and is not comparable to AntSeed fees without that caveat.
