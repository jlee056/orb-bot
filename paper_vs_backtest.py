"""Phase C: every paper trade next to what the engine says it should have done.

Three results per trade, all in R (1 R = the amount risked):
  A  what the broker actually did (paper log, column R)
  S  the engine on the same free one-exchange (IEX) bars the bot saw that morning. The paper log's sim_R is the
     bot's own record of this; the script re-runs the engine on freshly fetched IEX bars to get its prices too,
     and checks that it reproduces sim_R.
  O  the engine on consolidated 1-minute bars (data/alpaca, refresh with get_data.py --qqq)

A - S is execution (entry timing, fills) on the same data. S - O is the data feed. A - O is both.
The A - S gap is split exactly into a price part (dollars gained or lost per share) and a risk-scale part
(a later entry changes the risk that R is divided by).
Reads local files plus one read-only market-data request. Changes nothing in the engine or the logs.
Writes docs/PAPER_VS_BACKTEST.md and docs/data/paper_vs_backtest.csv.

Run:  python paper_vs_backtest.py
"""
import os

import numpy as np
import pandas as pd

import alpaca_io as A
import orb_engine as E
import variants as VS
from alpaca_bot import qqq_params
from walkforward import load_days

HERE = os.path.dirname(os.path.abspath(__file__))
NO_TRADE = {"filtered", "no_breakout", "downside_break", "filtered_dir", "doji", "no_room", "monthly_cap", "over_risk",
            "order_not_filled", "missed"}
CHECK_TOL = 0.02          # a re-run counts as reproducing the bot's logged sim_R within this many R


def read_log(path):
    return pd.read_csv(path, dtype={"config_id": str}) if os.path.isfile(path) else pd.DataFrame()


def iex_days(first, last):
    """Engine days built from the free-feed 1-minute bars (what the bot saw), or {} if they cannot be fetched."""
    try:
        start = pd.Timestamp(first) - pd.Timedelta(days=100)
        df = A.AlpacaData().bars(1, start, pd.Timestamp(last) + pd.Timedelta(days=1))
        return {d.date: d for d in E.prepare(df, E.load_vix())}
    except Exception as exc:                      # no keys, no network, rate limit: the S re-run is skipped
        print(f"Could not fetch free-feed bars ({exc}); S is taken from the log only.")
        return {}


def sim(day, p):
    rec = E.simulate(day, p) if day is not None else None
    out = dict(why=rec["why"] if rec else "no_data", dir=0, R=np.nan)
    if rec and rec["dir"] != 0:
        px = E.prices(rec)
        out.update(dir=rec["dir"], R=rec["pts"] / rec["risk"], entry=px["entry"], exit=px["exit"], stop=px["stop"],
                   pts=rec["pts"], risk=rec["risk"])
    return out


def compare(log, p, by_cons, by_iex):
    rows = []
    for _, r in log.iterrows():
        d = pd.Timestamp(r["date"]).date()
        o, s = sim(by_cons.get(d), p), sim(by_iex.get(d), p)
        a_dir = 0
        if pd.notna(r["entry"]) and pd.notna(r["stop"]):
            a_dir = 1 if r["stop"] < r["entry"] else -1       # the order the bot actually sent
        row = dict(date=r["date"], outcome=r["outcome"], A=r["R"], S=r["sim_R"], S_log_outcome=r["sim_outcome"],
                   A_dir=a_dir, O=o["R"], O_outcome=o["why"], O_dir=o["dir"], S2=s["R"], S2_outcome=s["why"],
                   S2_dir=s["dir"], S_risk=s.get("risk", np.nan), O_risk=o.get("risk", np.nan))
        row["S_rerun_ok"] = (bool(s["dir"] != 0 and abs(s["R"] - r["sim_R"]) <= CHECK_TOL)
                             if pd.notna(r["sim_R"]) and s["dir"] != 0 else np.nan)
        if pd.notna(r["R"]) and a_dir and o["dir"] and a_dir != o["dir"]:
            row["O"] = np.nan                                  # opposite trades: not comparable
        if pd.notna(r["R"]) and a_dir != 0 and a_dir == s["dir"]:
            actual_pts = (r["exit"] - r["entry"]) * a_dir
            row["entry_worse"] = (r["entry"] - s["entry"]) * a_dir          # dollars per share, positive = worse
            row["exit_worse"] = -(r["exit"] - s["exit"]) * a_dir
            row["stop_diff"] = (r["stop"] - s["stop"]) * a_dir              # bot stop vs engine stop on the same feed
            row["price_R"] = (actual_pts - s["pts"]) / s["risk"]
            row["scale_R"] = r["R"] - actual_pts / s["risk"]
            row["actual_risk"] = abs(r["entry"] - r["stop"])
        if s["dir"] and o["dir"] and s["dir"] == o["dir"]:
            row["feed_stop_diff"] = (s["stop"] - o["stop"]) * s["dir"]      # free-feed stop minus consolidated stop
        rows.append(row)
    return pd.DataFrame(rows)


