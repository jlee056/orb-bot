"""Tests for paper_vs_backtest.py. Run: python -m unittest -v test_paper_vs_backtest

The data-driven checks read docs/data/paper_vs_backtest.csv, written by `python paper_vs_backtest.py`,
and are skipped if it does not exist.
"""
import os
import unittest

import numpy as np
import pandas as pd

import paper_vs_backtest as P

CSV = os.path.join(os.path.dirname(os.path.abspath(__file__)), "docs", "data", "paper_vs_backtest.csv")


class AgreeTests(unittest.TestCase):
    def test_no_trade_reasons_agree_with_each_other(self):
        self.assertTrue(P.agree("filtered", "no_breakout", 0, 0))
        self.assertTrue(P.agree("downside_break", "filtered_dir", 0, 0))

    def test_same_outcome_same_side(self):
        self.assertTrue(P.agree("stop", "stop", 1, 1))

    def test_same_outcome_opposite_side_is_a_disagreement(self):
        self.assertFalse(P.agree("stop", "stop", 1, -1))

    def test_different_outcome(self):
        self.assertFalse(P.agree("target", "eod", -1, -1))
        self.assertFalse(P.agree("stop", "no_breakout", 1, 0))


class StatTests(unittest.TestCase):
    def test_stat(self):
        s = P.stat([1.0, 2.0, 3.0, np.nan])
        self.assertEqual(s["n"], 3)
        self.assertAlmostEqual(s["mean"], 2.0)
        self.assertAlmostEqual(s["median"], 2.0)
        self.assertAlmostEqual(s["se"], 1 / np.sqrt(3))
        self.assertIsNone(P.stat([np.nan]))


@unittest.skipUnless(os.path.isfile(CSV), "run paper_vs_backtest.py first")
class OutputInvariants(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.df = pd.read_csv(CSV)

    def test_price_and_scale_effects_add_up_to_the_gap(self):
        m = self.df[self.df["price_R"].notna()]
        self.assertGreater(len(m), 0)
        self.assertTrue(np.allclose(m["price_R"] + m["scale_R"], m["A"] - m["S2"], atol=0.02))

    def test_engine_rerun_matches_the_bots_logged_expectation(self):
        chk = self.df["S_rerun_ok"].dropna()
        self.assertGreater(len(chk), 0)
        self.assertTrue(chk.astype(bool).all(), "the free-feed re-run no longer reproduces a logged sim_R")

    def test_bot_stop_equals_engine_stop_on_the_same_feed(self):
        m = self.df[self.df["stop_diff"].notna()]
        self.assertTrue((m["stop_diff"].abs() < 0.015).all())

    def test_sides_are_plus_or_minus_one(self):
        self.assertTrue(set(self.df["A_dir"].dropna().unique()) <= {-1, 0, 1})


if __name__ == "__main__":
    unittest.main()
