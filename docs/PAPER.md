# Paper trading record (Alpaca, QQQ)

Orders the bot actually placed in an Alpaca **paper** account: practice money, real order handling. It trades QQQ shares because Alpaca has no futures, using the same frozen settings and the same engine as the backtest. This page is rebuilt automatically after every close by `alpaca_bot.py` and `paper_report.py`.

Each trade is sized to risk about $75. The "$5,000 account" column shows what the same trade would have made with only $5,000 of cash and no borrowing.

Paper fills are optimistic: Alpaca's simulator does not model slippage or market impact.

**Days logged:** 14 (2026-10-12 to 2026-10-29)  
**Trades closed:** 0  
**Missed signals:** 1 (the engine saw a breakout but no order went out)  

20 more trades needed before this record means much. With fewer than 20 trades, any result is mostly luck.

## Last 20 sessions

| Date | Outcome | Shares | Entry | Stop | Target | Exit | Result (R) | Practice profit | $5,000 account |
|---|---|---|---|---|---|---|---|---|---|
| 2026-10-29 | MISSED: engine traded, no order sent |  |  |  |  |  |  |  |  |
| 2026-10-28 | Skipped (trend filter) |  |  |  |  |  |  |  |  |
| 2026-10-27 | Skipped (trend filter) |  |  |  |  |  |  |  |  |
| 2026-10-26 | Skipped (trend filter) |  |  |  |  |  |  |  |  |
| 2026-10-23 | Skipped (trend filter) |  |  |  |  |  |  |  |  |
| 2026-10-22 | Skipped (trend filter) |  |  |  |  |  |  |  |  |
| 2026-10-21 | Skipped (trend filter) |  |  |  |  |  |  |  |  |
| 2026-10-20 | Skipped (trend filter) |  |  |  |  |  |  |  |  |
| 2026-10-19 | Skipped (trend filter) |  |  |  |  |  |  |  |  |
| 2026-10-16 | Skipped (trend filter) |  |  |  |  |  |  |  |  |
| 2026-10-15 | Skipped (trend filter) |  |  |  |  |  |  |  |  |
| 2026-10-14 | Broke down first |  |  |  |  |  |  |  |  |
| 2026-10-13 | No breakout |  |  |  |  |  |  |  |  |
| 2026-10-12 | No breakout |  |  |  |  |  |  |  |  |

## Other orders in this account

Everything else that happened in the account: connection tests and anything not placed by the strategy. These are logged here so the record is complete, but they are **not** strategy trades and are left out of the win rate and profit figures above.

| Date | Time (ET) | Kind | Shares | Bought | Sold | Profit | What it was |
|---|---|---|---|---|---|---|---|
| 2026-10-12 | 09:32 | Test | 1 | 747.83 | 747.86 | $+0.03 | Connection test. Buy filled after 100 seconds, stop and target went live, closed by the test script. First fill in the account. |
| 2026-10-12 | 09:31 | Test | 1 |  |  |  | Connection test. Bracket order accepted, then cancelled after 8 seconds before it filled. |

Profit from these orders: $+0.03. Full list: [`paper/other_orders.csv`](../paper/other_orders.csv).

Full log: [`paper/alpaca_trades.csv`](../paper/alpaca_trades.csv). The `sim_outcome` and `sim_R` columns there show what the engine expected for the same day, so broker fills can be checked against it. Background: [logbook](LOGBOOK.md). Futures forward record: [FORWARD.md](FORWARD.md).