def agree(s_out, o_out, s_dir, o_dir):
    """Did the engine on the free feed and on consolidated data tell the same story, direction included?"""
    if s_out in NO_TRADE and o_out in NO_TRADE:
        return True
    return s_out == o_out and (not s_dir or not o_dir or s_dir == o_dir)


def stat(v):
    v = pd.Series(v).dropna()
    return dict(n=len(v), mean=float(v.mean()), median=float(v.median()),
                se=float(v.std(ddof=1) / np.sqrt(len(v))) if len(v) > 1 else np.nan) if len(v) else None


def main():
    cons = load_days("qqq")
    by_cons = {d.date: d for d in cons}
    last = max(by_cons)
    logs = {name: read_log(v.path("paper_log")) for name, v in VS.ALL.items()}
    dates = sorted(pd.to_datetime(pd.concat([lg["date"] for lg in logs.values() if len(lg)])).dt.date.unique())
    by_iex = iex_days(dates[0], dates[-1])
    tables = []
    for name, v in VS.ALL.items():
        if len(logs[name]):
            df = compare(logs[name], qqq_params(v), by_cons, by_iex)
            df.insert(0, "variant", name)
            tables.append(df)
    allrows = pd.concat(tables, ignore_index=True)
    allrows.to_csv(os.path.join(HERE, "docs", "data", "paper_vs_backtest.csv"), index=False)

    L = ["# Paper trades against the engine (Phase C)", "",
         "Built by `paper_vs_backtest.py`. Each paper trade has three results in R (1 R = the amount risked): **A** what "
         "the broker did, **S** the engine on the free one-exchange bars the bot saw that morning, **O** the engine on "
         "consolidated bars (today's data). A - S is execution on the same data, S - O is the data feed, A - O is both. "
         "Prices are dollars per share and \"worse\" means worse for the trade (paid more or sold lower for a long, the "
         "reverse for a short). The 2026-10-26 late close is shown but left out of every average. "
         f"Consolidated data runs to {last}.", ""]
    for name in VS.ALL:
        df = allrows[allrows["variant"] == name]
        if not len(df):
            continue
        L += [f"## {name}", ""]
        ok = [agree(a, b, c, d) for a, b, c, d in zip(df["S_log_outcome"], df["O_outcome"], df["S2_dir"], df["O_dir"])]
        L.append(f"Days logged {len(df)}. The engine on the free feed and on consolidated data told the same story, "
                 f"direction included, on {sum(ok)} of {len(df)} days.")
        for r in df[[not x for x in ok]].itertuples():
            side = lambda x: " long" if x == 1 else " short" if x == -1 else ""
            L.append(f"- {r.date}: free feed {r.S_log_outcome}{side(r.S2_dir)}, consolidated {r.O_outcome}{side(r.O_dir)}.")
        chk = df["S_rerun_ok"].dropna()
        if len(chk):
            L.append(f"Check: re-running the engine on freshly fetched free-feed bars reproduces the bot's logged "
                     f"expectation (within {CHECK_TOL} R) on {int(chk.sum())} of {len(chk)} traded days"
                     + ("." if chk.all() else "; the others: "
                        + ", ".join(df.loc[df["S_rerun_ok"] == False, "date"]) + "."))  # noqa: E712
        L.append("")
        t = df[df["A"].notna() & (df["outcome"] != "late_close")].copy()
        if len(t):
            t["A_S"], t["S_O"], t["A_O"] = t["A"] - t["S"], t["S"] - t["O"], t["A"] - t["O"]
            L += ["| Date | Outcome | Bot | A | S | O | A-S | S-O | Entry worse | Exit worse | Stop vs engine | Risk ($/sh) |",
                  "|---|---|---|---|---|---|---|---|---|---|---|---|"]
            f = lambda x, d=2: "" if pd.isna(x) else f"{x:+.{d}f}"
            for r in t.itertuples():
                side = 'long' if r.A_dir == 1 else 'short' if r.A_dir == -1 else ''
                if r.A_dir and r.O_dir and r.A_dir != r.O_dir:
                    side += " (consolidated: opposite side)"
                L.append(f"| {r.date} | {r.outcome} | {side} | {f(r.A)} | {f(r.S)} | {f(r.O)} | {f(r.A_S)} | {f(r.S_O)} | "
                         f"{f(getattr(r, 'entry_worse', np.nan))} | {f(getattr(r, 'exit_worse', np.nan))} | "
                         f"{f(getattr(r, 'stop_diff', np.nan))} | "
                         f"{'' if pd.isna(r.S_risk) else format(r.S_risk, '.2f')} |")
            L.append("")
            for k, lab in (("A_S", "A - S (execution)"), ("S_O", "S - O (data feed)"), ("A_O", "A - O (both)")):
                s = stat(t[k])
                if s:
                    L.append(f"- {lab}: mean {s['mean']:+.2f} R, median {s['median']:+.2f} R, standard error "
                             f"{s['se']:.2f}, {s['n']} trades")
            m = t[t["price_R"].notna()]
            if len(m):
                med = float(m["S_risk"].median())
                L.append(f"- Execution (A - S) on the {len(m)} trades where the bot and the engine took the same side: a "
                         f"price effect of {m['price_R'].mean():+.2f} R and a risk-scale effect of "
                         f"{m['scale_R'].mean():+.2f} R (they add up exactly to {(m['price_R'] + m['scale_R']).mean():+.2f}).")
                L.append(f"- In dollars per share the bot's entry was {m['entry_worse'].mean():+.2f} worse than the engine's "
                         f"and its exit {m['exit_worse'].mean():+.2f} worse (average, negative = better); its stop was "
                         f"{m['stop_diff'].mean():+.2f} from the engine's. The engine's risk is {m['S_risk'].mean():.2f} "
                         f"dollars per share on average (median {med:.2f}; {(m['S_risk'] < 1).mean() * 100:.0f}% of trades "
                         f"under 1 dollar), so one cent is {0.01 / med:.3f} R at the median.")
                big = m.loc[m["A_S"] <= -1.0]
                if len(big):
                    L.append(f"- The gap is concentrated: {len(big)} of {len(m)} trades account for "
                             f"{big['A_S'].sum():+.2f} of the total {m['A_S'].sum():+.2f} R "
                             f"({', '.join(big['date'])}).")
                rest = m.loc[m["A_S"] > -1.0]
                L.append(f"- Without those, the mean A - S is {rest['A_S'].mean():+.2f} R over {len(rest)} trades.")
            fs = t["feed_stop_diff"].dropna()
            if len(fs):
                L.append(f"- Feed: the free feed's stop level differs from consolidated by {fs.mean():+.2f} dollars per "
                         f"share on average (positive = free feed's stop is further from entry); S - O mean "
                         f"{t['S_O'].mean():+.2f} R.")
            L.append("")
        miss = df[df["outcome"] == "missed"]
        if len(miss):
            L.append("Missed signals (no order went out), engine result on the free feed: " + "; ".join(
                f"{r.date} {r.S:+.2f}" for r in miss.itertuples()) + f" R, total {miss['S'].sum():+.2f} R.")
            L.append("")
        late = df[df["outcome"] == "late_close"]
        if len(late):
            r = late.iloc[0]
            L += [f"Late close, left out of the averages: {r['date']} actual {r['A']:+.2f} R, engine on the free feed "
                  f"{r['S']:+.2f}, on consolidated {r['O']:+.2f}.", ""]
    L += ["Small samples: with 15 trades or fewer the standard error is large, so read these as a description of what "
          "happened, not as a measured cost.", ""]
    with open(os.path.join(HERE, "docs", "PAPER_VS_BACKTEST.md"), "w", encoding="utf-8", newline="\n") as fh:
        fh.write("\n".join(L))
    print("\n".join(L))
    print("\nwrote docs/PAPER_VS_BACKTEST.md and docs/data/paper_vs_backtest.csv")


if __name__ == "__main__":
    main()
