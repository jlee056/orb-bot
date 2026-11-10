# When did orb5's paper entries fill? (inferred from prices)

Built by `entry_timing.py`. The rule is to enter at the 9:35 bar's open. The bot submits its order about 9:36:05 (it waits for the 9:35 bar to exist in the data) and Alpaca's paper simulator fills it later. The fill times themselves are not in the log, so this infers them from prices: for each trade, which minute's open is the bot's entry price closest to. "Worse" is dollars per share, positive = worse for the trade.

| Date | Side | Entry | Closest open | Worse than 9:35 open | Worse than 9:36 open | Worse than 9:37 open |
|---|---|---|---|---|---|---|
| 2026-10-15 | short | 717.56 | 9:36 | +0.18 | +0.03 | +0.96 |
| 2026-10-16 | short | 723.18 | 9:37 | +1.03 | -0.17 | +0.15 |
| 2026-10-19 | short | 719.42 | 9:35 | +0.02 | -0.09 | +0.40 |
| 2026-10-20 | short | 713.40 | 9:35 | +0.01 | +0.01 | +0.72 |
| 2026-10-21 | short | 721.36 | 9:36 | +1.00 | +0.11 | +0.18 |
| 2026-10-22 | long | 713.38 | 9:38 | -0.67 | -0.42 | -0.28 |
| 2026-10-23 | long | 701.69 | 9:39 | -0.56 | -0.48 | -0.27 |
| 2026-10-30 | short | 694.32 | 9:36 | +0.29 | +0.12 | +1.12 |
| 2026-11-02 | short | 694.25 | 9:38 | +0.84 | +0.67 | +0.35 |
| 2026-11-03 | long | 685.58 | 9:35 | +0.06 | +0.09 | -0.24 |
| 2026-11-04 | short | 689.74 | 9:36 | -1.63 | -0.38 | +0.72 |
| 2026-11-05 | short | 675.95 | 9:37 | +2.36 | +2.02 | +0.12 |
| 2026-11-06 | short | 656.92 | 9:35 | -0.47 | -0.97 | +0.80 |
| 2026-11-09 | long | 667.07 | 9:38 | +1.34 | +0.44 | -0.43 |

- Average entry vs the 9:35 open: +0.27 dollars per share worse (average size 0.75). Vs the 9:36 open: +0.07 (size 0.43).
- 8 of 14 entries sit closest to the 9:35 or 9:36 open; 6 sit closest to the 9:37 open or later (2026-10-16, 2026-10-22, 2026-10-23, 2026-11-02, 2026-11-05, 2026-11-09), so those orders probably filled a minute or more after they were submitted.

Reading: submission at 9:36:05 explains the average. The biggest misses come on days the price ran quickly from the open, and there the entry looks like a 9:37 or 9:38 price. Sending the order at about 9:35:05 would remove the first minute only. The rest looks like paper-simulator fill time (a one-share test on 2026-10-12 took 100 seconds to fill), which a real broker would not have. Small sample and an inference from prices: the broker's fill timestamps would settle it.
