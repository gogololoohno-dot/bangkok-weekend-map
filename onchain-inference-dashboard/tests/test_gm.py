import pytest
from sources import gm


def test_parse_epochs_from_fixture(fixture):
    epochs = gm.parse_epochs(fixture("gm_miners.html"))
    assert len(epochs) == 20
    assert epochs[0] == (24989, "2026-09-08T08:16:00+00:00", 10455, 652.99)
    assert epochs[-1] == (24970, "2026-09-07T09:23:00+00:00", 13288, 554.53)


def test_parse_no_table_raises():
    with pytest.raises(ValueError):
        gm.parse_epochs(b"<html></html>")


def _ep(n, ts, req=10, usd=1.0):
    return (n, ts, req, usd)


def test_rollup_emits_only_fully_bracketed_days():
    epochs = [
        _ep(100, "2026-09-06T23:30:00+00:00"),      # last before 09-07
        _ep(101, "2026-09-07T00:42:00+00:00"),
        _ep(102, "2026-09-07T01:54:00+00:00"),
        _ep(103, "2026-09-07T23:50:00+00:00"),
        _ep(104, "2026-09-08T01:02:00+00:00"),      # first after 09-07
    ]
    rows = gm.rollup(epochs)
    assert ("2026-09-07", "requests", 30.0) in rows
    assert ("2026-09-07", "spend_usd", 3.0) in rows
    # 09-06 has nothing before it; 09-08 has nothing after it -> both withheld
    assert {d for d, _, _ in rows} == {"2026-09-07"}


def test_rollup_withholds_day_with_missing_epoch():
    epochs = [
        _ep(100, "2026-09-06T23:30:00+00:00"),
        _ep(101, "2026-09-07T00:42:00+00:00"),
        # 102 missing
        _ep(103, "2026-09-07T23:50:00+00:00"),
        _ep(104, "2026-09-08T01:02:00+00:00"),
    ]
    assert gm.rollup(epochs) == []


def test_rollup_withholds_first_observed_day():
    epochs = [_ep(101, "2026-09-07T00:42:00+00:00"), _ep(102, "2026-09-08T01:02:00+00:00")]
    assert gm.rollup(epochs) == []


def test_declares_contract():
    assert gm.PLAYER == "gm" and gm.KIND == "scrape"
