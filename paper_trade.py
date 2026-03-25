"""
MarketShift — Paper Trading Mode
=================================
Real market data + virtual balance. No MetaTrader 5 needed.

Usage:
    python paper_trade.py
    python paper_trade.py --symbol GBPUSD --balance 500 --risk 5
    python paper_trade.py --symbol EURUSD --balance 200 --risk 3 --interval 60
"""

import argparse

from bot.engine_paper import PaperTradingEngine


def main():
    parser = argparse.ArgumentParser(
        description="MarketShift — Paper Trading with Real Data"
    )
    parser.add_argument(
        "--symbol", default="EURUSD",
        help="Forex pair (default: EURUSD). Supported: EURUSD, GBPUSD, USDJPY, "
             "AUDUSD, NZDUSD, USDCAD, EURGBP, EURJPY, GBPJPY, XAUUSD"
    )
    parser.add_argument(
        "--balance", type=float, default=200.0,
        help="Virtual starting balance in USD (default: 200)"
    )
    parser.add_argument(
        "--risk", type=float, default=3.0,
        help="Risk per trade in %% (default: 3.0 — aggressive for small accounts)"
    )
    parser.add_argument(
        "--interval", type=int, default=30,
        help="Poll interval in seconds (default: 30)"
    )
    args = parser.parse_args()

    engine = PaperTradingEngine(
        symbol=args.symbol,
        balance=args.balance,
        risk_pct=args.risk,
        poll_interval=args.interval,
    )
    engine.start()


if __name__ == "__main__":
    main()
