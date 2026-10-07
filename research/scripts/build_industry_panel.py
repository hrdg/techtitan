"""Rebuild the 10 申万二级行业 daily series from constituent data (quantdb, 2016-01-04+).

Why: 申万官方只发布 2021-12-13 起 801737/801735/801745/801103/801078 的日度数据，研报却用
2015-2026 回溯序列（万得自算）。本脚本用成分股自建代理面板，并在 2021-12-13 后与申万官方数据
做重合期校验（validate_proxy_panel.py）。

Proxy construction:
- 成分股：joinquant get_industry_stocks(sw_l2)；2021-12-13 起按抽样日阶梯取 PIT 名单，
  此前冻结在 2021-12-13 名单。
- 行业收益：流通市值加权，权重用前一交易日成分股 float_mv。
- 个股收益：不复权收盘价按送股/配股除权调整（保留现金分红除息下跌）→ 价格指数口径。
- 行业 PB：整体法 Σ总市值 / Σ净资产；行业流通市值：Σ float_mv。
"""
from __future__ import annotations

import os

import argparse
import glob
import hashlib
import json
from pathlib import Path

import numpy as np
import pandas as pd

QUANTDB = Path(os.environ.get("QUANTDB_DIR", "/Users/hsh/quantmind/QuantMind_src/QuantMind-master/data/quantdb"))
ROOT = Path(__file__).resolve().parents[2]
RAW = ROOT / "data" / "raw"
START, END = "20160104", "20260731"


def membership_frame(raw: dict) -> dict[str, dict[str, list[str]]]:
    return {c: v["members_by_date"] for c, v in raw["industries"].items()}


def to_qdb(sym: str) -> str:
    """joinquant .XSHE/.XSHG -> quantdb .SZ/.SH"""
    return sym.replace(".XSHE", ".SZ").replace(".XSHG", ".SH")


