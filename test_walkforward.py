"""Unit tests for walkforward.py. Run: python -m unittest -v test_walkforward

Fast checks of the statistics and of the no-lookahead structure. The slower synthetic-data checks
(null data and planted edge through the whole pipeline) are `python walkforward.py --selftest`.
"""
import math
import unittest

import numpy as np
import pandas as pd
from scipy import stats as sps

import walkforward as W


def noise_matrix(T=1500, N=50, seed=0, sd=0.4):
    return np.random.default_rng(seed).normal(0, sd, (T, N))


def fake_cell(rng, dates, mean):
    """A results frame shaped like walkforward.frame(): about 25% of days trade, R ~ mean + noise."""
    trade = rng.random(len(dates)) < 0.25
    R = np.where(trade, rng.normal(mean, 0.8, len(dates)), 0.0)
    return pd.DataFrame({"dir": trade.astype(int), "R": R}, index=dates)


class StatsTests(unittest.TestCase):
    def test_min_backtest_length_matches_bailey(self):
        # Bailey et al.: with 5 years of data no more than about 45 independent trials.
        self.assertAlmostEqual(W.min_backtest_years(45), 5.0, delta=0.2)
        self.assertGreater(W.min_backtest_years(800), W.min_backtest_years(50))

    def test_expected_max_sharpe(self):
        self.assertEqual(W.expected_max_sharpe(1, 0.01), 0.0)
        self.assertGreater(W.expected_max_sharpe(100, 0.01), W.expected_max_sharpe(10, 0.01))
        self.assertAlmostEqual(W.expected_max_sharpe(10, 0.04), 2 * W.expected_max_sharpe(10, 0.01), places=9)

    def test_deflated_sharpe_single_trial_is_psr(self):
        x = np.random.default_rng(3).normal(0.05, 1.0, 2000)
        dsr, sr, sr0 = W.deflated_sharpe(x, 1, 0.01)
        self.assertEqual(sr0, 0.0)
        g3, g4 = sps.skew(x), sps.kurtosis(x, fisher=False)
        expect = sps.norm.cdf(sr * math.sqrt(len(x) - 1) / math.sqrt(1 - g3 * sr + (g4 - 1) / 4 * sr ** 2))
        self.assertAlmostEqual(dsr, expect, places=9)

    def test_deflated_sharpe_falls_with_more_trials(self):
        x = np.random.default_rng(4).normal(0.04, 1.0, 1500)
        values = [W.deflated_sharpe(x, n, 0.0004)[0] for n in (1, 10, 100, 1000)]
        self.assertTrue(all(a > b for a, b in zip(values, values[1:])), values)

    def test_stationary_bootstrap_block_length(self):
        rng = np.random.default_rng(5)
        T, mean_block = 4000, 10
        idx = W.sb_indices(rng, T, 40, mean_block)
        self.assertTrue(idx.min() >= 0 and idx.max() < T)
        continues = (idx[:, 1:] == (idx[:, :-1] + 1) % T)
        # a new block starts with probability 1/mean_block (a random jump can also land on the next index)
        self.assertAlmostEqual(1 - continues.mean(), 1 / mean_block, delta=0.01)

    def test_cscv_hand_case_no_overfit(self):
        # column 0 beats column 1 in every block, so the in-sample winner is always the out-of-sample winner
        rng = np.random.default_rng(6)
        M = np.column_stack([rng.normal(0.5, 0.1, 400), rng.normal(-0.5, 0.1, 400)])
        pbo, lam = W.pbo_cscv(M, S=4)
        self.assertEqual(len(lam), 6)                  # C(4,2) combinations
        self.assertEqual(pbo, 0.0)
        self.assertAlmostEqual(lam[0], math.log((2 / 3) / (1 / 3)), places=9)   # rank 2 of 2 -> w = 2/3

    def test_cscv_noise_is_about_half(self):
        pbos = [W.pbo_cscv(noise_matrix(1200, 40, seed=s), S=16)[0] for s in range(4)]
        self.assertAlmostEqual(float(np.mean(pbos)), 0.5, delta=0.15, msg=str(pbos))

    def test_cscv_planted_edge_is_low(self):
        M = noise_matrix(1200, 40, seed=11)
        M[:, 7] += 0.12                                # one cell with a real, persistent edge
        self.assertLess(W.pbo_cscv(M, S=16)[0], 0.1)

    def test_reality_check_noise_is_rarely_significant(self):
        hits = [W.reality_check(noise_matrix(800, 30, seed=s), 10, 300, seed=s)["spa_consistent"] < 0.05
                for s in range(12)]
        self.assertLessEqual(sum(hits), 3, hits)       # nominal 5% of 12 is 0.6

    def test_reality_check_finds_planted_edge(self):
        M = noise_matrix(1500, 30, seed=21)
        M[:, 3] += 0.08
        r = W.reality_check(M, 10, 500, seed=1)
        self.assertEqual(r["best_cell"], 3)
        self.assertLess(r["spa_consistent"], 0.05)
        self.assertLess(r["rc"], 0.05)

    def test_reality_check_pvalue_ordering(self):
        r = W.reality_check(noise_matrix(800, 30, seed=33), 10, 500, seed=2)
        self.assertLessEqual(r["spa_lower"], r["spa_consistent"] + 1e-12)
        self.assertLessEqual(r["spa_consistent"], r["spa_upper"] + 1e-12)

    def test_mean_pvalue(self):
        rng = np.random.default_rng(8)
        self.assertLess(W.mean_pvalue(rng.normal(0.15, 1, 1500), 10, 500, 1), 0.05)
        self.assertGreater(W.mean_pvalue(rng.normal(0.0, 1, 1500), 10, 500, 1), 0.05)

    def test_effective_trials(self):
        n_eff, _ = W.effective_trials(noise_matrix(1500, 20, seed=2))
        self.assertGreater(n_eff, 15)                  # independent columns count as nearly independent
        common = np.random.default_rng(1).normal(0, 1, (1500, 1))
        n_eff2, _ = W.effective_trials(common + 0.05 * noise_matrix(1500, 20, seed=3))
        self.assertLess(n_eff2, 3)                     # near-identical columns count as about one


