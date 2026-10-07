"""Assemble the primary industry panel used by the reproduction.

口径（DEC-001 的执行结果）：
- 2015-01-05 ~ 2016-12-31：聚宽（get_price fq=post + get_valuation）。研报首个信号在 2016-12-30，
  需要 2015 年收益（供 ΔC 的 125 日窗口）与 2015-2016 的行业 PB；本地 quantdb 自 2016-01-04 起，
  且 2016 上半年可用成分股仅 0~2 只，无法支撑暖机。
- 2017-01-03 ~ 2026-07-31：本地 quantdb 成分股重建（价格指数口径；2021-12-13 起与申万官方校验
  TE 3%~4%）。这段同时是策略净值所在，保持单一价格指数口径。
- 2017-2020 本地面板缺值的行业-日，用聚宽同日值补齐（避免 C 序列出现 125 日断点）。
"""
from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path

import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parents[2]
RAW = ROOT / "data" / "raw"
SPLICE = pd.Timestamp("2017-01-03")
PATCH_END = pd.Timestamp("2021-01-01")


def naive(s):
    s = pd.to_datetime(s)
    if isinstance(s.dtype, pd.DatetimeTZDtype):
        s = s.dt.tz_convert("Asia/Shanghai").dt.tz_localize(None)
    return s.astype("datetime64[ns]")


def load_jq(files: list[str]) -> pd.DataFrame:
    frames = []
    for f in files:
        d = json.loads((RAW / f).read_text(encoding="utf-8"))
        df = pd.DataFrame(d["panel"])
        df["date"] = naive(df["date"])
        df["pb"] = df["sum_total_mv_yi"] / df["sum_equity_yi"]
        df["float_mv"] = df["float_mv_yi"] * 1e8
        frames.append(df)
    jq = pd.concat(frames, ignore_index=True)
    return jq.drop_duplicates(["date", "code"])


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--local", default="industry_panel_proxy.parquet")
    ap.add_argument("--jq", default="jq_panel_1520.json")
    ap.add_argument("--out", default="industry_panel_final.parquet")
    args = ap.parse_args()
    local = pd.read_parquet(RAW / args.local)
    local["date"] = naive(local["date"])
    local["source"] = "quantdb-reconstruction"
    names = local.drop_duplicates("code").set_index("code")["name"]
    jq = load_jq([f.strip() for f in args.jq.split(",") if f.strip()])
    jq["name"] = jq["code"].map(names)
    jq["source"] = "joinquant"

    patch_win = local[(local["date"] >= SPLICE) & (local["date"] < PATCH_END)]
    need = patch_win[(patch_win["ret"].isna()) | (patch_win["float_mv"].isna()) |
                     (patch_win["float_mv"] <= 0)][["date", "code"]]
    src = jq[["date", "code", "ret", "float_mv", "pb"]].add_suffix("_jq").rename(
        columns={"date_jq": "date", "code_jq": "code"})
    filled = local.merge(need.merge(src, on=["date", "code"], how="left"),
                         on=["date", "code"], how="left")
    n_ret = int((filled["ret"].isna() & filled["ret_jq"].notna()).sum())
    n_fmv = int(((filled["float_mv"].isna() | (filled["float_mv"] <= 0)) &
                 filled["float_mv_jq"].notna()).sum())
    filled["ret"] = filled["ret"].fillna(filled["ret_jq"])
    filled["float_mv"] = np.where(filled["float_mv"].isna() | (filled["float_mv"] <= 0),
                                  filled["float_mv_jq"], filled["float_mv"])
    filled["pb"] = filled["pb"].fillna(filled["pb_jq"])
    local = filled.drop(columns=[c for c in filled.columns if c.endswith("_jq")])
    print(f"local gaps patched from joinquant: ret {n_ret}, float_mv {n_fmv}")

    ov = jq.merge(local[["date", "code", "ret"]], on=["date", "code"], suffixes=("_jq", "_loc"))
    ov = ov[(ov["date"] >= "2016-01-04") & (ov["date"] < SPLICE)]
    stats = []
    for code, g in ov.groupby("code"):
        g = g.dropna(subset=["ret_jq", "ret_loc"])
        if len(g) < 30:
            continue
        stats.append({"code": code, "n": int(len(g)),
                      "ret_corr": round(float(g["ret_jq"].corr(g["ret_loc"])), 4),
                      "tracking_error_ann": round(float((g["ret_jq"] - g["ret_loc"]).std()
                                                        * np.sqrt(250)), 4)})

    cols = ["date", "code", "name", "ret", "float_mv", "pb", "n_members", "source"]
    jq_pre = jq[jq["date"] < SPLICE][cols].copy()
    local_post = local[local["date"] >= SPLICE][cols]
    final = pd.concat([jq_pre, local_post], ignore_index=True).sort_values(["date", "code"])
    dest = RAW / args.out
    final.to_parquet(dest, index=False)
    (RAW / (args.out.replace(".parquet", "") + "_manifest.json")).write_text(json.dumps({
        "description": "primary panel: joinquant 2015-2016 + quantdb reconstruction 2017-2026",
        "splice_date": str(SPLICE.date()),
        "conventions": {"2015-2016": "joinquant fq=post（后复权，含分红）",
                        "2017-2026": "quantdb 成分股重建（价格指数口径）"},
        "range": [str(final["date"].min().date()), str(final["date"].max().date())],
        "rows": int(len(final)),
        "rows_from_joinquant": int(len(jq_pre)),
        "patched_cells": {"ret": n_ret, "float_mv": n_fmv},
        "overlap_2016_cross_source": stats,
        "sha256": hashlib.sha256(final.to_csv(index=False).encode()).hexdigest(),
    }, ensure_ascii=False, indent=2), encoding="utf-8")
    s = pd.DataFrame(stats)
    print(f"spliced {final.shape} {final['date'].min().date()}..{final['date'].max().date()}")
    if len(s):
        print(f"2016 跨源: corr {s['ret_corr'].min():.3f}~{s['ret_corr'].max():.3f}, "
              f"TE {s['tracking_error_ann'].min():.1%}~{s['tracking_error_ann'].max():.1%}")
    print("wrote", dest)


if __name__ == "__main__":
    main()