def members_for(code: str, date: pd.Timestamp, by_date: dict[str, list[str]]) -> list[str]:
    keys = sorted(by_date)
    chosen = keys[0]
    for k in keys:
        if pd.Timestamp(k) <= date:
            chosen = k
    return by_date[chosen]


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--members", default="sw2_members.json")
    ap.add_argument("--out", default="industry_panel_proxy.parquet")
    args = ap.parse_args()
    raw = json.loads((RAW / args.members).read_text(encoding="utf-8"))
    by_date_all = {
        c: {d: [to_qdb(s) for s in lst] for d, lst in v.items()}
        for c, v in membership_frame(raw).items()
    }
    names = {c: v["name"] for c, v in raw["industries"].items()}
    symbols = sorted({to_qdb(s) for v in raw["industries"].values() for s in v["union"]})
    sym_set = set(symbols)
    print("union symbols:", len(symbols))

    # --- split (送股/配股) adjustment series per symbol ---
    adj_events = {}
    for sym in symbols:
        p = QUANTDB / "3_financial_data/dividend_factors" / f"{sym}.parquet"
        if not p.exists():
            continue
        ev = pd.read_parquet(p)
        if len(ev) == 0:
            continue
        ratio, out = 1.0, []
        for t, b, a in zip(ev["time"], ev.get("stockBonus", 0.0), ev.get("allotment", 0.0)):
            b = 0.0 if pd.isna(b) else float(b)
            a = 0.0 if pd.isna(a) else float(a)
            ratio *= 1.0 + b / 10.0 + a / 10.0
            out.append((pd.Timestamp(t), ratio))
        if out:
            adj_events[sym] = pd.DataFrame(out, columns=["date", "ratio"])

    val_rows, px_rows = [], []
    dv_all = sorted(glob.glob(str(QUANTDB / "5_technical_derived/valuation/dt=*")))
    dp_all = sorted(glob.glob(str(QUANTDB / "1_kline_data/daily_unadjusted/dt=*")))
    for i, (dv, dp) in enumerate(zip(dv_all, dp_all)):
        dt = Path(dv).name.split("=")[1]
        if dt < START or dt > END:
            continue
        v = pd.read_parquet(Path(dv) / "data.parquet",
                            columns=["symbol", "time", "total_mv", "float_mv", "equity"])
        v = v[v["symbol"].isin(sym_set)]
        v["date"] = pd.to_datetime(v["time"])
        val_rows.append(v[["date", "symbol", "total_mv", "float_mv", "equity"]])
        p = pd.read_parquet(Path(dp) / "data.parquet", columns=["symbol", "time", "close", "amount"])
        market_amount = float(pd.to_numeric(p["amount"], errors="coerce").sum())   # 全市场成交额（万元）
        p = p[p["symbol"].isin(sym_set)]
        p["date"] = pd.to_datetime(p["time"])
        p["market_amount"] = market_amount
        px_rows.append(p[["date", "symbol", "close", "amount", "market_amount"]])
        if i % 500 == 0:
            print("  loaded", dt, len(val_rows), flush=True)

    val = pd.concat(val_rows, ignore_index=True)
    px = pd.concat(px_rows, ignore_index=True)
    px["amount"] = pd.to_numeric(px["amount"], errors="coerce")
    print("valuation rows", len(val), "price rows", len(px))

    adj_long = pd.concat(
        [df.assign(symbol=s) for s, df in adj_events.items()], ignore_index=True
    ) if adj_events else pd.DataFrame(columns=["date", "ratio", "symbol"])
    if len(adj_long):
        adj_long["date"] = pd.to_datetime(adj_long["date"], errors="coerce").astype("datetime64[ns]")
        adj_long["ratio"] = pd.to_numeric(adj_long["ratio"], errors="coerce")
        adj_long = adj_long.dropna(subset=["date"])
        adj_long = adj_long.sort_values("date").drop_duplicates(["symbol", "date"], keep="last")
    px["date"] = px["date"].astype("datetime64[ns]")
    px = px.merge(adj_long, on=["date", "symbol"], how="left").sort_values(["symbol", "date"])
    # 关键：面板起点之前的历史送转事件必须计入基准比例，否则首个面板内除权日会出现虚假跳变。
    px_min_date = px["date"].min()
    pre = adj_long[adj_long["date"] < px_min_date].sort_values("date").groupby("symbol")["ratio"].last()
    px["ratio"] = px.groupby("symbol")["ratio"].ffill()
    px["ratio"] = px["ratio"].fillna(px["symbol"].map(pre)).fillna(1.0)
    px["adj_close"] = px["close"] * px["ratio"]
    px["ret"] = px.groupby("symbol")["adj_close"].pct_change()
    # cap absurd returns from data errors
    px.loc[px["ret"].abs() > 1.5, "ret"] = np.nan

    dates = pd.Index(sorted(val["date"].unique()))
    syms = pd.Index(symbols)
    fmv = val.pivot_table(index="date", columns="symbol", values="float_mv").reindex(index=dates, columns=syms)
    tmv = val.pivot_table(index="date", columns="symbol", values="total_mv").reindex(index=dates, columns=syms)
    eq = val.pivot_table(index="date", columns="symbol", values="equity").reindex(index=dates, columns=syms)
    ret = px.pivot_table(index="date", columns="symbol", values="ret").reindex(index=dates, columns=syms)
    amt = px.pivot_table(index="date", columns="symbol", values="amount").reindex(index=dates, columns=syms)
    mkt_amt = px.groupby("date")["market_amount"].first().reindex(dates)
    print("matrices", fmv.shape)

    w_prev = fmv.shift(1)
    out_rows = []
    for code, by_date in by_date_all.items():
        mask = pd.DataFrame(False, index=dates, columns=syms)
        for d in dates:
            m = members_for(code, d, by_date)
            mask.loc[d, [s for s in m if s in sym_set]] = True
        w = w_prev.where(mask)
        r = ret.where(mask)
        valid = w.notna() & r.notna() & (w > 0)
        num = (w.where(valid, 0.0) * r.where(valid, 0.0)).sum(axis=1)
        den = w.where(valid, 0.0).sum(axis=1)
        ind_ret = num / den.replace(0.0, np.nan)
        ind_fmv = fmv.where(mask).sum(axis=1)
        ind_amt = amt.where(mask).sum(axis=1)                       # 万元
        pos_eq = eq.where(mask)
        sum_tmv = tmv.where(mask).sum(axis=1)
        sum_eq = pos_eq.sum(axis=1)
        ind_pb = sum_tmv / sum_eq.replace(0.0, np.nan)
        ind_pe = np.nan
        out_rows.append(pd.DataFrame({
            "date": dates, "code": code, "name": names[code],
            "ret": ind_ret.to_numpy(), "float_mv": ind_fmv.to_numpy(),
            "pb": ind_pb.to_numpy(), "sum_total_mv_yi": sum_tmv.to_numpy(),
            "sum_equity_yi": sum_eq.to_numpy(),
            "amount_wan": ind_amt.to_numpy(),
            "turnover_pct": (ind_amt.to_numpy() * 1e4 / ind_fmv.to_numpy()) * 100,
            "amount_share_pct": (ind_amt.to_numpy() / mkt_amt.to_numpy()) * 100,
            "n_members": mask.sum(axis=1).to_numpy(),
            "n_used": valid.sum(axis=1).to_numpy(),
        }))
    panel = pd.concat(out_rows, ignore_index=True).sort_values(["date", "code"])
    dest = RAW / args.out
    panel.to_parquet(dest, index=False)
    (RAW / (args.out.replace(".parquet", "") + "_manifest.json")).write_text(json.dumps({
        "schema": "constituent-rebuilt proxy of 申万二级行业指数",
        "source_data": {
            "stock_panel": str(QUANTDB),
            "membership": "joinquant get_industry_stocks(sw_l2) via research exec",
            "membership_dates": raw["dates"],
        },
        "construction": {
            "industry_return": "float_mv(t-1) weighted, split-adjusted price return (cash dividends not reinvested)",
            "industry_pb": "sum(total_mv)/sum(equity), 整体法",
            "membership": "PIT step from 2021-12-13 samples; frozen at 2021-12-13 list before that",
        },
        "range": [str(dates.min().date()), str(dates.max().date())],
        "industries": len(by_date_all),
        "rows": int(len(panel)),
        "sha256": hashlib.sha256(panel.to_csv(index=False).encode()).hexdigest(),
    }, ensure_ascii=False, indent=2), encoding="utf-8")
    print("wrote", dest, panel.shape)


if __name__ == "__main__":
    main()
