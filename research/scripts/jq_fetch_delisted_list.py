"""取全市场退市股名单及其退市时的行业归属（用于幸存者偏差审计）。

做法（沿用 ETF个股机器学习 线的已验证口径）：
- 多日期 get_all_securities(types=['stock'], date=...) 取并集，避免单日期只返回存续标的；
- get_all_securities(types=['stock']) 取 end_date，end_date < 2026-06 视为已退市；
- 对退市股取其最后交易日（end_date 前最近交易日）的 sw_l1/sw_l2 行业与流通市值。
产物同时写研究区 CSV（可 download）与 stdout（小样本核对）。
"""
import json

import pandas as pd

from jqdata import *  # noqa: F401,F403,E402

CHECK_DATES = ["2016-06-30", "2017-06-30", "2018-06-30", "2019-06-30", "2020-06-30",
               "2021-06-30", "2022-06-30", "2023-06-30", "2024-06-30", "2025-06-30", "2026-06-30"]
CUT = "2026-06-01"

ever = set()
for d in CHECK_DATES:
    ever.update(get_all_securities(types=["stock"], date=d).index)

allsec = get_all_securities(types=["stock"])
allsec["end_date"] = pd.to_datetime(allsec["end_date"])
allsec["start_date"] = pd.to_datetime(allsec["start_date"])

delisted = allsec[allsec["end_date"] < pd.Timestamp(CUT)]
rows = []
debug = []
for code, r in delisted.iterrows():
    last = min(r["end_date"], pd.Timestamp("2026-06-30"))
    ind = {}
    for back in (7, 30, 120, 365):
        probe = last - pd.Timedelta(days=back)
        try:
            cand = get_industry(code, date=str(probe.date()))
        except Exception:  # noqa: BLE001
            cand = {}
        if cand and (cand.get("sw_l2") or cand.get("sw_l1")):
            ind = cand
            break
    if code in ("600401.XSHG", "002450.XSHE", "600485.XSHG"):
        debug.append({"code": code, "end": str(r["end_date"].date()), "ind": str(ind)[:220]})
    sw1 = (ind.get("sw_l1") or {}).get("industry_code")
    sw2 = (ind.get("sw_l2") or {}).get("industry_code")
    sw1n = (ind.get("sw_l1") or {}).get("industry_name")
    sw2n = (ind.get("sw_l2") or {}).get("industry_name")
    fcap = None
    try:
        v = get_valuation(code, end_date=str(last.date()), count=1,
                          fields=["market_cap", "circulating_market_cap"])
        if len(v):
            fcap = float(v["circulating_market_cap"].iloc[-1])
    except Exception:  # noqa: BLE001
        pass
    rows.append({"code": code, "name": str(r["display_name"]),
                 "start_date": str(r["start_date"].date()), "end_date": str(r["end_date"].date()),
                 "sw_l1": sw1, "sw_l1_name": sw1n, "sw_l2": sw2, "sw_l2_name": sw2n,
                 "last_float_mktcap_yi": fcap, "in_ever_union": code in ever})

out = pd.DataFrame(rows)
out.to_csv("delisted_stocks_20261013.csv", index=False, encoding="utf-8-sig")
print("PROBE_JSON_START")
print(json.dumps({"cut": CUT, "n_all": int(len(allsec)), "n_delisted": int(len(out)),
                  "n_in_ever_union": int(out["in_ever_union"].sum()),
                  "n_with_industry": int(out["sw_l2"].notna().sum()),
                  "date_min": str(out["end_date"].min()), "date_max": str(out["end_date"].max()),
                  "by_year": out["end_date"].str[:4].value_counts().sort_index().to_dict(),
                  "debug": debug,
                  "file": "delisted_stocks_20261013.csv"}, ensure_ascii=False))
print("PROBE_JSON_END")
