"""
Data provider — fetches real forex OHLCV data from Yahoo Finance.
No API keys, no MetaTrader 5 required.

Limitations:
  - M1  data: last 7 days
  - M15 data: last 60 days
"""

from __future__ import annotations

import yfinance as yf
import pandas as pd

# Yahoo Finance uses different ticker format for forex
_SYMBOL_MAP = {
    "EURUSD": "EURUSD=X",
    "GBPUSD": "GBPUSD=X",
    "USDJPY": "USDJPY=X",
    "USDCHF": "USDCHF=X",
    "AUDUSD": "AUDUSD=X",
    "NZDUSD": "NZDUSD=X",
    "USDCAD": "USDCAD=X",
    "EURGBP": "EURGBP=X",
    "EURJPY": "EURJPY=X",
    "GBPJPY": "GBPJPY=X",
    "XAUUSD": "GC=F",        # Gold
    "XAGUSD": "SI=F",        # Silver
}

_TF_MAP = {
    "M1": {"interval": "1m", "period": "5d"},
    "M5": {"interval": "5m", "period": "30d"},
    "M15": {"interval": "15m", "period": "60d"},
    "M30": {"interval": "30m", "period": "60d"},
    "H1": {"interval": "1h", "period": "60d"},
    "H4": {"interval": "1h", "period": "60d"},   # yfinance has no 4h; use 1h
    "D1": {"interval": "1d", "period": "365d"},
}

# Default point sizes for common forex pairs
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
    "XAGUSD": 0.001,
}


def get_rates(symbol: str, timeframe: str, count: int) -> pd.DataFrame:
    """
    Fetch OHLCV data from Yahoo Finance.

    Returns DataFrame with columns:
        time, open, high, low, close, tick_volume
    """
    yf_symbol = _SYMBOL_MAP.get(symbol, f"{symbol}=X")
    tf_params = _TF_MAP.get(timeframe)
    if tf_params is None:
        raise ValueError(f"Unknown timeframe: {timeframe}")

    ticker = yf.Ticker(yf_symbol)
    df = ticker.history(
        interval=tf_params["interval"],
        period=tf_params["period"],
    )

    if df.empty:
        raise RuntimeError(f"No data received for {symbol} ({yf_symbol}) {timeframe}")

    df = df.reset_index()

    # Normalize column names
    rename = {}
    for col in df.columns:
        col_lower = col.lower()
        if col_lower in ("datetime", "date"):
            rename[col] = "time"
        elif col_lower == "open":
            rename[col] = "open"
        elif col_lower == "high":
            rename[col] = "high"
        elif col_lower == "low":
            rename[col] = "low"
        elif col_lower == "close":
            rename[col] = "close"
        elif col_lower == "volume":
            rename[col] = "tick_volume"

    df = df.rename(columns=rename)

    required = ["time", "open", "high", "low", "close"]
    for col in required:
        if col not in df.columns:
            raise RuntimeError(f"Missing column {col} in data for {symbol}")

    if "tick_volume" not in df.columns:
        df["tick_volume"] = 0

    df["time"] = pd.to_datetime(df["time"])
    df = df[["time", "open", "high", "low", "close", "tick_volume"]]

    # Trim to requested count
    if len(df) > count:
        df = df.tail(count).reset_index(drop=True)

    return df


def get_point_size(symbol: str) -> float:
    """Return the point size for a symbol."""
    return _POINT_SIZES.get(symbol, 0.00001)


def get_current_price(symbol: str) -> tuple[float, float]:
    """
    Get current bid/ask approximation.
    Yahoo Finance doesn't provide bid/ask, so we use last close
    with a small synthetic spread.
    """
    yf_symbol = _SYMBOL_MAP.get(symbol, f"{symbol}=X")
    ticker = yf.Ticker(yf_symbol)
    data = ticker.history(interval="1m", period="1d")

    if data.empty:
        raise RuntimeError(f"Cannot get current price for {symbol}")

    last_close = data["Close"].iloc[-1]
    point = get_point_size(symbol)
    spread = point * 15  # ~1.5 pip spread

    bid = last_close
    ask = last_close + spread
    return bid, ask
