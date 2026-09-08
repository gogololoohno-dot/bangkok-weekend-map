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
