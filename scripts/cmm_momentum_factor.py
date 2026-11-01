"""CMM（状态条件综合动量）在 10 个行业上的实现与对照。

口径（按 HA 项目文档）：
- 对每个市场状态变量 j，取过去 252 个交易日，按日期稳定等频分五箱 S1-S5；
- CMM[i,j,s] = 仅累计处于状态 s 的交易日的行业对数收益；
- 每个决策日选有效状态 S_j*：用过去 24 个月末的截面 IC（CMM 排名 vs 次月收益）取均值最大的状态，
  历史不足 6 期时回退到传统 MOM（对应“MOM 仅作基准与回退”的定位）；
- 综合分数 = 各状态变量 CMM 的截面排名均值。
对照：MOM（传统 12M）、CMM、CMM 作为第三因子接入 ΔC∩RV。
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
WIN, NQ = 252, 5


def main() -> None:
    df = pd.read_parquet(RAW / "industry_panel_latest.parquet")
    df["date"] = pd.to_datetime(df["date"]).dt.tz_localize(None)
    ret = df.pivot(index="date", columns="code", values="ret")
    pb = df.pivot(index="date", columns="code", values="pb")
    fmv = df.pivot(index="date", columns="code", values="float_mv")
    amt = df.pivot(index="date", columns="code", values="amount_wan")
    codes = list(ret.columns)
    logret = np.log1p(ret)
    ew = ret.mean(axis=1)
    level = (1 + ret.fillna(0)).cumprod()

    ar, conc = absorption_and_concentration(ret, fmv)
    dc, rv, d_ar = delta_zscore(conc), relative_valuation(pb), delta_zscore(ar)
    b = pd.read_parquet(RAW / "benchmark_csi_daily.parquet")
    b["date"] = pd.to_datetime(b["date"]).dt.tz_localize(None)
    bond_all = b[b["code"] == "H11006"].set_index("date")["close"].pct_change()

    # 市场状态变量（日频，全体行业共享）
    mkt_amt = amt.sum(axis=1)
    z = (mkt_amt - mkt_amt.rolling(244).mean()) / mkt_amt.rolling(244).std(ddof=1)
    vp = ew.rolling(10).corr(z)                                  # 量价相关性
    breadth = (ret > 0).rolling(20).mean().mean(axis=1)          # 20 日上涨行业占比
    disp = ret.rolling(20).std().std(axis=1)                     # 截面离散度
    states = {"vp": vp, "breadth": breadth, "disp": disp}

    s = pd.Series(ret.index, index=ret.index)
    me = pd.DatetimeIndex(s.groupby([ret.index.year, ret.index.month]).last().values)
    first = pd.DatetimeIndex(s.groupby([ret.index.year, ret.index.month]).first().values)
    me = me[(me >= pd.Timestamp(START)) & (me < pd.Timestamp(END))]
    print(f"决策月末 {len(me)} 个：{me[0].date()} ~ {me[-1].date()}")

    # 每个决策日的 CMM 分数（逐状态）与下一月收益
    hist = []          # (T, {var: {s: zscores}}, fwd_ret)
    cmm_scores = {}
    for T in me:
        idx = ret.index[ret.index <= T]
        if len(idx) < WIN:
            continue
        win = idx[-WIN:]
        out = {}
        for name, ser in states.items():
            x = ser.reindex(win)
            if x.notna().sum() < 100:
                continue
            r = x.rank(method="first")
            st = np.ceil(r / len(x) * NQ).clip(1, NQ).astype("Int64")
            lr = logret.reindex(win)
            per = {}
            for k in range(1, NQ + 1):
                mask = (st == k)
                if mask.sum() < 10:
                    continue
                cum = lr[mask].sum()
                per[k] = cum.rank(pct=True)
            if per:
                out[name] = per
        cmm_scores[T] = out
        nxt = me[me > T]
        if len(nxt):
            fwd = (level.loc[nxt[0]] / level.loc[T] - 1) if nxt[0] in level.index else None
            hist.append((T, out, fwd))

    # 逐期选 S*（用过去 24 期的 IC；不足 6 期回退 MOM）
    mom = (level / level.shift(252) - 1)
    picks = {}
    ic_hist = {name: {k: [] for k in range(1, NQ + 1)} for name in states}
    for T, out, fwd in hist:
        chosen = {}
        for name, per in out.items():
            best, best_ic = None, -np.inf
            for k, sc in per.items():
                ics = ic_hist[name][k]
                if len(ics) >= 6:
                    m = float(np.mean(ics[-24:]))
                    if m > best_ic:
                        best, best_ic = k, m
            chosen[name] = best
        picks[T] = chosen
        if fwd is not None:
            for name, per in out.items():
                fr = fwd.reindex(per[list(per)[0]].index) if per else None
                for k, sc in per.items():
                    if fr is None:
                        continue
                    ic = sc.rank().corr(fr.rank())
                    if np.isfinite(ic):
                        ic_hist[name][k].append(float(ic))

    def score_at(T, use_cmm: bool):
        """各状态变量在各自 S* 下的截面排名，取均值；无有效状态时回退 MOM。"""
        out = cmm_scores.get(T, {})
        parts = []
        if use_cmm:
            for name, per in out.items():
                k = picks.get(T, {}).get(name)
                if k is not None and k in per:
                    parts.append(per[k])
        if not parts:
            return mom.loc[T].rank(pct=True)
        return pd.concat(parts, axis=1).mean(axis=1).rank(pct=True)

    vol20 = ret.rolling(20).std(ddof=1) * np.sqrt(250)

    def select(T, mode):
        d, r = dc.loc[T].dropna(), rv.loc[T].dropna()
        base = set(d.nlargest(4).index) & set(r.nlargest(2).index)
        if mode == "base":
            return sorted(base)
        sc = score_at(T, use_cmm=(mode.startswith("cmm")))
        if sc is None:
            return sorted(base)
        v = vol20.loc[T].dropna()
        lo = v.quantile(0.70) if len(v) else np.inf
        ok = [c for c in sc.dropna().index if c in v.index and v[c] <= lo]
        if mode == "mom_vol":
            return list(sc[ok].nlargest(2).index) if ok else []
        if mode == "cmm_vol":
            return list(sc[ok].nlargest(2).index) if ok else []
        if mode == "cmm_gate":
            keep = set(sc[ok].nlargest(4).index) if ok else set()
            return sorted(base & keep)
        return sorted(base)

    def weights(mode):
        w = pd.DataFrame(0.0, index=ret.index, columns=codes)
        cur = []
        for d in first:
            prior = me[me < d]
            if not len(prior):
                continue
            sel = select(prior[-1], mode)
            if sel:
                cur = sel
            if cur:
                w.loc[d:] = 0.0
                w.loc[d:, cur] = 1.0 / len(cur)
        return w

    rows, navs = [], {}
    for mode, label in [("base", "① 基准 ΔC∩RV"), ("mom_vol", "② MOM前2+VOL20"),
                        ("cmm_vol", "③ CMM前2+VOL20"), ("cmm_gate", "④ CMM作为第三闸")]:
        w = weights(mode)
        r = portfolio_returns(w, ret)
        r = r[r.index >= START]
        timed, _ = run_timing_overlay(d_ar, r, bond_all.reindex(r.index), TH)
        m = metrics(timed.dropna())
        rows.append({"variant": label, "annual_return": round(m["annual_return"], 4),
                     "annual_vol": round(m["annual_vol"], 4), "sharpe": round(m["sharpe"], 4),
                     "max_drawdown": round(m["max_drawdown"], 4), "calmar": round(m["calmar"], 4)})
        navs[label] = nav_curve(timed.dropna())
    t = pd.DataFrame(rows).sort_values("sharpe", ascending=False)
    t.to_csv(OUT / "cmm_comparison.csv", index=False)
    pd.DataFrame(navs).to_csv(OUT / "cmm_nav.csv")
    print(t.to_string(index=False))
    print("\nS* 选择分布（vp）：", pd.Series([v.get("vp") for v in picks.values()]).value_counts().to_dict())
    (OUT / "cmm_summary.json").write_text(json.dumps({
        "window": [START, END],
        "states": ["量价相关性(10d corr of EW ret vs 244d amount z)", "20日上涨行业占比", "截面离散度"],
        "S_star": "各状态取过去24期截面IC均值最大者；不足6期回退MOM",
        "results": t.to_dict(orient="records"),
    }, ensure_ascii=False, indent=2, default=float), encoding="utf-8")


if __name__ == "__main__":
    main()
