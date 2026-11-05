"""Single-implementation comparison of the 10- and 18-industry tech pools.

Both pools go through exactly the same code path: PCA/AR on the industry panel,
monthly selection, ETF execution (corr top-8 then 50/50 beta+momentum rank),
and the calendar TIP x deltaAR gate.  Only the panel and k differ.
"""
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
WINDOW, N_CORR, MIN_CORR = 250, 8, 0.80
START, END = "2019-08-01", "2026-07-31"
import os
FALLBACK = os.environ.get("FB") == "1"


def load_panel(path: Path):
    p = pd.read_parquet(path)
    p["date"] = pd.to_datetime(p["date"]).dt.tz_localize(None)
    piv = lambda k: p.pivot(index="date", columns="code", values=k).sort_index()
    ret, pb, mv = piv("ret"), piv("pb"), piv("float_mv")
    for f in (ret, pb, mv):
        f.columns = f.columns.astype(str)
    return ret, pb, mv


def main() -> None:
    d = pd.DatetimeIndex(np.load(HA / "research/runs/ha_chart19_frequency_v1/data/dates.npy"))
    codes = np.load(HA / "research/runs/ha_chart19_frequency_v1/data/codes.npy", allow_pickle=True).astype(str)
    px = pd.read_parquet(HA / "research/runs/ha_chart19_frequency_v1/data/adj_close_snapshot.parquet").reindex(index=d, columns=codes)
    ret_e = px.pct_change(fill_method=None)
    comp = pd.read_parquet(HA / "research/runs/ha_oos_tip136u_gate_30_v1/outputs/composite_scores_all.parquet")
    comp["date"] = pd.to_datetime(comp["date"])
    comp_p = comp.pivot(index="date", columns="code", values="composite").sort_index()

    b = pd.read_parquet(ROOT / "data/raw/benchmark_csi_daily.parquet")
    b["date"] = pd.to_datetime(b["date"]).dt.tz_localize(None)
    bond = b[b["code"] == "H11006"].set_index("date")["close"].sort_index().pct_change()
    tip = pd.read_parquet(ROOT / "data/raw/tip_daily.parquet")
    tip["date"] = pd.to_datetime(tip["date"]).dt.tz_localize(None)
    tip = tip.set_index("date")["close"].sort_index()

    results = {}
    for tag, panel, ks in (
        ("18tech", ROOT / "data/raw/industry_panel_18.parquet", [(5, 3)]),
        
    ):
        ret, pb, mv = load_panel(panel)
        rv = relative_valuation(pb)
        ar, conc = absorption_and_concentration(ret, mv)
        dc, dar = delta_zscore(conc), delta_zscore(ar)
        days = ret.index[(ret.index >= START) & (ret.index <= END)]
        ta = tip.reindex(days).ffill()
        tg = (pd.concat([ta / ta.shift(k) - 1 for k in (21, 63, 126, 252)], axis=1).mean(axis=1) > 0).astype(float)
        ev = pd.Series(np.nan, index=days)
        ev[dar.reindex(days) > 1.5] = 0.0
        ev[dar.reindex(days) < 0] = 1.0
        exp = (ev.ffill().fillna(1.0) * tg).shift(1).fillna(0.0)
        mes = pd.DatetimeIndex(pd.Series(days, index=days).groupby([days.year, days.month]).last().values)

        # ETF candidates via a single numpy correlation path
        etf_cols = np.asarray(ret_e.columns)
        cands = {}
        for T in mes:
            rows = ret_e.index[ret_e.index <= T][-WINDOW:]
            if len(rows) < WINDOW:
                continue
            H = ret_e.reindex(rows).to_numpy(float)
            cd = comp_p.index[comp_p.index <= T]
            cs = comp_p.loc[cd[-1]] if len(cd) else None
            for ind in ret.columns:
                y = ret[ind].reindex(rows).to_numpy(float)
                mr = np.isfinite(y)
                H2, y2 = H[mr], y[mr]
                if len(y2) < 100:
                    continue
                cm = np.isfinite(H2).all(axis=0) & (H2.std(axis=0) > 0)
                if cm.sum() < 50:
                    continue
                Hm, ym = H2[:, cm], y2
                Hs = (Hm - Hm.mean(0)) / Hm.std(0)
                ys = (ym - ym.mean()) / ym.std()
                corr = Hs.T @ ys / len(ys)
                keep = np.where(corr >= MIN_CORR)[0]
                if len(keep) < 3:
                    continue
                pick = keep[np.argsort(-corr[keep])][:N_CORR]
                beta = (Hm[:, pick].T @ ym / len(ym) - Hm[:, pick].mean(0) * ym.mean()) / ym.var()
                cols = etf_cols[cm][pick]
                mom = cs.reindex(cols).to_numpy() if cs is not None else np.full(len(pick), np.nan)
                cands[(T, ind)] = pd.DataFrame({"beta": beta, "mom": mom}, index=cols)

        for k1, k2 in ks:
            sel, cur = {}, []
            for T in mes:
                d1, r1 = dc.loc[T].dropna(), rv.loc[T].dropna()
                common = [q for q in d1.index if q in r1.index]
                if not common:
                    continue
                s = sorted(set(d1[common].nlargest(k1).index) & set(r1.nlargest(k2).index))
                if not s and FALLBACK:
                    cand = list(r1.nlargest(k2).index)
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
                    df = cands.get((T, ind))
                    if df is None or df.empty:
                        continue
                    mom = df["mom"]
                    ref = mom if mom.notna().any() else df["beta"]
                    score = df["beta"].rank(pct=True) * 0.5 + ref.rank(pct=True) * 0.5
                    picks.append(str(score.idxmax()))
                if not picks:
                    continue
                w.loc[nxt[0]:, :] = 0.0
                for q in picks:
                    w.loc[nxt[0]:, q] = 1.0 / len(picks)
            risky = portfolio_returns(w, ret_e).reindex(days).fillna(0.0)
            r = exp * risky + (1 - exp) * bond.reindex(days).fillna(0.0)
            key = f"{tag}_k{k1}_{k2}"
            seg = {}
            for name, (a, z) in {"2019-2023": ("2019-08-01", "2023-12-31"),
                                 "2024-2026": ("2024-01-01", "2026-07-31"),
                                 "full": (START, END)}.items():
                m = metrics(r.loc[a:z])
                seg[name] = {"sharpe": round(m["sharpe"], 3), "ann": round(m["annual_return"], 4),
                             "mdd": round(m["max_drawdown"], 4)}
            yearly = {int(y): round(float(v), 4) for y, v in ((1 + r).groupby(r.index.year).prod() - 1).items()}
            freq = pd.Series([i for T in sel for i in sel[T]]).value_counts()
            results[key] = {"segments": seg, "yearly": yearly,
                            "industry_freq": {str(k): int(v) for k, v in freq.items()}}
            print(key, json.dumps(seg, ensure_ascii=False), flush=True)

    (ROOT / "results/fallback_etf_test.json").write_text(json.dumps(results, ensure_ascii=False, indent=1))
    print("\nyearly")
    for k, v in results.items():
        print(k, v["yearly"])


if __name__ == "__main__":
    main()
