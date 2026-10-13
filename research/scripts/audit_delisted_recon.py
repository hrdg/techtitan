"""审计侦察：本线的行业聚合面板是否包含已退市股票。

检查三件事：
1. quantdb（本地面板的数据源）里是否存在退市股；
2. 本线的 sw_l2 成员名单里是否可能包含退市股；
3. 用已知退市股抽样核对。
"""
from __future__ import annotations

import json
from pathlib import Path

import pandas as pd

QUANTDB = Path("/Users/hsh/quantmind/QuantMind_src/QuantMind-master/data/quantdb")
ROOT = Path(__file__).resolve().parents[2]
RAW = ROOT / "data" / "raw"

# 2016-2021 年间退市的 A 股抽样（含属于本线 10 个行业的标的）
SAMPLE = {
    "600401.SH": "海润光伏（光伏设备，2018-2019 退市）",
    "002450.SZ": "康得新（光学膜/消费电子链，2021 退市）",
    "300372.SZ": "欣泰电气（电气设备，2017 退市）",
    "600485.SH": "信威集团（通信设备，2021 退市）",
    "000939.SZ": "凯迪生态（电力/环保，2020 退市）",
    "600806.SH": "昆明机床（机械，2019 退市）",
    "000693.SZ": "华泽钴镍（有色，2019 退市）",
}


def main() -> None:
    val_dirs = sorted(QUANTDB.glob("5_technical_derived/valuation/dt=*"))
    latest = pd.read_parquet(val_dirs[-1] / "data.parquet", columns=["symbol"])
    earliest = pd.read_parquet(val_dirs[0] / "data.parquet", columns=["symbol"])
    cur = set(latest["symbol"])
    old = set(earliest["symbol"])
    print(f"quantdb 最新日股票数 {len(cur)}，最早日({val_dirs[0].name}) {len(old)}；"
          f"曾出现但最新日缺失 {len(old - cur)} 只")

    print()
    for code, desc in SAMPLE.items():
        print(f"  {code} {desc}: 最早日{'有' if code in old else '无'} / 最新日{'有' if code in cur else '无'}")

    members = json.loads((RAW / "sw2_members.json").read_text(encoding="utf-8"))
    union = set()
    for body in members["industries"].values():
        union.update(body["union"])
    jq_fmt = {s.replace(".SH", ".XSHG").replace(".SZ", ".XSHE") for s in cur}
    print()
    print(f"10 行业 union 成员数（聚宽格式）{len(union)}")
    print(f"其中在 quantdb 最新日存在的 {len(union & jq_fmt)}，"
          f"不在最新日的 {len(union - jq_fmt)}（可能是未上市/已退市/代码差异）")
    missing = sorted(union - jq_fmt)[:15]
    print("  示例:", missing)


if __name__ == "__main__":
    main()
