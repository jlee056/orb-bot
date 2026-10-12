"""Build every chart and data table used in docs/LOGBOOK.md.

Run:  python make_charts.py
Out:  docs/charts/*.png (light) and *-dark.png, docs/data/*.csv

Everything is recomputed from orb_engine.py, so the logbook can be reproduced
from the raw data (see get_data.py).
"""
import os

import matplotlib
matplotlib.use("Agg")
import matplotlib.dates as mdates
import matplotlib.pyplot as plt
import numpy as np
import pandas as pd
from matplotlib.colors import LinearSegmentedColormap

import backtest
import orb_engine as E

HERE = os.path.dirname(os.path.abspath(__file__))
CHARTS = os.path.join(HERE, "docs", "charts")
TABLES = os.path.join(HERE, "docs", "data")

THEMES = {
    "light": dict(surface="#fcfcfb", text="#0b0b0b", muted="#52514e", grid="#e6e5e1",
                  s1="#2a78d6", s2="#eb6834", s3="#1baf7a", band="#f0efec",
                  ramp=["#cde2fb", "#86b6ef", "#3987e5", "#1c5cab", "#0d366b"]),
    "dark": dict(surface="#1a1a19", text="#ffffff", muted="#c3c2b7", grid="#383835",
                 s1="#3987e5", s2="#d95926", s3="#199e70", band="#2a2a28",
                 ramp=["#0d366b", "#184f95", "#256abf", "#5598e7", "#b7d3f6"]),
}
T = THEMES["light"]

# Settings before the 2026-10-12 research loop (config.py at commit a4e2db6).
OLD = E.P(or_min=30, cutoff=11 * 60, stop_mode="atr", stop_k=0.4, target_mode="range", target_k=1.0,
          breakeven=0.75, vix_min=13, ema_days=3)
OLD_LIVE = E.replace(OLD, f_friday=True, f_vix=True, f_ema=True, f_gap=True, f_range=True)
NEW = E.replace(backtest.params_from_config(), oversize="min1", monthly_cap=0)
PERIODS = ["2023", "2024", "2025", "2026H1", "2026H2"]
PERIOD_LABELS = ["2023", "2024", "2025", "Jan–Apr\n2026", "Aug–Oct\n2026"]


# ---------------------------------------------------------------------------
# Styling helpers
# ---------------------------------------------------------------------------

def style():
    plt.rcParams.update({
        "figure.facecolor": T["surface"], "axes.facecolor": T["surface"], "savefig.facecolor": T["surface"],
        "font.family": "DejaVu Sans", "font.size": 10.5,
        "text.color": T["text"], "axes.labelcolor": T["muted"],
        "xtick.color": T["muted"], "ytick.color": T["muted"],
        "axes.edgecolor": T["grid"], "axes.linewidth": 1,
        "axes.spines.top": False, "axes.spines.right": False, "axes.spines.left": False,
        "axes.grid": True, "axes.grid.axis": "y", "grid.color": T["grid"], "grid.linewidth": 1,
        "axes.axisbelow": True, "xtick.major.size": 0, "ytick.major.size": 0,
        "legend.frameon": False,
    })


def titled(fig, title, subtitle):
    h = fig.get_figheight()
    fig.text(0.012, 1 - 0.14 / h, title, fontsize=14, fontweight="bold", va="top", ha="left", color=T["text"])
    fig.text(0.012, 1 - 0.50 / h, subtitle, fontsize=10.5, va="top", ha="left", color=T["muted"])


def save(fig, name, theme):
    suffix = "" if theme == "light" else "-dark"
    fig.savefig(os.path.join(CHARTS, f"{name}{suffix}.png"), dpi=160)
    plt.close(fig)


def money(x, _=None):
    return f"-${abs(x):,.0f}" if x < 0 else f"${x:,.0f}"


# ---------------------------------------------------------------------------
# Data
# ---------------------------------------------------------------------------

def trades(res):
    t = res[res["dir"] != 0].copy()
    t["date"] = pd.to_datetime(t["date"])
    t["R"] = t["pts"] / t["risk"]
    t["risk_usd"] = t["risk"] * E.MULT
    return t


