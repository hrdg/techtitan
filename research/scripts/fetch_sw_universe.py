"""取申万一级/二级全量行业指数的日度收盘、市净率、流通市值（申万宏源官网）。

用法: python research/scripts/fetch_sw_universe.py 1|2
先取一个近端日期的行业清单，再逐行业取全历史（index_analysis_report + swindexcode）。
"""
from __future__ import annotations

import hashlib
import json
import sys
import time
from pathlib import Path

import pandas as pd
import requests

ROOT = Path(__file__).resolve().parents[2]
RAW = ROOT / "data" / "raw"
BASE = "https://www.swsresearch.com/institute-sw/api/index_analysis/index_analysis_report/"
HEADERS = {
    "User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 "
                  "(KHTML, like Gecko) Chrome/120.0 Safari/537.36",
    "Referer": "https://www.swsresearch.com/institute_sw/allIndex/analysisIndex",
}
START, END = "2015-01-01", "2026-07-31"
TYPE = {"1": "一级行业", "2": "二级行业"}


def get(url_params: dict) -> dict:
    for attempt in range(4):
        try:
            r = requests.get(BASE, params=url_params, headers=HEADERS, verify=False, timeout=60)
            return r.json()
        except Exception:
            if attempt == 3:
                raise
            time.sleep(1.5 * (attempt + 1))
    raise RuntimeError("unreachable")


def listing(index_type: str) -> pd.DataFrame:
    p = {"page": "1", "page_size": "5000", "index_type": index_type,
         "start_date": "2026-07-01", "end_date": "2026-07-31", "type": "DAY", "swindexcode": "all"}
    rows = get(p)["data"]["results"]
    df = pd.DataFrame(rows)
    return df[["swindexcode", "swindexname"]].drop_duplicates().sort_values("swindexcode")


def history(code: str, index_type: str) -> pd.DataFrame:
    p = {"page": "1", "page_size": "5000", "index_type": index_type,
         "start_date": START, "end_date": END, "type": "DAY", "swindexcode": code}
    rows = get(p)["data"]["results"]
    df = pd.DataFrame(rows)
    if df.empty:
        return df
    df = df.rename(columns={"swindexcode": "code", "swindexname": "name", "bargaindate": "date",
                            "closeindex": "close", "pb": "pb",
                            "negotiablessharesum1": "float_mv_yi", "pe": "pe",
                            "markup": "pct_chg", "bargainsumrate": "amount_share"})
    df["date"] = (pd.to_datetime(df["date"], utc=True).dt.tz_convert("Asia/Shanghai")
                  .dt.normalize().dt.tz_localize(None))
    for c in ["close", "pb", "float_mv_yi", "pe", "pct_chg", "amount_share"]:
        df[c] = pd.to_numeric(df[c], errors="coerce")
    cols = ["date", "code", "name", "close", "pb", "float_mv_yi", "pe", "amount_share"]
    return df[cols].sort_values("date")


def main() -> None:
    level = sys.argv[1]
    index_type = TYPE[level]
    lst = listing(index_type)
    print(f"{index_type}: {len(lst)} 个行业")
    frames, recs = [], []
    for i, (code, name) in enumerate(zip(lst["swindexcode"], lst["swindexname"])):
        df = history(code, index_type)
        if df.empty:
            continue
        frames.append(df)
        recs.append({"code": code, "name": name, "rows": int(len(df)),
                     "date_min": str(df["date"].min().date()), "date_max": str(df["date"].max().date()),
                     "pb_missing": int(df["pb"].isna().sum()),
                     "fmv_zero_or_missing": int((df["float_mv_yi"].isna() | (df["float_mv_yi"] <= 0)).sum())})
        if i % 20 == 0:
            print(f"  {i}/{len(lst)} {code} {name} {recs[-1]['rows']} 行", flush=True)
        time.sleep(0.35)
    panel = pd.concat(frames, ignore_index=True)
    dest = RAW / f"sw{level}_daily.parquet"
    panel.to_parquet(dest, index=False)
    (RAW / f"sw{level}_fetch_manifest.json").write_text(json.dumps({
        "source": BASE, "index_type": index_type, "requested_range": [START, END],
        "fetched_at": pd.Timestamp.now(tz="Asia/Shanghai").isoformat(),
        "industries": len(recs), "rows": int(len(panel)),
        "sha256": hashlib.sha256(panel.to_csv(index=False).encode()).hexdigest(),
        "per_code": recs,
    }, ensure_ascii=False, indent=2), encoding="utf-8")
    print("wrote", dest, panel.shape, "| 行业数", len(recs))


if __name__ == "__main__":
    main()
