"""Run the 科技成长景气轮动与量化择时 model reproduction and dump result artifacts.

Usage: python scripts/run_reproduction.py [--panel proxy|official]
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from tech_rotation import (  # noqa: E402
    PortfolioSpec,
    absorption_and_concentration,
    build_daily_weights,
    delta_zscore,
    metrics,
    nav_curve,
    portfolio_returns,
    relative_valuation,
    run_timing_overlay,
)

RAW = ROOT / "data" / "raw"
OUT = ROOT / "results"
BACKTEST_START, BACKTEST_END = "2017-01-01", "2026-07-31"
INSAMPLE_END = "2024-12-31"
OOS_START = "2025-01-01"
BENCH_ORDER = ["中证A500", "科技50", "行业等权", "高估值", "高集中度", "高集中度高估值"]


def _naive(s):
    s = pd.to_datetime(s)
    if isinstance(s.dtype, pd.DatetimeTZDtype):
        s = s.dt.tz_convert("Asia/Shanghai").dt.tz_localize(None)
    return s.astype("datetime64[ns]")


def load_panel(kind: str):
    if kind in ("proxy", "final"):
        fname = "industry_panel_final.parquet" if kind == "final" else "industry_panel_proxy.parquet"
        df = pd.read_parquet(RAW / fname)
        df["date"] = _naive(df["date"])
        df = df.sort_values(["date", "code"])
        ret = df.pivot(index="date", columns="code", values="ret")
        pb = df.pivot(index="date", columns="code", values="pb")
        fmv = df.pivot(index="date", columns="code", values="float_mv")
        names = df.drop_duplicates("code").set_index("code")["name"].to_dict()
    else:
        df = pd.read_parquet(RAW / "sw_l2_daily.parquet")
        df["date"] = _naive(df["date"])
        df["code"] = df["code"].astype(str)
        df = df.sort_values(["date", "code"])
        ret = df.pivot(index="date", columns="code", values="close").pct_change()
        pb = df.pivot(index="date", columns="code", values="pb")
        fmv = df.pivot(index="date", columns="code", values="float_mktcap_yi")
        names = df.drop_duplicates("code").set_index("code")["name"].to_dict()
    return ret, pb, fmv, names


def benchmarks(dates: pd.DatetimeIndex, ret: pd.DataFrame):
    b = pd.read_parquet(RAW / "benchmark_csi_daily.parquet")
    b["date"] = _naive(b["date"])
    out = {}
    for code, label in [("000510", "中证A500"), ("931380", "科技50")]:
        s = b[b["code"] == code].set_index("date")["close"]
        out[label] = s.reindex(dates).pct_change()
    out["行业等权"] = ret.mean(axis=1)
    bond = b[b["code"] == "H11006"].set_index("date")["close"]
    return out, bond.reindex(dates).pct_change()


def main() -> None:
    global BACKTEST_START
    ap = argparse.ArgumentParser()
    ap.add_argument("--panel", default="final", choices=["final", "proxy", "official"])
    ap.add_argument("--threshold", type=float, default=1.5)
    ap.add_argument("--start", default=BACKTEST_START, help="backtest start date")
    args = ap.parse_args()
    BACKTEST_START = args.start
    OUT.mkdir(exist_ok=True)

    ret, pb, fmv, names = load_panel(args.panel)
    dates = ret.index
    print("panel", args.panel, ret.shape, dates.min().date(), dates.max().date())

    ar, conc = absorption_and_concentration(ret, fmv)
    d_conc = delta_zscore(conc)
    d_ar = delta_zscore(ar)
    rv = relative_valuation(pb)
    print("first valid: C", conc.notna().any(axis=1).idxmax().date(),
          "| dC", d_conc.notna().any(axis=1).idxmax().date(),
          "| RV", rv.notna().any(axis=1).idxmax().date(),
          "| dAR", d_ar.dropna().index.min().date())

    bench, bond = benchmarks(dates, ret)
    specs = {
        "高估值": PortfolioSpec(k1=2, k2=4, name="value"),
        "高集中度": PortfolioSpec(k1=2, k2=4, name="concentration"),
        "高集中度高估值": PortfolioSpec(k1=2, k2=4, name="combined"),
    }
    rows, curves, holdings_log = [], {}, {}
    for label, spec in specs.items():
        w = build_daily_weights(d_conc, rv, dates, spec, BACKTEST_START, BACKTEST_END)
        r = portfolio_returns(w, ret)
        r = r[r.index >= BACKTEST_START]
        rows.append({"strategy": label, "timing": "否", **metrics(r)})
        curves[label] = nav_curve(r)
        timed, state = run_timing_overlay(d_ar, r, bond.reindex(r.index), args.threshold)
        rows.append({"strategy": label, "timing": "是", **metrics(timed)})
        curves[label + "_择时"] = nav_curve(timed)
        if spec.name == "combined":
            hold = w[w.sum(axis=1) > 0].apply(lambda s: ",".join(sorted(s[s > 0].index)), axis=1)
            holdings_log["高集中度高估值"] = hold[hold.ne(hold.shift())].dropna()
            combined = (w, r, state)

    for label, series in bench.items():
        s = series[series.index >= BACKTEST_START]
        rows.append({"strategy": label, "timing": "否", **metrics(s)})
        curves[label] = nav_curve(s)

    table = pd.DataFrame(rows)[["strategy", "timing", "cum_return", "annual_return",
                                "annual_vol", "sharpe", "sharpe_arith", "max_drawdown",
                                "calmar", "n_days"]]
    suffix = args.panel if args.start == "2017-01-01" else f"{args.panel}_{args.start[:7]}"
    table.to_csv(OUT / f"table4_5_{suffix}.csv", index=False)
    print(table.to_string(float_format=lambda x: f"{x:,.4f}"))

    nav = pd.DataFrame(curves)
    nav.to_csv(OUT / f"nav_{suffix}.csv")

    # ---- threshold sensitivity ----
    w_c, r_c, _ = combined
    trows = []
    for th in [0.0, 0.25, 0.5, 0.75, 1.0, 1.25, 1.5, 1.75, 2.0]:
        timed, _ = run_timing_overlay(d_ar, r_c, bond.reindex(r_c.index), th)
        full = metrics(timed)
        ins = metrics(timed[timed.index <= INSAMPLE_END])
        oos = metrics(timed[timed.index >= OOS_START])
        trows.append({"threshold": th,
                      **{f"full_{k}": v for k, v in full.items()},
                      **{f"in_{k}": v for k, v in ins.items()},
                      **{f"oos_{k}": v for k, v in oos.items()}})
    tdf = pd.DataFrame(trows)
    tdf.to_csv(OUT / f"threshold_sensitivity_{suffix}.csv", index=False)
    print(tdf[["threshold", "full_annual_return", "full_sharpe", "full_max_drawdown", "full_calmar"]]
          .to_string(index=False, float_format=lambda x: f"{x:,.4f}"))

    # ---- k1 x k2 grid ----
    grid = []
    for k1 in range(1, 9):
        for k2 in range(1, 9):
            spec = PortfolioSpec(k1=k1, k2=k2, name="combined")
            w = build_daily_weights(d_conc, rv, dates, spec, BACKTEST_START, BACKTEST_END)
            r = portfolio_returns(w, ret)
            r = r[r.index >= BACKTEST_START]
            timed, _ = run_timing_overlay(d_ar, r, bond.reindex(r.index), args.threshold)
            grid.append({"k1": k1, "k2": k2,
                         **{f"full_{k}": v for k, v in metrics(timed).items()},
                         **{f"in_{k}": v for k, v in metrics(timed[timed.index <= INSAMPLE_END]).items()},
                         **{f"oos_{k}": v for k, v in metrics(timed[timed.index >= OOS_START]).items()}})
    gdf = pd.DataFrame(grid)
    gdf.to_csv(OUT / f"grid_k1k2_{suffix}.csv", index=False)
    best = gdf.loc[gdf["full_sharpe"].idxmax()]
    best_in = gdf.loc[gdf["in_sharpe"].idxmax()]
    best_oos = gdf.loc[gdf["oos_sharpe"].idxmax()]
    print("best k1,k2 (full sharpe):", int(best.k1), int(best.k2),
          "| in-sample:", int(best_in.k1), int(best_in.k2),
          "| oos:", int(best_oos.k1), int(best_oos.k2))

    holdings_log["高集中度高估值"].to_csv(OUT / f"holdings_{suffix}.csv")
    pd.DataFrame({"AR": ar, "dAR": d_ar}).to_csv(OUT / f"absorption_{suffix}.csv")
    conc.to_csv(OUT / f"concentration_{suffix}.csv")
    rv.to_csv(OUT / f"relative_valuation_{suffix}.csv")

    summary = {
        "panel": args.panel,
        "threshold": args.threshold,
        "first_valid": {"C": str(conc.notna().any(axis=1).idxmax().date()),
                        "dC": str(d_conc.notna().any(axis=1).idxmax().date()),
                        "RV": str(rv.notna().any(axis=1).idxmax().date()),
                        "dAR": str(d_ar.dropna().index.min().date())},
        "best_k_in_sample": [int(best_in.k1), int(best_in.k2)],
        "best_k_full": [int(best.k1), int(best.k2)],
        "best_k_oos": [int(best_oos.k1), int(best_oos.k2)],
        "best_threshold_full": float(tdf.loc[tdf["full_sharpe"].idxmax(), "threshold"]),
        "best_threshold_oos": float(tdf.loc[tdf["oos_sharpe"].idxmax(), "threshold"]),
    }
    (OUT / f"summary_{suffix}.json").write_text(
        json.dumps(summary, ensure_ascii=False, indent=2), encoding="utf-8")


if __name__ == "__main__":
    main()
