# Onchain Inference Dashboard

Daily scraper + single-file dashboard tracking 4 onchain inference players.
Design: `../docs/superpowers/specs/2026-09-08-onchain-inference-dashboard-design.md`

## Run

    uv run python scrape.py        # all sources -> data/inference.db
    uv run python scrape.py --only chutes
    uv run python build.py         # -> dashboard/data.json
    uv run pytest                  # fixtures under tests/fixtures

Serve `dashboard/` with any static server (launch.json entry `inference-dashboard`, port 8792).

## Schedule

`register_tasks.ps1` creates one Task Scheduler job, `OnchainInferenceDaily`, at 15:10 local
(UTC+7). Logs append to `scrape.log`. A nonzero exit means at least one source failed —
check the log before trusting that day.

## Sources

| player | kind | metrics |
|---|---|---|
| chutes | api | requests, tokens_in/out, spend_usd |
| antseed | scrape | requests, tokens, spend_gmv, capture_fees, dau, settles |
| surplus | scrape | requests, tokens_in/out/cache |
| engy | scrape + api | requests, tokens; capture_emissions (taostats key from `../inference-farm/.env`) |

Scraped sources parse undocumented Next.js payloads. When one breaks, its adapter raises,
the run exits 1, and the other sources still commit. Fix the regex, refresh the fixture,
update the test expectations.
