"""检验「科技池成长腿＋分腿A016」是否等于「科技池成长腿A016＋分腿A016」。

结论前提：A016 只有两条独立腿 —— {IC, IM} 逐日完全相同、{IF, IH} 完全相同。
于是两种口径的差别只出现在成长日：
  单闸： 成长日收益 = 科技池 × exp_g
  双闸： 成长日收益 = (科技池 × exp_g) × exp_g = 科技池 × exp_g²
只有在 exp_g ∈ {0, 1}（二元敞口）时才等价。
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
STYLE = Path(os.environ.get("V33_STYLE_WEEKLY_CSV", "/Users/hsh/Documents/Quant/风格轮动/research/runs/aw_equity_swap_20261006/v33_style_weekly.csv"))
LEGS = Path(os.environ.get("V33_ETF_LEGS_DIR", "/Users/hsh/Documents/Quant/风格轮动/local/data/etf_legs_20261005"))
A016 = Path(os.environ.get("A016_SIG_CSV", "/Users/hsh/Documents/Quant/择时策略/output/e247_lev_sig_daily.csv"))
START, END, SHIFT = "2021-01-04", "2026-07-31", 2


def etf_ret(n):
    d = pd.read_csv(LEGS / f"etf_{n}.csv", index_col=0, parse_dates=True)
    d.index = pd.to_datetime(d.index)
    return d["close_adj"].pct_change()


def main() -> None:
    df = pd.read_parquet(RAW / "industry_panel_final.parquet")
    df["date"] = pd.to_datetime(df["date"]).dt.tz_localize(None)
    ret = df.pivot(index="date", columns="code", values="ret")
    pb = df.pivot(index="date", columns="code", values="pb")
    fmv = df.pivot(index="date", columns="code", values="float_mv")
    ar, conc = absorption_and_concentration(ret, fmv)
    dc = delta_zscore(conc)
    rv = relative_valuation(pb)
    w = build_daily_weights(dc, rv, ret.index, PortfolioSpec(2, 4, "combined"), "2017-01-01", END)
    px = ret.index
    tech = portfolio_returns(w, ret).reindex(px)

    s = pd.read_csv(STYLE)
    s["signal_date"] = pd.to_datetime(s["signal_date"])
    growth = (s.sort_values("signal_date").set_index("signal_date")["style"]
              .reindex(px, method="ffill").shift(1) > 0)
    value = etf_ret("512890").reindex(px)

    a = pd.read_csv(A016)
    a["date"] = pd.to_datetime(a["date"])
    a = a.set_index("date")
    exp_g = a["IC"].reindex(px).shift(SHIFT).clip(0, 1).fillna(0.0)      # = IM，逐日相同
    exp_v = a["IF"].reindex(px).shift(SHIFT).clip(0, 1).fillna(0.0)      # = IH

    g = pd.Series(np.where(growth, exp_g, exp_v), index=px).loc[START:END]
    gg = exp_g.loc[START:END][growth.loc[START:END]]
    binary = ((gg == 0) | (gg == 1)).mean()
    partial = ((gg > 0) & (gg < 1)).mean()
    print(f"成长日占比 {growth.loc[START:END].mean():.1%}；成长日中敞口为 0 或 1 的占 {binary:.1%}，"
          f"处于 (0,1) 的占 {partial:.1%}")
    print(f"成长日敞口均值 {gg.mean():.3f}；平方后均值 {(gg ** 2).mean():.3f}")

    rows, navs = [], {}
    def show(eq, label):
        rr = (eq * pd.Series(np.where(growth, tech, value), index=px)).loc[START:END]
        m = metrics(rr.dropna())
        o = metrics(rr[rr.index >= "2025-01-01"].dropna())
        rows.append({"variant": label, "avg_exposure": round(float(eq.loc[START:END].mean()), 3),
                     "annual_return": round(m["annual_return"], 4), "annual_vol": round(m["annual_vol"], 4),
                     "sharpe": round(m["sharpe"], 4), "max_drawdown": round(m["max_drawdown"], 4),
                     "calmar": round(m["calmar"], 4), "oos_sharpe": round(o["sharpe"], 4)})
        navs[label] = nav_curve(rr.dropna())

    eq_single = pd.Series(np.where(growth, exp_g, exp_v), index=px)
    eq_double = pd.Series(np.where(growth, exp_g * exp_g, exp_v), index=px)
    eq_growth_gate = pd.Series(np.where(growth, exp_g * exp_g, exp_v), index=px)  # 成长腿×IC 后再×日闸
    show(eq_single, "① 科技池成长腿 ＋分腿A016（单闸）")
    show(eq_double, "② 科技池成长腿A016 ＋分腿A016（成长日双闸=exp²）")
    show(pd.Series(np.where(growth, exp_g, 1.0), index=px), "③ 只在成长日加 IC 闸（价值腿不闸）")
    t = pd.DataFrame(rows).sort_values("sharpe", ascending=False)
    t.to_csv(OUT / "double_gate_check.csv", index=False)
    print()
    print(t.to_string(index=False))
    (OUT / "double_gate_check_summary.json").write_text(json.dumps({
        "finding": "A016 只有两条独立腿：IC==IM、IF==IH（逐日完全相同）",
        "growth_day_partial_exposure_share": round(float(partial), 4),
        "avg_gate_growth": round(float(gg.mean()), 4), "avg_gate_growth_squared": round(float((gg ** 2).mean()), 4),
        "results": t.to_dict(orient="records"),
    }, ensure_ascii=False, indent=2, default=float), encoding="utf-8")


if __name__ == "__main__":
    main()
