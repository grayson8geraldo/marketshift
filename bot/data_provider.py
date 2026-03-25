"""
Data provider — fetches OHLCV data from MetaTrader 5.
"""

try:
    import MetaTrader5 as mt5
except ImportError:
    mt5 = None  # MT5 is Windows-only; allows testing on other platforms
import pandas as pd
import numpy as np
from datetime import datetime

_TF_MAP = {
    "M1": mt5.TIMEFRAME_M1,
    "M5": mt5.TIMEFRAME_M5,
    "M15": mt5.TIMEFRAME_M15,
    "M30": mt5.TIMEFRAME_M30,
    "H1": mt5.TIMEFRAME_H1,
    "H4": mt5.TIMEFRAME_H4,
    "D1": mt5.TIMEFRAME_D1,
}


def init_mt5() -> bool:
    """Initialize MT5 connection. Returns True on success."""
    if not mt5.initialize():
        print(f"MT5 initialize failed: {mt5.last_error()}")
        return False
    return True


def shutdown_mt5():
    mt5.shutdown()


def get_rates(symbol: str, timeframe: str, count: int) -> pd.DataFrame:
    """
    Fetch OHLCV rates from MT5.

    Returns DataFrame with columns:
        time, open, high, low, close, tick_volume, spread
    Indexed by integer; `time` is a datetime column.
    """
    tf = _TF_MAP.get(timeframe)
    if tf is None:
        raise ValueError(f"Unknown timeframe: {timeframe}")

    rates = mt5.copy_rates_from_pos(symbol, tf, 0, count)
    if rates is None or len(rates) == 0:
        raise RuntimeError(
            f"Failed to get rates for {symbol} {timeframe}: {mt5.last_error()}"
        )

    df = pd.DataFrame(rates)
    df["time"] = pd.to_datetime(df["time"], unit="s")
    return df


def get_symbol_info(symbol: str):
    """Return MT5 symbol info object."""
    info = mt5.symbol_info(symbol)
    if info is None:
        raise RuntimeError(f"Symbol {symbol} not found")
    return info


def get_account_info():
    """Return MT5 account info object."""
    info = mt5.account_info()
    if info is None:
        raise RuntimeError("Failed to get account info")
    return info
