"""探测退市股的行情与估值可得性（决定补齐方案）。Read-only。"""
import json

import pandas as pd

from jqdata import *  # noqa: F401,F403,E402

CODES = ["600401.XSHG", "002450.XSHE", "600485.XSHG", "300372.XSHE", "002089.XSHE",
         "000748.XSHE", "600680.XSHG", "300282.XSHE"]
out = {}

for c in CODES:
    rec = {}
    try:
        px = get_price(c, start_date="2016-01-01", end_date="2021-12-31", frequency="daily",
                       fields=["close"], fq="post", panel=False)
        rec["price_post"] = {"n": int(len(px)), "min": str(px["time"].min())[:10],
                             "max": str(px["time"].max())[:10]} if len(px) else "empty"
    except Exception as exc:  # noqa: BLE001
        rec["price_post"] = "ERR:" + str(exc)[:90]
    try:
        px2 = get_price(c, start_date="2016-01-01", end_date="2021-12-31", frequency="daily",
                        fields=["close"], fq="none", panel=False)
        rec["price_none"] = {"n": int(len(px2))} if len(px2) else "empty"
    except Exception as exc:  # noqa: BLE001
        rec["price_none"] = "ERR:" + str(exc)[:90]
    try:
        v = get_valuation(c, start_date="2016-01-01", end_date="2021-12-31",
                          fields=["market_cap", "circulating_market_cap", "pb_ratio"])
        rec["valuation"] = {"n": int(len(v)), "cols": list(v.columns),
                            "min": str(v["day"].min())[:10], "max": str(v["day"].max())[:10]} if len(v) else "empty"
    except Exception as exc:  # noqa: BLE001
        rec["valuation"] = "ERR:" + str(exc)[:90]
    out[c] = rec

print("PROBE_JSON_START")
print(json.dumps(out, ensure_ascii=False))
print("PROBE_JSON_END")
