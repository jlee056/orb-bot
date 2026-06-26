"""
events.py — high-impact economic / earnings calendar for the ORB bot.

Used by orb_bot.py to:
  - flag macro-event mornings (CPI, PPI, PCE, GDP, FOMC) and Mag-7 earnings
    mornings so the strategy can skip them (live) or log "would_skip:event_day"
    (paper),
  - force an early close on FOMC announcement days (is_fomc()).

NOTE: this is a HAND-MAINTAINED list. It must be refreshed each year (FOMC
dates are published ~1 year ahead) and each quarter (earnings). NFP is always
the first Friday of the month and is already covered by the Friday skip, so it
is not re-listed here.

Dates are keyed "YYYY-MM-DD" (US Eastern calendar date of the release).
FOMC dates below are the *decision day* (second day of the two-day meeting)
from the Fed's published 2026 schedule — VERIFY against federalreserve.gov.
CPI/PPI/PCE/GDP and earnings dates are left for Sir Jeremy to populate from
BLS/BEA schedules and company IR pages (see ORB_BOT progress open items).
"""

# ---------------------------------------------------------------------------
# 2026 FOMC decision days (verify at federalreserve.gov/monetarypolicy/fomccalendars.htm)
# ---------------------------------------------------------------------------
FOMC_DATES_2026 = [
    "2026-01-28",
    "2026-03-18",
    "2026-04-29",
    "2026-06-17",
    "2026-07-29",
    "2026-09-16",
    "2026-10-28",
    "2026-12-09",
]

# ---------------------------------------------------------------------------
# Other high-impact macro releases (8:30 AM ET) — POPULATE from BLS/BEA schedules.
# Example shape (uncomment / fill with real 2026 dates):
#   CPI:  monthly, ~mid-month
#   PPI:  monthly, ~day before/after CPI
#   PCE:  monthly, ~last business day (BEA)
#   GDP:  quarterly, end of month (BEA)
# ---------------------------------------------------------------------------
CPI_DATES_2026 = []   # e.g. ["2026-01-13", "2026-02-11", ...]
PPI_DATES_2026 = []
PCE_DATES_2026 = []
GDP_DATES_2026 = []

# ---------------------------------------------------------------------------
# Mag-7 earnings mornings (NVDA alone can move NQ 3–5%) — POPULATE from IR pages.
# Map date -> ticker so the log shows which name.  e.g. {"2026-02-25": "NVDA"}
# ---------------------------------------------------------------------------
EARNINGS_DATES_2026 = {}   # {"YYYY-MM-DD": "NVDA"}


def _build_event_index():
    """Collapse all the sources above into one dict: date -> [tags]."""
    index = {}

    def add(date_str, tag):
        index.setdefault(date_str, [])
        if tag not in index[date_str]:
            index[date_str].append(tag)

    for d in FOMC_DATES_2026:
        add(d, "FOMC")
    for d in CPI_DATES_2026:
        add(d, "CPI")
    for d in PPI_DATES_2026:
        add(d, "PPI")
    for d in PCE_DATES_2026:
        add(d, "PCE")
    for d in GDP_DATES_2026:
        add(d, "GDP")
    for d, ticker in EARNINGS_DATES_2026.items():
        add(d, f"earnings:{ticker}")

    return index


# Built once at import.
EVENT_DATES = _build_event_index()


def get_events_today(date_str):
    """Return the list of high-impact event tags for date_str ('YYYY-MM-DD').
    Empty list if the day has no flagged events."""
    return list(EVENT_DATES.get(date_str, []))


def is_fomc(date_str):
    """True if date_str ('YYYY-MM-DD') is an FOMC decision day."""
    return "FOMC" in EVENT_DATES.get(date_str, [])
