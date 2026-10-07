"""Render reproduction charts (NAV / timing / ΔAR)."""
from __future__ import annotations

import sys
from pathlib import Path

import matplotlib
import numpy as np
import pandas as pd

matplotlib.use("Agg")
import matplotlib.dates as mdates  # noqa: E402
import matplotlib.pyplot as plt  # noqa: E402

plt.rcParams["font.sans-serif"] = ["PingFang SC", "Heiti SC", "Arial Unicode MS", "DejaVu Sans"]
plt.rcParams["axes.unicode_minus"] = False

ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / "results"
sys.path.insert(0, str(ROOT / "src"))
from tech_rotation import delta_zscore  # noqa: E402


def main() -> None:
    nav = pd.read_csv(OUT / "nav_final.csv", index_col=0, parse_dates=True)
    th = pd.read_csv(OUT / "threshold_sensitivity_final.csv")
    absorp = pd.read_csv(OUT / "absorption_final.csv", index_col=0, parse_dates=True)
    spec = pd.read_csv(OUT / "spec_sensitivity.csv")
    dar = delta_zscore(absorp["AR"])
    dar = dar[dar.index >= "2017-01-01"]

    fig, axes = plt.subplots(3, 1, figsize=(12, 12),
                             gridspec_kw={"height_ratios": [3, 3, 1.3]})

    ax = axes[0]
    for col, style in [("高集中度高估值", "-"), ("高估值", "-"), ("高集中度", "-"),
                       ("科技50", "--"), ("行业等权", "--"), ("中证A500", "--")]:
        if col in nav:
            ax.plot(nav.index, nav[col], style, lw=1.6, label=col)
    ax.set_yscale("log")
    ax.set_title("图 A：三组合与基准净值（复现，2017-01~2026-07）")
    ax.legend(fontsize=9)
    ax.grid(alpha=0.3)

    ax = axes[1]
    ax.plot(nav.index, nav["高集中度高估值"], lw=1.8, label="高集中度高估值（无择时）")
    ax.plot(nav.index, nav["高集中度高估值_择时"], lw=1.8, label="叠加 ΔAR 择时（阈值 1.5）")
    ax.set_yscale("log")
    ax.set_title("图 B：择时前后净值（复现）")
    ax.legend(fontsize=9)
    ax.grid(alpha=0.3)

    ax = axes[2]
    ax.plot(dar.index, dar.values, lw=1.0, color="steelblue", label="ΔAR")
    ax.axhline(1.5, color="crimson", ls="--", lw=1.0, label="阈值 1.5")
    ax.axhline(0.0, color="gray", lw=0.8)
    off = dar > 1.5
    ax.fill_between(dar.index, dar.min(), dar.max(), where=off,
                    color="crimson", alpha=0.15, label="预警（持有国债）")
    ax.set_title("图 C：吸收比率变化量 ΔAR 与预警区间")
    ax.legend(fontsize=8, ncol=3)
    ax.grid(alpha=0.3)
    ax.xaxis.set_major_locator(mdates.YearLocator(1))
    ax.xaxis.set_major_formatter(mdates.DateFormatter("%Y"))

    fig.tight_layout()
    dest = OUT / "reproduction_overview.png"
    fig.savefig(dest, dpi=140)
    print("wrote", dest)

    fig2, ax2 = plt.subplots(figsize=(9, 4.5))
    ax2.plot(th["threshold"], th["full_sharpe"], "o-", label="复现：全样本夏普")
    t6 = {0.0: 1.0065, 0.25: 1.0261, 0.5: 1.1395, 0.75: 1.2763, 1.0: 1.2497,
          1.25: 1.2719, 1.5: 1.3724, 1.75: 1.2626, 2.0: 1.1026}
    ax2.plot(list(t6), list(t6.values()), "s--", label="研报表 6：全样本夏普")
    ax2.set_xlabel("择时阈值 threshold")
    ax2.set_ylabel("夏普比率")
    ax2.set_title("图 D：择时阈值敏感性（复现 vs 研报表 6）")
    ax2.legend()
    ax2.grid(alpha=0.3)
    fig2.tight_layout()
    dest2 = OUT / "threshold_comparison.png"
    fig2.savefig(dest2, dpi=140)
    print("wrote", dest2)

    fig3, ax3 = plt.subplots(figsize=(11, 4.5))
    r0 = spec[spec["rv"].str.startswith("R0")]
    xpos = np.arange(len(r0))
    ax3.bar(xpos - 0.2, r0["AR1_mean"], width=0.2, label="第一主成分 AR1 均值")
    ax3.bar(xpos, r0["AR2_mean"], width=0.2, label="第二主成分 AR2 均值")
    ax3.bar(xpos + 0.2, r0["AR_total_mean"], width=0.2, label="前两个主成分合计")
    ax3.axhspan(0.7, 0.9, color="gray", alpha=0.15, label="研报图8 合计区间 0.7-0.9")
    ax3.set_xticks(xpos)
    ax3.set_xticklabels([v.split("_")[0] for v in r0["variant"]], fontsize=9)
    ax3.set_title("图 E：PCA 预处理变体的吸收比率结构（研报图8 为参考带，非逐点目标）")
    ax3.legend(fontsize=8)
    ax3.grid(alpha=0.3, axis="y")
    fig3.tight_layout()
    dest3 = OUT / "spec_sensitivity.png"
    fig3.savefig(dest3, dpi=140)
    print("wrote", dest3)


if __name__ == "__main__":
    main()
