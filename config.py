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
ACCOUNT_SIZE = 5000   # simulated paper account size in dollars
RISK_PERCENT = 0.02   # 2% of account per trade = $100 max risk

# Opening range
OPENING_RANGE_MIN = 15     # first 15 minutes define the range
MAX_RANGE_PCT     = 0.008  # skip day if range > 0.8% of price (too choppy)

# Trade parameters
TARGET_RATIO       = 1.5  # target = orb_high + 150% of range (optimized: 1.5 R/R full exit)
ENTRY_CUTOFF_HOUR  = 11   # no new entries at or after 11:00 AM ET

# End of session — exit all open trades by 11:00 AM (trade window is 9:45–11:00 only)
EOD_CLOSE_HOUR   = 11
EOD_CLOSE_MINUTE = 0

# Files
TRADE_LOG = "trade_log.csv"
