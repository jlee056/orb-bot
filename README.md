# MNQ ORB Bot

> Automated Opening Range Breakout day trader for Micro E-Mini Nasdaq (MNQ) futures via Interactive Brokers.

![Status](https://img.shields.io/badge/status-paper%20trading-yellow)
![Python](https://img.shields.io/badge/python-3.9%2B-blue)
![Broker](https://img.shields.io/badge/broker-Interactive%20Brokers-red)

---

## Strategy

The Opening Range Breakout (ORB) strategy captures momentum after the first 30 minutes of the trading day.

**How it works:**
1. **9:30–9:59 AM ET** — Market opens, bot watches
2. **10:00 AM ET** — Opening range locked: wick high and wick low of the first 30 minutes
3. **10:00–11:00 AM ET** — Wait for a 5-minute candle to **close** above the range high
4. **On breakout** — Enter long with bracket order: stop at range midpoint, target at range high + 1.0× range
5. **After 11:00 AM** — No new entries
6. **3:50 PM ET** — Force-close any open position (bracket order handles exits; this is the backstop)

**Filters — days the bot skips:**
- Fridays (consistently worst ORB day)
- VIX below 13 (too calm — 48% win rate, no edge)
- VIX above 35 (danger zone — April 2025 tariff shock hit VIX 60)
- NQ below its 20-day EMA (bearish regime — removes ~70% of losing long setups)
- Overnight gap-up > 0.7% (breakout from exhausted gap = low follow-through)
- Range exceeds 0.8% of price (too choppy to trade)
- Daily loss >= $150 or monthly loss >= $300 (Elder's 6% monthly rule)

**Automatic risk reduction:**
- After 3 consecutive losses, risk per trade halves until a winning trade resets it

---

## Backtested Benchmark

| Source | Win Rate | Return | Sample |
|--------|----------|--------|--------|
| Edgeful (live, Jan–Jul 2025) | **73.44%** | **+174.85%** | NQ futures, optimized settings |
| Cory Mitchell (Oct 2024–Oct 2025) | **74.6%** | **433%/yr** | 114 trades, NQ futures |
| tradingstats.net (6,142 days, 2014–2025) | **71.5%** | — | NQ 30-min ORB continuation rate |

> The ORB edge on NQ has not degraded in 12 years of data. The 2024 continuation rate (73.7%) was the highest ever recorded.

---

## Quick Setup

**1. Open an Interactive Brokers account**
- Apply at ibkr.com (free, no minimum for paper trading)
- Request futures and margin permissions
- Create a paper trading account at Client Portal → Settings → Paper Trading

**2. Install TWS (Trader Workstation)**
- Download from ibkr.com
- Enable API: Edit → Global Configuration → API → Settings → Enable ActiveX and Socket Clients
- Set socket port to `7497` (paper) or `7496` (live)
- Allow localhost only, uncheck Read-Only API

**3. Run the bot**
```bash
pip install -r requirements.txt
python orb_bot.py
```

Open TWS and log into your paper account each morning before market open. The bot handles everything from there.

---

## Configuration

All parameters live in `config.py`:

| Parameter | Default | Description |
|-----------|---------|-------------|
| `TWS_PORT` | `7497` | `7497` = paper, `7496` = live |
| `TWS_HOST` | `127.0.0.1` | Localhost (same machine as TWS) |
| `OPENING_RANGE_MIN` | `30` | Minutes used to define the range |
| `TARGET_RATIO` | `1.0` | Target = ORB high + 1.0× range size |
| `ENTRY_CUTOFF_HOUR` | `11` | No entries after this hour (ET) |
| `EOD_CLOSE_HOUR` | `15` | Force-close hour (ET) |
| `EOD_CLOSE_MINUTE` | `50` | Force-close minute |
| `RISK_PERCENT` | `0.015` | Risk 1.5% of account per trade |
| `MAX_CONTRACTS` | `3` | Hard cap on contracts per trade |
| `DAILY_LOSS_LIMIT` | `150` | Halt for the day if losses hit $150 |
| `MONTHLY_LOSS_CAP` | `300` | Halt for the month if losses hit $300 |
| `STREAK_THRESHOLD` | `3` | Consecutive losses before halving risk |
| `VIX_MIN` | `13` | Skip if VIX below this |
| `VIX_MAX` | `35` | Skip if VIX above this |
| `GAP_SKIP_PCT` | `0.007` | Skip if overnight gap-up exceeds 0.7% |
| `MAX_RANGE_PCT` | `0.008` | Skip if range exceeds 0.8% of price |

---

## Research — Why These Settings

Every parameter in this bot is based on data, not guessing. Here's the research behind the key decisions.

### Why 30-minute ORB instead of 15-minute?

[tradingstats.net](https://tradingstats.net/orb-breakout-strategy-guide/) analyzed **6,142 trading days of ES and NQ futures from 2014 to 2025** across multiple ORB timeframes. The NQ 30-minute ORB produced a **71.5% continuation rate** — the highest single configuration in the entire dataset. The 15-minute ORB came in at ~63%. The 2024 single-year reading was 73.7%, the highest ever recorded.

The 5-minute ORB has a 69.2% double-break rate on NQ — meaning nearly 70% of days, NQ tags both sides of the 5-minute range and gives no clean direction. The 30-minute window filters out the chaotic first half-hour and locks in on the real committed move.

### Why a midpoint stop instead of the range low?

A ToSIndicators backtest on AAPL ORB compared stop placements directly. The midpoint stop produced a **+20 percentage point improvement in win rate** over the full range-low stop. The [tradingstats.net](https://tradingstats.net/orb-strategy-research/) 6,142-day dataset confirms that adverse moves are better calibrated to ATR than to the arbitrary range boundary — the midpoint stop is a more volatility-appropriate level.

### Why a 1.0× target instead of 1.5×?

The tradingstats.net extension data shows for NQ 30-min ORB:
- **0.5× range** extension is reached ~50% of breakout days
- **1.0× range** extension is reached ~32% of breakout days
- **1.5× range** extension is reached only **~20%** of breakout days

The median NQ maximum favorable excursion is **0.42× the opening range**. A 1.5× target was being hit less than 1-in-5 times. [FazenCapital](https://fazencapital.com/learn/en/opening-range-breakout-orb-strategy-indices-guide) specifically recommends lower targets for NQ vs ES due to Nasdaq's mean-reversion tendency. 2025 cross-validation against live edgeful data confirmed 1.0× as the right level for current market conditions.

### Why the VIX filter (skip below 13, skip above 35)?

[ToSIndicators](https://tosindicators.com/research/vix-opening-range-breakout-orb-strategy-thinkorswim) backtested VIX-adaptive vs static ORB strategies from 2020 to 2025:
- VIX below 13: **48% win rate** — ranges too tight, no momentum
- VIX 15–25: **58% win rate** — sweet spot
- VIX above 35: danger zone

The ceiling was set at 35 (not 25) after April 7, 2025, when VIX spiked to **60.13** on Trump tariff announcements — the highest since the 2020 pandemic. At VIX 60, opening ranges lose their structural meaning entirely. Below 35, the edge holds.

### Why the 20-day EMA trend filter?

Long-only ORB trades taken in a downtrending market fight the primary direction. Adding a filter of "only take long ORBs when NQ is above its 20-day EMA" reduced losing trades by ~70% in documented NQ backtests while retaining winning trades. The EMA filter correctly blocked two major losing periods: August 2024 (NQ -13% on yen carry unwind) and April 2025 (tariff shock, VIX 60).

### Why 1.5% risk instead of 2%?

Alexander Elder's *The New Trading for a Living* sets 2% as the **ceiling**, not the target. Professional prop traders and funded account operators (Topstep, Apex) standardize at 1.5–2% per trade. At 1.5% on a $5K account, maximum loss per trade is $75 — survivable across a losing streak. Elder's 6% monthly rule (halt when cumulative monthly losses hit 6%) is implemented as the `MONTHLY_LOSS_CAP` of $300.

---

## Requirements

- Python 3.9+
- Interactive Brokers account with TWS or IB Gateway
- MNQ market data subscription (included with IBKR paper trading)

```
ib_insync==0.9.86
pandas>=2.0
python-dotenv>=1.0
yfinance>=0.2
```

---

## Trade Log

Every trade and every skip auto-appends to `trade_log.csv` (gitignored):

```
date, range_high, range_low, range_pct, skipped, entry, stop, target, exit, contracts, pnl_usd, win, vix
```

The `vix` column lets you analyze which VIX environments produce the best results over time. The `skipped` column shows exactly why the bot passed on a given day.

---

## Current Status

**Paper trading phase** — validating live execution against the backtest benchmark before risking real capital.

- [x] IBKR account opened
- [x] Code optimized with research-backed parameters
- [x] GitHub published
- [ ] TWS installed and API enabled
- [ ] 30+ paper trades logged
- [ ] Win rate ≥ 60% confirmed over sample
- [ ] Go live (`TWS_PORT = 7496`)

---

## Files

- `orb_bot.py` — main bot (~240 lines)
- `config.py` — all tunable parameters with research citations
- `setup_guide.md` — full IBKR + TWS setup walkthrough
- `requirements.txt` — Python dependencies
- `trade_log.csv` — auto-generated trade journal (gitignored)

---

## Disclaimer

Futures trading involves substantial risk of loss. Paper trade for at least 30 days and verify your results match the backtest benchmark before trading real capital. Past performance does not guarantee future results.
