"""Tests for the published frozen replay and guard reconstruction."""
from __future__ import annotations

import unittest

import pandas as pd

import generate_guard_panel
import replay_frozen


class ReplayTest(unittest.TestCase):
    def test_selector_cost_is_charged_once_on_switch_day(self) -> None:
        dates = pd.DatetimeIndex(
            [
                "2020-09-01",
                "2020-09-30",
                "2020-10-09",
                "2020-10-30",
            ]
        )
        branches = pd.DataFrame(
            {
                "W_BASE": [0.01, 0.01, 0.01, 0.01],
                "V2_BASE": [0.02, 0.02, 0.02, 0.02],
            },
            index=dates,
        )
        selections = pd.DataFrame(
            {
                "selected": ["W", "V2"],
                "changed": [False, True],
            },
            index=pd.PeriodIndex(["2020-09", "2020-10"], freq="M"),
        )
        result = replay_frozen.replay_selector(branches, selections, "BASE")
        self.assertAlmostEqual(result.iloc[0], 0.01, places=15)
        self.assertAlmostEqual(result.iloc[2], 0.02 - 0.001, places=15)
        self.assertAlmostEqual(result.iloc[3], 0.02, places=15)

    def test_published_selector_replays(self) -> None:
        result, metrics_frame = replay_frozen.replay_cost_case(5)
        published = pd.read_csv(
            replay_frozen.ROOT / "outputs" / "daily_returns_5bp.csv",
            parse_dates=["date"],
        ).set_index("date")
        columns = published.columns.intersection(result.columns)
        self.assertLess(
            float((result[columns] - published[columns]).abs().max().max()),
            1e-12,
        )
        self.assertEqual(set(metrics_frame["sample"]), {
            "full",
            "2019_2023",
            "2024_2026",
            "2026",
        })

    def test_guard_panel_replays(self) -> None:
        panel = generate_guard_panel.build_guard_panel(
            pd.read_csv(replay_frozen.ROOT / "data" / "holdings_nofb_v20261116.csv"),
            pd.read_csv(replay_frozen.ROOT / "data" / "industry_vix_beta.csv"),
            pd.read_csv(replay_frozen.ROOT / "data" / "industry_beta_state.csv"),
        )
        published = pd.read_csv(
            replay_frozen.ROOT / "outputs" / "guard_diagnostics.csv"
        )
        self.assertTrue(panel["selected"].equals(published["selected"]))
        self.assertLess(
            float(
                (
                    panel[["state_rank", "selected_beta_rank", "guard"]]
                    - published[["state_rank", "selected_beta_rank", "guard"]]
                )
                .abs()
                .max()
                .max()
            ),
            1e-12,
        )


if __name__ == "__main__":
    unittest.main()
