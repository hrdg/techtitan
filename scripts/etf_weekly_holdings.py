"""把「高集中度高估值 + ΔAR 择时(1.5)」落到 ETF 载体，统计周频持仓只数。

这是 baseline 的**扩展变体**（研报为月频），不是原策略本身。
ETF 映射：申万二级行业 → 首选 ETF；缺二级 ETF 的行业用同链条 L1/兄弟二级 ETF 代理，并标注。
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
    portfolio_returns,
    relative_valuation,
    run_timing_overlay,
)
from tech_rotation.backtest import period_first_trading_days  # noqa: E402

RAW = ROOT / "data" / "raw"
OUT = ROOT / "results"
START, END = "2017-01-01", "2026-07-31"
THRESHOLD = 1.5

# 申万二级行业 -> ETF（首选）；source 标注直接跟踪还是代理
ETF_MAP = {
    "801081": ("512480.XSHG", "半导体ETF（中证全指半导体）", "直接"),
    "801085": ("159732.XSHE", "消费电子ETF", "直接"),
    "801737": ("159755.XSHE", "电池ETF（国证新能源车电池）", "直接"),
    "801735": ("515790.XSHG", "光伏ETF（中证光伏产业）", "直接"),
    "801745": ("512660.XSHG", "军工ETF（中证军工，一级行业代理）", "代理"),
    "801101": ("159998.XSHE", "计算机ETF（中证计算机，一级行业代理）", "代理"),
    "801103": ("159852.XSHE", "软件ETF（中证软件服务，兄弟二级代理）", "代理"),
    "801102": ("515880.XSHG", "通信ETF（中证全指通信设备）", "直接"),
    "801093": ("159565.XSHE", "汽车零部件ETF（中证全指汽车零部件）", "直接"),
    "801078": ("159530.XSHE", "机器人ETF（中证机器人/自动化设备代理）", "代理"),
}
BOND_ETF = ("511010.XSHG", "国债ETF（上证5年期国债）")


def main() -> None:
    df = pd.read_parquet(RAW / "industry_panel_final.parquet")
    df["date"] = pd.to_datetime(df["date"]).dt.tz_localize(None)
    ret = df.pivot(index="date", columns="code", values="ret")
    pb = df.pivot(index="date", columns="code", values="pb")
    fmv = df.pivot(index="date", columns="code", values="float_mv")

    ar, conc = absorption_and_concentration(ret, fmv)
    dc = delta_zscore(conc)
    d_ar = delta_zscore(ar)
    rv = relative_valuation(pb)

    b = pd.read_parquet(RAW / "benchmark_csi_daily.parquet")
    b["date"] = pd.to_datetime(b["date"]).dt.tz_localize(None)
    bond = b[b["code"] == "H11006"].set_index("date")["close"].reindex(ret.index).pct_change()

    rows = []
    summary = {}
    for freq, label in [("M", "月频（研报原口径）"), ("W", "周频")]:
        w = build_daily_weights(dc, rv, ret.index, PortfolioSpec(2, 4, "combined"),
                                START, END, freq=freq)
        r = portfolio_returns(w, ret)
        r = r[r.index >= START]
        timed, state = run_timing_overlay(d_ar, r, bond.reindex(r.index), THRESHOLD)
        m = metrics(timed)
        m_raw = metrics(r)
        held = w[w.index >= START]
        n_ind = (held > 0).sum(axis=1)
        n_ind = n_ind[n_ind.index.isin(state.index)]
        risk_off = (state <= 0.5)
        n_legs = np.where(risk_off, 1, n_ind)          # 风险规避期只持 1 只国债 ETF
        # 每次调仓当日的只数（周期首个交易日）
        rebal_days = period_first_trading_days(held.index, freq)
        per_rebal = n_ind.reindex(rebal_days).dropna()
        rebal_dist = {str(int(k)): int(v) for k, v in per_rebal.value_counts().sort_index().items()}
        summary[freq] = {
            "label": label,
            "annual_return": round(m["annual_return"], 4),
            "max_drawdown": round(m["max_drawdown"], 4),
            "sharpe": round(m["sharpe"], 4),
            "calmar": round(m["calmar"], 4),
            "no_timing_annual": round(m_raw["annual_return"], 4),
            "risk_off_share": round(float(risk_off.mean()), 4),
            "industry_count_dist": {str(int(k)): int(v) for k, v in n_ind.value_counts().sort_index().items()},
            "legs_count_dist": {str(int(k)): int(v) for k, v in pd.Series(n_legs).value_counts().sort_index().items()},
            "rebalance_count": int(len(per_rebal)),
            "industries_per_rebalance_dist": rebal_dist,
            "mean_industries_per_rebalance": round(float(per_rebal.mean()), 3),
            "max_min_industries": [int(per_rebal.max()), int(per_rebal.min())],
        }
        rows.append(pd.DataFrame({"freq": freq, "date": n_ind.index, "n_industry_etf": n_ind.values,
                                  "risk_off": risk_off.values, "n_legs": n_legs}).set_index(["freq", "date"]))
    pd.concat(rows).to_csv(OUT / "etf_holdings_counts.csv")

    # 实际用到的 ETF 清单
    used = {}
    for freq in ("M", "W"):
        w = build_daily_weights(dc, rv, ret.index, PortfolioSpec(2, 4, "combined"),
                                START, END, freq=freq)
        used[freq] = sorted({c for c in w.columns if w[c].sum() > 0})
    etf_list = {c: {"etf": ETF_MAP[c][0], "name": ETF_MAP[c][1], "tracking": ETF_MAP[c][2]} for c in used["W"]}

    res = {
        "strategy": "高集中度高估值 + ΔAR 择时（threshold=1.5）",
        "note": "月频为研报口径；周频是本复现的扩展变体，非研报原策略",
        "bond_leg": {"etf": BOND_ETF[0], "name": BOND_ETF[1]},
        "industries_held_at_weekly": used["W"],
        "etf_mapping": etf_list,
        "summary": summary,
    }
    (OUT / "etf_weekly_holdings.json").write_text(json.dumps(res, ensure_ascii=False, indent=2), encoding="utf-8")

    for freq, s in summary.items():
        print(f"=== {s['label']} ===")
        print(f"  年化 {s['annual_return']:.2%} | 回撤 {s['max_drawdown']:.2%} | 夏普 {s['sharpe']:.2f} "
              f"| 卡玛 {s['calmar']:.2f} | 无择时年化 {s['no_timing_annual']:.2%}")
        print(f"  国债仓位占比 {s['risk_off_share']:.1%} | 调仓次数 {s['rebalance_count']} | "
              f"每次平均持仓行业数 {s['mean_industries_per_rebalance']}")
        print(f"  每次调仓买入选中的行业只数: {s['industries_per_rebalance_dist']}")
        print(f"  持有行业 ETF 只数分布（按交易日）: {s['industry_count_dist']}")
        print(f"  含国债腿的实际持仓只数分布（按交易日）: {s['legs_count_dist']}")
    print("\n周频用到的行业 ETF:", [f"{c}→{ETF_MAP[c][0]}({ETF_MAP[c][2]})" for c in used["W"]])


if __name__ == "__main__":
    main()
