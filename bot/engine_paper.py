"""
Paper trading engine — uses real market data with virtual balance.
No MetaTrader 5 required.

Data sources (auto-selected):
  1. yfinance — real live forex data (needs internet)
  2. Simulator — realistic generated price action (works offline)
"""

from __future__ import annotations

import time
import signal as sig
import sys
from datetime import datetime

# Try yfinance first, fall back to built-in simulator
_DATA_SOURCE = "Built-in simulator"
_yf_get_rates = None
_yf_get_point_size = None
_yf_get_current_price = None
try:
    import logging
    logging.getLogger("yfinance").setLevel(logging.CRITICAL)
    from bot.data_provider_yfinance import (
        get_rates as _yf_get_rates,
        get_point_size as _yf_get_point_size,
        get_current_price as _yf_get_current_price,
    )
    # Quick connectivity test
    import io, contextlib
    with contextlib.redirect_stderr(io.StringIO()):
        _yf_get_rates("EURUSD", "M15", 5)
    _DATA_SOURCE = "Yahoo Finance (live)"
except Exception:
    pass

# Always import simulator as fallback
from bot.data_provider_sim import (
    get_rates as sim_get_rates,
    get_point_size as sim_get_point_size,
    get_current_price as sim_get_current_price,
)


def _safe_get_rates(symbol, timeframe, count):
    if _DATA_SOURCE.startswith("Yahoo"):
        try:
            return _yf_get_rates(symbol, timeframe, count)
        except Exception:
            pass
    return sim_get_rates(symbol, timeframe, count)


def _safe_get_current_price(symbol):
    if _DATA_SOURCE.startswith("Yahoo"):
        try:
            return _yf_get_current_price(symbol)
        except Exception:
            pass
    return sim_get_current_price(symbol)


def _safe_get_point_size(symbol):
    if _DATA_SOURCE.startswith("Yahoo"):
        try:
            return _yf_get_point_size(symbol)
        except Exception:
            pass
    return sim_get_point_size(symbol)
from bot.zones import detect_zones, Zone, ZoneType
from bot.entry import find_entry, TradeSetup, Signal
from bot.risk_manager import calculate_lot_size
from bot.paper_trader import PaperTrader, PaperPosition
from config.settings import (
    HTF_TIMEFRAME, LTF_TIMEFRAME, HTF_BARS, LTF_BARS,
    RISK_PER_TRADE_PCT, BREAKEVEN_TRIGGER_RR,
    TRAILING_STOP_ENABLED, TRAILING_STEP_POINTS, SL_BUFFER_POINTS,
)


