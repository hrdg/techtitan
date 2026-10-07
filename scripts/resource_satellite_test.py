"""资源类作为"卫星仓"而不是并入选行业池：按固定权重叠加。"""
from __future__ import annotations

import sys
from pathlib import Path

import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))
from tech_rotation import (  # noqa: E402
    PortfolioSpec, absorption_and_concentration, build_daily_weights, delta_zscore,
    metrics, portfolio_returns, relative_valuation, run_timing_overlay,
)

RAW = ROOT / "data" / "raw"
RES = ["801054", "801055", "801056", "801039", "801086"]
START, END, TH = "2017-01-01", "2026-07-31", 1.5


def load(p):
    d = pd.read_parquet(RAW / p)
    d["date"] = pd.to_datetime(d["date"]).dt.tz_localize(None)
    return (d.pivot(index="date", columns="code", values="ret"),
            d.pivot(index="date", columns="code", values="pb"),
            d.pivot(index="date", columns="code", values="float_mv"))


def show(rr, label):
    m = metrics(rr.dropna())
    o = metrics(rr[rr.index >= "2025-01-01"].dropna())
    print(f"{label:<34} 年化 {m['annual_return']:>7.2%}  夏普 {m['sharpe']:>5.2f}  "
          f"回撤 {m['max_drawdown']:>7.2%}  Calmar {m['calmar']:>5.2f}  OOS夏普 {o['sharpe']:>5.2f}")


def main() -> None:
    ret, pb, fmv = load("industry_panel_final.parquet")
    ar, conc = absorption_and_concentration(ret, fmv)
    dc, d_ar = delta_zscore(conc), delta_zscore(ar)
    rv = relative_valuation(pb)
    w = build_daily_weights(dc, rv, ret.index, PortfolioSpec(2, 4, "combined"), START, END)
    r = portfolio_returns(w, ret)
    r = r[r.index >= START]
    b = pd.read_parquet(RAW / "benchmark_csi_daily.parquet")
    b["date"] = pd.to_datetime(b["date"]).dt.tz_localize(None)
    bond = b[b["code"] == "H11006"].set_index("date")["close"].pct_change().reindex(r.index)
    _, state = run_timing_overlay(d_ar, r, bond, TH)
    gate = state.clip(0, 1)
    rres = load("industry_panel_final_15.parquet")[0][RES].reindex(r.index).mean(axis=1)

    # 月度再平衡的资源等权篮子（更接近可实现）：月内买入持有，月初重置为等权
    raw = load("industry_panel_final_15.parquet")[0][RES].reindex(r.index).fillna(0.0)
    key = [r.index.year, r.index.month]
    monthly = (1 + raw).groupby(key).prod() - 1          # 各行业月度收益
    basket_m = monthly.mean(axis=1)                       # 等权组合月度收益
    rres_m = pd.Series(0.0, index=r.index)
    for (y, mo), v in basket_m.items():
        mask = (r.index.year == y) & (r.index.month == mo)
        rres_m.loc[r.index[mask][-1]] = float(v)

    show(gate * r + (1 - gate) * bond, "U10 + ΔAR（基准）")
    for wgt in (0.10, 0.20, 0.30):
        day = (1 - wgt) * r + wgt * rres
        show(gate * day + (1 - gate) * bond, f"U10 + 资源卫星仓 {int(wgt*100)}%")
    show(gate * rres + (1 - gate) * bond, "只持资源等权（对照）")
    print("\n资源篮子改为月度再平衡（可实现性更好）:")
    for wgt in (0.10, 0.20, 0.30):
        day = (1 - wgt) * r + wgt * rres_m
        show(gate * day + (1 - gate) * bond, f"U10 + 资源卫星仓 {int(wgt*100)}%（月频）")

    # 现实版：月初设定 (1-w) 科技 + w 资源，月内让权重随净值漂移，不再每日拉回
    print("\n权重月内漂移（只在月初重置，最接近可实现）:")
    for wgt in (0.10, 0.20, 0.30):
        daily = pd.Series(0.0, index=r.index)
        for (y, mo) in dict.fromkeys(zip(r.index.year, r.index.month)):
            mask = (r.index.year == y) & (r.index.month == mo)
            rt = r[mask].fillna(0.0)
            rr = rres_m[mask].fillna(0.0)
            nav_t = (1 + rt).cumprod()
            nav_r = (1 + rr).cumprod()
            mix = (1 - wgt) * nav_t + wgt * nav_r            # 月内权重随净值漂移
            daily[mask] = mix.pct_change().fillna(mix.iloc[0] - 1)
        show(gate * daily + (1 - gate) * bond, f"U10 + 资源卫星仓 {int(wgt*100)}%（漂移）")

    # 真实相关性：用"月内权重漂移"的资源篮子日收益（rres_m 只在月末有值，不能直接相关）
    res_daily = pd.Series(0.0, index=r.index)
    raw_res = load("industry_panel_final_15.parquet")[0][RES].reindex(r.index).fillna(0.0)
    for (y, mo) in dict.fromkeys(zip(r.index.year, r.index.month)):
        mask = (r.index.year == y) & (r.index.month == mo)
        nav = (1 + raw_res[mask]).cumprod().mean(axis=1)      # 月初等权、月内漂移
        res_daily[mask] = nav.pct_change().fillna(nav.iloc[0] - 1)
    print("\n相关性与对照:")
    print(f"  科技组合与资源篮子的日收益相关性 {r.corr(res_daily):.3f}"
          f"（资源篮子年化 {metrics(res_daily)['annual_return']:.1%}、"
          f"波动 {metrics(res_daily)['annual_vol']:.1%}）")


if __name__ == "__main__":
    main()
