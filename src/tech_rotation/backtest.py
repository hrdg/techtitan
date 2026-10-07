"""组合构建、择时叠加与绩效指标。

对应研报：
- 2.3 节：月度调仓（每月第一个交易日），高估值 / 高集中度 / 高集中度高估值三组合
- 3.3 节：ΔAR 择时（下一交易日切换 100% 国债指数）
- 表 4-表 7：评价指标口径（见 strategy.json DEC-004）
"""
from __future__ import annotations

from dataclasses import dataclass

import numpy as np
import pandas as pd


@dataclass(frozen=True)
class PortfolioSpec:
    """组合参数。"""

    k1: int = 2       # 相对估值排名前 k1
    k2: int = 4       # 集中度排名前 k2
    name: str = "combined"  # combined | value | concentration


def month_end_signal_dates(index: pd.DatetimeIndex) -> pd.DatetimeIndex:
    """每个自然月最后一个交易日。"""
    s = pd.Series(index, index=index)
    return pd.DatetimeIndex(s.groupby([index.year, index.month]).last().values)


def month_first_trading_days(index: pd.DatetimeIndex) -> pd.DatetimeIndex:
    """每个自然月第一个交易日。"""
    s = pd.Series(index, index=index)
    return pd.DatetimeIndex(s.groupby([index.year, index.month]).first().values)


def _period_key(index: pd.DatetimeIndex, freq: str):
    if freq == "M":
        return [index.year, index.month]
    if freq == "W":
        iso = index.isocalendar()
        return [iso["year"].to_numpy(), iso["week"].to_numpy()]
    raise ValueError("freq must be 'M' or 'W'")


def period_end_signal_dates(index: pd.DatetimeIndex, freq: str = "M") -> pd.DatetimeIndex:
    """每个调仓周期最后一个交易日（周频 = 每周最后一个交易日）。"""
    s = pd.Series(index, index=index)
    return pd.DatetimeIndex(s.groupby(_period_key(index, freq)).last().values)


def period_first_trading_days(index: pd.DatetimeIndex, freq: str = "M") -> pd.DatetimeIndex:
    """每个调仓周期第一个交易日。"""
    s = pd.Series(index, index=index)
    return pd.DatetimeIndex(s.groupby(_period_key(index, freq)).first().values)


def build_daily_weights(
    delta_c: pd.DataFrame,
    rel_val: pd.DataFrame,
    trading_days: pd.DatetimeIndex,
    spec: PortfolioSpec,
    start: str,
    end: str,
    freq: str = "M",
    exclude: pd.DataFrame | None = None,
) -> pd.DataFrame:
    """按上月末因子在每月首个交易日调仓，返回每日行业权重（等权）。

    交集为空时沿用上一期持仓（研报 2.3 节）。
    """
    days = trading_days[(trading_days >= start) & (trading_days <= end)]
    rebal = period_first_trading_days(days, freq)
    signal_dates = period_end_signal_dates(delta_c.index, freq)
    assets = list(delta_c.columns)
    weights = pd.DataFrame(0.0, index=days, columns=assets)

    current: list[str] = []
    for d in rebal:
        prior = signal_dates[signal_dates < d]
        if len(prior) == 0:
            continue
        t = prior[-1]
        dc = delta_c.loc[t].dropna()
        rv = rel_val.loc[t].dropna()
        if exclude is not None:
            bad = exclude.loc[t].fillna(False)
            restricted = [c for c in dc.index if c in rv.index and not bad.get(c, False)]
            dc = dc[dc.index.isin(restricted)]
            rv = rv[rv.index.isin(restricted)]
        if dc.empty or rv.empty:
            top_conc = set()
            top_val = set()
        else:
            top_conc = set(dc.nlargest(spec.k2).index)
            top_val = set(rv.nlargest(spec.k1).index)

        if spec.name == "value":
            selected = sorted(top_val)
        elif spec.name == "concentration":
            selected = sorted(top_conc)
        else:
            selected = sorted(top_conc & top_val)

        if not selected and spec.name == "combined":
            continue  # 保持上一期持仓
        current = selected
        weights.loc[d:] = 0.0
        if current:
            weights.loc[d:, current] = 1.0 / len(current)
    return weights


def portfolio_returns(weights: pd.DataFrame, returns: pd.DataFrame) -> pd.Series:
    """组合日收益（权重当日起生效，权重来自上一交易日收盘信号）。"""
    aligned = returns.reindex(index=weights.index, columns=weights.columns).fillna(0.0)
    return (weights * aligned).sum(axis=1)


def run_timing_overlay(
    delta_ar: pd.Series,
    risky_ret: pd.Series,
    bond_ret: pd.Series,
    threshold: float = 1.5,
) -> tuple[pd.Series, pd.Series]:
    """ΔAR 择时：下一交易日生效。

    signal = 0 若 ΔAR > threshold（预警，持有国债）；= 1 若 ΔAR < 0（入场，持有组合）；
    否则维持原仓位。初始底仓为策略组合。
    """
    idx = risky_ret.index
    d = delta_ar.reindex(idx)
    signal = pd.Series(np.nan, index=idx)
    signal[d > threshold] = 0.0
    signal[d < 0] = 1.0
    state = signal.shift(1)          # 次日生效
    state = state.ffill().fillna(1.0)  # 初始底仓为策略组合
    ret = pd.Series(np.where(state > 0.5, risky_ret, bond_ret), index=idx)
    return ret, state


def metrics(ret: pd.Series, periods_per_year: int = 250, rf: float = 0.0) -> dict:
    """累积/年化/波动/夏普/最大回撤/卡玛。"""
    r = ret.dropna()
    n = len(r)
    if n == 0:
        return {k: np.nan for k in ("cum_return", "annual_return", "annual_vol",
                                    "sharpe", "sharpe_arith", "max_drawdown", "calmar", "n_days")}
    nav = (1 + r).cumprod()
    cum = float(nav.iloc[-1] - 1)
    annual = float((1 + cum) ** (periods_per_year / n) - 1)
    vol = float(r.std(ddof=1) * np.sqrt(periods_per_year))
    mdd = float((nav / nav.cummax() - 1).min())
    arith = float(r.mean() * periods_per_year)
    return {
        "cum_return": cum,
        "annual_return": annual,
        "annual_vol": vol,
        "sharpe": (annual - rf) / vol if vol else np.nan,
        "sharpe_arith": (arith - rf) / vol if vol else np.nan,
        "max_drawdown": mdd,
        "calmar": annual / abs(mdd) if mdd else np.nan,
        "n_days": n,
    }


def nav_curve(ret: pd.Series) -> pd.Series:
    return (1 + ret.fillna(0.0)).cumprod()
