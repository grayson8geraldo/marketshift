"""
MarketShift — Paper Trading Mode (Multi-Symbol)
=================================================
Real market data + virtual balance. No MetaTrader 5 needed.

Usage:
    python paper_trade.py                           # All 11 forex pairs
    python paper_trade.py --symbols EURUSD GBPUSD   # Specific pairs
    python paper_trade.py --risk 5 --balance 200    # Custom risk
    python paper_trade.py --symbols ALL              # Explicit all pairs
"""

import argparse

from bot.engine_paper import PaperTradingEngine, ALL_SYMBOLS


def main():
    parser = argparse.ArgumentParser(
        description="MarketShift — Multi-Symbol Paper Trading with Real Data"
    )
    parser.add_argument(
        "--symbols", nargs="+", default=None,
        help=f"Forex pairs to trade (default: all). "
             f"Available: {', '.join(ALL_SYMBOLS)}"
    )
    parser.add_argument(
        "--balance", type=float, default=200.0,
        help="Virtual starting balance in USD (default: 200)"
    )
    parser.add_argument(
        "--risk", type=float, default=3.0,
        help="Risk per trade in %% (default: 3.0)"
    )
    parser.add_argument(
        "--max-positions", type=int, default=3,
        help="Max simultaneous open positions (default: 3)"
    )
    parser.add_argument(
        "--interval", type=int, default=30,
        help="Poll interval in seconds (default: 30)"
    )
    args = parser.parse_args()

    # Resolve symbols
    symbols = None  # None = all
    if args.symbols:
        if args.symbols == ["ALL"]:
            symbols = None
        else:
            symbols = [s.upper() for s in args.symbols]
            invalid = [s for s in symbols if s not in ALL_SYMBOLS]
            if invalid:
                parser.error(
                    f"Unknown symbols: {', '.join(invalid)}. "
                    f"Available: {', '.join(ALL_SYMBOLS)}"
                )

    engine = PaperTradingEngine(
        symbols=symbols,
        balance=args.balance,
        risk_pct=args.risk,
        poll_interval=args.interval,
        max_positions=args.max_positions,
    )
    engine.start()


if __name__ == "__main__":
    main()
