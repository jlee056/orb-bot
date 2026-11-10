"""Walk-forward and data-snooping tests for the frozen ORB base rules.

The protocol (grid, windows, objective, thresholds) is in docs/WALKFORWARD.md and in PROTOCOL below.
It was written before any real result was looked at. Do not change it after seeing results.
This file reuses orb_engine.py and changes nothing in it, so the frozen base settings hash is untouched.

Run:  python walkforward.py --market qqq --mode anchored
      python walkforward.py --market qqq --mode rolling
      python walkforward.py --market nq --mode anchored        (cross-check on NQ/MNQ futures)
      python walkforward.py --selftest                          (null-data and planted-edge checks)
Options: --slip 0.05   cost stress run (QQQ dollars per share, NQ points); skips the reproduction gate
         --reps N      bootstrap repetitions (default from PROTOCOL)
"""
import argparse
import glob
import hashlib
import itertools
import json
import math
import os
import sys

import numpy as np
import pandas as pd
from scipy import stats as sps

import orb_engine as E

HERE = os.path.dirname(os.path.abspath(__file__))
OUT = os.path.join(HERE, "docs", "data")

PROTOCOL = dict(
    or_min=[30, 45, 60, 75, 90],
    target_k=[0.25, 0.35, 0.5, 0.75, 1.0],
    ema=[True, False],
    min_is_trades=30,                      # a grid cell needs this many in-sample trades to be eligible
    objective="average R per trade (pts / risk) in-sample",
    start_year={"qqq": 2020, "nq": 2023},
    is_years={"anchored": {"qqq": 2, "nq": 1}, "rolling": {"qqq": 3, "nq": 2}},
    oos_years=1,                           # calendar-year out-of-sample windows, step = 1 year, no overlap
    boot_block=10,                         # mean stationary-bootstrap block, trading days (5 and 20 reported as sensitivity)
    boot_reps=5000,
    seed=7,
    cscv_blocks=16,
    earlier_settings_examined=800,         # logbook: about 800 setups were looked at in total
    pass_rules=dict(pos_windows=0.6, wfe=0.5, spa_p=0.05),
)
PROTOCOL_ID = hashlib.sha1(json.dumps(PROTOCOL, sort_keys=True).encode()).hexdigest()[:8]

# Reproduction gate: numbers from docs/LOGBOOK.md and variants.BACKTEST for the frozen base.
REFERENCE = {
    "qqq": dict(n=432, win=62.7, avgR=0.084, maxDD=684),
    "nq": dict(n=216, win=65, avgR=0.13, PF=1.48, maxDD=985),   # logbook gives NQ win rate as a rounded integer
}
REFERENCE_END = {"qqq": "2026-10-09", "nq": None}   # the reference numbers were produced on data ending here
REGISTERED_END = "2026-10-09"                         # the 2026-11-09 results in docs/WALKFORWARD.md use data to this date
EULER = 0.5772156649015329


# ---------------------------------------------------------------------------
# Data and parameter grid
# ---------------------------------------------------------------------------

def load_days(market):
    if market == "qqq":
        files = sorted(glob.glob(os.path.join(E.DATA, "alpaca", "QQQ_1min_*.csv")))
        if not files:
            raise SystemExit("No QQQ data. Run: python get_data.py --qqq")
        df = pd.concat(pd.read_csv(f, index_col=0, parse_dates=True) for f in files).sort_index()
        return E.prepare(df, E.load_vix())
    ds = E.datasets()
    return sorted((d for v in ds.values() for d in v), key=lambda d: d.date)


def base_params(market, slip=None):
    """The frozen base rules exactly as backtest.py runs them."""
    if market == "qqq":
        import variants
        from alpaca_bot import RISK_USD, qqq_params
        p = E.replace(qqq_params(variants.get("base")), account=RISK_USD / 0.015, risk_pct=0.015,
                      max_contracts=10 ** 6)
    else:
        import backtest
        p = E.replace(backtest.params_from_config(), oversize="min1", monthly_cap=0)
    return E.replace(p, slip=slip) if slip is not None else p


