"""
Unit tests for the zone detection module.
Uses synthetic OHLCV data — no MT5 connection required.
"""

import numpy as np
import pandas as pd
import pytest

from bot.zones import (
    find_swings,
    detect_zones,
    ZoneType,
    _is_round_number,
    _build_raw_zone,
)


def _make_ohlcv(n: int = 300, seed: int = 42) -> pd.DataFrame:
    """Generate synthetic OHLCV data with clear swing points."""
    rng = np.random.RandomState(seed)

    # Create a price series with two clear peaks and two clear troughs
    t = np.linspace(0, 4 * np.pi, n)
    base = 1.1000 + 0.0100 * np.sin(t) + 0.0005 * np.cumsum(rng.randn(n))

    close = base
    open_ = np.roll(close, 1)
    open_[0] = close[0]
    high = np.maximum(open_, close) + rng.uniform(0.0001, 0.0010, n)
    low = np.minimum(open_, close) - rng.uniform(0.0001, 0.0010, n)

    df = pd.DataFrame({
        "time": pd.date_range("2025-01-01", periods=n, freq="15min"),
        "open": open_,
        "high": high,
        "low": low,
        "close": close,
        "tick_volume": rng.randint(100, 5000, n),
    })
    return df


class TestSwings:
    def test_finds_swing_highs_and_lows(self):
        df = _make_ohlcv()
        result = find_swings(df)

        assert "swing_high" in result.columns
        assert "swing_low" in result.columns
        assert result["swing_high"].sum() > 0
        assert result["swing_low"].sum() > 0

    def test_swing_high_is_local_max(self):
        df = _make_ohlcv()
        result = find_swings(df, depth=10)
        sh_indices = result.index[result["swing_high"]].tolist()

        for idx in sh_indices:
            h = result.iloc[idx]["high"]
            for offset in range(1, 6):
                if idx - offset >= 0:
                    assert h > result.iloc[idx - offset]["high"]
                if idx + offset < len(result):
                    assert h > result.iloc[idx + offset]["high"]

    def test_swing_low_is_local_min(self):
        df = _make_ohlcv()
        result = find_swings(df, depth=10)
        sl_indices = result.index[result["swing_low"]].tolist()

        for idx in sl_indices:
            low = result.iloc[idx]["low"]
            for offset in range(1, 6):
                if idx - offset >= 0:
                    assert low < result.iloc[idx - offset]["low"]
                if idx + offset < len(result):
                    assert low < result.iloc[idx + offset]["low"]


class TestRoundNumbers:
    def test_forex_round_100pip(self):
        assert _is_round_number(1.1000) is True
        assert _is_round_number(1.0800) is True

    def test_forex_round_50pip(self):
        assert _is_round_number(1.0850) is True

    def test_forex_not_round(self):
        assert _is_round_number(1.08237) is False

    def test_index_round(self):
        assert _is_round_number(7000) is True
        assert _is_round_number(7500) is True

    def test_index_not_round(self):
        assert _is_round_number(7123) is False


class TestZoneDetection:
    def test_returns_zones(self):
        df = _make_ohlcv(500, seed=7)
        zones = detect_zones(df)
        # May or may not find zones depending on synthetic data;
        # at minimum the function should not crash
        assert isinstance(zones, list)

    def test_zone_structure(self):
        df = _make_ohlcv(500, seed=7)
        zones = detect_zones(df)
        for z in zones:
            assert z.upper >= z.lower
            assert z.zone_type in (ZoneType.SUPPLY, ZoneType.DEMAND)
            assert z.touches >= 2
            assert z.score > 0

    def test_zones_are_sorted_by_score(self):
        df = _make_ohlcv(500, seed=7)
        zones = detect_zones(df)
        scores = [z.score for z in zones]
        assert scores == sorted(scores, reverse=True)


class TestBuildRawZone:
    def test_supply_zone_wick_above_body(self):
        df = _make_ohlcv()
        idx = 50
        zone = _build_raw_zone(df, idx, ZoneType.SUPPLY)
        assert zone.upper == df.iloc[idx]["high"]
        assert zone.lower == max(df.iloc[idx]["open"], df.iloc[idx]["close"])
        assert zone.upper >= zone.lower

    def test_demand_zone_wick_below_body(self):
        df = _make_ohlcv()
        idx = 50
        zone = _build_raw_zone(df, idx, ZoneType.DEMAND)
        assert zone.lower == df.iloc[idx]["low"]
        assert zone.upper == min(df.iloc[idx]["open"], df.iloc[idx]["close"])
        assert zone.upper >= zone.lower
