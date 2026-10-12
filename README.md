# MNQ ORB Bot

> Automated Opening Range Breakout day trader for Micro E-Mini Nasdaq (MNQ) futures via Interactive Brokers.

![Status](https://img.shields.io/badge/status-paper%20trading-yellow)
![Python](https://img.shields.io/badge/python-3.9%2B-blue)
![Broker](https://img.shields.io/badge/broker-Interactive%20Brokers-red)

**[Read the logbook](docs/LOGBOOK.md)** for the full build history, the 800-day backtest, and every chart.

<picture>
  <source media="(prefers-color-scheme: dark)" srcset="docs/charts/equity-dark.png">
  <img src="docs/charts/equity.png" alt="Backtested cumulative profit of the current settings versus the previous settings, 2023 to 2026" width="900">
</picture>

---

## Strategy

The Opening Range Breakout (ORB) strategy captures momentum after the first 60 minutes of the trading day.

**How it works:**
1. **9:30–10:29 AM ET** — Market opens, bot watches
2. **10:30 AM ET** — Opening range locked: wick high and wick low of the first 60 minutes
3. **10:30 AM–12:00 PM ET** — Wait for a 5-minute candle to **close** above the range high
4. **On breakout** — Enter long with bracket order. Stop = range midpoint (`STOP_MODE`). Target = range high + 0.5× range.
5. **After 12:00 PM** — No new entries
6. **3:50 PM ET** — Force-close any open position (1:30 PM ET on FOMC days). The bracket order handles exits; this is the backstop.

**Filters — days the strategy skips (live mode):**
- NQ's last close is below its 20-day EMA (the only filter the backtest supports)
- VIX above 35 (safety stop; almost never triggers)
- High-impact event mornings — FOMC, CPI, PPI, PCE, GDP, and Mag-7 earnings (`events.py`; not backtested)
- Daily net loss ≥ $150 or monthly net loss ≥ $300
- One contract would risk more than the budget (`ACCOUNT_SIZE × RISK_PERCENT × MAX_RISK_OVERSHOOT`)
- Switched off after the backtest, still logged as `off:` notes: Friday, low VIX, overnight gap, wide range

> **Paper-log-only mode (current phase).** With `PAPER_LOG_ONLY=1` (the default) none of the filters above actually skip. Each one instead logs the reason it *would* have skipped into the `would_skip` CSV column and the bot trades the day anyway — so we gather real fills and can later measure which filters truly help. Genuine signal-absence days (`no_breakout`, or a downside-first break, since this is long-only) are still real no-trades. Set `PAPER_LOG_ONLY=0` before going live so the filters skip for real.

**Risk management on a live trade:**
- 1.5% risk per trade, hard cap of 3 contracts
- After 3 consecutive losses, risk per trade halves until a winning trade resets it
- September: position size halved (historically weak month — a size reducer, not a skip)
- FOMC days: force-close at 1:30 PM ET to dodge the announcement whipsaw

---

## Backtest (2026-10-12)

`python backtest.py` runs the bot exactly as `config.py` has it on about 800 trading days of 1-minute data (NQ 2023–2025, MNQ Jan–Apr 2026, NQ Aug–Oct 2026). Costs are included: 0.5 point slippage per market fill and $1.24 commission per contract. Settings were tuned on 2023–2024 only; 2025–2026 was held back as a test.

| Period | Trades | Win rate | Avg R | Profit factor | P&L, 1 contract | Max drawdown |
|--------|--------|----------|-------|---------------|-----------------|--------------|
| 2023–2024 (tuned on) | 140 | 66% | +0.13 | 1.42 | +$2,099 | $703 |
| 2025–2026 (held back) | 76 | 63% | +0.14 | 1.57 | +$2,201 | $985 |
| All | 216 | 65% | +0.13 | 1.48 | +$4,300 | $985 |

What the numbers mean:
- The edge is small: about 0.13 of the amount risked per trade, roughly $20 per trade per contract, about 70 trades a year. A simulated year loses money about 8% of the time and a $1,300 drawdown is normal.
- One MNQ contract risks about $130–$310 per trade on this setup. A 1.5% risk budget needs roughly a $15,000 account. At $5,000 the bot (live mode) skips almost every trade.
- Before this change the bot (30-min range, ATR stop, 1× target, all filters) averaged about zero after costs on the same data.

The third-party figures below use different rules (15-minute range, 0.5× target, wide capped stop, no costs) and are not comparable with this bot.

## Third-party benchmarks

| Source | Win Rate | Return | Sample |
|--------|----------|--------|--------|
| Edgeful (live, Jan–Jul 2025) | **73.44%** | **+174.85%** | NQ futures, optimized settings |
| Cory Mitchell (Oct 2024–Oct 2025) | **74.6%** | **433%/yr** | 114 trades, NQ futures |
| tradingstats.net (6,142 days, 2014–2025) | **71.5%** | — | NQ 30-min ORB continuation rate |

These are other people's results and were not reproduced here.

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
| `PAPER_LOG_ONLY` | `1` | `1` = filters log `would_skip` and keep trading; `0` = filters skip for real (set before going live) |
| `OPENING_RANGE_MIN` | `60` | Minutes used to define the range |
| `TARGET_RATIO` | `0.5` | Target = ORB high + 0.5× range size |
| `ENTRY_CUTOFF_HOUR` | `12` | No entries after this hour (ET) |
| `EOD_CLOSE_HOUR` | `15` | Force-close hour (ET) |
| `EOD_CLOSE_MINUTE` | `50` | Force-close minute |
| `RISK_PERCENT` | `0.015` | Risk 1.5% of account per trade |
| `MAX_CONTRACTS` | `3` | Hard cap on contracts per trade |
| `DAILY_LOSS_LIMIT` | `150` | Halt for the day if net loss hits $150 |
| `MONTHLY_LOSS_CAP` | `300` | Halt for the month if net loss hits $300 |
| `MAX_RISK_OVERSHOOT` | `1.0` | Skip (live) when 1 contract risks more than budget × this |
| `FILTER_FRIDAY` / `FILTER_GAP` / `FILTER_RANGE` | `False` | Filters switched off after the backtest; logged only |
| `STREAK_THRESHOLD` | `3` | Consecutive losses before halving risk |
| `VIX_MIN` | `0` | Skip if VIX below this (0 = off) |
| `VIX_MAX` | `35` | Skip if VIX above this |
| `GAP_SKIP_PCT` | `0.007` | Skip if overnight gap-up exceeds 0.7% |
| `MAX_RANGE_PCT` | `0.008` | Skip if range exceeds 0.8% of price |
| `EMA_DAYS_ABOVE_REQUIRED` | `1` | Consecutive closes above the 20-day EMA required before a long |
| `STOP_MODE` | `midpoint` | `atr` = `max(range low, entry − mult×ATR)`; `midpoint` = range midpoint |
| `ATR_PERIOD` | `14` | ATR lookback in daily bars |
| `ATR_STOP_MULT` | `0.4` | ATR multiple for the stop distance |
| `BREAKEVEN_TRIGGER_RATIO` | `0` | Move stop to entry once price is this fraction of the way to target (0 = off) |
| `SEPTEMBER_SIZE_MULT` | `0.5` | Position-size multiplier in September (weak month) |
| `STREAK_RISK_MULT` | `0.5` | Risk multiplier applied after `STREAK_THRESHOLD` consecutive losses |

---

## Why These Settings

The settings come from this project's own backtest, described step by step in the [logbook](docs/LOGBOOK.md).

- **60-minute range, 0.5× target, midpoint stop.** Every nearby combination (45 to 75 minute ranges, 0.5× to 1.0× targets) was profitable after costs. This one sits in the middle of that area, with a 65% win rate and the smallest drawdown.
- **Trend filter only.** Trades taken when NQ closed below its 20-day EMA lost money on average. The Friday, low-VIX, gap and wide-range filters blocked trades that were profitable, so they are switched off.
- **Long only.** Short breakouts added nothing in testing.
- **1.5% risk per trade.** A common professional ceiling. One MNQ contract needs an account of about $15,000 to fit inside it.

Earlier versions of these settings (30-minute range, 1.0× target, ATR stop, five filters) were chosen from published statistics. The backtest did not support them. The logbook keeps that history.

---

## Requirements

- Python 3.9+
- Interactive Brokers account with TWS or IB Gateway
- For live or paper orders: a funded IBKR account with futures permission and a CME market data subscription. The backtest needs neither.

```
ib_insync==0.9.86
pandas>=2.0
python-dotenv>=1.0
yfinance>=0.2
matplotlib>=3.8   # charts only
```

---

## Trade Log

Every trade and every skip auto-appends to `trade_log.csv` (gitignored):

```
date, range_high, range_low, range_pct, skipped, entry, stop, target, exit, contracts, pnl_usd, win, vix, would_skip
```

The `vix` column lets you analyze which VIX environments produce the best results over time. The `skipped` column records genuine no-trade days — `no_breakout` (price never closed above the range) or `downside_break` (broke down first; this is long-only). The `would_skip` column is the paper-mode validation field: a `;`-joined list of every filter that fired but was overridden so the bot still traded — exactly the data needed to measure which filters help before going live.

---

## Current Status

**Backtested, waiting on a forward record.** See the [logbook](docs/LOGBOOK.md) for detail.

- [x] Bot built; connects, locks the range, detects breakouts, sends bracket orders
- [x] Paper-log-only mode, event calendar, loss caps
- [x] First live breakout detected (order rejected: account has no futures permission)
- [x] 800-day backtest with costs; settings retuned from it
- [ ] Daily forward run on delayed data, no broker
- [ ] 20+ forward signals compared with the backtest
- [ ] First paper fill through IBKR (needs a funded account)

---

## Files

- `orb_bot.py` — the bot (connect, range lock, breakout poll, bracket order, logging)
- `config.py` — every tunable setting
- `events.py` — hand-maintained economic-calendar and earnings day filter
- `orb_engine.py` — backtest engine and data loaders
- `backtest.py` — backtests the bot exactly as `config.py` has it
- `make_charts.py` — rebuilds every chart and table in the logbook
- `get_data.py` — downloads the free price data into `data/` (git-ignored)
- `docs/LOGBOOK.md` — the project logbook; `docs/charts/`, `docs/data/` — its charts and tables
- `setup_guide.md` — IBKR and TWS setup walkthrough
- `trade_log.csv` — auto-generated trade journal (git-ignored)

To reproduce the backtest:

```bash
pip install -r requirements.txt
python get_data.py
python backtest.py
python make_charts.py
```

---

## Disclaimer

Futures trading involves substantial risk of loss. Paper trade for at least 30 days and compare your results with the backtest before trading real capital. Past performance does not guarantee future results.
