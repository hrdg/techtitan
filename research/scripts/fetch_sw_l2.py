"""Fetch Shenwan level-2 industry index daily analysis (close / PB / float mktcap).

Source: 申万宏源研究-指数分析 (https://www.swsresearch.com/institute_sw/allIndex/analysisIndex),
same REST endpoint that akshare>=1.19.1 uses in index_analysis_daily_sw. Queried directly with
page_size=5000 and swindexcode=<code> so one request returns the full daily history per index.
"""
from __future__ import annotations

import hashlib
import json
import time
from pathlib import Path

import pandas as pd
import requests

BASE = "https://www.swsresearch.com/institute-sw/api/index_analysis/index_analysis_report/"
HEADERS = {
    "User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/120.0 Safari/537.36",
    "Referer": "https://www.swsresearch.com/institute_sw/allIndex/analysisIndex",
}
CODES = {
    "801081": "半导体",
    "801085": "消费电子",
    "801737": "电池",
    "801735": "光伏设备",
    "801745": "军工电子Ⅱ",
    "801101": "计算机设备",
    "801103": "IT服务Ⅱ",
    "801102": "通信设备",
    "801093": "汽车零部件",
    "801078": "自动化设备",
}
START, END = "2015-01-01", "2026-07-31"
OUT = Path(__file__).resolve().parents[2] / "data" / "raw"


def fetch(code: str, start: str, end: str, index_type: str = "二级行业") -> pd.DataFrame:
    params = {
        "page": "1",
        "page_size": "5000",
        "index_type": index_type,
        "start_date": start,
        "end_date": end,
        "type": "DAY",
        "swindexcode": code,
    }
    for attempt in range(4):
        try:
            resp = requests.get(BASE, params=params, headers=HEADERS, verify=False, timeout=60)
            payload = resp.json()
            rows = payload["data"]["results"]
            if len(rows) >= payload["data"]["count"]:
                return pd.DataFrame(rows)
            params["page_size"] = "5000"
        except Exception:  # noqa: BLE001 - retry network/JSON failures
            if attempt == 3:
                raise
        time.sleep(1.5 * (attempt + 1))
    raise RuntimeError(f"incomplete payload for {code}")


def main() -> None:
    OUT.mkdir(parents=True, exist_ok=True)
    frames, records = [], []
    for code, name in CODES.items():
        raw = fetch(code, START, END)
        raw = raw.rename(
            columns={
                "swindexcode": "code",
                "swindexname": "name",
                "bargaindate": "date",
                "closeindex": "close",
                "bargainamount": "volume",
                "markup": "pct_chg",
                "turnoverrate": "turnover",
                "pe": "pe",
                "pb": "pb",
                "meanprice": "avg_price",
                "bargainsumrate": "amount_share",
                "negotiablessharesum1": "float_mktcap_yi",
                "negotiablessharesum2": "avg_float_mktcap_yi",
                "dp": "dividend_yield",
            }
        )
        # 申万接口返回带 +08:00/UTC 偏移的时间戳，统一归一到本地日历日（同日 00:00）
        raw["date"] = (
            pd.to_datetime(raw["date"], utc=True)
            .dt.tz_convert("Asia/Shanghai")
            .dt.normalize()
            .dt.tz_localize(None)
        )
        for col in [
            "close", "volume", "pct_chg", "turnover", "pe", "pb", "avg_price",
            "amount_share", "float_mktcap_yi", "avg_float_mktcap_yi", "dividend_yield",
        ]:
            raw[col] = pd.to_numeric(raw[col], errors="coerce")
        raw = raw.sort_values("date").reset_index(drop=True)
        blob = raw.to_csv(index=False).encode()
        records.append(
            {
                "code": code,
                "name": name,
                "rows": int(len(raw)),
                "date_min": str(raw["date"].min().date()),
                "date_max": str(raw["date"].max().date()),
                "sha256": hashlib.sha256(blob).hexdigest(),
                "missing": {c: int(raw[c].isna().sum()) for c in ["close", "pb", "float_mktcap_yi"]},
            }
        )
        frames.append(raw)
        print(f"{code} {name}: {len(raw)} rows {records[-1]['date_min']}..{records[-1]['date_max']}")
        time.sleep(0.8)

    panel = pd.concat(frames, ignore_index=True)
    dest = OUT / "sw_l2_daily.parquet"
    panel.to_parquet(dest, index=False)
    (OUT / "sw_l2_fetch_manifest.json").write_text(
        json.dumps(
            {
                "source": BASE,
                "index_type": "二级行业",
                "type": "DAY",
                "requested_range": [START, END],
                "fetched_at": pd.Timestamp.now(tz="Asia/Shanghai").isoformat(),
                "panel_rows": int(len(panel)),
                "per_code": records,
            },
            ensure_ascii=False,
            indent=2,
        ),
        encoding="utf-8",
    )
    print("wrote", dest, panel.shape)


if __name__ == "__main__":
    main()
