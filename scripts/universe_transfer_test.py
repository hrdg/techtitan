"""实测：ΔAR 择时信号在不同横截面规模（10 行业 / 申万一级）下的可比性。

回答「同一套算法能否直接搬到 SW1 / SW2 / 主题」：核心是吸收比率的水平与阈值随资产数漂移。
"""
from __future__ import annotations

import os

import json
import sys
from pathlib import Path

import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))
from tech_rotation import absorption_and_concentration, delta_zscore  # noqa: E402

RAW = ROOT / "data" / "raw"
OUT = ROOT / "results"
SW_CACHE = Path(os.environ.get("SW_INDEX_CACHE_DIR", "/Users/hsh/Documents/Quant/行业轮动/data/raw/local_cache/sw_indices"))

SW1_2021 = ["801010", "801030", "801040", "801050", "801080", "801110", "801120", "801130",
            "801140", "801150", "801160", "801170", "801180", "801200", "801210", "801230",
            "801710", "801720", "801730", "801740", "801750", "801760", "801770", "801780",
            "801790", "801880", "801890", "801950", "801960", "801970", "801980"]


def ar_stats(ret: pd.DataFrame, m: int, window: int = 125) -> dict:
    mv = pd.DataFrame(100.0, index=ret.index, columns=ret.columns)
    ar, conc = absorption_and_concentration(ret, mv, window=window, m=m,
                                            use_mktcap=False, use_decay=True)
    dar = delta_zscore(ar).dropna()
    dar = dar[dar.index >= "2017-01-01"]
    return {
        "n_assets": ret.shape[1], "m": m,
        "AR_mean": round(float(ar.dropna().mean()), 4),
        "AR_p05": round(float(ar.dropna().quantile(0.05)), 4),
        "AR_p95": round(float(ar.dropna().quantile(0.95)), 4),
        "dAR_mean": round(float(dar.mean()), 3),
        "dAR_std": round(float(dar.std()), 3),
        "dAR_p90": round(float(dar.quantile(0.90)), 3),
        "dAR_p95": round(float(dar.quantile(0.95)), 3),
        "dAR_max": round(float(dar.max()), 3),
        "trigger_share_at_1.5": round(float((dar > 1.5).mean()), 4),
        "share_at_1.5_equals_10y_p90": round(float((dar > dar.quantile(0.90)).mean()), 4),
    }


def main() -> None:
    # --- 报告口径的 10 行业（价格面板）---
    df = pd.read_parquet(RAW / "industry_panel_final.parquet")
    df["date"] = pd.to_datetime(df["date"]).dt.tz_localize(None)
    ret10 = df.pivot(index="date", columns="code", values="ret")

    # --- 申万一级（本地缓存，31 个 2021 版行业的可得子集）---
    frames = {}
    for c in SW1_2021:
        p = SW_CACHE / f"{c}.csv"
        if not p.exists():
            continue
        s = pd.read_csv(p, parse_dates=["date"]).set_index("date")["close"]
        frames[c] = s
    px = pd.DataFrame(frames).sort_index()
    px = px.loc["2016-01-01":"2026-07-31"]
    keep = px.columns[px.notna().sum() > 2000]
    px = px[keep].ffill()
    ret1 = px.pct_change()
    print(f"SW1 面板: {ret1.shape[1]} 个行业, {ret1.index.min().date()}~{ret1.index.max().date()}")
    print("  含:", ", ".join(keep))

    rows = []
    for m in (2, 6):
        rows.append({"universe": "10 科技成长行业", **ar_stats(ret10, m)})
        rows.append({"universe": f"申万一级 {ret1.shape[1]} 行业", **ar_stats(ret1, m)})
    t = pd.DataFrame(rows)
    t.to_csv(OUT / "universe_transfer_test.csv", index=False)
    print()
    print(t.to_string(index=False))

    # --- ΔAR 择时套用到申万一级等权组合：能不能减少回撤？---
    b = pd.read_parquet(RAW / "benchmark_csi_daily.parquet")
    b["date"] = pd.to_datetime(b["date"]).dt.tz_localize(None)
    bond = b[b["code"] == "H11006"].set_index("date")["close"].pct_change()
    from tech_rotation import run_timing_overlay

    ew = ret1.mean(axis=1)
    ew = ew[ew.index >= "2017-01-01"]
    print("\n申万一级 27 行业等权 + ΔAR 择时:")
    print("%-14s %10s %10s %10s %10s" % ("配置", "年化", "波动", "最大回撤", "夏普"))
    from tech_rotation import metrics
    m0 = metrics(ew)
    print("%-14s %9.2f%% %9.2f%% %9.2f%% %10.2f" % ("买入持有", m0["annual_return"] * 100,
          m0["annual_vol"] * 100, m0["max_drawdown"] * 100, m0["sharpe"]))
    timing_rows = []
    for m in (2, 6):
        mv = pd.DataFrame(100.0, index=ret1.index, columns=ret1.columns)
        ar, _ = absorption_and_concentration(ret1, mv, window=125, m=m,
                                             use_mktcap=False, use_decay=True)
        dar = delta_zscore(ar)
        for th in (1.0, 1.5):
            t_, st = run_timing_overlay(dar, ew, bond.reindex(ew.index), th)
            mm = metrics(t_)
            timing_rows.append({"universe": "SW1-27", "m": m, "threshold": th,
                                "annual_return": round(mm["annual_return"], 4),
                                "annual_vol": round(mm["annual_vol"], 4),
                                "max_drawdown": round(mm["max_drawdown"], 4),
                                "sharpe": round(mm["sharpe"], 4),
                                "bond_share": round(float((st <= 0.5).mean()), 4)})
            print("%-14s %9.2f%% %9.2f%% %9.2f%% %10.2f" % (f"择时 m={m} th={th}",
                  mm["annual_return"] * 100, mm["annual_vol"] * 100,
                  mm["max_drawdown"] * 100, mm["sharpe"]))
    pd.DataFrame(timing_rows).to_csv(OUT / "universe_transfer_timing.csv", index=False)
    (OUT / "universe_transfer_test.json").write_text(
        json.dumps({"sw1_included": list(keep), "table": t.to_dict(orient="records")},
                   ensure_ascii=False, indent=2), encoding="utf-8")


if __name__ == "__main__":
    main()