def compute():
    ds = E.datasets()
    all_days = [d for k in PERIODS for d in ds[k]]
    out = {"ds": ds, "all": all_days}
    out["new"] = trades(E.run(all_days, NEW))
    out["old"] = trades(E.run(all_days, OLD))
    out["old_live"] = trades(E.run(all_days, OLD_LIVE))

    rows = []
    for k, lab in zip(PERIODS, PERIOD_LABELS):
        for name, p in (("Old settings, no filters", OLD), ("Old settings, all filters", OLD_LIVE),
                        ("New settings", NEW)):
            rows.append({"period": k, "config": name, **E.stats(E.run(ds[k], p))})
    for name, p in (("Old settings, no filters", OLD), ("Old settings, all filters", OLD_LIVE),
                    ("New settings", NEW)):
        rows.append({"period": "ALL", "config": name, **E.stats(E.run(all_days, p))})
    out["periods"] = pd.DataFrame(rows)

    # Filter attribution. Trend filter: measured with every filter off. The other four:
    # measured on the trades that already pass the trend filter (the adopted setup).
    no_filters = trades(E.run(all_days, E.replace(NEW, f_ema=False, f_vix=False)))
    with_ema = trades(E.run(all_days, E.replace(NEW, f_vix=False, vix_min=13)))
    frows = []
    for base, key, label in ((no_filters, "below_ema", "Close below\n20-day EMA"), (with_ema, "friday", "Friday"),
                             (with_ema, "vix_low", "VIX under 13"), (with_ema, "gap", "Gap up over 0.7%"),
                             (with_ema, "range_wide", "Range over 0.8%")):
        m = base["flags"].str.contains(key)
        frows.append({"filter": label, "blocked_n": int(m.sum()), "blocked_avgR": base["R"][m].mean(),
                      "kept_n": int((~m).sum()), "kept_avgR": base["R"][~m].mean()})
    out["filters"] = pd.DataFrame(frows)

    # Robustness grid around the chosen setting.
    ors, tgts = [30, 45, 60, 75, 90], [0.25, 0.35, 0.5, 0.75, 1.0]
    grid = np.zeros((len(tgts), len(ors)))
    grows = []
    for j, om in enumerate(ors):
        for i, tk in enumerate(tgts):
            s = E.stats(E.run(all_days, E.replace(NEW, or_min=om, target_k=tk, cutoff=max(720, 570 + om + 60))))
            grid[i, j] = s["avgR"]
            grows.append({"range_min": om, "target_x_range": tk, **s})
    out["grid"], out["grid_axes"], out["grid_rows"] = grid, (ors, tgts), pd.DataFrame(grows)

    # Account-size sweep: share of signals one contract fits inside a 1.5% budget.
    arows = []
    for acct in (2000, 5000, 7500, 10000, 12500, 15000, 20000, 25000):
        s = E.stats(E.run(all_days, E.replace(NEW, account=acct, oversize="skip")))
        arows.append({"account": acct, "trades_taken": s["n"], "share": s["n"] / len(out["new"]),
                      "usd": s.get("usd", 0)})
    out["accounts"] = pd.DataFrame(arows)

    rng = np.random.default_rng(0)
    out["mc"] = rng.choice(out["new"]["usd"].to_numpy(), (20000, 70)).sum(axis=1)
    return out


# ---------------------------------------------------------------------------
# Charts
# ---------------------------------------------------------------------------

# Stretches with no price data between the three sources.
GAPS = [(pd.Timestamp("2025-12-12"), pd.Timestamp("2026-02-08")),
        (pd.Timestamp("2026-04-16"), pd.Timestamp("2026-08-20"))]


def gapped(dates, values):
    """Break a series at the data gaps so no line is drawn across them."""
    x, y = list(dates), list(map(float, values))
    for g0, g1 in GAPS:
        before = [i for i, v in enumerate(x) if v < g0]
        if before and len(before) < len(x):
            k = before[-1] + 1
            x[k:k] = [g0, g0 + pd.Timedelta(days=1), g1]
            y[k:k] = [y[k - 1], np.nan, y[k - 1]]
    return x, y


