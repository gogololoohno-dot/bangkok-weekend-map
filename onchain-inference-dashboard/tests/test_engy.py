import pytest
from sources import engy


def test_parse_requests_page(fixture):
    rows = engy.parse(fixture("engy_requests.html"), "requests")
    assert len(rows) == 31
    days = [d for d, _, _ in rows]
    assert days[0] == "2026-08-09" and days[-1] == "2026-09-08"
    # first bucket: qwen3.6-35b-a3b=615485 + deepseek=8680 + glm-5.2=31471 + others
    by_day = dict((d, v) for d, _, v in rows)
    assert by_day["2026-08-09"] > 615485
    assert all(m == "requests" for _, m, _ in rows)


def test_parse_tokens_page(fixture):
    rows = engy.parse(fixture("engy_tokens.html"), "tokens")
    assert len(rows) == 31
    by_day = dict((d, v) for d, _, v in rows)
    assert by_day["2026-08-09"] > 6077651372          # first model's first bucket alone


def test_length_mismatch_raises():
    bad = (b'\\"buckets\\":[1788739200,1788825600],'
           b'\\"series\\":[{\\"model\\":\\"x\\",\\"counts\\":[1,2,3]}]')
    with pytest.raises(ValueError):
        engy.parse(bad, "requests")


def test_no_buckets_raises():
    with pytest.raises(ValueError):
        engy.parse(b"<html></html>", "requests")


def test_declares_contract():
    assert engy.PLAYER == "engy" and engy.KIND == "scrape"
