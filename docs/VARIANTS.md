# Variants, side by side

Three versions of the strategy run at the same time, each in its own Alpaca paper account, so data builds up about four times faster than with the base rules alone. Their rules were fixed on 2026-10-14 before the first trade (see the [logbook](LOGBOOK.md)). This page is rebuilt automatically after every close by `variants_report.py`.

| Variant | Rules |
|---|---|
| `base` | 60-minute range, long only, stop at the range midpoint, target half the range, only when QQQ is above its 20-day average |
| `orb5` | first 5-minute candle up: buy at 9:35; down: sell short. Stop at the candle's far side, target 10 R or the close. No trend filter |
| `both60` | base rules, plus a short on a downside break. Longs need QQQ above its 20-day average, shorts below |

## Paper accounts (Alpaca, QQQ)

| Variant | Days | Trades | Win rate | Avg R | Total R | Backtest avg R | Fill gap (R) | Status |
|---|---|---|---|---|---|---|---|---|
| `base` | 3 | 0 | | | | +0.084 | | running, next review at 50 trades |
| `orb5` | 0 | 0 | | | | +0.081 | | running, next review at 50 trades |
| `both60` | 0 | 0 | | | | +0.053 | | running, next review at 50 trades |

*Fill gap* is the broker's result minus what the engine expected on the same day. Alpaca's paper fills do not charge slippage, so a gap near zero is expected; real trading would be worse.

## Forward log (Yahoo, NQ futures, no orders)

| Variant | Days | Signals | Win rate | Avg R | Total R |
|---|---|---|---|---|---|
| `base` | 3 | 0 | | | |
| `orb5` | 0 | 0 | | | |
| `both60` | 0 | 0 | | | |

## Rules for judging, fixed in advance

- Review each variant at 50, 100, 312 trades. Nothing is retuned from this record; a change of rules would be a new variant with a new settings hash.
- 312 trades is roughly what it takes to tell an average of +0.1 R from zero (95% confidence, with the spread of results the backtest shows).
- A variant stops if its average is -0.15 R or worse after 100 trades, or if its drawdown passes 1.5× the largest drawdown in its backtest.
- The backtest expects about 64 trades a year for `base`, 242 trades a year for `orb5`, 94 trades a year for `both60`.

Logs: [`paper/alpaca_trades.csv`](../paper/alpaca_trades.csv), [`paper/alpaca_trades_orb5.csv`](../paper/alpaca_trades_orb5.csv), [`paper/alpaca_trades_both60.csv`](../paper/alpaca_trades_both60.csv); [`forward/forward_log.csv`](../forward/forward_log.csv), [`forward/forward_log_orb5.csv`](../forward/forward_log_orb5.csv), [`forward/forward_log_both60.csv`](../forward/forward_log_both60.csv).
