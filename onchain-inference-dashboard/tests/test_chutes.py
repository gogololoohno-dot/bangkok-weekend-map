import json
import pytest
from sources import chutes

STATS = json.dumps([
    {"chute_id": "a", "name": "GLM", "date": "2026-09-07", "total_requests": 100,
     "total_input_tokens": 1000, "total_output_tokens": 50, "average_tps": 1, "average_ttft": 1},
    {"chute_id": "b", "name": "Kimi", "date": "2026-09-07", "total_requests": 20,
     "total_input_tokens": 200, "total_output_tokens": 10, "average_tps": 1, "average_ttft": 1},
    {"chute_id": "a", "name": "GLM", "date": "2026-09-06", "total_requests": 7,
     "total_input_tokens": 70, "total_output_tokens": 3, "average_tps": 1, "average_ttft": 1},
]).encode()

USAGE = json.dumps([
    {"chute_id": "a", "date": "2026-09-07", "usd_amount": 1.5, "invocation_count": 100},
    {"chute_id": "b", "date": "2026-09-07", "usd_amount": 2.25, "invocation_count": 20},
]).encode()


def test_parse_stats_sums_models_per_day():
    rows = set(chutes.parse_stats(STATS))
    assert ("2026-09-07", "requests", 120.0) in rows
    assert ("2026-09-07", "tokens_in", 1200.0) in rows
    assert ("2026-09-07", "tokens_out", 60.0) in rows
    assert ("2026-09-06", "requests", 7.0) in rows
    assert len(rows) == 6


def test_parse_usage_sums_chutes_per_day():
    assert chutes.parse_usage(USAGE) == [("2026-09-07", "spend_usd", 3.75)]


def test_empty_payload_raises():
    with pytest.raises(ValueError):
        chutes.parse_stats(b"[]")
    with pytest.raises(ValueError):
        chutes.parse_usage(b"[]")


def test_declares_contract():
    assert chutes.PLAYER == "chutes"
    assert chutes.KIND == "api"
