"""Backtest the bot exactly as config.py has it set, on ~800 days of 1-minute data.

No broker and no deposit needed. Engine and data loading live in orb_engine.py.

Run:  python backtest.py            (live rules: filters and loss cap enforced)
      python backtest.py --paper    (paper log-only rules: every breakout traded)
      python backtest.py --refresh  (re-download the latest 60 days from yfinance)
"""
import sys

import pandas as pd

import config
import orb_engine as E


def params_from_config(paper=False):
    stop_k = config.ATR_STOP_MULT if config.STOP_MODE == "atr" else 0
    return E.P(
        or_min=config.OPENING_RANGE_MIN,
        cutoff=config.ENTRY_CUTOFF_HOUR * 60,
        eod=config.EOD_CLOSE_HOUR * 60 + config.EOD_CLOSE_MINUTE,
        stop_mode=config.STOP_MODE, stop_k=stop_k,
        target_mode="range", target_k=config.TARGET_RATIO,
        breakeven=config.BREAKEVEN_TRIGGER_RATIO,
        f_friday=config.FILTER_FRIDAY and not paper,
        f_vix=not paper, f_ema=not paper,
        f_gap=config.FILTER_GAP and not paper,
        f_range=config.FILTER_RANGE and not paper,
        vix_min=config.VIX_MIN, vix_max=config.VIX_MAX,
        ema_days=config.EMA_DAYS_ABOVE_REQUIRED,
        gap_max=config.GAP_SKIP_PCT, range_max=config.MAX_RANGE_PCT,
        account=config.ACCOUNT_SIZE, risk_pct=config.RISK_PERCENT,
        max_contracts=config.MAX_CONTRACTS,
        oversize="min1" if paper else "skip", oversize_tol=config.MAX_RISK_OVERSHOOT,
        monthly_cap=0 if paper else config.MONTHLY_LOSS_CAP,
    )


def qqq():
    """The frozen settings on QQQ shares (what the Alpaca paper bot trades). No retuning."""
    import glob
    import os

    import alpaca_io as A
    from alpaca_bot import RISK_USD, qqq_params
    p = E.replace(qqq_params(), account=RISK_USD / 0.015, risk_pct=0.015, max_contracts=10 ** 6)
    files = sorted(glob.glob(os.path.join(E.DATA, "alpaca", "QQQ_1min_*.csv")))
    vix = E.load_vix()
    if files:
        df = pd.concat(pd.read_csv(f, index_col=0, parse_dates=True) for f in files).sort_index()
        days = E.prepare(df, vix)
        groups = {str(y): [d for d in days if d.date.year == y] for y in sorted({d.date.year for d in days})}
        src = f"Alpaca 1-minute bars, {days[0].date} to {days[-1].date}"
    else:
        days = E.prepare(A.YahooData().bars(5, "2000-01-01"), vix)
        groups = {"last 60 days": days}
        src = "yfinance 5-minute bars, last 60 days only (run get_data.py --qqq for the full history)"
    cols = ["days", "n", "win%", "avgR", "t", "PF", "usd", "maxDD$", "worst$", "avgRisk$"]
    pd.set_option("display.width", 200)
    print(f"QQQ, frozen settings: range {p.or_min} min, stop {p.stop_mode}, target {p.target_k} x range")
    print(f"Data: {src}")
    print(f"Sized to risk ${RISK_USD:.0f} per trade. Costs: 2 cents slippage per market fill, no commission.\n")
    table = {k: E.stats(E.run(v, p)) for k, v in groups.items() if v}
    if len(groups) > 1:
        table["ALL"] = E.stats(E.run(days, p))
    print(pd.DataFrame(table).T.reindex(columns=cols).to_string())
    print("\nFor comparison, NQ futures on the same settings: 216 trades, 65% wins, +0.13 avg R, PF 1.48.")


def main():
    if "--qqq" in sys.argv:
        return qqq()
    paper = "--paper" in sys.argv
    if "--refresh" in sys.argv:
        E.load_yf(refresh=True)
    ds = E.datasets()
    p = params_from_config(paper)
    one = E.replace(p, oversize="min1", monthly_cap=0)   # 1 contract every signal, no account limits

    pd.set_option("display.width", 200)
    cols = ["days", "n", "win%", "avgR", "t", "PF", "usd", "maxDD$", "worst$", "avgRisk$"]
    all_days = [d for v in ds.values() for d in v]
    print(f"Mode: {'PAPER (no filters)' if paper else 'LIVE rules'}   "
          f"Range {p.or_min} min, stop {p.stop_mode}, target {p.target_k} x range")
    print("Costs included: 0.5 pt slippage per market fill, $1.24 commission per contract round trip.\n")

    print("Strategy, 1 MNQ contract per signal (no account limits):")
    table = {k: E.stats(E.run(v, one)) for k, v in ds.items()}
    table["ALL"] = E.stats(E.run(all_days, one))
    print(pd.DataFrame(table).T.reindex(columns=cols).to_string())

    budget = p.account * p.risk_pct
    print(f"\nWith account ${p.account:,.0f}, risk budget ${budget:.0f}/trade, "
          f"monthly cap ${p.monthly_cap:.0f}, over-budget trades {'traded' if paper else 'skipped'}:")
    res = E.run(all_days, p)
    print(pd.DataFrame({"ALL": E.stats(res)}).T.reindex(columns=cols).to_string())
    print("\nOutcome counts:", res["why"].value_counts().to_dict())

    res.to_csv("backtest_results.csv", index=False)
    print("Per-day detail saved to backtest_results.csv")
    print("Not modelled: events.py skip days, losing-streak size cut, September half size.")


if __name__ == "__main__":
    main()
