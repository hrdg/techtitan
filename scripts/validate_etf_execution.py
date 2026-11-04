"""v2 signals on industry indices, execution on the mapped tech ETFs at next open."""
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

CTA = Path("/Users/hsh/Documents/Quant/CTA策略/01_代码/strategies/22_xb_industry_cta/data/etf_qfq")
MAP = {"801081": "512480.XSHG", "801085": "159732.XSHE", "801735": "515790.XSHG",
       "801737": "159755.XSHE", "801102": "515880.XSHG", "801078": "562500.XSHG",
       "801101": "159852.XSHE", "801093": "516110.XSHG", "801745": "512660.XSHG"}
SPREAD_BP = 2.0


def main():
    p = pd.read_parquet(ROOT / "data/raw/industry_panel_latest.parquet")
    p["date"] = pd.to_datetime(p["date"]).dt.tz_localize(None)
    piv = lambda k: p.pivot(index="date", columns="code", values=k).sort_index()
    ret, pb, mv = piv("ret"), piv("pb"), piv("float_mv")
    rv = relative_valuation(pb)
    ar, conc = absorption_and_concentration(ret, mv)
    dc, dar = delta_zscore(conc), delta_zscore(ar)
    b = pd.read_parquet(ROOT / "data/raw/benchmark_csi_daily.parquet")
    b["date"] = pd.to_datetime(b["date"]).dt.tz_localize(None)
    bond = b[b["code"] == "H11006"].set_index("date")["close"].sort_index().pct_change()
    tip = pd.read_parquet(ROOT / "data/raw/tip_daily.parquet")
    tip["date"] = pd.to_datetime(tip["date"]).dt.tz_localize(None)
    tip = tip.set_index("date")["close"].sort_index()

    # ETF price panel (open + close) for the mapped industries
    panel = {}
    for ind, code in MAP.items():
        f = CTA / f"{code}.csv"
        if not f.exists():
            continue
        d = pd.read_csv(f, parse_dates=["date"]).set_index("date").sort_index()
        panel[ind] = d[["open", "close"]]
    codes = [c for c in MAP if c in panel]
    o = pd.DataFrame({c: panel[c]["open"] for c in codes}).sort_index()
    cl = pd.DataFrame({c: panel[c]["close"] for c in codes}).sort_index()

    START, END = "2022-01-01", "2026-08-31"
    days = ret.index[(ret.index >= START) & (ret.index <= END)]
    ta = tip.reindex(days).ffill()
    tg = (pd.concat([ta / ta.shift(k) - 1 for k in (21, 63, 126, 252)], axis=1).mean(axis=1) > 0).astype(float)
    ev = pd.Series(np.nan, index=days)
    ev[dar.reindex(days) > 1.5] = 0.0
    ev[dar.reindex(days) < 0] = 1.0
    exp = (ev.ffill().fillna(1.0) * tg).shift(1).fillna(0.0)

    s = pd.Series(days, index=days)
    mes = pd.DatetimeIndex(s.groupby([days.year, days.month]).last().values)
    weights = pd.DataFrame(0.0, index=days, columns=list(MAP))
    cur: list[str] = []
    for T in mes:
        nxt = days[days > T]
        if nxt.empty:
            break
        d1, r1 = dc.loc[T].dropna(), rv.loc[T].dropna()
        common = [c for c in d1.index if c in r1.index]
        if not common:
            continue
        x = sorted(set(d1[common].nlargest(4).index) & set(r1[common].nlargest(2).index))
        if x:
            cur = x
        if cur:
            weights.loc[nxt[0]:, :] = 0.0
            weights.loc[nxt[0]:, cur] = 1.0 / len(cur)

    # index (no cost) reference
    risky_i = portfolio_returns(weights, ret).reindex(days).fillna(0.0)
    r_idx = exp * risky_i + (1 - exp) * bond.reindex(days).fillna(0.0)

    # ETF execution: trades at open of the first day the weight/gate changes
    o = o.reindex(days).ffill()
    cl = cl.reindex(days).ffill()
    prev_close = cl.shift(1)
    r_full = cl / prev_close - 1                     # held both days
    r_buy = cl / o - 1                               # bought at open today
    r_sell = o / prev_close - 1                      # sold at open today
    w_prev = weights.shift(1).fillna(0.0)
    bond_r = bond.reindex(days).fillna(0.0)
    e_prev_all = exp.shift(1).fillna(1.0)
    ovn = (w_prev * (o / prev_close - 1)).sum(axis=1)          # prev close -> open
    intra = (weights * (cl / o - 1)).sum(axis=1)               # open -> close
    turnover = (weights - w_prev).abs().sum(axis=1)
    gate_turn = (exp - e_prev_all).abs().fillna(0.0)
    cost = (turnover + gate_turn) * SPREAD_BP / 1e4
    r_etf = e_prev_all * ovn + exp * intra + (1 - 0.5 * (e_prev_all + exp)) * bond_r - cost

    rows = []
    for tag, r in (("index signals + index returns", r_idx), ("index signals + ETF T+1 open", r_etf)):
        m = metrics(r.dropna())
        rows.append({"variant": tag, "sharpe": m["sharpe"], "ann": m["annual_return"],
                     "vol": m["annual_vol"], "mdd": m["max_drawdown"], "calmar": m["calmar"]})
    table = pd.DataFrame(rows)
    yearly = pd.DataFrame({"index": (1 + r_idx).groupby(r_idx.index.year).prod() - 1,
                           "etf": (1 + r_etf).groupby(r_etf.index.year).prod() - 1})
    table.to_csv(ROOT / "results/etf_execution_summary.csv", index=False)
    yearly.to_csv(ROOT / "results/etf_execution_yearly.csv")
    pd.DataFrame({"index": r_idx, "etf": r_etf}).to_csv(ROOT / "results/etf_execution_returns.csv")
    print(table.to_string(index=False, float_format=lambda x: f"{x:.4f}"))
    print("\nyearly %\n", (yearly * 100).round(1).to_string())
    print(f"\navg daily turnover {turnover.mean():.3f}, gate turns {gate_turn.sum():.0f}, spread {SPREAD_BP}bp/side")


if __name__ == "__main__":
    main()
