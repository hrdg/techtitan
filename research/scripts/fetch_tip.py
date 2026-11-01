"""取 TIP（iShares TIPS Bond ETF）日线收盘，用于综合动量择时。"""
from __future__ import annotations

import hashlib
import json
from pathlib import Path

import akshare as ak
import pandas as pd

ROOT = Path(__file__).resolve().parents[2]
RAW = ROOT / "data" / "raw"


def main() -> None:
    d = ak.stock_us_daily(symbol="TIP", adjust="qfq")
    d["date"] = pd.to_datetime(d["date"])
    d = d.sort_values("date")[["date", "close"]].reset_index(drop=True)
    dest = RAW / "tip_daily.parquet"
    d.to_parquet(dest, index=False)
    blob = d.to_csv(index=False).encode()
    (RAW / "tip_fetch_manifest.json").write_text(json.dumps({
        "source": "akshare.stock_us_daily(symbol='TIP', adjust='qfq')",
        "rows": int(len(d)), "date_min": str(d["date"].min().date()),
        "date_max": str(d["date"].max().date()),
        "sha256": hashlib.sha256(blob).hexdigest(),
    }, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"TIP {len(d)} rows {d['date'].min().date()} ~ {d['date'].max().date()}")


if __name__ == "__main__":
    main()
