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
MONTHLY_LOSS_CAP = 300   # $300 = 6% of $5K; Elder's 6% rule — halt until manual reset
STREAK_THRESHOLD = 3     # consecutive losses before reducing size
STREAK_RISK_MULT = 0.5   # halve risk% after streak threshold hit

# Opening range
OPENING_RANGE_MIN = 30     # 30-min ORB: 71.5% NQ continuation rate (6,142-day dataset)
MAX_RANGE_PCT     = 0.008  # skip day if opening range > 0.8% of price (choppy day). In paper mode this only logs would_skip and still trades.

# Pre-trade filters (checked via yfinance before market open)
VIX_MIN      = 13      # skip if VIX below — too calm, 48% win rate below 13
VIX_MAX      = 35      # skip if VIX above — April 2025 tariff spike hit 60 (danger zone)
GAP_SKIP_PCT = 0.007   # skip long ORB if overnight gap-up exceeds 0.7% of prior close

# EMA trend filter (longs only when NQ in a confirmed uptrend)
EMA_DAYS_ABOVE_REQUIRED = 3   # require 3+ consecutive closes above 20-EMA before a long (anti-whipsaw, 2025 cross-check)

# Trade parameters
TARGET_RATIO      = 1.0   # 2025 cross-check: median NQ max extension ~0.42× range
ENTRY_CUTOFF_HOUR = 11    # no new entries at or after 11:00 AM ET

# Stop logic
STOP_MODE     = "atr"   # "atr" => max(orb_low, entry - ATR_STOP_MULT*ATR); "midpoint" => (orb_high+orb_low)/2
ATR_PERIOD    = 14      # ATR lookback (daily bars)
ATR_STOP_MULT = 0.4     # research: stop = entry - 0.4*ATR, floored at orb_low
BREAKEVEN_TRIGGER_RATIO = 0.75  # move stop to entry once price is 0.75x of the way to target. No trailing (QuantCrawler: trailing hurt PnL).

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
