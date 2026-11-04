"""Index signal + ETF execution: pick, per industry, the max-beta ETF among the
top-n most correlated ETFs over the trailing 250 trading days."""
from __future__ import annotations

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

HA = Path("/Users/hsh/Documents/Quant/因子择时/HA_market_attention_etf_momentum")
WINDOW = 250


def main(n_corr: int = 8, min_corr: float = 0.80):
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

    # choose ETF per industry and month
    choice: dict[tuple[pd.Timestamp, str], str] = {}
    for T in mes:
        hist = ret_e.loc[:T].tail(WINDOW)
        if len(hist) < WINDOW:
            continue
        for ind in ret_i.columns:
            y = ret_i[ind].loc[:T].tail(WINDOW)
            if y.notna().sum() < WINDOW * 0.9:
                continue
            x = hist.reindex(y.index)
            ok = x.notna().all()
            if ok.sum() < 30:
                continue
            xs = x.loc[:, ok]
            corr = xs.corrwith(y).dropna()
            corr = corr[corr >= min_corr]
            if corr.empty:
                continue
            top = corr.nlargest(n_corr).index
            var = y.var()
            beta = xs[top].apply(lambda col: col.cov(y) / var).dropna()
            if beta.empty:
                continue
            choice[(T, ind)] = str(beta.idxmax())

    w = pd.DataFrame(0.0, index=days, columns=ret_e.columns)
    for T in mes:
        nxt = days[days > T]
        if nxt.empty:
            break
        picks = [choice.get((T, ind)) for ind in sel.get(T, [])]
        picks = [p for p in picks if p is not None]
        if not picks:
            continue
        w.loc[nxt[0]:, :] = 0.0
        for p in picks:
            w.loc[nxt[0]:, p] = 1.0 / len(picks)

    def run(tag, rf, wts):
        ris = portfolio_returns(wts, rf.reindex(columns=wts.columns)).reindex(days).fillna(0.0)
        r = exp * ris + (1 - exp) * bond.reindex(days).fillna(0.0)
        m = metrics(r.dropna())
        tv = wts.diff().abs().sum(axis=1)
        print(f"{tag:52s} SR={m['sharpe']:.3f} ann={m['annual_return']*100:5.1f}% "
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
    r_etf = run(f"index signal + corr-top{n_corr} then max-beta ETF", ret_e, w)

    yearly = pd.DataFrame({"index": (1 + r_idx).groupby(r_idx.index.year).prod() - 1,
                           "etf": (1 + r_etf).groupby(r_etf.index.year).prod() - 1})
    pd.DataFrame({"index": r_idx, "etf": r_etf}).to_csv(ROOT / "results/corr_beta_exec_returns.csv")
    yearly.to_csv(ROOT / "results/corr_beta_exec_yearly.csv")
    print("\nyearly %\n", (yearly * 100).round(1).to_string())
    picks = pd.DataFrame([{"date": k[0], "industry": k[1], "etf": v} for k, v in choice.items()])
    picks.to_csv(ROOT / "results/corr_beta_selection.csv", index=False)
    print("\nselections per industry (last month):")
    last = picks[picks.date == picks.date.max()]
    print(last.to_string(index=False))


if __name__ == "__main__":
    main()
