"""宏观剪刀差的软性分与"闸+软性分"组合：先声明假设，再验证。

H1 软性分优于硬闸：连续缩放保留上行暴露，Sharpe/Calmar 应高于二元闸。
H2 "尾部硬切 + 中间软缩放"优于两者：极端负值时清仓，其余按信号强度缩放。
H3 软性分与 ΔAR×TIP 信息重叠：相对基线的增量有限（预计 < 0.05 夏普）。

信号：M1-M2 剪刀差的 3 个月变化（月度、滞后一月）；z 用过去 36 个月标准化（因果）。
软性分：w = floor + (1-floor)/(1+exp(-z))；闸：z>0 时 1、否则 0；组合：z<-1 硬切，否则软性分。
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
    metrics, nav_curve, portfolio_returns, relative_valuation, run_timing_overlay,
)

RAW = ROOT / "data" / "raw"
OUT = ROOT / "results"
CMS = Path("/Users/hsh/Documents/Quant/风格轮动/style-rotation/local/data/"
           "prepared_joinquant_20261001")
START, END, TH = "2017-01-03", "2026-10-30", 1.5


def main() -> None:
    df = pd.read_parquet(RAW / "industry_panel_latest.parquet")
    df["date"] = pd.to_datetime(df["date"]).dt.tz_localize(None)
    ret = df.pivot(index="date", columns="code", values="ret")
    pb = df.pivot(index="date", columns="code", values="pb")
    fmv = df.pivot(index="date", columns="code", values="float_mv")
    ar, conc = absorption_and_concentration(ret, fmv)
    dc, rv, d_ar = delta_zscore(conc), relative_valuation(pb), delta_zscore(ar)
    b = pd.read_parquet(RAW / "benchmark_csi_daily.parquet")
    b["date"] = pd.to_datetime(b["date"]).dt.tz_localize(None)
    bond = b[b["code"] == "H11006"].set_index("date")["close"].pct_change().reindex(ret.index)
    w = build_daily_weights(dc, rv, ret.index, PortfolioSpec(2, 4, "combined"), START, END)
    r = portfolio_returns(w, ret)
    r = r[r.index >= START]
    bond = bond.reindex(r.index)
    _, state = run_timing_overlay(d_ar, r, bond, TH)
    st = state.clip(0, 1)

    tip = pd.read_parquet(RAW / "tip_daily.parquet")
    tip["date"] = pd.to_datetime(tip["date"])
    tp = tip.set_index("date")["close"].sort_index()
    tp.index = tp.index.astype("datetime64[ns]")
    tsc = pd.concat([tp / tp.shift(d) - 1 for d in (28, 84, 168, 364)], axis=1).mean(axis=1)
    tg = pd.Series(np.where(tsc > 0, 1.0, 0.0), index=tp.index)
    tg[tsc.isna()] = np.nan
    mt = pd.merge_asof(pd.DataFrame({"date": ret.index}), tg.dropna().rename("tip").reset_index(),
                       on="date", direction="backward", allow_exact_matches=False).set_index("date")
    tip_gate = mt["tip"].shift(1).reindex(r.index).fillna(0.0)
    base = st * tip_gate

    money = pd.read_parquet(CMS / "macro_money.parquet")
    money["stat_month"] = pd.to_datetime(money["stat_month"])
    money = money.set_index("stat_month").sort_index()
    sci = (money["m1_yoy"] - money["m2_yoy"]).shift(1)       # 公布滞后一月
    s3 = sci.diff(3)
    z = (s3 - s3.rolling(36).mean()) / s3.rolling(36).std(ddof=1)
    z_d = z.reindex(r.index, method="ffill")

    gate = (z_d > 0).astype(float)
    soft30 = 0.3 + 0.7 / (1 + np.exp(-z_d))
    soft50 = 0.5 + 0.5 / (1 + np.exp(-z_d))
    gate_soft = np.where(z_d < -1, 0.0, 0.3 + 0.7 / (1 + np.exp(-z_d)))
    print(f"z 覆盖 {z.notna().sum()} 个月｜闸开 {gate.mean():.1%}｜"
          f"软30 均值 {soft30.mean():.2f}｜软50 均值 {soft50.mean():.2f}｜"
          f"闸+软 均值 {np.nanmean(gate_soft):.2f}")

    rows, navs = [], {}
    cases = [
        ("① 基线 ΔAR×TIP", base),
        ("② 硬闸（z>0 才持有）", base * gate),
        ("③ 软性分 floor=0.3", base * soft30),
        ("④ 软性分 floor=0.5", base * soft50),
        ("⑤ 闸+软性分（z<-1 硬切）", base * pd.Series(gate_soft, index=r.index)),
    ]
    for label, eq in cases:
        eq = eq.fillna(0.0).clip(0, 1)
        rr = eq * r + (1 - eq) * bond
        m = metrics(rr.dropna())
        rows.append({"variant": label, "avg_equity": round(float(eq.mean()), 3),
                     "annual_return": round(m["annual_return"], 4),
                     "annual_vol": round(m["annual_vol"], 4), "sharpe": round(m["sharpe"], 4),
                     "max_drawdown": round(m["max_drawdown"], 4),
                     "calmar": round(m["calmar"], 4)})
        navs[label] = nav_curve(rr.dropna())
    t = pd.DataFrame(rows).sort_values("sharpe", ascending=False)
    t.to_csv(OUT / "soft_score_macro.csv", index=False)
    pd.DataFrame(navs).to_csv(OUT / "soft_score_macro_nav.csv")
    print(t.to_string(index=False))
    (OUT / "soft_score_macro_summary.json").write_text(json.dumps({
        "window": [START, END],
        "signal": "M1-M2 剪刀差 3 个月变化，z 用过去 36 个月标准化，公布滞后一月",
        "hypotheses": {"H1": "软性分优于硬闸", "H2": "尾部硬切+中间软缩放优于两者",
                       "H3": "软性分与 ΔAR×TIP 重叠，增量有限"},
        "results": t.to_dict(orient="records"),
    }, ensure_ascii=False, indent=2, default=float), encoding="utf-8")


if __name__ == "__main__":
    main()
