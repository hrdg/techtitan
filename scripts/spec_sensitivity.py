"""归因：DEC-003 / DEC-002 的因子口径变体对照。

判据只用研报中与收益无关的**规格侧**证据：
- 图 8：第二主成分吸收比率在 0~0.3、前两个主成分合计在 0.7~0.9；
- 2.4 节持仓描述（2020-2021 光伏设备+电池、2023 通信设备+IT服务Ⅱ、2024H2 消费电子/通信设备/半导体）；
- 交集非空率（图 7 显示组合长期持有 1-2 个行业）。
收益水平仅作参考，不作为选择依据。

输出：results/spec_sensitivity.csv
"""
from __future__ import annotations

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
    portfolio_returns,
    relative_valuation,
    run_timing_overlay,
)

RAW = ROOT / "data" / "raw"
OUT = ROOT / "results"
BACKTEST_START = "2017-01-01"


def main() -> None:
    df = pd.read_parquet(RAW / "industry_panel_final.parquet")
    df["date"] = pd.to_datetime(df["date"]).dt.tz_localize(None)
    ret = df.pivot(index="date", columns="code", values="ret")
    pb = df.pivot(index="date", columns="code", values="pb")
    fmv = df.pivot(index="date", columns="code", values="float_mv")

    b = pd.read_parquet(RAW / "benchmark_csi_daily.parquet")
    b["date"] = pd.to_datetime(b["date"]).dt.tz_localize(None)
    bond = b[b["code"] == "H11006"].set_index("date")["close"].reindex(ret.index).pct_change()

    variants = {
        "V0_市值×衰减（当前 DEC-003）": dict(use_mktcap=True, use_decay=True, standardize=False),
        "V1_仅衰减": dict(use_mktcap=False, use_decay=True, standardize=False),
        "V2_仅市值": dict(use_mktcap=True, use_decay=False, standardize=False),
        "V3_市值×衰减+等方差标准化": dict(use_mktcap=True, use_decay=True, standardize=True),
        "V4_原始收益（无加权）": dict(use_mktcap=False, use_decay=False, standardize=False),
    }
    rv_variants = {"R0_剔除本行业（DEC-002）": True, "R1_全部行业": False}

    rows = []
    for vname, kw in variants.items():
        # 需要 AR 分解时单独取第一主成分
        ar, conc = absorption_and_concentration(ret, fmv, **kw)
        ar1, _ = absorption_and_concentration(ret, fmv, m=1, **kw)
        dc = delta_zscore(conc)
        for rname, loo in rv_variants.items():
            rv = relative_valuation(pb, leave_one_out=loo)
            w = build_daily_weights(dc, rv, ret.index, PortfolioSpec(2, 4, "combined"),
                                    BACKTEST_START, "2026-07-31")
            r = portfolio_returns(w, ret)
            r = r[r.index >= BACKTEST_START]
            m = metrics(r)
            # 交集非空率
            me = pd.Series(dc.index, index=dc.index).groupby(
                [dc.index.year, dc.index.month]).last().values
            me = pd.DatetimeIndex(me)
            me = me[me >= pd.Timestamp(BACKTEST_START)]
            both = empty = 0
            for t in me:
                a, c = dc.loc[t].dropna(), rv.loc[t].dropna()
                if a.empty or c.empty:
                    continue
                both += 1
                empty += int(len(set(a.nlargest(4).index) & set(c.nlargest(2).index)) == 0)
            a2 = (ar - ar1).dropna()
            rows.append({
                "variant": vname, "rv": rname,
                "AR1_mean": round(float(ar1.dropna().mean()), 4),
                "AR1_p05": round(float(ar1.dropna().quantile(0.05)), 4),
                "AR1_p95": round(float(ar1.dropna().quantile(0.95)), 4),
                "AR2_mean": round(float(a2.mean()), 4),
                "AR2_p95": round(float(a2.quantile(0.95)), 4),
                "AR_total_mean": round(float(ar.dropna().mean()), 4),
                "intersection_empty_share": round(empty / max(both, 1), 4),
                "ann": round(m["annual_return"], 4),
                "mdd": round(m["max_drawdown"], 4),
                "vol": round(m["annual_vol"], 4),
                "calmar": round(m["calmar"], 4),
            })
        print("done", vname, flush=True)
    t = pd.DataFrame(rows)
    t.to_csv(OUT / "spec_sensitivity.csv", index=False)
    print(t.to_string(index=False))


if __name__ == "__main__":
    main()