def chart_equity(d, theme):
    fig, (ax, ax2) = plt.subplots(2, 1, figsize=(10, 6.6), sharex=True,
                                  gridspec_kw={"height_ratios": [3, 1.15], "hspace": 0.12})
    fig.subplots_adjust(left=0.085, right=0.80, top=0.83, bottom=0.07)
    titled(fig, "The new settings earned nearly twice as much, with less than half the drawdown",
           "Cumulative profit trading 1 MNQ contract per signal, after slippage and commission")
    split = pd.Timestamp("2025-01-01")
    for a in (ax, ax2):
        a.axvspan(split, pd.Timestamp("2026-10-20"), color=T["band"], lw=0, zorder=0)
    series = (("New settings", d["new"], T["s1"]), ("Old settings, all filters", d["old_live"], T["s3"]),
              ("Old settings, no filters", d["old"], T["s2"]))
    ends = []
    for name, t, c in series:
        eq = t["usd"].cumsum()
        x, y = gapped(t["date"], eq)
        ax.step(x, y, where="post", color=c, lw=2, label=name, solid_joinstyle="round")
        ax.plot(t["date"].iloc[-1], eq.iloc[-1], "o", ms=8, color=c, mec=T["surface"], mew=2, zorder=5)
        ends.append([eq.iloc[-1], name, len(t)])
    # Space the end labels so they never overlap.
    ends.sort()
    gap = (ax.get_ylim()[1] - ax.get_ylim()[0]) * 0.11
    ys = [e[0] for e in ends]
    for i in range(1, len(ys)):
        ys[i] = max(ys[i], ys[i - 1] + gap)
    for y, (v, name, n) in zip(ys, ends):
        ax.annotate(f"{name}\n{money(v)} · {n} trades", (pd.Timestamp("2026-10-12"), v),
                    xytext=(pd.Timestamp("2026-11-12"), y), fontsize=9.5, va="center", color=T["text"],
                    annotation_clip=False,
                    arrowprops=dict(arrowstyle="-", color=T["muted"], lw=0.8, shrinkB=4))
    ax.axhline(0, color=T["muted"], lw=1)
    ax.yaxis.set_major_formatter(plt.FuncFormatter(money))
    ax.text(pd.Timestamp("2023-02-01"), ax.get_ylim()[1], "Tuned on 2023–2024", fontsize=9.5,
            color=T["muted"], va="top")
    ax.text(pd.Timestamp("2025-01-20"), ax.get_ylim()[1], "Held-back test: 2025–2026", fontsize=9.5,
            color=T["muted"], va="top")
    ax.legend(loc="upper left", bbox_to_anchor=(0.0, 0.90), fontsize=9.5, handlelength=1.6)
    for a in (ax, ax2):
        for g0, g1 in GAPS:
            a.axvspan(g0, g1, facecolor=T["surface"], edgecolor=T["grid"], hatch="////", lw=0, zorder=1)
    for g0, g1 in GAPS:
        ax.text(g0 + (g1 - g0) / 2, ax.get_ylim()[0] + 60, "no data", fontsize=8.5, color=T["muted"],
                ha="center", va="bottom", rotation=90)

    t = d["new"]
    eq = t["usd"].cumsum()
    dd = eq - np.maximum(eq.cummax(), 0)
    x, y = gapped(t["date"], dd)
    ax2.fill_between(x, y, 0, step="post", color=T["s1"], alpha=0.18, lw=0)
    ax2.step(x, y, where="post", color=T["s1"], lw=1.5)
    ax2.set_ylim(dd.min() * 1.45, 0)
    ax2.yaxis.set_major_formatter(plt.FuncFormatter(money))
    ax2.set_ylabel("Drawdown", fontsize=9.5)
    ax2.text(pd.Timestamp("2023-02-01"), dd.min() * 1.40, "Drawdown from peak, new settings", fontsize=9.5,
             color=T["muted"], va="bottom")
    worst = dd.idxmin()
    ax2.annotate(f"Deepest: {money(dd.min())}", (t["date"][worst], dd.min()), xytext=(-10, 0),
                 textcoords="offset points", fontsize=9.5, color=T["text"], va="center", ha="right")
    ax2.xaxis.set_major_locator(mdates.MonthLocator(bymonth=(1, 7)))
    ax2.xaxis.set_major_formatter(mdates.DateFormatter("%b %Y"))
    ax2.set_xlim(pd.Timestamp("2023-01-01"), pd.Timestamp("2026-10-20"))
    save(fig, "equity", theme)