def grid_cells(base):
    cells = {}
    for om in PROTOCOL["or_min"]:
        for tk in PROTOCOL["target_k"]:
            for ema in PROTOCOL["ema"]:
                cells[(om, tk, ema)] = E.replace(base, or_min=om, target_k=tk, cutoff=max(720, 570 + om + 60),
                                                 f_ema=ema)
    return cells


def frame(res):
    """E.run output as a date-indexed frame with R per trade (0 on days without a trade)."""
    f = res.copy()
    f.index = pd.to_datetime(f.pop("date"))
    f["R"] = (f["pts"] / f["risk"]).where(f["dir"] != 0, 0.0).fillna(0.0)
    return f


def run_cells(days, cells):
    return {k: frame(E.run(days, p)) for k, p in cells.items()}


def daily_matrix(results):
    """Days x cells matrix of daily R (0 on days without a trade)."""
    return pd.DataFrame({k: v["R"] for k, v in results.items()}).sort_index().fillna(0.0)


# ---------------------------------------------------------------------------
# Walk-forward
# ---------------------------------------------------------------------------

def make_windows(start_year, is_years, mode, last_date):
    out = []
    for oy in range(start_year + is_years, last_date.year + 1):
        out.append(dict(
            is_start=pd.Timestamp(start_year, 1, 1) if mode == "anchored" else pd.Timestamp(oy - is_years, 1, 1),
            is_end=pd.Timestamp(oy - 1, 12, 31), oos_year=oy,
            oos_start=pd.Timestamp(oy, 1, 1), oos_end=min(pd.Timestamp(oy, 12, 31), last_date)))
    return out


def select(results, start, end, min_trades, default):
    """Best cell by in-sample average R. Looks only at rows dated start..end (the in-sample window)."""
    best, best_avg, best_n = None, -np.inf, 0
    for key in sorted(results):
        f = results[key].loc[start:end]
        t = f[f["dir"] != 0]
        if len(t) < min_trades:
            continue
        m = float(t["R"].mean())
        if m > best_avg:
            best, best_avg, best_n = key, m, len(t)
    if best is None:
        return default, float("nan"), 0, True
    return best, best_avg, best_n, False


def _avg(f):
    t = f[f["dir"] != 0]
    return float(t["R"].mean()) if len(t) else float("nan")


def walk_forward(results, base_key, bench, windows, min_trades):
    rows, oos, frozen, benchp = [], [], [], []
    for w in windows:
        if not w["is_end"] < w["oos_start"]:
            raise AssertionError("in-sample window must end before the out-of-sample window starts")
        key, is_avg, is_n, fallback = select(results, w["is_start"], w["is_end"], min_trades, base_key)
        sl = slice(w["oos_start"], w["oos_end"])
        o, fz, bn = results[key].loc[sl], results[base_key].loc[sl], bench.loc[sl]
        is_f = results[key].loc[w["is_start"]:w["is_end"]]
        rows.append(dict(
            oos_year=w["oos_year"], chosen=key, fallback=fallback, is_trades=is_n, is_avgR=is_avg,
            is_days=len(is_f), is_sumR=float(is_f["R"].sum()),
            oos_trades=int((o["dir"] != 0).sum()), oos_avgR=_avg(o), oos_days=len(o), oos_sumR=float(o["R"].sum()),
            frozen_trades=int((fz["dir"] != 0).sum()), frozen_avgR=_avg(fz),
            bench_trades=int((bn["dir"] != 0).sum()), bench_avgR=_avg(bn)))
        oos.append(o)
        frozen.append(fz)
        benchp.append(bn)
    return pd.DataFrame(rows), pd.concat(oos), pd.concat(frozen), pd.concat(benchp)


