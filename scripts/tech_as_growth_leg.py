"""把「科技池 10 ETF」接进风格轮动 v3.3 的成长腿，再叠分腿 A016。

结构：v3.3 周频产出成长/价值方向 →
      成长日 → 持科技池（研报 10 行业「高集中度高估值」组合，可选叠加 ΔAR(1.5)）
      价值日 → 持 512890 红利低波ETF
      分腿 A016：成长日用 exp_im（2022-07 前用 exp_ic）、价值日用 exp_if；敞口 clip 到 [0,1]，其余为现金。

对照：把成长腿换回 v3.3 原版的 159915（创业板ETF）+ 588000（科创50ETF）各半。
窗口 2021-01-04 ~ 2026-07-31。注意：科技池为指数口径（非 ETF 实价），原版腿为 ETF 复权价。
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


def etf_ret(name: str) -> pd.Series:
    d = pd.read_csv(LEGS / f"etf_{name}.csv", index_col=0, parse_dates=True)
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
    tech = portfolio_returns(w, ret)

    px = ret.index
    tech = tech.reindex(px)
    b = pd.read_parquet(RAW / "benchmark_csi_daily.parquet")
    b["date"] = pd.to_datetime(b["date"]).dt.tz_localize(None)
    bond = b[b["code"] == "H11006"].set_index("date")["close"].pct_change().reindex(px)
    _, state = run_timing_overlay(d_ar, tech.reindex(px), bond, TH)
    tech_dar = state.clip(0, 1) * tech + (1 - state.clip(0, 1)) * bond

    # v3.3 周频方向 -> 日频（signal_date 次一交易日生效）
    s = pd.read_csv(STYLE)
    s["signal_date"] = pd.to_datetime(s["signal_date"])
    s = s.sort_values("signal_date").set_index("signal_date")["style"]
    daily = s.reindex(px, method="ffill").shift(1)      # 次一交易日执行
    growth = (daily > 0)

    g_old = 0.5 * etf_ret("159915").reindex(px) + 0.5 * etf_ret("588000").reindex(px)
    value = etf_ret("512890").reindex(px)

    a = pd.read_csv(A016)
    a["date"] = pd.to_datetime(a["date"])
    a = a.set_index("date")
    exp_ic = a["IC"].reindex(px).shift(SHIFT).clip(0, 1)
    exp_im = a["IM"].reindex(px).shift(SHIFT).clip(0, 1)
    exp_if = a["IF"].reindex(px).shift(SHIFT).clip(0, 1)
    gate_growth = exp_im.fillna(exp_ic).fillna(0.0)
    gate_value = exp_if.fillna(0.0)
    gate = pd.Series(np.where(growth, gate_growth, gate_value), index=px)

    def leg(growth_series: pd.Series) -> pd.Series:
        return pd.Series(np.where(growth, growth_series, value), index=px)

    rows, navs = [], {}
    def show(rr, label, use_gate):
        rr = rr.reindex(px)
        rr = rr[rr.index >= START]
        if use_gate:
            g = gate.reindex(rr.index).fillna(0.0)
            rr = g * rr            # 其余为现金（与 v33_size_etf 口径一致）
        m = metrics(rr.dropna())
        o = metrics(rr[rr.index >= "2025-01-01"].dropna())
        rows.append({"variant": label, "annual_return": round(m["annual_return"], 4),
                     "annual_vol": round(m["annual_vol"], 4), "sharpe": round(m["sharpe"], 4),
                     "max_drawdown": round(m["max_drawdown"], 4), "calmar": round(m["calmar"], 4),
                     "oos_annual": round(o["annual_return"], 4), "oos_sharpe": round(o["sharpe"], 4)})
        navs[label] = nav_curve(rr.dropna())

    for use_gate in (False, True):
        tag = "＋分腿A016" if use_gate else "（无A016）"
        show(leg(g_old), f"原版成长腿(159915+588000) {tag}", use_gate)
        show(leg(tech), f"科技池成长腿 {tag}", use_gate)
        show(leg(tech_dar), f"科技池+ΔAR成长腿 {tag}", use_gate)

    t = pd.DataFrame(rows).sort_values("sharpe", ascending=False)
    t.to_csv(OUT / "tech_as_growth_leg.csv", index=False)
    pd.DataFrame(navs).to_csv(OUT / "tech_as_growth_leg_nav.csv")
    print(f"窗口 {START} ~ {END}；成长日占比 {(growth.loc[START:END]).mean():.1%}")
    print(t.to_string(index=False))
    print(f"\n平均敞口（分腿A016）: 成长日 {gate_growth.loc[START:END].mean():.3f} | "
          f"价值日 {gate_value.loc[START:END].mean():.3f}")
    (OUT / "tech_as_growth_leg_summary.json").write_text(json.dumps({
        "window": [START, END], "growth_day_share": round(float(growth.loc[START:END].mean()), 4),
        "avg_gate_growth": round(float(gate_growth.loc[START:END].mean()), 4),
        "avg_gate_value": round(float(gate_value.loc[START:END].mean()), 4),
        "results": t.to_dict(orient="records"),
        "caveat": "科技池为指数口径、原版腿与价值腿为 ETF 复权价；A016 敞口 clip 到 [0,1]，其余现金",
    }, ensure_ascii=False, indent=2, default=float), encoding="utf-8")


if __name__ == "__main__":
    main()
