"""软性分 vs 基线的净值图：全区间（对齐表格口径）+ 2026 年内。"""
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
from tech_rotation import metrics  # noqa: E402

OUT = ROOT / "results"
COLS = ["① 基线 ΔAR×TIP", "③ 软性分 floor=0.3", "④ 软性分 floor=0.5"]
LABEL = {"① 基线 ΔAR×TIP": "基线 ΔAR×TIP", "③ 软性分 floor=0.3": "软性分 floor=0.3",
         "④ 软性分 floor=0.5": "软性分 floor=0.5"}
COLOR = {"① 基线 ΔAR×TIP": "#2c3e50", "③ 软性分 floor=0.3": "#c0392b",
         "④ 软性分 floor=0.5": "#1f77b4"}
plt.rcParams["font.sans-serif"] = ["PingFang SC", "Heiti SC", "Arial Unicode MS", "DejaVu Sans"]
plt.rcParams["axes.unicode_minus"] = False


def draw(nav, start, end, fname, title, log):
    sub = nav[(nav.index >= start) & (nav.index <= end)]
    fig, axes = plt.subplots(2, 1, figsize=(12, 8.2), sharex=True,
                             gridspec_kw={"height_ratios": [3, 1.2]})
    ax = axes[0]
    for c in COLS:
        ax.plot(sub.index, sub[c], lw=1.9, color=COLOR[c], label=LABEL[c])
    ax.set_yscale("log" if log else "linear")
    ax.set_title(title, fontsize=12)
    ax.set_ylabel("净值" + ("（对数轴）" if log else ""))
    ax.grid(alpha=0.3)
    ax.legend(loc="upper left", fontsize=9)
    lines = []
    for c in COLS:
        r = sub[c].pct_change().dropna()
        m = metrics(r)
        lines.append(f"{LABEL[c]}：年化 {m['annual_return']:.1%}  夏普 {m['sharpe']:.3f}  "
                     f"回撤 {m['max_drawdown']:.1%}  Calmar {m['calmar']:.3f}")
    ax.text(0.015, 0.03, "\n".join(lines), transform=ax.transAxes, fontsize=8.5, va="bottom",
            bbox=dict(boxstyle="round", fc="white", ec="0.75", alpha=0.92))
    ax2 = axes[1]
    for c in COLS:
        dd = sub[c] / sub[c].cummax() - 1
        ax2.plot(dd.index, dd, lw=1.3, color=COLOR[c], label=LABEL[c])
    ax2.set_ylabel("回撤")
    ax2.grid(alpha=0.3)
    ax2.legend(loc="lower left", fontsize=8)
    fig.tight_layout()
    dest = OUT / fname
    fig.savefig(dest, dpi=140, bbox_inches="tight")
    print("wrote", dest)
    for c in COLS:
        r = sub[c].pct_change().dropna()
        m = metrics(r)
        print(f"  {LABEL[c]}: 年化 {m['annual_return']:.2%} 夏普 {m['sharpe']:.4f} "
              f"回撤 {m['max_drawdown']:.2%} Calmar {m['calmar']:.4f}")


def main() -> None:
    nav = pd.read_csv(OUT / "soft_score_macro_nav.csv", index_col=0, parse_dates=True)
    draw(nav, "2017-01-03", "2026-07-31", "nav_soft_score_full.png",
         "组合 + ΔAR×TIP：基线 vs 宏观剪刀差软性分（2017-01 ~ 2026-07）", True)
    draw(nav, "2026-01-01", "2026-10-30", "nav_soft_score_2026.png",
         "2026 年内：基线 vs 软性分（截至 2026-10-30）", False)


if __name__ == "__main__":
    main()
