"""行业轮动因子：PCA 集中度 ΔC、总吸收比率 AR / ΔAR、相对估值 RV。

对应研报：西南证券《科技成长景气轮动与量化择时模型》(2026-09-10)
- 2.1 节：集中度指标（PCA 吸收比率 + 暴露绝对值加权）、ΔC
- 2.2 节：相对估值指标（PB 时序标准化后再做横截面标准化）
- 3.1/3.2 节：总吸收比率 AR 与变化量 ΔAR

实现口径见 research/runs/swsc_tech_rotation_260910/strategy.json 的 DEC-002 / DEC-003。
"""
from __future__ import annotations

import numpy as np
import pandas as pd


def _window_pca(
    ret_window: np.ndarray,
    mktcap_prev: np.ndarray,
    decay: np.ndarray,
    n_components: int,
    use_mktcap: bool = True,
    use_decay: bool = True,
    standardize: bool = False,
) -> tuple[np.ndarray, np.ndarray, np.ndarray]:
    """单窗口 PCA。

    Parameters
    ----------
    ret_window : (n_days, n_assets) 窗口内日收益（按时间升序）
    mktcap_prev : (n_days, n_assets) 每条收益对应的前一交易日行业流通市值
    decay : (n_days,) 指数衰减权重，最新一天权重最大
    n_components : 主成分个数 m

    Returns
    -------
    ar : (n_components,) 吸收比率
    loadings : (n_assets, n_components) 行业在各主成分上的暴露
    total_ar : 前 m 个主成分吸收比率之和
    """
    x = ret_window.copy()
    if use_decay:
        x = x * decay[:, None]
    if use_mktcap:
        x = x * np.sqrt(mktcap_prev)
    x = x - x.mean(axis=0, keepdims=True)
    if standardize:
        sd = x.std(axis=0, ddof=1, keepdims=True)
        x = x / np.where(sd > 0, sd, 1.0)
    # 列去均值后做 SVD；奇异值平方 ∝ 主成分方差
    _, sv, vt = np.linalg.svd(x, full_matrices=False)
    var = sv**2 / max(len(x) - 1, 1)
    ar = var / var.sum()
    loadings = vt.T[:, :n_components]
    return ar[:n_components], loadings, float(ar[:n_components].sum())


def absorption_and_concentration(
    returns: pd.DataFrame,
    float_mv: pd.DataFrame,
    window: int = 125,
    m: int = 2,
    half_life: int = 125,
    use_mktcap: bool = True,
    use_decay: bool = True,
    standardize: bool = False,
) -> tuple[pd.Series, pd.DataFrame]:
    """滚动 PCA，返回总吸收比率 AR_t 与行业集中度 C_{i,t}。

    C_i,t = Σ_j ( AR_j × |EV^j_i| / Σ_i |EV^j_i| ) / Σ_j AR_j
    """
    dates = returns.index
    assets = returns.columns
    ar_out = pd.Series(index=dates, dtype=float, name="AR")
    c_out = pd.DataFrame(index=dates, columns=assets, dtype=float)

    r = returns.to_numpy(dtype=float)
    mc = float_mv.shift(1).to_numpy(dtype=float)  # 前一交易日流通市值
    decay = 0.5 ** ((window - 1 - np.arange(window)) / half_life)

    for i in range(window - 1, len(dates)):
        sl = slice(i - window + 1, i + 1)
        rw, mw = r[sl], mc[sl]
        if np.isnan(rw).any() or np.isnan(mw).any() or (mw <= 0).any():
            continue
        ar, load, total = _window_pca(rw, mw, decay, m, use_mktcap, use_decay, standardize)
        ar_out.iat[i] = total
        abs_load = np.abs(load)
        denom_i = abs_load.sum(axis=0)
        share = abs_load / denom_i[None, :]
        c_out.iloc[i] = (share * ar[None, :]).sum(axis=1) / ar.sum()
    return ar_out, c_out


def delta_zscore(series: pd.DataFrame | pd.Series, short: int = 15, long: int = 125) -> pd.DataFrame | pd.Series:
    """Δ = (mean_short - mean_long) / std_long，长周期标准差用 ddof=1。"""
    short_mean = series.rolling(short).mean()
    long_mean = series.rolling(long).mean()
    long_std = series.rolling(long).std(ddof=1)
    return (short_mean - long_mean) / long_std


def relative_valuation(
    pb: pd.DataFrame,
    window: int = 500,
    min_periods: int = 250,
    leave_one_out: bool = True,
) -> pd.DataFrame:
    """相对估值指标。

    SPB_i,t = PB_i,t / mean_{过去 window 个交易日}(PB_i)
    RV_i,t  = SPB_i,t / mean_{j≠i}(SPB_j,t)
    """
    base = pb.rolling(window, min_periods=min_periods).mean()
    spb = pb / base
    n = spb.shape[1]
    total = spb.sum(axis=1)
    if leave_one_out:
        # 其余行业标准化市净率的横截面均值（剔除本行业）
        others = (total.values[:, None] - spb.values) / (n - 1)
        return pd.DataFrame(spb.values / others, index=spb.index, columns=spb.columns)
    return spb.div(total / n, axis=0)
