"""Build docs/PAPER.md and its chart from paper/alpaca_trades.csv.

Run:  python paper_report.py
"""
import os

import pandas as pd

import make_charts as mc
from alpaca_bot import LOG, RISK_USD, SMALL_ACCOUNT
from forward_report import BACKTEST_TRADES, NEEDED, chart

HERE = os.path.dirname(os.path.abspath(__file__))
OUT = os.path.join(HERE, "docs", "PAPER.md")
OTHER = os.path.join(HERE, "paper", "other_orders.csv")   # orders in the account that the strategy did not choose

OUTCOMES = {"target": "Hit target", "stop": "Hit stop", "eod": "Closed before the bell",
            "no_breakout": "No breakout", "downside_break": "Broke down first", "filtered": "Skipped (trend filter)",
            "no_room": "No room to target", "missed": "MISSED: engine traded, no order sent",
            "order_not_filled": "Order not filled", "still_open": "Position still open", "no_data": "No data"}


def main():
    log = pd.read_csv(LOG, dtype={"config_id": str}) if os.path.isfile(LOG) else pd.DataFrame(columns=["date"])
    t = log[log["profit"].notna()].copy() if len(log) else log
    n = len(t)
    bt = pd.read_csv(BACKTEST_TRADES)
    exp_r, sd_r = bt["R"].mean(), bt["R"].std()

    L = ["# Paper trading record (Alpaca, QQQ)", "",
         "Orders the bot actually placed in an Alpaca **paper** account: practice money, real order handling. "
         "It trades QQQ shares because Alpaca has no futures, using the same frozen settings and the same engine as "
         "the backtest. This page is rebuilt automatically after every close by `alpaca_bot.py` and `paper_report.py`.",
         "",
         f"Each trade is sized to risk about ${RISK_USD:.0f}. The \"$5,000 account\" column shows what the same trade "
         f"would have made with only ${SMALL_ACCOUNT:,.0f} of cash and no borrowing.", "",
         "Paper fills are optimistic: Alpaca's simulator does not model slippage or market impact.", ""]
    if not len(log):
        L += ["No sessions logged yet.", ""]
    else:
        L += [f"**Days logged:** {len(log)} ({log['date'].iloc[0]} to {log['date'].iloc[-1]})  ",
              f"**Trades closed:** {n}  "]
        if n:
            wins = (t["profit"] > 0).sum()
            L += [f"**Win rate:** {wins / n * 100:.0f}% ({wins} of {n})  ",
                  f"**Average result:** {t['R'].mean():+.2f} R per trade (NQ backtest: {exp_r:+.2f} R)  ",
                  f"**Practice profit:** {mc.money(t['profit'].sum())}  ",
                  f"**Same trades in a $5,000 account:** {mc.money(t['profit_5k'].sum())}  "]
        missed = int((log["outcome"] == "missed").sum())
        if missed:
            L += [f"**Missed signals:** {missed} (the engine saw a breakout but no order went out)  "]
        L += [""]
        if n < NEEDED:
            L += [f"{NEEDED - n} more trade{'s' if NEEDED - n != 1 else ''} needed before this record means much. "
                  f"With fewer than {NEEDED} trades, any result is mostly luck.", ""]
        if n:
            for theme in ("light", "dark"):
                chart(t, exp_r, sd_r, theme, name="paper", title="Paper trades against what the backtest predicts",
                      label="Paper trades (QQQ)", short="Paper")
            L += ['<picture>',
                  '  <source media="(prefers-color-scheme: dark)" srcset="charts/paper-dark.png">',
                  '  <img src="charts/paper.png" alt="Cumulative paper-trading result in R against the backtest average '
                  'and normal range" width="900">',
                  '</picture>', "",
                  "The grey band is the range the NQ futures backtest predicts about 95% of the time. "
                  "QQQ is a different instrument on the same index, so treat it as a guide.", ""]
        L += ["## Last 20 sessions", "",
              "| Date | Outcome | Shares | Entry | Stop | Target | Exit | Result (R) | Practice profit | $5,000 account |",
              "|---|---|---|---|---|---|---|---|---|---|"]
        for r in log.tail(20).iloc[::-1].itertuples():
            cells = [r.date, OUTCOMES.get(r.outcome, r.outcome)]
            if pd.notna(r.entry):
                def num(x, fmt):
                    return format(x, fmt) if pd.notna(x) else ""
                cells += [num(r.shares, ".0f"), num(r.entry, ",.2f"), num(r.stop, ",.2f"), num(r.target, ",.2f"),
                          num(r.exit, ",.2f"), num(r.R, "+.2f"),
                          mc.money(r.profit) if pd.notna(r.profit) else "",
                          mc.money(r.profit_5k) if pd.notna(r.profit_5k) else ""]
            else:
                cells += [""] * 8
            L.append("| " + " | ".join(cells) + " |")
        L += [""]
    if os.path.isfile(OTHER):
        other = pd.read_csv(OTHER, dtype=str).fillna("")
        if len(other):
            total = pd.to_numeric(other["profit"], errors="coerce").sum()
            L += ["## Other orders in this account", "",
                  "Everything else that happened in the account: connection tests and anything not placed by the strategy. "
                  "These are logged here so the record is complete, but they are **not** strategy trades and are "
                  "left out of the win rate and profit figures above.", "",
                  "| Date | Time (ET) | Kind | Shares | Bought | Sold | Profit | What it was |",
                  "|---|---|---|---|---|---|---|---|"]
            for r in other.iloc[::-1].itertuples():
                profit = f"${float(r.profit):+,.2f}" if r.profit else ""
                L.append(f"| {r.date} | {r.time_et} | {r.kind.title()} | {r.shares} | {r.buy} | {r.sell} | {profit} | {r.note} |")
            L += ["", f"Profit from these orders: ${total:+,.2f}. Full list: "
                      "[`paper/other_orders.csv`](../paper/other_orders.csv).", ""]
    L += ["Full log: [`paper/alpaca_trades.csv`](../paper/alpaca_trades.csv). The `sim_outcome` and `sim_R` columns "
          "there show what the engine expected for the same day, so broker fills can be checked against it. "
          "Background: [logbook](LOGBOOK.md). Futures forward record: [FORWARD.md](FORWARD.md).", ""]
    with open(OUT, "w", encoding="utf-8", newline="\n") as fh:
        fh.write("\n".join(L))
    print(f"wrote docs/PAPER.md ({len(log)} days, {n} trades)")


if __name__ == "__main__":
    main()
