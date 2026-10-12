"""Daily forward record: what the bot would have done today, on free delayed data.

No broker and no orders. Runs after the close, replays each finished session with
the same engine as the backtest, and appends one row per trading day to
forward/forward_log.csv. Rows are never rewritten, and each one stores a hash of
the strategy settings that were in force when it was logged.

Run:  python forward_run.py
Test: python forward_run.py --start 2026-10-05 --out scratch.csv [--no-1m]
"""
import argparse
import csv
import dataclasses
import hashlib
import json
import os
import sys
import time
from datetime import date, datetime, timezone

import numpy as np
import pandas as pd
import yfinance as yf

import backtest
import config
import orb_engine as E

HERE = os.path.dirname(os.path.abspath(__file__))
LOG = os.path.join(HERE, "forward", "forward_log.csv")
FORWARD_START = date(2026, 10, 12)   # the day the current settings were frozen
SYMBOL = "NQ=F"
TZ = "America/New_York"
COLUMNS = ["date", "config_id", "bar_min", "range_high", "range_low", "range_pct", "flags", "outcome",
           "entry", "stop", "target", "exit", "pts", "risk_pts", "R", "usd_1c", "over_risk", "logged_at"]
# Settings that describe the account, not the strategy, are left out of the hash.
ACCOUNT_FIELDS = {"account", "risk_pct", "max_contracts", "oversize", "oversize_tol", "monthly_cap", "monthly_net"}


def strategy_params():
    """Live rules from config.py, sized at 1 contract per signal with no account limits."""
    return E.replace(backtest.params_from_config(), oversize="min1", monthly_cap=0)


def config_id(p):
    d = {k: v for k, v in dataclasses.asdict(p).items() if k not in ACCOUNT_FIELDS}
    return hashlib.sha1(json.dumps(d, sort_keys=True, default=str).encode()).hexdigest()[:8]


def fetch(interval, period, tries=3):
    """NQ futures bars from Yahoo as a naive Eastern-time frame (about 10 minutes delayed)."""
    last = None
    for attempt in range(tries):
        try:
            d = yf.download(SYMBOL, period=period, interval=interval, progress=False, multi_level_index=False)
            if len(d):
                d.index = d.index.tz_convert(TZ).tz_localize(None)
                d = d.rename(columns=str.lower)[["open", "high", "low", "close", "volume"]]
                d.index.name = "ts"
                return d
            last = "empty response"
        except Exception as e:   # network or rate-limit error: retry
            last = e
        time.sleep(20 * (attempt + 1))
    raise RuntimeError(f"Yahoo returned no {interval} data for {SYMBOL}: {last}")


def fetch_vix():
    v = yf.download("^VIX", period="3mo", interval="1d", progress=False, multi_level_index=False)["Close"]
    v.index = v.index.tz_localize(None)
    return v


def with_minute_bars(day, df1):
    """Swap a day's 5-minute bars for 1-minute bars when the full session is available."""
    b = df1[df1.index.normalize() == pd.Timestamp(day.date)]
    mod = (b.index.hour * 60 + b.index.minute).to_numpy()
    keep = (mod >= E.RTH_OPEN) & (mod < E.RTH_CLOSE)
    b, mod = b[keep], mod[keep]
    if len(b) < 0.95 * (E.RTH_CLOSE - E.RTH_OPEN) or mod[0] != E.RTH_OPEN:
        return day
    return dataclasses.replace(day, mod=mod, o=b["open"].to_numpy(float), h=b["high"].to_numpy(float),
                               l=b["low"].to_numpy(float), c=b["close"].to_numpy(float), bar=1)


def load_days(use_1m=True, partial_last=False):
    days = E.prepare(fetch("5m", "60d"), fetch_vix(), partial_last=partial_last)
    if use_1m:
        df1 = fetch("1m", "7d")
        days = [with_minute_bars(d, df1) for d in days]
    return days


def row_for(day, p, cid):
    r = E.simulate(day, p)
    if r is None:
        return None
    traded = r["dir"] != 0
    hi = lo = np.nan
    in_or = day.mod < E.RTH_OPEN + p.or_min
    if in_or.any():
        hi, lo = day.h[in_or].max(), day.l[in_or].min()
    budget = config.ACCOUNT_SIZE * config.RISK_PERCENT * config.MAX_RISK_OVERSHOOT

    def f(x, nd=2):
        return "" if x is None or (isinstance(x, float) and np.isnan(x)) else f"{x:.{nd}f}"

    return {
        "date": day.date.isoformat(), "config_id": cid, "bar_min": day.bar,
        "range_high": f(hi), "range_low": f(lo), "range_pct": f(r["range_pct"], 5),
        "flags": r["flags"], "outcome": r["why"],
        "entry": f(r.get("entry")) if traded else "", "stop": f(r.get("stop")) if traded else "",
        "target": f(r.get("target")) if traded else "", "exit": f(r.get("exit")) if traded else "",
        "pts": f(r["pts"]) if traded else "", "risk_pts": f(r["risk"]) if traded else "",
        "R": f(r["pts"] / r["risk"], 3) if traded else "",
        "usd_1c": f(r["pts"] * E.MULT - p.commission) if traded else "",
        "over_risk": ("Y" if r["risk"] * E.MULT > budget else "N") if traded else "",
        "logged_at": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%MZ"),
    }


def logged_dates(path):
    if not os.path.isfile(path):
        return set()
    with open(path, newline="") as fh:
        return {r["date"] for r in csv.DictReader(fh)}


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--start", default=FORWARD_START.isoformat(), help="first date to log (testing)")
    ap.add_argument("--out", default=LOG, help="log file (testing)")
    ap.add_argument("--no-1m", action="store_true", help="use 5-minute bars only (testing)")
    a = ap.parse_args()

    start = date.fromisoformat(a.start)
    now = pd.Timestamp.now(tz=TZ)
    p = strategy_params()
    cid = config_id(p)
    have = logged_dates(a.out)

    rows = []
    for day in load_days(use_1m=not a.no_1m):
        if day.date < start or day.date.isoformat() in have:
            continue
        # A session is only logged once it has finished and the delayed data has caught up.
        if day.date > now.date() or (day.date == now.date() and (now.hour, now.minute) < (16, 15)):
            continue
        r = row_for(day, p, cid)
        if r:
            rows.append(r)

    if not rows:
        print(f"Nothing new to log (settings {cid}, {len(have)} days already logged).")
        return 0
    os.makedirs(os.path.dirname(os.path.abspath(a.out)), exist_ok=True)
    new_file = not os.path.isfile(a.out)
    with open(a.out, "a", newline="") as fh:
        w = csv.DictWriter(fh, fieldnames=COLUMNS)
        if new_file:
            w.writeheader()
        w.writerows(rows)
    for r in rows:
        tail = f" entry {r['entry']} exit {r['exit']} R {r['R']}" if r["entry"] else ""
        print(f"{r['date']}  {r['outcome']:14s}{tail}")
    print(f"Logged {len(rows)} day(s) to {os.path.relpath(a.out, HERE)} (settings {cid}).")
    return 0


if __name__ == "__main__":
    try:
        sys.exit(main())
    except RuntimeError as e:
        print("ERROR:", e)
        sys.exit(1)
