# Walk-forward and data-snooping test (pre-registered protocol)

Written 2026-11-09, before any real-data walk-forward result was looked at. Protocol id `6341dcaa` (hash of the `PROTOCOL` block in `walkforward.py`). If that block changes, the id changes and the old results no longer count. No rule, setting or paper-trading variant is changed because of these results; the freeze from 2026-10-14 stands.

## Questions
1. If the settings were re-tuned each year on the data available then, and traded on the next unseen year, would the result still be positive?
2. After correcting for having searched a grid of settings (and about 800 earlier ones), is the best result distinguishable from luck?
3. Does re-tuning beat simply holding the frozen base settings?

## What is tested
- Strategy: the frozen base rules on QQQ (60-minute range, midpoint stop, 0.5x range target, 20-day EMA filter, long only, 2 cents slippage, $75 risk), exactly as `backtest.py --qqq --variant base` runs them. NQ/MNQ futures (`backtest.py` settings) as an indicative cross-check.
- Search grid per window (50 cells): range 30/45/60/75/90 minutes x target 0.25/0.35/0.5/0.75/1.0 times the range x EMA filter on or off. Entry cutoff is `max(12:00, range end + 60 min)`, as in `make_charts.py`. The cell (60, 0.5, EMA on) is the frozen base and is asserted equal to it in code.
- Objective: average R per trade in-sample (R = points / risk). A cell needs at least 30 in-sample trades to be eligible; if none is, the frozen base is used and the window is flagged.
- Windows: calendar years, out-of-sample step one year, no overlap. QQQ anchored: in-sample starts 2020, first in-sample block 2020-2021, out-of-sample 2022, 2023, 2024, 2025, 2026 to date (5 windows). QQQ rolling: 3-year in-sample, out-of-sample 2023 to 2026 to date (4 windows). NQ anchored: in-sample 2023, out-of-sample 2024 to 2026 (3 windows); NQ rolling: 2-year in-sample, out-of-sample 2025 and 2026 (2 windows, indicative only). Anchored and rolling are both reported; neither is chosen after the fact.
- Comparators on the same out-of-sample years: frozen base, and buy-every-day with the same stop, target and filter (`entry_mode="always"`).
- Cost stress: QQQ slippage 5 cents (reported, never used for selection).

## Statistics
- Stitched out-of-sample trades: count, win rate, average R, t-stat, profit factor, max drawdown; per-window average R; share of windows positive; parameter changes between windows.
- Walk-forward efficiency, two ways: per trade (stitched out-of-sample average R / trade-weighted in-sample average R of the chosen cells) and per day (out-of-sample R per day / in-sample R per day).
- Single-test stationary-bootstrap p-value that the stitched out-of-sample mean is at most zero.
- Data snooping over all 50 cells on the whole sample, against zero: White Reality Check and Hansen SPA (lower, consistent, upper), stationary bootstrap, mean block 10 trading days (5 and 20 as sensitivity), 5,000 repetitions, seed 7. Own numpy implementation, since the `arch` package is not installed.
- Probability of Backtest Overfitting by CSCV, 16 time blocks, Sharpe on daily R.
- Deflated Sharpe Ratio of the frozen base for N = 50 (grid), N = effective independent trials (participation ratio of the cell correlation matrix) and N = 800 (earlier settings). Minimum backtest length for N = 50 and 800.

## Decision rules (thresholds from the walk-forward guides; fixed before running)
The edge counts as supported only if all hold:
1. Stitched out-of-sample average R is above 0.
2. At least 60% of out-of-sample windows are positive.
3. Walk-forward efficiency per trade is at least 0.5.
4. SPA consistent p-value is below 0.05.

Also reported: whether frozen beats re-tuned on the same years (if so, keep freezing). Anything else is "plausible, not proven". Power is limited: R per trade has a standard deviation of about 0.8, so about 340 out-of-sample trades give a standard error of about 0.045 R. A +0.05 R edge cannot be proven by this test, only a large edge confirmed or a large decay revealed.

## How the harness was checked before any real result
- Reproduction gate (runs automatically and stops the script on a mismatch): QQQ base must reproduce 432 trades, 62.7% wins, +0.084 R, $684 max drawdown; NQ 216 trades, 65% wins, +0.13 R, PF 1.48. QQQ was reproduced exactly with `backtest.py` on 2026-11-09.
- `python -m unittest -v test_walkforward`: 19 tests passed (stationary bootstrap block length, CSCV hand case, PBO about 0.5 on noise and near 0 with a planted edge, Reality Check/SPA rarely significant on noise and finding a planted cell, deflated Sharpe, Bailey's "5 years allows about 45 trials", window construction, in-sample selection unaffected by out-of-sample rows).
- `python walkforward.py --selftest`: six random-walk datasets with no edge (median out-of-sample average R +0.03, no SPA p below 0.05) and one with a planted opening-range continuation edge (out-of-sample average R +0.31, SPA p 0.000). The planted strength was calibrated once on seed 101 so the control is detectable, which is a positive control, not a result. Two of six null seeds showed out-of-sample average R of +0.17 and +0.12 in about 100 trades, which shows how noisy a single window set is.
- Not used as a pass criterion: PBO on random-walk engine data. Grid cells differ systematically even without skill (costs, stop and target geometry), so PBO is not expected to be 0.5 there. PBO is checked on exchangeable noise instead.
- `python variants.py --check` printed "base settings unchanged" after the code was added.

## Known limits (not addressed in v1)
- Backtest bars are consolidated; the live bot reads the IEX feed, so opening ranges can differ by cents.
- The engine resolves a bar that hits both stop and target as a stop (conservative). The number of such trades is not counted here because it would need an engine change, which would alter the frozen settings hash.
- Slippage is a fixed 2 cents; real fills in the first minutes can be worse.
- 2020 starts on Jan 23 in the data; the QQQ settings were tuned on NQ, so the QQQ years 2023-24 are not independent of the tuning.

## Results
(appended after the first real run)
