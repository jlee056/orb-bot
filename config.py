import os
from dotenv import load_dotenv

load_dotenv()

# Connection
TWS_HOST = os.getenv("TWS_HOST", "127.0.0.1")
TWS_PORT = int(os.getenv("TWS_PORT", 7497))  # 7497 = paper | 7496 = live

# Paper log-only mode
# When True (default), every pre-trade FILTER (Friday, VIX, EMA, gap, range,
# loss-limit, event day) only LOGS the reason it would skip and KEEPS TRADING,
# recording the reason in the trade_log 'would_skip' column. This is how we
# gather real paper fills to validate the filters. Signal-absence days
# (no breakout / downside-first break) are still genuine no-trades.
# MUST be set to 0 before going live so filters actually skip.
PAPER_LOG_ONLY = os.getenv("PAPER_LOG_ONLY", "1") == "1"

# Instrument
SYMBOL   = "MNQ"
EXCHANGE = "CME"
CURRENCY = "USD"

# Account
ACCOUNT_SIZE = 5000
RISK_PERCENT = 0.015   # Elder's 2% is the ceiling; pros operate at 0.5–1.5%

# Risk controls
MAX_CONTRACTS    = 3     # 1 contract per $1K–2K equity (prop firm standard at $5K)
DAILY_LOSS_LIMIT = 150   # $150 = 3% of $5K; halt for the day if hit (Topstep standard)
MONTHLY_LOSS_CAP = 300   # $300 = 6% of $5K; Elder's 6% rule — halt until manual reset. Measured on NET month P&L.
# 1-contract risk allowed as a multiple of the risk budget (ACCOUNT_SIZE * RISK_PERCENT).
# One MNQ contract risks ~$130-310 on this setup, far above a $75 budget. Live mode skips
# the trade when 1 contract would exceed budget * this; paper mode trades 1 and logs over_risk.
MAX_RISK_OVERSHOOT = 1.0
STREAK_THRESHOLD = 3     # consecutive losses before reducing size
STREAK_RISK_MULT = 0.5   # halve risk% after streak threshold hit

# Opening range
OPENING_RANGE_MIN = 60     # 60-min range: most consistent family in the 2023-2026 backtest (see README "Backtest")
MAX_RANGE_PCT     = 0.008  # skip day if opening range > 0.8% of price (choppy day). In paper mode this only logs would_skip and still trades.

# Pre-trade filters (checked via yfinance before market open)
# 2023-2026 backtest (800 days, 1-min data): only the EMA trend filter helped, in every
# setup tested, in-sample and out-of-sample. Friday, low-VIX, gap and range filters removed
# good trades or made no difference, so they are OFF: they are still logged in would_skip
# but never block a trade. Flip to True to enforce one again.
FILTER_FRIDAY = False
# Scheduled-news days (events.py). Tested 2026-10-12 on 432 QQQ and 216 NQ trades: days with CPI, PPI,
# jobs, PCE, GDP or Mag-7 earnings were no worse than other days, so they are logged, not skipped.
# FOMC decision days were clearly worse (2 wins in 8 trades); a separate FOMC skip is under review.
FILTER_EVENT_DAYS = False
FILTER_GAP    = False
FILTER_RANGE  = False
VIX_MIN      = 0       # low-VIX skip disabled (was 13): low-VIX days were above average
VIX_MAX      = 35      # skip if VIX above — April 2025 tariff spike hit 60 (danger zone)
GAP_SKIP_PCT = 0.007   # skip long ORB if overnight gap-up exceeds 0.7% of prior close

# EMA trend filter (longs only when NQ in a confirmed uptrend)
EMA_DAYS_ABOVE_REQUIRED = 1   # prior close above the 20-EMA. 1 vs 3 days made no reliable difference; 1 keeps more trades.

# Trade parameters
TARGET_RATIO      = 0.5   # target = range high + 0.5 x range (~66% win rate in backtest)
ENTRY_CUTOFF_HOUR = 12    # no new entries at or after 12:00 PM ET (range now ends 10:30)

# Stop logic
STOP_MODE     = "midpoint"   # midpoint halves the dollar risk per contract vs the range low, with a higher avg R.  Options: "atr" => max(orb_low, entry - ATR_STOP_MULT*ATR); "midpoint" => (orb_high+orb_low)/2
ATR_PERIOD    = 14      # ATR lookback (daily bars)
ATR_STOP_MULT = 0.4     # research: stop = entry - 0.4*ATR, floored at orb_low
BREAKEVEN_TRIGGER_RATIO = 0     # 0 = off. With a 0.5x target the breakeven move only cut winners short in the backtest.

# Position sizing modifiers
SEPTEMBER_SIZE_MULT = 0.5   # September is a weak month: halve size (size reducer, NOT a skip)

# Day-of-week monitoring (log-only hook — never actually skips, even live)
# Python weekday(): Mon=0 ... Fri=4. e.g. [3] flags Thursdays as historically weak.
WEAK_WEEKDAYS = []

# End of session — force-close any open position at 3:50 PM ET
EOD_CLOSE_HOUR   = 15
EOD_CLOSE_MINUTE = 50

# FOMC days: force-close earlier (1:30 PM ET) to avoid the announcement whipsaw
FOMC_CLOSE_HOUR   = 13
FOMC_CLOSE_MINUTE = 30

# Files
TRADE_LOG = "trade_log.csv"
