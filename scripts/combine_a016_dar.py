"""A016(IC) 与 ΔAR(1.5) 的结合方式对照。

预注册判据（先写后用）：以风险调整后效率（夏普、Calmar）为主判据，且不得让样本外
2025-01~2026-07 明显恶化；平均股票权重一并列出，避免用"少承担风险"冒充"信号更好"。
所有变体都按 A016 生产口径计万五单边成本、并按 shift(2) 对齐时点。
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
A016_CSV = Path(os.environ.get("A016_SIG_CSV", "/Users/hsh/Documents/Quant/择时策略/output/e247_lev_sig_daily.csv"))
START, END, TH, SHIFT, COST = "2017-01-01", "2026-07-31", 1.5, 2, 5e-4


def main() -> None:
    df = pd.read_parquet(RAW / "industry_panel_final.parquet")
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
    _, state = run_timing_overlay(d_ar, r, r * 0.0, TH)

    a = pd.read_csv(A016_CSV)
    a["date"] = pd.to_datetime(a["date"])
    exp = a.set_index("date")["IC"].reindex(r.index).shift(SHIFT)
    eq_a = exp.clip(0, 1).fillna(0.0)
    st = state.clip(0, 1)

    b = pd.read_parquet(RAW / "benchmark_csi_daily.parquet")
    b["date"] = pd.to_datetime(b["date"]).dt.tz_localize(None)
    bond = b[b["code"] == "H11006"].set_index("date")["close"].reindex(r.index).pct_change()

    print(f"无条件（全样本）组合日均收益 {r.mean():.3%}  → 四象限的参照线")
    print(f"A016 敞口均值 {eq_a.mean():.3f} | ΔAR 持股票占比 {st.mean():.1%}")

    def book(eqw: pd.Series, name: str) -> dict:
        eqw = eqw.clip(0, 1).fillna(0.0)
        rr = eqw * r + (1 - eqw) * bond
        rr = rr - COST * eqw.diff().abs().fillna(0.0)
        m = metrics(rr.dropna())
        oos = metrics(rr[rr.index >= "2025-01-01"].dropna())
        return {"variant": name, "avg_equity": round(float(eqw.mean()), 3),
                "annual_return": round(m["annual_return"], 4), "annual_vol": round(m["annual_vol"], 4),
                "sharpe": round(m["sharpe"], 4), "max_drawdown": round(m["max_drawdown"], 4),
                "calmar": round(m["calmar"], 4), "oos_annual": round(oos["annual_return"], 4),
                "oos_sharpe": round(oos["sharpe"], 4), "oos_mdd": round(oos["max_drawdown"], 4)}, rr

    schemes = {
        "① 只用 A016": eq_a,
        "② 只用 ΔAR(1.5)": st,
        "③ 相乘（当前）": eq_a * st,
        "④ 取并集 max": np.maximum(eq_a, st),
        "⑤ 等权平均": 0.5 * eq_a + 0.5 * st,
        "⑥ A016 + ΔAR 独占日半仓": eq_a + 0.5 * st * (1 - (eq_a > 0).astype(float)),
        "⑦ A016 + ΔAR 独占日全仓(≈OR)": eq_a + st * (1 - (eq_a > 0).astype(float)),
        "⑧ A016，ΔAR 仅在极端(>2.0)清仓": eq_a.where(d_ar.reindex(r.index) <= 2.0, 0.0),
        "⑨ A016，ΔAR 仅在极端(>1.75)清仓": eq_a.where(d_ar.reindex(r.index) <= 1.75, 0.0),
        "⑩ A016×ΔAR 软闸(1.0→1.5 线性)": eq_a * (1 - ((d_ar.reindex(r.index) - 1.0) / 0.5).clip(0, 1)),
    }
    rows, navs = [], {}
    for name, eqw in schemes.items():
        row, rr = book(eqw, name)
        rows.append(row)
        navs[name] = nav_curve(rr.dropna())
    t = pd.DataFrame(rows).sort_values("sharpe", ascending=False)
    t.to_csv(OUT / "combine_a016_dar.csv", index=False)
    pd.DataFrame(navs).to_csv(OUT / "combine_a016_dar_nav.csv")
    print()
    print(t.to_string(index=False))

    # 四象限 + 无条件均值
    ic_on = eq_a > 0
    dar_on = st > 0.5
    print("\n四象限（组合原始日收益，不含国债腿，参照线为无条件均值）:")
    attr = {}
    for k, msk in {"两者都开": dar_on & ic_on, "只 ΔAR 开": dar_on & ~ic_on,
                   "只 A016 开": ~dar_on & ic_on, "两者都关": ~dar_on & ~ic_on}.items():
        sub = r[msk.reindex(r.index).fillna(False)]
        attr[k] = {"days": int(len(sub)), "mean_daily": round(float(sub.mean()), 5),
                   "excess_vs_unconditional": round(float(sub.mean() - r.mean()), 5)}
        print(f"  {k:<10} n={len(sub):>4}  日均 {sub.mean():>7.3%}  "
              f"超额 {sub.mean() - r.mean():>7.3%}")
    (OUT / "combine_a016_dar_summary.json").write_text(json.dumps({
        "unconditional_mean_daily": round(float(r.mean()), 5),
        "criterion": "风险调整后效率为主判据，且样本外不得明显恶化；平均股票权重一并披露",
        "results": t.to_dict(orient="records"), "quadrants": attr,
    }, ensure_ascii=False, indent=2), encoding="utf-8")


if __name__ == "__main__":
    main()
