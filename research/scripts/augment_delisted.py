"""幸存者偏差补齐：把已退市股票的贡献增量并入行业序列。

方法（不必重建原始面板）：
  行业加权收益 ret_old 的隐含分子 = float_mv_old(t-1) × ret_old(t)，
  加入退市股后：num_new = num_old + Σ_j float_mv_j(t-1) × r_j(t)，
               den_new = float_mv_old(t-1) + Σ_j float_mv_j(t-1)，
               ret_new = num_new / den_new
  其中 r_j 为退市股按送转调整后的价格收益；float_mv 取聚宽流通市值（亿元→元）。
PB 同理按 Σ总市值/Σ(总市值/市净率) 合并。

映射：按聚宽 2014 版行业枚举打标；电源设备再用 sw_l3 细分到光伏设备/电池。
"""
from __future__ import annotations

import json
from pathlib import Path

import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parents[2]
RAW = ROOT / "data" / "raw"

# 2014 版枚举分组 -> 2021 版行业代码；电源设备按 sw_l3 细分
GROUP2IND = {"半导体": "801081", "消费电子": "801085", "计算机设备": "801101",
             "通信设备": "801102", "汽车零部件": "801093"}
POWER_L3 = {"光伏设备III": "801735", "光伏辅材III": "801735", "锂电池III": "801737"}
# 枚举里同时落在两个分组的按 sw_l3 判定（600680 终端设备 -> 通信设备）
OVERRIDE = {"600680.XSHG": "801102"}


def assign(mapdf: pd.DataFrame) -> dict:
    out = {}
    for _, r in mapdf.iterrows():
        code = r["code"]
        if code in OVERRIDE:
            out[code] = OVERRIDE[code]
            continue
        l3 = r["sw_l3_name"]
        if r["groups"] == "电源设备":
            if l3 in POWER_L3:
                out[code] = POWER_L3[l3]
            continue
        if "|" in str(r["groups"]):
            continue
        out[code] = GROUP2IND.get(r["groups"])
    return {k: v for k, v in out.items() if v}