def summarize(win, oos, frozen, bench):
    st = E.stats(oos)
    is_avg = float((win["is_avgR"] * win["is_trades"]).sum() / win["is_trades"].sum()) if win["is_trades"].sum() else np.nan
    is_rate = win["is_sumR"].sum() / win["is_days"].sum()
    oos_rate = win["oos_sumR"].sum() / win["oos_days"].sum()
    chosen = list(win["chosen"])
    return dict(
        oos_stats=st, frozen_stats=E.stats(frozen), bench_stats=E.stats(bench),
        windows=len(win), share_positive=float((win["oos_avgR"] > 0).mean()),
        wfe_trade=float(st.get("avgR", np.nan) / is_avg) if is_avg else np.nan,
        wfe_year=float(oos_rate / is_rate) if is_rate else np.nan,
        param_changes=int(sum(chosen[i] != chosen[i - 1] for i in range(1, len(chosen)))),
        fallbacks=int(win["fallback"].sum()))


# ---------------------------------------------------------------------------
# Bootstrap, Reality Check / SPA, PBO, deflated Sharpe
# ---------------------------------------------------------------------------

def sb_indices(rng, T, B, mean_block):
    """Politis-Romano stationary bootstrap: B index paths of length T (circular)."""
    new = rng.random((B, T)) < 1.0 / mean_block
    jump = rng.integers(0, T, (B, T))
    idx = np.empty((B, T), dtype=np.int32)
    idx[:, 0] = rng.integers(0, T, B)
    for t in range(1, T):
        nxt = idx[:, t - 1] + 1
        nxt[nxt == T] = 0
        idx[:, t] = np.where(new[:, t], jump[:, t], nxt)
    return idx


def boot_means(D, rng, mean_block, reps, chunk=100):
    T, k = D.shape
    out = np.empty((reps, k))
    for s in range(0, reps, chunk):
        b = min(chunk, reps - s)
        out[s:s + b] = D[sb_indices(rng, T, b, mean_block)].mean(axis=1)
    return out


def reality_check(D, mean_block, reps, seed):
    """White (2000) Reality Check and Hansen (2005) SPA p-values.
    D: days x models matrix of R differences (model minus benchmark). Null: no model has a positive mean."""
    D = np.asarray(D, float)
    T, k = D.shape
    rng = np.random.default_rng(seed)
    dbar = D.mean(0)
    Ds = boot_means(D, rng, mean_block, reps)
    omega = np.sqrt(T * Ds.var(axis=0, ddof=1))
    omega = np.where(omega > 0, omega, np.inf)            # a cell that never trades has no information
    root = math.sqrt(T)
    stat = max(0.0, float((root * dbar / omega).max()))
    A = 0.25 * T ** -0.25 * omega
    centers = {"lower": np.maximum(dbar, 0.0), "consistent": np.where(dbar >= -A, dbar, 0.0), "upper": dbar}
    out = {f"spa_{n}": float((np.maximum(0.0, (root * (Ds - g) / omega).max(1)) >= stat).mean())
           for n, g in centers.items()}
    out["rc"] = float(((root * (Ds - dbar)).max(1) >= (root * dbar).max()).mean())
    out["best_cell"] = int(np.argmax(dbar))
    out["best_mean_R_per_day"] = float(dbar.max())
    return out


def mean_pvalue(x, mean_block, reps, seed):
    """One-sided stationary-bootstrap p-value that the mean of x is at most zero (a single test, no search)."""
    x = np.asarray(x, float)
    rng = np.random.default_rng(seed)
    centered = (x - x.mean())[:, None]
    m = boot_means(centered, rng, mean_block, reps)[:, 0]
    return float((m >= x.mean()).mean())


