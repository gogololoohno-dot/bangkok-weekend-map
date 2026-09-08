import pytest
from sources import antseed


def test_parse_extracts_full_history(fixture):
    rows = antseed.parse(fixture("antseed.html"))
    days = sorted({d for d, _, _ in rows})
    assert len(days) == 153
    assert days[0] == "2026-04-09" and days[-1] == "2026-09-08"


def test_parse_known_day(fixture):
    rows = set(antseed.parse(fixture("antseed.html")))
    assert ("2026-09-04", "requests", 75859.0) in rows
    assert ("2026-09-04", "tokens", 1368778609.0) in rows
    assert ("2026-09-04", "spend_gmv", 1842.858222) in rows
    assert ("2026-09-04", "capture_fees", 73.713038) in rows
    assert ("2026-09-04", "dau", 148.0) in rows
    assert ("2026-09-04", "settles", 2958.0) in rows


def test_no_match_raises():
    with pytest.raises(ValueError):
        antseed.parse(b"<html></html>")


def test_declares_contract():
    assert antseed.PLAYER == "antseed" and antseed.KIND == "scrape"
