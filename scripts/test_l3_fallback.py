"""Hierarchical repair: select at the 18-industry level, execute via the strongest L3 child."""
from __future__ import annotations

import json
import sys
import warnings
from pathlib import Path

import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))
warnings.filterwarnings("ignore")
from tech_rotation import (  # noqa: E402
    absorption_and_concentration,
    delta_zscore,
    metrics,
    portfolio_returns,
    relative_valuation,
)

HA = Path("/Users/hsh/Documents/Quant/因子择时/HA_market_attention_etf_momentum")
WINDOW = 250
import os
FALLBACK = os.environ.get("FB")=="1"
CHILDREN = {
    "801081": ["850813", "850814", "850815", "850817", "850818"],
    "801102": ["851024", "851025", "851026", "851027"],
}


def load(path):
    p = pd.read_parquet(path)
    p["date"] = pd.to_datetime(p["date"]).dt.tz_localize(None)
    piv = lambda k: p.pivot(index="date", columns="code", values=k).sort_index()
    ret, pb, mv = piv("ret"), piv("pb"), piv("float_mv")
    for f in (ret, pb, mv):
        f.columns = f.columns.astype(str)
    return ret, pb, mv


def main():
    r18, pb18, mv18 = load(ROOT / "data/raw/industry_panel_18.parquet")
    r25, pb25, mv25 = load(ROOT / "data/raw/industry_panel_25.parquet")
    rv18 = relative_valuation(pb18)
    ar18, conc18 = absorption_and_concentration(r18, mv18)
    dc18, dar = delta_zscore(conc18), delta_zscore(ar18)
    _, conc25 = absorption_and_concentration(r25, mv25)
    dc25 = delta_zscore(conc25)

    b = pd.read_parquet(ROOT / "data/raw/benchmark_csi_daily.parquet")
    b["date"] = pd.to_datetime(b["date"]).dt.tz_localize(None)
    bond = b[b["code"] == "H11006"].set_index("date")["close"].sort_index().pct_change()
    tip = pd.read_parquet(ROOT / "data/raw/tip_daily.parquet")
    tip["date"] = pd.to_datetime(tip["date"]).dt.tz_localize(None)
    tip = tip.set_index("date")["close"].sort_index()

    days = r18.index[(r18.index >= "2019-08-01") & (r18.index <= "2026-07-31")]
    ta = tip.reindex(days).ffill()
    tg = (pd.concat([ta / ta.shift(k) - 1 for k in (21, 63, 126, 252)], axis=1).mean(axis=1) > 0).astype(float)
    ev = pd.Series(np.nan, index=days)
    ev[dar.reindex(days) > 1.5] = 0.0
    ev[dar.reindex(days) < 0] = 1.0
    exp = (ev.ffill().fillna(1.0) * tg).shift(1).fillna(0.0)
    mes = pd.DatetimeIndex(pd.Series(days, index=days).groupby([days.year, days.month]).last().values)

    px = pd.read_parquet(HA / "research/runs/ha_chart19_frequency_v1/data/adj_close_snapshot.parquet")
    ret_e = px.pct_change(fill_method=None)
    comp = pd.read_parquet(HA / "research/runs/ha_oos_tip136u_gate_30_v1/outputs/composite_scores_all.parquet")
    comp["date"] = pd.to_datetime(comp["date"])
    comp_p = comp.pivot(index="date", columns="code", values="composite").sort_index()
    etf_cols = np.asarray(ret_e.columns)

    series = {"18": r18, "25": r25}
    cands = {}
    for lvl, rr in series.items():
        for T in mes:
            rows = ret_e.index[ret_e.index <= T][-WINDOW:]
            if len(rows) < WINDOW:
                continue
            H = ret_e.reindex(rows).to_numpy(float)
            cd = comp_p.index[comp_p.index <= T]
            cs = comp_p.loc[cd[-1]] if len(cd) else None
            for ind in rr.columns:
                y = rr[ind].reindex(rows).to_numpy(float)
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
                keep = np.where(corr >= 0.80)[0]
                if len(keep) < 3:
                    continue
                pick = keep[np.argsort(-corr[keep])][:8]
                beta = (Hm[:, pick].T @ y2 / len(y2) - Hm[:, pick].mean(0) * y2.mean()) / y2.var()
                cols = etf_cols[cm][pick]
                mom = cs.reindex(cols).to_numpy() if cs is not None else np.full(len(pick), np.nan)
                cands[(lvl, T, ind)] = pd.DataFrame({"beta": beta, "mom": mom}, index=cols)

    def run(mode):
        sel, cur = {}, []
        for T in mes:
            d1, r1 = dc18.loc[T].dropna(), rv18.loc[T].dropna()
            common = [q for q in d1.index if q in r1.index]
            if not common:
                continue
            s = sorted(set(d1[common].nlargest(5).index) & set(r1.nlargest(3).index))
            if not s and FALLBACK:
                cand = list(r1.nlargest(3).index)
                s = [max(cand, key=lambda q: d1.get(q, -9e9))] if cand else []
            if s:
                cur = s
            sel[T] = list(cur)
        w = pd.DataFrame(0.0, index=days, columns=ret_e.columns)
        for T in mes:
            nxt = days[days > T]
            if nxt.empty:
                break
            picks = []
            for ind in sel.get(T, []):
                target, lvl = ind, "18"
                if mode == "hier" and ind in CHILDREN and T in dc25.index:
                    kids = [k for k in CHILDREN[ind] if k in dc25.columns and np.isfinite(dc25.loc[T, k])]
                    if kids:
                        target = max(kids, key=lambda k: dc25.loc[T, k])
                        lvl = "25"
                df = cands.get((lvl, T, target))
                if df is None or df.empty:
                    continue
                mom = df["mom"]
                ref = mom if mom.notna().any() else df["beta"]
                picks.append(str((df["beta"].rank(pct=True) * 0.5 + ref.rank(pct=True) * 0.5).idxmax()))
            if not picks:
                continue
            w.loc[nxt[0]:, :] = 0.0
            for q in picks:
                w.loc[nxt[0]:, q] = 1.0 / len(picks)
        risky = portfolio_returns(w, ret_e).reindex(days).fillna(0.0)
        return exp * risky + (1 - exp) * bond.reindex(days).fillna(0.0)

    out = {}
    for mode, tag in (("base", "18 base"), ("hier", "18 select + L3 execute")):
        r = run(mode)
        seg = {}
        for name, (a, z) in {"2019-2023": ("2019-08-01", "2023-12-31"),
                             "2024-2026": ("2024-01-01", "2026-07-31"),
                             "full": ("2019-08-01", "2026-07-31")}.items():
            m = metrics(r.loc[a:z])
            seg[name] = {"sharpe": round(m["sharpe"], 3), "ann": round(m["annual_return"], 4),
                         "mdd": round(m["max_drawdown"], 4)}
        out[tag] = seg
        print(tag, json.dumps(seg, ensure_ascii=False), flush=True)
    (ROOT / "results/hier_l3_fallback.json").write_text(json.dumps(out, ensure_ascii=False, indent=1))


if __name__ == "__main__":
    main()
