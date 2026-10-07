"""科技池(10 ETF) + 风格轮动 v3.3 + 分腿 A016 的组合测试。

- 科技袖：研报 10 行业「高集中度高估值」+ ΔAR(1.5)（本项目复现），可选再叠加 A016(IC) 分腿闸。
- 风格袖：风格轮动项目 v3.3（成长/价值周频票 → 512100 中证1000ETF / 510300 沪深300ETF），
  两种口径：gated = 分腿 A016（持 1000 用 exp_im、持 300 用 exp_if）；ungated = 无 A016。
  数据取自 风格轮动/research/runs/v33_size_etf_20261005/nav_platform.csv（聚宽实测净值，含成本）。
- 共同窗口 2021-01-04 ~ 2026-07-31（v3.3 信号自 2021-01 起，研报窗口至 2026-07 止）。
- 权重按月重置、月内漂移。
注意：风格袖净值含交易成本（佣金 0.005%/边 + 滑点 0.2%/边），科技袖为零成本，两者不完全对等。
"""
from __future__ import annotations

import os

import json
import sys
from pathlib import Path

import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))
from tech_rotation import (  # noqa: E402
    PortfolioSpec, absorption_and_concentration, build_daily_weights, delta_zscore,
    metrics, nav_curve, portfolio_returns, relative_valuation, run_timing_overlay,
)

RAW = ROOT / "data" / "raw"
OUT = ROOT / "results"
V33_NAV = Path(os.environ.get("V33_NAV_CSV", "/Users/hsh/Documents/Quant/风格轮动/research/runs/v33_size_etf_20261005/nav_platform.csv"))
START, END, TH, SHIFT = "2021-01-04", "2026-07-31", 1.5, 2


def blend(tech: pd.Series, style: pd.Series, w: float) -> pd.Series:
    """按月重置权重、月内漂移的 w 科技 + (1-w) 风格。"""
    out = pd.Series(0.0, index=tech.index)
    key = list(zip(tech.index.year, tech.index.month))
    for (y, mo) in dict.fromkeys(key):
        mask = (tech.index.year == y) & (tech.index.month == mo)
        nt = (1 + tech[mask].fillna(0)).cumprod()
        ns = (1 + style[mask].fillna(0)).cumprod()
        mix = w * nt + (1 - w) * ns
        out[mask] = mix.pct_change().fillna(mix.iloc[0] - 1)
    return out


def show(rr, label, rows):
    m = metrics(rr.dropna())
    o = metrics(rr[rr.index >= "2025-01-01"].dropna())
    rows.append({"variant": label, "annual_return": round(m["annual_return"], 4),
                 "annual_vol": round(m["annual_vol"], 4), "sharpe": round(m["sharpe"], 4),
                 "max_drawdown": round(m["max_drawdown"], 4), "calmar": round(m["calmar"], 4),
                 "oos_annual": round(o["annual_return"], 4), "oos_sharpe": round(o["sharpe"], 4),
                 "n_days": int(m["n_days"])})
    return nav_curve(rr.dropna())


def main() -> None:
    df = pd.read_parquet(RAW / "industry_panel_final.parquet")
    df["date"] = pd.to_datetime(df["date"]).dt.tz_localize(None)
    ret = df.pivot(index="date", columns="code", values="ret")
    pb = df.pivot(index="date", columns="code", values="pb")
    fmv = df.pivot(index="date", columns="code", values="float_mv")
    ar, conc = absorption_and_concentration(ret, fmv)
    dc, d_ar = delta_zscore(conc), delta_zscore(ar)
    rv = relative_valuation(pb)
    w = build_daily_weights(dc, rv, ret.index, PortfolioSpec(2, 4, "combined"), "2017-01-01", END)
    tech = portfolio_returns(w, ret)
    tech = tech[tech.index >= START]
    b = pd.read_parquet(RAW / "benchmark_csi_daily.parquet")
    b["date"] = pd.to_datetime(b["date"]).dt.tz_localize(None)
    bond = b[b["code"] == "H11006"].set_index("date")["close"].pct_change().reindex(tech.index)
    _, state = run_timing_overlay(d_ar, tech, bond, TH)
    tech_dar = state.clip(0, 1) * tech + (1 - state.clip(0, 1)) * bond

    a = pd.read_csv(Path("/Users/hsh/Documents/Quant/择时策略/output/e247_lev_sig_daily.csv"))
    a["date"] = pd.to_datetime(a["date"])
    exp_ic = a.set_index("date")["IC"].reindex(tech.index).shift(SHIFT).clip(0, 1).fillna(0.0)
    tech_a016 = exp_ic * tech + (1 - exp_ic) * bond
    tech_both = (exp_ic * state.clip(0, 1)) * tech + (1 - exp_ic * state.clip(0, 1)) * bond

    v = pd.read_csv(V33_NAV)
    v["date"] = pd.to_datetime(v["date"])
    v = v.set_index("date")
    style_gated = v["gated"].reindex(tech.index).pct_change()
    style_ungated = v["ungated"].reindex(tech.index).pct_change()

    rows, navs = [], {}
    navs["① 科技+ΔAR（基准）"] = show(tech_dar, "① 科技+ΔAR（基准）", rows)
    navs["② 科技+分腿A016(IC)"] = show(tech_a016, "② 科技+分腿A016(IC)", rows)
    navs["③ v3.3 无A016"] = show(style_ungated, "③ v3.3 无A016", rows)
    navs["④ v3.3 分腿A016"] = show(style_gated, "④ v3.3 分腿A016", rows)
    for wgt in (0.5, 0.6, 0.7):
        for tag, sty in (("v3.3无闸", style_ungated), ("v3.3分腿A016", style_gated)):
            lbl = f"{int(wgt*100)}% 科技+ΔAR ＋ {int((1-wgt)*100)}% {tag}"
            navs[lbl] = show(blend(tech_dar, sty, wgt), lbl, rows)
    for wgt in (0.5, 0.6, 0.7):
        lbl = f"{int(wgt*100)}% 科技+分腿A016 ＋ {int((1-wgt)*100)}% v3.3分腿A016"
        navs[lbl] = show(blend(tech_a016, style_gated, wgt), lbl, rows)

    t = pd.DataFrame(rows).sort_values("sharpe", ascending=False)
    t.to_csv(OUT / "combine_tech_v33.csv", index=False)
    pd.DataFrame(navs).to_csv(OUT / "combine_tech_v33_nav.csv")
    print(f"共同窗口 {tech.index.min().date()} ~ {tech.index.max().date()}, {len(tech)} 个交易日")
    print(t.to_string(index=False))
    print(f"\n科技袖与 v3.3(分腿A016) 日收益相关性 "
          f"{tech_dar.corr(style_gated.reindex(tech_dar.index)):.3f} | "
          f"与 v3.3 无闸 {tech_dar.corr(style_ungated.reindex(tech_dar.index)):.3f}")
    (OUT / "combine_tech_v33_summary.json").write_text(json.dumps({
        "window": [str(tech.index.min().date()), str(tech.index.max().date())],
        "sources": {"v33_nav": str(V33_NAV),
                    "v33_definition": "成长/价值周频票 → 512100 中证1000ETF / 510300 沪深300ETF；gated 为分腿 A016"},
        "caveat": "风格袖含成本、科技袖零成本；权重按月重置",
        "results": t.to_dict(orient="records"),
    }, ensure_ascii=False, indent=2, default=float), encoding="utf-8")


if __name__ == "__main__":
    main()
