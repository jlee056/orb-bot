import os
from dotenv import load_dotenv

load_dotenv()

# Connection
TWS_HOST = os.getenv("TWS_HOST", "127.0.0.1")
TWS_PORT = int(os.getenv("TWS_PORT", 7497))  # 7497 = paper | 7496 = live

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
MAX_RANGE_PCT     = 0.008  # skip day if range > 0.8% of price (too choppy)

# Pre-trade filters (checked via yfinance before market open)
VIX_MIN      = 13      # skip if VIX below — too calm, 48% win rate below 13
VIX_MAX      = 35      # skip if VIX above — April 2025 tariff spike hit 60 (danger zone)
GAP_SKIP_PCT = 0.007   # skip long ORB if overnight gap-up exceeds 0.7% of prior close

# Trade parameters
TARGET_RATIO      = 1.0   # 2025 cross-check: median NQ max extension ~0.42× range
ENTRY_CUTOFF_HOUR = 11    # no new entries at or after 11:00 AM ET

# End of session — force-close any open position at 3:50 PM ET
EOD_CLOSE_HOUR   = 15
EOD_CLOSE_MINUTE = 50

# Files
TRADE_LOG = "trade_log.csv"
