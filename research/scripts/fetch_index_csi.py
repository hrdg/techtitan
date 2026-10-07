"""Fetch benchmark and treasury index daily series.

Primary sources reachable from this host:
- 中证指数官网 (via akshare.stock_zh_index_hist_csindex): 中证A500 000510, 科技50 931380,
  中证国债 H11006
- 新浪 (via akshare.stock_zh_index_daily): 上证国债指数 sh000012 (sensitivity only)
"""
from __future__ import annotations

import hashlib
import json
import warnings
from pathlib import Path

import akshare as ak
import pandas as pd

warnings.filterwarnings("ignore")

OUT = Path(__file__).resolve().parents[2] / "data" / "raw"
START, END = "20150101", "20260731"
CSI = {"000510": "中证A500", "931380": "科技50", "H11006": "中证国债"}


def main() -> None:
    OUT.mkdir(parents=True, exist_ok=True)
    records, frames = [], []

    for code, name in CSI.items():
        df = ak.stock_zh_index_hist_csindex(symbol=code, start_date=START, end_date=END)
        df = df[["日期", "指数代码", "指数中文简称", "开盘", "最高", "最低", "收盘"]].copy()
        df.columns = ["date", "code", "name", "open", "high", "low", "close"]
        df["date"] = pd.to_datetime(df["date"])
        df = df.sort_values("date").reset_index(drop=True)
        blob = df.to_csv(index=False).encode()
        records.append(
            {
                "source": "csindex.com.cn via akshare.stock_zh_index_hist_csindex",
                "code": code,
                "name": name,
                "rows": int(len(df)),
                "date_min": str(df["date"].min().date()),
                "date_max": str(df["date"].max().date()),
                "sha256": hashlib.sha256(blob).hexdigest(),
            }
        )
        frames.append(df)
        print(code, name, len(df), records[-1]["date_min"], records[-1]["date_max"])

    panel = pd.concat(frames, ignore_index=True)
    panel.to_parquet(OUT / "benchmark_csi_daily.parquet", index=False)

    sg = ak.stock_zh_index_daily(symbol="sh000012")
    sg["date"] = pd.to_datetime(sg["date"])
    sg = sg[(sg["date"] >= "2015-01-01") & (sg["date"] <= "2026-07-31")].reset_index(drop=True)
    sg = sg[["date", "open", "high", "low", "close"]]
    sg.to_parquet(OUT / "sse_treasury_000012_daily.parquet", index=False)
    print("sh000012 上证国债指数", len(sg), sg["date"].min().date(), sg["date"].max().date())

    (OUT / "benchmark_fetch_manifest.json").write_text(
        json.dumps(
            {
                "requested_range": [START, END],
                "fetched_at": pd.Timestamp.now(tz="Asia/Shanghai").isoformat(),
                "csi_series": records,
                "sse_treasury": {
                    "source": "finance.sina.com.cn via akshare.stock_zh_index_daily(sh000012)",
                    "rows": int(len(sg)),
                    "date_min": str(sg["date"].min().date()),
                    "date_max": str(sg["date"].max().date()),
                },
            },
            ensure_ascii=False,
            indent=2,
        ),
        encoding="utf-8",
    )
    print("wrote", OUT / "benchmark_csi_daily.parquet")


if __name__ == "__main__":
    main()
