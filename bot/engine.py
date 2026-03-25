"""
Main trading engine — orchestrates zone detection, entry search, and position management.
"""

from __future__ import annotations

import time
from datetime import datetime

from bot.data_provider import (
    init_mt5, shutdown_mt5, get_rates, get_symbol_info, get_account_info,
)
from bot.zones import detect_zones, Zone, ZoneType
from bot.entry import find_entry, TradeSetup, Signal
from bot.risk_manager import (
    calculate_lot_size, open_trade, manage_position, OpenPosition,
)
from config.settings import (
    HTF_TIMEFRAME, LTF_TIMEFRAME, HTF_BARS, LTF_BARS,
    SYMBOL, RISK_PER_TRADE_PCT, MIN_RR_RATIO,
)


class TradingEngine:
    """
    Main loop:
    1. Every HTF bar → re-scan zones.
    2. Every LTF bar → check if price is inside a zone → search for entry.
    3. Continuously manage open positions.
    """

    def __init__(self, symbol: str = SYMBOL):
        self.symbol = symbol
        self.zones: list[Zone] = []
        self.open_positions: list[OpenPosition] = []
        self.last_htf_bar_time = None

    # ── Lifecycle ────────────────────────────────────────────────────────

    def start(self):
        if not init_mt5():
            raise RuntimeError("Cannot initialize MT5")

        info = get_symbol_info(self.symbol)
        self.point_size = info.point
        self.point_value = info.trade_tick_value
        self.min_lot = info.volume_min
        self.max_lot = info.volume_max
        self.lot_step = info.volume_step

        print(f"[ENGINE] Started on {self.symbol} | "
              f"HTF={HTF_TIMEFRAME} LTF={LTF_TIMEFRAME} | "
              f"point={self.point_size}")

        try:
            self._loop()
        except KeyboardInterrupt:
            print("\n[ENGINE] Stopped by user.")
        finally:
            shutdown_mt5()

    def _loop(self):
        while True:
            try:
                self._tick()
            except Exception as e:
                print(f"[ENGINE] Error in tick: {e}")
            time.sleep(1)

    # ── Per-tick logic ───────────────────────────────────────────────────

    def _tick(self):
        # 1. Refresh HTF zones periodically
        df_htf = get_rates(self.symbol, HTF_TIMEFRAME, HTF_BARS)
        current_htf_time = df_htf["time"].iloc[-1]

        if self.last_htf_bar_time is None or current_htf_time != self.last_htf_bar_time:
            self.zones = detect_zones(df_htf)
            self.last_htf_bar_time = current_htf_time
            print(f"[ENGINE] {current_htf_time} — {len(self.zones)} active zones")
            for z in self.zones[:5]:
                print(f"  {z.zone_type.value:6s} | "
                      f"{z.lower:.5f}–{z.upper:.5f} | "
                      f"touches={z.touches} impulse={z.impulse_score:.2f} "
                      f"round={z.round_number} score={z.score}")

        # 2. Manage existing positions
        self.open_positions = [
            pos for pos in self.open_positions
            if manage_position(pos, self.symbol, self.point_size)
        ]

        # 3. If no open position, search for new entry
        if self.open_positions:
            return

        df_ltf = get_rates(self.symbol, LTF_TIMEFRAME, LTF_BARS)
        current_price = df_ltf["close"].iloc[-1]

        for zone in self.zones:
            if not self._price_in_zone(current_price, zone):
                continue

            tp_target = self._find_tp_target(zone)
            if tp_target is None:
                continue

            setup = find_entry(df_ltf, zone, tp_target, self.point_size)
            if setup is None:
                continue

            # Execute trade
            account = get_account_info()
            sl_distance = abs(setup.entry_price - setup.stop_loss)

            lot = calculate_lot_size(
                account_balance=account.balance,
                risk_pct=RISK_PER_TRADE_PCT,
                sl_distance=sl_distance,
                point_value=self.point_value,
                point_size=self.point_size,
                min_lot=self.min_lot,
                max_lot=self.max_lot,
                lot_step=self.lot_step,
            )

            position = open_trade(setup, self.symbol, lot)
            if position:
                self.open_positions.append(position)
                print(f"[ENGINE] Opened {setup.signal.value} | "
                      f"RR={setup.rr_ratio} | lot={lot}")
            break  # One trade at a time

    # ── Helpers ──────────────────────────────────────────────────────────

    def _price_in_zone(self, price: float, zone: Zone) -> bool:
        return zone.lower <= price <= zone.upper

    def _find_tp_target(self, active_zone: Zone) -> float | None:
        """
        Find the nearest opposing zone as a take-profit target.
        Supply zone trade → TP at nearest demand zone (and vice versa).
        """
        opposing_type = (
            ZoneType.DEMAND if active_zone.zone_type == ZoneType.SUPPLY
            else ZoneType.SUPPLY
        )

        candidates = [z for z in self.zones if z.zone_type == opposing_type]
        if not candidates:
            return None

        if active_zone.zone_type == ZoneType.SUPPLY:
            # Short → TP below → nearest demand zone below current price
            below = [z for z in candidates if z.upper < active_zone.lower]
            if not below:
                return None
            return max(below, key=lambda z: z.upper).upper
        else:
            # Long → TP above → nearest supply zone above current price
            above = [z for z in candidates if z.lower > active_zone.upper]
            if not above:
                return None
            return min(above, key=lambda z: z.lower).lower
