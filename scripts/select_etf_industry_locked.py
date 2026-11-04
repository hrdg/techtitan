"""Index signal + ETF execution, restricted to same-industry candidates.

Per industry, candidates come from the SW2 ETF map (2-3 products).  Each month:
keep candidates with >=250d history and trailing correlation >= threshold, then
pick the one whose 250d beta is closest to 1 (most faithful tracker).
"""
from __future__ import annotations

import sys
import warnings
from pathlib import Path

import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))
warnings.filterwarnings("ignore", category=RuntimeWarning)
from tech_rotation import (  # noqa: E402
    absorption_and_concentration,
    delta_zscore,
    metrics,
    portfolio_returns,
    relative_valuation,
)

HA = Path("/Users/hsh/Documents/Quant/因子择时/HA_market_attention_etf_momentum")
WINDOW = 250
MIN_CORR = 0.80

CANDIDATES = {
    "801081": ["512480.XSHG", "159995.XSHE", "512760.XSHG", "588200.XSHG"],
    "801085": ["159732.XSHE", "562950.XSHG"],
    "801735": ["515790.XSHG", "159857.XSHE"],
    "801737": ["159755.XSHE", "561910.XSHG", "159566.XSHE"],
    "801102": ["515880.XSHG", "515050.XSHG"],
    "801078": ["562500.XSHG", "159530.XSHE"],
    "801101": ["512720.XSHG", "159852.XSHE"],
    "801103": ["515230.XSHG"],
    "801093": ["516110.XSHG", "159565.XSHE"],
    "801745": ["512660.XSHG", "512710.XSHG"],
}


