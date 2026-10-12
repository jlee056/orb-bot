"""Morning alert: push a phone notification when today's breakout fires.

No broker and no orders. Polls Yahoo's NQ futures data (about 10 minutes late)
once a minute and runs the same engine as the backtest and the forward log, so
the alert and the log can never disagree. Sends exactly one push, then exits.

Run:   python forward_alert.py
Test:  python forward_alert.py --test                 (send one test push)
       python forward_alert.py --replay 2026-10-07    (step through a past day, print only)

The push goes to https://ntfy.sh/<NTFY_TOPIC>. NTFY_TOPIC comes from the
environment (.env locally, a repository secret in GitHub Actions). Without it the
message is printed and nothing is sent.
"""
import argparse
import dataclasses
import os
import sys
import time
import urllib.request
from datetime import date

import pandas as pd

import config
import orb_engine as E
from forward_run import TZ, fetch, fetch_vix, strategy_params

DATA_LAG_MIN = 15   # keep polling this long past the cutoff so delayed bars can arrive


def push(title, body, tags="chart_with_upwards_trend", dry=False):
    topic = os.getenv("NTFY_TOPIC", "").strip()
    print(f"[{pd.Timestamp.now(tz=TZ):%H:%M}] {title} | {body}")
    if dry or not topic:
        if not topic and not dry:
            print("NTFY_TOPIC not set: nothing sent.")
        return
    req = urllib.request.Request(f"https://ntfy.sh/{topic}", data=body.encode("utf-8"),
                                 headers={"Title": title, "Tags": tags})
    urllib.request.urlopen(req, timeout=20).read()


def today_bars(df1, day, drop_forming=False):
    """A copy of `day` holding the 1-minute RTH bars seen so far.
    drop_forming removes the newest bar, which Yahoo may still be updating."""
    b = df1[df1.index.normalize() == pd.Timestamp(day.date)]
    if drop_forming:
        b = b.iloc[:-1]
    mod = (b.index.hour * 60 + b.index.minute).to_numpy()
    keep = (mod >= E.RTH_OPEN) & (mod < E.RTH_CLOSE)
    b, mod = b[keep], mod[keep]
    if not len(b):
        return None
    return dataclasses.replace(day, mod=mod, o=b["open"].to_numpy(float), h=b["high"].to_numpy(float),
                               l=b["low"].to_numpy(float), c=b["close"].to_numpy(float), bar=1)


def decide(day, p, final):
    """Return (title, body, tags) once the day is decided, else None."""
    r = E.simulate(day, p)
    if r is None:
        return None
    d = f"{day.date:%a %b} {day.date.day}"
    if r["why"] == "filtered":
        return (f"ORB {d}: no trade", "Trend filter: NQ closed below its 20-day average (or VIX above 35).",
                "no_entry_sign")
    if r["dir"] != 0:
        entry, stop, target = r["entry"] - p.slip, r["stop"], r["target"]
        risk = (entry - stop) * E.MULT
        budget = config.ACCOUNT_SIZE * config.RISK_PERCENT * config.MAX_RISK_OVERSHOOT
        over = f" Over the ${budget:.0f} budget: live mode would skip." if risk > budget else ""
        return (f"ORB {d}: BREAKOUT (long)",
                f"Entry ~{entry:,.2f}  Stop {stop:,.2f}  Target {target:,.2f}. "
                f"1 MNQ risks ${risk:,.0f}, target pays ${(target - entry) * E.MULT:,.0f}.{over} "
                f"Price is about 10 min old. No order was placed.",
                "chart_with_upwards_trend")
    if r["why"] == "downside_break":
        return (f"ORB {d}: no trade", "The range broke to the downside first. The bot is long only.", "no_entry_sign")
    if final:
        return (f"ORB {d}: no trade", f"No breakout by {p.cutoff // 60}:{p.cutoff % 60:02d} ET.", "no_entry_sign")
    return None


def base_day(target_date):
    """Today's Day with no-lookahead daily features, from the 60-day 5-minute history."""
    days = E.prepare(fetch("5m", "60d"), fetch_vix(), partial_last=True)
    for d in days:
        if d.date == target_date:
            return d
    return None


def replay(target, p):
    df1 = fetch("1m", "7d")
    days = E.prepare(fetch("5m", "60d"), fetch_vix())
    day = next((d for d in days if d.date == target), None)
    if day is None:
        print("No full session for that date in the last 60 days.")
        return 1
    full = today_bars(df1, day)
    if full is None:
        print("No 1-minute bars for that date (only the last 7 days are kept).")
        return 1
    for k in range(1, len(full.mod) + 1):
        part = dataclasses.replace(full, mod=full.mod[:k], o=full.o[:k], h=full.h[:k], l=full.l[:k], c=full.c[:k])
        msg = decide(part, p, final=full.mod[k - 1] + 1 >= p.cutoff)
        if msg:
            print(f"decided at bar {full.mod[k-1] // 60}:{full.mod[k-1] % 60:02d} ET")
            push(*msg, dry=True)
            return 0
    print("never decided")
    return 1


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--test", action="store_true")
    ap.add_argument("--replay")
    a = ap.parse_args()
    p = strategy_params()

    if a.test:
        push("ORB bot: test alert", "If you can read this on your phone, alerts are working.", "white_check_mark")
        return 0
    if a.replay:
        return replay(date.fromisoformat(a.replay), p)

    now = pd.Timestamp.now(tz=TZ)
    today = now.date()
    or_end = E.RTH_OPEN + p.or_min
    stop_at = p.cutoff + DATA_LAG_MIN
    if now.dayofweek >= 5 or now.hour * 60 + now.minute > stop_at:
        print("Outside the alert window; nothing to do.")
        return 0

    # Sleep until the range has formed (the job may start hours early in winter time).
    wait = (or_end + 1) - (now.hour * 60 + now.minute)
    if wait > 0:
        print(f"Waiting {wait} min for the {p.or_min}-minute range to finish...")
        time.sleep(wait * 60)

    day, polls = None, 0
    while True:
        now = pd.Timestamp.now(tz=TZ)
        minute = now.hour * 60 + now.minute
        final = minute >= stop_at
        try:
            # The 60-day history is only needed once; on a holiday, re-check every 10 minutes.
            if day is None and polls % 10 == 0:
                day = base_day(today)
            polls += 1
            if day is not None:
                cur = today_bars(fetch("1m", "1d", tries=1), day, drop_forming=True)
                msg = decide(cur, p, final) if cur is not None else None
                if msg:
                    push(*msg)
                    return 0
        except Exception as e:   # one bad poll should not end the morning
            print(f"[{now:%H:%M}] poll failed: {e}")
        if final:
            # No session today (holiday) or no data ever arrived.
            print("Cutoff reached with no session data; market closed or data unavailable.")
            return 0
        time.sleep(60)


if __name__ == "__main__":
    sys.exit(main())
