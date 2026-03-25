"""
Entry logic module — analyses the lower timeframe to find precise entries.

Steps:
1. Detect exhaustion move into the zone.
2. Wait for market structure break (BOS).
3. Determine entry price, stop-loss, and take-profit.
"""

from __future__ import annotations

import numpy as np
import pandas as pd
from dataclasses import dataclass
from enum import Enum

from bot.zones import Zone, ZoneType
from config.settings import (
    FRACTAL_PERIOD,
    EXHAUSTION_CANDLE_COUNT,
    EXHAUSTION_BODY_RATIO,
    EXHAUSTION_RETRACEMENT,
    STRUCTURE_BREAK_CONFIRM,
    SL_BUFFER_POINTS,
    MIN_RR_RATIO,
)


class Signal(Enum):
    LONG = "long"
    SHORT = "short"


@dataclass
class TradeSetup:
    signal: Signal
    entry_price: float
    stop_loss: float
    take_profit: float
    zone: Zone
    rr_ratio: float
    bar_index: int          # LTF bar index of the entry trigger


# ── LTF swing detection (fractals) ──────────────────────────────────────

def _ltf_swings(df: pd.DataFrame, period: int = FRACTAL_PERIOD):
    """
    Return arrays of swing-high and swing-low indices + prices on the LTF.
    Uses Williams-style fractals (N bars on each side).
    """
    highs = df["high"].values
    lows = df["low"].values
    n = len(df)

    sh_idx, sh_price = [], []
    sl_idx, sl_price = [], []

    for i in range(period, n - period):
        # Swing high
        is_sh = all(highs[i] > highs[i - j] and highs[i] > highs[i + j]
                     for j in range(1, period + 1))
        if is_sh:
            sh_idx.append(i)
            sh_price.append(highs[i])

        # Swing low
        is_sl = all(lows[i] < lows[i - j] and lows[i] < lows[i + j]
                     for j in range(1, period + 1))
        if is_sl:
            sl_idx.append(i)
            sl_price.append(lows[i])

    return sh_idx, sh_price, sl_idx, sl_price


# ── Exhaustion detection ─────────────────────────────────────────────────

def _detect_exhaustion(df: pd.DataFrame, zone: Zone, arrival_idx: int) -> bool:
    """
    Check if the price approached the zone with an exhaustion (climactic) move.

    Criteria:
    - Most recent N candles before zone touch have large body/range ratios.
    - Minimal retracement during the approach.
    """
    start = max(0, arrival_idx - EXHAUSTION_CANDLE_COUNT)
    window = df.iloc[start:arrival_idx]
    if len(window) < 2:
        return False

    opens = window["open"].values
    closes = window["close"].values
    highs = window["high"].values
    lows = window["low"].values

    body_ratios = []
    for i in range(len(window)):
        rng = highs[i] - lows[i]
        if rng == 0:
            continue
        body_ratios.append(abs(closes[i] - opens[i]) / rng)

    if not body_ratios:
        return False

    avg_body_ratio = np.mean(body_ratios)
    if avg_body_ratio < EXHAUSTION_BODY_RATIO:
        return False

    # Check retracement: price should move mostly in one direction
    total_move = abs(closes[-1] - opens[0])
    max_retrace = 0.0
    if zone.zone_type == ZoneType.SUPPLY:
        # Price moving up — retracement = any drop
        running_high = highs[0]
        for i in range(len(window)):
            running_high = max(running_high, highs[i])
            retrace = running_high - lows[i]
            max_retrace = max(max_retrace, retrace)
    else:
        # Price moving down — retracement = any rise
        running_low = lows[0]
        for i in range(len(window)):
            running_low = min(running_low, lows[i])
            retrace = highs[i] - running_low
            max_retrace = max(max_retrace, retrace)

    if total_move == 0:
        return False

    return (max_retrace / total_move) <= (1.0 + EXHAUSTION_RETRACEMENT)


# ── Market structure break detection ─────────────────────────────────────

