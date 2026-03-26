"""
Paper trading engine — multi-symbol, real market data, virtual balance.
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
from dataclasses import dataclass, field

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

from bot.zones import detect_zones, Zone, ZoneType
from bot.entry import find_entry, TradeSetup, Signal
from bot.risk_manager import calculate_lot_size
from bot.paper_trader import PaperTrader, PaperPosition
from config.settings import (
    HTF_TIMEFRAME, LTF_TIMEFRAME, HTF_BARS, LTF_BARS,
    RISK_PER_TRADE_PCT, BREAKEVEN_TRIGGER_RR,
    TRAILING_STOP_ENABLED, TRAILING_STEP_POINTS, SL_BUFFER_POINTS,
)


# All supported forex pairs
ALL_SYMBOLS = [
    "EURUSD", "GBPUSD", "USDJPY", "USDCHF",
    "AUDUSD", "NZDUSD", "USDCAD",
    "EURGBP", "EURJPY", "GBPJPY",
    "XAUUSD",
]


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


@dataclass
class SymbolState:
    """Tracked state per symbol."""
    symbol: str
    point_size: float
    zones: list[Zone] = field(default_factory=list)
    last_htf_bar_time: object = None


class PaperTradingEngine:
    """
    Multi-symbol paper trading engine.

    Workflow per tick:
    1. Refresh zones for all symbols.
    2. Fetch prices, update open positions.
    3. For symbols without open positions, scan for entries.
    """

    def __init__(
        self,
        symbols: list[str] | None = None,
        balance: float = 200.0,
        risk_pct: float = 3.0,
        poll_interval: int = 30,
        max_positions: int = 3,
    ):
        if symbols is None:
            symbols = ALL_SYMBOLS

        self.symbols = symbols
        self.risk_pct = risk_pct
        self.poll_interval = poll_interval
        self.max_positions = max_positions
        self.trader = PaperTrader(balance=balance)
        self._running = True

        # Per-symbol state
        self.states: dict[str, SymbolState] = {}
        for sym in symbols:
            self.states[sym] = SymbolState(
                symbol=sym,
                point_size=_safe_get_point_size(sym),
            )

    def start(self):
        sig.signal(sig.SIGINT, self._handle_exit)
        sig.signal(sig.SIGTERM, self._handle_exit)

        sym_list = ", ".join(self.symbols)
        print("=" * 65)
        print("  MarketShift — Multi-Symbol Paper Trading")
        print(f"  Data:       {_DATA_SOURCE}")
        print(f"  Symbols:    {sym_list}")
        print(f"  Balance:    ${self.trader.account.balance:.2f}")
        print(f"  Risk/trade: {self.risk_pct}%")
        print(f"  Max open:   {self.max_positions} positions")
        print(f"  HTF: {HTF_TIMEFRAME}  |  LTF: {LTF_TIMEFRAME}")
        print(f"  Poll:       every {self.poll_interval}s")
        print("=" * 65)

        print("\n[ENGINE] Loading initial data...")
        total_zones = 0
        for sym in self.symbols:
            self._refresh_zones(sym)
            total_zones += len(self.states[sym].zones)
        print(f"[ENGINE] {total_zones} total zones across "
              f"{len(self.symbols)} symbols. Starting loop.\n")
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

    # ── Zone refresh ─────────────────────────────────────────────────

    def _refresh_zones(self, symbol: str):
        state = self.states[symbol]
        try:
            df_htf = _safe_get_rates(symbol, HTF_TIMEFRAME, HTF_BARS)
        except Exception as e:
            print(f"[{symbol}] HTF data error: {e}")
            return

        current_htf_time = df_htf["time"].iloc[-1]
        if state.last_htf_bar_time is not None and current_htf_time == state.last_htf_bar_time:
            return

        state.zones = detect_zones(df_htf)
        state.last_htf_bar_time = current_htf_time

        if state.zones:
            print(f"[ZONES] {symbol} — {len(state.zones)} zones:")
            for z in state.zones[:3]:
                rn = " [ROUND]" if z.round_number else ""
                print(f"  {z.zone_type.value:6s} | "
                      f"{z.lower:.5f} – {z.upper:.5f} | "
                      f"touches={z.touches} score={z.score:.2f}{rn}")

    # ── Main tick ────────────────────────────────────────────────────

    def _tick(self):
        now = datetime.now().strftime("%H:%M:%S")

        # 1. Refresh zones for all symbols
        for sym in self.symbols:
            self._refresh_zones(sym)

        # 2. Get all prices
        price_feeds: dict[str, tuple[float, float]] = {}
        for sym in self.symbols:
            try:
                bid, ask = _safe_get_current_price(sym)
                price_feeds[sym] = (bid, ask)
            except Exception:
                pass

        # 3. Manage open positions
        if self.trader.has_open_positions:
            self._manage_all_positions(price_feeds)
        self.trader.update_all_positions(price_feeds)

        # 4. Status line for open positions
        open_count = len(self.trader.account.positions)
        if open_count > 0:
            parts = []
            for pos in self.trader.account.positions:
                if pos.symbol in price_feeds:
                    bid, ask = price_feeds[pos.symbol]
                    if pos.signal == Signal.LONG:
                        pips = (bid - pos.entry_price) / pos.point_size
                    else:
                        pips = (pos.entry_price - ask) / pos.point_size
                    parts.append(f"#{pos.ticket} {pos.symbol} {pos.signal.value} "
                                 f"{pips:+.1f}p")
            print(f"[{now}] Open: {' | '.join(parts)} | "
                  f"Equity: ${self.trader.account.equity:.2f}")

        # 5. Search for new entries (if we have room)
        if open_count >= self.max_positions:
            if open_count > 0:
                return
            return

        # Which symbols already have open positions?
        symbols_with_positions = {
            pos.symbol for pos in self.trader.account.positions
        }

        scanned = []
        for sym in self.symbols:
            if sym in symbols_with_positions:
                continue
            if len(self.trader.account.positions) >= self.max_positions:
                break

            state = self.states[sym]
            if not state.zones:
                continue
            if sym not in price_feeds:
                continue

            bid, ask = price_feeds[sym]
            current_price = (bid + ask) / 2

            # Check if price is near any zone
            found_entry = False
            nearest_zone_dist = None
            for zone in state.zones:
                dist_to_zone = min(
                    abs(current_price - zone.upper),
                    abs(current_price - zone.lower),
                )
                if nearest_zone_dist is None or dist_to_zone < nearest_zone_dist:
                    nearest_zone_dist = dist_to_zone

                if not (zone.lower <= current_price <= zone.upper):
                    continue

                print(f"  [{sym}] Price {current_price:.5f} IN "
                      f"{zone.zone_type.value} zone "
                      f"[{zone.lower:.5f}–{zone.upper:.5f}]")

                tp_target = self._find_tp_target(state, zone)
                if tp_target is None:
                    print(f"    → No opposing zone for TP, skip")
                    continue

                try:
                    df_ltf = _safe_get_rates(sym, LTF_TIMEFRAME, LTF_BARS)
                except Exception:
                    continue

                setup = find_entry(df_ltf, zone, tp_target, state.point_size)
                if setup is None:
                    # Diagnostic: run entry steps manually to show reason
                    from bot.entry import _detect_exhaustion, _ltf_swings, _detect_structure_break
                    highs = df_ltf["high"].values
                    lows = df_ltf["low"].values

                    arrival_idx = None
                    for i in range(len(df_ltf)):
                        if zone.zone_type == ZoneType.SUPPLY and highs[i] >= zone.lower:
                            arrival_idx = i
                            break
                        if zone.zone_type == ZoneType.DEMAND and lows[i] <= zone.upper:
                            arrival_idx = i
                            break

                    if arrival_idx is None:
                        print(f"    → Price never entered zone on LTF")
                    else:
                        exh = _detect_exhaustion(df_ltf, zone, arrival_idx)
                        if not exh:
                            print(f"    → No exhaustion move (approach too slow/choppy)")
                        else:
                            sh_idx, sh_price, sl_idx, sl_price = _ltf_swings(df_ltf)
                            bos = _detect_structure_break(
                                df_ltf, zone, sh_idx, sh_price,
                                sl_idx, sl_price, arrival_idx
                            )
                            if bos is None:
                                print(f"    → Exhaustion OK, but no BOS (structure not broken)")
                            else:
                                print(f"    → Exhaustion OK, BOS OK, but R:R or SL filter rejected")
                    continue

                # Execute paper trade
                sl_distance = abs(setup.entry_price - setup.stop_loss)
                lot = calculate_lot_size(
                    account_balance=self.trader.account.balance,
                    risk_pct=self.risk_pct,
                    sl_distance=sl_distance,
                    point_value=10.0,
                    point_size=state.point_size,
                )

                entry_price = ask if setup.signal == Signal.LONG else bid

                pos = self.trader.open_position(
                    symbol=sym,
                    signal=setup.signal,
                    entry_price=entry_price,
                    stop_loss=setup.stop_loss,
                    take_profit=setup.take_profit,
                    lot_size=lot,
                    point_size=state.point_size,
                )
                # Pass structure data for trailing/breakeven
                pos.first_structure_level = setup.first_structure_level
                print(f"  R:R = {setup.rr_ratio} | Lot = {lot} | "
                      f"Exhaustion={'YES' if setup.exhaustion else 'NO'}")
                found_entry = True
                break

            if not found_entry:
                scanned.append(sym)

        if scanned and open_count == 0:
            print(f"[{now}] Scanned {len(scanned)} symbols — no entries | "
                  f"Balance: ${self.trader.account.balance:.2f}")

    # ── Position management ──────────────────────────────────────────

    def _manage_all_positions(self, price_feeds: dict[str, tuple[float, float]]):
        """
        Per-strategy position management:
        1. Breakeven: when price breaks the first local support/resistance level
        2. Trailing: move SL behind new swing extremes as trend develops
        """
        for pos in self.trader.account.positions:
            if pos.symbol not in price_feeds:
                continue
            bid, ask = price_feeds[pos.symbol]
            current_price = bid if pos.signal == Signal.SHORT else ask

            # ── 1. Breakeven on first structure level break ──────────
            if not pos.breakeven_applied and pos.first_structure_level is not None:
                if pos.signal == Signal.LONG and current_price > pos.first_structure_level:
                    self.trader.modify_sl(pos, pos.entry_price)
                    pos.breakeven_applied = True
                    print(f"  [STRAT] #{pos.ticket} {pos.symbol}: price broke "
                          f"resistance {pos.first_structure_level:.5f} → BE")
                elif pos.signal == Signal.SHORT and current_price < pos.first_structure_level:
                    self.trader.modify_sl(pos, pos.entry_price)
                    pos.breakeven_applied = True
                    print(f"  [STRAT] #{pos.ticket} {pos.symbol}: price broke "
                          f"support {pos.first_structure_level:.5f} → BE")

            # Fallback: if no structure level, use 1R as breakeven trigger
            if not pos.breakeven_applied and pos.first_structure_level is None:
                risk = abs(pos.entry_price - pos.stop_loss)
                if pos.signal == Signal.LONG:
                    profit = current_price - pos.entry_price
                else:
                    profit = pos.entry_price - current_price
                if risk > 0 and (profit / risk) >= BREAKEVEN_TRIGGER_RR:
                    self.trader.modify_sl(pos, pos.entry_price)
                    pos.breakeven_applied = True

            # ── 2. Trailing stop behind swing extremes ───────────────
            if TRAILING_STOP_ENABLED and pos.breakeven_applied:
                # Refresh LTF swings for this symbol to get new structure
                try:
                    df_ltf = _safe_get_rates(pos.symbol, LTF_TIMEFRAME, LTF_BARS)
                    from bot.entry import _ltf_swings
                    sh_idx, sh_price, sl_idx, sl_price = _ltf_swings(df_ltf)

                    if pos.signal == Signal.LONG:
                        # Trail behind the most recent swing low
                        recent_lows = [
                            p for idx, p in zip(sl_idx, sl_price)
                            if p > pos.stop_loss and p < current_price
                        ]
                        if recent_lows:
                            new_sl = max(recent_lows) - (SL_BUFFER_POINTS * pos.point_size)
                            if new_sl > pos.stop_loss:
                                self.trader.modify_sl(pos, round(new_sl, 5))
                    else:
                        # Trail behind the most recent swing high
                        recent_highs = [
                            p for idx, p in zip(sh_idx, sh_price)
                            if p < pos.stop_loss and p > current_price
                        ]
                        if recent_highs:
                            new_sl = min(recent_highs) + (SL_BUFFER_POINTS * pos.point_size)
                            if new_sl < pos.stop_loss:
                                self.trader.modify_sl(pos, round(new_sl, 5))
                except Exception:
                    # Fallback to fixed step if data unavailable
                    step = TRAILING_STEP_POINTS * pos.point_size
                    if pos.signal == Signal.LONG:
                        candidate = current_price - step
                        if candidate > pos.stop_loss:
                            self.trader.modify_sl(pos, round(candidate, 5))
                    else:
                        candidate = current_price + step
                        if candidate < pos.stop_loss:
                            self.trader.modify_sl(pos, round(candidate, 5))

    # ── TP target ────────────────────────────────────────────────────

    def _find_tp_target(self, state: SymbolState, active_zone: Zone) -> float | None:
        opposing = (
            ZoneType.DEMAND if active_zone.zone_type == ZoneType.SUPPLY
            else ZoneType.SUPPLY
        )
        candidates = [z for z in state.zones if z.zone_type == opposing]

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
