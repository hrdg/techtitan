"""Tests for the published common-axis comparison."""
from __future__ import annotations

import unittest

import pandas as pd

import replay_frozen


class ReplayTest(unittest.TestCase):
    def test_performance_endpoints(self) -> None:
        index = pd.bdate_range("2020-01-01", periods=10)
        values = pd.Series([0.01] * 10, index=index)
        result = replay_frozen.performance(values)
        self.assertEqual(result["n_days"], 10)
        self.assertGreater(result["cagr"], 0.0)
        self.assertEqual(result["mdd"], 0.0)

    def test_published_axis_and_vix_mapping(self) -> None:
        returns = pd.read_csv(
            replay_frozen.ROOT / "data/daily_returns_common_axis_20261116.csv",
            parse_dates=["date"],
        ).set_index("date")
        state = pd.read_csv(
            replay_frozen.ROOT / "data/vix_state.csv",
            parse_dates=["date"],
        ).set_index("date")
        self.assertTrue(returns.index.equals(state.index))
        self.assertLessEqual(replay_frozen.validate_mapping(state), 1e-12)
        self.assertEqual(
            str(returns.index.max().date()),
            "2026-11-16",
        )


if __name__ == "__main__":
    unittest.main()
