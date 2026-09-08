import json
import pytest
from sources import venice

RAW = json.dumps({"granularity": "daily", "range": "all", "buckets": [
    {"t": 1788739200000, "discUsdThen": 5000.0, "discUsdNow": 9999.0,
     "proSubUsdThen": 4288.0, "proSubUsdNow": 9999.0, "proSubCount": 1850,
     "creditsUsdThen": 10130.0, "creditsUsdNow": 9999.0, "creditsCount": 2026, "hasOneOff": False},
]}).encode()


def test_parse_maps_burn_value_to_capture():
    rows = set(venice.parse(RAW))
    assert ("2026-09-07", "capture_burns", 14418.0) in rows       # credits + subs, "Then" only
    assert ("2026-09-07", "credits_count", 2026.0) in rows
    assert ("2026-09-07", "subs_count", 1850.0) in rows
    assert len(rows) == 3


def test_empty_raises():
    with pytest.raises(ValueError):
        venice.parse(json.dumps({"buckets": []}).encode())


def test_declares_contract():
    assert venice.PLAYER == "venice" and venice.KIND == "api"
