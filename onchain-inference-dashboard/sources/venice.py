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
