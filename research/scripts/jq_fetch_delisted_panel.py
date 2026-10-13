"""拉取本线 10 个行业里已退市股票的日线/估值/送转事件，用于幸存者偏差补齐。

输出（研究区，纯文本 CSV）：
- delisted_panel_20261013.csv   逐股逐日：code,date,close,market_cap,circulating_market_cap,pb_ratio
- delisted_events_20261013.csv  送转事件：code,a_registration_date,transfer_ratio（每 10 股送转）
- delisted_indmap_20261013.csv  行业归属：code,sw_l1_name,sw_l2_name,sw_l3_name（退市前日期）
"""
import json

import pandas as pd

from jqdata import *  # noqa: F401,F403,E402
from jqdata import finance

# 5 个可干净对应的申万 2014 版行业，外加电源设备（其覆盖 2021 版的电池与光伏设备）
GROUPS = {
    "801081": "半导体",
    "801085": "消费电子",
    "801101": "计算机设备",
    "801102": "通信设备",
    "801093": "汽车零部件",
    "801733": "电源设备",
}
DATES = ["2016-06-30", "2017-06-30", "2018-06-29", "2019-06-28", "2020-06-30", "2021-06-30"]

allsec = get_all_securities(types=["stock"])
allsec["end_date"] = pd.to_datetime(allsec["end_date"])
delisted = set(allsec[allsec["end_date"] < pd.Timestamp("2026-06-01")].index)

targets = set()
for code14 in GROUPS:
    for d in DATES:
        try:
            targets.update(get_industry_stocks(code14, date=d))
        except Exception:  # noqa: BLE001
            pass
targets &= delisted
targets = sorted(targets)

px_rows, ind_rows = [], []
for code in targets:
    end = allsec.loc[code, "end_date"]
    try:
        px = get_price(code, start_date="2016-01-01", end_date=str(end.date()), frequency="daily",
                       fields=["close"], fq="none")
        px = px.reset_index().rename(columns={px.reset_index().columns[0]: "date"})
        px["date"] = pd.to_datetime(px["date"]).dt.strftime("%Y-%m-%d")
        px["code"] = code
        v = get_valuation(code, start_date="2016-01-01", end_date=str(end.date()),
                          fields=["market_cap", "circulating_market_cap", "pb_ratio"])
        v["date"] = pd.to_datetime(v["day"]).dt.strftime("%Y-%m-%d")
        mg = px.merge(v[["date", "market_cap", "circulating_market_cap", "pb_ratio"]],
                      on="date", how="left")
        px_rows.append(mg[["code", "date", "close", "market_cap",
                           "circulating_market_cap", "pb_ratio"]])
    except Exception as exc:  # noqa: BLE001
        print("PRICE_ERR", code, str(exc)[:80])
    mid = pd.Timestamp("2016-01-01") + (end - pd.Timestamp("2016-01-01")) / 2
    try:
        ind = get_industry(code, date=str(mid.date()))
        lay = lambda k: (ind.get(k) or {}).get("industry_name")
        ind_rows.append({"code": code, "sw_l1_name": lay("sw_l1"), "sw_l2_name": lay("sw_l2"),
                         "sw_l3_name": lay("sw_l3"), "probe_date": str(mid.date())})
    except Exception as exc:  # noqa: BLE001
        ind_rows.append({"code": code, "sw_l1_name": None, "sw_l2_name": None,
                         "sw_l3_name": None, "probe_date": "ERR:" + str(exc)[:60]})

panel = pd.concat(px_rows, ignore_index=True)
panel.to_csv("delisted_panel_20261013.csv", index=False, encoding="utf-8-sig")

ev = finance.run_query(query(finance.STK_XR_XD).filter(finance.STK_XR_XD.code.in_(targets)))
ev = ev[ev["transfer_ratio"].notna()][["code", "a_registration_date", "transfer_ratio"]]
ev.to_csv("delisted_events_20261013.csv", index=False, encoding="utf-8-sig")

indm = pd.DataFrame(ind_rows)
indm.to_csv("delisted_indmap_20261013.csv", index=False, encoding="utf-8-sig")

print("PROBE_JSON_START")
print(json.dumps({"n_targets": len(targets), "panel_rows": int(len(panel)),
                  "event_rows": int(len(ev)),
                  "files": ["delisted_panel_20261013.csv", "delisted_events_20261013.csv",
                            "delisted_indmap_20261013.csv"]}, ensure_ascii=False))
print("PROBE_JSON_END")
