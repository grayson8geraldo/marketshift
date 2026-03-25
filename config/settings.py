"""
MarketShift Forex Trading Bot — Configuration
"""

# ─── Timeframes ────────────────────────────────────────────────────────
HTF_TIMEFRAME = "M15"          # Higher timeframe for zone discovery
LTF_TIMEFRAME = "M1"           # Lower timeframe for entry triggers
HTF_BARS = 2000                # Number of HTF bars to load for analysis
LTF_BARS = 500                 # Number of LTF bars to load for entry search

# ─── Zone Detection (HTF) ─────────────────────────────────────────────
ZIGZAG_DEPTH = 12              # ZigZag depth — minimum bars between pivots
ZIGZAG_DEVIATION = 5.0         # ZigZag deviation in points (filter noise)
ZIGZAG_BACKSTEP = 3            # ZigZag backstep

ZONE_TOUCH_MIN = 2             # Minimum times price must touch a zone
ZONE_PROXIMITY_PCT = 0.0015    # Max distance to merge two zones (0.15%)
EXTREMUM_PERCENTILE = 15       # Only consider top/bottom N% of price range

IMPULSE_MIN_BODY_RATIO = 0.6  # Min body/range ratio to count as impulse candle
IMPULSE_MIN_CANDLES = 2        # Min consecutive impulse candles from zone
IMPULSE_MIN_MOVE_PCT = 0.003   # Min % price move to qualify as impulse (0.3%)

ROUND_NUMBER_WEIGHT = 1.5      # Score multiplier for zones near round numbers
ROUND_NUMBER_TOLERANCE = 0.001 # 0.1% tolerance for round-number detection

# ─── Entry Logic (LTF) ────────────────────────────────────────────────
FRACTAL_PERIOD = 5             # Swing high/low lookback on each side
EXHAUSTION_CANDLE_COUNT = 5    # Number of recent candles to evaluate speed
EXHAUSTION_BODY_RATIO = 0.7    # Min avg body/range ratio for exhaustion move
EXHAUSTION_RETRACEMENT = 0.2   # Max allowed retracement during approach (20%)

STRUCTURE_BREAK_CONFIRM = True # Require candle CLOSE beyond structure level
MIN_RR_RATIO = 2.0             # Minimum reward-to-risk ratio to take a trade

# ─── Risk Management ──────────────────────────────────────────────────
RISK_PER_TRADE_PCT = 1.0       # Risk per trade as % of account balance
SL_BUFFER_POINTS = 3           # Extra points beyond swing for stop-loss
BREAKEVEN_TRIGGER_RR = 1.0     # Move SL to breakeven at this R:R
TRAILING_STOP_ENABLED = True   # Enable trailing stop
TRAILING_STEP_POINTS = 5       # Trailing stop step size in points

# ─── Execution ─────────────────────────────────────────────────────────
MAGIC_NUMBER = 202603          # EA magic number for order identification
MAX_SLIPPAGE = 3               # Maximum allowed slippage in points
LOT_SIZE_FIXED = None          # Set to a float for fixed lot; None = dynamic
SYMBOL = "EURUSD"              # Default trading symbol
