"""主题（行业/主题 ETF 篮子）上的变体：集中度因子 ΔC + A016(IC) 择时。

限制（必须随结果一起读）：主题横截面**没有可信的行业级 PB/流通市值**，因此相对估值
因子 RV 无法复现，这里是**单因子（集中度）版本**；ETF 也没有行业流通市值，PCA 只做
半衰期衰减加权、不做 √市值加权。样本自 2021-07 起（篮子内 ETF 全部上市）。
"""
from __future__ import annotations

import glob
import json
import os
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
    run_timing_overlay,
)

ETF_DIR = Path(os.environ.get("SW_ETF_CACHE_DIR", "/Users/hsh/Documents/Quant/行业轮动/data/raw/local_cache/etf"))
MAP_CSV = Path(os.environ.get("SW_ETF_MAP_CSV", "/Users/hsh/Documents/Quant/行业轮动/data/raw/timing17_etf_map/etf_industry_map.csv"))
RAW = ROOT / "data" / "raw"
OUT = ROOT / "results"
A016_CSV = Path(os.environ.get("A016_SIG_CSV", "/Users/hsh/Documents/Quant/择时策略/output/e247_lev_sig_daily.csv"))
START, TH, SHIFT, COST = "2021-07-01", 1.5, 2, 5e-4

EXCLUDE = {"511010", "511030", "511220", "511880", "510050", "510300", "510310", "510330",
           "510500", "510580", "512100", "588000", "588090", "159915", "159919", "159949",
           "510100", "512500", "159935", "159907", "510060", "510010", "510880", "513100",
           "518880", "159981", "159985", "159980", "161226", "515180", "512750", "512950",
           "512890", "159959", "159967"}


def main() -> None:
    name_map = (pd.read_csv(MAP_CSV).assign(c=lambda d: d["code"].str.split(".").str[0])
                .drop_duplicates("c").set_index("c")["name"].to_dict())
    frames = {}
    for f in sorted(glob.glob(str(ETF_DIR / "*.csv"))):
        code = os.path.basename(f).split(".")[0]
        if code in EXCLUDE:
            continue
        s = pd.read_csv(f)
        dcol = [c for c in s.columns if c.lower() in ("date", "日期")][0]
        ccol = [c for c in s.columns if c.lower() in ("close", "收盘")][0]
        s = s[[dcol, ccol]].rename(columns={dcol: "date", ccol: "close"})
        s["date"] = pd.to_datetime(s["date"])
        s = s.set_index("date")["close"]
        if len(s) < 100 or s.index.min() > pd.Timestamp(START) or s.index.max() < pd.Timestamp("2026-07-01"):
            continue
        frames[code] = s
    px = pd.DataFrame(frames).sort_index().ffill().loc[START:"2026-07-31"]
    keep = px.columns[px.notna().mean() > 0.98]
    px = px[keep]
    ret = px.pct_change()
    print(f"主题 ETF 篮子: {len(keep)} 只, {ret.index.min().date()}~{ret.index.max().date()}")
    print("  含:", ", ".join(f"{c}({name_map.get(c, '?')})" for c in list(keep)[:10]), "...")

    mv = pd.DataFrame(100.0, index=ret.index, columns=ret.columns)
    ar, conc = absorption_and_concentration(ret, mv, m=2, use_mktcap=False, use_decay=True)
    dc, d_ar = delta_zscore(conc), delta_zscore(ar)
    n = len(keep)
    k2 = max(2, round(n * 0.4))
    print(f"仅集中度因子：k2={k2}（前 {k2/n:.0%}）")
    w = build_daily_weights(dc, pd.DataFrame(10.0, index=ret.index, columns=ret.columns),
                            ret.index, PortfolioSpec(k1=2, k2=k2, name="concentration"),
                            START, "2026-07-31")
    r = portfolio_returns(w, ret)
    r = r[r.index >= START]
    n_ind = (w[w.index >= START] > 0).sum(axis=1)

    b = pd.read_parquet(RAW / "benchmark_csi_daily.parquet")
    b["date"] = pd.to_datetime(b["date"]).dt.tz_localize(None)
    bond = b[b["code"] == "H11006"].set_index("date")["close"].reindex(r.index).pct_change()
    a = pd.read_csv(A016_CSV)
    a["date"] = pd.to_datetime(a["date"])
    eq_a = a.set_index("date")["IC"].reindex(r.index).shift(SHIFT).clip(0, 1).fillna(0.0)
    _, state = run_timing_overlay(d_ar, r, bond, TH)

    rows, navs = [], {}
    for k, eqw in {"无择时": pd.Series(1.0, index=r.index), "A016(IC)": eq_a, "ΔAR(1.5)": state}.items():
        eqw = eqw.clip(0, 1).fillna(0.0)
        rr = eqw * r + (1 - eqw) * bond
        rr = rr - COST * eqw.diff().abs().fillna(0.0)
        m = metrics(rr.dropna())
        oos = metrics(rr[rr.index >= "2025-01-01"].dropna())
        rows.append({"universe": f"主题ETF({n}只)", "timing": k,
                     "avg_equity": round(float(eqw.mean()), 3),
                     "annual_return": round(m["annual_return"], 4),
                     "annual_vol": round(m["annual_vol"], 4), "sharpe": round(m["sharpe"], 4),
                     "max_drawdown": round(m["max_drawdown"], 4), "calmar": round(m["calmar"], 4),
                     "oos_annual": round(oos["annual_return"], 4), "oos_sharpe": round(oos["sharpe"], 4),
                     "avg_holdings": round(float(n_ind.mean()), 2)})
        navs[k] = nav_curve(rr.dropna())
    ew = ret.mean(axis=1)
    m0 = metrics(ew.dropna())
    rows.append({"universe": f"主题ETF({n}只)", "timing": "篮子等权(基准)", "avg_equity": 1.0,
                 "annual_return": round(m0["annual_return"], 4), "annual_vol": round(m0["annual_vol"], 4),
                 "sharpe": round(m0["sharpe"], 4), "max_drawdown": round(m0["max_drawdown"], 4),
                 "calmar": round(m0["calmar"], 4),
                 "oos_annual": round(metrics(ew[ew.index >= "2025-01-01"])["annual_return"], 4),
                 "oos_sharpe": round(metrics(ew[ew.index >= "2025-01-01"])["sharpe"], 4),
                 "avg_holdings": np.nan})
    t = pd.DataFrame(rows)
    t.to_csv(OUT / "universe_variant_theme.csv", index=False)
    pd.DataFrame(navs).to_csv(OUT / "universe_variant_theme_nav.csv")
    print(t.to_string(index=False))
    (OUT / "universe_variant_theme.json").write_text(json.dumps({
        "universe": f"行业/主题 ETF 篮子（剔除宽基/债券/商品），{n} 只",
        "included": {c: name_map.get(c) for c in keep},
        "limitations": ["无行业级 PB 与流通市值 → 仅集中度单因子，缺相对估值因子 RV",
                        "PCA 仅做半衰期衰减加权，无 √市值加权",
                        f"样本自 {START}（篮子内 ETF 全部上市）起"],
        "results": t.to_dict(orient="records"),
    }, ensure_ascii=False, indent=2), encoding="utf-8")


if __name__ == "__main__":
    main()
