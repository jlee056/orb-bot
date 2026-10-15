"""Backtest engine for the ORB strategy in orb_bot.py.

Data (all converted to naive Eastern time, bars labelled by START minute):
  kaggle  - NQ 1-min, 2022-12 to 2025-12  (data/kaggle/Dataset_NQ_1min_2022_2025.csv)
  github  - MNQ 1-min, 2026-01 to 2026-04 (data/github/MNQ_1min_20260120_20260415.csv)
  yf      - NQ=F 5-min, last ~60 days     (yfinance, cached in data/yf_5m.pkl)

Nothing here talks to a broker.
"""
import math
import os
from dataclasses import dataclass, field, replace

import numpy as np
import pandas as pd

HERE = os.path.dirname(os.path.abspath(__file__))
DATA = os.path.join(HERE, "data")
MULT = 2.0          # MNQ dollars per point
RTH_OPEN = 9 * 60 + 30
RTH_CLOSE = 16 * 60


# ---------------------------------------------------------------------------
# Loading
# ---------------------------------------------------------------------------

def load_kaggle():
    d = pd.read_csv(os.path.join(DATA, "kaggle", "Dataset_NQ_1min_2022_2025.csv"),
                    usecols=[0, 1, 2, 3, 4, 5])
    d.columns = ["ts", "open", "high", "low", "close", "volume"]
    # File is ET, labelled by bar END minute (volume peaks at 09:31 and 16:00).
    d["ts"] = pd.to_datetime(d["ts"], format="%m/%d/%Y %H:%M") - pd.Timedelta(minutes=1)
    return d.set_index("ts").sort_index()


def load_github():
    d = pd.read_csv(os.path.join(DATA, "github", "MNQ_1min_20260120_20260415.csv"))
    d.columns = ["ts", "open", "high", "low", "close", "volume"]
    # File is UTC, labelled by bar START minute (volume peaks at 14:30 UTC in winter).
    ts = pd.to_datetime(d["ts"]).dt.tz_localize("UTC").dt.tz_convert("America/New_York").dt.tz_localize(None)
    d["ts"] = ts
    return d.set_index("ts").sort_index()


def load_yf(refresh=False):
    path = os.path.join(DATA, "yf_5m.pkl")
    if os.path.isfile(path) and not refresh:
        return pd.read_pickle(path)   # local cache this script wrote itself
    import yfinance as yf
    d = yf.download("NQ=F", period="60d", interval="5m", progress=False, multi_level_index=False)
    d.index = d.index.tz_convert("America/New_York").tz_localize(None)
    d = d.rename(columns=str.lower)[["open", "high", "low", "close", "volume"]]
    d.index.name = "ts"
    os.makedirs(DATA, exist_ok=True)
    d.to_pickle(path)
    return d


def load_vix():
    path = os.path.join(DATA, "vix_daily.pkl")
    if os.path.isfile(path):
        return pd.read_pickle(path)
    import yfinance as yf
    v = yf.download("^VIX", period="max", interval="1d", progress=False, multi_level_index=False)["Close"]
    v.index = v.index.tz_localize(None)
    v.to_pickle(path)
    return v


# ---------------------------------------------------------------------------
# Per-day preparation
# ---------------------------------------------------------------------------

@dataclass
class Day:
    date: object
    mod: np.ndarray      # minute-of-day of each RTH bar start
    o: np.ndarray
    h: np.ndarray
    l: np.ndarray
    c: np.ndarray
    bar: int             # bar length in minutes
    vix: float
    prev_close: float    # prior RTH close
    prev_above: object   # prior session close > EMA20
    prev_days_above: float
    atr: float           # ATR(14) of full sessions, known before today's open


