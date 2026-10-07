"""Validate the constituent-rebuilt industry panel ag["float_mv"]inst 申万官方指数 over the overlap."""
from __future__ import annotations

import json
from pathlib import Path

import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parents[2]
RAW = ROOT / "data" / "raw"
OVERLAP_START = "2021-12-13"


def _naive(s: pd.Series) -> pd.Series:
    s = pd.to_datetime(s)
    if isinstance(s.dtype, pd.DatetimeTZDtype):
        s = s.dt.tz_convert("Asia/Shanghai").dt.tz_localize(None)
    return s.astype("datetime64[ns]")


def main() -> None:
    proxy = pd.read_parquet(RAW / "industry_panel_proxy.parquet")
    proxy["date"] = _naive(proxy["date"])
    off = pd.read_parquet(RAW / "sw_l2_daily.parquet")
    off["code"] = off["code"].astype(str)
    off["date"] = _naive(off["date"])
    off = off.rename(columns={"close": "close_off", "pb": "pb_off", "float_mktcap_yi": "fmv_off"})
    off["ret_off"] = off.groupby("code")["close_off"].pct_change()

    m = proxy.merge(off[["date", "code", "ret_off", "close_off", "pb_off", "fmv_off"]],
                    on=["date", "code"], how="inner")
    m = m[m["date"] >= OVERLAP_START].copy()
    print("overlap rows:", len(m), "codes:", m["code"].nunique())
    rows = []
    for code, g in m.groupby("code"):
        g = g.dropna(subset=["ret", "ret_off"])
        if len(g) < 60:
            rows.append({"code": code, "n": len(g), "note": "insufficient overlap"})
            continue
        n = len(g)
        cum_p = float((1 + g["ret"]).prod() - 1)
        cum_o = float((1 + g["ret_off"]).prod() - 1)
        rows.append({
            "code": code,
            "name": g["name"].iloc[-1],
            "n": n,
            "ret_corr": float(g["ret"].corr(g["ret_off"])),
            "tracking_error_ann": float((g["ret"] - g["ret_off"]).std() * np.sqrt(250)),
            "ann_proxy": float((1 + cum_p) ** (250 / n) - 1),
            "ann_official": float((1 + cum_o) ** (250 / n) - 1),
            "pb_proxy_last": float(g["pb"].iloc[-1]),
            "pb_official_last": float(g["pb_off"].iloc[-1]),
            "pb_corr": float(g["pb"].corr(g["pb_off"])),
            "fmv_proxy_over_official": float((g["float_mv"] / g["fmv_off"]).median()),
            "n_used_median": float(g["n_used"].median()),
            "n_members_median": float(g["n_members"].median()),
        })
    res = pd.DataFrame(rows).sort_values("code")
    print(res.to_string(float_format=lambda x: f"{x:,.4f}"))
    (RAW / "proxy_validation.json").write_text(
        json.dumps({"overlap_start": OVERLAP_START,
                    "rows": res.to_dict(orient="records")}, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    res.to_csv(RAW / "proxy_validation.csv", index=False)


if __name__ == "__main__":
    main()
