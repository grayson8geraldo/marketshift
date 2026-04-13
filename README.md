# MarketShift — Forex Trading Bot

Supply/demand zone trading bot with paper trading mode.

## Strategy

1. **Zone Detection (HTF M15)** — Finds supply/demand zones at price extremes using fractal swing detection. Zones are scored by touch count, impulse strength, and round-number proximity.
2. **Entry Logic (LTF M1)** — When price enters a zone, detects exhaustion moves and waits for market structure break (BOS) before entering.
3. **Risk Management** — Dynamic lot sizing, breakeven at 1R, trailing stop, TP at next opposing zone. Minimum 2:1 R:R.

## Quick Start — Paper Trading

No MetaTrader 5 needed. Works on any OS.

```bash
pip install -r requirements.txt

# Default: $200 balance, 3% risk, EURUSD
python paper_trade.py

# Custom settings
python paper_trade.py --symbol GBPUSD --balance 500 --risk 5 --interval 60
```

Data sources (auto-selected):
- **Yahoo Finance** — real live forex data (when internet is available)
- **Built-in simulator** — realistic generated price action (works offline)

Press `Ctrl+C` to stop and see the full trade summary.

## Live Trading (MT5)

For live/demo trading via MetaTrader 5 (Windows only):

```bash
pip install MetaTrader5
python main.py --symbol EURUSD
```

## Project Structure

```
paper_trade.py              — Paper trading entry point (no MT5)
main.py                     — Live trading entry point (MT5)
bot/
  zones.py                  — HTF zone detection, scoring, filtering
  entry.py                  — LTF exhaustion detection, structure break
  risk_manager.py           — Lot sizing, SL/TP management
  paper_trader.py           — Paper trading simulator (virtual balance)
  engine_paper.py           — Paper trading engine
  engine.py                 — Live trading engine (MT5)
  data_provider_yfinance.py — Yahoo Finance data provider
  data_provider_sim.py      — Built-in price simulator
  data_provider.py          — MT5 data provider
config/
  settings.py               — All tunable parameters
tests/                      — Unit tests (23 tests)
```

## Testing

```bash
python -m pytest tests/ -v
```
