"""When did orb5's paper entries actually fill? Compares each entry price with the free-feed bar opens around 9:35.

The engine's rule is to enter at the open of the 9:35 bar. The live bot decides about 9:36:05 (it waits for that bar to
exist in the data) and Alpaca's paper simulator then fills the market order some time later. This script does not know the
fill times (the orb5 account's keys live only in the GitHub secrets); it infers them from prices, so read it as a hint.

Reads the paper log plus one read-only market-data request. Writes docs/ENTRY_TIMING.md. Run: python entry_timing.py
"""
import os

import numpy as np
import pandas as pd

import alpaca_io as A
import variants as VS

HERE = os.path.dirname(os.path.abspath(__file__))


def main(variant="orb5"):
    log = pd.read_csv(VS.get(variant).path("paper_log"))
    t = log[log["entry"].notna() & (log["outcome"] != "late_close")]
    df = A.AlpacaData().bars(1, pd.Timestamp(t["date"].min()) - pd.Timedelta(days=2),
                             pd.Timestamp(t["date"].max()) + pd.Timedelta(days=1))
    rows = []
    for r in t.itertuples():
        d = pd.Timestamp(r.date)
        side = 1 if r.stop < r.entry else -1
        opens = {m: df["open"].get(d + pd.Timedelta(hours=9, minutes=m), np.nan) for m in range(35, 41)}
        closest = min((abs(r.entry - v), m) for m, v in opens.items() if not np.isnan(v))[1]
        rows.append(dict(date=r.date, side="long" if side == 1 else "short", entry=r.entry, closest=closest,
                         worse_935=(r.entry - opens[35]) * side, worse_936=(r.entry - opens[36]) * side,
                         worse_937=(r.entry - opens[37]) * side))
    o = pd.DataFrame(rows)
    late = o[o["closest"] >= 37]
    L = [f"# When did {variant}'s paper entries fill? (inferred from prices)", "",
         "Built by `entry_timing.py`. The rule is to enter at the 9:35 bar's open. The bot submits its order about 9:36:05 "
         "(it waits for the 9:35 bar to exist in the data) and Alpaca's paper simulator fills it later. The fill times "
         "themselves are not in the log, so this infers them from prices: for each trade, which minute's open is the "
         "bot's entry price closest to. \"Worse\" is dollars per share, positive = worse for the trade.", "",
         "| Date | Side | Entry | Closest open | Worse than 9:35 open | Worse than 9:36 open | Worse than 9:37 open |",
         "|---|---|---|---|---|---|---|"]
    for r in o.itertuples():
        L.append(f"| {r.date} | {r.side} | {r.entry:.2f} | 9:{r.closest} | {r.worse_935:+.2f} | {r.worse_936:+.2f} | "
                 f"{r.worse_937:+.2f} |")
    L += ["", f"- Average entry vs the 9:35 open: {o['worse_935'].mean():+.2f} dollars per share worse "
              f"(average size {o['worse_935'].abs().mean():.2f}). Vs the 9:36 open: {o['worse_936'].mean():+.2f} "
              f"(size {o['worse_936'].abs().mean():.2f}).",
          f"- {len(o) - len(late)} of {len(o)} entries sit closest to the 9:35 or 9:36 open; {len(late)} sit closest to "
          f"the 9:37 open or later ({', '.join(late['date'])}), so those orders probably filled a minute or more after "
          "they were submitted.", "",
          "Reading: submission at 9:36:05 explains the average. The biggest misses come on days the price ran quickly "
          "from the open, and there the entry looks like a 9:37 or 9:38 price. Sending the order at about 9:35:05 would "
          "remove the first minute only. The rest looks like paper-simulator fill time (a one-share test on 2026-10-12 "
          "took 100 seconds to fill), which a real broker would not have. Small sample and an inference from prices: "
          "the broker's fill timestamps would settle it.", ""]
    with open(os.path.join(HERE, "docs", "ENTRY_TIMING.md"), "w", encoding="utf-8", newline="\n") as fh:
        fh.write("\n".join(L))
    print("\n".join(L))


if __name__ == "__main__":
    main()
