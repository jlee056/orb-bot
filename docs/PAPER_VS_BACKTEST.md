# Paper trades against the engine (Phase C)

Built by `paper_vs_backtest.py`. Each paper trade has three results in R (1 R = the amount risked): **A** what the broker did, **S** the engine on the free one-exchange bars the bot saw that morning, **O** the engine on consolidated bars (today's data). A - S is execution on the same data, S - O is the data feed, A - O is both. Prices are dollars per share and "worse" means worse for the trade (paid more or sold lower for a long, the reverse for a short). The 2026-10-26 late close is shown but left out of every average. Consolidated data runs to 2026-11-09.

## base

Days logged 21. The engine on the free feed and on consolidated data told the same story, direction included, on 21 of 21 days.
Check: re-running the engine on freshly fetched free-feed bars reproduces the bot's logged expectation (within 0.02 R) on 1 of 1 traded days.

Missed signals (no order went out), engine result on the free feed: 2026-10-29 -1.01 R, total -1.01 R.

## orb5

Days logged 18. The engine on the free feed and on consolidated data told the same story, direction included, on 16 of 18 days.
- 2026-10-16: free feed target short, consolidated eod short.
- 2026-10-21: free feed stop short, consolidated stop long.
Check: re-running the engine on freshly fetched free-feed bars reproduces the bot's logged expectation (within 0.02 R) on 18 of 18 traded days.

| Date | Outcome | Bot | A | S | O | A-S | S-O | Entry worse | Exit worse | Stop vs engine | Risk ($/sh) |
|---|---|---|---|---|---|---|---|---|---|---|---|
| 2026-10-15 | stop | short | -0.90 | -1.01 | -1.01 | +0.11 | +0.00 | +0.16 | -0.20 | -0.00 | 1.66 |
| 2026-10-16 | target | short | +5.48 | +9.85 | +8.55 | -4.37 | +1.30 | +1.01 | -0.01 | -0.00 | 1.50 |
| 2026-10-19 | stop | short | -0.95 | -1.03 | -1.03 | +0.07 | -0.00 | +0.00 | -0.05 | +0.00 | 0.72 |
| 2026-10-20 | stop | short | -1.00 | -1.01 | -1.01 | +0.01 | +0.00 | -0.01 | -0.03 | -0.00 | 1.91 |
| 2026-10-21 | stop | short (consolidated: opposite side) | -1.02 | -1.03 |  | +0.00 |  | +0.98 | +0.02 | -0.00 | 0.70 |
| 2026-10-22 | stop | long | -1.41 | -1.01 | -1.01 | -0.39 | -0.00 | -0.69 | +0.31 | +0.00 | 1.51 |
| 2026-10-23 | stop | long | -1.43 | -1.02 | -1.02 | -0.40 | -0.00 | -0.58 | +0.09 | +0.00 | 0.86 |
| 2026-10-30 | stop | short | -0.99 | -1.01 | -1.01 | +0.01 | +0.00 | +0.27 | -0.04 | -0.00 | 2.81 |
| 2026-11-02 | stop | short | -1.01 | -1.04 | -1.03 | +0.03 | -0.01 | +0.82 | +0.01 | -0.00 | 0.48 |
| 2026-11-03 | eod | long | -0.05 | +0.27 | +0.26 | -0.32 | +0.02 | +0.04 | +0.71 | +0.00 | 2.34 |
| 2026-11-04 | stop | short | -1.16 | -1.01 | -1.01 | -0.15 | -0.00 | -1.65 | +0.24 | -0.00 | 3.27 |
| 2026-11-05 | eod | short | +3.34 | +5.12 | +4.42 | -1.78 | +0.70 | +2.34 | -0.64 | -0.00 | 5.35 |
| 2026-11-06 | stop | short | -1.03 | -1.01 | -1.01 | -0.02 | -0.00 | -0.49 | +0.03 | -0.00 | 2.45 |
| 2026-11-09 | eod | long | +2.67 | +4.10 | +4.27 | -1.43 | -0.17 | +1.32 | +0.22 | +0.00 | 3.56 |

- A - S (execution): mean -0.62 R, median -0.09 R, standard error 0.33, 14 trades
- S - O (data feed): mean +0.14 R, median -0.00 R, standard error 0.11, 13 trades
- A - O (both): mean -0.52 R, median -0.15 R, standard error 0.25, 13 trades
- Execution (A - S) on the 14 trades where the bot and the engine took the same side: a price effect of -0.24 R and a risk-scale effect of -0.37 R (they add up exactly to -0.62).
- In dollars per share the bot's entry was +0.25 worse than the engine's and its exit +0.05 worse (average, negative = better); its stop was +0.00 from the engine's. The engine's risk is 2.08 dollars per share on average (median 1.78; 29% of trades under 1 dollar), so one cent is 0.006 R at the median.
- The gap is concentrated: 3 of 14 trades account for -7.57 of the total -8.62 R (2026-10-16, 2026-11-05, 2026-11-09).
- Without those, the mean A - S is -0.10 R over 11 trades.
- Feed: the free feed's stop level differs from consolidated by +0.10 dollars per share on average (positive = free feed's stop is further from entry); S - O mean +0.14 R.

Missed signals (no order went out), engine result on the free feed: 2026-10-27 -1.01; 2026-10-28 -1.02; 2026-10-29 -1.00 R, total -3.04 R.

Late close, left out of the averages: 2026-10-26 actual +3.63 R, engine on the free feed +3.79, on consolidated +2.91.

## both60

Days logged 18. The engine on the free feed and on consolidated data told the same story, direction included, on 18 of 18 days.
Check: re-running the engine on freshly fetched free-feed bars reproduces the bot's logged expectation (within 0.02 R) on 4 of 4 traded days.

| Date | Outcome | Bot | A | S | O | A-S | S-O | Entry worse | Exit worse | Stop vs engine | Risk ($/sh) |
|---|---|---|---|---|---|---|---|---|---|---|---|
| 2026-10-16 | target | short | +0.10 | +0.16 | +0.20 | -0.06 | -0.03 | +0.34 | -0.07 | +0.00 | 5.06 |
| 2026-10-22 | target | short | +0.53 | +0.50 | +0.52 | +0.03 | -0.02 | -0.06 | -0.03 | +0.00 | 3.80 |
| 2026-11-05 | eod | short | +0.22 | +0.21 | +0.23 | +0.01 | -0.02 | +0.32 | -0.58 | -0.00 | 15.66 |

- A - S (execution): mean -0.01 R, median +0.01 R, standard error 0.03, 3 trades
- S - O (data feed): mean -0.02 R, median -0.02 R, standard error 0.01, 3 trades
- A - O (both): mean -0.03 R, median -0.00 R, standard error 0.03, 3 trades
- Execution (A - S) on the 3 trades where the bot and the engine took the same side: a price effect of -0.00 R and a risk-scale effect of -0.00 R (they add up exactly to -0.01).
- In dollars per share the bot's entry was +0.20 worse than the engine's and its exit -0.23 worse (average, negative = better); its stop was +0.00 from the engine's. The engine's risk is 8.18 dollars per share on average (median 5.06; 0% of trades under 1 dollar), so one cent is 0.002 R at the median.
- Without those, the mean A - S is -0.01 R over 3 trades.
- Feed: the free feed's stop level differs from consolidated by -0.11 dollars per share on average (positive = free feed's stop is further from entry); S - O mean -0.02 R.

Missed signals (no order went out), engine result on the free feed: 2026-10-29 -1.01 R, total -1.01 R.

Small samples: with 15 trades or fewer the standard error is large, so read these as a description of what happened, not as a measured cost.
