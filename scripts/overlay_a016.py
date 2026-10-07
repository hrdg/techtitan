"""在研报设置（10 行业高集中度高估值轮动）上叠加 A016 择时。

A016 口径取自 择时策略/sentiment/execution/exposure_map.py：
    exp = min(1.5, 3·s)⁺ + min(s, 0)   （多头最高 1.5 倍杠杆，空头不杠杆）
生产执行序列：择时策略/output/e247_lev_sig_daily.csv（IC/IF/IM/IH 四腿）。

映射到研报组合（纯多头、无杠杆、只在国内行业指数与国债之间切换）：
    股票权重 = clip(exp, 0, 1)   → 负敞口视为 0（不融券），>1 截断为 1（不加杠杆）
    其余权重进国债指数。
全窗口只能用 IC 腿：IM（中证1000）期货 2022-07 才上市。
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
START, END = "2017-01-01", "2026-07-31"
TH = 1.5
LEGS = ["IC", "IF", "IM", "IH"]


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
    _, state = run_timing_overlay(d_ar, r, r * 0.0, TH)      # ΔAR 状态（1=股票）

    a = pd.read_csv(A016_CSV)
    a["date"] = pd.to_datetime(a["date"])
    a = a.set_index("date")
    a016 = a[[c for c in LEGS if c in a.columns]].reindex(r.index)
    print("A016 覆盖:", a016.notna().any(axis=1).sum(), "/", len(r),
          "| 各腿可用起始:", {c: str(a016[c].first_valid_index().date()) for c in a016.columns})
    print("时点口径: e247 存的是 T 日信号；生产回测用 exp.shift(2)（T 日收盘信号 → T+1 9:31 成交，"
          "close-to-close 需滞后两日）。下表同时给出 shift1（乐观上界）与 shift2（生产口径）。")

    b = pd.read_parquet(RAW / "benchmark_csi_daily.parquet")
    b["date"] = pd.to_datetime(b["date"]).dt.tz_localize(None)
    bond = b[b["code"] == "H11006"].set_index("date")["close"].reindex(r.index).pct_change()

    def overlay(exp_raw: pd.Series, gate: pd.Series | None = None) -> tuple[pd.Series, pd.Series]:
        """A016 敞口 → 股票权重（长仓截断到 [0,1]），其余进国债。"""
        eqw = exp_raw.clip(lower=0.0, upper=1.0).fillna(0.0)
        if gate is not None:
            eqw = eqw * gate.clip(0.0, 1.0)
        return eqw * r + (1 - eqw) * bond, eqw

    COST_BP = 5e-4          # 与 A016 生产口径一致：万五单边，按 |Δ股权权重| 计

    def with_cost(rr: pd.Series, eqw: pd.Series) -> pd.Series:
        return rr - COST_BP * eqw.diff().abs().fillna(0.0)

    variants = {}
    variants["研报原生：组合+ΔAR(1.5)"] = (r * state + bond * (1 - state), state)
    variants["组合（无择时）"] = (r, pd.Series(1.0, index=r.index))
    for leg in ["IC", "IF"]:
        if leg not in a016:
            continue
        for sh in (1, 2):
            exp_s = a016[leg].shift(sh)
            tag = "shift1(乐观)" if sh == 1 else "shift2(生产)"
            ret_a, eqw = overlay(exp_s)
            variants[f"组合+A016({leg})替代·{tag}"] = (ret_a, eqw)
            variants[f"组合+A016({leg})替代·{tag}+成本"] = (with_cost(ret_a, eqw), eqw)
            ret_b, eqw2 = overlay(exp_s, state)
            variants[f"组合+ΔAR×A016({leg})·{tag}"] = (ret_b, eqw2)

    rows, navs = [], {}
    for k, (rr, ew) in variants.items():
        m = metrics(rr.dropna())
        oos = rr[rr.index >= "2025-01-01"]
        m_oos = metrics(oos.dropna())
        rows.append({
            "variant": k,
            "avg_equity_weight": round(float(ew.mean()), 3),
            "annual_return": round(m["annual_return"], 4),
            "annual_vol": round(m["annual_vol"], 4),
            "sharpe": round(m["sharpe"], 4),
            "max_drawdown": round(m["max_drawdown"], 4),
            "calmar": round(m["calmar"], 4),
            "oos_annual": round(m_oos["annual_return"], 4),
            "oos_sharpe": round(m_oos["sharpe"], 4),
            "oos_mdd": round(m_oos["max_drawdown"], 4),
        })
        navs[k] = nav_curve(rr.dropna())
    t = pd.DataFrame(rows).sort_values("sharpe", ascending=False)
    t.to_csv(OUT / "a016_overlay_comparison.csv", index=False)
    pd.DataFrame(navs).to_csv(OUT / "a016_overlay_nav.csv")
    print()
    print(t.to_string(index=False))

    # 信号互补性
    ic = a016["IC"].clip(0, 1)
    both = ((state > 0.5) & (ic > 0)).mean()
    only_dar = ((state > 0.5) & (ic == 0)).mean()
    only_a016 = ((state <= 0.5) & (ic > 0)).mean()
    neither = ((state <= 0.5) & (ic == 0)).mean()
    print(f"\nΔAR 与 A016(IC) 的日度组合: 两者都持股票 {both:.1%} | 只 ΔAR {only_dar:.1%} | "
          f"只 A016 {only_a016:.1%} | 都空仓 {neither:.1%}")
    print(f"IC 敞口均值 {ic.mean():.3f} | ΔAR 持股票占比 {(state > 0.5).mean():.1%}")

    # 信号归因：按两个信号的开关状态分组，看组合原始收益
    ic_on = a016["IC"].clip(0, 1).fillna(0.0).shift(1) > 0     # 与 shift1 对齐的"开/关"
    dar_on = state > 0.5
    buckets = {
        "两者都开": (dar_on & ic_on), "只 ΔAR 开": (dar_on & ~ic_on),
        "只 A016 开": (~dar_on & ic_on), "两者都关": (~dar_on & ~ic_on),
    }
    print("\n组合原始日收益（不含国债腿）在四象限的表现:")
    print("%-12s %6s %10s %10s %10s" % ("象限", "天数", "日均", "年化", "胜率"))
    attr = {}
    for k, msk in buckets.items():
        sub = r[msk.reindex(r.index).fillna(False)]
        if len(sub) == 0:
            continue
        attr[k] = {"days": int(len(sub)), "mean_daily": round(float(sub.mean()), 5),
                   "annualized": round(float((1 + sub).prod() ** (250 / len(sub)) - 1), 4),
                   "win_rate": round(float((sub > 0).mean()), 4)}
        print("%-12s %6d %9.3f%% %9.1f%% %9.1f%%" % (k, len(sub), sub.mean() * 100,
              attr[k]["annualized"] * 100, attr[k]["win_rate"] * 100))
    # A016 敞口日均变化（换手）
    turn = a016["IC"].clip(0, 1).fillna(0.0).shift(2).diff().abs().mean()
    print(f"\nA016(IC) 股权权重日均绝对变化 {turn:.4f} → 年化换手 {turn * 250:.1f}，"
          f"按万五单边年化成本约 {turn * 250 * COST_BP:.2%}")

    (OUT / "a016_overlay_summary.json").write_text(json.dumps({
        "a016_source": str(A016_CSV), "a016_rule": "exp = min(1.5, 3s)+ + min(s,0); 多头截断到 [0,1]",
        "note": "IC 腿用于全窗口（IM 期货 2022-07 才上市）；其余权重进国债指数 H11006",
        "results": t.to_dict(orient="records"),
        "signal_overlap": {"both_equity": round(float(both), 4), "only_dar": round(float(only_dar), 4),
                           "only_a016": round(float(only_a016), 4), "neither": round(float(neither), 4)},
        "signal_attribution": attr,
        "a016_daily_turnover": round(float(turn), 4),
    }, ensure_ascii=False, indent=2), encoding="utf-8")


if __name__ == "__main__":
    main()
