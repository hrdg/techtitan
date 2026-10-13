"""探测聚宽除权除息表（STK_XR_XD）能否给出退市股的送转/配股，用于前复权外的分拆调整。Read-only."""
import json

import pandas as pd

from jqdata import *  # noqa: F401,F403,E402
from jqdata import finance

CODES = ["600401.XSHG", "002450.XSHE", "600485.XSHG", "300372.XSHE"]
out = {}

try:
    q = query(finance.STK_XR_XD).filter(finance.STK_XR_XD.code.in_(CODES))
    df = finance.run_query(q)
    out["xr_xd"] = {"n": int(len(df)), "cols": list(df.columns)}
    if len(df):
        keep = [c for c in ["code", "a_registration_date", "bonus_ratio_rmb", "transfer_ratio",
                            "dividend_ratio_rmb", "at_price", "report_date"] if c in df.columns]
        out["xr_xd_sample"] = df[keep].head(6).astype(str).to_dict(orient="records")
except Exception as exc:  # noqa: BLE001
    out["xr_xd"] = "ERR:" + str(exc)[:150]

try:
    px = get_price("600401.XSHG", start_date="2016-01-01", end_date="2016-03-01", frequency="daily",
                   fields=["close"], fq="pre")
    out["fq_pre"] = {"type": str(type(px)), "n": int(len(px)),
                     "cols": list(px.columns) if hasattr(px, "columns") else None}
except Exception as exc:  # noqa: BLE001
    out["fq_pre"] = "ERR:" + str(exc)[:120]

print("PROBE_JSON_START")
print(json.dumps(out, ensure_ascii=False, default=str))
print("PROBE_JSON_END")
