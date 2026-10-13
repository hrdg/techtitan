"""给出退市股→2021 版行业的映射：枚举时按分组打标，电源设备再用 sw_l3 细分。"""
import json

import pandas as pd

from jqdata import *  # noqa: F401,F403,E402

GROUPS = {"801081": "半导体", "801085": "消费电子", "801101": "计算机设备",
          "801102": "通信设备", "801093": "汽车零部件", "801733": "电源设备"}
DATES = ["2016-06-30", "2017-06-30", "2018-06-29", "2019-06-28", "2020-06-30", "2021-06-30"]

allsec = get_all_securities(types=["stock"])
allsec["end_date"] = pd.to_datetime(allsec["end_date"])
allsec["start_date"] = pd.to_datetime(allsec["start_date"])
delisted = set(allsec[allsec["end_date"] < pd.Timestamp("2026-06-01")].index)

code2groups = {}
for code14, label in GROUPS.items():
    for d in DATES:
        try:
            for s in get_industry_stocks(code14, date=d):
                if s in delisted:
                    code2groups.setdefault(s, set()).add(label)
        except Exception:  # noqa: BLE001
            pass

rows = []
for code, groups in sorted(code2groups.items()):
    end = allsec.loc[code, "end_date"]
    start = allsec.loc[code, "start_date"]
    probe = max(start + pd.Timedelta(days=30), end - pd.Timedelta(days=60))
    l3 = None
    try:
        info = get_industry(code, date=str(probe.date()))
        l3 = ((info.get(code) or {}).get("sw_l3") or {}).get("industry_name")
    except Exception:  # noqa: BLE001
        pass
    rows.append({"code": code, "name": str(allsec.loc[code, "display_name"]),
                 "start": str(start.date()), "end": str(end.date()),
                 "groups": "|".join(sorted(groups)), "sw_l3_name": l3, "probe": str(probe.date())})

df = pd.DataFrame(rows)
df.to_csv("delisted_mapping_20261013.csv", index=False, encoding="utf-8-sig")
print("PROBE_JSON_START")
print(json.dumps({"n": int(len(df)),
                  "by_group": df["groups"].value_counts().to_dict(),
                  "power_l3": df[df["groups"] == "电源设备"]["sw_l3_name"].value_counts().to_dict(),
                  "file": "delisted_mapping_20261013.csv"}, ensure_ascii=False))
print("PROBE_JSON_END")
