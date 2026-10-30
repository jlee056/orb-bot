"""ORB bot on QQQ in an Alpaca PAPER account. Practice money only.

Same frozen strategy and the same engine as the backtest and the forward log,
so the decision to trade can never differ from what was tested.

  python alpaca_bot.py entry    morning: watch 10:30 to 12:00 ET, send one bracket order
  python alpaca_bot.py close    afternoon: flatten before the close, record the day
  python alpaca_bot.py status   show the paper account and today's orders
  python alpaca_bot.py replay 2026-10-07 [--out file.csv]
                                step through a past day with a fake broker (no orders sent)

Add --variant orb5 or --variant both60 to run one of the side-by-side variants (variants.py);
each uses its own paper account, log file and order ids. The default is the frozen base.

Without ALPACA_API_KEY / ALPACA_SECRET_KEY the live modes exit without doing anything.
"""
import argparse
import csv
import dataclasses
import math
import os
import tempfile
import sys
import time
from datetime import date, datetime, timezone

import numpy as np
import pandas as pd

import alpaca_io as A
import config
import orb_engine as E
import variants
from forward_alert import push
from forward_run import config_id, fetch_vix, strategy_params

HERE = os.path.dirname(os.path.abspath(__file__))
V = variants.BASE                 # set by --variant
LOG = V.path("paper_log")
SYMBOL = A.SYMBOL
TZ = A.TZ
RISK_USD = config.ACCOUNT_SIZE * config.RISK_PERCENT   # $75: the designed risk per trade
SMALL_ACCOUNT = config.ACCOUNT_SIZE                    # $5,000 cash, no leverage: the realistic size
FLATTEN_BEFORE_CLOSE_MIN = 10
COLUMNS = ["date", "config_id", "source", "outcome", "shares", "entry", "stop", "target", "exit", "profit", "R",
           "shares_5k", "profit_5k", "sim_outcome", "sim_R", "logged_at"]


def qqq_params(v=None):
    """The variant's frozen strategy, priced per share: $1 per point, 2 cents slippage, no commission."""
    v = v or V
    return E.replace(strategy_params(), mult=1.0, slip=0.02, commission=0.0, **v.changes)


def label(day_date):
    """Notification title prefix: 'ORB QQQ Wed Oct 14' for base, 'ORB QQQ [orb5] Wed Oct 14' for a variant."""
    tag = f" {V.tag}" if V.tag else ""
    return f"ORB QQQ{tag} {day_date:%a %b} {day_date.day}"


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
    if r["why"] == "filtered_dir":
        return ("none", "filtered_dir", "The first break went against the trend filter "
                                        "(longs need QQQ above its 20-day average, shorts below).")
    if r["why"] == "doji":
        return ("none", "doji", "The first 5-minute candle opened and closed at the same price.")
    if r["why"] == "no_room":
        return ("none", "no_room", "The entry price was already past the stop or the target.")
    if final:
        return ("none", "no_breakout", f"No breakout by {p.cutoff // 60}:{p.cutoff % 60:02d} ET.")
    return None


def order_plan(rec, p, buying_power, last=None):
    """Share count for the designed $75 risk, capped by buying power, plus the $5,000-cash size.
    last: the latest price, used instead of the engine's entry when the order goes out later than the
    tested fill (candle mode decides one bar after its entry bar opens). None if price is past the stop."""
    px = E.prices(rec)
    side = "buy" if rec["dir"] == 1 else "sell"
    signal = px["entry"] - rec["dir"] * p.slip if last is None else float(last)
    stop, target = round(px["stop"], 2), round(px["target"], 2)
    if last is not None and rec["dir"] * (signal - stop) <= 0.01:
        return None
    per_share = abs(signal - stop)
    qty = max(1, math.floor(RISK_USD / per_share))
    qty = max(1, min(qty, math.floor(0.9 * buying_power / signal)))
    return dict(signal=signal, stop=stop, target=target, qty=qty, per_share=per_share, side=side,
                qty_5k=max(0, math.floor(SMALL_ACCOUNT / signal)))


def order_id(day_date):
    return f"{V.order_prefix}-{day_date.isoformat()}"


