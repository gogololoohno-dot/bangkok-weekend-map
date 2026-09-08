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
