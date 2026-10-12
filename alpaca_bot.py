"""ORB bot on QQQ in an Alpaca PAPER account. Practice money only.

Same frozen strategy and the same engine as the backtest and the forward log,
so the decision to trade can never differ from what was tested.

  python alpaca_bot.py entry    morning: watch 10:30 to 12:00 ET, send one bracket order
  python alpaca_bot.py close    afternoon: flatten before the close, record the day
  python alpaca_bot.py status   show the paper account and today's orders
  python alpaca_bot.py replay 2026-10-07 [--out file.csv]
                                step through a past day with a fake broker (no orders sent)

Without ALPACA_API_KEY / ALPACA_SECRET_KEY the live modes exit without doing anything.
"""
import argparse
import csv
import dataclasses
import math
import os
import sys
import time
from datetime import date, datetime, timezone

import numpy as np
import pandas as pd

import alpaca_io as A
import config
import orb_engine as E
from forward_alert import push
from forward_run import config_id, fetch_vix, strategy_params

HERE = os.path.dirname(os.path.abspath(__file__))
LOG = os.path.join(HERE, "paper", "alpaca_trades.csv")
SYMBOL = A.SYMBOL
TZ = A.TZ
RISK_USD = config.ACCOUNT_SIZE * config.RISK_PERCENT   # $75: the designed risk per trade
SMALL_ACCOUNT = config.ACCOUNT_SIZE                    # $5,000 cash, no leverage: the realistic size
FLATTEN_BEFORE_CLOSE_MIN = 10
COLUMNS = ["date", "config_id", "source", "outcome", "shares", "entry", "stop", "target", "exit", "profit", "R",
           "shares_5k", "profit_5k", "sim_outcome", "sim_R", "logged_at"]


def qqq_params():
    """The frozen strategy, priced per share: $1 per point, 2 cents slippage, no commission."""
    return E.replace(strategy_params(), mult=1.0, slip=0.02, commission=0.0)


def safe_vix():
    try:
        return fetch_vix()
    except Exception as e:
        print(f"VIX unavailable ({e}); the VIX-above-35 safety check is skipped today.")
        return None


def base_day(data, day_date, vix):
    """The day with no-lookahead daily features, from ~95 days of 5-minute bars."""
    start = pd.Timestamp(day_date) - pd.Timedelta(days=95)
    hist = data.bars(5, start, pd.Timestamp(day_date) + pd.Timedelta(days=1))
    for d in E.prepare(hist, vix, partial_last=True):
        if d.date == day_date:
            return d
    return None


def with_bars(day, b1):
    """`day` carrying the given 1-minute regular-hours bars."""
    mod = (b1.index.hour * 60 + b1.index.minute).to_numpy()
    return dataclasses.replace(day, mod=mod, o=b1["open"].to_numpy(float), h=b1["high"].to_numpy(float),
                               l=b1["low"].to_numpy(float), c=b1["close"].to_numpy(float), bar=1)


def minute_bars(data, day_date, upto=None):
    b = data.bars(1, pd.Timestamp(day_date), pd.Timestamp(day_date) + pd.Timedelta(days=1))
    if upto is not None:
        b = b[b.index + pd.Timedelta(minutes=1) <= upto]   # completed minutes only
    return b


def decide(day, p, final):
    """('trade', rec) | ('none', reason, text) | None while the morning is still undecided."""
    r = E.simulate(day, p)
    if r is None:
        return None
    if r["why"] == "filtered":
        return ("none", "filtered", "Trend filter: QQQ closed below its 20-day average (or VIX above 35).")
    if r["dir"] != 0:
        return ("trade", r)
    if r["why"] == "downside_break":
        return ("none", "downside_break", "The range broke to the downside first. The bot is long only.")
    if final:
        return ("none", "no_breakout", f"No breakout by {p.cutoff // 60}:{p.cutoff % 60:02d} ET.")
    return None