def chart_periods(d, theme):
    p = d["periods"]
    fig, ax = plt.subplots(figsize=(10, 4.8))
    fig.subplots_adjust(left=0.075, right=0.985, top=0.77, bottom=0.17)
    titled(fig, "The new settings are profitable in every period, including the held-back ones",
           "Average result per trade, in units of the amount risked (R). Above zero is profitable after costs.")
    names = (("Old settings, no filters", T["s2"]), ("Old settings, all filters", T["s3"]), ("New settings", T["s1"]))
    w, x = 0.22, np.arange(len(PERIODS))
    for k, (name, c) in enumerate(names):
        sub = p[p["config"] == name].set_index("period").loc[PERIODS]
        xs = x + (k - 1) * (w + 0.03)
        ax.bar(xs, sub["avgR"], width=w, color=c, label=name, lw=0)
        for xi, v, n in zip(xs, sub["avgR"], sub["n"]):
            ax.text(xi, v + (0.02 if v >= 0 else -0.02), f"{v:+.2f}", ha="center",
                    va="bottom" if v >= 0 else "top", fontsize=8.5, color=T["text"])
            ax.text(xi, -0.36, f"n={int(n)}", ha="center", va="top", fontsize=8, color=T["muted"])
    ax.axhline(0, color=T["muted"], lw=1)
    ax.axvspan(1.5, 4.5, color=T["band"], lw=0, zorder=0)
    ax.text(4.44, 1.0, "Held-back test", fontsize=9.5, color=T["muted"], va="top", ha="right")
    ax.set_xticks(x, PERIOD_LABELS)
    ax.tick_params(axis="x", pad=18)
    ax.set_ylim(-0.3, 1.05)
    ax.set_ylabel("Average R per trade")
    ax.legend(loc="lower left", ncols=3, fontsize=9.5, bbox_to_anchor=(-0.01, 1.0), borderaxespad=0)
    fig.text(0.012, 0.012, "The two 2026 windows are short (3 to 25 trades each), so their bars are noisy.",
             fontsize=9, color=T["muted"])
    save(fig, "periods", theme)


def chart_filters(d, theme):
    f = d["filters"].iloc[::-1].reset_index(drop=True)
    fig, ax = plt.subplots(figsize=(10, 4.6))
    fig.subplots_adjust(left=0.215, right=0.97, top=0.76, bottom=0.13)
    titled(fig, "The trend filter is the only one that blocks losing trades",
           "Average R of the trades each filter would block versus the trades it would keep (new settings, 2023–2026)")
    y = np.arange(len(f))
    ax.grid(axis="x")
    ax.grid(axis="y", visible=False)
    for yi, r in zip(y, f.itertuples()):
        ax.plot([r.blocked_avgR, r.kept_avgR], [yi, yi], color=T["grid"], lw=3, zorder=1, solid_capstyle="round")
    ax.scatter(f["blocked_avgR"], y, s=120, color=T["s2"], edgecolor=T["surface"], lw=2, zorder=3,
               label="Trades the filter would block")
    ax.scatter(f["kept_avgR"], y, s=120, color=T["s1"], edgecolor=T["surface"], lw=2, zorder=3,
               label="Trades it would keep")
    for yi, r in zip(y, f.itertuples()):
        left = r.blocked_avgR < r.kept_avgR
        ax.text(r.blocked_avgR + (-0.012 if left else 0.012), yi, f"{r.blocked_avgR:+.2f} (n={r.blocked_n})",
                ha="right" if left else "left", va="center", fontsize=9, color=T["text"])
        ax.text(r.kept_avgR + (0.012 if left else -0.012), yi, f"{r.kept_avgR:+.2f}",
                ha="left" if left else "right", va="center", fontsize=9, color=T["text"])
    ax.axvline(0, color=T["muted"], lw=1)
    ax.set_yticks(y, f["filter"])
    ax.tick_params(axis="y", labelcolor=T["text"])
    ax.set_ylim(-0.6, len(f) - 0.4)
    lo, hi = min(f["blocked_avgR"].min(), f["kept_avgR"].min()), max(f["blocked_avgR"].max(), f["kept_avgR"].max())
    ax.set_xlim(lo - 0.13, hi + 0.13)
    ax.set_xlabel("Average R per trade")
    ax.legend(loc="lower left", ncols=2, fontsize=9.5, bbox_to_anchor=(-0.01, 1.0), borderaxespad=0)
    save(fig, "filters", theme)


