"""Build docs/FORWARD.md and its chart from forward/forward_log.csv.

Run:  python forward_report.py
"""
import os

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
import matplotlib.ticker
import numpy as np
import pandas as pd

import make_charts as mc
from forward_run import FORWARD_START, LOG

HERE = os.path.dirname(os.path.abspath(__file__))
OUT = os.path.join(HERE, "docs", "FORWARD.md")
BACKTEST_TRADES = os.path.join(HERE, "docs", "data", "trades_new_settings.csv")
NEEDED = 20   # signals before the forward record is compared with the backtest

OUTCOMES = {"target": "Hit target", "stop": "Hit stop", "eod": "Closed at end of day", "breakeven": "Breakeven stop",
            "no_breakout": "No breakout", "downside_break": "Broke down first", "filtered": "Skipped (trend filter)",
            "no_room": "No room to target"}


def chart(t, exp_r, sd_r, theme, name="forward", title="Forward record against what the backtest predicts",
          label="Forward record", short="Forward"):
    mc.T = mc.THEMES[theme]
    T = mc.T
    mc.style()
    n = len(t)
    fig, ax = plt.subplots(figsize=(10, 4.6))
    fig.subplots_adjust(left=0.075, right=0.745, top=0.78, bottom=0.14)
    ax.xaxis.set_major_locator(matplotlib.ticker.MaxNLocator(integer=True))
    mc.titled(fig, title,
              "Cumulative result in R (1 R = the amount risked on a trade), by signal number")
    xs = np.arange(0, max(n, NEEDED) + 1)
    ax.fill_between(xs, exp_r * xs - 2 * sd_r * np.sqrt(xs), exp_r * xs + 2 * sd_r * np.sqrt(xs),
                    color=T["band"], lw=0, label="Backtest: normal range")
    ax.plot(xs, exp_r * xs, color=T["muted"], lw=2, label="Backtest: average")
    cum = np.concatenate([[0], t["R"].cumsum().to_numpy()])
    ax.plot(np.arange(n + 1), cum, color=T["s1"], lw=2, marker="o", ms=6, mec=T["surface"], mew=1.5,
            label=label)
    ax.annotate(f"{short}: {cum[-1]:+.2f} R\nafter {n} signal{'s' if n != 1 else ''}", (n, cum[-1]),
                xytext=(10, -22), textcoords="offset points", fontsize=9.5, va="top", color=T["text"],
                annotation_clip=False)
    ax.axhline(0, color=T["muted"], lw=1)
    ax.set_xlim(0, xs[-1])
    ax.set_xlabel("Signals taken")
    ax.set_ylabel("Cumulative R")
    ax.legend(loc="upper left", bbox_to_anchor=(1.01, 0.55), fontsize=9.5)
    mc.save(fig, name, theme)


def main():
    log = pd.read_csv(LOG, dtype={"config_id": str}) if os.path.isfile(LOG) else pd.DataFrame(columns=["date"])
    t = log[log["entry"].notna()].copy() if len(log) else log
    n = len(t)
    bt = pd.read_csv(BACKTEST_TRADES)
    exp_r, sd_r = bt["R"].mean(), bt["R"].std()

    L = ["# Forward record", "",
         "What the bot would have done each trading day since the settings were frozen on "
         f"{FORWARD_START.isoformat()}. This page is rebuilt automatically after every close by "
         "`forward_run.py` and `forward_report.py`. No orders are placed; prices are Yahoo's NQ futures "
         "data, which runs about 10 minutes late. The log replays finished sessions, so the delay does not affect it.",
         ""]
    if not len(log):
        L += ["No sessions logged yet.", ""]
    else:
        L += [f"**Days logged:** {len(log)} ({log['date'].iloc[0]} to {log['date'].iloc[-1]})  ",
              f"**Signals taken:** {n}  "]
        if n:
            wins = (t["usd_1c"] > 0).sum()
            L += [f"**Win rate:** {wins / n * 100:.0f}% ({wins} of {n})  ",
                  f"**Average result:** {t['R'].mean():+.2f} R per trade (backtest: {exp_r:+.2f} R)  ",
                  f"**Profit, 1 contract, after costs:** {mc.money(t['usd_1c'].sum())}  "]
        L += [""]
        if n < NEEDED:
            L += [f"{NEEDED - n} more signal{'s' if NEEDED - n != 1 else ''} needed before this record says "
                  f"anything about the backtest. With fewer than {NEEDED} trades, any result is mostly luck.", ""]
        if n:
            for theme in ("light", "dark"):
                chart(t, exp_r, sd_r, theme)
            L += ['<picture>',
                  '  <source media="(prefers-color-scheme: dark)" srcset="charts/forward-dark.png">',
                  '  <img src="charts/forward.png" alt="Cumulative forward result in R against the backtest average '
                  'and normal range" width="900">',
                  '</picture>', "",
                  "The grey band is where the backtest says the record should sit about 95% of the time. "
                  "A forward line that stays inside it is behaving as tested.", ""]
        L += ["## Last 20 sessions", "",
              "| Date | Outcome | Entry | Stop | Target | Exit | Result (R) | Profit, 1 contract | Over $75 risk budget |",
              "|---|---|---|---|---|---|---|---|---|"]
        for r in log.tail(20).iloc[::-1].itertuples():
            traded = pd.notna(r.entry)
            cells = [r.date, OUTCOMES.get(r.outcome, r.outcome)]
            if traded:
                cells += [f"{r.entry:,.2f}", f"{r.stop:,.2f}", f"{r.target:,.2f}", f"{r.exit:,.2f}", f"{r.R:+.2f}",
                          mc.money(r.usd_1c), "Yes" if r.over_risk == "Y" else "No"]
            else:
                cells += [""] * 7
            L.append("| " + " | ".join(cells) + " |")
        L += ["", f"Settings in use: `{'`, `'.join(sorted(log['config_id'].unique()))}` "
                  "(a hash of the strategy settings; a new value means the settings changed).", ""]
    L += ["Full log: [`forward/forward_log.csv`](../forward/forward_log.csv). "
          "Background: [logbook](LOGBOOK.md).", ""]
    with open(OUT, "w", encoding="utf-8", newline="\n") as fh:
        fh.write("\n".join(L))
    print(f"wrote docs/FORWARD.md ({len(log)} days, {n} signals)")


if __name__ == "__main__":
    main()