class StructureTests(unittest.TestCase):
    def test_windows_qqq_anchored(self):
        w = W.make_windows(2020, 2, "anchored", pd.Timestamp("2026-10-09"))
        self.assertEqual([x["oos_year"] for x in w], [2022, 2023, 2024, 2025, 2026])
        self.assertTrue(all(x["is_start"] == pd.Timestamp(2020, 1, 1) for x in w))
        self.assertTrue(all(x["is_end"] < x["oos_start"] for x in w))
        self.assertEqual(w[-1]["oos_end"], pd.Timestamp("2026-10-09"))
        self.assertEqual(w[0]["is_end"], pd.Timestamp(2021, 12, 31))

    def test_windows_qqq_rolling(self):
        w = W.make_windows(2020, 3, "rolling", pd.Timestamp("2026-10-09"))
        self.assertEqual([x["oos_year"] for x in w], [2023, 2024, 2025, 2026])
        self.assertTrue(all(x["is_start"] == pd.Timestamp(x["oos_year"] - 3, 1, 1) for x in w))
        # out-of-sample windows never overlap
        self.assertTrue(all(a["oos_end"] < b["oos_start"] for a, b in zip(w, w[1:])))

    def test_grid_has_50_cells_and_contains_frozen_base(self):
        base = W.selftest_base()
        cells = W.grid_cells(base)
        self.assertEqual(len(cells), 50)
        self.assertEqual(cells[(60, 0.5, True)], base)

    def test_selection_ignores_out_of_sample_rows(self):
        dates = pd.bdate_range("2020-01-01", "2024-12-31")
        rng = np.random.default_rng(9)
        results = {(60, 0.5, True): fake_cell(rng, dates, 0.05), (75, 1.0, True): fake_cell(rng, dates, 0.30),
                   (30, 0.25, True): fake_cell(rng, dates, -0.2)}
        a, b = pd.Timestamp("2020-01-01"), pd.Timestamp("2021-12-31")
        before = W.select(results, a, b, 30, (60, 0.5, True))
        # make every out-of-sample row of the cell that was NOT chosen spectacular: choice must not move
        other = (30, 0.25, True)
        results[other].loc["2022-01-01":, "R"] = 50.0
        results[other].loc["2022-01-01":, "dir"] = 1
        self.assertEqual(W.select(results, a, b, 30, (60, 0.5, True)), before)

    def test_selection_respects_min_trades_and_falls_back(self):
        dates = pd.bdate_range("2020-01-01", "2021-12-31")
        thin = pd.DataFrame({"dir": 0, "R": 0.0}, index=dates)
        thin.iloc[:10, thin.columns.get_loc("dir")] = 1
        thin.iloc[:10, thin.columns.get_loc("R")] = 5.0         # great average, but only 10 trades
        key, avg, n, fallback = W.select({(1, 1.0, True): thin}, dates[0], dates[-1], 30, (60, 0.5, True))
        self.assertEqual(key, (60, 0.5, True))
        self.assertTrue(fallback)

    def test_walk_forward_end_to_end_on_planted_cell(self):
        dates = pd.bdate_range("2020-01-01", "2024-12-31")
        rng = np.random.default_rng(10)
        results = {(60, 0.5, True): fake_cell(rng, dates, 0.0), (75, 1.0, True): fake_cell(rng, dates, 0.5)}
        bench = fake_cell(rng, dates, 0.0)
        windows = W.make_windows(2020, 2, "anchored", dates[-1])
        win, oos, frozen, benchp = W.walk_forward(results, (60, 0.5, True), bench, windows, 30)
        self.assertTrue((win["chosen"] == [(75, 1.0, True)] * len(win)).all())
        self.assertEqual(win["oos_year"].tolist(), [2022, 2023, 2024])
        self.assertGreater(oos["R"].sum(), frozen["R"].sum())
        self.assertEqual(oos.index.min(), pd.Timestamp("2022-01-03"))   # nothing from the in-sample years leaks in


if __name__ == "__main__":
    unittest.main()
