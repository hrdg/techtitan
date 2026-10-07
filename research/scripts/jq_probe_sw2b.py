"""Second JoinQuant probe: enumerate finance tables and 申万二级 availability."""
import json

res = {}


def probe(key, fn):
    try:
        res[key] = fn()
    except Exception as exc:  # noqa: BLE001
        res[key] = "ERR:%s:%s" % (type(exc).__name__, str(exc)[:180])


from jqdata import *  # noqa: F401,F403,E402
from jqdata import finance  # noqa: E402

probe("finance_dir", lambda: sorted(n for n in dir(finance) if not n.startswith("_")))
probe("jqdata_dir_sw", lambda: sorted(n for n in dir() if "valuation" in n.lower()))


def span(codes, start, end):
    df = get_price(codes, start_date=start, end_date=end, frequency="daily",
                   fields=["close"], panel=False)
    if df is None or len(df) == 0:
        return {"rows": 0}
    return {"rows": int(len(df)), "min": str(df["time"].min())[:10], "max": str(df["time"].max())[:10]}


for c in ["801737", "801735", "801081", "000012.XSHG", "000510.XSHG"]:
    probe("gp_" + c, lambda c=c: span([c], "2016-01-04", "2016-02-04"))


def sw1_span():
    q = query(finance.SW1_DAILY_PRICE).filter(finance.SW1_DAILY_PRICE.code == "801730")
    df = finance.run_query(q)
    return {"rows": int(len(df)), "min": str(df["date"].min()), "max": str(df["date"].max())}


probe("sw1_power_equipment_span", sw1_span)


def sw2_members(d):
    df = get_industry_stocks("801737", date=d)
    return {"n": len(df), "sample": list(df[:5])}


for d in ["2019-06-28", "2022-06-30", "2026-06-30"]:
    probe("sw2_members_" + d, lambda d=d: sw2_members(d))


def sw2_members_alt(d):
    df = get_industry_stocks("801737.XSHG", date=d)
    return {"n": len(df), "sample": list(df[:5])}


probe("sw2_members_alt_2022", lambda: sw2_members_alt("2022-06-30"))


def all_sw_l2():
    df = get_industries("sw_l2", date="2026-06-30")
    return {"n": int(len(df)), "codes": list(df.index[:10]), "has_801737": "801737" in df.index}


probe("sw_l2_industries", all_sw_l2)
probe("sw_l2_history_len", lambda: len(get_industries("sw_l2")))

print("PROBE_JSON_START")
print(json.dumps(res, ensure_ascii=False, default=str)[:6000])
print("PROBE_JSON_END")
