# Forward record

What the bot would have done each trading day since the settings were frozen on 2026-10-12. This page is rebuilt automatically after every close by `forward_run.py` and `forward_report.py`. No orders are placed; prices are Yahoo's NQ futures data, which runs about 10 minutes late. The log replays finished sessions, so the delay does not affect it.

**Days logged:** 15 (2026-10-12 to 2026-10-30)  
**Signals taken:** 0  

20 more signals needed before this record says anything about the backtest. With fewer than 20 trades, any result is mostly luck.

## Last 20 sessions

| Date | Outcome | Entry | Stop | Target | Exit | Result (R) | Profit, 1 contract | Over $75 risk budget |
|---|---|---|---|---|---|---|---|---|
| 2026-10-30 | Skipped (trend filter) |  |  |  |  |  |  |  |
| 2026-10-29 | Skipped (trend filter) |  |  |  |  |  |  |  |
| 2026-10-28 | Skipped (trend filter) |  |  |  |  |  |  |  |
| 2026-10-27 | Skipped (trend filter) |  |  |  |  |  |  |  |
| 2026-10-26 | Skipped (trend filter) |  |  |  |  |  |  |  |
| 2026-10-23 | Skipped (trend filter) |  |  |  |  |  |  |  |
| 2026-10-22 | Skipped (trend filter) |  |  |  |  |  |  |  |
| 2026-10-21 | Skipped (trend filter) |  |  |  |  |  |  |  |
| 2026-10-20 | Skipped (trend filter) |  |  |  |  |  |  |  |
| 2026-10-19 | Skipped (trend filter) |  |  |  |  |  |  |  |
| 2026-10-16 | Skipped (trend filter) |  |  |  |  |  |  |  |
| 2026-10-15 | Skipped (trend filter) |  |  |  |  |  |  |  |
| 2026-10-14 | Broke down first |  |  |  |  |  |  |  |
| 2026-10-13 | No breakout |  |  |  |  |  |  |  |
| 2026-10-12 | No breakout |  |  |  |  |  |  |  |

Settings in use: `00c5314f` (a hash of the strategy settings; a new value means the settings changed).

Full log: [`forward/forward_log.csv`](../forward/forward_log.csv). Background: [logbook](LOGBOOK.md).
