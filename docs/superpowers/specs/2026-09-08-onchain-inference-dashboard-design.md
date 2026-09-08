# Onchain Inference Dashboard — Design

**Date:** 2026-09-08
**Status:** Approved, pending implementation plan

## Purpose

Track the operating performance of onchain inference players side by side on shared
charts: requests/day, tokens/day, and money/day. Successor to
`inference-capital-markets-map.html`, which maps who exists; this measures how they
are actually doing.

## Roster and coverage

Four players. No player covers every metric, and the gaps are load-bearing
information — they are rendered, not hidden.

| Player | req/day | tok/day | buyer spend | protocol capture | History at build time | Access |
|---|---|---|---|---|---|---|
| Chutes (SN64) | yes | yes | yes | — | 587 days (from 2025-01-30) | public REST |
| AntSeed | yes | yes | yes (GMV) | yes (fees) | 153 days (from 2026-04-09) | HTML scrape |
| Surplus | yes | yes | — | — | 28 days rolling | HTML scrape |
| Engy (SN53) | yes | yes | — | yes (emissions) | 31 days rolling | HTML scrape + taostats |

Removed after the first build (2026-09-08):
- **Venice.** venicestats.com is a third-party token tracker, not a Venice dashboard — Venice
  itself discloses no usage or revenue. The only onchain series is the fixed burn per
  purchase (~$5), which measures neither demand nor capture comparably.
- **BlockRun.** Exposes a single rolling-24h number with no history; at ~900 calls/day it
  would take months of snapshots to show anything, and even then not calendar days.
- **gm (SN28).** Exposes only the last 20 epochs (~24h) with no history, so it had nothing to
  show on day one and would have needed twice-daily scraping just to accumulate calendar
  days. Not worth a second scheduled job for a ~10K req/epoch player.

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
    chutes.py  engy_emissions.py           # kind="api"
    surplus.py engy.py antseed.py          # kind="scrape"
  store.py            # SQLite open / upsert / query
  build.py            # store -> dashboard/data.json
  data/inference.db
  dashboard/
    index.html        # self-contained, reads data.json
    data.json
```

Adding a player is one file in `sources/` plus one registry line. Nothing else changes.

### Adapter contract

Every adapter — API or scrape — exposes one function:

```python
def fetch() -> list[tuple[str, str, float]]:   # (day 'YYYY-MM-DD' UTC, metric, value)
```

Per-source shape differences (Engy's per-model count arrays, the emissions snapshot) are
absorbed inside the adapter. `store.py` and `build.py` never learn
that sources differ.

Every adapter sends a browser-style `User-Agent`; several sources sit behind Cloudflare
and return 403 to Python's default.

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

Long format, not wide. The four players expose genuinely different metric sets; a wide
table would be mostly NULL and would need a migration every time a player adds a field or
a player is added.

**Write rule: insert any `(player, day, metric)` that is missing; update an existing row
only if `day` is within the trailing 3 days; never modify anything older.**

Insert-if-missing is what backfills: the first run banks Chutes' 587 days, and a source that
was unreachable for five days gets those days filled from its rolling window on the next
successful run. The 3-day update window is what protects the past.

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

The 20MB daily fetch is the largest cost in the pipeline. The API sends no `ETag` or
`Last-Modified`, so it cannot be short-circuited; it is simply fetched once a day.

### Surplus — `kind="scrape"`

- `GET https://www.surplusintelligence.ai/analytics`
- Parse the embedded RSC payload for
  `{"day":"YYYY-MM-DD","requests":N,"inputTokens":N,"outputTokens":N,"cacheTokens":N, ...}`
- -> `requests`, `tokens_in`, `tokens_out`, `tokens_cache`. 28 days rolling.

### Engy — `kind="scrape"`

- `GET https://provider.engy.ai/requests` -> embedded RSC payload containing
  `"buckets":[<epoch seconds> x31], "series":[{"model": str, "counts": [int x31]}, ...]`
- `GET https://provider.engy.ai/requests?m=tokens` -> same shape, token counts
- `buckets[i]` is the UTC midnight of bucket `i`; sum `counts[i]` across models ->
  `requests`, `tokens` for that day.

The date axis is explicit, so no positional date derivation is needed. Guard: raise if
`len(counts) != len(buckets)` for any model, or if `buckets` is empty — a length mismatch
would otherwise silently misalign every value it writes.

`capture_emissions`: SN53 alpha emissions valued in USD, reusing the math already in
`inference-farm/scripts/poll_sn53.py` (`miner_pool_usd_day`). Requires the taostats key that
project already uses. It is a daily-rate **snapshot**, not a settlement figure: assigned to
the UTC day preceding the scrape and never revised; a missed day is a permanent gap. It is a
separate source module so a missing key cannot block Engy's requests/tokens.

