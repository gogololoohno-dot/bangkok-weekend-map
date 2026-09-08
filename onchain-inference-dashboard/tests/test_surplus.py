import pytest
from sources import surplus


def test_parse_extracts_28_days(fixture):
    rows = surplus.parse(fixture("surplus.html"))
    days = sorted({d for d, _, _ in rows})
    assert len(days) == 28
    assert days[0] == "2026-08-12" and days[-1] == "2026-09-08"


def test_parse_known_day(fixture):
    rows = set(surplus.parse(fixture("surplus.html")))
    assert ("2026-09-05", "requests", 1464868.0) in rows
    assert ("2026-09-05", "tokens_in", 72484554369.0) in rows
    assert ("2026-09-05", "tokens_out", 1457577822.0) in rows
    assert ("2026-09-05", "tokens_cache", 58873521207.0) in rows


def test_no_match_raises():
    with pytest.raises(ValueError):
        surplus.parse(b"<html>nothing here</html>")


def test_declares_contract():
    assert surplus.PLAYER == "surplus" and surplus.KIND == "scrape"
