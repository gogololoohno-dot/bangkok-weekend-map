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
