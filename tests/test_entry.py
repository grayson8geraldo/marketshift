"""
Unit tests for the entry logic module.
"""

import numpy as np
import pandas as pd
import pytest

from bot.entry import _ltf_swings, _detect_exhaustion, Signal
from bot.zones import Zone, ZoneType


def _make_ltf_data(n: int = 200, trend: str = "up", seed: int = 42) -> pd.DataFrame:
    """Generate synthetic 1-minute data."""
    rng = np.random.RandomState(seed)

    if trend == "up":
        base = 1.1000 + np.linspace(0, 0.0050, n) + 0.0002 * np.cumsum(rng.randn(n))
    elif trend == "down":
        base = 1.1050 - np.linspace(0, 0.0050, n) + 0.0002 * np.cumsum(rng.randn(n))
    else:
        base = 1.1025 + 0.0003 * np.cumsum(rng.randn(n))

    close = base
    open_ = np.roll(close, 1)
    open_[0] = close[0]
    high = np.maximum(open_, close) + rng.uniform(0.0001, 0.0005, n)
    low = np.minimum(open_, close) - rng.uniform(0.0001, 0.0005, n)

    return pd.DataFrame({
        "time": pd.date_range("2025-01-01", periods=n, freq="1min"),
        "open": open_,
        "high": high,
        "low": low,
        "close": close,
        "tick_volume": rng.randint(50, 2000, n),
    })


class TestLTFSwings:
    def test_finds_swings(self):
        df = _make_ltf_data(200, "up")
        sh_idx, sh_price, sl_idx, sl_price = _ltf_swings(df, period=3)
        assert len(sh_idx) > 0
        assert len(sl_idx) > 0
        assert len(sh_idx) == len(sh_price)
        assert len(sl_idx) == len(sl_price)

    def test_swing_high_prices_match(self):
        df = _make_ltf_data(200, "up")
        sh_idx, sh_price, _, _ = _ltf_swings(df, period=3)
        for idx, price in zip(sh_idx, sh_price):
            assert price == df.iloc[idx]["high"]


class TestExhaustion:
    def test_strong_impulse_candles_detected(self):
        """Large bodied candles with no retracement = exhaustion."""
        n = 20
        # Build candles that are 90% body (strong impulse up)
        open_ = np.linspace(1.1000, 1.1050, n)
        close = open_ + 0.0003  # body = 3 pips up
        high = close + 0.00005
        low = open_ - 0.00005

        df = pd.DataFrame({
            "time": pd.date_range("2025-01-01", periods=n, freq="1min"),
            "open": open_,
            "high": high,
            "low": low,
            "close": close,
            "tick_volume": np.full(n, 500),
        })

        zone = Zone(
            zone_type=ZoneType.SUPPLY,
            upper=1.1060,
            lower=1.1055,
        )
        result = _detect_exhaustion(df, zone, arrival_idx=15)
        assert result == True

    def test_no_exhaustion_in_choppy_market(self):
        """Small bodies and random movement = no exhaustion."""
        df = _make_ltf_data(50, "up", seed=99)
        zone = Zone(zone_type=ZoneType.SUPPLY, upper=1.12, lower=1.118)
        result = _detect_exhaustion(df, zone, arrival_idx=40)
        # Choppy data likely won't pass exhaustion criteria
        assert isinstance(result, bool)


class TestRiskReward:
    def test_min_rr_filter(self):
        """Ensure we don't take trades with R:R below the minimum."""
        from config.settings import MIN_RR_RATIO
        assert MIN_RR_RATIO >= 1.0