# ---------------------------------------------------------------------------
# Recording
# ---------------------------------------------------------------------------

def logged(path):
    if not os.path.isfile(path):
        return set()
    with open(path, newline="") as fh:
        return {r["date"] for r in csv.DictReader(fh)}


def build_row(broker, data, day_date, p, vix, previous=None):
    """One row for the day: what the broker actually did, next to what the engine expected."""
    day = None if previous else base_day(data, day_date, vix)
    sim = None
    if day is not None:
        b1 = minute_bars(data, day_date)
        if len(b1):
            sim = E.simulate(with_bars(day, b1), p)

    def f(x, nd=2):
        return "" if x is None or (isinstance(x, float) and np.isnan(x)) else f"{x:.{nd}f}"

    row = {c: "" for c in COLUMNS}
    if previous:
        row.update(previous)
    row.update(date=day_date.isoformat(), config_id=config_id(p), source=f"{broker.name}/{data.name}",
               logged_at=datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%MZ"))
    if sim is not None:
        row["sim_outcome"] = sim["why"]
        if sim["dir"] != 0:
            row["sim_R"] = f(sim["pts"] / sim["risk"], 3)

    orders = (broker.trade_orders(day_date, order_id(day_date)) if hasattr(broker, "trade_orders")
              else broker.day_orders(day_date))
    parent = next((o for o in orders if o.client_order_id == order_id(day_date)), None)
    if parent is None:
        if previous:
            raise RuntimeError(f"Historical entry {order_id(day_date)} not found; preserving old row")
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
    d = -1 if parent.side.endswith("sell") else 1          # a sell entry is a short
    out_side = "buy" if d == -1 else "sell"
    sells = [o for o in orders if o.id != parent.id and o.side.endswith(out_side) and o.filled_qty
             and o.filled_avg_price is not None]
    # Only exits that filled after the bot's own entry count (ignores unrelated orders earlier in the day).
    if parent.filled_at is not None:
        sells = [o for o in sells if o.filled_at is None or o.filled_at >= parent.filled_at]
    sold = sum(o.filled_qty for o in sells)
    entry, qty = parent.filled_avg_price, parent.filled_qty
    row.update(shares=f(qty, 0), entry=f(entry), stop=f(sl.stop_price if sl else None),
               target=f(tp.limit_price if tp else None))
    if sold > qty + 0.000001:
        raise RuntimeError("Exit quantity exceeds the entry; manual order attribution needs review")
    if sold < qty - 0.000001:
        row["outcome"] = "still_open"
        for field in ("exit", "profit", "R", "shares_5k", "profit_5k"):
            row[field] = ""
        return row
    exit_px = sum(o.filled_qty * o.filled_avg_price for o in sells) / sold
    if tp is not None and tp.filled_qty:
        row["outcome"] = "target"
    elif sl is not None and sl.filled_qty:
        row["outcome"] = "stop"
    else:
        filled_dates = [pd.Timestamp(o.filled_at).tz_convert(TZ).date() for o in sells if o.filled_at is not None]
        row["outcome"] = "late_close" if any(d > day_date for d in filled_dates) else "eod"
    qty_5k = max(0, math.floor(SMALL_ACCOUNT / entry))
    move = d * (exit_px - entry)
    row.update(exit=f(exit_px), profit=f(move * sold), shares_5k=str(qty_5k), profit_5k=f(move * qty_5k))
    if sl is not None and d * (entry - sl.stop_price) > 0:
        row["R"] = f(move / abs(entry - sl.stop_price), 3)
    return row


def append_row(path, row):
    os.makedirs(os.path.dirname(os.path.abspath(path)), exist_ok=True)
    new = not os.path.isfile(path)
    with open(path, "a", newline="") as fh:
        w = csv.DictWriter(fh, fieldnames=COLUMNS)
        if new:
            w.writeheader()
        w.writerow(row)



def read_rows(path):
    if not os.path.isfile(path):
        return []
    with open(path, newline="") as fh:
        return list(csv.DictReader(fh))


def upsert_row(path, row):
    """Atomically replace this date, preserving all other dates and their order."""
    rows = read_rows(path)
    by_date = {r["date"]: r for r in rows}
    by_date[row["date"]] = row
    folder = os.path.dirname(os.path.abspath(path))
    os.makedirs(folder, exist_ok=True)
    fd, temporary = tempfile.mkstemp(dir=folder, suffix=".csv")
    try:
        with os.fdopen(fd, "w", newline="") as fh:
            writer = csv.DictWriter(fh, fieldnames=COLUMNS)
            writer.writeheader()
            writer.writerows(by_date[d] for d in sorted(by_date))
        os.replace(temporary, path)
    finally:
        if os.path.exists(temporary):
            os.unlink(temporary)


def reconcile_pending(broker, data, p):
    for old in read_rows(LOG):
        if old["outcome"] not in ("still_open", "order_not_filled"):
            continue
        row = build_row(broker, data, date.fromisoformat(old["date"]), p, None, previous=old)
        if row["outcome"] != old["outcome"] or row.get("profit") != old.get("profit"):
            upsert_row(LOG, row)
            print(f"Reconciled {row['date']}: {result_text(row)}")


def result_text(row):
    if row["entry"] == "":
        return f"No trade ({row['outcome'].replace('_', ' ')})."
    if row["profit"] == "":
        return f"Order placed but not closed ({row['outcome'].replace('_', ' ')})."
    short = row["stop"] != "" and float(row["stop"]) > float(row["entry"])
    return (f"{row['outcome'].title()}{' (short)' if short else ''}: {row['shares']} QQQ, "
            f"in {row['entry']}, out {row['exit']}. "
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
    title = label(today)
    if hours[1].hour * 60 + hours[1].minute < A.RTH_CLOSE:
        push(f"{title}: no trade", "Half day: the bot does not trade shortened sessions.", "no_entry_sign")
        return 0
    if broker.has_order(order_id(today)):
        print("Today's order was already sent; nothing to do.")
        return 0
    if broker.position_qty() != 0 or broker.open_orders():
        push(f"{title}: BLOCKED", "A QQQ position or order already exists; reconciliation is required.",
             "rotating_light")
        return 1

    candle = p.entry_mode == "candle"
    or_end = E.RTH_OPEN + p.or_min
    # Candle mode enters at the open, so a start more than 5 minutes late is a missed day.
    stop_at = or_end + 5 if candle else p.cutoff + 2
    if now.hour * 60 + now.minute > stop_at:
        push(f"{title}: STARTED TOO LATE", "Entry window missed; no late order will be placed.", "warning")
        print("Past the entry window; nothing to do.")
        return 1
    if candle:
        # The entry bar has to be complete in the data, so the earliest decision is one minute after the range.
        go = pd.Timestamp(today) + pd.Timedelta(minutes=or_end + 1, seconds=5)
        wait = (go - now).total_seconds()
        if wait > 0:
            print(f"Waiting {wait / 60:.1f} min for the {p.or_min}-minute candle...")
            time.sleep(wait)
    else:
        wait = (or_end + 1) - (now.hour * 60 + now.minute)
        if wait > 0:
            print(f"Waiting {wait} min for the {p.or_min}-minute range to finish...")
            time.sleep(wait * 60)

    vix, day = safe_vix(), None
    while True:
        now = pd.Timestamp.now(tz=TZ).tz_localize(None)
        final = now.hour * 60 + now.minute >= stop_at
        try:
            if broker.has_order(order_id(today)):
                print("Today's order exists; no additional submission.")
                return 0
            if day is None:
                day = base_day(data, today, vix)
            b1 = minute_bars(data, today, upto=now) if day is not None else []
            verdict = decide(with_bars(day, b1), p, final) if len(b1) else None
            if verdict and verdict[0] == "none":
                push(f"{title}: no trade", verdict[2], "no_entry_sign")
                return 0
            if verdict and verdict[0] == "trade":
                last = float(b1["close"].iloc[-1]) if candle else None
                plan = order_plan(verdict[1], p, broker.account().buying_power, last)
                if plan is None:
                    push(f"{title}: no trade", "Price was already through the stop when the order was due.",
                         "no_entry_sign")
                    return 0
                if plan["side"] == "sell":
                    ok, why = broker.can_short()
                    if not ok:
                        push(f"{title}: no trade", f"Short signal, but {why}.", "warning")
                        return 0
                broker.place_bracket(plan["qty"], plan["stop"], plan["target"], order_id(today), side=plan["side"])
                verb = "Bought" if plan["side"] == "buy" else "Sold short"
                push(f"{title}: ORDER PLACED (practice)",
                     f"{verb} {plan['qty']} QQQ near {plan['signal']:,.2f}. Stop {plan['stop']:,.2f}, "
                     f"target {plan['target']:,.2f}. Risk about ${plan['qty'] * plan['per_share']:,.0f}. "
                     f"Alpaca paper account, no real money.")
                return 0
        except Exception as e:   # one bad poll should not end the morning
            print(f"[{now:%H:%M}] poll failed: {e}")
        if final:
            push(f"{title}: no trade", "No decision by the cutoff (data unavailable).", "warning")
            return 0
        time.sleep(10 if candle else 60)


def mode_close():
    if not A.have_keys():
        raise RuntimeError("Alpaca paper keys are not set")
    broker, data, p = A.AlpacaBroker(), A.AlpacaData(), qqq_params()
    now = pd.Timestamp.now(tz=TZ).tz_localize(None)
    today = now.date()
    hours = broker.hours(today)
    if hours is None:
        print("Market is closed today.")
        return 0
    flatten_at = hours[1] - pd.Timedelta(minutes=FLATTEN_BEFORE_CLOSE_MIN)
    wait = (flatten_at - now).total_seconds()
    if wait > 0:
        print(f"Waiting {wait / 60:.0f} min until {flatten_at:%H:%M} ET to flatten...")
        time.sleep(wait)
    print(f"Before close: {broker.position_qty():g} QQQ; {len(broker.open_orders())} open orders")
    flat = broker.flatten()  # Always check the account, even if today has a log row.
    remaining = (hours[1] + pd.Timedelta(minutes=3) - pd.Timestamp.now(tz=TZ).tz_localize(None)).total_seconds()
    if remaining > 0:
        time.sleep(remaining)
    reconcile_pending(broker, data, p)
    previous = next((r for r in read_rows(LOG) if r["date"] == today.isoformat()), None)
    if previous is None:
        row = build_row(broker, data, today, p, safe_vix())
        upsert_row(LOG, row)
    else:
        row = previous
    qty, open_count = broker.position_qty(), len(broker.open_orders())
    print(f"Verified account: {qty:g} QQQ; {open_count} open orders")
    unresolved = any(r["outcome"] == "still_open" for r in read_rows(LOG))
    if not flat or qty != 0 or open_count or unresolved:
        push(f"{label(today)}: CLOSE UNRESOLVED", "Paper position/order or unresolved record remains. "
             "Check the account; a queued after-hours close is not a confirmed fill.", "rotating_light")
        return 1
    push(f"{label(today)}: result", result_text(row), "bar_chart")
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
            last = float(part["close"].iloc[-1]) if p.entry_mode == "candle" else None
            plan = order_plan(verdict[1], p, broker.account().buying_power, last)
            if plan is None:
                print(f"{part.index[-1]:%H:%M} no trade: price already through the stop")
                break
            broker.place_bracket(plan["qty"], plan["stop"], plan["target"], order_id(day_date),
                                 side=plan["side"], placed_at=part.index[-1])
            print(f"{part.index[-1]:%H:%M} order: {plan['side']} {plan['qty']} near {plan['signal']:.2f}, stop {plan['stop']:.2f}, "
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
    ap.add_argument("--variant", default="base", choices=list(variants.ALL))
    a = ap.parse_args()
    global V, LOG
    V = variants.get(a.variant)
    LOG = V.path("paper_log")
    print(f"Variant: {V.name} (settings {config_id(qqq_params())}, order ids {V.order_prefix}-<date>, "
          f"log {V.paper_log})")
    if a.mode == "entry":
        return mode_entry()
    if a.mode == "close":
        return mode_close()
    if a.mode == "status":
        return mode_status()
    return mode_replay(date.fromisoformat(a.day), a.out)


if __name__ == "__main__":
    sys.exit(main())
