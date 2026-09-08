import datetime as dt
import pytest
from sources import engy_emissions as em

NOW = dt.datetime(2026, 9, 8, 8, 10, tzinfo=dt.timezone.utc)
NEURONS = [{"daily_mining_alpha": "1000000000000"},    # 1000 alpha
           {"daily_mining_alpha": "2000000000000"},    # 2000 alpha
           {"daily_mining_alpha": "0"}]
POOL = {"price": "0.03"}          # alpha in TAO
TAO_USD = 200.0


def test_compute_prices_miner_pool():
    rows = em.compute(NEURONS, POOL, TAO_USD, now=NOW)
    # 3000 alpha * 0.03 TAO * $200 = $18,000
    assert rows == [("2026-09-07", "capture_emissions", 18000.0)]


def test_no_miners_raises():
    with pytest.raises(ValueError):
        em.compute([{"daily_mining_alpha": "0"}], POOL, TAO_USD, now=NOW)


def test_declares_contract():
    assert em.PLAYER == "engy" and em.KIND == "api"
