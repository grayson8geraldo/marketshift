# MarketShift — Forex Trading Bot

Supply/demand zone trading bot for MetaTrader 5.

## Strategy

1. **Zone Detection (HTF M15)** — Finds supply/demand zones at price extremes using fractal swing detection. Zones are scored by touch count, impulse strength, and round-number proximity.
2. **Entry Logic (LTF M1)** — When price enters a zone, detects exhaustion moves and waits for market structure break (BOS) before entering.
3. **Risk Management** — Dynamic lot sizing (1% risk per trade), breakeven at 1R, trailing stop, TP at next opposing zone. Minimum 2:1 R:R.

## Project Structure

```
bot/
  zones.py          — HTF zone detection, scoring, filtering
  entry.py          — LTF exhaustion detection, structure break, trade setup
  risk_manager.py   — Lot sizing, order execution, SL/TP management
  engine.py         — Main loop orchestrating all modules
  data_provider.py  — MT5 data fetching
config/
  settings.py       — All tunable parameters
tests/              — Unit tests (23 tests)
main.py             — Entry point
```

## Quick Start

```bash
pip install -r requirements.txt
python main.py --symbol EURUSD
```

Requires MetaTrader 5 terminal running on Windows with a connected account.

## Testing

```bash
pip install pytest
python -m pytest tests/ -v
```
