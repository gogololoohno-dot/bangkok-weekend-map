import datetime as dt
import json
import pytest
from sources import blockrun

OVERVIEW = json.dumps({"timestamp": "2026-09-08T08:40:39.357Z", "overall": "degraded",
                       "models": {"total": 78}, "chain": {"status": "healthy"},
                       "totalCalls24h": 914}).encode()
CHAIN = json.dumps({"timestamp": "2026-09-08T08:40:39.897Z", "successRate24h": 0.997,
                    "avgSettlementTimeMs": 1420, "totalSettlements24h": 8293,
                    "failedSettlements24h": 24, "recentFailures": []}).encode()
NOW = dt.datetime(2026, 9, 8, 8, 10, tzinfo=dt.timezone.utc)


def test_parse_assigns_to_preceding_day():
    rows = set(blockrun.parse(OVERVIEW, CHAIN, now=NOW))
    assert rows == {("2026-09-07", "requests", 914.0),
                    ("2026-09-07", "settlements", 8293.0),
                    ("2026-09-07", "settlements_failed", 24.0)}


def test_missing_field_raises():
    with pytest.raises(KeyError):
        blockrun.parse(b"{}", CHAIN, now=NOW)


def test_declares_contract():
    assert blockrun.PLAYER == "blockrun" and blockrun.KIND == "api"
