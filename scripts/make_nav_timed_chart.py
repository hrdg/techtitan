"""净值图：高集中度高估值组合 + ΔAR 择时（threshold=1.5）对比无择时。"""
from __future__ import annotations

import json
import sys
from pathlib import Path

import matplotlib
import numpy as np
import pandas as pd

matplotlib.use("Agg")
import matplotlib.pyplot as plt  # noqa: E402

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from tech_rotation import (  # noqa: E402
    PortfolioSpec,
    absorption_and_concentration,
    build_daily_weights,
    delta_zscore,
    metrics,
    nav_curve,
    portfolio_returns,
    relative_valuation,
    run_timing_overlay,
)

RAW = ROOT / "data" / "raw"
OUT = ROOT / "results"
START, END, TH = "2017-01-01", "2026-07-31", 1.5

plt.rcParams["font.sans-serif"] = ["PingFang SC", "Heiti SC", "Arial Unicode MS", "DejaVu Sans"]
plt.rcParams["axes.unicode_minus"] = False


def risk_off_windows(state: pd.Series) -> list[tuple[pd.Timestamp, pd.Timestamp]]:
    off = (state <= 0.5).astype(int)
    grp = (off.diff() != 0).cumsum()
    out = []
    for _, v in off.groupby(grp):
        if v.iloc[0] == 1:
            out.append((v.index[0], v.index[-1]))
    return out


def main() -> None:
    df = pd.read_parquet(RAW / "industry_panel_final.parquet")
    df["date"] = pd.to_datetime(df["date"]).dt.tz_localize(None)
    ret = df.pivot(index="date", columns="code", values="ret")
    pb = df.pivot(index="date", columns="code", values="pb")
    fmv = df.pivot(index="date", columns="code", values="float_mv")
    ar, conc = absorption_and_concentration(ret, fmv)
    dc, d_ar = delta_zscore(conc), delta_zscore(ar)
    rv = relative_valuation(pb)

    b = pd.read_parquet(RAW / "benchmark_csi_daily.parquet")
    b["date"] = pd.to_datetime(b["date"]).dt.tz_localize(None)
    bond = b[b["code"] == "H11006"].set_index("date")["close"].reindex(ret.index).pct_change()

    w = build_daily_weights(dc, rv, ret.index, PortfolioSpec(2, 4, "combined"), START, END)
    r = portfolio_returns(w, ret)
    r = r[r.index >= START]
    timed, state = run_timing_overlay(d_ar, r, bond.reindex(r.index), TH)

    nav_raw, nav_timed = nav_curve(r), nav_curve(timed)
    dd_raw = nav_raw / nav_raw.cummax() - 1
    dd_timed = nav_timed / nav_timed.cummax() - 1
    m_raw, m_td = metrics(r), metrics(timed)
    windows = risk_off_windows(state)

    fig = plt.figure(figsize=(13, 11))
    gs = fig.add_gridspec(3, 1, height_ratios=[3.2, 1.5, 1.5], hspace=0.3)

    ax = fig.add_subplot(gs[0])
    ax.plot(nav_timed.index, nav_timed, lw=2.0, color="#c0392b",
            label=f"组合 + ΔAR 择时（阈值 {TH}）")
    ax.plot(nav_raw.index, nav_raw, lw=1.6, color="#2c3e50", alpha=0.85,
            label="组合（无择时）")
    for a, bnd in windows:
        ax.axvspan(a, bnd, color="crimson", alpha=0.10)
    ax.set_yscale("log")
    ax.set_title(f"高集中度高估值（k1=2, k2=4，等权 1-2 个行业）叠加 ΔAR 择时 vs 无择时\n"
                 f"2017-01-03 ~ 2026-07-31（红色区间 = 全仓国债指数）", fontsize=12)
    ax.set_ylabel("净值（对数轴）")
    ax.grid(alpha=0.3)
    txt = (f"择时后：累计 {m_td['cum_return']:.0%}  年化 {m_td['annual_return']:.1%}  "
           f"波动 {m_td['annual_vol']:.1%}  夏普 {m_td['sharpe']:.2f}  回撤 {m_td['max_drawdown']:.1%}\n"
           f"无择时：累计 {m_raw['cum_return']:.0%}  年化 {m_raw['annual_return']:.1%}  "
           f"波动 {m_raw['annual_vol']:.1%}  夏普 {m_raw['sharpe']:.2f}  回撤 {m_raw['max_drawdown']:.1%}")
    ax.text(0.015, 0.97, txt, transform=ax.transAxes, va="top", fontsize=10,
            bbox=dict(boxstyle="round", fc="white", ec="0.7", alpha=0.9))
    ax.legend(loc="lower right", fontsize=10)

    ax2 = fig.add_subplot(gs[1], sharex=ax)
    ax2.fill_between(dd_timed.index, dd_timed, 0, color="#c0392b", alpha=0.45, label="择时后回撤")
    ax2.plot(dd_raw.index, dd_raw, lw=1.0, color="#2c3e50", label="无择时回撤")
    ax2.set_ylabel("回撤")
    ax2.grid(alpha=0.3)
    ax2.legend(loc="lower left", fontsize=9)

    ax3 = fig.add_subplot(gs[2])
    yrs = sorted({d.year for d in r.index})
    a_raw = [(1 + r[r.index.year == y]).prod() - 1 for y in yrs]
    a_td = [(1 + timed[timed.index.year == y]).prod() - 1 for y in yrs]
    x = np.arange(len(yrs))
    ax3.bar(x - 0.2, a_raw, width=0.4, color="#2c3e50", alpha=0.85, label="无择时")
    ax3.bar(x + 0.2, a_td, width=0.4, color="#c0392b", alpha=0.85, label="择时 1.5")
    ax3.set_xticks(x)
    ax3.set_xticklabels([f"{y}" for y in yrs])
    ax3.axhline(0, color="black", lw=0.8)
    ax3.set_ylabel("年度收益")
    ax3.yaxis.set_major_formatter(lambda v, _: f"{v:.0%}")
    ax3.grid(alpha=0.3, axis="y")
    ax3.legend(fontsize=9)
    for xi, (v1, v2) in enumerate(zip(a_raw, a_td)):
        ax3.text(xi - 0.2, v1, f"{v1:.0%}", ha="center", va="bottom" if v1 >= 0 else "top", fontsize=7.5)
        ax3.text(xi + 0.2, v2, f"{v2:.0%}", ha="center", va="bottom" if v2 >= 0 else "top", fontsize=7.5)

    dest = OUT / "nav_timed_1p5.png"
    fig.savefig(dest, dpi=140, bbox_inches="tight")
    print("wrote", dest)
    print("\n风险规避区间（全仓国债）:")
    for a, bnd in windows:
        print(f"  {a.date()} ~ {bnd.date()}  ({(bnd - a).days} 自然日)")
    print("\n年度收益:")
    for y, v1, v2 in zip(yrs, a_raw, a_td):
        print(f"  {y}: 无择时 {v1:>7.1%} | 择时 {v2:>7.1%}")
    (OUT / "nav_timed_1p5_summary.json").write_text(json.dumps({
        "threshold": TH, "timed": m_td, "no_timing": m_raw,
        "risk_off_windows": [[str(a.date()), str(b.date())] for a, b in windows],
        "yearly": {str(y): {"no_timing": float(v1), "timed": float(v2)}
                   for y, v1, v2 in zip(yrs, a_raw, a_td)},
    }, ensure_ascii=False, indent=2, default=float), encoding="utf-8")


if __name__ == "__main__":
    main()
