"""Rank correlated ETFs by beta and the HA 77-factor composite momentum."""
from __future__ import annotations

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


def main():
    d = pd.DatetimeIndex(np.load(HA / "research/runs/ha_chart19_frequency_v1/data/dates.npy"))
    codes = np.load(HA / "research/runs/ha_chart19_frequency_v1/data/codes.npy", allow_pickle=True).astype(str)
    px = pd.read_parquet(HA / "research/runs/ha_chart19_frequency_v1/data/adj_close_snapshot.parquet").reindex(index=d, columns=codes)
    ret_e = px.pct_change(fill_method=None)
    comp = pd.read_parquet(HA / "research/runs/ha_oos_tip136u_gate_30_v1/outputs/composite_scores_all.parquet")
    comp["date"] = pd.to_datetime(comp["date"])
    comp_p = comp.pivot(index="date", columns="code", values="composite").sort_index()

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

    def selection(k1, k2):
        out, cur = {}, []
        for T in mes:
            d1, r1 = dc.loc[T].dropna(), rv.loc[T].dropna()
            common = [x for x in d1.index if x in r1.index]
            if not common:
                continue
            x = sorted(set(d1[common].nlargest(k1).index) & set(r1.nlargest(k2).index))
            if x:
                cur = x
            out[T] = list(cur)
        return out

    cands: dict[tuple[pd.Timestamp, str], pd.DataFrame] = {}
    for T in mes:
        hist = ret_e.loc[:T].tail(WINDOW)
        if len(hist) < WINDOW:
            continue
        cdate = comp_p.index[comp_p.index <= T]
        csnap = comp_p.loc[cdate[-1]] if len(cdate) else pd.Series(dtype=float)
        for ind in ret_i.columns:
            y = ret_i[ind].loc[:T].tail(WINDOW)
            x = hist.reindex(y.index)
            ok = x.notna().all() & (x.std() > 0)
            sub = x.loc[:, ok]
            if sub.shape[1] < 3:
                continue
            corr = sub.corrwith(y).dropna()
            corr = corr[corr >= MIN_CORR].nlargest(N_CORR)
            if corr.empty:
                continue
            var = y.var()
            beta = pd.Series({c: sub[c].cov(y) / var for c in corr.index})
            mom = csnap.reindex(corr.index)
            cands[(T, ind)] = pd.DataFrame({"corr": corr, "beta": beta, "mom": mom})

    rules = {
        "max_beta": lambda df: df["beta"].idxmax(),
        "max_momentum": lambda df: (df["mom"] if df["mom"].notna().any() else df["beta"]).idxmax(),
        "blend_50_50": lambda df: (
            df["beta"].rank(pct=True) * 0.5
            + (df["mom"] if df["mom"].notna().any() else df["beta"]).rank(pct=True) * 0.5
        ).idxmax(),
        "mom_positive_then_beta": lambda df: (
            df.loc[df["mom"] > 0, "beta"].idxmax()
            if (df["mom"] > 0).any()
            else df["beta"].idxmax()
        ),
    }

    def weights_for(rule, sel):
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
                picks.append(rule(df))
            if not picks:
                continue
            w.loc[nxt[0]:, :] = 0.0
            for x in picks:
                w.loc[nxt[0]:, x] = 1.0 / len(picks)
        return w

    rows, curves = [], {}
    for k1, k2 in ((4, 2), (3, 2), (4, 3), (3, 3)):
        sel = selection(k1, k2)
        rule = rules["blend_50_50"]
        w = weights_for(rule, sel)
        ris = portfolio_returns(w, ret_e).reindex(days).fillna(0.0)
        r = exp * ris + (1 - exp) * bond.reindex(days).fillna(0.0)
        m = metrics(r.dropna())
        te = metrics(r[r.index >= "2021-01-01"])
        curves[f"k{k1}_{k2}"] = r
        rows.append({"k1_dC": k1, "k2_rv": k2, "full_sharpe": m["sharpe"],
                     "full_ann": m["annual_return"], "test_sharpe": te["sharpe"],
                     "test_ann": te["annual_return"], "test_mdd": te["max_drawdown"]})
    table = pd.DataFrame(rows).sort_values("full_sharpe", ascending=False)
    yearly = pd.DataFrame({k: (1 + v).groupby(v.index.year).prod() - 1 for k, v in curves.items()})
    table.to_csv(ROOT / "results/etf_beta_momentum_rules.csv", index=False)
    yearly.to_csv(ROOT / "results/etf_beta_momentum_yearly.csv")
    pd.DataFrame(curves).to_csv(ROOT / "results/etf_beta_momentum_returns.csv")
    print(table.to_string(index=False, float_format=lambda x: f"{x:.4f}"))
    print("\nyearly %\n", (yearly * 100).round(1).to_string())
    print("\ncandidate coverage: %d (T,industry) pairs" % len(cands))


if __name__ == "__main__":
    main()
