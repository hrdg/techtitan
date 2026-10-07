"""Fetch 申万二级行业 constituent lists from JoinQuant for the 10 tech-growth industries.

JQ's sw_l2 classification starts 2021-12-11, so the union over sampled dates approximates
the 2021-version classification. Returns per-industry union + per-date counts.
Read-only.
"""
import json

from jqdata import *  # noqa: F401,F403,E402

CODES = ["801081", "801085", "801737", "801735", "801745",
         "801101", "801103", "801102", "801093", "801078"]
DATES = ["2021-12-13", "2022-06-30", "2022-12-30", "2023-06-30", "2023-12-29",
         "2024-06-28", "2024-12-31", "2025-06-30", "2025-12-31", "2026-06-30", "2026-07-31"]

out = {"as_of": "2026-10-06", "source": "joinquant get_industry_stocks(sw_l2)",
       "dates": DATES, "industries": {}}

industries = get_industries("sw_l2")
names = {c: str(industries.loc[c, "name"]) for c in CODES if c in industries.index}

for code in CODES:
    union, per_date, lists = set(), {}, {}
    for d in DATES:
        try:
            members = list(get_industry_stocks(code, date=d))
        except Exception as exc:  # noqa: BLE001
            members = []
            per_date[d] = "ERR:" + str(exc)[:60]
            continue
        per_date[d] = len(members)
        union.update(members)
        lists[d] = sorted(members)
    out["industries"][code] = {
        "name": names.get(code),
        "per_date_counts": per_date,
        "union_size": len(union),
        "union": sorted(union),
        "members_by_date": lists,
    }

print("PROBE_JSON_START")
print(json.dumps(out, ensure_ascii=False))
print("PROBE_JSON_END")
