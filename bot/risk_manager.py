"""
Risk management module — position sizing, stop management, trailing stop.
"""

from __future__ import annotations

try:
    import MetaTrader5 as mt5
except ImportError:
    mt5 = None  # MT5 is Windows-only; allows testing on other platforms
from dataclasses import dataclass

from bot.entry import TradeSetup, Signal
from config.settings import (
    RISK_PER_TRADE_PCT,
    LOT_SIZE_FIXED,
    MAGIC_NUMBER,
    MAX_SLIPPAGE,
    BREAKEVEN_TRIGGER_RR,
    TRAILING_STOP_ENABLED,
    TRAILING_STEP_POINTS,
)


@dataclass
class OpenPosition:
    ticket: int
    signal: Signal
    entry_price: float
    stop_loss: float
    take_profit: float
    lot_size: float
    breakeven_applied: bool = False


# ── Lot calculation ──────────────────────────────────────────────────────

def calculate_lot_size(
    account_balance: float,
    risk_pct: float,
    sl_distance: float,
    point_value: float,
    point_size: float,
    min_lot: float = 0.01,
    max_lot: float = 100.0,
    lot_step: float = 0.01,
) -> float:
    """
    Calculate lot size based on fixed-percentage risk.

    risk_amount = balance * risk_pct / 100
    lot = risk_amount / (sl_distance_points * point_value)
    """
    if LOT_SIZE_FIXED is not None:
        return LOT_SIZE_FIXED

    risk_amount = account_balance * risk_pct / 100.0
    sl_points = sl_distance / point_size
    if sl_points <= 0 or point_value <= 0:
        return min_lot

    lot = risk_amount / (sl_points * point_value)

    # Round to nearest lot_step
    lot = max(min_lot, min(max_lot, round(lot / lot_step) * lot_step))
    return round(lot, 2)


# ── Order execution ──────────────────────────────────────────────────────

def open_trade(setup: TradeSetup, symbol: str, lot_size: float) -> OpenPosition | None:
    """Send a market order to MT5 and return an OpenPosition."""
    order_type = mt5.ORDER_TYPE_SELL if setup.signal == Signal.SHORT else mt5.ORDER_TYPE_BUY

    tick = mt5.symbol_info_tick(symbol)
    if tick is None:
        print(f"[RISK] Cannot get tick for {symbol}")
        return None

    price = tick.bid if setup.signal == Signal.SHORT else tick.ask

    request = {
        "action": mt5.TRADE_ACTION_DEAL,
        "symbol": symbol,
        "volume": lot_size,
        "type": order_type,
        "price": price,
        "sl": setup.stop_loss,
        "tp": setup.take_profit,
        "deviation": MAX_SLIPPAGE,
        "magic": MAGIC_NUMBER,
        "comment": f"MarketShift {setup.signal.value}",
        "type_time": mt5.ORDER_TIME_GTC,
        "type_filling": mt5.ORDER_FILLING_IOC,
    }

    result = mt5.order_send(request)
    if result is None or result.retcode != mt5.TRADE_RETCODE_DONE:
        retcode = result.retcode if result else "None"
        print(f"[RISK] Order failed: retcode={retcode}")
        return None

    print(f"[RISK] Order placed: ticket={result.order}, {setup.signal.value} "
          f"{lot_size} lots @ {price}, SL={setup.stop_loss}, TP={setup.take_profit}")

    return OpenPosition(
        ticket=result.order,
        signal=setup.signal,
        entry_price=price,
        stop_loss=setup.stop_loss,
        take_profit=setup.take_profit,
        lot_size=lot_size,
    )


# ── Stop-loss management ─────────────────────────────────────────────────

def manage_position(pos: OpenPosition, symbol: str, point_size: float) -> bool:
    """
    Manage an open position: breakeven move + trailing stop.

    Returns True if position is still open, False if it was closed / invalid.
    """
    # Check if position still exists
    mt5_pos = mt5.positions_get(ticket=pos.ticket)
    if not mt5_pos:
        return False

    current_pos = mt5_pos[0]
    tick = mt5.symbol_info_tick(symbol)
    if tick is None:
        return True

    current_price = tick.bid if pos.signal == Signal.SHORT else tick.ask
    new_sl = pos.stop_loss

    # ── 1. Breakeven ─────────────────────────────────────────────────
    if not pos.breakeven_applied:
        risk = abs(pos.entry_price - pos.stop_loss)
        if pos.signal == Signal.LONG:
            profit = current_price - pos.entry_price
        else:
            profit = pos.entry_price - current_price

        if risk > 0 and (profit / risk) >= BREAKEVEN_TRIGGER_RR:
            new_sl = pos.entry_price
            pos.breakeven_applied = True
            print(f"[RISK] Ticket {pos.ticket}: moved SL to breakeven @ {new_sl}")

    # ── 2. Trailing stop ─────────────────────────────────────────────
    if TRAILING_STOP_ENABLED and pos.breakeven_applied:
        step = TRAILING_STEP_POINTS * point_size

        if pos.signal == Signal.LONG:
            candidate_sl = current_price - step
            if candidate_sl > pos.stop_loss:
                new_sl = candidate_sl
        else:
            candidate_sl = current_price + step
            if candidate_sl < pos.stop_loss:
                new_sl = candidate_sl

    # ── 3. Modify if needed ──────────────────────────────────────────
    if abs(new_sl - pos.stop_loss) > point_size:
        request = {
            "action": mt5.TRADE_ACTION_SLTP,
            "position": pos.ticket,
            "symbol": symbol,
            "sl": round(new_sl, 5),
            "tp": pos.take_profit,
            "magic": MAGIC_NUMBER,
        }
        result = mt5.order_send(request)
        if result and result.retcode == mt5.TRADE_RETCODE_DONE:
            pos.stop_loss = round(new_sl, 5)
            print(f"[RISK] Ticket {pos.ticket}: SL updated to {pos.stop_loss}")
        else:
            retcode = result.retcode if result else "None"
            print(f"[RISK] SL modify failed: retcode={retcode}")

    return True
