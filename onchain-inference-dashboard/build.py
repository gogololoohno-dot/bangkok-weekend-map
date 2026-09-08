"""Flatten the store into dashboard/data.json. Usage: python build.py"""

import collections
import datetime as dt
import json
from pathlib import Path

import store
from sources import PLAYERS

OUT_PATH = Path(__file__).parent / "dashboard" / "data.json"

# chart -> metrics summed per (player, day)
CHARTS = {
    "requests": {"requests"},
    "tokens":   {"tokens", "tokens_in", "tokens_out", "tokens_cache"},
    "spend":    {"spend_usd", "spend_gmv"},
    "capture":  {"capture_fees", "capture_emissions"},
}


def build(conn, now: dt.datetime | None = None) -> dict:
    now = now or dt.datetime.now(dt.timezone.utc)
    today = now.date().isoformat()
    # chart -> player -> day -> value
    acc = {c: collections.defaultdict(lambda: collections.defaultdict(float)) for c in CHARTS}
    through = {}
    for player, day, metric, value in store.all_daily(conn):
        if day >= today:
            continue
        through[player] = max(through.get(player, ""), day)
        for chart, metrics in CHARTS.items():
            if metric in metrics:
                acc[chart][player][day] += value

    charts = {}
    for chart, per_player in acc.items():
        charts[chart] = {p: [[d, v] for d, v in sorted(days.items())]
                         for p, days in per_player.items()}

    tpr = {}
    for player, days in acc["tokens"].items():
        reqs = acc["requests"].get(player, {})
        pts = [[d, days[d] / reqs[d]] for d in sorted(days) if reqs.get(d)]
        if pts:
            tpr[player] = pts
    charts["tokens_per_request"] = tpr

    return {
        "generated_at": now.isoformat(timespec="seconds"),
        "players": PLAYERS,
        "charts": charts,
        "through": through,
    }


def write(conn, path: Path = OUT_PATH, now: dt.datetime | None = None) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(build(conn, now)), encoding="utf-8")


if __name__ == "__main__":
    write(store.connect())
    print(f"wrote {OUT_PATH}")
