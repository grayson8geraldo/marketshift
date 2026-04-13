"""
Simulated data provider — generates realistic forex price action.

Used as a fallback when yfinance / MT5 are unavailable.
Produces live-updating candles by combining:
  - Random walk with mean reversion
  - Variable volatility (session simulation)
  - Realistic wick/body ratios
  - Clear swing structure for zone detection

Every call to get_rates() appends new bars based on real elapsed time,
so the engine can run a genuine paper-trading loop.
"""

from __future__ import annotations

import time
import numpy as np
import pandas as pd
from datetime import datetime, timedelta
from dataclasses import dataclass


@dataclass
class _SimState:
    """Mutable state for the simulation."""
    price: float
    last_update: float        # time.time() of last bar
    bars: list[dict]
    volatility: float
    trend_bias: float
    rng: np.random.RandomState


# One simulator per (symbol, timeframe)
_sims: dict[tuple[str, str], _SimState] = {}

_INITIAL_PRICES = {
    "EURUSD": 1.0850,
    "GBPUSD": 1.2720,
    "USDJPY": 149.50,
    "AUDUSD": 0.6650,
    "USDCAD": 1.3680,
    "EURGBP": 0.8550,
    "EURJPY": 162.20,
    "GBPJPY": 190.10,
    "XAUUSD": 2350.00,
}

_POINT_SIZES = {
    "EURUSD": 0.00001,
    "GBPUSD": 0.00001,
    "USDJPY": 0.001,
    "USDCHF": 0.00001,
    "AUDUSD": 0.00001,
    "NZDUSD": 0.00001,
    "USDCAD": 0.00001,
    "EURGBP": 0.00001,
    "EURJPY": 0.001,
    "GBPJPY": 0.001,
    "XAUUSD": 0.01,
}

_TF_SECONDS = {
    "M1": 60,
    "M5": 300,
    "M15": 900,
    "M30": 1800,
    "H1": 3600,
    "H4": 14400,
    "D1": 86400,
}

_VOLATILITY = {
    "EURUSD": 0.00015,
    "GBPUSD": 0.00018,
    "USDJPY": 0.015,
    "AUDUSD": 0.00016,
    "USDCAD": 0.00014,
    "EURGBP": 0.00010,
    "EURJPY": 0.018,
    "GBPJPY": 0.022,
    "XAUUSD": 0.50,
}


def _get_sim(symbol: str, timeframe: str, count: int) -> _SimState:
    """Get or create simulator state, generating historical bars if needed."""
    key = (symbol, timeframe)
    if key in _sims:
        return _sims[key]

    initial_price = _INITIAL_PRICES.get(symbol, 1.0000)
    vol = _VOLATILITY.get(symbol, 0.00015)
    tf_sec = _TF_SECONDS.get(timeframe, 60)

    rng = np.random.RandomState(hash(symbol + timeframe) % (2**31))

    # Generate initial history
    state = _SimState(
        price=initial_price,
        last_update=time.time(),
        bars=[],
        volatility=vol,
        trend_bias=0.0,
        rng=rng,
    )

    # Generate `count` historical bars
    now = datetime.now()
    start_time = now - timedelta(seconds=tf_sec * count)

    for i in range(count):
        bar_time = start_time + timedelta(seconds=tf_sec * i)
        _generate_bar(state, bar_time, tf_sec)

    _sims[key] = state
    return state


def _generate_bar(state: _SimState, bar_time: datetime, tf_seconds: int) -> dict:
    """Generate a single OHLCV bar with realistic price action."""
    rng = state.rng
    vol = state.volatility

    # Scale volatility by timeframe (sqrt of time)
    tf_scale = (tf_seconds / 60) ** 0.5

    # Mean reversion: slight pull toward initial price
    mean_price = _INITIAL_PRICES.get("EURUSD", state.price)
    for sym, p in _INITIAL_PRICES.items():
        if abs(state.price - p) / p < 0.1:
            mean_price = p
            break

    reversion = (mean_price - state.price) * 0.001

    # Trend bias shifts slowly
    state.trend_bias += rng.normal(0, vol * 0.3)
    state.trend_bias *= 0.95  # decay

    # Price change
    delta = (
        rng.normal(0, vol * tf_scale)
        + state.trend_bias * tf_scale * 0.1
        + reversion
    )

    open_price = state.price
    close_price = open_price + delta

    # Generate realistic high/low (wicks)
    body = abs(close_price - open_price)
    upper_wick = abs(rng.normal(0, vol * tf_scale * 0.4))
    lower_wick = abs(rng.normal(0, vol * tf_scale * 0.4))

    high = max(open_price, close_price) + upper_wick
    low = min(open_price, close_price) - lower_wick

    # Occasionally create impulse candles (big body, small wicks)
    if rng.random() < 0.08:
        impulse = rng.normal(0, vol * tf_scale * 3)
        close_price = open_price + impulse
        high = max(open_price, close_price) + abs(impulse) * 0.1
        low = min(open_price, close_price) - abs(impulse) * 0.1

    # Occasionally create rejection candles (small body, big wick)
    if rng.random() < 0.05:
        direction = rng.choice([-1, 1])
        wick = vol * tf_scale * 4
        if direction > 0:
            high = open_price + wick
            close_price = open_price + wick * 0.1
        else:
            low = open_price - wick
            close_price = open_price - wick * 0.1

    state.price = close_price
    volume = int(abs(rng.normal(1000, 500)) * tf_scale)

    bar = {
        "time": bar_time,
        "open": round(open_price, 5),
        "high": round(high, 5),
        "low": round(low, 5),
        "close": round(close_price, 5),
        "tick_volume": volume,
    }
    state.bars.append(bar)
    return bar


def get_rates(symbol: str, timeframe: str, count: int) -> pd.DataFrame:
    """
    Get OHLCV data — generates new bars based on elapsed real time.
    """
    tf_sec = _TF_SECONDS.get(timeframe)
    if tf_sec is None:
        raise ValueError(f"Unknown timeframe: {timeframe}")

    state = _get_sim(symbol, timeframe, count)

    # Generate new bars for elapsed time
    now = time.time()
    elapsed = now - state.last_update
    new_bars = int(elapsed / tf_sec)

    if new_bars > 0:
        last_bar_time = state.bars[-1]["time"] if state.bars else datetime.now()
        for i in range(1, new_bars + 1):
            bar_time = last_bar_time + timedelta(seconds=tf_sec * i)
            _generate_bar(state, bar_time, tf_sec)
        state.last_update = now

    # Return last `count` bars
    bars = state.bars[-count:]
    df = pd.DataFrame(bars)
    df["time"] = pd.to_datetime(df["time"])
    return df.reset_index(drop=True)


def get_point_size(symbol: str) -> float:
    return _POINT_SIZES.get(symbol, 0.00001)


def get_current_price(symbol: str) -> tuple[float, float]:
    """Get current simulated bid/ask."""
    state = _get_sim(symbol, "M1", 200)
    bid = state.price
    spread = get_point_size(symbol) * 15
    ask = bid + spread
    return round(bid, 5), round(ask, 5)
