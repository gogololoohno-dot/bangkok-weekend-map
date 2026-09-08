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
