"""Probe JoinQuant research env for 申万二级行业指数 history backfill.

Runs remotely via: jqcli research exec --file <this> --yes
Read-only: only queries data.
"""
import json

res = {}


def probe(key, fn):
    try:
        res[key] = fn()
    except Exception as exc:  # noqa: BLE001
        res[key] = "ERR:%s:%s" % (type(exc).__name__, str(exc)[:180])


from jqdata import *  # noqa: F401,F403,E402
from jqdata import finance  # noqa: E402


def index_universe():
    df = get_all_securities(types=["index"])
    keys = list(df.index)
    sw = [k for k in keys if k.startswith("801") or "申万" in str(df.loc[k, "display_name"])]
    return {
        "n_index": len(keys),
        "n_sw_like": len(sw),
        "sw_sample": sw[:15],
        "sw_names": [str(df.loc[k, "display_name"]) for k in sw[:15]],
    }


probe("index_universe", index_universe)


def span(codes, start, end):
    df = get_price(codes, start_date=start, end_date=end, frequency="daily",
                   fields=["close"], panel=False)
    if df is None or len(df) == 0:
        return {"rows": 0}
    return {
        "rows": int(len(df)),
        "min": str(df["time"].min())[:10],
        "max": str(df["time"].max())[:10],
        "codes": sorted(set(df["code"]))[:5],
    }


for code in ["801737.XSHG", "801737.XSHE", "801735.XSHG", "801081.XSHG",
             "801103.XSHG", "801078.XSHG", "801745.XSHG"]:
    probe("get_price_2015_" + code, lambda c=code: span([c], "2015-01-05", "2015-02-05"))
probe("get_price_2022_801737", lambda: span(["801737.XSHG"], "2022-01-04", "2022-02-04"))


def finance_tables():
    names = [n for n in dir(finance) if n.isupper()]
    return {
        "sw_like": [n for n in names if "SW" in n or "INDUSTRY" in n],
        "daily_like": [n for n in names if "DAILY" in n][:30],
    }


probe("finance_tables", finance_tables)


def sw1_check():
    q = query(finance.SW1_DAILY_PRICE).filter(finance.SW1_DAILY_PRICE.code == "801080")
    df = finance.run_query(q)
    return {"rows": int(len(df)), "min": str(df["date"].min()), "max": str(df["date"].max()),
            "cols": list(df.columns)}


probe("sw1_daily_price", sw1_check)


def sw2_check():
    tbl = getattr(finance, "SW2_DAILY_PRICE", None)
    if tbl is None:
        return "no SW2_DAILY_PRICE"
    df = finance.run_query(query(tbl).filter(tbl.code == "801737"))
    return {"rows": int(len(df)), "min": str(df["date"].min()), "max": str(df["date"].max()),
            "cols": list(df.columns)}


probe("sw2_daily_price", sw2_check)
probe("index_valuation_801737",
      lambda: len(get_index_valuation(["801737.XSHG"], start_date="2020-01-02", end_date="2020-01-10")))
probe("index_valuation_000510",
      lambda: len(get_index_valuation(["000510.XSHG"], start_date="2020-01-02", end_date="2020-01-10")))


def sw2_members():
    df = get_industry_stocks("801737", date="2020-06-30")
    return {"n": len(df), "sample": df[:5]}


probe("sw2_members_2020", sw2_members)

print("PROBE_JSON_START")
print(json.dumps(res, ensure_ascii=False, default=str))
print("PROBE_JSON_END")
