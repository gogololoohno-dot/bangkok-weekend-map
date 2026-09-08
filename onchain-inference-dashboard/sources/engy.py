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