def prepare(df, vix=None, atr_period=14, partial_last=False):
    """Turn an intraday frame into a list of Day objects with no-lookahead daily features.
    partial_last=True also keeps the final day while its session is still in progress."""
    bar = int(pd.Series(df.index[1:200] - df.index[:199]).mode()[0].total_seconds() // 60)
    mod_all = df.index.hour * 60 + df.index.minute

    # Full-session daily bars (session = 18:00 previous day to 17:00), like yfinance NQ=F daily.
    sess = (df.index + pd.Timedelta(hours=6)).normalize()
    g = df.groupby(sess)
    daily = pd.DataFrame({"high": g["high"].max(), "low": g["low"].min(), "close": g["close"].last()})
    daily = daily[daily.index.dayofweek < 5]
    pc = daily["close"].shift(1)
    tr = pd.concat([daily["high"] - daily["low"], (daily["high"] - pc).abs(), (daily["low"] - pc).abs()],
                   axis=1).max(axis=1)
    ema = daily["close"].ewm(span=20, adjust=False).mean()
    above = daily["close"] > ema
    streak = above.astype(int).groupby((~above).cumsum()).cumsum()
    feat = pd.DataFrame({"atr": tr.rolling(atr_period).mean(), "above": above,
                         "days_above": streak}).shift(1)

    rth = df[(mod_all >= RTH_OPEN) & (mod_all < RTH_CLOSE)]
    days, prev_close = [], np.nan
    last_day = rth.index[-1].normalize() if len(rth) else None
    for d, b in rth.groupby(rth.index.normalize()):
        mod = (b.index.hour * 60 + b.index.minute).to_numpy()
        full = len(b) >= 0.95 * (RTH_CLOSE - RTH_OPEN) / bar and mod[0] == RTH_OPEN
        if partial_last and d == last_day and mod[0] == RTH_OPEN:
            full = True
        f = feat.loc[d] if d in feat.index else None
        if full and f is not None and not np.isnan(f["atr"]):
            v = np.nan
            if vix is not None:
                prior = vix[vix.index < d]
                v = float(prior.iloc[-1]) if len(prior) else np.nan
            days.append(Day(d.date(), mod, b["open"].to_numpy(float), b["high"].to_numpy(float),
                            b["low"].to_numpy(float), b["close"].to_numpy(float), bar, v, prev_close,
                            bool(f["above"]), float(f["days_above"]), float(f["atr"])))
        prev_close = float(b["close"].iloc[-1])
    return days


# ---------------------------------------------------------------------------
# Strategy parameters
# ---------------------------------------------------------------------------

@dataclass(frozen=True)
class P:
    or_min: int = 30               # opening range length, minutes
    cutoff: int = 11 * 60          # no entries after this minute-of-day
    eod: int = 15 * 60 + 50        # force close
    shorts: bool = False
    entry_mode: str = "breakout"  # "always" = buy the first 5-min close after the range (benchmark only)
    #                               "candle" = trade the range candle's direction at the next bar's open
    # stop: "atr" max(orb_low, entry - k*ATR) | "orb_low" | "midpoint" | "cap" max(orb_low, entry - k pts)
    #       | "pct" entry*(1-k) floored at orb_low
    stop_mode: str = "atr"
    stop_k: float = 0.4
    # target: "range" orb_high + k*range | "r" entry + k*risk | "none" hold to EOD
    target_mode: str = "range"
    target_k: float = 1.0
    breakeven: float = 0.75        # move stop to entry at this fraction of the way to target; 0 = off
    # filters (True = enforce, like live mode)
    f_friday: bool = False
    f_vix: bool = False
    f_ema: bool = False
    f_ema_dir: bool = False        # with f_ema: longs need above EMA, shorts need below (instead of blocking the day)
    f_gap: bool = False
    f_range: bool = False
    skip_days: tuple = ()          # weekdays to skip (Mon=0)
    vix_min: float = 13
    vix_max: float = 35
    ema_days: int = 3
    gap_max: float = 0.007
    range_max: float = 0.008
    range_min: float = 0.0
    # costs
    slip: float = 0.5              # points of slippage on market/stop fills (2 ticks)
    commission: float = 1.24       # dollars per contract round trip
    # sizing
    account: float = 5000
    risk_pct: float = 0.015
    max_contracts: int = 3
    oversize: str = "min1"         # "min1" trade 1 contract even if over budget | "skip"
    oversize_tol: float = 1.0      # with "skip": allow 1-contract risk up to tol * budget
    mult: float = MULT             # dollars per point per unit: 2.0 for MNQ, 1.0 for one share
    monthly_cap: float = 0.0       # dollars of loss that halt the month; 0 = off
    monthly_net: bool = True       # True: cap on net month P&L | False: cap on summed losing trades (old bot)


def flags(day, p, orb_high, orb_low):
    out = []
    rng = (orb_high - orb_low) / ((orb_high + orb_low) / 2)
    if day.date.weekday() == 4:
        out.append("friday")
    if not np.isnan(day.vix):
        if day.vix < p.vix_min:
            out.append("vix_low")
        if day.vix > p.vix_max:
            out.append("vix_high")
    if not day.prev_above:
        out.append("below_ema")
    elif day.prev_days_above < p.ema_days:
        out.append("ema_whipsaw")
    if not np.isnan(day.prev_close) and (day.o[0] - day.prev_close) / day.prev_close > p.gap_max:
        out.append("gap")
    if rng > p.range_max:
        out.append("range_wide")
    if rng < p.range_min:
        out.append("range_narrow")
    return out, rng


def blocked(fl, day, p):
    if day.date.weekday() in p.skip_days:
        return True
    if p.f_friday and "friday" in fl:
        return True
    if p.f_vix and ("vix_low" in fl or "vix_high" in fl):
        return True
    if p.f_ema and not p.f_ema_dir and ("below_ema" in fl or "ema_whipsaw" in fl):
        return True
    if p.f_gap and "gap" in fl:
        return True
    if p.f_range and "range_wide" in fl:
        return True
    return "range_narrow" in fl


def _first(mask, start):
    idx = np.flatnonzero(mask[start:])
    return idx[0] + start if len(idx) else None


def simulate(day, p):
    """One day. Returns dict (traded or not). Points are net of slippage, per contract."""
    mod, bar = day.mod, day.bar
    or_end = RTH_OPEN + p.or_min
    in_or = mod < or_end
    if in_or.sum() < p.or_min // bar:
        return None
    orb_high, orb_low = day.h[in_or].max(), day.l[in_or].min()
    fl, rng = flags(day, p, orb_high, orb_low)
    rec = {"date": day.date, "range_pct": rng, "flags": ";".join(fl), "why": "no_breakout",
           "pts": 0.0, "risk": np.nan, "dir": 0}
    if blocked(fl, day, p):
        rec["why"] = "filtered"
        return rec

    i, direction = None, 0
    if p.entry_mode == "candle":
        # The range is one candle: trade its direction at the open of the first bar after it.
        c_open, c_close = day.o[in_or][0], day.c[in_or][-1]
        after = np.flatnonzero(mod >= or_end)
        if c_close == c_open:
            rec["why"] = "doji"
            return rec
        if not len(after):
            return rec
        i, direction = after[0], (1 if c_close > c_open else -1)
    else:
        # 5-minute closes strictly after the range and up to the cutoff.
        end = mod + bar
        sig = np.flatnonzero((end % 5 == 0) & (end > or_end) & (end <= p.cutoff))
        for k in sig:
            if p.entry_mode == "always":
                i, direction = k, 1
                break
            if day.c[k] > orb_high:
                i, direction = k, 1
                break
            if day.c[k] < orb_low:
                if p.shorts:
                    i, direction = k, -1
                else:
                    rec["why"] = "downside_break"
                break
    if i is None:
        return rec

    # Trend filter per direction: only the first break counts, there is no second look.
    if p.f_ema and p.f_ema_dir:
        if direction == 1 and ("below_ema" in fl or "ema_whipsaw" in fl):
            rec["why"] = "filtered_dir"
            return rec
        if direction == -1 and "below_ema" not in fl:
            rec["why"] = "filtered_dir"
            return rec

    # Mirror prices for shorts so the rest is written long-only.
    if direction == 1:
        o, h, l, c, hi, lo = day.o, day.h, day.l, day.c, orb_high, orb_low
    else:
        o, h, l, c, hi, lo = -day.o, -day.l, -day.h, -day.c, -orb_low, -orb_high

    # Breakout fills at the signal bar's close; candle mode fills at the entry bar's open.
    candle = p.entry_mode == "candle"
    ref = o[i] if candle else c[i]
    entry = ref + p.slip
    if p.stop_mode == "atr":
        stop = max(lo, ref - p.stop_k * day.atr)
    elif p.stop_mode == "orb_low":
        stop = lo
    elif p.stop_mode == "midpoint":
        stop = (hi + lo) / 2
    elif p.stop_mode == "cap":
        stop = max(lo, ref - p.stop_k)
    elif p.stop_mode == "pct":
        stop = max(lo, ref - p.stop_k * abs(ref))
    else:
        raise ValueError(p.stop_mode)
    risk = entry - stop
    if p.target_mode == "range":
        target = hi + p.target_k * (hi - lo)
    elif p.target_mode == "r":
        target = ref + p.target_k * (ref - stop)
    else:
        target = np.inf
    if target <= entry or risk <= 0:
        rec["why"] = "no_room"
        return rec

    j0 = i if candle else i + 1
    eod_i = _first(mod >= p.eod, j0)
    last = eod_i if eod_i is not None else len(c)
    hs, ls, cs = h[:last], l[:last], c[:last]
    t_tgt = _first(hs >= target, j0)
    t_stop = _first(ls <= stop, j0)
    t_be = None
    if p.breakeven > 0 and np.isfinite(target):
        t_be = _first(cs >= ref + p.breakeven * (target - ref), j0)

    INF = 10 ** 9
    a_tgt = t_tgt if t_tgt is not None else INF
    a_stop = t_stop if t_stop is not None else INF
    why, exit_px = "eod", None
    if t_be is not None and t_be < a_stop and t_be < a_tgt:
        t_bes = _first(ls <= ref, t_be + 1)
        a_bes = t_bes if t_bes is not None else INF
        if a_bes <= a_tgt and a_bes < INF:
            why, exit_px = "breakeven", min(ref, o[a_bes]) - p.slip
        elif a_tgt < INF:
            why, exit_px = "target", target
    elif a_stop <= a_tgt and a_stop < INF:      # same-bar tie goes to the stop (conservative)
        why, exit_px = "stop", min(stop, o[a_stop]) - p.slip
    elif a_tgt < INF:
        why, exit_px = "target", target
    if exit_px is None:
        exit_px = (o[eod_i] if eod_i is not None else c[-1]) - p.slip

    rec.update(why=why, dir=direction, entry=entry, stop=stop, target=target, exit=exit_px,
               pts=exit_px - entry, risk=risk)
    return rec


def prices(rec):
    """Real (positive) entry/stop/target/exit of a traded record. simulate() keeps short prices
    mirrored (negative); pts and risk are already signed correctly."""
    s = rec["dir"]
    return {k: s * rec[k] for k in ("entry", "stop", "target", "exit")}


# ---------------------------------------------------------------------------
# Portfolio + statistics
# ---------------------------------------------------------------------------

def run(days, p):
    """Simulate all days, then apply sizing, commissions and the monthly loss cap."""
    budget = p.account * p.risk_pct
    rows, month, month_loss = [], None, 0.0
    for d in days:
        r = simulate(d, p)
        if r is None:
            continue
        r["qty"], r["usd"], r["risk_usd"] = 0, 0.0, 0.0
        ym = (d.date.year, d.date.month)
        if ym != month:
            month, month_loss = ym, 0.0
        if r["dir"] != 0:
            if p.monthly_cap and month_loss >= p.monthly_cap:
                r.update(why="monthly_cap", dir=0, pts=0.0)
            else:
                risk_usd = r["risk"] * p.mult
                qty = min(math.floor(budget / risk_usd), p.max_contracts)
                if qty < 1:
                    qty = 1 if (p.oversize == "min1" or risk_usd <= p.oversize_tol * budget) else 0
                if qty == 0:
                    r.update(why="over_risk", dir=0, pts=0.0)
                else:
                    r["qty"] = qty
                    r["usd"] = r["pts"] * p.mult * qty - p.commission * qty
                    r["risk_usd"] = risk_usd * qty
                    if p.monthly_net:
                        month_loss -= r["usd"]
                    elif r["usd"] < 0:
                        month_loss += -r["usd"]
        rows.append(r)
    return pd.DataFrame(rows)


def stats(res):
    t = res[res["dir"] != 0]
    n = len(t)
    if n == 0:
        return {"days": len(res), "n": 0}
    R = (t["pts"] / t["risk"]).to_numpy()
    usd = t["usd"].to_numpy()
    wins, losses = usd[usd > 0], usd[usd < 0]
    eq = np.cumsum(usd)
    dd = float((np.maximum.accumulate(np.maximum(eq, 0)) - eq).max())
    sd = R.std(ddof=1) if n > 1 else np.nan
    return {
        "days": len(res), "n": n,
        "win%": round(100 * (usd > 0).mean(), 1),
        "avgR": round(float(R.mean()), 3),
        "t": round(float(R.mean() / sd * math.sqrt(n)), 2) if sd and sd > 0 else np.nan,
        "PF": round(float(wins.sum() / -losses.sum()), 2) if len(losses) else np.inf,
        "usd": round(float(usd.sum())),
        "avg$": round(float(usd.mean()), 1),
        "maxDD$": round(dd),
        "worst$": round(float(usd.min())),
        "avgRisk$": round(float(t["risk_usd"].mean())),
    }


def datasets():
    """Named day-lists. Kaggle is split by calendar year for in/out-of-sample work."""
    vix = load_vix()
    out = {}
    k = prepare(load_kaggle(), vix)
    for y in (2023, 2024, 2025):
        out[str(y)] = [d for d in k if d.date.year == y]
    out["2026H1"] = prepare(load_github(), vix)
    out["2026H2"] = prepare(load_yf(), vix)
    return out
