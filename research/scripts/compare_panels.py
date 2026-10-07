"""Compare candidate industry panels against 申万官方数据 and against each other.

Usage: python research/scripts/compare_panels.py <panel.parquet> [<other.parquet>]
"""
from __future__ import annotations

import sys
from pathlib import Path

import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parents[2]
RAW = ROOT / "data" / "raw"


def naive(s):
    s = pd.to_datetime(s)
    if isinstance(s.dtype, pd.DatetimeTZDtype):
        s = s.dt.tz_convert("Asia/Shanghai").dt.tz_localize(None)
    return s.astype("datetime64[ns]")


def load(path: Path) -> pd.DataFrame:
    df = pd.read_parquet(path)
    df["date"] = naive(df["date"])
    if "float_mv" in df.columns and df["float_mv"].median() > 1e9:
        df["float_mv"] = df["float_mv"] / 1e8      # 元 -> 亿元
    if "float_mv_yi" in df.columns:
        df["float_mv"] = df["float_mv_yi"]
    return df


def vs_official(df: pd.DataFrame, start="2021-12-13") -> pd.DataFrame:
    off = pd.read_parquet(RAW / "sw_l2_daily.parquet")
    off["code"] = off["code"].astype(str)
    off["date"] = naive(off["date"])
    off["ret_off"] = off.groupby("code")["close"].pct_change()
    m = df.merge(off[["date", "code", "ret_off", "pb", "float_mktcap_yi"]], on=["date", "code"],
                 how="inner", suffixes=("", "_off"))
    m = m[m["date"] >= start].dropna(subset=["ret", "ret_off"])
    out = []
    for code, g in m.groupby("code"):
        n = len(g)
        out.append({
            "code": code, "n": n,
            "ret_corr": round(float(g["ret"].corr(g["ret_off"])), 4),
            "te_ann": round(float((g["ret"] - g["ret_off"]).std() * np.sqrt(250)), 4),
            "ann_panel": round(float((1 + g["ret"]).prod() ** (250 / n) - 1), 4),
            "ann_official": round(float((1 + g["ret_off"]).prod() ** (250 / n) - 1), 4),
            "pb_corr": round(float(g["pb"].corr(g["pb_off"])), 4),
            "pb_ratio_median": round(float((g["pb"] / g["pb_off"]).median()), 4),
        })
    return pd.DataFrame(out)


def main() -> None:
    a = load(Path(sys.argv[1]))
    print(f"--- {Path(sys.argv[1]).name} vs 申万官方 (2021-12-13 起) ---")
    t = vs_official(a)
    print(t.to_string(index=False))
    if len(sys.argv) > 2:
        b = load(Path(sys.argv[2]))
        m = a.merge(b, on=["date", "code"], suffixes=("_a", "_b")).dropna(subset=["ret_a", "ret_b"])
        m = m[m["date"] >= "2016-01-04"]
        rows = []
        for code, g in m.groupby("code"):
            rows.append({"code": code, "n": len(g),
                         "corr": round(float(g["ret_a"].corr(g["ret_b"])), 4),
                         "te_ann": round(float((g["ret_a"] - g["ret_b"]).std() * np.sqrt(250)), 4),
                         "ann_a": round(float((1 + g["ret_a"]).prod() ** (250 / len(g)) - 1), 4),
                         "ann_b": round(float((1 + g["ret_b"]).prod() ** (250 / len(g)) - 1), 4)})
        print(f"\n--- {Path(sys.argv[1]).name} vs {Path(sys.argv[2]).name} (2016+) ---")
        print(pd.DataFrame(rows).to_string(index=False))


if __name__ == "__main__":
    main()