def order_plan(rec, p, buying_power):
    """Share count for the designed $75 risk, capped by buying power, plus the $5,000-cash size."""
    signal = rec["entry"] - p.slip
    stop, target = round(rec["stop"], 2), round(rec["target"], 2)
    per_share = signal - stop
    qty = max(1, math.floor(RISK_USD / per_share))
    qty = max(1, min(qty, math.floor(0.9 * buying_power / signal)))
    return dict(signal=signal, stop=stop, target=target, qty=qty, per_share=per_share,
                qty_5k=max(0, math.floor(SMALL_ACCOUNT / signal)))


def order_id(day_date):
    return f"orb-{day_date.isoformat()}"


# ---------------------------------------------------------------------------
# Recording
# ---------------------------------------------------------------------------

def logged(path):
    if not os.path.isfile(path):
        return set()
    with open(path, newline="") as fh:
        return {r["date"] for r in csv.DictReader(fh)}


def build_row(broker, data, day_date, p, vix):
    """One row for the day: what the broker actually did, next to what the engine expected."""
    day = base_day(data, day_date, vix)
    sim = None
    if day is not None:
        b1 = minute_bars(data, day_date)
        if len(b1):
            sim = E.simulate(with_bars(day, b1), p)

    def f(x, nd=2):
        return "" if x is None or (isinstance(x, float) and np.isnan(x)) else f"{x:.{nd}f}"

    row = {c: "" for c in COLUMNS}
    row.update(date=day_date.isoformat(), config_id=config_id(p), source=f"{broker.name}/{data.name}",
               logged_at=datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%MZ"))
    if sim is not None:
        row["sim_outcome"] = sim["why"]
        if sim["dir"] != 0:
            row["sim_R"] = f(sim["pts"] / sim["risk"], 3)

    orders = broker.day_orders(day_date)
    parent = next((o for o in orders if o.client_order_id == order_id(day_date)), None)
    if parent is None:
        if sim is None:
            row["outcome"] = "no_data"
        else:
            row["outcome"] = "missed" if sim["dir"] != 0 else sim["why"]   # missed = engine traded, no order went out
        return row
    if not parent.filled_qty:
        row["outcome"] = "order_not_filled"
        return row

    legs = [o for o in orders if o.parent == parent.id]
    tp = next((o for o in legs if o.limit_price is not None), None)
    sl = next((o for o in legs if o.stop_price is not None and o.limit_price is None), None)
    sells = [o for o in orders if o.side.endswith("sell") and o.filled_qty and o.filled_avg_price is not None]
    # Only sells that filled after the bot's own entry count (ignores unrelated orders earlier in the day).
    if parent.filled_at is not None:
        sells = [o for o in sells if o.filled_at is None or o.filled_at >= parent.filled_at]
    sold = sum(o.filled_qty for o in sells)
    entry, qty = parent.filled_avg_price, parent.filled_qty
    row.update(shares=f(qty, 0), entry=f(entry), stop=f(sl.stop_price if sl else None),
               target=f(tp.limit_price if tp else None))
    if not sold:
        row["outcome"] = "still_open"
        return row
    exit_px = sum(o.filled_qty * o.filled_avg_price for o in sells) / sold
    if tp is not None and tp.filled_qty:
        row["outcome"] = "target"
    elif sl is not None and sl.filled_qty:
        row["outcome"] = "stop"
    else:
        row["outcome"] = "eod"
    qty_5k = max(0, math.floor(SMALL_ACCOUNT / entry))
    row.update(exit=f(exit_px), profit=f((exit_px - entry) * sold), shares_5k=str(qty_5k),
               profit_5k=f((exit_px - entry) * qty_5k))
    if sl is not None and entry > sl.stop_price:
        row["R"] = f((exit_px - entry) / (entry - sl.stop_price), 3)
    return row


def append_row(path, row):
    os.makedirs(os.path.dirname(os.path.abspath(path)), exist_ok=True)
    new = not os.path.isfile(path)
    with open(path, "a", newline="") as fh:
        w = csv.DictWriter(fh, fieldnames=COLUMNS)
        if new:
            w.writeheader()
        w.writerow(row)


def result_text(row):
    if row["entry"] == "":
        return f"No trade ({row['outcome'].replace('_', ' ')})."
    if row["profit"] == "":
        return f"Order placed but not closed ({row['outcome'].replace('_', ' ')})."
    return (f"{row['outcome'].title()}: {row['shares']} QQQ, in {row['entry']}, out {row['exit']}. "
            f"Practice profit ${float(row['profit']):+,.2f} ({row['R'] or '?'} R). "
            f"A $5,000 account would have made ${float(row['profit_5k']):+,.2f}.")


# ---------------------------------------------------------------------------
# Modes
# ---------------------------------------------------------------------------

def mode_entry():
    if not A.have_keys():
        print("Alpaca keys are not set; nothing to do.")
        return 0
    broker, data, p = A.AlpacaBroker(), A.AlpacaData(), qqq_params()
    now = pd.Timestamp.now(tz=TZ).tz_localize(None)
    today = now.date()
    hours = broker.hours(today)
    if hours is None:
        print("Market is closed today.")
        return 0
    if hours[1].hour * 60 + hours[1].minute < A.RTH_CLOSE:
        push(f"ORB QQQ {today:%b} {today.day}: no trade", "Half day: the bot does not trade shortened sessions.",
             "no_entry_sign")
        return 0
    if broker.has_order(order_id(today)):
        print("Today's order was already sent; nothing to do.")
        return 0
    if broker.position_qty() != 0 or broker.open_orders():
        print("A QQQ position or order already exists; not placing another.")
        return 0

    or_end, stop_at = E.RTH_OPEN + p.or_min, p.cutoff + 2
    if now.hour * 60 + now.minute > stop_at:
        print("Past the entry window; nothing to do.")
        return 0
    wait = (or_end + 1) - (now.hour * 60 + now.minute)
    if wait > 0:
        print(f"Waiting {wait} min for the {p.or_min}-minute range to finish...")
        time.sleep(wait * 60)

    vix, day = safe_vix(), None
    label = f"ORB QQQ {today:%a %b} {today.day}"
    while True:
        now = pd.Timestamp.now(tz=TZ).tz_localize(None)
        final = now.hour * 60 + now.minute >= stop_at
        try:
            if day is None:
                day = base_day(data, today, vix)
            b1 = minute_bars(data, today, upto=now) if day is not None else []
            verdict = decide(with_bars(day, b1), p, final) if len(b1) else None
            if verdict and verdict[0] == "none":
                push(f"{label}: no trade", verdict[2], "no_entry_sign")
                return 0
            if verdict and verdict[0] == "trade":
                plan = order_plan(verdict[1], p, broker.account().buying_power)
                broker.place_bracket(plan["qty"], plan["stop"], plan["target"], order_id(today))
                push(f"{label}: ORDER PLACED (practice)",
                     f"Bought {plan['qty']} QQQ near {plan['signal']:,.2f}. Stop {plan['stop']:,.2f}, "
                     f"target {plan['target']:,.2f}. Risk about ${plan['qty'] * plan['per_share']:,.0f}. "
                     f"Alpaca paper account, no real money.")
                return 0
        except Exception as e:   # one bad poll should not end the morning
            print(f"[{now:%H:%M}] poll failed: {e}")
        if final:
            push(f"{label}: no trade", "No decision by the cutoff (data unavailable).", "warning")
            return 0
        time.sleep(60)


def mode_close():
    if not A.have_keys():
        print("Alpaca keys are not set; nothing to do.")
        return 0
    broker, data, p = A.AlpacaBroker(), A.AlpacaData(), qqq_params()
    now = pd.Timestamp.now(tz=TZ).tz_localize(None)
    today = now.date()
    hours = broker.hours(today)
    if hours is None:
        print("Market is closed today.")
        return 0
    if today.isoformat() in logged(LOG):
        print("Today is already logged.")
        return 0
    flatten_at = hours[1] - pd.Timedelta(minutes=FLATTEN_BEFORE_CLOSE_MIN)
    wait = (flatten_at - now).total_seconds()
    if wait > 0:
        print(f"Waiting {wait / 60:.0f} min until {flatten_at:%H:%M} ET to flatten...")
        time.sleep(wait)
    late = pd.Timestamp.now(tz=TZ).tz_localize(None) > hours[1]
    broker.flatten()
    time.sleep(30)   # let the closing fill arrive

    # Record once the session's bars are complete.
    remaining = (hours[1] + pd.Timedelta(minutes=3) - pd.Timestamp.now(tz=TZ).tz_localize(None)).total_seconds()
    if remaining > 0:
        time.sleep(remaining)
    row = build_row(broker, data, today, p, safe_vix())
    append_row(LOG, row)
    note = " Started after the close; any open position closes at the next open." if late else ""
    push(f"ORB QQQ {today:%a %b} {today.day}: result", result_text(row) + note, "bar_chart")
    return 0


def mode_status():
    if not A.have_keys():
        print("Alpaca keys are not set.")
        return 1
    broker = A.AlpacaBroker()
    a = broker.account()
    print(f"Paper account {a.number}: {a.status}, equity ${a.equity:,.2f}, buying power ${a.buying_power:,.2f}")
    print(f"QQQ position: {broker.position_qty():g} shares; open orders: {len(broker.open_orders())}")
    today = pd.Timestamp.now(tz=TZ).date()
    print("Market hours today:", broker.hours(today))
    for o in broker.day_orders(today):
        print(f"  {o.side:5s} {o.type:7s} {o.status:10s} filled {o.filled_qty:g} @ {o.filled_avg_price}")
    return 0


def mode_replay(day_date, out):
    """Walk a past day minute by minute with a fake broker. Sends nothing to Alpaca."""
    data, p, broker, vix = A.data_source(), qqq_params(), A.FakeBroker(), safe_vix()
    day = base_day(data, day_date, vix)
    full = minute_bars(data, day_date)
    if day is None or not len(full):
        print("No full session for that date from", data.name)
        return 1
    for k in range(1, len(full) + 1):
        part = full.iloc[:k]
        last_mod = part.index[-1].hour * 60 + part.index[-1].minute
        verdict = decide(with_bars(day, part), p, final=last_mod + 1 >= p.cutoff)
        if verdict is None:
            continue
        if verdict[0] == "trade":
            plan = order_plan(verdict[1], p, broker.account().buying_power)
            broker.place_bracket(plan["qty"], plan["stop"], plan["target"], order_id(day_date),
                                 placed_at=part.index[-1])
            print(f"{part.index[-1]:%H:%M} order: buy {plan['qty']} near {plan['signal']:.2f}, stop {plan['stop']:.2f}, "
                  f"target {plan['target']:.2f}, risk ${plan['qty'] * plan['per_share']:.0f}, 5k size {plan['qty_5k']}")
        else:
            print(f"{part.index[-1]:%H:%M} no trade: {verdict[1]}")
        break
    close_at = pd.Timestamp(day_date) + pd.Timedelta(minutes=A.RTH_CLOSE - FLATTEN_BEFORE_CLOSE_MIN)
    broker.settle(full, close_at)
    row = build_row(broker, data, day_date, p, vix)
    print(result_text(row), f"| engine expected: {row['sim_outcome']} {row['sim_R']}")
    if out and day_date.isoformat() not in logged(out):
        append_row(out, row)
    return 0


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("mode", choices=["entry", "close", "status", "replay"])
    ap.add_argument("day", nargs="?")
    ap.add_argument("--out")
    a = ap.parse_args()
    if a.mode == "entry":
        return mode_entry()
    if a.mode == "close":
        return mode_close()
    if a.mode == "status":
        return mode_status()
    return mode_replay(date.fromisoformat(a.day), a.out)


if __name__ == "__main__":
    sys.exit(main())
