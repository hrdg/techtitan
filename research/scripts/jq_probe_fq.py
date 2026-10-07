"""Diagnose whether chunked get_price(fq='post') breaks 后复权 consistency."""
import json

import pandas as pd

from jqdata import *  # noqa: F401,F403,E402

syms = ["000009.XSHE", "002049.XSHE", "600460.XSHG"]

whole = get_price(syms, start_date="2016-01-01", end_date="2016-12-31", frequency="daily",
                  fields=["close"], fq="post", panel=False)
whole["time"] = pd.to_datetime(whole["time"])

frames = []
for a, b in [("2016-01-01", "2016-02-01"), ("2016-02-01", "2016-03-01")]:
    part = get_price(syms, start_date=a, end_date=b, frequency="daily",
                     fields=["close"], fq="post", panel=False)
    part["time"] = pd.to_datetime(part["time"])
    frames.append(part)
chunked = pd.concat(frames, ignore_index=True).drop_duplicates(["code", "time"])

w = whole.pivot(index="time", columns="code", values="close")
c = chunked.pivot(index="time", columns="code", values="close")
both = w.join(c, lsuffix="_whole", rsuffix="_chunked", how="inner")
out = {"n": int(len(both))}
for s in syms:
    rw = both[f"{s}_whole"].pct_change().dropna()
    rc = both[f"{s}_chunked"].pct_change().dropna()
    out[s] = {"max_abs_diff_ret": float((rw - rc).abs().max()),
              "level_ratio_end": float(both[f"{s}_chunked"].iloc[-1] / both[f"{s}_whole"].iloc[-1]),
              "level_ratio_start": float(both[f"{s}_chunked"].iloc[0] / both[f"{s}_whole"].iloc[0])}

# 停牌处理：skip_paused 默认
nn = get_price(syms, start_date="2016-01-01", end_date="2016-01-15", frequency="daily",
               fields=["close"], fq="post", panel=False)
out["jan_pause_nan"] = int(nn["close"].isna().sum())
out["rows_whole"] = int(len(whole))
out["rows_chunked"] = int(len(chunked))

print("PROBE_JSON_START")
print(json.dumps(out, ensure_ascii=False))
print("PROBE_JSON_END")
