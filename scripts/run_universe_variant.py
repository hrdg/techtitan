"""把研报的双因子轮动（PCA 集中度 ΔC + 相对估值 RV）搬到任意横截面，择时用 A016(IC)。

用法: python scripts/run_universe_variant.py <panel.parquet> <名称> [m]
判据：k1/k2 沿用研报的横截面比例（前 20% / 前 40%）；择时对比 无择时 / A016(IC) / ΔAR(1.5)。
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


def naive(s):
    s = pd.to_datetime(s)
    if isinstance(s.dtype, pd.DatetimeTZDtype):
        s = s.dt.tz_convert("Asia/Shanghai").dt.tz_localize(None)
    return s.astype("datetime64[ns]")


def main() -> None:
    panel_path, name = Path(sys.argv[1]), sys.argv[2]
    m = int(sys.argv[3]) if len(sys.argv) > 3 else 2
    df = pd.read_parquet(panel_path)
    df["date"] = naive(df["date"])
    df["code"] = df["code"].astype(str)
    df = df.sort_values(["date", "code"])
    ret = df.pivot(index="date", columns="code", values="close").pct_change()
    pb = df.pivot(index="date", columns="code", values="pb")
    fmv = df.pivot(index="date", columns="code", values="float_mv_yi")
    rows_before = ret.shape[1]
    keep = [c for c in ret.columns
            if ret[c].loc[START:END].notna().mean() > 0.9 and pb[c].loc[START:END].notna().mean() > 0.3
            and (fmv[c].loc[START:END] > 0).mean() > 0.7]
    ret, pb, fmv = ret[keep], pb[keep], fmv[keep]
    n = len(keep)
    print(f"{name}: {n} 个行业可用（原始 {rows_before}），m={m}")
    if n < 5:
        print("样本不足，跳过"); return

    ar, conc = absorption_and_concentration(ret, fmv, m=m)
    dc, d_ar = delta_zscore(conc), delta_zscore(ar)
    rv = relative_valuation(pb)
    k1, k2 = max(2, round(n * 0.2)), max(2, round(n * 0.4))
    spec = PortfolioSpec(k1=k1, k2=k2, name="combined")
    print(f"k1={k1}（前 {k1/n:.0%}）/ k2={k2}（前 {k2/n:.0%}）")
    w = build_daily_weights(dc, rv, ret.index, spec, START, END)
    r = portfolio_returns(w, ret)
    r = r[r.index >= START]
    eqw_univ = ret.mean(axis=1)
    eqw_univ = eqw_univ[eqw_univ.index >= START]
    held = w[w.index >= START]
    n_ind = (held > 0).sum(axis=1)
    empty_share = float((n_ind == 0).mean())

    b = pd.read_parquet(RAW / "benchmark_csi_daily.parquet")
    b["date"] = naive(b["date"])
    bond = b[b["code"] == "H11006"].set_index("date")["close"].reindex(r.index).pct_change()
    a = pd.read_csv(A016_CSV)
    a["date"] = pd.to_datetime(a["date"])
    eq_a = a.set_index("date")["IC"].reindex(r.index).shift(SHIFT).clip(0, 1).fillna(0.0)
    _, state = run_timing_overlay(d_ar, r, bond, TH)

    def book(eqw: pd.Series) -> tuple[pd.Series, dict]:
        eqw = eqw.clip(0, 1).fillna(0.0)
        rr = eqw * r + (1 - eqw) * bond
        rr = rr - COST * eqw.diff().abs().fillna(0.0)
        return rr, metrics(rr.dropna())

    rows, navs = [], {}
    variants = {"无择时": pd.Series(1.0, index=r.index), "A016(IC)": eq_a, "ΔAR(1.5)": state}
    for k, eqw in variants.items():
        rr, mm = book(eqw)
        oos = metrics(rr[rr.index >= "2025-01-01"].dropna())
        rows.append({"universe": name, "n_industries": n, "m": m, "timing": k,
                     "avg_equity": round(float(eqw.mean()), 3),
                     "annual_return": round(mm["annual_return"], 4),
                     "annual_vol": round(mm["annual_vol"], 4),
                     "sharpe": round(mm["sharpe"], 4),
                     "max_drawdown": round(mm["max_drawdown"], 4),
                     "calmar": round(mm["calmar"], 4),
                     "oos_annual": round(oos["annual_return"], 4),
                     "oos_sharpe": round(oos["sharpe"], 4),
                     "avg_holdings": round(float(n_ind[n_ind.index >= START].mean()), 2),
                     "empty_holding_share": round(empty_share, 3)})
        navs[f"{name}·{k}"] = nav_curve(rr.dropna())
    mm0 = metrics(eqw_univ.dropna())
    rows.append({"universe": name, "n_industries": n, "m": m, "timing": "行业等权(基准)",
                 "avg_equity": 1.0, "annual_return": round(mm0["annual_return"], 4),
                 "annual_vol": round(mm0["annual_vol"], 4), "sharpe": round(mm0["sharpe"], 4),
                 "max_drawdown": round(mm0["max_drawdown"], 4), "calmar": round(mm0["calmar"], 4),
                 "oos_annual": round(metrics(eqw_univ[eqw_univ.index >= "2025-01-01"].dropna())["annual_return"], 4),
                 "oos_sharpe": round(metrics(eqw_univ[eqw_univ.index >= "2025-01-01"].dropna())["sharpe"], 4),
                 "avg_holdings": np.nan, "empty_holding_share": np.nan})
    t = pd.DataFrame(rows)
    tag = name.replace("/", "_")
    t.to_csv(OUT / f"universe_variant_{tag}.csv", index=False)
    pd.DataFrame(navs).to_csv(OUT / f"universe_variant_{tag}_nav.csv")
    print(t.to_string(index=False))
    (OUT / f"universe_variant_{tag}.json").write_text(json.dumps({
        "universe": name, "panel": str(panel_path), "n_industries": n, "m": m,
        "k1": k1, "k2": k2, "results": t.to_dict(orient="records"),
    }, ensure_ascii=False, indent=2), encoding="utf-8")


if __name__ == "__main__":
    main()
