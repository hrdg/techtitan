"""V2：修正权重的 18 行业 ETF 执行版。

相对 UNIVERSE18_L3EXEC_FALLBACK_V20261105 的三处改动：
1. 权重按唯一 ETF 等权且合计为 1（消除重复映射造成的隐式现金）
2. 移除 L3 子行业执行（唯一干净区间内为负增量）
3. ETF 综合动量仅在分数日期距 T 不超过 STALE_DAYS 时使用，否则退化为 beta 排序

用法：
  python scripts/v2_etf_normalized_backtest.py
  FB=1 python scripts/v2_etf_normalized_backtest.py

正式结果写入 results/v2_normalized；参数试跑应设置 RUN_TAG 或 OUT_DIR，
避免覆盖正式 summary/holdings/nav/live 文件。
"""
from __future__ import annotations

import json
import os
import sys
from pathlib import Path

import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from tech_rotation import (  # noqa: E402
    absorption_and_concentration,
    delta_zscore,
    metrics,
    portfolio_returns,
    relative_valuation,
)
from tech_rotation.backtest import period_end_signal_dates  # noqa: E402

HA = Path("/Users/hsh/Documents/Quant/因子择时/HA_market_attention_etf_momentum")
OUT = Path(os.environ.get("OUT_DIR", ROOT / "results" / "v2_normalized"))
OUT.mkdir(parents=True, exist_ok=True)

WINDOW = 250
CORR_MIN = 0.80
TOP_CORR = 8
FALLBACK = os.environ.get("FB", "0") == "1"
COST = float(os.environ.get("COST", "0.0005"))
STALE_DAYS = int(os.environ.get("STALE_DAYS", "45"))
K1 = int(os.environ.get("K1", "3"))   # rv 前 k1
K2 = int(os.environ.get("K2", "5"))   # dc 前 k2
STICKY = float(os.environ.get("STICKY", "0.10"))  # 与当前持仓 ETF 分数差小于该值时保留
START, END = os.environ.get("START", "2019-08-01"), os.environ.get("END", "2026-07-31")
RUN_TAG = os.environ.get("RUN_TAG", "")
REBAL = os.environ.get("REBAL", "M").upper()
PHASE = int(os.environ.get("PHASE", "0"))
if REBAL not in {"M", "W", "2W"}:
    raise ValueError("REBAL must be 'M', 'W' or '2W'")
if PHASE not in {0, 1}:
    raise ValueError("PHASE must be 0 or 1")


def load_panel(path: Path):
    p = pd.read_parquet(path)
    p["date"] = pd.to_datetime(p["date"]).dt.tz_localize(None)
    piv = lambda k: p.pivot(index="date", columns="code", values=k).sort_index()  # noqa: E731
    return piv("ret"), piv("pb"), piv("float_mv")


