"""组合构建、择时叠加与指标口径测试。"""
from __future__ import annotations

import sys
from pathlib import Path

import numpy as np
import pandas as pd
import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from tech_rotation import PortfolioSpec, build_daily_weights, metrics, run_timing_overlay  # noqa: E402


def _factors(dates, dc_map, rv_map):
    cols = [f"I{i}" for i in range(10)]
    dc = pd.DataFrame(np.nan, index=dates, columns=cols)
    rv = pd.DataFrame(np.nan, index=dates, columns=cols)
    for t, order in dc_map.items():
        for rank, c in enumerate(order):
            dc.loc[t, c] = 10.0 - rank
    for t, order in rv_map.items():
        for rank, c in enumerate(order):
            rv.loc[t, c] = 10.0 - rank
    return dc, rv


def test_empty_intersection_holds_previous_holdings():
    days = pd.bdate_range("2021-01-01", "2021-04-30")
    cols = [f"I{i}" for i in range(10)]
    dc = pd.DataFrame(np.nan, index=days, columns=cols)
    rv = pd.DataFrame(np.nan, index=days, columns=cols)
    dc.loc[days[-1], "I0"] = 1.0
    rv.loc[days[-1], "I0"] = 1.0
    # 2 月末交集 = {I0}
    dc.loc[pd.Timestamp("2021-02-26"), ["I0", "I1", "I2", "I3"]] = [9, 8, 7, 6]
    rv.loc[pd.Timestamp("2021-02-26"), ["I0", "I5"]] = [9, 8]
    # 3 月末交集为空：RV 只选 I5/I6，不在 ΔC 前 4
    dc.loc[pd.Timestamp("2021-03-31"), ["I1", "I2", "I3", "I4"]] = [9, 8, 7, 6]
    rv.loc[pd.Timestamp("2021-03-31"), ["I5", "I6"]] = [9, 8]

    w = build_daily_weights(dc, rv, days, PortfolioSpec(k1=2, k2=4, name="combined"),
                            "2021-01-01", "2021-04-30")
    apr = w.loc["2021-04-01"]
    assert apr["I0"] == pytest.approx(1.0)
    assert apr.sum() == pytest.approx(1.0)


def test_intersection_equal_weight_and_month_start_application():
    days = pd.bdate_range("2021-01-01", "2021-03-31")
    cols = [f"I{i}" for i in range(10)]
    dc = pd.DataFrame(np.nan, index=days, columns=cols)
    rv = pd.DataFrame(np.nan, index=days, columns=cols)
    t = pd.Timestamp("2021-02-26")
    dc.loc[t, ["I0", "I1", "I2", "I3"]] = [9, 8, 7, 6]
    rv.loc[t, ["I0", "I1"]] = [9, 8]
    w = build_daily_weights(dc, rv, days, PortfolioSpec(k1=2, k2=4, name="combined"),
                            "2021-01-01", "2021-03-31")
    mar1 = w.loc["2021-03-01"]
    assert mar1["I0"] == pytest.approx(0.5) and mar1["I1"] == pytest.approx(0.5)
    assert mar1.sum() == pytest.approx(1.0)
    # 3 月 1 日之前不持仓（信号日 2/26 之后才生效）
    assert w.loc["2021-02-26"].sum() == 0.0


def test_timing_overlay_next_day_switch_and_hold():
    dates = pd.bdate_range("2021-01-04", periods=6)
    risky = pd.Series(0.01, index=dates)
    bond = pd.Series(0.001, index=dates)
    # d1: ΔAR=2.0 > 1.5 预警；d4: ΔAR=-1.0 < 0 入场；其余为 NaN（维持原仓位）
    dar = pd.Series([np.nan, 2.0, np.nan, np.nan, -1.0, np.nan], index=dates)
    ret, state = run_timing_overlay(dar, risky, bond, threshold=1.5)
    assert list(state) == [1.0, 1.0, 0.0, 0.0, 0.0, 1.0]   # 初始底仓为组合，信号次日生效
    assert list(ret) == pytest.approx([0.01, 0.01, 0.001, 0.001, 0.001, 0.01])


def test_timing_overlay_zero_to_threshold_keeps_position():
    dates = pd.bdate_range("2021-01-04", periods=4)
    risky = pd.Series(0.01, index=dates)
    bond = pd.Series(0.001, index=dates)
    # d0 预警 → d1 起国债；d1/d2 的 ΔAR 落在 [0, threshold] → 继续持有国债
    dar = pd.Series([2.0, 0.5, 1.0, np.nan], index=dates)
    ret, state = run_timing_overlay(dar, risky, bond, threshold=1.5)
    assert list(state) == [1.0, 0.0, 0.0, 0.0]
    assert list(ret) == pytest.approx([0.01, 0.001, 0.001, 0.001])


def test_metrics_formulas():
    dates = pd.bdate_range("2020-01-01", periods=250)
    r = pd.Series([0.001] * 250, index=dates)
    m = metrics(r)
    assert m["cum_return"] == pytest.approx(1.001**250 - 1, rel=1e-12)
    assert m["annual_return"] == pytest.approx(1.001**250 - 1, rel=1e-12)  # n=250
    assert m["max_drawdown"] == pytest.approx(0.0)

    r2 = pd.Series([0.10, -0.20, 0.05, 0.02], index=pd.bdate_range("2020-01-01", periods=4))
    m2 = metrics(r2)
    nav = (1 + r2).cumprod()
    assert m2["max_drawdown"] == pytest.approx(float((nav / nav.cummax() - 1).min()))
    assert m2["calmar"] == pytest.approx(m2["annual_return"] / abs(m2["max_drawdown"]))
    assert m2["sharpe"] == pytest.approx(m2["annual_return"] / m2["annual_vol"])
