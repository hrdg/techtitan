"""取"科技上游"资源类行业的聚宽 sw_l2 成分（与 10 科技行业同口径）。Read-only."""
import json

from jqdata import *  # noqa: F401,F403,E402

CODES = ["801054", "801055", "801056", "801039", "801086"]
MDATES = ["2021-12-13", "2022-06-30", "2022-12-30", "2023-06-30", "2023-12-29",
          "2024-06-28", "2024-12-31", "2025-06-30", "2025-12-31", "2026-06-30", "2026-07-31"]

out = {"as_of": "2026-10-07", "source": "joinquant get_industry_stocks(sw_l2)",
       "dates": MDATES, "industries": {}}
industries = get_industries("sw_l2")
for code in CODES:
    union, per_date, lists = set(), {}, {}
    for d in MDATES:
        try:
            m = list(get_industry_stocks(code, date=d))
        except Exception as exc:  # noqa: BLE001
            per_date[d] = "ERR:" + str(exc)[:60]
            continue
        per_date[d] = len(m)
        union.update(m)
        lists[d] = sorted(m)
    out["industries"][code] = {
        "name": str(industries.loc[code, "name"]) if code in industries.index else None,
        "per_date_counts": per_date, "union_size": len(union),
        "union": sorted(union), "members_by_date": lists,
    }
print("PROBE_JSON_START")
print(json.dumps(out, ensure_ascii=False))
print("PROBE_JSON_END")