def pbo_cscv(M, S=16):
    """Probability of Backtest Overfitting by combinatorially symmetric cross-validation
    (Bailey, Borwein, Lopez de Prado, Zhu). M: days x cells matrix of daily R. Returns (PBO, logits)."""
    M = np.asarray(M, float)
    T, N = M.shape
    edges = np.linspace(0, T, S + 1).astype(int)
    blocks = [M[edges[i]:edges[i + 1]] for i in range(S)]
    s1 = np.array([b.sum(0) for b in blocks])
    s2 = np.array([(b ** 2).sum(0) for b in blocks])
    cnt = np.array([len(b) for b in blocks])

    def sharpe(ix):
        n = cnt[ix].sum()
        m = s1[ix].sum(0) / n
        sd = np.sqrt(np.maximum(s2[ix].sum(0) / n - m ** 2, 0.0) * n / (n - 1))
        return np.where(sd > 0, m / np.where(sd > 0, sd, 1.0), 0.0)

    lam = []
    for comb in itertools.combinations(range(S), S // 2):
        ins = list(comb)
        outs = [i for i in range(S) if i not in comb]
        best = int(np.argmax(sharpe(ins)))
        w = sps.rankdata(sharpe(outs))[best] / (N + 1)
        lam.append(math.log(w / (1 - w)))
    lam = np.array(lam)
    return float((lam <= 0).mean()), lam


def expected_max_sharpe(n_trials, var_sr):
    """Expected maximum of n_trials Sharpe estimates when the true Sharpe is zero (Bailey and Lopez de Prado)."""
    if n_trials < 2:
        return 0.0
    z = sps.norm.ppf
    return math.sqrt(var_sr) * ((1 - EULER) * z(1 - 1.0 / n_trials) + EULER * z(1 - 1.0 / (n_trials * math.e)))


def deflated_sharpe(x, n_trials, var_sr):
    """Probability that the true Sharpe of series x is positive after n_trials searches.
    x: periodic returns (here daily R). Sharpe is per period, not annualised."""
    x = np.asarray(x, float)
    T = len(x)
    sr = x.mean() / x.std(ddof=1)
    sr0 = expected_max_sharpe(n_trials, var_sr)
    g3, g4 = sps.skew(x), sps.kurtosis(x, fisher=False)
    denom = math.sqrt(max(1e-12, 1 - g3 * sr + (g4 - 1) / 4 * sr ** 2))
    return float(sps.norm.cdf((sr - sr0) * math.sqrt(T - 1) / denom)), float(sr), float(sr0)


def min_backtest_years(n_trials, target_annual_sharpe=1.0):
    """Years of data needed so the best of n_trials unskilled strategies does not reach target Sharpe by luck."""
    z = sps.norm.ppf
    e = (1 - EULER) * z(1 - 1.0 / n_trials) + EULER * z(1 - 1.0 / (n_trials * math.e))
    return (e / target_annual_sharpe) ** 2


def effective_trials(M):
    """Participation ratio of the correlation-matrix eigenvalues: roughly how many independent cells there are."""
    M = np.asarray(M, float)
    M = M[:, M.std(0) > 0]
    ev = np.clip(np.linalg.eigvalsh(np.corrcoef(M, rowvar=False)), 0, None)
    return float(ev.sum() ** 2 / (ev ** 2).sum()), int((np.cumsum(np.sort(ev)[::-1]) / ev.sum() < 0.9).sum() + 1)


def analyse(results, base_key, bench, windows, min_trades, reps, seed, block, cscv_blocks):
    """Everything in one place so the self-test runs the identical pipeline."""
    win, oos, frozen, benchp = walk_forward(results, base_key, bench, windows, min_trades)
    summ = summarize(win, oos, frozen, benchp)
    M = daily_matrix(results)
    summ["oos_mean_p"] = mean_pvalue(oos["R"].to_numpy(), block, reps, seed)
    summ["spa_zero"] = reality_check(M.to_numpy(), block, reps, seed)
    summ["pbo"], _ = pbo_cscv(M.to_numpy(), cscv_blocks)
    return win, summ, M


# ---------------------------------------------------------------------------
# Reporting
# ---------------------------------------------------------------------------

def check_reproduction(market, base_stats):
    ref = REFERENCE[market]
    ok = base_stats["n"] == ref["n"]
    # Tolerance is half a unit in the last digit the reference was published with (65 means 64.5 to 65.5).
    for k, tol in (("win", 0.5 if float(ref.get("win", 0)).is_integer() else 0.06), ("avgR", 0.0055),
                   ("maxDD", 0.6), ("PF", 0.006)):
        if k in ref:
            key = {"win": "win%", "maxDD": "maxDD$"}.get(k, k)
            ok &= abs(base_stats[key] - ref[k]) <= tol
    print(f"Reproduction gate ({market}): got n={base_stats['n']}, win={base_stats['win%']}, avgR={base_stats['avgR']}, "
          f"maxDD={base_stats.get('maxDD$')}, PF={base_stats.get('PF')}  vs  {ref}  ->  {'PASS' if ok else 'FAIL'}")
    return ok


def fmt(st):
    return "n/a" if not st.get("n") else (f"n={st['n']}, win {st['win%']}%, avg R {st['avgR']:+.3f}, t {st['t']}, "
                                          f"PF {st['PF']}, max DD ${st['maxDD$']}")


def report(market, mode, win, summ, M, base_key, args):
    print(f"\nProtocol {PROTOCOL_ID}  market {market}  mode {mode}  cells {M.shape[1]}  days {len(M)}")
    show = win.assign(chosen=win["chosen"].map(lambda k: f"{k[0]}m x{k[1]} ema={'Y' if k[2] else 'N'}"))
    cols = ["oos_year", "chosen", "is_trades", "is_avgR", "oos_trades", "oos_avgR", "frozen_trades", "frozen_avgR",
            "bench_trades", "bench_avgR"]
    pd.set_option("display.width", 220)
    print(show[cols].round(3).to_string(index=False))
    print("\nStitched out-of-sample, re-tuned each window :", fmt(summ["oos_stats"]))
    print("Same years, frozen base settings              :", fmt(summ["frozen_stats"]))
    print("Same years, buy-every-day benchmark           :", fmt(summ["bench_stats"]))
    print(f"Windows {summ['windows']}, share with positive OOS avg R {summ['share_positive']:.0%}, "
          f"parameter changes {summ['param_changes']}, fallbacks to frozen {summ['fallbacks']}")
    print(f"Walk-forward efficiency: per trade {summ['wfe_trade']:.2f}, per day {summ['wfe_year']:.2f}")
    print(f"Single-test bootstrap p (stitched OOS mean <= 0): {summ['oos_mean_p']:.3f}")
    s = summ["spa_zero"]
    b = M.columns[s["best_cell"]]
    print(f"Best cell over the whole sample: {int(b[0])}m x{float(b[1])} EMA {'on' if b[2] else 'off'}, "
          f"mean {s['best_mean_R_per_day']:.4f} R per day")
    print(f"Data-snooping p over {M.shape[1]} cells vs zero: White RC {s['rc']:.3f}, SPA lower {s['spa_lower']:.3f}, "
          f"consistent {s['spa_consistent']:.3f}, upper {s['spa_upper']:.3f}")
    print(f"PBO (CSCV, {PROTOCOL['cscv_blocks']} blocks): {summ['pbo']:.2f}")
    n_eff, n90 = effective_trials(M)
    base_x = M[base_key].to_numpy()
    var_sr = float(np.var([c.mean() / c.std(ddof=1) for c in M.to_numpy().T if c.std() > 0], ddof=1))
    print(f"Trials: grid {M.shape[1]}; effective independent {n_eff:.1f} (components for 90%: {n90}); "
          f"earlier settings examined about {PROTOCOL['earlier_settings_examined']}")
    for label, n in (("grid", M.shape[1]), ("effective", max(2, round(n_eff))), ("earlier ~800", 800)):
        dsr, sr, sr0 = deflated_sharpe(base_x, n, var_sr)
        print(f"  Deflated Sharpe of frozen base, N={n:>3} ({label}): DSR {dsr:.2f}  (daily SR {sr:.4f}, "
              f"expected best-of-N by luck {sr0:.4f})")
    print(f"  Minimum backtest length for annual Sharpe 1 by luck: N=50 -> {min_backtest_years(50):.1f} years, "
          f"N=800 -> {min_backtest_years(800):.1f} years, data here {len(M) / 252:.1f} years")
    for blk in (5, 20):
        r = reality_check(M.to_numpy(), blk, min(args.reps, 2000), PROTOCOL["seed"])
        print(f"  Block {blk:>2}: SPA consistent {r['spa_consistent']:.3f}, RC {r['rc']:.3f}")
    rules = PROTOCOL["pass_rules"]
    checks = {
        "stitched OOS avg R > 0": summ["oos_stats"].get("avgR", -1) > 0,
        f"share positive windows >= {rules['pos_windows']:.0%}": summ["share_positive"] >= rules["pos_windows"],
        f"walk-forward efficiency >= {rules['wfe']}": summ["wfe_trade"] >= rules["wfe"],
        f"SPA consistent p < {rules['spa_p']}": s["spa_consistent"] < rules["spa_p"],
    }
    print("\nPre-registered checks:")
    for k, v in checks.items():
        print(f"  {'PASS' if v else 'FAIL'}  {k}")
    fz, rt = summ["frozen_stats"].get("avgR", np.nan), summ["oos_stats"].get("avgR", np.nan)
    print(f"  Frozen vs re-tuned on the same years: frozen {fz:+.3f} R, re-tuned {rt:+.3f} R "
          f"-> {'keep freezing' if fz >= rt else 're-tuning did better'}")
    print("  Verdict: " + ("edge supported" if all(checks.values()) else "plausible, not proven (some checks failed)"))
    return checks


def save(market, mode, win, summ, args):
    os.makedirs(OUT, exist_ok=True)
    tag = f"{market}_{mode}" + (f"_slip{args.slip}" if args.slip is not None else "") + \
          (f"_end{args.end}" if args.end and args.end != REGISTERED_END else "")
    win.assign(chosen=win["chosen"].astype(str)).to_csv(os.path.join(OUT, f"walkforward_{tag}.csv"), index=False)
    flat = {k: v for k, v in summ.items() if not isinstance(v, dict)}
    flat.update({f"spa_{k}": v for k, v in summ["spa_zero"].items()})
    flat["protocol_id"] = PROTOCOL_ID
    with open(os.path.join(OUT, f"walkforward_{tag}.json"), "w") as f:
        json.dump(flat, f, indent=1, default=float)
    print(f"\nSaved docs/data/walkforward_{tag}.csv and .json")


def run_market(args):
    market, mode = args.market, args.mode
    days = load_days(market)
    if args.end:
        days = [d for d in days if str(d.date) <= args.end]
    base = base_params(market, args.slip)
    cells = grid_cells(base)
    base_key = (60, 0.5, True)
    assert cells[base_key] == base, "grid cell (60, 0.5, EMA on) must equal the frozen base parameters"
    results = run_cells(days, cells)
    bench = frame(E.run(days, E.replace(base, entry_mode="always")))
    ref_part = results[base_key].loc[:REFERENCE_END[market]] if REFERENCE_END[market] else results[base_key]
    if args.slip is None and not check_reproduction(market, E.stats(ref_part)):
        raise SystemExit("Reproduction gate failed. Stop and find out why before reading any other number.")
    last = max(d.date for d in days)
    windows = make_windows(PROTOCOL["start_year"][market], PROTOCOL["is_years"][mode][market], mode,
                           pd.Timestamp(last))
    print(f"Windows: " + ", ".join(f"IS {w['is_start'].year}-{w['is_end'].year} -> OOS {w['oos_year']}" for w in windows))
    win, summ, M = analyse(results, base_key, bench, windows, PROTOCOL["min_is_trades"], args.reps,
                           PROTOCOL["seed"], PROTOCOL["boot_block"], PROTOCOL["cscv_blocks"])
    report(market, mode, win, summ, M, base_key, args)
    save(market, mode, win, summ, args)


# ---------------------------------------------------------------------------
# Self-test on synthetic data (null and planted edge)
# ---------------------------------------------------------------------------

def synthetic_days(n_days, seed, momentum=0.0, start="2021-01-04"):
    """Random-walk 1-minute RTH bars. momentum > 0 adds a planted opening-range continuation edge: the afternoon
    drifts in the direction of the first hour by `momentum` times the afternoon's own volatility."""
    rng = np.random.default_rng(seed)
    dates = pd.bdate_range(start, periods=n_days)
    mins = np.arange(390)
    ret = rng.normal(0, 0.0003, (n_days, 390))
    if momentum:
        sign = np.sign(ret[:, :60].sum(1))[:, None]
        ret[:, 60:] += sign * momentum * 0.0003 * math.sqrt(330) / 330
    close = 400 * np.exp(np.cumsum(ret.ravel()))       # QQQ-like price, so 2 cents of slippage costs what it does live
    open_ = np.concatenate([[400.0], close[:-1]])
    wick = np.abs(rng.normal(0, 0.0001, close.size))
    idx = (dates.values[:, None] + (570 + mins) * np.timedelta64(1, "m")).ravel()
    df = pd.DataFrame({"open": open_, "high": np.maximum(open_, close) * (1 + wick),
                       "low": np.minimum(open_, close) * (1 - wick), "close": close, "volume": 1.0}, index=idx)
    df.index.name = "ts"
    return E.prepare(df, None)


def selftest_base():
    return E.P(or_min=60, cutoff=720, eod=950, stop_mode="midpoint", stop_k=0.0, target_mode="range", target_k=0.5,
               breakeven=0.0, f_ema=True, slip=0.02, commission=0.0, mult=1.0, account=5000, risk_pct=0.015,
               max_contracts=10 ** 6, oversize="min1", monthly_cap=0)


def selftest(reps=400, null_seeds=6, n_days=1000):
    base = selftest_base()
    cells = grid_cells(base)
    base_key = (60, 0.5, True)
    ok_all = True

    def once(seed, momentum):
        days = synthetic_days(n_days, seed, momentum)
        res = run_cells(days, cells)
        bench = frame(E.run(days, E.replace(base, entry_mode="always")))
        wins = make_windows(2021, 1, "anchored", pd.Timestamp(max(d.date for d in days)))
        win, summ, M = analyse(res, base_key, bench, wins, PROTOCOL["min_is_trades"], reps, seed, 10,
                               PROTOCOL["cscv_blocks"])
        return summ["oos_stats"].get("avgR", float("nan")), summ["spa_zero"]["spa_consistent"], summ["pbo"]

    print(f"Null test: {null_seeds} random-walk datasets of {n_days} days, no edge, same pipeline as real data")
    nulls = [once(s, 0.0) for s in range(1, null_seeds + 1)]
    for s, (a, p, b) in enumerate(nulls, 1):
        print(f"  seed {s}: stitched OOS avg R {a:+.3f}, SPA p {p:.3f}, PBO {b:.2f}")
    med_r = float(np.nanmedian([a for a, _, _ in nulls]))
    share = float(np.mean([p < 0.05 for _, p, _ in nulls]))
    mean_pbo = float(np.mean([b for _, _, b in nulls]))
    for name, ok in ((f"median OOS avg R {med_r:+.3f} <= +0.05", med_r <= 0.05),
                     (f"share of seeds with SPA p<0.05 {share:.0%} <= 33%", share <= 1 / 3)):
        print(f"  {'PASS' if ok else 'FAIL'}  {name}")
        ok_all &= ok
    # PBO is informational here: real grid cells differ systematically even on a random walk (costs and
    # stop/target geometry), so PBO need not be 0.5. PBO is checked on exchangeable noise in test_walkforward.py.
    print(f"  info  mean PBO on random walks {mean_pbo:.2f}")

    print("Planted-edge test: opening-range continuation edge (momentum 1.0, calibrated on seed 101) added")
    a, p, b = once(101, 1.0)
    ok = a > 0.10 and p < 0.05
    print(f"  stitched OOS avg R {a:+.3f}, SPA p {p:.3f}, PBO {b:.2f}  ->  {'PASS' if ok else 'FAIL'} "
          f"(expect avg R > +0.10 and SPA p < 0.05)")
    ok_all &= ok
    print("SELF-TEST " + ("PASSED" if ok_all else "FAILED"))
    return ok_all


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--market", choices=["qqq", "nq"], default="qqq")
    ap.add_argument("--mode", choices=["anchored", "rolling"], default="anchored")
    ap.add_argument("--slip", type=float, default=None)
    ap.add_argument("--reps", type=int, default=PROTOCOL["boot_reps"])
    ap.add_argument("--end", default=None,
                    help=f"last date of data to use, e.g. {REGISTERED_END} to reproduce the registered results")
    ap.add_argument("--selftest", action="store_true")
    args = ap.parse_args()
    if args.selftest:
        sys.exit(0 if selftest() else 1)
    run_market(args)


if __name__ == "__main__":
    main()
