"""净值图：2017 起至 2026-10 全区间 + 2026 年内。"""
from __future__ import annotations

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
    PortfolioSpec, absorption_and_concentration, build_daily_weights, delta_zscore,
    metrics, nav_curve, portfolio_returns, relative_valuation, run_timing_overlay,
)

RAW = ROOT / "data" / "raw"
OUT = ROOT / "results"
TH = 1.5
plt.rcParams["font.sans-serif"] = ["PingFang SC", "Heiti SC", "Arial Unicode MS", "DejaVu Sans"]
plt.rcParams["axes.unicode_minus"] = False


def tip_gate(dates: pd.DatetimeIndex) -> pd.Series:
    t = pd.read_parquet(RAW / "tip_daily.parquet")
    t["date"] = pd.to_datetime(t["date"])
    s = t.set_index("date")["close"].sort_index()
    s.index = pd.DatetimeIndex(s.index).astype("datetime64[ns]")
    score = pd.concat([s / s.shift(d) - 1 for d in (28, 84, 168, 364)], axis=1).mean(axis=1)
    g = pd.Series(np.where(score > 0, 1.0, 0.0), index=s.index)
    g[score.isna()] = np.nan
    m = pd.merge_asof(pd.DataFrame({"date": dates}), g.dropna().rename("tip").reset_index(),
                      on="date", direction="backward", allow_exact_matches=False)
    return pd.Series(m["tip"].values, index=dates).shift(1)


def main() -> None:
    df = pd.read_parquet(RAW / "industry_panel_latest.parquet")
    df["date"] = pd.to_datetime(df["date"]).dt.tz_localize(None)
    ret = df.pivot(index="date", columns="code", values="ret")
    pb = df.pivot(index="date", columns="code", values="pb")
    fmv = df.pivot(index="date", columns="code", values="float_mv")
    ar, conc = absorption_and_concentration(ret, fmv)
    dc, rv, d_ar = delta_zscore(conc), relative_valuation(pb), delta_zscore(ar)
    w = build_daily_weights(dc, rv, ret.index, PortfolioSpec(2, 4, "combined"),
                            "2017-01-03", str(ret.index.max().date()))
    r = portfolio_returns(w, ret)
    r = r[r.index >= "2017-01-03"]
    b = pd.read_parquet(RAW / "benchmark_csi_daily.parquet")
    b["date"] = pd.to_datetime(b["date"]).dt.tz_localize(None)
    bond = b[b["code"] == "H11006"].set_index("date")["close"].pct_change().reindex(r.index)
    timed, state = run_timing_overlay(d_ar, r, bond, TH)
    tg = tip_gate(r.index).fillna(0.0)
    both = pd.Series(np.where(state.clip(0, 1) * tg > 0.5, 1.0, 0.0), index=r.index)
    timed_tip = both * r + (1 - both) * bond
    tech50 = b[b["code"] == "931380"].set_index("date")["close"].reindex(r.index).pct_change()

    series = {"组合+ΔAR(1.5)": timed, "+TIP综合动量": timed_tip, "组合（无择时）": r, "科技50": tech50}
    colors = {"组合+ΔAR(1.5)": "#c0392b", "+TIP综合动量": "#1f77b4",
              "组合（无择时）": "#2c3e50", "科技50": "#7f8c8d"}

    def draw(start, end, fname, title, log):
        sub = {k: v[(v.index >= start) & (v.index <= end)] for k, v in series.items()}
        nav = pd.DataFrame(sub).apply(nav_curve)
        fig, axes = plt.subplots(2, 1, figsize=(12, 8.5), sharex=True,
                                 gridspec_kw={"height_ratios": [3, 1.2]})
        ax = axes[0]
        for k in series:
            ax.plot(nav.index, nav[k], lw=1.8, color=colors[k], label=k)
        ax.set_yscale("log" if log else "linear")
        ax.set_title(title, fontsize=12)
        ax.set_ylabel("净值" + ("（对数轴）" if log else ""))
        ax.grid(alpha=0.3)
        ax.legend(loc="upper left", fontsize=9)
        stats = []
        for k in series:
            m = metrics(sub[k].dropna())
            stats.append(f"{k}: 年化 {m['annual_return']:.1%}  回撤 {m['max_drawdown']:.1%}  "
                         f"夏普 {m['sharpe']:.2f}")
        ax.text(0.015, 0.03, "\n".join(stats), transform=ax.transAxes, fontsize=8.5,
                va="bottom", bbox=dict(boxstyle="round", fc="white", ec="0.75", alpha=0.92))
        off = state.reindex(nav.index) <= 0.5
        ax.fill_between(nav.index, ax.get_ylim()[0], ax.get_ylim()[1], where=off,
                        color="crimson", alpha=0.07)
        ax2 = axes[1]
        for k in ("组合+ΔAR(1.5)", "+TIP综合动量", "组合（无择时）"):
            dd = nav[k] / nav[k].cummax() - 1
            ax2.plot(dd.index, dd, lw=1.2, color=colors[k], label=k)
        ax2.set_ylabel("回撤")
        ax2.grid(alpha=0.3)
        ax2.legend(loc="lower left", fontsize=8)
        fig.tight_layout()
        dest = OUT / fname
        fig.savefig(dest, dpi=140, bbox_inches="tight")
        print("wrote", dest)
        for k in series:
            m = metrics(sub[k].dropna())
            print(f"  {k}: 区间 {sub[k].index.min().date()}~{sub[k].index.max().date()} "
                  f"年化 {m['annual_return']:.2%} 回撤 {m['max_drawdown']:.2%} "
                  f"夏普 {m['sharpe']:.3f} 累计 {m['cum_return']:.1%}")

    draw("2017-01-03", str(r.index.max().date()), "nav_full_to_202610.png",
         "高集中度高估值（k1=2,k2=4）｜2017-01 ~ 2026-10（阴影＝ΔAR 风险规避期）", True)
    draw("2026-01-01", str(r.index.max().date()), "nav_2026_ytd.png",
         "2026 年内净值（截至 2026-10-30）", False)


if __name__ == "__main__":
    main()
