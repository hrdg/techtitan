"""Build 10 申万二级行业 daily aggregates for a date range inside JoinQuant research env.

Range is set by START/END below (run twice: 2015-2020 and 2021-2026) to keep each payload small.
Construction mirrors the local quantdb reconstruction so the two can be compared:
- 成分股 = get_industry_stocks(sw_l2)，2021-12-13 起按抽样日阶梯，此前冻结在该日名单；
- 行业收益 = 前一交易日流通市值加权；价格用后复权（含分红，见报告限制）；
- 行业 PB = Σ总市值 / Σ(总市值/市净率)，与本地整体法等价。
Read-only.
"""
import json

import numpy as np
import pandas as pd

from jqdata import *  # noqa: F401,F403,E402

CODES = ["801054", "801055", "801056", "801039", "801086"]
MDATES = ["2021-12-13", "2022-06-30", "2022-12-30", "2023-06-30", "2023-12-29",
          "2024-06-28", "2024-12-31", "2025-06-30", "2025-12-31", "2026-06-30", "2026-07-31"]

START, END = "2015-01-01", "2020-12-31"

members_union, members_by_date = {}, {}
for code in CODES:
    union = set()
    for d in MDATES:
        m = list(get_industry_stocks(code, date=d))
        members_by_date.setdefault(code, {})[d] = m
        union.update(m)
    members_union[code] = sorted(union)

syms = sorted({s for v in members_union.values() for s in v})

px_frames, val_frames = [], []
bounds = pd.date_range(START, END, freq="MS").tolist() + [pd.Timestamp(END) + pd.Timedelta(days=1)]
for a, b in zip(bounds[:-1], bounds[1:]):
    px_frames.append(get_price(syms, start_date=str(a.date()), end_date=str(b.date()),
                               frequency="daily", fields=["close"], fq="post", panel=False))
cal = list(get_trade_days(start_date=START, end_date=END))
for i in range(0, len(cal), 8):
    chunk = cal[i:i + 8]
    val_frames.append(get_valuation(syms, start_date=str(chunk[0]), end_date=str(chunk[-1]),
                                    fields=["market_cap", "circulating_market_cap", "pb_ratio"]))

px = pd.concat(px_frames, ignore_index=True)
px["time"] = pd.to_datetime(px["time"])
val = pd.concat(val_frames, ignore_index=True)
val["time"] = pd.to_datetime(val["day"])
val = val.drop(columns=["day"])
px = px.drop_duplicates(["code", "time"])
val = val.drop_duplicates(["code", "time"])

m = px.merge(val, on=["code", "time"], how="inner").sort_values(["code", "time"])
m["ret"] = m.groupby("code")["close"].pct_change()
m.loc[m["ret"].abs() > 1.5, "ret"] = np.nan
m["float_mv_yi"] = pd.to_numeric(m["circulating_market_cap"], errors="coerce")
m["cap"] = pd.to_numeric(m["market_cap"], errors="coerce")
m["pb"] = pd.to_numeric(m["pb_ratio"], errors="coerce")
m["equity"] = np.where(m["pb"] > 0, m["cap"] / m["pb"], np.nan)
m["fmv_prev"] = m.groupby("code")["float_mv_yi"].shift(1)

dates = pd.Index(sorted(m["time"].unique()))
codes = pd.Index(sorted(m["code"].unique()))


def pivot(col):
    return m.pivot_table(index="time", columns="code", values=col).reindex(index=dates, columns=codes)


ret, fmv, fmv_prev, cap, eq = (pivot(c) for c in ["ret", "float_mv_yi", "fmv_prev", "cap", "equity"])
code_pos = {c: i for i, c in enumerate(codes)}
date_pos = {d: i for i, d in enumerate(dates)}

rows = []
for code in CODES:
    mask = np.zeros((len(dates), len(codes)), dtype=bool)
    for d in dates:
        if d < pd.Timestamp("2021-12-13"):
            mem = members_union[code]
        else:
            chosen = MDATES[0]
            for k in MDATES:
                if pd.Timestamp(k) <= d:
                    chosen = k
            mem = members_by_date[code][chosen]
        idx = [code_pos[s] for s in mem if s in code_pos]
        if idx:
            mask[date_pos[d], idx] = True
    w = fmv_prev.where(mask)
    r = ret.where(mask)
    ok = w.notna() & r.notna() & (w > 0)
    num = (w.where(ok, 0.0) * r.where(ok, 0.0)).sum(axis=1)
    den = w.where(ok, 0.0).sum(axis=1)
    rows.append(pd.DataFrame({
        "date": dates, "code": code,
        "ret": (num / den.replace(0.0, np.nan)).values,
        "float_mv_yi": fmv.where(mask).sum(axis=1).values,
        "sum_total_mv_yi": cap.where(mask).sum(axis=1).values,
        "sum_equity_yi": eq.where(mask).sum(axis=1).values,
        "n_members": mask.sum(axis=1),
        "n_used": ok.sum(axis=1).values,
    }))

panel = pd.concat(rows, ignore_index=True)
panel["date"] = pd.to_datetime(panel["date"]).dt.strftime("%Y-%m-%d")
out = {"source": "joinquant research env, get_price(fq=post) + get_valuation",
       "range": [START, END], "rows": int(len(panel)), "n_symbols": len(syms),
       "panel": panel.round(6).to_dict(orient="records")}
print("PROBE_JSON_START")
print(json.dumps(out, ensure_ascii=False, separators=(",", ":")))
print("PROBE_JSON_END")
