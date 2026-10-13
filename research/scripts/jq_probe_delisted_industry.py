"""验证：用历史日期的行业成分能否取到后来退市的股票。Read-only。"""
import json

from jqdata import *  # noqa: F401,F403,E402

out = {}

for d in ["2016-06-30", "2018-06-29", "2019-06-28", "2021-06-30"]:
    try:
        inds = get_industries("sw_l2", date=d)
        out[f"industries_{d}"] = {"n": int(len(inds)), "sample": list(inds.index[:5]),
                                  "names": [str(inds.loc[i, "name"]) for i in inds.index[:5]]}
    except Exception as exc:  # noqa: BLE001
        out[f"industries_{d}"] = "ERR:" + str(exc)[:100]

for code in ["801733", "801080", "801750", "801770"]:
    for d in ["2018-06-29", "2019-06-28"]:
        try:
            m = list(get_industry_stocks(code, date=d))
            hits = [s for s in m if s in ("600401.XSHG", "002450.XSHE", "600485.XSHG", "000939.XSHE")]
            out[f"{code}_{d}"] = {"n": len(m), "delisted_hits": hits}
        except Exception as exc:  # noqa: BLE001
            out[f"{code}_{d}"] = "ERR:" + str(exc)[:80]

out["get_industry_300372_2016"] = str(get_industry("300372.XSHE", date="2016-06-30"))[:200]

print("PROBE_JSON_START")
print(json.dumps(out, ensure_ascii=False))
print("PROBE_JSON_END")
