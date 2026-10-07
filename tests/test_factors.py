"""公式级测试：用手工可验算的构造数据核对 C、ΔC、AR、RV 与择时信号。"""
from __future__ import annotations

import sys
from pathlib import Path

import numpy as np
import pandas as pd
import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from tech_rotation import (  # noqa: E402
    absorption_and_concentration,
    delta_zscore,
    relative_valuation,
)


def test_relative_valuation_leave_one_out_matches_hand_calc():
    n = 300
    idx = pd.bdate_range("2020-01-01", periods=n)
    pb = pd.DataFrame({"A": 10.0, "B": 10.0, "C": 10.0}, index=idx)
    # C 最后 20 天翻倍
    pb.loc[idx[-20:], "C"] = 20.0

    rv = relative_valuation(pb, window=250, min_periods=250, leave_one_out=True)
    # rolling(250) 在最后一天覆盖最后 250 行：230 行为 10.0，20 行为 20.0
    mean_c = (230 * 10.0 + 20 * 20.0) / 250
    spb_c = 20.0 / mean_c
    expected_c = spb_c / 1.0                      # 其余行业 SPB 均为 1
    expected_a = 1.0 / ((spb_c + 1.0) / 2)        # 其余为 C 与 B

    assert rv["C"].iloc[-1] == pytest.approx(expected_c, rel=1e-9)
    assert rv["A"].iloc[-1] == pytest.approx(expected_a, rel=1e-9)
    assert rv["A"].iloc[-1] == rv["B"].iloc[-1]
    assert rv.iloc[-1]["C"] > rv.iloc[-1]["A"]


def test_relative_valuation_all_industry_variant():
    idx = pd.bdate_range("2020-01-01", periods=300)
    pb = pd.DataFrame({"A": 10.0, "B": 10.0, "C": 10.0}, index=idx)
    pb.loc[idx[-20:], "C"] = 20.0
    rv = relative_valuation(pb, window=250, min_periods=250, leave_one_out=False)
    mean_c = (230 * 10.0 + 20 * 20.0) / 250
    spb = {"A": 1.0, "B": 1.0, "C": 20.0 / mean_c}
    cross = np.mean(list(spb.values()))
    assert rv["C"].iloc[-1] == pytest.approx(spb["C"] / cross, rel=1e-9)
    assert rv["A"].iloc[-1] == pytest.approx(1.0 / cross, rel=1e-9)


def test_delta_zscore_formula():
    idx = pd.bdate_range("2020-01-01", periods=200)
    s = pd.Series(np.linspace(0.0, 1.0, 200) + np.sin(np.arange(200) / 5), index=idx)
    out = delta_zscore(s, short=15, long=125)
    t = idx[-1]
    manual = (s.tail(15).mean() - s.tail(125).mean()) / s.tail(125).std(ddof=1)
    assert out.loc[t] == pytest.approx(manual, rel=1e-12)
    assert out.iloc[:124].isna().all()


def test_absorption_uniform_loadings_gives_equal_concentration():
    """单一共同因子、等暴露：AR(m=1) 接近 1，各行业 C 相等且和为 1。"""
    rng = np.random.default_rng(7)
    dates = pd.bdate_range("2020-01-01", periods=300)
    assets = [f"I{i}" for i in range(10)]
    common = rng.normal(0, 0.01, size=300)
    data = {a: common + rng.normal(0, 0.0005, size=300) for a in assets}
    ret = pd.DataFrame(data, index=dates)
    mv = pd.DataFrame(100.0, index=dates, columns=assets)
    ar, c = absorption_and_concentration(ret, mv, window=125, m=1)
    assert ar.dropna().iloc[0] > 0.99
    last = c.dropna().iloc[-1]
    assert last.sum() == pytest.approx(1.0, rel=1e-9)
    assert last.max() - last.min() < 0.02


def test_concentration_ranks_dominant_industry_first():
    """某一行业在共同因子上暴露远大于其他行业时，其 C 最大。"""
    rng = np.random.default_rng(11)
    dates = pd.bdate_range("2020-01-01", periods=300)
    assets = [f"I{i}" for i in range(10)]
    common = rng.normal(0, 0.01, size=300)
    data = {}
    for i, a in enumerate(assets):
        beta = 5.0 if a == "I0" else 1.0
        data[a] = beta * common + rng.normal(0, 0.0005, size=300)
    ret = pd.DataFrame(data, index=dates)
    mv = pd.DataFrame(100.0, index=dates, columns=assets)
    _, c = absorption_and_concentration(ret, mv, window=125, m=2)
    last = c.dropna().iloc[-1]
    assert last.idxmax() == "I0"
    assert last.sum() == pytest.approx(1.0, rel=1e-9)


def test_concentration_uses_previous_day_market_cap():
    """市值权重取前一交易日：把第 t 日市值放大不应影响第 t 日的 C。"""
    rng = np.random.default_rng(3)
    dates = pd.bdate_range("2020-01-01", periods=200)
    assets = [f"I{i}" for i in range(10)]
    ret = pd.DataFrame(rng.normal(0, 0.01, size=(200, 10)), index=dates, columns=assets)
    mv = pd.DataFrame(100.0, index=dates, columns=assets)
    _, c1 = absorption_and_concentration(ret, mv, window=125, m=2)
    mv2 = mv.copy()
    mv2.iloc[-1] *= 1e6  # 只改最后一天（作为 t 的前一日用于 t+1，但 t 日窗口不含 t+1）
    _, c2 = absorption_and_concentration(ret, mv2, window=125, m=2)
    pd.testing.assert_frame_equal(c1, c2)