def main():
    d = pd.DatetimeIndex(np.load(HA / "research/runs/ha_chart19_frequency_v1/data/dates.npy"))
    codes = np.load(HA / "research/runs/ha_chart19_frequency_v1/data/codes.npy", allow_pickle=True).astype(str)
    px = pd.read_parquet(HA / "research/runs/ha_chart19_frequency_v1/data/adj_close_snapshot.parquet").reindex(index=d, columns=codes)
    ret_e = px.pct_change(fill_method=None)

    p = pd.read_parquet(ROOT / "data/raw/industry_panel_latest.parquet")
    p["date"] = pd.to_datetime(p["date"]).dt.tz_localize(None)
    piv = lambda k: p.pivot(index="date", columns="code", values=k).sort_index()
    ret_i, pb, mv = piv("ret"), piv("pb"), piv("float_mv")
    for f in (ret_i, pb, mv):
        f.columns = f.columns.astype(str)
    rv = relative_valuation(pb)
    ar, conc = absorption_and_concentration(ret_i, mv)
    dc, dar = delta_zscore(conc), delta_zscore(ar)
    b = pd.read_parquet(ROOT / "data/raw/benchmark_csi_daily.parquet")
    b["date"] = pd.to_datetime(b["date"]).dt.tz_localize(None)
    bond = b[b["code"] == "H11006"].set_index("date")["close"].sort_index().pct_change()
    tip = pd.read_parquet(ROOT / "data/raw/tip_daily.parquet")
    tip["date"] = pd.to_datetime(tip["date"]).dt.tz_localize(None)
    tip = tip.set_index("date")["close"].sort_index()

    days = ret_i.index[(ret_i.index >= "2019-08-01") & (ret_i.index <= "2026-07-31")]
    ta = tip.reindex(days).ffill()
    tg = (pd.concat([ta / ta.shift(k) - 1 for k in (21, 63, 126, 252)], axis=1).mean(axis=1) > 0).astype(float)
    ev = pd.Series(np.nan, index=days)
    ev[dar.reindex(days) > 1.5] = 0.0
    ev[dar.reindex(days) < 0] = 1.0
    exp = (ev.ffill().fillna(1.0) * tg).shift(1).fillna(0.0)

    s = pd.Series(days, index=days)
    mes = pd.DatetimeIndex(s.groupby([days.year, days.month]).last().values)
    sel: dict[pd.Timestamp, list[str]] = {}
    cur: list[str] = []
    for T in mes:
        d1, r1 = dc.loc[T].dropna(), rv.loc[T].dropna()
        common = [x for x in d1.index if x in r1.index]
        if not common:
            continue
        x = sorted(set(d1[common].nlargest(4).index) & set(r1.nlargest(2).index))
        if x:
            cur = x
        sel[T] = list(cur)

    choice: dict[tuple[pd.Timestamp, str], str] = {}
    diag = []
    for T in mes:
        for ind in ret_i.columns:
            cands = [c for c in CANDIDATES.get(ind, []) if c in ret_e.columns]
            if not cands:
                continue
            picked = None
            for win in (250, 120, 60):
                y = ret_i[ind].loc[:T].tail(win)
                if y.notna().sum() < win * 0.8:
                    continue
                x = ret_e.loc[y.index, cands]
                ok = x.notna().all() & (x.std() > 0)
                sub = [c for c in cands if ok.get(c, False)]
                if not sub:
                    continue
                yc = x[sub].corrwith(y).dropna()
                yc = yc[yc >= MIN_CORR]
                if yc.empty:
                    continue
                var = y.var()
                betas = {c: x.loc[y.index, c].cov(y) / var for c in yc.index}
                best = min(betas, key=lambda c: abs(betas[c] - 1.0))
                picked = (best, float(yc[best]), float(betas[best]), win, len(sub))
                break
            if picked is None:
                continue
            choice[(T, ind)] = picked[0]
            diag.append({"date": T, "industry": ind, "etf": picked[0], "corr": picked[1],
                         "beta": picked[2], "window": picked[3], "n_candidates": picked[4]})

    w = pd.DataFrame(0.0, index=days, columns=ret_e.columns)
    for T in mes:
        nxt = days[days > T]
        if nxt.empty:
            break
        picks = [choice.get((T, ind)) for ind in sel.get(T, [])]
        picks = [x for x in picks if x is not None]
        if not picks:
            continue
        w.loc[nxt[0]:, :] = 0.0
        for x in picks:
            w.loc[nxt[0]:, x] = 1.0 / len(picks)

    def run(tag, rf, wts):
        ris = portfolio_returns(wts, rf.reindex(columns=wts.columns)).reindex(days).fillna(0.0)
        r = exp * ris + (1 - exp) * bond.reindex(days).fillna(0.0)
        m = metrics(r.dropna())
        tv = wts.diff().abs().sum(axis=1)
        print(f"{tag:56s} SR={m['sharpe']:.3f} ann={m['annual_return']*100:5.1f}% "
              f"mdd={m['max_drawdown']*100:6.1f}% to={tv.sum()/(len(days)/250):4.1f}x")
        return r

    wi = pd.DataFrame(0.0, index=days, columns=ret_i.columns)
    for T in mes:
        nxt = days[days > T]
        if nxt.empty:
            break
        inds = sel.get(T, [])
        if not inds:
            continue
        wi.loc[nxt[0]:, :] = 0.0
        for ind in inds:
            wi.loc[nxt[0]:, ind] = 1.0 / len(inds)
    r_idx = run("index signal + index returns", ret_i, wi)
    r_etf = run("index signal + industry-locked beta~1 ETF", ret_e, w)

    yr = pd.DataFrame({"index": (1 + r_idx).groupby(r_idx.index.year).prod() - 1,
                       "etf": (1 + r_etf).groupby(r_etf.index.year).prod() - 1})
    pd.DataFrame(diag).to_csv(ROOT / "results/industry_locked_selection.csv", index=False)
    pd.DataFrame({"index": r_idx, "etf": r_etf}).to_csv(ROOT / "results/industry_locked_returns.csv")
    yr.to_csv(ROOT / "results/industry_locked_yearly.csv")
    print("\nyearly %\n", (yr * 100).round(1).to_string())
    dd = pd.DataFrame(diag)
    print("\nbeta stats: mean %.2f, share within [0.8,1.2] %.2f" % (dd.beta.mean(), ((dd.beta > 0.8) & (dd.beta < 1.2)).mean()))
    print("corr mean %.3f" % dd.corr.mean())
    print("\nlast month picks:")
    print(dd[dd.date == dd.date.max()][["industry", "etf", "corr", "beta"]].to_string(index=False))


if __name__ == "__main__":
    main()
