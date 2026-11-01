"""输出下一期（2026-11）的研报口径信号：月频选行业 + 日频 ΔAR + TIP 闸。

信号日 = 最近一个交易日（也是 10 月最后一个交易日），执行日 = 下一个交易日。
"""
from __future__ import annotations

import sys
from pathlib import Path

import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))
from tech_rotation import (  # noqa: E402
    PortfolioSpec, absorption_and_concentration, build_daily_weights, delta_zscore,
    relative_valuation, run_timing_overlay,
)

RAW = ROOT / "data" / "raw"
TH = 1.5
ETF = {
    "801081": ("512480.XSHG", "半导体ETF"), "801085": ("159732.XSHE", "消费电子ETF"),
    "801737": ("159755.XSHE", "电池ETF"), "801735": ("515790.XSHG", "光伏ETF"),
    "801745": ("512660.XSHG", "军工ETF(一级代理)"), "801101": ("159998.XSHE", "计算机ETF(一级代理)"),
    "801103": ("159852.XSHE", "软件ETF(兄弟代理)"), "801102": ("515880.XSHG", "通信ETF"),
    "801093": ("159565.XSHE", "汽车零部件ETF"), "801078": ("159530.XSHE", "机器人ETF(代理)"),
}


def main() -> None:
    df = pd.read_parquet(RAW / "industry_panel_latest.parquet")
    df["date"] = pd.to_datetime(df["date"]).dt.tz_localize(None)
    ret = df.pivot(index="date", columns="code", values="ret")
    pb = df.pivot(index="date", columns="code", values="pb")
    fmv = df.pivot(index="date", columns="code", values="float_mv")
    names = df.drop_duplicates("code").set_index("code")["name"].to_dict()
    ar, conc = absorption_and_concentration(ret, fmv)
    dc, rv, d_ar = delta_zscore(conc), relative_valuation(pb), delta_zscore(ar)

    last = ret.index.max()
    sig = last                      # 10-30 同时是月末与最新交易日
    print(f"信号日 {sig.date()}（同时是 10 月最后交易日）｜面板 {ret.index.min().date()} ~ {last.date()}")
    print("执行日：下一个交易日 2026-11-02（周一）\n")

    d, r = dc.loc[sig].dropna(), rv.loc[sig].dropna()
    print("ΔC 集中度（前 6）:")
    for c, v in d.nlargest(6).items():
        print(f"  {names.get(c, c):<8} {c}  {v:+.3f}")
    print("\nRV 相对估值（前 4）:")
    for c, v in r.nlargest(4).items():
        print(f"  {names.get(c, c):<8} {c}  {v:.3f}")
    hold = sorted(set(d.nlargest(4).index) & set(r.nlargest(2).index))
    print("\n交集（k1=2 ∩ k2=4）:", [names.get(c, c) for c in hold])
    for c in hold:
        print(f"  → {ETF[c][0]} {ETF[c][1]}")

    zero = pd.Series(0.0, index=ret.index)
    _, state = run_timing_overlay(d_ar, zero, zero, TH)
    chg = state[state.ne(state.shift())].index
    print(f"\nΔAR（阈值 {TH}）: {d_ar.loc[sig]:+.2f} → "
          f"{'持策略组合' if state.loc[sig] > 0.5 else '持国债'}")
    print(f"最近切换 {chg[-1].date()}；信号为 0 时不动仓位（死区 0~1.5 保持）")

    tip = pd.read_parquet(RAW / "tip_daily.parquet")
    tip["date"] = pd.to_datetime(tip["date"])
    tp = tip.set_index("date")["close"].sort_index()
    tp.index = pd.DatetimeIndex(tp.index).astype("datetime64[ns]")
    score = pd.concat([tp / tp.shift(w) - 1 for w in (28, 84, 168, 364)], axis=1).mean(axis=1)
    ms = score.loc[:sig].dropna()
    print(f"\nTIP 综合动量: {ms.iloc[-1]:+.4f}（{ms.index[-1].date()}）→ "
          f"{'开' if ms.iloc[-1] > 0 else '关'}")
    expo = (state.loc[sig] > 0.5) and (ms.iloc[-1] > 0)
    print(f"\n最终：{'股票 100%' if expo else '国债 100%'}（ΔAR×TIP 口径）")

    # 周频变体（同一信号日、周内调仓）
    w = build_daily_weights(dc, rv, ret.index, PortfolioSpec(2, 4, "combined"),
                            "2017-01-03", str(last.date()), freq="W")
    row = w.loc[last]
    wk = [names.get(c, c) for c in row[row > 0].index]
    print(f"\n周频变体（每周首个交易日调仓）本周持仓: " + ("、".join(wk) if wk else "沿用上期"))


if __name__ == "__main__":
    main()
