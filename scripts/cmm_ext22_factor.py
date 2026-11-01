"""CMM + 扩展 22 项特征的月频综合动量（按 HA 项目口径复刻，10 行业代理）。

特征定义对齐 因子择时/HA_market_attention_etf_momentum/src/build_huafu_etf_features.py：
BASE16 = vol_60/120, log_amount_60/252, amihud_60, amount_trend, ret_21d, ret_126d,
         max_ret_21d, skew_60, kurt_60, price_to_high_252, beta_252, idio_vol_60,
         zero_ret_ratio_60, mean_abs_ret_60
EXTRA6 = LTRSTR, RSTR, HALPHA, CMRA, DASTD, HSIGMA（日价 Barra 代理）
赋权：各特征截面排名 -> 过去 24 期正 IC 加权（IC<=0 记 0）；历史不足回退 MOM。
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
WIN, NQ, IC_LOOKBACK = 252, 5, 24


def feats_at(logret, amount, mkt, j, codes):
    """第 j 行（含）往前 252 日窗口的 22 项特征。"""
    lo = max(0, j - WIN + 1)
    x = logret.iloc[lo:j + 1]
    a = amount.iloc[lo:j + 1]
    b = mkt.iloc[lo:j + 1]
    out = {}
    if len(x) < 120:
        return out
    x60, x120, x252 = x.tail(60), x.tail(120), x.tail(252)
    a60, a252 = a.tail(60), a.tail(252)
    out["vol_60"] = -x60.std(ddof=1)                 # 低波更优 -> 取负
    out["vol_120"] = -x120.std(ddof=1)
    out["log_amount_60"] = np.log(a60.mean() + 1)
    out["log_amount_252"] = np.log(a252.mean() + 1)
    out["amihud_60"] = -(x60.abs() / (a60 + 1e-9)).mean()
    out["amount_trend"] = np.log((a.tail(20).mean() + 1) / (a60.mean() + 1))
    out["ret_21d"] = x.tail(21).sum()
    out["ret_126d"] = x.tail(126).sum()
    out["max_ret_21d"] = x.tail(21).max()
    out["skew_60"] = x60.skew()
    out["kurt_60"] = x60.kurt()
    lvl = x.cumsum()
    out["price_to_high_252"] = lvl.iloc[-1] - lvl.tail(252).max()
    X = x252.to_numpy()
    bb = b.tail(len(x252)).to_numpy()
    Xc = X - X.mean(axis=0)
    bc = bb - bb.mean()
    beta = (Xc * bc[:, None]).sum(axis=0) / (bc ** 2).sum()
    resid_np = Xc - bc[:, None] * beta[None, :]
    resid = pd.DataFrame(resid_np, index=x252.index, columns=x252.columns)
    out["beta_252"] = pd.Series(-np.abs(beta), index=x252.columns)   # 低 beta 更优
    out["idio_vol_60"] = -resid.tail(60).std(ddof=1)
    out["zero_ret_ratio_60"] = (x60 == 0).mean()
    out["mean_abs_ret_60"] = x60.abs().mean()
    out["LTRSTR"] = -x252.sum()
    out["RSTR"] = x252.iloc[:-21].sum()
    out["HALPHA"] = resid.sum()
    cum = x252.cumsum()
    out["CMRA"] = cum.max() - cum.min()
    out["DASTD"] = -x252.std(ddof=1)
    out["HSIGMA"] = -resid.std(ddof=1)
    return pd.DataFrame(out).T  # rows=feature, cols=industry


def main() -> None:
    df = pd.read_parquet(RAW / "industry_panel_latest.parquet")
    df["date"] = pd.to_datetime(df["date"]).dt.tz_localize(None)
    ret = df.pivot(index="date", columns="code", values="ret")
    pb = df.pivot(index="date", columns="code", values="pb")
    fmv = df.pivot(index="date", columns="code", values="float_mv")
    amt = df.pivot(index="date", columns="code", values="amount_wan").replace(0, np.nan)
    codes = list(ret.columns)
    logret = np.log1p(ret)
    mkt = ret.mean(axis=1)
    level = (1 + ret.fillna(0)).cumprod()
    ar, conc = absorption_and_concentration(ret, fmv)
    dc, rv, d_ar = delta_zscore(conc), relative_valuation(pb), delta_zscore(ar)
    b = pd.read_parquet(RAW / "benchmark_csi_daily.parquet")
    b["date"] = pd.to_datetime(b["date"]).dt.tz_localize(None)
    bond_all = b[b["code"] == "H11006"].set_index("date")["close"].pct_change()

    s = pd.Series(ret.index, index=ret.index)
    me = pd.DatetimeIndex(s.groupby([ret.index.year, ret.index.month]).last().values)
    first = pd.DatetimeIndex(s.groupby([ret.index.year, ret.index.month]).first().values)
    me = me[(me >= pd.Timestamp(START)) & (me < pd.Timestamp(END))]

    # 决策日特征与前瞻收益
    snap, fwd = {}, {}
    for i, T in enumerate(me):
        j = ret.index.get_loc(T)
        f = feats_at(logret, amt, mkt, j, codes)
        if f.empty:
            continue
        snap[T] = f.rank(axis=1, pct=True)
        if i + 1 < len(me):
            nxt = me[i + 1]
            if nxt in level.index:
                fwd[T] = (level.loc[nxt] / level.loc[T] - 1)

    names = list(next(iter(snap.values())).index)
    hist = {k: [] for k in names}
    weight_hist, scores = {}, {}
    for T in me:
        if T not in snap:
            continue
        w = {}
        for k in names:
            ics = hist[k][-IC_LOOKBACK:]
            if len(ics) >= 6:
                v = float(np.mean(ics))
                if v > 0:
                    w[k] = v
        if not w:
            w = {k: 1.0 for k in names}
        tot = sum(w.values())
        score = sum(snap[T].loc[k] * (v / tot) for k, v in w.items())
        scores[T] = score.rank(pct=True)
        if T in fwd:
            fr = fwd[T]
            for k in names:
                ic = snap[T].loc[k].rank().corr(fr.rank())
                if np.isfinite(ic):
                    hist[k].append(float(ic))

    mom = level / level.shift(252) - 1
    vol20 = ret.rolling(20).std(ddof=1) * np.sqrt(250)

    # 状态条件 CMM（3 个市场状态变量，S* 由过去 IC 估计，不足回退 MOM）
    mkt_amt = amt.sum(axis=1)
    z = (mkt_amt - mkt_amt.rolling(244).mean()) / mkt_amt.rolling(244).std(ddof=1)
    state_series = {
        "vp": ret.mean(axis=1).rolling(10).corr(z),
        "breadth": (ret > 0).rolling(20).mean().mean(axis=1),
        "disp": ret.rolling(20).std().std(axis=1),
    }
    ic_state = {n: {k: [] for k in range(1, NQ + 1)} for n in state_series}
    cmm_score = {}
    for T in me:
        idx = ret.index[ret.index <= T]
        if len(idx) < WIN:
            continue
        win = idx[-WIN:]
        per, chosen = {}, {}
        for name, ser in state_series.items():
            x = ser.reindex(win)
            if x.notna().sum() < 100:
                continue
            r = x.rank(method="first")
            st = np.ceil(r / len(x) * NQ).clip(1, NQ).astype("Int64")
            lr = logret.reindex(win)
            per[name] = {}
            for k in range(1, NQ + 1):
                mask = st == k
                if mask.sum() < 10:
                    continue
                per[name][k] = lr[mask].sum().rank(pct=True)
            best, best_ic = None, -np.inf
            for k, sc in per[name].items():
                if len(ic_state[name][k]) >= 6:
                    m = float(np.mean(ic_state[name][k][-24:]))
                    if m > best_ic:
                        best, best_ic = k, m
            chosen[name] = best
        parts = [per[n][k] for n, k in chosen.items() if k in per.get(n, {})]
        if parts:
            cmm_score[T] = pd.concat(parts, axis=1).mean(axis=1).rank(pct=True)
        if T in fwd:
            for n, d_ in per.items():
                fr = fwd[T]
                for k, sc in d_.items():
                    ic = sc.rank().corr(fr.rank())
                    if np.isfinite(ic):
                        ic_state[n][k].append(float(ic))

    def score_at(T):
        return scores.get(T, mom.loc[T].rank(pct=True))

    def score_cmm(T):
        return cmm_score.get(T, mom.loc[T].rank(pct=True))

    def score_both(T):
        a, c = score_at(T), score_cmm(T)
        return ((a + c) / 2).rank(pct=True)

    def select(T, mode):
        d, r = dc.loc[T].dropna(), rv.loc[T].dropna()
        base = set(d.nlargest(4).index) & set(r.nlargest(2).index)
        if mode == "base":
            return sorted(base)
        sc = {"top2": score_at, "gate": score_at, "gate_both": score_both}[mode](T).dropna()
        v = vol20.loc[T].dropna()
        lo = v.quantile(0.70) if len(v) else np.inf
        ok = [c for c in sc.index if c in v.index and v[c] <= lo]
        if mode == "top2":
            return list(sc[ok].nlargest(2).index) if ok else []
        if mode in ("gate", "gate_both"):
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
    for mode, label in [("base", "① 基准 ΔC∩RV"), ("top2", "② EXT22综合动量前2+VOL20"),
                        ("gate", "③ EXT22作为第三闸"),
                        ("gate_both", "④ EXT22+CMM 作为第三闸")]:
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
    t.to_csv(OUT / "cmm_ext22_comparison.csv", index=False)
    pd.DataFrame(navs).to_csv(OUT / "cmm_ext22_nav.csv")
    print(f"决策月末 {len(me)} 个；特征 {len(names)} 项：{names}")
    print(t.to_string(index=False))
    (OUT / "cmm_ext22_summary.json").write_text(json.dumps({
        "window": [START, END], "n_features": len(names), "features": names,
        "weighting": "过去24期正IC均值加权（IC<=0记0），不足6期等权",
        "results": t.to_dict(orient="records"),
    }, ensure_ascii=False, indent=2, default=float), encoding="utf-8")


if __name__ == "__main__":
    main()
