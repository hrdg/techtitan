"""给月频选行业加一个"综合动量"因子（借鉴 HA_EXT22_12M_MONTHLY_IC_TOP2_VOL20 的语义）。

本机没有该标签的原文，按同项目已文档化的口径实现等价版本：
- 12 个月动量：close_t / close_{t-252} - 1（截面排名，越大越好）
- VOL20 过滤：剔除 20 日年化波动处于截面最高的 30%
- 选法对照：
  T1 三因子取交集（RV 前2 ∩ ΔC 前4 ∩ 动量前4）
  T2 动量只做门槛（RV 前2 ∩ ΔC 前4，但剔除动量后 30%）
  T3 综合打分（ΔC、RV、动量三者排名均值，取前 2）
  T4 动量+低波（动量前 2 且波动不在最高 30%）
信号日收盘确认、次月首个交易日执行；择时沿用 ΔAR(1.5)。
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
START, END, TH = "2017-01-03", "2026-10-30", 1.5


def monthly_weights(dates, select):
    """select(date)->list[code]；返回每日等权权重（次月首个交易日生效）。"""
    s = pd.Series(dates, index=dates)
    me = pd.DatetimeIndex(s.groupby([dates.year, dates.month]).last().values)
    first = pd.DatetimeIndex(s.groupby([dates.year, dates.month]).first().values)
    w = pd.DataFrame(0.0, index=dates, columns=ALL)
    cur: list[str] = []
    for d in first:
        prior = me[me < d]
        if len(prior) == 0:
            continue
        sel = select(prior[-1])
        if sel:
            cur = sel
        if cur:
            w.loc[d:] = 0.0
            w.loc[d:, cur] = 1.0 / len(cur)
    return w


def main() -> None:
    global ALL
    df = pd.read_parquet(RAW / "industry_panel_latest.parquet")
    df["date"] = pd.to_datetime(df["date"]).dt.tz_localize(None)
    close = df.pivot(index="date", columns="code", values="close") if "close" in df.columns else None
    ret = df.pivot(index="date", columns="code", values="ret")
    pb = df.pivot(index="date", columns="code", values="pb")
    fmv = df.pivot(index="date", columns="code", values="float_mv")
    ALL = list(ret.columns)
    # 用收益累计构造行业指数（面板没有 close 列）
    level = (1 + ret.fillna(0)).cumprod()
    mom = level / level.shift(252) - 1                      # 12 个月动量
    vol20 = ret.rolling(20).std(ddof=1) * np.sqrt(250)
    ar, conc = absorption_and_concentration(ret, fmv)
    dc, rv, d_ar = delta_zscore(conc), relative_valuation(pb), delta_zscore(ar)
    b = pd.read_parquet(RAW / "benchmark_csi_daily.parquet")
    b["date"] = pd.to_datetime(b["date"]).dt.tz_localize(None)
    bond_all = b[b["code"] == "H11006"].set_index("date")["close"].pct_change()

    def top(s: pd.Series, k: int) -> list[str]:
        return list(s.dropna().nlargest(k).index)

    def rule_intersect(t):
        d, r, m = dc.loc[t].dropna(), rv.loc[t].dropna(), mom.loc[t].dropna()
        if d.empty or r.empty or m.empty:
            return []
        return sorted(set(top(d, 4)) & set(top(r, 2)) & set(top(m, 4)))

    def rule_mom_gate(t):
        d, r, m = dc.loc[t].dropna(), rv.loc[t].dropna(), mom.loc[t].dropna()
        if d.empty or r.empty or m.empty:
            return []
        cut = m.quantile(0.30)
        keep = [c for c in d.index if c in r.index and m.get(c, -np.inf) >= cut]
        d, r = d[d.index.isin(keep)], r[r.index.isin(keep)]
        if d.empty or r.empty:
            return []
        return sorted(set(top(d, 4)) & set(top(r, 2)))

    def rule_score(t):
        d, r, m = dc.loc[t].dropna(), rv.loc[t].dropna(), mom.loc[t].dropna()
        idx = sorted(set(d.index) & set(r.index) & set(m.index))
        if not idx:
            return []
        score = (d[idx].rank(ascending=False) + r[idx].rank(ascending=False)
                 + m[idx].rank(ascending=False))
        return list(score.nsmallest(2).index)

    def rule_mom_lowvol(t):
        m, v = mom.loc[t].dropna(), vol20.loc[t].dropna()
        idx = [c for c in m.index if c in v.index]
        if not idx:
            return []
        lo = v[idx].quantile(0.70)
        keep = [c for c in idx if v[c] <= lo]
        return top(m[keep], 2) if keep else []

    rows, navs = [], {}
    def run(label, select):
        w = monthly_weights(ret.index, select)
        r = portfolio_returns(w, ret)
        r = r[r.index >= START]
        bond = bond_all.reindex(r.index)
        timed, _ = run_timing_overlay(d_ar, r, bond, TH)
        m = metrics(timed.dropna())
        rows.append({"variant": label, "annual_return": round(m["annual_return"], 4),
                     "annual_vol": round(m["annual_vol"], 4), "sharpe": round(m["sharpe"], 4),
                     "max_drawdown": round(m["max_drawdown"], 4), "calmar": round(m["calmar"], 4)})
        navs[label] = nav_curve(timed.dropna())

    def rule_base(t):
        d, r = dc.loc[t].dropna(), rv.loc[t].dropna()
        if d.empty or r.empty:
            return []
        return sorted(set(top(d, 4)) & set(top(r, 2)))

    run("① 基准：ΔC∩RV", rule_base)
    run("② 三因子交集（+动量前4）", rule_intersect)
    run("③ 动量门槛（剔除动量后30%）", rule_mom_gate)
    run("④ 综合打分（三因子排名均值）", rule_score)
    run("⑤ 动量前2+低波（VOL20）", rule_mom_lowvol)
    t = pd.DataFrame(rows).sort_values("sharpe", ascending=False)
    t.to_csv(OUT / "momentum_factor_comparison.csv", index=False)
    pd.DataFrame(navs).to_csv(OUT / "momentum_factor_nav.csv")
    print(f"窗口 {START} ~ {END}")
    print(t.to_string(index=False))
    print(f"\n动量可用起点 {mom.dropna(how='all').index.min().date()}；"
          f"20 日波动可用起点 {vol20.dropna(how='all').index.min().date()}")
    (OUT / "momentum_factor_summary.json").write_text(json.dumps({
        "window": [START, END],
        "momentum": "12 个月（252 日）收益率，截面排名",
        "vol_filter": "VOL20：剔除截面波动最高 30%",
        "note": "HA_EXT22 标签本机无原文，按同项目 12M/月频/Top2/VOL20 语义实现等价版本，IC 赋权未复刻",
        "results": t.to_dict(orient="records"),
    }, ensure_ascii=False, indent=2, default=float), encoding="utf-8")


if __name__ == "__main__":
    main()
