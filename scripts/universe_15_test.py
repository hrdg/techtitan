"""对比：研报 10 个科技行业 vs 加入 5 个"科技上游"资源行业后的 15 行业宇宙。

资源类：稀有金属(801054, 稀土)、工业金属(801055, 铜铝)、能源金属(801056, 锂钴)、
        非金属材料(801039, 硅/石英)、电子化学品(801086, 半导体材料)。
k1/k2 按相对分位换算：10 个里前 2/前 4 = 20%/40% → 15 个里 = 3/6；同时给出不换算的 (2,4)。
ΔAR 阈值保持 1.5（其标准化后跨截面规模可迁移，已单独实测）。
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
START, END, TH = "2017-01-01", "2026-07-31", 1.5
RESOURCE = {"801054": "稀有金属", "801055": "工业金属", "801056": "能源金属",
            "801039": "非金属材料", "801086": "电子化学品"}


def load(path: str):
    df = pd.read_parquet(RAW / path)
    df["date"] = pd.to_datetime(df["date"]).dt.tz_localize(None)
    ret = df.pivot(index="date", columns="code", values="ret")
    pb = df.pivot(index="date", columns="code", values="pb")
    fmv = df.pivot(index="date", columns="code", values="float_mv")
    return ret, pb, fmv, df.drop_duplicates("code").set_index("code")["name"].to_dict()


def load_subset(path: str, keep: set[str]):
    ret, pb, fmv, names = load(path)
    cols = [c for c in ret.columns if c in keep]
    return ret[cols], pb[cols], fmv[cols], {c: names[c] for c in cols}


def main() -> None:
    b = pd.read_parquet(RAW / "benchmark_csi_daily.parquet")
    b["date"] = pd.to_datetime(b["date"]).dt.tz_localize(None)
    bond_all = b[b["code"] == "H11006"].set_index("date")["close"].pct_change()

    rows, navs, detail = [], {}, {}
    cases = [
        ("U10 研报（10 科技，k=2/4）", "industry_panel_final.parquet", 2, 4, 2),
        ("U15（15 行业，k=2/4 不换算）", "industry_panel_final_15.parquet", 2, 4, 2),
        ("U15（15 行业，k=3/6 分位换算）", "industry_panel_final_15.parquet", 3, 6, 2),
        ("U15（15 行业，k=3/6，m=3）", "industry_panel_final_15.parquet", 3, 6, 3),
        ("U12（10 科技 + 稀有金属 + 工业金属，k=2/5）", "industry_panel_final_15.parquet", 2, 5, 2),
        ("U12b（10 科技 + 3 个薄资源，k=2/5）", "industry_panel_final_15.parquet", 2, 5, 2),
    ]
    THICK = {"801054", "801055"}
    THIN = {"801056", "801039", "801086"}
    TECH10 = {"801081", "801085", "801737", "801735", "801745", "801101",
              "801103", "801102", "801093", "801078"}
    for label, path, k1, k2, m in cases:
        if label.startswith("U12（"):
            ret, pb, fmv, names = load_subset(path, TECH10 | THICK)
        elif label.startswith("U12b"):
            ret, pb, fmv, names = load_subset(path, TECH10 | THIN)
        else:
            ret, pb, fmv, names = load(path)
        ar, conc = absorption_and_concentration(ret, fmv, m=m)
        dc, d_ar = delta_zscore(conc), delta_zscore(ar)
        rv = relative_valuation(pb)
        w = build_daily_weights(dc, rv, ret.index, PortfolioSpec(k1, k2, "combined"), START, END)
        r = portfolio_returns(w, ret)
        r = r[r.index >= START]
        bond = bond_all.reindex(r.index)
        m_raw = metrics(r)
        timed, state = run_timing_overlay(d_ar, r, bond, TH)
        m_td = metrics(timed)
        oos = metrics(timed[timed.index >= "2025-01-01"])
        rows.append({"case": label, "n_assets": ret.shape[1], "m": m,
                     "no_timing_ann": round(m_raw["annual_return"], 4),
                     "no_timing_mdd": round(m_raw["max_drawdown"], 4),
                     "timed_ann": round(m_td["annual_return"], 4),
                     "timed_vol": round(m_td["annual_vol"], 4),
                     "timed_sharpe": round(m_td["sharpe"], 4),
                     "timed_mdd": round(m_td["max_drawdown"], 4),
                     "timed_calmar": round(m_td["calmar"], 4),
                     "oos_ann": round(oos["annual_return"], 4),
                     "oos_sharpe": round(oos["sharpe"], 4),
                     "risk_off_share": round(float((state <= 0.5).mean()), 4),
                     "ar_mean": round(float(ar.dropna().mean()), 4)})
        navs[label] = nav_curve(timed.dropna())
        # 资源类被选中的频率 + 持仓明细
        held = w[w.index >= START]
        sel = (held > 0)
        share = {c: round(float(sel[c].mean()), 3) for c in sel.columns}
        detail[label] = {"perp_industry_holding_share": share,
                         "resource_share_total": round(float(sum(
                             v for c, v in share.items() if c in RESOURCE)), 3)}
        if "U15（15 行业，k=3/6 分位换算）" == label:
            log = held.apply(lambda s: "、".join(names[c] for c in s[s > 0].index), axis=1)
            log = log[log.ne(log.shift())]
            detail[label]["holdings_changes"] = [[str(d.date()), v] for d, v in log.items()]

    t = pd.DataFrame(rows)
    t.to_csv(OUT / "universe_15_comparison.csv", index=False)
    pd.DataFrame(navs).to_csv(OUT / "universe_15_nav.csv")
    print(t.to_string(index=False))
    print("\n资源类行业在持仓中的时间占比:")
    for label, d in detail.items():
        if d["resource_share_total"] > 0:
            rs = {c: v for c, v in d["perp_industry_holding_share"].items() if c in RESOURCE and v > 0}
            print(f"  {label}: 合计 {d['resource_share_total']:.1%} {rs}")
    key = "U15（15 行业，k=3/6 分位换算）"
    print(f"\n{key} 持仓变化（近 12 次）:")
    for d, v in detail[key]["holdings_changes"][-12:]:
        print("   ", d, v)
    (OUT / "universe_15_summary.json").write_text(json.dumps({
        "resource_industries": RESOURCE, "results": t.to_dict(orient="records"),
        "selection_detail": {k: {kk: vv for kk, vv in v.items() if kk != "holdings_changes"}
                             for k, v in detail.items()},
        "holdings_changes_u15": detail[key]["holdings_changes"],
    }, ensure_ascii=False, indent=2, default=float), encoding="utf-8")


if __name__ == "__main__":
    main()
