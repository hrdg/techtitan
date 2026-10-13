"""枚举 2014 版行业在历史日期（2016-2021）的成分，找出我的 10 个行业里的退市股。

2014→2021 版行业映射（按名称对应，只覆盖可干净对应的部分）：
  801081 半导体II        → 半导体
  801085 电子制造II      → 消费电子
  801101 计算机设备II    → 计算机设备
  801102 通信设备II      → 通信设备
  801093 汽车零部件II    → 汽车零部件
  801733 电源设备II      → 电池 + 光伏设备（两行业在 2021 版才拆分，此处合并统计）
  801102/801750 等其余略；电池/光伏/军工电子/IT服务/自动化设备在 2014 版无独立对应
产物：研究区 CSV（可 download）。
"""
import json

import pandas as pd

from jqdata import *  # noqa: F401,F403,E402

DATES = ["2016-06-30", "2017-06-30", "2018-06-29", "2019-06-28", "2020-06-30", "2021-06-30"]
MAP14 = {
    "801081": "半导体（2021版 801081）",
    "801085": "消费电子（2021版 801085）",
    "801101": "计算机设备（2021版 801101）",
    "801102": "通信设备（2021版 801102）",
    "801093": "汽车零部件（2021版 801093）",
    "801733": "电源设备→电池+光伏设备（2021版 801737/801735）",
}

allsec = get_all_securities(types=["stock"])
allsec["end_date"] = pd.to_datetime(allsec["end_date"])
delisted = set(allsec[allsec["end_date"] < pd.Timestamp("2026-06-01")].index)
live = set(allsec[allsec["end_date"] >= pd.Timestamp("2026-06-01")].index)

rows = []
union_by_ind = {}
for code14, label in MAP14.items():
    members = set()
    for d in DATES:
        try:
            members.update(get_industry_stocks(code14, date=d))
        except Exception as exc:  # noqa: BLE001
            rows.append({"industry": label, "date": d, "err": str(exc)[:80]})
    union_by_ind[label] = members
    dead = sorted(members & delisted)
    rows.append({"industry": label, "date": "UNION", "n_members": len(members),
                 "n_delisted": len(dead), "delisted": ",".join(dead)})

out = pd.DataFrame(rows)
out.to_csv("delisted_in_tech_industries_20261013.csv", index=False, encoding="utf-8-sig")

summary = {}
for label, members in union_by_ind.items():
    dead = sorted(members & delisted)
    summary[label] = {"n_members_union": len(members), "n_delisted": len(dead), "codes": dead[:20]}

print("PROBE_JSON_START")
print(json.dumps({"check_dates": DATES, "n_delisted_total": len(delisted),
                  "summary": summary, "file": "delisted_in_tech_industries_20261013.csv"},
                 ensure_ascii=False))
print("PROBE_JSON_END")
