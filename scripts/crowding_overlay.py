"""在「高集中度高估值 + ΔAR(1.5)」上再考虑拥挤度。

拥挤度指标（全部来自成分股重建，2016-2026 全窗口可得）：
  - 行业换手率 = Σ成分股成交额 / Σ成分股流通市值
  - 行业成交额占全市场比（该口径已复现研报图 1：2026-07-10 峰值 46.1% vs 研报 46.5%）
  - 板块拥挤度 = 10 行业合计成交额占比 的 250 日 z 分数
预注册判据：风险调整后效率（夏普/Calmar）为主，样本外不得明显恶化，平均敞口一并披露。
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from tech_rotation import (  # noqa: E402
    PortfolioSpec,
    absorption_and_concentration,
    build_daily_weights,
    delta_zscore,
    metrics,
    nav_curve,
    portfolio_returns,
    relative_valuation,
    run_timing_overlay,
)

RAW = ROOT / "data" / "raw"
OUT = ROOT / "results"
START, END, TH, COST = "2017-01-01", "2026-07-31", 1.5, 5e-4
W = 250


def zscore(df: pd.DataFrame | pd.Series, w: int = W) -> pd.DataFrame | pd.Series:
    mu = df.rolling(w).mean()
    sd = df.rolling(w).std(ddof=1)
    return (df - mu) / sd


def main() -> None:
    df = pd.read_parquet(RAW / "industry_panel_final.parquet")
    df["date"] = pd.to_datetime(df["date"]).dt.tz_localize(None)
    ret = df.pivot(index="date", columns="code", values="ret")
    pb = df.pivot(index="date", columns="code", values="pb")
    fmv = df.pivot(index="date", columns="code", values="float_mv")

    ar, conc = absorption_and_concentration(ret, fmv)
    dc, d_ar = delta_zscore(conc), delta_zscore(ar)
    rv = relative_valuation(pb)

    # --- 拥挤度（来自本地面板；2017 起才有，2016 用于暖机）---
    prox = pd.read_parquet(RAW / "industry_panel_proxy.parquet")
    prox["date"] = pd.to_datetime(prox["date"]).dt.tz_localize(None)
    turn = prox.pivot(index="date", columns="code", values="turnover_pct").reindex(ret.index)
    share = prox.pivot(index="date", columns="code", values="amount_share_pct").reindex(ret.index)
    turn_z = zscore(turn)
    sector_share = share.sum(axis=1)
    sector_z = zscore(sector_share)
    print("拥挤度覆盖:", turn_z.notna().any(axis=1).sum(), "/", len(ret),
          "| 板块占比 2017 均 %.1f%% → 2026 均 %.1f%%" % (
              sector_share["2017"].mean(), sector_share["2026"].mean()))
    print("板块拥挤度 z: 均值 %.2f p90 %.2f p95 %.2f max %.2f" % (
        sector_z.mean(), sector_z.quantile(.9), sector_z.quantile(.95), sector_z.max()))

    b = pd.read_parquet(RAW / "benchmark_csi_daily.parquet")
    b["date"] = pd.to_datetime(b["date"]).dt.tz_localize(None)
    bond = b[b["code"] == "H11006"].set_index("date")["close"].reindex(ret.index).pct_change()

    def run(label: str, exclude: pd.DataFrame | None = None, gate: pd.Series | None = None,
            scale: pd.Series | None = None, use_dar: bool = True) -> tuple[dict, pd.Series]:
        w = build_daily_weights(dc, rv, ret.index, PortfolioSpec(2, 4, "combined"),
                                START, END, exclude=exclude)
        r = portfolio_returns(w, ret)
        r = r[r.index >= START]
        ew = pd.Series(1.0, index=r.index)
        if use_dar:
            _, st = run_timing_overlay(d_ar, r, r * 0.0, TH)
            ew = ew * st.clip(0, 1)
        if gate is not None:
            ew = ew * gate.reindex(r.index).fillna(1.0)
        if scale is not None:
            ew = ew * scale.reindex(r.index).fillna(1.0).clip(0, 1)
        rr = ew * r + (1 - ew) * bond.reindex(r.index)
        rr = rr - COST * ew.diff().abs().fillna(0.0)
        m = metrics(rr.dropna())
        o = metrics(rr[rr.index >= "2025-01-01"].dropna())
        return {"variant": label, "avg_equity": round(float(ew.mean()), 3),
                "annual_return": round(m["annual_return"], 4), "annual_vol": round(m["annual_vol"], 4),
                "sharpe": round(m["sharpe"], 4), "max_drawdown": round(m["max_drawdown"], 4),
                "calmar": round(m["calmar"], 4), "oos_annual": round(o["annual_return"], 4),
                "oos_sharpe": round(o["sharpe"], 4)}, nav_curve(rr.dropna())

    rows, navs = [], {}
    variants = [
        ("C0 基准：ΔAR(1.5)", {}),
        ("C1 选行业剔除拥挤(top20%换手z)", {"exclude": turn_z > turn_z.quantile(0.80, axis=1).values[:, None]}),
        ("C1b 选行业剔除拥挤(换手z>2)", {"exclude": turn_z > 2.0}),
        ("C2 板块拥挤z>2 减半仓", {"gate": pd.Series(np.where(sector_z > 2.0, 0.5, 1.0), index=ret.index)}),
        ("C2b 板块拥挤z>2 清仓", {"gate": pd.Series(np.where(sector_z > 2.0, 0.0, 1.0), index=ret.index)}),
        ("C2c 板块占比分位>90% 减半仓", {"gate": pd.Series(
            np.where(sector_share > sector_share.rolling(W).quantile(0.90), 0.5, 1.0), index=ret.index)}),
        ("C3 敞口×(1-拥挤z/4)缩放", {"scale": (1 - (sector_z / 4).clip(0, 1))}),
        ("C4 C1+C2 组合", {"exclude": turn_z > 2.0,
                            "gate": pd.Series(np.where(sector_z > 2.0, 0.5, 1.0), index=ret.index)}),
    ]
    for label, kw in variants:
        row, nav = run(label, **kw)
        rows.append(row)
        navs[label] = nav
    t = pd.DataFrame(rows).sort_values("sharpe", ascending=False)
    t.to_csv(OUT / "crowding_overlay.csv", index=False)
    pd.DataFrame(navs).to_csv(OUT / "crowding_overlay_nav.csv")
    print()
    print(t.to_string(index=False))
    (OUT / "crowding_overlay_summary.json").write_text(json.dumps({
        "criterion": "风险调整后效率为主，样本外不得明显恶化；平均敞口一并披露",
        "figure1_reproduction": {"2026-07-10": round(float(sector_share.get(pd.Timestamp("2026-07-10"), np.nan)), 2),
                                 "report": 46.5, "2026H1_mean": round(float(sector_share["2026-01-01":"2026-06-30"].mean()), 2),
                                 "report_h1": "接近 37"},
        "results": t.to_dict(orient="records"),
    }, ensure_ascii=False, indent=2, default=float), encoding="utf-8")


if __name__ == "__main__":
    main()
