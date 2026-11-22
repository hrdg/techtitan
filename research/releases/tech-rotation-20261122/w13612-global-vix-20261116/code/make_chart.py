"""Regenerate the published COMMON-AXIS NAV and drawdown chart."""
from __future__ import annotations

from pathlib import Path

import matplotlib
import pandas as pd

matplotlib.use("Agg")
import matplotlib.pyplot as plt


ROOT = Path(__file__).resolve().parents[1]
LABELS = {
    "W_BASE": "W base",
    "W_GLOBAL_VIX": "W + global VIX state",
    "ER_BASE": "Effective-rank base",
    "ER_RISK_VIX": "ER + RISK_VIX",
}
COLORS = {
    "W_BASE": "#314b63",
    "W_GLOBAL_VIX": "#d76d43",
    "ER_BASE": "#668ea8",
    "ER_RISK_VIX": "#2e8b80",
}
STYLES = {
    "W_BASE": "-",
    "W_GLOBAL_VIX": "-",
    "ER_BASE": "--",
    "ER_RISK_VIX": "-",
}


def main() -> None:
    returns = pd.read_csv(
        ROOT / "data/daily_returns_common_axis_20261116.csv",
        parse_dates=["date"],
    ).set_index("date")
    metrics = pd.read_csv(ROOT / "outputs/performance_comparison_20261116.csv")
    metrics = metrics.set_index("arm")
    nav = (1.0 + returns).cumprod()
    drawdown = nav / nav.cummax() - 1.0
    fig, axes = plt.subplots(
        2,
        1,
        figsize=(14, 9),
        sharex=True,
        gridspec_kw={"height_ratios": [3.2, 1.2]},
    )
    for column, label in LABELS.items():
        row = metrics.loc[column]
        axes[0].plot(
            nav.index,
            nav[column],
            color=COLORS[column],
            ls=STYLES[column],
            lw=2.0,
            label=(
                f"{label} | {row['cagr']:.2%} | "
                f"SR {row['sharpe']:.3f} | MDD {row['mdd']:.2%}"
            ),
        )
        axes[1].plot(
            drawdown.index,
            drawdown[column] * 100.0,
            color=COLORS[column],
            ls=STYLES[column],
            lw=1.4,
        )
    axes[0].set_yscale("log")
    axes[0].set_ylabel("NAV (log scale)")
    axes[0].set_title(
        "Same-window comparison | 2019-08-01 to 2026-11-16",
        loc="left",
        fontweight="normal",
    )
    axes[0].grid(alpha=0.22)
    axes[0].legend(frameon=False, loc="upper left", fontsize=8.5)
    axes[1].set_ylabel("Drawdown (%)")
    axes[1].set_xlabel("Date")
    axes[1].grid(alpha=0.22)
    axes[1].axhline(0.0, color="#555555", lw=0.8)
    fig.tight_layout()
    output = ROOT / "outputs/common_axis_nav_drawdown.png"
    fig.savefig(output, dpi=180)
    plt.close(fig)
    print(output)


if __name__ == "__main__":
    main()