`build.py` excludes the current UTC day for every player, since every daily source reports
it partially. Assigning the snapshot to the preceding day keeps it visible under that rule.

### AntSeed — `kind="scrape"`

- `GET https://antseedstats.com/`
- Parse `{"day":<epoch ms>,"dau":N,"freeDau":N,"newUsers":N,"newFree":N,"volume":F,
  "fees":F,"settles":N,"requests":N,"tokens":N}` — 153 days present.
- -> `requests`, `tokens`, `spend_gmv` (volume), `capture_fees` (fees), `dau`, `settles`.

## Failure behaviour

Three of five adapters parse undocumented payloads that will change without notice. The
governing rule: **a silently zeroed day is far worse than a visible gap**, because it corrupts
history that cannot be rebuilt.

- An adapter whose pattern matches zero rows raises. It does not write an empty day.
- An adapter that returns fewer rows than the source's known window raises.
- `scrape.py` isolates each source: one failure does not block the others.
- `scrape.py` exits nonzero if any source failed, so the scheduled task surfaces it.
- Partial success still commits the sources that succeeded.

## Dashboard

Single self-contained HTML reading `data.json`. Inline SVG, no chart library, consistent with
`inference-capital-markets-map.html`. Served locally via a `launch.json` entry, matching the
existing `oil-dashboard` pattern.

Five **stacked bar charts over time**, in the style of OpenRouter's "Top Models" chart:
x-axis is time, each bar is one period, each segment within the bar is one player, linear
scale. The biggest player over the range sits at the bottom of every stack. A breakdown
panel beside each chart lists every player's value for the hovered bar, sorted, plus the
total; it defaults to the most recent bar. Hovering dims every other bar.

Period = one day for the 30d / 90d ranges and one ISO week for "All". The final week on
"All" is usually partial; it is hatched and the panel says how many of its 7 days are in.

1. **Requests** — Chutes, AntSeed, Surplus, Engy
2. **Tokens** — Chutes, AntSeed, Surplus, Engy
3. **Buyer spend** — Chutes USD, AntSeed GMV
4. **Protocol capture** — AntSeed fees, Engy emissions
5. **Tokens per request** — Chutes, AntSeed, Surplus, Engy; Σ tokens ÷ Σ requests per
   period. Not additive, so this chart is **grouped** (one thin bar per player per period)
   rather than stacked, and has no total row.

Unequal coverage is honest by construction here: a player that only reports 28 days simply
has no segment in earlier bars. Nothing is averaged or extrapolated.

Two earlier designs were rejected. Log-scale lines on a shared time axis preserved the small
players but made magnitude unreadable — you could not see who was bigger or by how much.
A ranked leaderboard table (per-day averages) showed size but lost the time dimension
entirely. Stacked bars show both: the height is the market, the segments are the shares,
and the sequence is the trend.

Charts 3 and 4 are split deliberately. "Revenue" means three different things across this
roster — actual buyer USD (Chutes), marketplace settlement GMV (AntSeed), and token emissions that are not buyer
money at all (Engy). One axis labelled "revenue/day" would be the most misleading
chart on the page. Buyer spend vs protocol capture is the honest cut, and the gap between the
two is itself the interesting quantity.

Supporting UI:
- Range selector: 30d / 90d (daily bars) / All (weekly bars)
- Header strip: per player, latest value, 7-day change, and **data-through timestamp**, so a
  dead scraper reads as dead rather than as a plateau
- Absent players render as greyed legend entries with the reason on hover — never as zero,
  never silently dropped
- Scraped sources badged distinctly from API sources on the tiles

Scheduled daily ~08:10 UTC (after Surplus generates ~08:01 UTC and Engy's hourly rollup lands).
Windows Task Scheduler, matching the existing `BangkokWeekendUpdate` pattern. Task Scheduler
triggers are in local time: on this machine (Asia/Bangkok, UTC+7) that is 15:10.

## Success criteria

1. `python scrape.py` twice in succession -> identical row count, no duplicates
2. Saved HTML/JSON fixture per adapter -> parses to known row count and known values.
   This is the tripwire for format drift and the main regression guard.
3. Corrupt a fixture -> that adapter raises, process exits nonzero, DB unchanged, **other six
   sources still commit**
4. Engy fixture with 30 instead of 31 buckets -> raises rather than writing shifted dates
5. `build.py` -> every series date-sorted; no gaps within a player's covered range
6. Dashboard opens -> all five ranked charts render; each player present only where it has
   data; Surplus listed as not reported on charts 3 and 4

## Known limitations

- Surplus and Engy start at ~30 days and deepen only from first run. Chutes and AntSeed
  carry real back history, so the "All" view is uneven for roughly two months.
- Engy's emissions series measures token issuance, not customer payment. It sits on the
  capture chart for that reason and is not comparable to AntSeed fees without that caveat.