class PaperTradingEngine:
    """
    Real data + virtual money.

    Workflow:
    1. Fetch real OHLCV from Yahoo Finance.
    2. Detect zones on HTF, find entries on LTF.
    3. Execute virtual trades, manage SL/TP/trailing.
    4. Print live P&L and summary on exit.
    """

    def __init__(
        self,
        symbol: str = "EURUSD",
        balance: float = 200.0,
        risk_pct: float = 3.0,
        poll_interval: int = 30,
    ):
        self.symbol = symbol
        self.risk_pct = risk_pct
        self.poll_interval = poll_interval
        self.point_size = _safe_get_point_size(symbol)
        self.trader = PaperTrader(balance=balance)
        self.zones: list[Zone] = []
        self.last_htf_bar_time = None
        self._running = True

    def start(self):
        # Handle Ctrl+C gracefully
        sig.signal(sig.SIGINT, self._handle_exit)
        sig.signal(sig.SIGTERM, self._handle_exit)

        print("=" * 60)
        print("  MarketShift — Paper Trading Mode")
        print(f"  Data:      {_DATA_SOURCE}")
        print(f"  Symbol:    {self.symbol}")
        print(f"  Balance:   ${self.trader.account.balance:.2f}")
        print(f"  Risk/trade:{self.risk_pct}%")
        print(f"  HTF:       {HTF_TIMEFRAME}  |  LTF: {LTF_TIMEFRAME}")
        print(f"  Poll:      every {self.poll_interval}s")
        print("=" * 60)

        print("\n[ENGINE] Loading initial data...")
        self._refresh_zones()
        print(f"[ENGINE] Found {len(self.zones)} active zones. Starting loop.\n")
        print("Press Ctrl+C to stop and see summary.\n")

        while self._running:
            try:
                self._tick()
            except KeyboardInterrupt:
                break
            except Exception as e:
                print(f"[ENGINE] Error: {e}")
            time.sleep(self.poll_interval)

        self.trader.account.print_summary()

    def _handle_exit(self, signum, frame):
        print("\n[ENGINE] Shutting down...")
        self._running = False

    def _refresh_zones(self):
        """Fetch HTF data and detect zones."""
        try:
            df_htf = _safe_get_rates(self.symbol, HTF_TIMEFRAME, HTF_BARS)
        except Exception as e:
            print(f"[ENGINE] Failed to fetch HTF data: {e}")
            return

        current_htf_time = df_htf["time"].iloc[-1]

        if self.last_htf_bar_time is None or current_htf_time != self.last_htf_bar_time:
            self.zones = detect_zones(df_htf)
            self.last_htf_bar_time = current_htf_time
            print(f"[ZONES] {current_htf_time} — {len(self.zones)} zones detected:")
            for z in self.zones[:8]:
                rn = " [ROUND]" if z.round_number else ""
                print(f"  {z.zone_type.value:6s} | "
                      f"{z.lower:.5f} – {z.upper:.5f} | "
                      f"touches={z.touches} impulse={z.impulse_score:.2f} "
                      f"score={z.score:.2f}{rn}")

    def _tick(self):
        """Single iteration of the trading loop."""
        # 1. Refresh zones
        self._refresh_zones()

        # 2. Get current price
        try:
            bid, ask = _safe_get_current_price(self.symbol)
        except Exception as e:
            print(f"[ENGINE] Price fetch error: {e}")
            return

        current_price = (bid + ask) / 2
        now = datetime.now().strftime("%H:%M:%S")

        # 3. Update open positions (SL/TP check + trailing)
        if self.trader.has_open_positions:
            self._manage_positions(bid, ask)
            self.trader.update_positions(bid, ask, self.point_size)

            # Status line
            pos = self.trader.account.positions
            if pos:
                p = pos[0]
                if p.signal == Signal.LONG:
                    unrealized = (bid - p.entry_price) / self.point_size
                else:
                    unrealized = (p.entry_price - ask) / self.point_size
                print(f"[{now}] {self.symbol} bid={bid:.5f} | "
                      f"Position #{p.ticket} {p.signal.value} "
                      f"pips={unrealized:.1f} SL={p.stop_loss:.5f}")
            return

        # 4. No open position — search for entry
        print(f"[{now}] {self.symbol} bid={bid:.5f} ask={ask:.5f} | Scanning...")

        for zone in self.zones:
            if not (zone.lower <= current_price <= zone.upper):
                continue

            print(f"  Price in {zone.zone_type.value} zone "
                  f"[{zone.lower:.5f}–{zone.upper:.5f}]")

            # Find TP target
            tp_target = self._find_tp_target(zone)
            if tp_target is None:
                print(f"  No opposing zone for TP — skip")
                continue

            # Get LTF data and look for entry
            try:
                df_ltf = _safe_get_rates(self.symbol, LTF_TIMEFRAME, LTF_BARS)
            except Exception as e:
                print(f"  LTF data error: {e}")
                continue

            setup = find_entry(df_ltf, zone, tp_target, self.point_size)
            if setup is None:
                print(f"  No BOS entry signal yet")
                continue

            # Execute paper trade
            sl_distance = abs(setup.entry_price - setup.stop_loss)
            lot = calculate_lot_size(
                account_balance=self.trader.account.balance,
                risk_pct=self.risk_pct,
                sl_distance=sl_distance,
                point_value=10.0,  # ~$10/pip per standard lot
                point_size=self.point_size,
            )

            entry_price = ask if setup.signal == Signal.LONG else bid

            self.trader.open_position(
                signal=setup.signal,
                entry_price=entry_price,
                stop_loss=setup.stop_loss,
                take_profit=setup.take_profit,
                lot_size=lot,
            )
            print(f"  R:R = {setup.rr_ratio} | Lot = {lot}")
            break

    def _manage_positions(self, bid: float, ask: float):
        """Breakeven + trailing stop logic."""
        for pos in self.trader.account.positions:
            current_price = bid if pos.signal == Signal.SHORT else ask

            # Breakeven
            if not pos.breakeven_applied:
                risk = abs(pos.entry_price - pos.stop_loss)
                if pos.signal == Signal.LONG:
                    profit = current_price - pos.entry_price
                else:
                    profit = pos.entry_price - current_price

                if risk > 0 and (profit / risk) >= BREAKEVEN_TRIGGER_RR:
                    self.trader.modify_sl(pos, pos.entry_price)
                    pos.breakeven_applied = True

            # Trailing stop
            if TRAILING_STOP_ENABLED and pos.breakeven_applied:
                step = TRAILING_STEP_POINTS * self.point_size
                if pos.signal == Signal.LONG:
                    candidate = current_price - step
                    if candidate > pos.stop_loss:
                        self.trader.modify_sl(pos, round(candidate, 5))
                else:
                    candidate = current_price + step
                    if candidate < pos.stop_loss:
                        self.trader.modify_sl(pos, round(candidate, 5))

    def _find_tp_target(self, active_zone: Zone) -> float | None:
        """Find nearest opposing zone as TP."""
        opposing = (
            ZoneType.DEMAND if active_zone.zone_type == ZoneType.SUPPLY
            else ZoneType.SUPPLY
        )
        candidates = [z for z in self.zones if z.zone_type == opposing]

        if not candidates:
            return None

        if active_zone.zone_type == ZoneType.SUPPLY:
            below = [z for z in candidates if z.upper < active_zone.lower]
            if not below:
                return None
            return max(below, key=lambda z: z.upper).upper
        else:
            above = [z for z in candidates if z.lower > active_zone.upper]
            if not above:
                return None
            return min(above, key=lambda z: z.lower).lower
