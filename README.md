# MNQ ORB Bot

> Automated Opening Range Breakout day trader for Micro E-Mini Nasdaq (MNQ) futures via Interactive Brokers.

![Status](https://img.shields.io/badge/status-paper%20trading-yellow)
![Python](https://img.shields.io/badge/python-3.9%2B-blue)
![Broker](https://img.shields.io/badge/broker-Interactive%20Brokers-red)

---

## Strategy

The Opening Range Breakout (ORB) strategy captures momentum after the first 15 minutes of the trading day.

**How it works:**
1. **9:30–9:44 AM ET** — Market opens, bot watches
2. **9:45 AM ET** — Opening range locked: wick high and wick low of the first 15 minutes
3. **9:45–11:00 AM ET** — Wait for a 5-minute candle to **close** above the range high
4. **On breakout** — Enter long with bracket order: stop at range low, target at range high + 50% of range
5. **After 11:00 AM** — No new entries
6. **3:50 PM ET** — Force-close any open position

**Filters:**
- Long only — no short trades
- Mon–Thu only — no Fridays
- Skips days where range exceeds 0.8% of price (too choppy to trade)
- One trade per day maximum

---

## Backtested Benchmark

| Source | Win Rate | Return | Sample |
|--------|----------|--------|--------|
| Cory Mitchell (Oct 2024–Oct 2025) | **74.6%** | **433%/yr** | 114 trades, NQ futures |
| Quantified Strategies | 65% | — | 198 trades |

> 2024–2026 is historically strong for ORB on NQ/MNQ. The 0.8% range cap filters the choppy sessions that hurt backtests in weaker periods.

---

## Quick Setup

**1. Open an Interactive Brokers account**
- Apply at ibkr.com (free, no minimum for paper trading)
- Request futures and margin permissions

**2. Install TWS (Trader Workstation)**
- Download from ibkr.com
- Enable API: File → Global Configuration → API → Settings → Enable ActiveX and Socket Clients
- Set socket port to `7497` (paper) or `7496` (live)

**3. Run the bot**
```bash
pip install -r requirements.txt
python orb_bot.py
```

Open TWS and log into your paper account each morning before market open.

---

## Configuration

All parameters live in `config.py`:

| Parameter | Default | Description |
|-----------|---------|-------------|
| `TWS_PORT` | `7497` | `7497` = paper, `7496` = live |
| `TWS_HOST` | `127.0.0.1` | Localhost (same machine as TWS) |
| `OPENING_RANGE_MIN` | `15` | Minutes used to define the range |
| `ENTRY_CUTOFF_HOUR` | `11` | No entries after this hour (ET) |
| `EOD_CLOSE_HOUR` | `15` | Force-close hour |
| `EOD_CLOSE_MINUTE` | `50` | Force-close minute |
| `RISK_PERCENT` | `0.02` | Risk 2% of account per trade |
| `TARGET_RATIO` | `0.5` | Target = entry + 50% of range |
| `MAX_RANGE_PCT` | `0.008` | Skip if range > 0.8% of price |

---

## Requirements

- Python 3.9+
- Interactive Brokers account with TWS or IB Gateway
- MNQ market data subscription (included with IBKR paper trading)

```
ib_insync==0.9.86
pandas>=2.0
python-dotenv>=1.0
```

---

## Trade Log

Every trade auto-appends to `trade_log.csv` (gitignored):

```
date, contract, range_high, range_low, range_pct, entry, stop, target, exit, contracts, pnl_$, win
```

---

## Current Status

**Paper trading phase** — validating live execution against the backtest benchmark before risking real capital.

- [x] IBKR account opened
- [ ] TWS installed and API enabled
- [ ] 30+ paper trades logged
- [ ] Win rate ≥ 60% confirmed
- [ ] Go live (`TWS_PORT = 7496`)

---

## Files

- `orb_bot.py` — main bot (~180 lines)
- `config.py` — all tunable parameters
- `setup_guide.md` — full IBKR + TWS setup walkthrough
- `trade_log.csv` — auto-generated trade journal (gitignored)

---

## Disclaimer

Futures trading involves substantial risk of loss. Paper trade for at least 30 days and verify your results match the backtest benchmark before trading real capital. Past performance does not guarantee future results.
