"""
MarketShift Forex Trading Bot
==============================
Entry point. Run: python main.py [--symbol EURUSD]
"""

import argparse
import sys

from bot.engine import TradingEngine
from config.settings import SYMBOL


def main():
    parser = argparse.ArgumentParser(description="MarketShift Forex Trading Bot")
    parser.add_argument("--symbol", default=SYMBOL, help="Trading symbol (default: %(default)s)")
    args = parser.parse_args()

    print("=" * 60)
    print("  MarketShift Forex Trading Bot")
    print(f"  Symbol: {args.symbol}")
    print("=" * 60)

    engine = TradingEngine(symbol=args.symbol)
    engine.start()


if __name__ == "__main__":
    main()
