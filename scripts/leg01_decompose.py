"""拆解 ①「科技池成长腿 ＋分腿A016（单闸）」的三层贡献。

L0 科技池裸组合（无风格开关、无闸，100% 在场）
L1 加 v3.3 风格开关（成长→科技池，价值→512890），仍 100% 在场
L2 再加分腿 A016 日闸 → 这就是 ①
对照：把成长腿换成「科技池+ΔAR」后加同一个闸
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
START, END, TH, SHIFT = "2021-01-04", "2026-07-31", 1.5, 2


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
    dc, d_ar = delta_zscore(conc), delta_zscore(ar)
    rv = relative_valuation(pb)
    w = build_daily_weights(dc, rv, ret.index, PortfolioSpec(2, 4, "combined"), "2017-01-01", END)
    px = ret.index
    tech = portfolio_returns(w, ret).reindex(px)
    b = pd.read_parquet(RAW / "benchmark_csi_daily.parquet")
    b["date"] = pd.to_datetime(b["date"]).dt.tz_localize(None)
    bond = b[b["code"] == "H11006"].set_index("date")["close"].pct_change().reindex(px)
    _, state = run_timing_overlay(d_ar, tech, bond, TH)
    tech_dar = state.clip(0, 1) * tech + (1 - state.clip(0, 1)) * bond

    s = pd.read_csv(STYLE)
    s["signal_date"] = pd.to_datetime(s["signal_date"])
    growth = (s.sort_values("signal_date").set_index("signal_date")["style"]
              .reindex(px, method="ffill").shift(1) > 0)
    value = etf_ret("512890").reindex(px)

    a = pd.read_csv(A016)
    a["date"] = pd.to_datetime(a["date"])
    a = a.set_index("date")
    exp_g = a["IC"].reindex(px).shift(SHIFT).clip(0, 1).fillna(0.0)
    exp_v = a["IF"].reindex(px).shift(SHIFT).clip(0, 1).fillna(0.0)
    gate = pd.Series(np.where(growth, exp_g, exp_v), index=px)

    rows, navs = [], {}
    def show(rr, label):
        rr = rr.loc[START:END].dropna()
        m = metrics(rr)
        o = metrics(rr[rr.index >= "2025-01-01"])
        rows.append({"layer": label, "annual_return": round(m["annual_return"], 4),
                     "annual_vol": round(m["annual_vol"], 4), "sharpe": round(m["sharpe"], 4),
                     "max_drawdown": round(m["max_drawdown"], 4), "calmar": round(m["calmar"], 4),
                     "oos_sharpe": round(o["sharpe"], 4)})
        navs[label] = nav_curve(rr)

    style_mix = pd.Series(np.where(growth, tech, value), index=px)
    style_mix_dar = pd.Series(np.where(growth, tech_dar, value), index=px)
    show(tech, "L0 科技池裸组合（无风格开关/无闸）")
    show(style_mix, "L1 ＋v3.3 风格开关（价值腿 512890）")
    show(gate * style_mix, "L2 ＋分腿A016 日闸 ＝ ①")
    show(gate * style_mix_dar, "对照：成长腿换成 科技池+ΔAR 后加同一闸")
    t = pd.DataFrame(rows)
    t.to_csv(OUT / "leg01_decompose.csv", index=False)
    pd.DataFrame(navs).to_csv(OUT / "leg01_decompose_nav.csv")
    print(f"窗口 {START} ~ {END}；成长日占比 {growth.loc[START:END].mean():.1%}；"
          f"A016 日闸均值 {gate.loc[START:END].mean():.3f}")
    print(t.to_string(index=False))
    (OUT / "leg01_decompose_summary.json").write_text(json.dumps({
        "answer": "① 的科技池成长腿是裸组合：不含 ΔAR，也不对科技池单独加 A016；唯一的仓位控制在 A016 日闸",
        "growth_day_share": round(float(growth.loc[START:END].mean()), 4),
        "avg_gate": round(float(gate.loc[START:END].mean()), 4),
        "results": t.to_dict(orient="records"),
    }, ensure_ascii=False, indent=2, default=float), encoding="utf-8")


if __name__ == "__main__":
    main()
