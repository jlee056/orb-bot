"""Build docs/VARIANTS.md and its chart: the three variants (variants.py) side by side.

Reads each variant's own paper log (Alpaca, QQQ) and forward log (Yahoo, NQ). Nothing is
mixed: every variant's numbers come from its own files only.

Run:  python variants_report.py
"""
import os

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
import matplotlib.ticker
import numpy as np
import pandas as pd

import make_charts as mc
import variants as VS

HERE = os.path.dirname(os.path.abspath(__file__))
OUT = os.path.join(HERE, "docs", "VARIANTS.md")
RULES = {
    "base": "60-minute range, long only, stop at the range midpoint, target half the range, "
            "only when QQQ is above its 20-day average",
    "orb5": "first 5-minute candle up: buy at 9:35; down: sell short. Stop at the candle's far side, "
            "target 10 R or the close. No trend filter",
    "both60": "base rules, plus a short on a downside break. Longs need QQQ above its 20-day average, shorts below",
}


def read(path):
    if not os.path.isfile(path) or os.path.getsize(path) == 0:
        return pd.DataFrame()
    return pd.read_csv(path, dtype={"config_id": str})


def drawdown(r):
    eq = np.concatenate([[0], np.cumsum(r)])
    return float((np.maximum.accumulate(eq) - eq).max())


def status(v, t):
    """Where the variant stands against the rules fixed before it started."""
    n, bt = len(t), VS.BACKTEST[v.name]
    if n and n >= 100 and t["R"].mean() <= VS.STOP_AVG_R:
        return f"**Stop:** average {t['R'].mean():+.2f} R after {n} trades"
    limit = VS.STOP_DD_MULT * bt["max_dd_usd"] / 75
    if n and drawdown(t["R"].to_numpy()) > limit:
        return f"**Stop:** drawdown beyond {limit:.1f} R"
    nxt = next((c for c in VS.CHECKPOINTS if c > n), None)
    return f"running, next review at {nxt} trades" if nxt else "reached 312 trades: ready to judge"


def chart(series, theme):
    mc.T = mc.THEMES[theme]
    T = mc.T
    mc.style()
    fig, ax = plt.subplots(figsize=(10, 4.6))
    fig.subplots_adjust(left=0.075, right=0.745, top=0.78, bottom=0.14)
    ax.xaxis.set_major_locator(matplotlib.ticker.MaxNLocator(integer=True))
    mc.titled(fig, "Paper trades by variant", "Cumulative result in R (1 R = the amount risked), by trade number")
    colors = {"base": T["s1"], "orb5": T["s2"], "both60": T["s3"]}
    most = max(len(t) for _, t in series)
    for name, t in series:
        exp = VS.BACKTEST[name]["avg_r"]
        xs = np.arange(0, most + 1)
        ax.plot(xs, exp * xs, color=colors[name], lw=1, ls="--", alpha=0.7)
        if len(t):
            cum = np.concatenate([[0], t["R"].cumsum().to_numpy()])
            ax.plot(np.arange(len(cum)), cum, color=colors[name], lw=2, marker="o", ms=4, mec=T["surface"],
                    mew=1, label=f"{name}: {cum[-1]:+.2f} R ({len(t)})")
    ax.plot([], [], color=T["muted"], lw=1, ls="--", label="Backtest average")
    ax.axhline(0, color=T["muted"], lw=1)
    ax.set_xlim(0, max(most, 5))
    ax.set_xlabel("Trades")
    ax.set_ylabel("Cumulative R")
    ax.legend(loc="upper left", bbox_to_anchor=(1.01, 0.75), fontsize=9.5)
    mc.save(fig, "variants", theme)


