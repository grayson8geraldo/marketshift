"""
Zone detection module — finds supply/demand zones on the higher timeframe.

Algorithm:
1. Identify swing highs/lows using a ZigZag-like fractal approach.
2. Cluster nearby swings into rectangular zones (wick-to-body).
3. Score zones by touch count, impulse strength, and round-number proximity.
4. Filter: keep only extreme zones (top/bottom percentile of the range).
"""

from __future__ import annotations

import numpy as np
import pandas as pd
from dataclasses import dataclass, field
from enum import Enum
from config.settings import (
    ZIGZAG_DEPTH,
    ZIGZAG_BACKSTEP,
    ZONE_TOUCH_MIN,
    ZONE_PROXIMITY_PCT,
    EXTREMUM_PERCENTILE,
    IMPULSE_MIN_BODY_RATIO,
    IMPULSE_MIN_CANDLES,
    IMPULSE_MIN_MOVE_PCT,
    ROUND_NUMBER_WEIGHT,
    ROUND_NUMBER_TOLERANCE,
)


class ZoneType(Enum):
    SUPPLY = "supply"   # resistance — look for shorts
    DEMAND = "demand"   # support   — look for longs


@dataclass
class Zone:
    zone_type: ZoneType
    upper: float            # top of zone  (wick extreme)
    lower: float            # bottom of zone (body edge)
    touches: int = 0
    impulse_score: float = 0.0
    round_number: bool = False
    score: float = 0.0
    origin_idx: int = 0     # bar index where the zone was first formed

    @property
    def mid(self) -> float:
        return (self.upper + self.lower) / 2

    @property
    def width(self) -> float:
        return self.upper - self.lower


# ── Swing detection (fractal / ZigZag) ──────────────────────────────────

def find_swings(df: pd.DataFrame, depth: int = ZIGZAG_DEPTH,
                backstep: int = ZIGZAG_BACKSTEP) -> pd.DataFrame:
    """
    Identify swing highs and swing lows using a fractal approach.

    Returns a copy of `df` with extra columns:
        swing_high (bool), swing_low (bool),
        swing_high_price (float | NaN), swing_low_price (float | NaN)
    """
    n = len(df)
    half = depth // 2

    swing_high = np.zeros(n, dtype=bool)
    swing_low = np.zeros(n, dtype=bool)
    swing_high_price = np.full(n, np.nan)
    swing_low_price = np.full(n, np.nan)

    highs = df["high"].values
    lows = df["low"].values

    for i in range(half, n - half):
        # Check swing high
        is_sh = True
        for j in range(1, half + 1):
            if highs[i] <= highs[i - j] or highs[i] <= highs[i + j]:
                is_sh = False
                break
        if is_sh:
            # Backstep: suppress if a higher swing high exists within backstep bars
            suppress = False
            for b in range(1, backstep + 1):
                if i - b >= 0 and swing_high[i - b] and highs[i - b] >= highs[i]:
                    suppress = True
                    break
            if not suppress:
                swing_high[i] = True
                swing_high_price[i] = highs[i]

        # Check swing low
        is_sl = True
        for j in range(1, half + 1):
            if lows[i] >= lows[i - j] or lows[i] >= lows[i + j]:
                is_sl = False
                break
        if is_sl:
            suppress = False
            for b in range(1, backstep + 1):
                if i - b >= 0 and swing_low[i - b] and lows[i - b] <= lows[i]:
                    suppress = True
                    break
            if not suppress:
                swing_low[i] = True
                swing_low_price[i] = lows[i]

    out = df.copy()
    out["swing_high"] = swing_high
    out["swing_low"] = swing_low
    out["swing_high_price"] = swing_high_price
    out["swing_low_price"] = swing_low_price
    return out


# ── Zone building ────────────────────────────────────────────────────────

def _build_raw_zone(df: pd.DataFrame, idx: int, zone_type: ZoneType) -> Zone:
    """Build a zone rectangle from a swing point (wick → body)."""
    row = df.iloc[idx]
    if zone_type == ZoneType.SUPPLY:
        wick_extreme = row["high"]
        body_edge = max(row["open"], row["close"])
        return Zone(
            zone_type=ZoneType.SUPPLY,
            upper=wick_extreme,
            lower=body_edge,
            origin_idx=idx,
        )
    else:
        wick_extreme = row["low"]
        body_edge = min(row["open"], row["close"])
        return Zone(
            zone_type=ZoneType.DEMAND,
            upper=body_edge,
            lower=wick_extreme,
            origin_idx=idx,
        )


def _merge_nearby_zones(zones: list[Zone], proximity: float) -> list[Zone]:
    """Merge zones of the same type whose midpoints are within `proximity`."""
    if not zones:
        return zones

    merged: list[Zone] = []
    used = set()

    for i, z1 in enumerate(zones):
        if i in used:
            continue
        group = [z1]
        for j in range(i + 1, len(zones)):
            if j in used:
                continue
            z2 = zones[j]
            if z1.zone_type != z2.zone_type:
                continue
            if abs(z1.mid - z2.mid) / max(z1.mid, 1e-10) <= proximity:
                group.append(z2)
                used.add(j)

        # Merge group
        upper = max(z.upper for z in group)
        lower = min(z.lower for z in group)
        combined = Zone(
            zone_type=z1.zone_type,
            upper=upper,
            lower=lower,
            touches=len(group),
            origin_idx=min(z.origin_idx for z in group),
        )
        merged.append(combined)
        used.add(i)

    return merged


# ── Touch counting ───────────────────────────────────────────────────────

