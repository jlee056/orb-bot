"""The strategy variants that run side by side, each in its own Alpaca paper account.

  base    the settings frozen on 2026-10-12: 60-minute range, long only, EMA trend filter
  orb5    first 5-minute candle's direction, long or short, at the 9:35 open; stop at the
          candle's far side, target 10 R or the close (Zarattini & Aziz 2023)
  both60  base plus short trades on downside breaks; the trend filter works per direction

Each variant is the base settings with a few fields changed, so everything not listed
stays exactly as tested. Rules are frozen from 2026-10-14; see docs/LOGBOOK.md.

Check: python variants.py --check   (fails if base's settings hash has drifted)
"""
import os
import sys
from dataclasses import dataclass, field

HERE = os.path.dirname(os.path.abspath(__file__))


@dataclass(frozen=True)
class Variant:
    name: str
    order_prefix: str      # Alpaca client_order_id is "{prefix}-{date}"
    tag: str               # inserted into phone-notification titles; base has none
    paper_log: str         # relative to the repo
    fwd_log: str
    changes: dict = field(default_factory=dict)   # fields of orb_engine.P that differ from base

    def path(self, which):
        return os.path.join(HERE, getattr(self, which))


BASE = Variant("base", "orb", "", "paper/alpaca_trades.csv", "forward/forward_log.csv")
ORB5 = Variant("orb5", "orb5", "[orb5]", "paper/alpaca_trades_orb5.csv", "forward/forward_log_orb5.csv",
               dict(entry_mode="candle", or_min=5, shorts=True, stop_mode="orb_low", stop_k=0.0,
                    target_mode="r", target_k=10.0, breakeven=0.0, f_ema=False))
BOTH60 = Variant("both60", "both60", "[both60]", "paper/alpaca_trades_both60.csv",
                 "forward/forward_log_both60.csv", dict(shorts=True, f_ema_dir=True))

ALL = {v.name: v for v in (BASE, ORB5, BOTH60)}

# What the QQQ backtest (2020-01 to 2026-10-09, 2 cents slippage, $75 risk) expects of each variant.
# `python backtest.py --qqq --variant NAME`. Used by variants_report.py and the stop rule below.
BACKTEST = {
    "base": dict(trades=432, per_year=64, win=62.7, avg_r=0.084, max_dd_usd=684),
    "orb5": dict(trades=1624, per_year=242, win=24.8, avg_r=0.081, max_dd_usd=3411),
    "both60": dict(trades=633, per_year=94, win=61.5, avg_r=0.053, max_dd_usd=556),
}

# Pre-registered on 2026-10-14 (docs/LOGBOOK.md). Not changed after the fact.
CHECKPOINTS = (50, 100, 312)     # trades at which a variant is reviewed; 312 is enough to tell +0.1 R from zero
STOP_AVG_R = -0.15               # after 100 trades, an average at or below this stops the variant
STOP_DD_MULT = 1.5               # or a drawdown beyond 1.5 times the backtest's largest

# Settings hashes of the frozen base rules. These must never change.
BASE_IDS = {"qqq": "e0a01dbd", "nq": "00c5314f"}


def get(name):
    if name not in ALL:
        raise SystemExit(f"Unknown variant {name!r}; choose from {', '.join(ALL)}")
    return ALL[name]


def check():
    import orb_engine as E
    from alpaca_bot import qqq_params
    from forward_run import config_id, strategy_params
    got = {"qqq": config_id(qqq_params(BASE)), "nq": config_id(E.replace(strategy_params(), **BASE.changes))}
    ok = got == BASE_IDS
    for v in ALL.values():
        print(f"{v.name:7s} QQQ {config_id(qqq_params(v))}  NQ {config_id(E.replace(strategy_params(), **v.changes))}")
    print("base settings unchanged" if ok else f"BASE SETTINGS DRIFTED: {got} != {BASE_IDS}")
    return 0 if ok else 1


if __name__ == "__main__":
    if "--check" in sys.argv:
        sys.exit(check())
    print(__doc__)
