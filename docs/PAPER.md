# Paper trading record (Alpaca, QQQ)

Orders the bot actually placed in an Alpaca **paper** account: practice money, real order handling. It trades QQQ shares because Alpaca has no futures, using the same frozen settings and the same engine as the backtest. This page is rebuilt automatically after every close by `alpaca_bot.py` and `paper_report.py`.

Each trade is sized to risk about $75. The "$5,000 account" column shows what the same trade would have made with only $5,000 of cash and no borrowing.

Paper fills are optimistic: Alpaca's simulator does not model slippage or market impact.

No sessions logged yet.

Full log: [`paper/alpaca_trades.csv`](../paper/alpaca_trades.csv). The `sim_outcome` and `sim_R` columns there show what the engine expected for the same day, so broker fills can be checked against it. Background: [logbook](LOGBOOK.md). Futures forward record: [FORWARD.md](FORWARD.md).
