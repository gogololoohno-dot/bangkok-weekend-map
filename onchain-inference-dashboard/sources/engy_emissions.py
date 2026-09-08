"""Engy (SN53) miner emissions in USD, via taostats. Same math as
inference-farm/scripts/poll_sn53.py. A daily-rate snapshot, not a settlement figure:
this is token issuance to miners, not buyer money, and sits on the capture chart.
"""

import datetime as dt
import json
import os
import time
import urllib.request
from pathlib import Path

PLAYER = "engy"
KIND = "api"

NETUID = 53
BASE = "https://api.taostats.io/api"
RAO = 1e9
ENV_FILE = Path(__file__).resolve().parents[2] / "inference-farm" / ".env"


def load_key() -> str:
    if os.environ.get("TAOSTATS_API_KEY"):
        return os.environ["TAOSTATS_API_KEY"]
    if ENV_FILE.exists():
        for line in ENV_FILE.read_text().splitlines():
            if line.startswith("TAOSTATS_API_KEY="):
                return line.split("=", 1)[1].strip()
    raise RuntimeError(f"No TAOSTATS_API_KEY in env or {ENV_FILE}")


def _get(path, key, **params):
    qs = "&".join(f"{k}={v}" for k, v in params.items())
    req = urllib.request.Request(f"{BASE}/{path}?{qs}", headers={
        "Authorization": key, "accept": "application/json",
        # Cloudflare rejects the default urllib UA before auth is checked.
        "User-Agent": "onchain-inference-dashboard/0.1",
    })
    with urllib.request.urlopen(req, timeout=30) as r:
        return json.load(r)


def compute(neurons, pool, tao_usd: float, now: dt.datetime | None = None):
    now = now or dt.datetime.now(dt.timezone.utc)
    day = (now.date() - dt.timedelta(days=1)).isoformat()
    total_alpha = sum(float(n.get("daily_mining_alpha") or 0) for n in neurons) / RAO
    if total_alpha <= 0:
        raise ValueError("engy emissions: no miner alpha reported")
    alpha_usd = float(pool["price"]) * tao_usd
    return [(day, "capture_emissions", total_alpha * alpha_usd)]


def fetch():
    key = load_key()
    resp = _get("metagraph/latest/v1", key, netuid=NETUID, limit=256)
    neurons = resp["data"]
    total = resp.get("pagination", {}).get("total_items", len(neurons))
    if len(neurons) < total:
        raise ValueError(f"engy emissions: got {len(neurons)} of {total} neurons")
    time.sleep(2)  # free tier rate-limits bursts
    pool = _get("dtao/pool/latest/v1", key, netuid=NETUID)["data"][0]
    time.sleep(2)
    tao_usd = float(_get("price/latest/v1", key, asset="tao")["data"][0]["price"])
    return compute(neurons, pool, tao_usd)