def main():
    L = ["# Variants, side by side", "",
         "Three versions of the strategy run at the same time, each in its own Alpaca paper account, so data "
         "builds up about four times faster than with the base rules alone. Their rules were fixed on 2026-10-14 "
         "before the first trade (see the [logbook](LOGBOOK.md)). This page is rebuilt automatically after every "
         "close by `variants_report.py`.", "",
         "| Variant | Rules |", "|---|---|"]
    L += [f"| `{v.name}` | {RULES[v.name]} |" for v in VS.ALL.values()]
    L += ["", "## Paper accounts (Alpaca, QQQ)", "",
          "| Variant | Days | Trades | Win rate | Avg R | Total R | Backtest avg R | Fill gap (R) | Status |",
          "|---|---|---|---|---|---|---|---|---|"]
    series = []
    for v in VS.ALL.values():
        log = read(v.path("paper_log"))
        t = log[log["profit"].notna() & log["R"].notna()] if len(log) else log
        bt = VS.BACKTEST[v.name]
        series.append((v.name, t))
        if not len(t):
            L.append(f"| `{v.name}` | {len(log)} | 0 | | | | {bt['avg_r']:+.3f} | | {status(v, t)} |")
            continue
        both = t[t["sim_R"].notna()]
        gap = f"{(both['R'] - both['sim_R']).mean():+.2f}" if len(both) else ""
        L.append(f"| `{v.name}` | {len(log)} | {len(t)} | {(t['profit'] > 0).mean() * 100:.0f}% | "
                 f"{t['R'].mean():+.2f} | {t['R'].sum():+.2f} | {bt['avg_r']:+.3f} | {gap} | {status(v, t)} |")
    L += ["", "*Fill gap* is the broker's result minus what the engine expected on the same day. Alpaca's paper "
          "fills do not charge slippage, so a gap near zero is expected; real trading would be worse.", ""]
    if any(len(t) for _, t in series):
        for theme in ("light", "dark"):
            chart(series, theme)
        L += ['<picture>',
              '  <source media="(prefers-color-scheme: dark)" srcset="charts/variants-dark.png">',
              '  <img src="charts/variants.png" alt="Cumulative paper result in R for each variant, with the backtest '
              'average as a dashed line" width="900">',
              '</picture>', ""]

    L += ["## Forward log (Yahoo, NQ futures, no orders)", "",
          "| Variant | Days | Signals | Win rate | Avg R | Total R |", "|---|---|---|---|---|---|"]
    for v in VS.ALL.values():
        log = read(v.path("fwd_log"))
        t = log[log["R"].notna()] if len(log) else log
        if not len(t):
            L.append(f"| `{v.name}` | {len(log)} | 0 | | | |")
            continue
        L.append(f"| `{v.name}` | {len(log)} | {len(t)} | {(t['R'] > 0).mean() * 100:.0f}% | "
                 f"{t['R'].mean():+.2f} | {t['R'].sum():+.2f} |")

    L += ["", "## Rules for judging, fixed in advance", "",
          f"- Review each variant at {', '.join(str(c) for c in VS.CHECKPOINTS)} trades. Nothing is retuned from "
          "this record; a change of rules would be a new variant with a new settings hash.",
          "- 312 trades is roughly what it takes to tell an average of +0.1 R from zero (95% confidence, "
          "with the spread of results the backtest shows).",
          f"- A variant stops if its average is {VS.STOP_AVG_R:+.2f} R or worse after 100 trades, or if its "
          f"drawdown passes {VS.STOP_DD_MULT}× the largest drawdown in its backtest.",
          "- The backtest expects about "
          + ", ".join(f"{bt['per_year']} trades a year for `{k}`" for k, bt in VS.BACKTEST.items()) + ".", "",
          "Logs: " + ", ".join(f"[`{v.paper_log}`](../{v.paper_log})" for v in VS.ALL.values()) + "; "
          + ", ".join(f"[`{v.fwd_log}`](../{v.fwd_log})" for v in VS.ALL.values()) + ".", ""]
    with open(OUT, "w", encoding="utf-8", newline="\n") as fh:
        fh.write("\n".join(L))
    print(f"wrote docs/VARIANTS.md ({', '.join(f'{n}: {len(t)} trades' for n, t in series)})")


if __name__ == "__main__":
    main()