def main() -> None:
    panel = pd.read_parquet(RAW / "industry_panel_final.parquet")
    panel["date"] = pd.to_datetime(panel["date"])
    prox = pd.read_parquet(RAW / "industry_panel_proxy.parquet",
                           columns=["date", "code", "sum_total_mv_yi", "sum_equity_yi"])
    prox["date"] = pd.to_datetime(prox["date"])
    panel = panel.merge(prox, on=["date", "code"], how="left")
    mapdf = pd.read_csv(RAW / "delisted_mapping_20261013.csv")
    ind_of = assign(mapdf)
    px = pd.read_csv(RAW / "delisted_panel_20261013.csv")
    px["date"] = pd.to_datetime(px["date"])
    ev = pd.read_csv(RAW / "delisted_events_20261013.csv")
    ev["a_registration_date"] = pd.to_datetime(ev["a_registration_date"], errors="coerce")

    px = px[px["code"].isin(ind_of)].copy()
    px["ind"] = px["code"].map(ind_of)
    px = px.sort_values(["code", "date"])
    # 送转调整：ratio = Π(1 + 每10股送转/10)
    fac = {}
    for code, g in ev[ev["code"].isin(ind_of)].groupby("code"):
        g = g.dropna(subset=["a_registration_date"]).sort_values("a_registration_date")
        run, rows = 1.0, []
        for d, t in zip(g["a_registration_date"], g["transfer_ratio"]):
            run *= 1.0 + float(t) / 10.0
            rows.append((d, run))
        if rows:
            fac[code] = pd.DataFrame(rows, columns=["date", "ratio"])
    base = {c: 1.0 for c in ind_of}
    for code, f in fac.items():
        first_px = px.loc[px["code"] == code, "date"].min()
        base[code] = float(f.loc[f["date"] < first_px, "ratio"].max()) if (f["date"] < first_px).any() else 1.0
    allf = pd.concat([f.assign(code=c) for c, f in fac.items()], ignore_index=True) if fac else pd.DataFrame(
        columns=["date", "ratio", "code"])
    px = px.merge(allf, on=["date", "code"], how="left").sort_values(["code", "date"])
    px["ratio"] = px.groupby("code")["ratio"].ffill()
    px["ratio"] = px["ratio"].fillna(px["code"].map(base))
    px["adj"] = px["close"] * px["ratio"]
    px["ret"] = px.groupby("code")["adj"].pct_change()
    px.loc[px["ret"].abs() > 1.0, "ret"] = np.nan
    px["fmv"] = pd.to_numeric(px["circulating_market_cap"], errors="coerce") * 1e8
    px["eq"] = np.where(px["pb_ratio"] > 0,
                        pd.to_numeric(px["market_cap"], errors="coerce") / px["pb_ratio"], np.nan)
    px["tmv"] = pd.to_numeric(px["market_cap"], errors="coerce") * 1e8

    dates = pd.Index(sorted(panel["date"].unique()))
    contrib = {}
    for ind, g in px.groupby("ind"):
        num = (g["fmv"].shift(1) * g["ret"]).groupby(g["date"]).sum().reindex(dates)
        den = g["fmv"].shift(1).groupby(g["date"]).sum().reindex(dates)
        fmt = g["fmv"].groupby(g["date"]).sum().reindex(dates)
        eqs = g["eq"].groupby(g["date"]).sum().reindex(dates)
        tms = g["tmv"].groupby(g["date"]).sum().reindex(dates)
        contrib[ind] = {"num": num.fillna(0.0), "den": den.fillna(0.0),
                        "fmv": fmt.fillna(0.0), "eq": eqs.fillna(0.0), "tmv": tms.fillna(0.0)}

    out = panel.copy()
    out["date"] = pd.to_datetime(out["date"])
    summary = {}
    for ind, c in contrib.items():
        m = out["code"] == ind
        old_fmv = out.loc[m, "float_mv"].shift(1)
        old_ret = out.loc[m, "ret"]
        num = old_fmv * old_ret + c["num"].values
        den = old_fmv + c["den"].values
        new_ret = num / den.replace(0.0, np.nan)
        new_fmv = out.loc[m, "float_mv"] + c["fmv"].values
        old_tmv = out.loc[m, "sum_total_mv_yi"] * 1e8
        old_eq = out.loc[m, "sum_equity_yi"] * 1e8
        new_tmv = old_tmv + c["tmv"].values
        new_eq = old_eq + c["eq"].values
        new_pb = new_tmv / np.where(new_eq > 0, new_eq, np.nan)
        out.loc[m, "ret_dl"] = new_ret.values
        out.loc[m, "float_mv_dl"] = new_fmv.values
        out.loc[m, "pb_dl"] = new_pb
        n_old = pd.Series(old_ret.values, index=out.index[m])
        n_new = pd.Series(new_ret.values, index=out.index[m])
        summary[ind] = {
            "n_delisted": int(px.loc[px["ind"] == ind, "code"].nunique()),
            "n_delisted_days": int((px["ind"] == ind).sum()),
            "cum_old": round(float((1 + n_old.fillna(0)).prod() - 1), 4),
            "cum_new": round(float((1 + n_new.fillna(0)).prod() - 1), 4),
            "ret_corr": round(float(n_old.corr(n_new)), 4),
            "te_ann": round(float((n_new - n_old).std() * np.sqrt(250)), 4),
            "max_float_mv_share": round(float((c["fmv"] / new_fmv.values).max()), 4),
        }

    for c in ["ret_dl", "float_mv_dl", "pb_dl"]:
        out[c] = out[c].fillna(out[{"ret_dl": "ret", "float_mv_dl": "float_mv",
                                    "pb_dl": "pb"}[c]])
    out["ret_orig"], out["float_mv_orig"], out["pb_orig"] = out["ret"], out["float_mv"], out["pb"]
    out["ret"], out["float_mv"], out["pb"] = out["ret_dl"], out["float_mv_dl"], out["pb_dl"]
    dest = RAW / "industry_panel_final_delisted.parquet"
    out.drop(columns=["ret_dl", "float_mv_dl", "pb_dl"]).to_parquet(dest, index=False)
    (RAW / "industry_panel_final_delisted_manifest.json").write_text(json.dumps({
        "purpose": "在行业序列中并入已退市股票的贡献（幸存者偏差补齐）",
        "mapping": {k: v for k, v in sorted(ind_of.items())},
        "per_industry": summary,
        "panel": dest.name,
    }, ensure_ascii=False, indent=2, default=float), encoding="utf-8")
    print(f"补齐 {len(ind_of)} 只退市股，覆盖 {len(summary)} 个行业")
    print(pd.DataFrame(summary).T.to_string())
    print("wrote", dest)


if __name__ == "__main__":
    main()