def _count_touches(zones: list[Zone], df: pd.DataFrame) -> None:
    """Count how many times price revisited each zone after formation."""
    highs = df["high"].values
    lows = df["low"].values

    for zone in zones:
        count = 0
        for i in range(zone.origin_idx + 1, len(df)):
            if zone.zone_type == ZoneType.SUPPLY:
                if highs[i] >= zone.lower and highs[i] <= zone.upper:
                    count += 1
            else:
                if lows[i] <= zone.upper and lows[i] >= zone.lower:
                    count += 1
        zone.touches = max(zone.touches, count)


# ── Impulse scoring ──────────────────────────────────────────────────────

def _score_impulse(zones: list[Zone], df: pd.DataFrame) -> None:
    """
    Score the impulse move away from each zone.
    A strong zone produces a sharp move with large-bodied candles.
    """
    opens = df["open"].values
    closes = df["close"].values
    highs = df["high"].values
    lows = df["low"].values

    for zone in zones:
        idx = zone.origin_idx
        direction = -1 if zone.zone_type == ZoneType.SUPPLY else 1

        impulse_candles = 0
        total_move = 0.0
        start_price = zone.mid

        for i in range(idx + 1, min(idx + 1 + IMPULSE_MIN_CANDLES + 5, len(df))):
            body = abs(closes[i] - opens[i])
            rng = highs[i] - lows[i]
            if rng == 0:
                continue

            body_ratio = body / rng
            move_dir = closes[i] - opens[i]

            if body_ratio >= IMPULSE_MIN_BODY_RATIO:
                if (direction == 1 and move_dir > 0) or (direction == -1 and move_dir < 0):
                    impulse_candles += 1

            total_move = abs(closes[i] - start_price)

        move_pct = total_move / max(start_price, 1e-10)
        zone.impulse_score = (
            min(impulse_candles / IMPULSE_MIN_CANDLES, 2.0)
            * min(move_pct / IMPULSE_MIN_MOVE_PCT, 2.0)
        )


# ── Round-number detection ───────────────────────────────────────────────

def _is_round_number(price: float, tolerance: float = ROUND_NUMBER_TOLERANCE) -> bool:
    """
    Check whether `price` is near a psychologically significant round number.
    Works for forex pairs (e.g. 1.0800, 1.1000) and indices (7000, 7500).
    """
    if price < 10:
        # Forex-style: check 0.01 (100 pip) and 0.005 (50 pip) levels
        mod_100 = price % 0.01
        near_100 = min(mod_100, 0.01 - mod_100) / price < tolerance
        mod_50 = price % 0.005
        near_50 = min(mod_50, 0.005 - mod_50) / price < tolerance
        return near_100 or near_50
    else:
        # Index/crypto-style: check nearest 100 and 500
        for step in (100, 500, 1000):
            mod = price % step
            if min(mod, step - mod) / price < tolerance:
                return True
        return False


def _apply_round_numbers(zones: list[Zone]) -> None:
    for zone in zones:
        zone.round_number = _is_round_number(zone.mid)


# ── Extremum filter ──────────────────────────────────────────────────────

def _filter_extremes(zones: list[Zone], df: pd.DataFrame,
                     pct: float = EXTREMUM_PERCENTILE) -> list[Zone]:
    """Keep only zones that sit in the top/bottom `pct`% of the price range."""
    price_min = df["low"].min()
    price_max = df["high"].max()
    total_range = price_max - price_min
    if total_range == 0:
        return zones

    lower_bound = price_min + total_range * (pct / 100)
    upper_bound = price_max - total_range * (pct / 100)

    return [
        z for z in zones
        if (z.zone_type == ZoneType.SUPPLY and z.mid >= upper_bound)
        or (z.zone_type == ZoneType.DEMAND and z.mid <= lower_bound)
    ]


# ── Final scoring ────────────────────────────────────────────────────────

def _compute_scores(zones: list[Zone]) -> None:
    for zone in zones:
        score = 1.0
        # Touch bonus: more touches = stronger zone
        score *= min(zone.touches, 5) / ZONE_TOUCH_MIN
        # Impulse bonus
        score *= max(zone.impulse_score, 0.1)
        # Round-number bonus
        if zone.round_number:
            score *= ROUND_NUMBER_WEIGHT
        zone.score = round(score, 3)


# ── Public API ───────────────────────────────────────────────────────────

def detect_zones(df: pd.DataFrame) -> list[Zone]:
    """
    Main entry point: detect and score supply/demand zones on an HTF DataFrame.

    Returns zones sorted by score descending.
    """
    swings = find_swings(df)

    raw_zones: list[Zone] = []

    # Build supply zones from swing highs
    sh_indices = swings.index[swings["swing_high"]].tolist()
    for idx in sh_indices:
        raw_zones.append(_build_raw_zone(swings, idx, ZoneType.SUPPLY))

    # Build demand zones from swing lows
    sl_indices = swings.index[swings["swing_low"]].tolist()
    for idx in sl_indices:
        raw_zones.append(_build_raw_zone(swings, idx, ZoneType.DEMAND))

    # Merge nearby zones
    zones = _merge_nearby_zones(raw_zones, ZONE_PROXIMITY_PCT)

    # Score components
    _count_touches(zones, df)
    _score_impulse(zones, df)
    _apply_round_numbers(zones)

    # Keep only extreme zones
    zones = _filter_extremes(zones, df)

    # Filter by minimum touches
    zones = [z for z in zones if z.touches >= ZONE_TOUCH_MIN]

    # Compute final score
    _compute_scores(zones)

    # Sort best first
    zones.sort(key=lambda z: z.score, reverse=True)
    return zones
