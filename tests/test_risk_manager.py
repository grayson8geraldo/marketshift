"""
Unit tests for the risk management module.
"""

import pytest

from bot.risk_manager import calculate_lot_size


class TestLotCalculation:
    def test_basic_lot_calc(self):
        """1% of $10,000 with 30-pip SL on EURUSD (point_value=1.0, point=0.00001)."""
        lot = calculate_lot_size(
            account_balance=10_000,
            risk_pct=1.0,
            sl_distance=0.00030,  # 30 pips = 0.00030
            point_value=1.0,
            point_size=0.00001,
        )
        # risk = $100, SL = 30 points, lot = 100 / 30 ≈ 3.33
        assert 3.0 <= lot <= 4.0

    def test_min_lot_enforced(self):
        lot = calculate_lot_size(
            account_balance=100,
            risk_pct=0.5,
            sl_distance=0.01,
            point_value=10.0,
            point_size=0.00001,
            min_lot=0.01,
        )
        assert lot >= 0.01

    def test_max_lot_enforced(self):
        lot = calculate_lot_size(
            account_balance=10_000_000,
            risk_pct=10.0,
            sl_distance=0.00001,
            point_value=0.01,
            point_size=0.00001,
            max_lot=100.0,
        )
        assert lot <= 100.0

    def test_zero_sl_returns_min_lot(self):
        lot = calculate_lot_size(
            account_balance=10_000,
            risk_pct=1.0,
            sl_distance=0.0,
            point_value=1.0,
            point_size=0.00001,
        )
        assert lot == 0.01

    def test_lot_step_rounding(self):
        lot = calculate_lot_size(
            account_balance=10_000,
            risk_pct=1.0,
            sl_distance=0.00050,
            point_value=1.0,
            point_size=0.00001,
            lot_step=0.01,
        )
        # Should be rounded to nearest 0.01
        assert round(lot * 100) == lot * 100