def chart_grid(d, theme):
    grid, (ors, tgts) = d["grid"], d["grid_axes"]
    fig, ax = plt.subplots(figsize=(8.2, 5.2))
    fig.subplots_adjust(left=0.13, right=0.97, top=0.80, bottom=0.12)
    titled(fig, "The edge is a broad plateau, not one lucky setting",
           "Average R per trade for 25 neighbouring settings. Outlined cell = the setting chosen. (2023–2026)")
    cmap = LinearSegmentedColormap.from_list("seq", T["ramp"])
    vmax = grid.max()
    ax.grid(False)
    for i in range(len(tgts)):
        for j in range(len(ors)):
            v = grid[i, j]
            frac = float(np.clip(v / vmax, 0, 1))
            ax.add_patch(plt.Rectangle((j - 0.47, i - 0.47), 0.94, 0.94, color=cmap(frac), lw=0))
            dark_cell = frac > 0.5 if theme == "light" else frac < 0.5
            ink = "#ffffff" if dark_cell else "#0b0b0b"
            chosen = ors[j] == NEW.or_min and tgts[i] == NEW.target_k
            ax.text(j, i, f"{v:+.2f}", ha="center", va="center", fontsize=11, color=ink,
                    fontweight="bold" if chosen else "normal")
            if chosen:
                ax.add_patch(plt.Rectangle((j - 0.47, i - 0.47), 0.94, 0.94, fill=False, ec=T["text"], lw=2))
    ax.set_xlim(-0.5, len(ors) - 0.5)
    ax.set_ylim(-0.5, len(tgts) - 0.5)
    ax.set_xticks(range(len(ors)), [f"{o} min" for o in ors])
    ax.set_yticks(range(len(tgts)), [f"{t}×" for t in tgts])
    ax.set_xlabel("Opening range length")
    ax.set_ylabel("Profit target, as a multiple of the range")
    for s in ax.spines.values():
        s.set_visible(False)
    save(fig, "robustness", theme)


def chart_risk(d, theme):
    t, a = d["new"], d["accounts"]
    fig, (ax, ax2) = plt.subplots(1, 2, figsize=(10, 4.7))
    fig.subplots_adjust(left=0.07, right=0.975, top=0.76, bottom=0.14, wspace=0.26)
    titled(fig, "One MNQ contract is too large for a $5,000 account",
           "Left: dollars at risk per trade with 1 contract.  Right: share of signals that fit a 1.5% risk budget.")
    bins = np.arange(0, 351, 25)
    ax.hist(t["risk_usd"], bins=bins, color=T["s1"], rwidth=0.9, lw=0)
    ax.axvline(75, color=T["text"], lw=1.5)
    ax.set_ylim(0, ax.get_ylim()[1] * 1.22)
    ax.text(81, ax.get_ylim()[1] * 0.98, r"\$75 budget (1.5% of \$5,000)", fontsize=9.5, va="top", color=T["text"])
    ax.set_xlabel("Risk per trade, 1 contract")
    ax.set_ylabel("Number of trades")
    ax.xaxis.set_major_formatter(plt.FuncFormatter(money))
    ax.set_title(f"Median risk {money(t['risk_usd'].median())}", fontsize=10.5, loc="left", color=T["muted"])

    ax2.plot(a["account"], a["share"] * 100, color=T["s1"], lw=2, marker="o", ms=8, mec=T["surface"], mew=2)
    for r in a.itertuples():
        if r.account in (5000, 10000, 15000, 25000):
            ax2.annotate(f"{r.share*100:.0f}%", (r.account, r.share * 100), xytext=(0, 10),
                         textcoords="offset points", ha="center", fontsize=9.5, color=T["text"])
    ax2.set_ylim(0, 112)
    ax2.set_xlabel("Account size")
    ax2.set_ylabel("Signals tradable (%)")
    ax2.xaxis.set_major_formatter(plt.FuncFormatter(money))
    ax2.set_xticks([5000, 10000, 15000, 20000, 25000])
    ax2.set_title("Signals where 1 contract stays within budget", fontsize=10.5, loc="left", color=T["muted"])
    save(fig, "risk", theme)