def _detect_structure_break(
    df: pd.DataFrame,
    zone: Zone,
    sh_idx: list[int],
    sh_price: list[float],
    sl_idx: list[int],
    sl_price: list[float],
    arrival_idx: int,
) -> int | None:
    """
    After price enters the zone, detect a break of market structure (BOS).

    For SHORT (supply zone):
        - Micro-trend has HH/HL.
        - BOS = first LL (close below prior swing low).

    For LONG (demand zone):
        - Micro-trend has LL/LH.
        - BOS = first HH (close above prior swing high).

    Returns the bar index of the BOS candle, or None.
    """
    closes = df["close"].values

    if zone.zone_type == ZoneType.SUPPLY:
        # Find the two most recent swing lows after arrival
        recent_sl = [
            (idx, price) for idx, price in zip(sl_idx, sl_price)
            if idx > arrival_idx
        ]
        if len(recent_sl) < 2:
            return None

        # Check for Lower Low: second swing low < first swing low
        for i in range(1, len(recent_sl)):
            prev_sl_price = recent_sl[i - 1][1]
            curr_sl_idx = recent_sl[i][0]
            curr_sl_price = recent_sl[i][1]

            if curr_sl_price < prev_sl_price:
                # BOS confirmed — find the break candle
                if STRUCTURE_BREAK_CONFIRM:
                    # Need a candle that closes below the previous swing low
                    for j in range(recent_sl[i - 1][0] + 1, min(curr_sl_idx + FRACTAL_PERIOD + 1, len(df))):
                        if closes[j] < prev_sl_price:
                            return j
                else:
                    return curr_sl_idx
        return None

    else:  # DEMAND
        recent_sh = [
            (idx, price) for idx, price in zip(sh_idx, sh_price)
            if idx > arrival_idx
        ]
        if len(recent_sh) < 2:
            return None

        for i in range(1, len(recent_sh)):
            prev_sh_price = recent_sh[i - 1][1]
            curr_sh_idx = recent_sh[i][0]
            curr_sh_price = recent_sh[i][1]

            if curr_sh_price > prev_sh_price:
                if STRUCTURE_BREAK_CONFIRM:
                    for j in range(recent_sh[i - 1][0] + 1, min(curr_sh_idx + FRACTAL_PERIOD + 1, len(df))):
                        if closes[j] > prev_sh_price:
                            return j
                else:
                    return curr_sh_idx
        return None


# ── Public API ───────────────────────────────────────────────────────────

def find_entry(df_ltf: pd.DataFrame, zone: Zone,
               tp_target: float, point_size: float) -> TradeSetup | None:
    """
    Scan LTF data for a valid entry within the given zone.

    Parameters
    ----------
    df_ltf : LTF OHLCV DataFrame
    zone   : The HTF zone that price is currently inside
    tp_target : Take-profit price (next opposing zone or key level on HTF)
    point_size : Symbol point size (e.g. 0.00001 for 5-digit forex)

    Returns a TradeSetup or None if no valid entry found.
    """
    highs = df_ltf["high"].values
    lows = df_ltf["low"].values
    closes = df_ltf["close"].values

    # 1. Find when price first enters the zone
    arrival_idx = None
    for i in range(len(df_ltf)):
        if zone.zone_type == ZoneType.SUPPLY and highs[i] >= zone.lower:
            arrival_idx = i
            break
        if zone.zone_type == ZoneType.DEMAND and lows[i] <= zone.upper:
            arrival_idx = i
            break

    if arrival_idx is None:
        return None

    # 2. Check exhaustion (optional but improves win rate)
    is_exhaustion = _detect_exhaustion(df_ltf, zone, arrival_idx)

    # 3. Compute LTF swings
    sh_idx, sh_price, sl_idx, sl_price = _ltf_swings(df_ltf)

    # 4. Detect structure break
    bos_idx = _detect_structure_break(
        df_ltf, zone, sh_idx, sh_price, sl_idx, sl_price, arrival_idx
    )
    if bos_idx is None:
        return None

    # 5. Build trade setup
    entry_price = closes[bos_idx]
    buffer = SL_BUFFER_POINTS * point_size

    if zone.zone_type == ZoneType.SUPPLY:
        # SHORT
        # SL above the highest recent swing high inside the zone
        recent_sh_in_zone = [
            p for idx, p in zip(sh_idx, sh_price)
            if arrival_idx <= idx <= bos_idx
        ]
        sl_price_val = (max(recent_sh_in_zone) if recent_sh_in_zone
                        else zone.upper) + buffer
        signal = Signal.SHORT
        risk = sl_price_val - entry_price
        reward = entry_price - tp_target
    else:
        # LONG
        recent_sl_in_zone = [
            p for idx, p in zip(sl_idx, sl_price)
            if arrival_idx <= idx <= bos_idx
        ]
        sl_price_val = (min(recent_sl_in_zone) if recent_sl_in_zone
                        else zone.lower) - buffer
        signal = Signal.LONG
        risk = entry_price - sl_price_val
        reward = tp_target - entry_price

    if risk <= 0:
        return None

    rr = reward / risk
    if rr < MIN_RR_RATIO:
        return None

    return TradeSetup(
        signal=signal,
        entry_price=round(entry_price, 5),
        stop_loss=round(sl_price_val, 5),
        take_profit=round(tp_target, 5),
        zone=zone,
        rr_ratio=round(rr, 2),
        bar_index=bos_idx,
    )
