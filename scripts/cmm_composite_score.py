"""把 CMM 作为第三个因子并入综合评分（ΔC、RV、CMM 的截面百分位加权）。"""
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
START, END, TH, WIN, NQ = "2017-01-03", "2026-10-30", 1.5, 252, 5


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

    mkt_amt = amt.sum(axis=1)
    z = (mkt_amt - mkt_amt.rolling(244).mean()) / mkt_amt.rolling(244).std(ddof=1)
    states = {"vp": ew.rolling(10).corr(z),
              "breadth": (ret > 0).rolling(20).mean().mean(axis=1),
              "disp": ret.rolling(20).std().std(axis=1)}

    s = pd.Series(ret.index, index=ret.index)
    me = pd.DatetimeIndex(s.groupby([ret.index.year, ret.index.month]).last().values)
    first = pd.DatetimeIndex(s.groupby([ret.index.year, ret.index.month]).first().values)
    me = me[(me >= pd.Timestamp(START)) & (me < pd.Timestamp(END))]

    cmm, ic_hist, picks, hist = {}, {n: {k: [] for k in range(1, NQ + 1)} for n in states}, {}, []
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
            st = np.ceil(x.rank(method="first") / len(x) * NQ).clip(1, NQ).astype("Int64")
            lr = logret.reindex(win)
            per = {}
            for k in range(1, NQ + 1):
                m = (st == k)
                if m.sum() >= 10:
                    per[k] = lr[m].sum().rank(pct=True)
            if per:
                out[name] = per
        cmm[T] = out
        nxt = me[me > T]
        fwd = (level.loc[nxt[0]] / level.loc[T] - 1) if len(nxt) else None
        hist.append((T, out, fwd))

    mom = level / level.shift(252) - 1
    for T, out, fwd in hist:
        ch = {}
        for name, per in out.items():
            best, bic = None, -np.inf
            for k in per:
                ics = ic_hist[name][k]
                if len(ics) >= 6 and np.mean(ics[-24:]) > bic:
                    best, bic = k, np.mean(ics[-24:])
            ch[name] = best
        picks[T] = ch
        if fwd is not None:
            for name, per in out.items():
                for k, sc in per.items():
                    ic = sc.rank().corr(fwd.reindex(sc.index).rank())
                    if np.isfinite(ic):
                        ic_hist[name][k].append(float(ic))

    def cmm_pct(T):
        parts = []
        for name, per in cmm.get(T, {}).items():
            k = picks.get(T, {}).get(name)
            if k in per:
                parts.append(per[k])
        if not parts:
            return mom.loc[T].rank(pct=True)
        return pd.concat(parts, axis=1).mean(axis=1).rank(pct=True)

    def weights(sel_fn):
        w = pd.DataFrame(0.0, index=ret.index, columns=codes)
        cur = []
        for d in first:
            prior = me[me < d]
            if not len(prior):
                continue
            sel = sel_fn(prior[-1])
            if sel:
                cur = sel
            if cur:
                w.loc[d:] = 0.0
                w.loc[d:, cur] = 1.0 / len(cur)
        return w

    def composite(T, wts, k):
        p = pd.DataFrame({"dc": dc.loc[T].rank(pct=True),
                          "rv": rv.loc[T].rank(pct=True),
                          "cmm": cmm_pct(T)}).dropna()
        if p.empty:
            return []
        score = sum(p[c] * w for c, w in wts.items())
        return list(score.nlargest(k).index)

    def base(T):
        d, r = dc.loc[T].dropna(), rv.loc[T].dropna()
        return sorted(set(d.nlargest(4).index) & set(r.nlargest(2).index)) if len(d) and len(r) else []

    rows, navs = [], {}
    cases = [
        ("① 基准 ΔC∩RV", base),
        ("② 综合评分 1/3·1/3·1/3 → 前2", lambda T: composite(T, {"dc": 1/3, "rv": 1/3, "cmm": 1/3}, 2)),
        ("③ 综合评分 0.45·0.45·0.10 → 前2", lambda T: composite(T, {"dc": .45, "rv": .45, "cmm": .10}, 2)),
        ("④ 综合评分 0.40·0.40·0.20 → 前2", lambda T: composite(T, {"dc": .40, "rv": .40, "cmm": .20}, 2)),
        ("⑤ 综合评分 1/3·1/3·1/3 → 前3", lambda T: composite(T, {"dc": 1/3, "rv": 1/3, "cmm": 1/3}, 3)),
        ("⑥ 综合评分 0.45·0.45·0.10 → 前3", lambda T: composite(T, {"dc": .45, "rv": .45, "cmm": .10}, 3)),
    ]
    for label, fn in cases:
        w = weights(fn)
        r = portfolio_returns(w, ret)
        r = r[r.index >= START]
        timed, _ = run_timing_overlay(d_ar, r, bond_all.reindex(r.index), TH)
        m = metrics(timed.dropna())
        rows.append({"variant": label, "annual_return": round(m["annual_return"], 4),
                     "annual_vol": round(m["annual_vol"], 4), "sharpe": round(m["sharpe"], 4),
                     "max_drawdown": round(m["max_drawdown"], 4), "calmar": round(m["calmar"], 4)})
        navs[label] = nav_curve(timed.dropna())
    t = pd.DataFrame(rows).sort_values("sharpe", ascending=False)
    t.to_csv(OUT / "cmm_composite.csv", index=False)
    pd.DataFrame(navs).to_csv(OUT / "cmm_composite_nav.csv")
    print(t.to_string(index=False))
    cors_dc, cors_rv = [], []
    for T in me:
        c = cmm_pct(T)
        d, r = dc.loc[T].dropna(), rv.loc[T].dropna()
        if len(c) and len(d):
            cors_dc.append(c.reindex(d.index).rank().corr(d.rank()))
        if len(c) and len(r):
            cors_rv.append(c.reindex(r.index).rank().corr(r.rank()))
    print(f"\nCMM 与 ΔC 的月末秩相关: {np.nanmean(cors_dc):+.2f} | 与 RV: {np.nanmean(cors_rv):+.2f}")
    (OUT / "cmm_composite_summary.json").write_text(json.dumps({
        "window": [START, END],
        "score": "ΔC/RV/CMM 截面百分位加权求和",
        "results": t.to_dict(orient="records"),
    }, ensure_ascii=False, indent=2, default=float), encoding="utf-8")


if __name__ == "__main__":
    main()
