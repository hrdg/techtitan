"""取申万二级"科技上游"资源类行业日度数据（申万宏源官网，同 fetch_sw_l2.py 口径）。"""
from __future__ import annotations

import hashlib
import json
import time
from pathlib import Path

import pandas as pd
import requests

import sys
sys.path.insert(0, str(Path(__file__).resolve().parent))
from fetch_sw_l2 import BASE, HEADERS, fetch  # noqa: E402

CODES = {
    "801054": "稀有金属",
    "801055": "工业金属",
    "801056": "能源金属",
    "801039": "非金属材料",
    "801086": "电子化学品",
    "801053": "贵金属",
}
L1_CODES = {"801030": "基础化工", "801950": "煤炭", "801960": "石油石化", "801040": "钢铁"}
START, END = "2015-01-01", "2026-07-31"
OUT = Path(__file__).resolve().parents[2] / "data" / "raw"


def main() -> None:
    frames, records = [], []
    jobs = ([(c, n, "二级行业") for c, n in CODES.items()]
            + [(c, n, "一级行业") for c, n in L1_CODES.items()])
    for code, name, itype in jobs:
        raw = fetch(code, START, END, index_type=itype)
        raw = raw.rename(columns={
            "swindexcode": "code", "swindexname": "name", "bargaindate": "date",
            "closeindex": "close", "bargainamount": "volume", "markup": "pct_chg",
            "turnoverrate": "turnover", "pe": "pe", "pb": "pb", "meanprice": "avg_price",
            "bargainsumrate": "amount_share", "negotiablessharesum1": "float_mktcap_yi",
        })
        raw["date"] = (pd.to_datetime(raw["date"], utc=True).dt.tz_convert("Asia/Shanghai")
                       .dt.normalize().dt.tz_localize(None))
        for col in ["close", "turnover", "pb", "amount_share", "float_mktcap_yi"]:
            raw[col] = pd.to_numeric(raw[col], errors="coerce")
        raw = raw.sort_values("date").reset_index(drop=True)
        records.append({"code": code, "name": name, "rows": int(len(raw)),
                        "date_min": str(raw["date"].min().date()),
                        "date_max": str(raw["date"].max().date())})
        frames.append(raw)
        print(f"{code} {name}: {len(raw)} rows {records[-1]['date_min']}..{records[-1]['date_max']}")
        time.sleep(0.8)
    panel = pd.concat(frames, ignore_index=True)
    panel.to_parquet(OUT / "sw_resource_daily.parquet", index=False)
    (OUT / "sw_resource_fetch_manifest.json").write_text(json.dumps({
        "source": BASE, "requested_range": [START, END], "per_code": records,
        "sha256": hashlib.sha256(panel.to_csv(index=False).encode()).hexdigest(),
    }, ensure_ascii=False, indent=2), encoding="utf-8")
    print("wrote", OUT / "sw_resource_daily.parquet", panel.shape)


if __name__ == "__main__":
    main()
