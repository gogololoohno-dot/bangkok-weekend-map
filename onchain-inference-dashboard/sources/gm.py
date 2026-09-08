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
