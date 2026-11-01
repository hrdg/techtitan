"""输出研报口径的当前信号：高集中度高估值选行业 + ΔAR(1.5) 择时 + ETF 映射。"""
from __future__ import annotations

import sys
from pathlib import Path

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
    "801081": ("512480.XSHG", "半导体ETF"),
    "801085": ("159732.XSHE", "消费电子ETF"),
    "801737": ("159755.XSHE", "电池ETF"),
    "801735": ("515790.XSHG", "光伏ETF"),
    "801745": ("512660.XSHG", "军工ETF（一级代理）"),
    "801101": ("159998.XSHE", "计算机ETF（一级代理）"),
    "801103": ("159852.XSHE", "软件ETF（兄弟二级代理）"),
    "801102": ("515880.XSHG", "通信ETF"),
    "801093": ("159565.XSHE", "汽车零部件ETF"),
    "801078": ("159530.XSHE", "机器人ETF（自动化代理）"),
}
BOND = ("511010.XSHG", "国债ETF")


def main() -> None:
    df = pd.read_parquet(RAW / "industry_panel_latest.parquet")
    df["date"] = pd.to_datetime(df["date"]).dt.tz_localize(None)
    ret = df.pivot(index="date", columns="code", values="ret")
    pb = df.pivot(index="date", columns="code", values="pb")
    fmv = df.pivot(index="date", columns="code", values="float_mv")
    names = df.drop_duplicates("code").set_index("code")["name"].to_dict()

    ar, conc = absorption_and_concentration(ret, fmv)
    dc = delta_zscore(conc)
    rv = relative_valuation(pb)
    d_ar = delta_zscore(ar)
    last = ret.index.max()
    print(f"数据截止 {last.date()}（quantdb）")

    # 最近月末与调仓日
    s = pd.Series(ret.index, index=ret.index)
    me = pd.DatetimeIndex(s.groupby([ret.index.year, ret.index.month]).last().values)
    me_last = me[-1] if me[-1] < last else me[-2]
    print(f"最近月末信号日 {me_last.date()}")
    d, r = dc.loc[me_last].dropna(), rv.loc[me_last].dropna()
    top_dc = d.nlargest(6)
    top_rv = r.nlargest(4)
    hold = sorted(set(d.nlargest(4).index) & set(r.nlargest(2).index))
    print("\nΔC 集中度排名（前 6）:")
    for c, v in top_dc.items():
        print(f"  {names.get(c, c):<8} {c}  ΔC={v:+.3f}")
    print("\nRV 相对估值排名（前 4）:")
    for c, v in top_rv.items():
        print(f"  {names.get(c, c):<8} {c}  RV={v:.3f}")
    print("\n交集（k1=2 ∩ k2=4）:", [names.get(c, c) for c in hold] or "空 → 沿用上期")
    if hold:
        print("对应 ETF:", [f"{ETF[c][0]} {ETF[c][1]}" for c in hold])

    # 当前择时状态（用项目里已验证的状态机：信号 shift(1) 次日生效）
    zero = pd.Series(0.0, index=ret.index)
    _, state = run_timing_overlay(d_ar, zero, zero, TH)
    chg_idx = state[state.ne(state.shift())].index
    print(f"\n最近一次择时状态切换: {chg_idx[-1].date()} → "
          f"{'持策略组合' if state.loc[chg_idx[-1]] > 0.5 else '持国债指数'}")
    print(f"（上一状态自 {chg_idx[-2].date() if len(chg_idx) > 1 else '-'}）")
    print(f"\nΔAR 最近 10 个交易日（阈值 {TH}）:")
    for t in ret.index[-10:]:
        st = state.loc[t]
        print(f"  {t.date()}  AR={ar.loc[t]:.3f}  ΔAR={d_ar.loc[t]:+.2f}  → "
              f"{'持策略组合' if st > 0.5 else '持国债'}")
    print(f"\n当前状态（{last.date()} 收盘，次日执行）: "
          f"{'持策略组合' if state.loc[last] > 0.5 else '持国债指数'}")

    # 若按 10 月组合，最近一个月的持仓
    w = build_daily_weights(dc, rv, ret.index, PortfolioSpec(2, 4, "combined"),
                            str(ret.index[0].date()), str(last.date()))
    held = w[w.sum(axis=1) > 0]
    label = held.apply(lambda s: "、".join(names.get(c, c) for c in s[s > 0].index), axis=1)
    chg = label[label.ne(label.shift())].dropna()
    print("\n最近 5 次持仓变化:")
    for t, v in chg.tail(5).items():
        print(f"  {t.date()}  {v}")
    print("\n当前持仓（自最近一个调仓日起）:", label.iloc[-1] if len(label) else "空仓")


if __name__ == "__main__":
    main()