def main() -> None:
    r18, pb18, mv18 = load_panel(ROOT / "data/raw/industry_panel_18.parquet")
    for f in (r18, pb18, mv18):
        f.columns = f.columns.astype(str)
    ar, conc = absorption_and_concentration(r18, mv18)
    dc, rv, dar = delta_zscore(conc), relative_valuation(pb18), delta_zscore(ar)

    b = pd.read_parquet(ROOT / "data/raw/benchmark_csi_daily.parquet")
    b["date"] = pd.to_datetime(b["date"]).dt.tz_localize(None)
    bond = b[b.code == "H11006"].set_index("date")["close"].sort_index().pct_change()
    tip = pd.read_parquet(ROOT / "data/raw/tip_daily.parquet")
    tip["date"] = pd.to_datetime(tip["date"]).dt.tz_localize(None)
    tip = tip.set_index("date")["close"].sort_index()

    days = r18.index[(r18.index >= START) & (r18.index <= END)]
    ta = tip.reindex(days).ffill()
    tg = (pd.concat([ta / ta.shift(k) - 1 for k in (21, 63, 126, 252)], axis=1).mean(axis=1) > 0).astype(float)
    ev = pd.Series(np.nan, index=days)
    ev[dar.reindex(days) > 1.5] = 0.0
    ev[dar.reindex(days) < 0] = 1.0
    exp = (ev.ffill().fillna(1.0) * tg).shift(1).fillna(0.0)
    if REBAL == "M":
        mes = pd.DatetimeIndex(
            pd.Series(days, index=days).groupby([days.year, days.month]).last().values
        )
    else:
        weekly_signals = period_end_signal_dates(days, "W")
        mes = weekly_signals if REBAL == "W" else weekly_signals[PHASE::2]

    px = pd.read_parquet(HA / "research/runs/ha_chart19_frequency_v1/data/adj_close_snapshot.parquet")
    ret_e = px.pct_change(fill_method=None)
    comp = pd.read_parquet(HA / "research/runs/ha_oos_tip136u_gate_30_v1/outputs/composite_scores_all.parquet")
    comp["date"] = pd.to_datetime(comp["date"])
    comp_p = comp.pivot(index="date", columns="code", values="composite").sort_index()
    etf_cols = np.asarray(ret_e.columns)

    # 每个信号周期末的候选集：相关 >= 0.80 的前 8 只，beta 与动量各占 50%
    cands, stale_months = {}, 0
    for T in mes:
        rows = ret_e.index[ret_e.index <= T][-WINDOW:]
        if len(rows) < WINDOW:
            continue
        H = ret_e.reindex(rows).to_numpy(float)
        cd = comp_p.index[comp_p.index <= T]
        fresh = len(cd) > 0 and (T - cd[-1]).days <= STALE_DAYS
        if len(cd) and not fresh:
            stale_months += 1
        cs = comp_p.loc[cd[-1]] if fresh else None
        for ind in r18.columns:
            y = r18[ind].reindex(rows).to_numpy(float)
            mr = np.isfinite(y)
            H2, y2 = H[mr], y[mr]
            if len(y2) < 100:
                continue
            cm = np.isfinite(H2).all(axis=0) & (H2.std(axis=0) > 0)
            if cm.sum() < 50:
                continue
            Hm = H2[:, cm]
            Hs = (Hm - Hm.mean(0)) / Hm.std(0)
            ys = (y2 - y2.mean()) / y2.std()
            corr = Hs.T @ ys / len(ys)
            keep = np.where(corr >= CORR_MIN)[0]
            if len(keep) < 3:
                continue
            pick = keep[np.argsort(-corr[keep])][:TOP_CORR]
            beta = (Hm[:, pick].T @ y2 / len(y2) - Hm[:, pick].mean(0) * y2.mean()) / y2.var()
            cols = etf_cols[cm][pick]
            mom = cs.reindex(cols).to_numpy() if cs is not None else np.full(len(pick), np.nan)
            cands[(T, ind)] = pd.DataFrame({"beta": beta, "mom": mom}, index=cols)

    # 行业选择：默认月末；REBAL=W 为周末；REBAL=2W 为隔周末的两个相位之一。
    cur, sel = [], {}
    for T in mes:
        d1, r1 = dc.loc[T].dropna(), rv.loc[T].dropna()
        common = [q for q in d1.index if q in r1.index]
        if not common:
            sel[T] = list(cur)
            continue
        s = sorted(set(d1[common].nlargest(K2).index) & set(r1.nlargest(K1).index))
        if not s and FALLBACK:
            cand = list(r1.nlargest(3).index)
            s = [max(cand, key=lambda q: d1.get(q, -9e9))] if cand else []
        if s:
            cur = s
        sel[T] = list(cur)

    # 权重：唯一 ETF 等权，合计 1
    w = pd.DataFrame(0.0, index=days, columns=ret_e.columns)
    n_fill, n_dup, dias = 0, 0, []
    held: dict[str, str] = {}
    for T in mes:
        nxt = days[days > T]
        if nxt.empty:
            break
        picks = []
        for ind in sel.get(T, []):
            df = cands.get((T, ind))
            if df is None or df.empty:
                continue
            mom = df["mom"]
            ref = mom if mom.notna().any() else df["beta"]
            score = df["beta"].rank(pct=True) * 0.5 + ref.rank(pct=True) * 0.5
            best = str(score.idxmax())
            prev = held.get(ind)
            if STICKY > 0 and prev in score.index and score[prev] >= score[best] - STICKY:
                best = prev
            held[ind] = best
            picks.append(best)
        if not picks:
            continue
        uq = list(dict.fromkeys(picks))
        n_dup += len(uq) != len(picks)
        n_fill += len(picks) < len(sel.get(T, []))
        w.loc[nxt[0]:, :] = 0.0
        for q in uq:
            w.loc[nxt[0]:, q] = 1.0 / len(uq)
        dias.append({"T": str(T.date()), "selected": list(sel.get(T, [])), "etfs": uq})

    risky = portfolio_returns(w, ret_e).reindex(days).fillna(0.0)
    etf_turn = w.diff().abs().sum(axis=1).fillna(0.0)
    risky_w = w.mul(exp, axis=0)
    bond_w = 1.0 - exp
    execution_turn = (risky_w.diff().abs().sum(axis=1) + bond_w.diff().abs()).fillna(0.0)
    r = (exp * risky + (1 - exp) * bond.reindex(days).fillna(0.0)
         - COST * execution_turn)

    def block(x: pd.Series) -> dict:
        x = x.dropna()
        if x.empty:
            return {"sharpe": None, "ann": None, "vol": None, "mdd": None, "calmar": None}
        m = metrics(x)
        return {"sharpe": round(m["sharpe"], 3), "ann": round(m["annual_return"], 4),
                "vol": round(m["annual_vol"], 4), "mdd": round(m["max_drawdown"], 4),
                "calmar": round(m["calmar"], 3)}

    out = {
        "variant": "V2_18K53_ETF_NORMALIZED"
        + ("_WEEKLY" if REBAL == "W" else "")
        + (f"_BIWEEKLY_P{PHASE}" if REBAL == "2W" else "")
        + ("_FALLBACK" if FALLBACK else ""),
        "window": {"start": START, "end": END, "cost": COST, "fallback": FALLBACK,
                   "weight_rule": "unique ETF equal weight, sum=1", "l3": False,
                   "stale_days": STALE_DAYS, "k_rv": K1, "k_deltaC": K2,
                   "stickiness": STICKY},
        "full": block(r), "2019-2023": block(r.loc[: "2023-12-31"]),
        "2024-2026": block(r.loc["2024-01-01":]),
        "pre2019": block(r.loc[: "2019-07-31"]),
        "yearly": {str(y): round(float((1 + x).prod() - 1), 4) for y, x in r.groupby(r.index.year)},
        "avg_exposure": round(float(w.sum(axis=1).mean()), 3),
        "avg_etf_turnover_month": round(float(etf_turn.mean() * 21), 3),
        "avg_execution_turnover_month": round(float(execution_turn.mean() * 21), 3),
        "months_duplicate_etf": int(n_dup), "months_partial_fill": int(n_fill),
        "months_with_stale_momentum": int(stale_months),
    }
    if REBAL != "M":
        out["window"]["rebalance_freq"] = REBAL
        if REBAL == "2W":
            out["window"]["phase"] = PHASE
        out["periods_duplicate_etf"] = int(n_dup)
        out["periods_partial_fill"] = int(n_fill)
        out["periods_with_stale_momentum"] = int(stale_months)
    suffix_parts = [
        "weekly" if REBAL == "W" else "",
        f"biweekly_p{PHASE}" if REBAL == "2W" else "",
        "fb" if FALLBACK else "nofb",
        RUN_TAG,
    ]
    suffix = "_".join(part for part in suffix_parts if part)
    (OUT / f"summary_{suffix}.json").write_text(
        json.dumps(out, ensure_ascii=False, indent=1, allow_nan=False), encoding="utf-8")
    pd.DataFrame(dias).to_csv(OUT / f"holdings_{suffix}.csv", index=False)
    pd.DataFrame({"nav": (1 + r).cumprod(), "exposure": exp}).to_csv(
        OUT / f"nav_{suffix}.csv")
    print(json.dumps(out, ensure_ascii=False, indent=1))

    # 当期信号
    last_T = mes[-1]
    d1, r1 = dc.loc[last_T].dropna(), rv.loc[last_T].dropna()
    common = [q for q in d1.index if q in r1.index]
    s = sorted(set(d1[common].nlargest(K2).index) & set(r1.nlargest(K1).index))
    chosen = s
    if not s and FALLBACK:
        cand = list(r1.nlargest(3).index)
        chosen = [max(cand, key=lambda q: d1.get(q, -9e9))] if cand else []
    live = {"signal_date": str(last_T.date()),
            "dc_top5": list(d1.nlargest(5).index), "rv_top3": list(r1.nlargest(3).index),
            "intersection": s, "selected": chosen, "fallback_used": bool(not s and FALLBACK),
            "exposure": float(exp.iloc[-1]), "name_map": {}}
    print(json.dumps(live, ensure_ascii=False, indent=1))
    (OUT / f"live_{suffix}.json").write_text(
        json.dumps(live, ensure_ascii=False, indent=1), encoding="utf-8")


if __name__ == "__main__":
    main()
