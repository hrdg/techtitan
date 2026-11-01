"""在「高集中度高估值 + ΔAR(1.5)」上叠加 TIP 综合动量、200D 趋势、15%/20% 波动率目标。

口径沿用本机既有项目：
- TIP 综合动量：TIP 的 28/84/168/364 日收益均值 > 0（全天候 ndx_timing 的 H5_TIP13612）；
- 200D 趋势：等权行业指数收盘 > 200 日均线（同一框架的 close_above_ma）；
- 15%/20% 风控：63 日实现波动率目标，缩放系数 clip 到 0.3~1（全天候 H2 vol multiplier）。
所有信号只用 t 之前的信息，t 日执行；成本按 |Δ敞口| 单边 5bp 计。
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
    PortfolioSpec, absorption_and_concentration, build_daily_weights, delta_zscore,
    metrics, portfolio_returns, relative_valuation, run_timing_overlay,
)

RAW = ROOT / "data" / "raw"
OUT = ROOT / "results"
START, END, TH = "2017-01-03", "2026-07-31", 1.5
COST = 5e-4
VOL_WIN = 63
VT_CLIP = (0.3, 1.0)


def tip_gate(dates: pd.DatetimeIndex) -> pd.Series:
    t = pd.read_parquet(RAW / "tip_daily.parquet")
    t["date"] = pd.to_datetime(t["date"])
    t = t.set_index("date")["close"].sort_index()
    t.index = pd.DatetimeIndex(t.index).astype("datetime64[ns]")
    score = pd.concat([t / t.shift(d) - 1 for d in (28, 84, 168, 364)], axis=1).mean(axis=1)
    g = pd.Series(np.where(score > 0, 1.0, 0.0), index=t.index)
    g[score.isna()] = np.nan
    left = pd.DataFrame({"date": pd.DatetimeIndex(dates).astype("datetime64[ns]")})
    right = g.dropna().rename("tip").reset_index()
    m = pd.merge_asof(left, right, on="date", direction="backward", allow_exact_matches=False)
    return pd.Series(m["tip"].values, index=dates)


def main() -> None:
    df = pd.read_parquet(RAW / "industry_panel_final_delisted.parquet")
    df["date"] = pd.to_datetime(df["date"]).dt.tz_localize(None)
    ret = df.pivot(index="date", columns="code", values="ret")
    pb = df.pivot(index="date", columns="code", values="pb")
    fmv = df.pivot(index="date", columns="code", values="float_mv")
    ar, conc = absorption_and_concentration(ret, fmv)
    dc, d_ar = delta_zscore(conc), delta_zscore(ar)
    rv = relative_valuation(pb)
    w = build_daily_weights(dc, rv, ret.index, PortfolioSpec(2, 4, "combined"), START, END)
    r = portfolio_returns(w, ret)
    r = r[r.index >= START]
    b = pd.read_parquet(RAW / "benchmark_csi_daily.parquet")
    b["date"] = pd.to_datetime(b["date"]).dt.tz_localize(None)
    bond = b[b["code"] == "H11006"].set_index("date")["close"].pct_change().reindex(r.index)
    base, state = run_timing_overlay(d_ar, r, bond, TH)

    dates = r.index
    # 200D：等权行业指数
    ew = ret.mean(axis=1).reindex(dates)
    level = (1 + ew.fillna(0)).cumprod()
    ma = level.rolling(200).mean()
    gate_ma = pd.Series(np.where(level > ma, 1.0, 0.0), index=dates).shift(1)

    gate_tip = tip_gate(dates).shift(1)

    vol = base.rolling(VOL_WIN).std(ddof=1) * np.sqrt(250)
    vol = vol.shift(1)

    def vt(target: float) -> pd.Series:
        return (target / vol).clip(*VT_CLIP).fillna(0.0)

    rows, navs = [], {}
    def run(label: str, exposure: pd.Series):
        eq = exposure.reindex(dates).fillna(0.0).clip(0, 1)
        rr = eq * r + (1 - eq) * bond.reindex(dates)
        rr = rr - COST * eq.diff().abs().fillna(0.0)
        m = metrics(rr.dropna())
        rows.append({"variant": label, "avg_equity": round(float(eq.mean()), 3),
                     "annual_return": round(m["annual_return"], 4),
                     "annual_vol": round(m["annual_vol"], 4), "sharpe": round(m["sharpe"], 4),
                     "max_drawdown": round(m["max_drawdown"], 4), "calmar": round(m["calmar"], 4),
                     "switches": int((eq.diff().abs() > 1e-9).sum())})
        navs[label] = (1 + rr.fillna(0)).cumprod()

    s = state.clip(0, 1)
    run("① 基准：组合+ΔAR(1.5)", s)
    run("② +TIP综合动量", s * gate_tip)
    run("③ +200D趋势", s * gate_ma)
    run("④ +15%波动率目标", s * vt(0.15))
    run("⑤ +20%波动率目标", s * vt(0.20))
    run("⑥ +TIP+200D", s * gate_tip * gate_ma)
    run("⑦ +TIP+200D+15%目标(相乘)", s * gate_tip * gate_ma * vt(0.15))
    run("⑧ +TIP+200D+20%目标(相乘)", s * gate_tip * gate_ma * vt(0.20))
    run("⑨ +200D+15%目标", s * gate_ma * vt(0.15))
    run("⑩ +TIP+15%目标", s * gate_tip * vt(0.15))
    run("⑪ 综合·仅最严生效(min)", s * pd.concat([gate_tip, gate_ma, vt(0.15)], axis=1).min(axis=1))
    t = pd.DataFrame(rows).sort_values("sharpe", ascending=False)
    t.to_csv(OUT / "risk_overlay_comparison.csv", index=False)
    pd.DataFrame(navs).to_csv(OUT / "risk_overlay_nav.csv")
    print(f"窗口 {START} ~ {END}（退市补齐面板），成本 5bp/单边换手")
    print(t.to_string(index=False))
    print(f"\n信号均值: TIP {gate_tip.mean():.2f} | 200D {gate_ma.mean():.2f} | "
          f"vt15 {vt(0.15).mean():.2f} | vt20 {vt(0.20).mean():.2f}")
    (OUT / "risk_overlay_summary.json").write_text(json.dumps({
        "window": [START, END],
        "definitions": {"tip": "mean(28/84/168/364d returns) > 0",
                        "ma200": "等权行业指数 > 200DMA",
                        "vol_target": "63d 实现波动率目标，缩放 clip 0.3-1"},
        "cost": "5bp × |Δ敞口|", "results": t.to_dict(orient="records"),
    }, ensure_ascii=False, indent=2, default=float), encoding="utf-8")


if __name__ == "__main__":
    main()