def chart_mc(d, theme):
    mc = d["mc"]
    fig, ax = plt.subplots(figsize=(10, 4.5))
    fig.subplots_adjust(left=0.07, right=0.975, top=0.80, bottom=0.14)
    titled(fig, "A typical year makes about $1,400 per contract, and about 1 year in 13 loses money",
           "20,000 simulated years of 70 trades each, resampled from the 216 backtest trades (1 contract)")
    bins = np.arange(-2000, 5001, 250)
    counts, edges = np.histogram(mc, bins=bins)
    centers = (edges[:-1] + edges[1:]) / 2
    share = counts / len(mc) * 100
    ax.bar(centers[centers < 0], share[centers < 0], width=215, color=T["s2"], lw=0, label="Losing year")
    ax.bar(centers[centers > 0], share[centers > 0], width=215, color=T["s1"], lw=0, label="Winning year")
    med = np.median(mc)
    ax.axvline(med, color=T["text"], lw=1.5)
    ax.text(med + 60, ax.get_ylim()[1] * 0.97, f"Median {money(med)}", fontsize=9.5, va="top", color=T["text"])
    ax.text(-1950, ax.get_ylim()[1] * 0.60, f"{(mc < 0).mean()*100:.0f}% of years\nlose money", fontsize=9.5,
            va="top", color=T["text"])
    ax.set_xlabel("Profit after one year")
    ax.set_ylabel("Share of simulated years (%)")
    ax.xaxis.set_major_formatter(plt.FuncFormatter(money))
    ax.legend(loc="upper right", fontsize=9.5)
    save(fig, "montecarlo", theme)


def chart_exits(d, theme):
    t = d["new"]
    g = t.groupby("why").agg(n=("R", "size"), avgR=("R", "mean"), usd=("usd", "sum"))
    g = g.loc[["target", "eod", "stop"]]
    labels = ["Hit the profit target", "Closed at end of day", "Hit the stop"]
    fig, ax = plt.subplots(figsize=(10, 3.8))
    fig.subplots_adjust(left=0.20, right=0.97, top=0.76, bottom=0.17)
    titled(fig, "Two wins for every loss, but each loss costs more than a win earns",
           "How the 216 trades ended under the new settings, with the average result of each ending")
    y = np.arange(3)[::-1]
    ax.grid(axis="x")
    ax.grid(axis="y", visible=False)
    ax.barh(y, g["n"], height=0.5, color=[T["s1"], T["s3"], T["s2"]], lw=0)
    for yi, r in zip(y, g.itertuples()):
        ax.text(r.n + 2, yi, f"{r.n} trades ({r.n/len(t)*100:.0f}%) · average {r.avgR:+.2f} R".replace("-0.00", "0.00"), va="center",
                fontsize=10, color=T["text"])
    ax.set_yticks(y, labels)
    ax.tick_params(axis="y", labelcolor=T["text"])
    ax.set_xlim(0, g["n"].max() * 1.5)
    ax.set_xlabel("Number of trades")
    save(fig, "exits", theme)


def main():
    global T
    os.makedirs(CHARTS, exist_ok=True)
    os.makedirs(TABLES, exist_ok=True)
    d = compute()
    d["new"].drop(columns=["flags"]).to_csv(os.path.join(TABLES, "trades_new_settings.csv"), index=False)
    d["old_live"].drop(columns=["flags"]).to_csv(os.path.join(TABLES, "trades_old_settings.csv"), index=False)
    d["periods"].to_csv(os.path.join(TABLES, "results_by_period.csv"), index=False)
    d["filters"].assign(filter=d["filters"]["filter"].str.replace("\n", " ")).to_csv(
        os.path.join(TABLES, "filter_attribution.csv"), index=False)
    d["grid_rows"].to_csv(os.path.join(TABLES, "robustness_grid.csv"), index=False)
    d["accounts"].to_csv(os.path.join(TABLES, "account_size.csv"), index=False)
    for theme in ("light", "dark"):
        T = THEMES[theme]
        style()
        for fn in (chart_equity, chart_periods, chart_filters, chart_grid, chart_risk, chart_mc, chart_exits):
            fn(d, theme)
    print("charts ->", CHARTS)
    print(d["periods"][d["periods"]["period"] == "ALL"].to_string(index=False))
    print(d["filters"].to_string(index=False))
    print(d["accounts"].to_string(index=False))
    mc = d["mc"]
    print("mc median", round(np.median(mc)), "P(loss)", round((mc < 0).mean(), 3))


if __name__ == "__main__":
    main()
