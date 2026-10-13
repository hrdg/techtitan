"""生成幸存者偏差审计产物：行业层与策略层的补齐前后对照。"""
from __future__ import annotations

import json
from pathlib import Path

import pandas as pd

ROOT = Path(__file__).resolve().parents[2]
RAW = ROOT / "data" / "raw"
OUT = ROOT / "results"


def main() -> None:
    man = json.loads((RAW / "industry_panel_final_delisted_manifest.json").read_text(encoding="utf-8"))
    per = pd.DataFrame(man["per_industry"]).T.reset_index().rename(columns={"index": "code"})
    names = {"801085": "消费电子", "801093": "汽车零部件", "801101": "计算机设备",
             "801102": "通信设备", "801735": "光伏设备", "801737": "电池"}
    per["name"] = per["code"].map(names)
    per["cum_old"] = pd.to_numeric(per["cum_old"])
    per["cum_new"] = pd.to_numeric(per["cum_new"])
    per["cum_change_pp"] = ((per["cum_new"] - per["cum_old"]) * 100).round(1)
    per["te_ann_pct"] = (pd.to_numeric(per["te_ann"]) * 100).round(2)
    per = per[["code", "name", "n_delisted", "cum_old", "cum_new", "cum_change_pp",
               "ret_corr", "te_ann_pct", "max_float_mv_share"]]
    per.to_csv(OUT / "delisted_bias_by_industry.csv", index=False)

    a = pd.read_csv(OUT / "table4_5_final.csv").add_suffix("_orig")
    b = pd.read_csv(OUT / "table4_5_delisted.csv").add_suffix("_dl")
    m = pd.concat([a, b], axis=1)
    m = m.rename(columns={"strategy_orig": "strategy", "timing_orig": "timing"})
    m["ann_delta_pp"] = ((m["annual_return_dl"] - m["annual_return_orig"]) * 100).round(2)
    m["mdd_delta_pp"] = ((m["max_drawdown_dl"] - m["max_drawdown_orig"]) * 100).round(2)
    m["sharpe_delta"] = (m["sharpe_dl"] - m["sharpe_orig"]).round(3)
    keep = ["strategy", "timing", "annual_return_orig", "annual_return_dl", "ann_delta_pp",
            "max_drawdown_orig", "max_drawdown_dl", "mdd_delta_pp",
            "sharpe_orig", "sharpe_dl", "sharpe_delta"]
    m[keep].to_csv(OUT / "delisted_bias_by_strategy.csv", index=False)
    print(per.to_string(index=False))
    print()
    print(m[keep].to_string(index=False, float_format=lambda v: f"{v:,.4f}"))


if __name__ == "__main__":
    main()
