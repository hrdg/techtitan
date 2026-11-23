#!/usr/bin/env python3
"""Rebuild ER_BASE with the frozen global-VIX half-exposure overlay.

The package is self-contained. It uses only the small input snapshots shipped
under ``inputs/`` and does not depend on the upstream private research tree.
"""
from __future__ import annotations

import argparse
import json
from pathlib import Path

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt
import numpy as np
import pandas as pd

HERE = Path(__file__).resolve().parent
START = pd.Timestamp("2019-08-01")
END = pd.Timestamp("2026-11-16")
COST = 0.0005
BOOT_BLOCK = 63
BOOT_DRAWS = 5000
SEEDS = (20261123, 20261124)


def performance(values: pd.Series) -> dict:
    clean = values.dropna().astype(float)
    nav = (1.0 + clean).cumprod()
    years = len(clean) / 250.0
    cagr = float(nav.iloc[-1] ** (1.0 / years) - 1.0)
    vol = float(clean.std(ddof=1) * np.sqrt(250.0))
    mdd = float((nav / nav.cummax() - 1.0).min())
    return {
        "start": str(clean.index.min().date()),
        "end": str(clean.index.max().date()),
        "cagr": cagr,
        "vol": vol,
        "sharpe": cagr / vol if vol > 0 else np.nan,
        "mdd": mdd,
        "calmar": cagr / abs(mdd) if mdd < 0 else np.nan,
        "total_return": float(nav.iloc[-1] - 1.0),
        "n_days": len(clean),
    }


def paired_bootstrap(
    candidate: pd.Series,
    control: pd.Series,
    seed: int,
) -> dict:
    frame = pd.concat(
        [candidate.rename("candidate"), control.rename("control")],
        axis=1,
    ).dropna()
    values = frame.to_numpy(float)
    n = len(values)
    rng = np.random.default_rng(seed)
    starts = rng.integers(
        0, n, size=(BOOT_DRAWS, int(np.ceil(n / BOOT_BLOCK)))
    )
    offsets = np.arange(BOOT_BLOCK)
    idx = (starts[:, :, None] + offsets[None, None, :]) % n
    idx = idx.reshape(BOOT_DRAWS, -1)[:, :n]
    sampled = values[idx]
    nav = np.cumprod(1.0 + sampled, axis=1)
    years = sampled.shape[1] / 250.0
    cagr = nav[:, -1] ** (1.0 / years) - 1.0
    vol = sampled.std(axis=1, ddof=1) * np.sqrt(250.0)
    running = np.maximum.accumulate(nav, axis=1)
    mdd = (nav / running - 1.0).min(axis=1)
    metrics = {}
    for side, slice_ in (("candidate", 0), ("control", 1)):
        draw = sampled[:, :, slice_]
        nav_side = np.cumprod(1.0 + draw, axis=1)
        cagr_side = nav_side[:, -1] ** (1.0 / years) - 1.0
        vol_side = draw.std(axis=1, ddof=1) * np.sqrt(250.0)
        run_side = np.maximum.accumulate(nav_side, axis=1)
        mdd_side = (nav_side / run_side - 1.0).min(axis=1)
        metrics[side] = {
            "cagr": cagr_side,
            "sharpe": np.divide(
                cagr_side,
                vol_side,
                out=np.full_like(cagr_side, np.nan),
                where=vol_side > 0,
            ),
            "mdd": mdd_side,
            "calmar": np.divide(
                cagr_side,
                np.abs(mdd_side),
                out=np.full_like(cagr_side, np.nan),
                where=mdd_side < 0,
            ),
        }
    point = performance(candidate)
    base = performance(control)
    result = {"seed": seed, "paths": BOOT_DRAWS, "days": n}
    for key in ("cagr", "sharpe", "mdd", "calmar"):
        delta = metrics["candidate"][key] - metrics["control"][key]
        result[f"{key}_point_delta"] = float(point[key] - base[key])
        result[f"{key}_ci025"] = float(np.nanquantile(delta, 0.025))
        result[f"{key}_ci975"] = float(np.nanquantile(delta, 0.975))
        result[f"{key}_p_two_sided"] = float(
            min(
                1.0,
                2.0
                * min(
                    np.mean(delta <= 0.0),
                    np.mean(delta >= 0.0),
                ),
            )
        )
    return result


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--output-dir", type=Path, default=HERE / "outputs")
    parser.add_argument("--figure", type=Path, default=HERE / "artifacts" / "nav_drawdown.png")
    args = parser.parse_args()
    args.output_dir.mkdir(parents=True, exist_ok=True)
    args.figure.parent.mkdir(parents=True, exist_ok=True)

    returns = pd.read_csv(
        HERE / "inputs/daily_returns_common_axis.csv",
        parse_dates=["date"],
    ).set_index("date")
    state = pd.read_csv(
        HERE / "inputs/vix_state.csv",
        parse_dates=["date"],
    ).set_index("date").reindex(returns.index)
    bond = pd.read_csv(
        HERE / "inputs/bond_returns.csv",
        parse_dates=["date"],
    ).set_index("date")["bond_return"].reindex(returns.index)
    if returns.index.min() != START or returns.index.max() != END:
        raise AssertionError("unexpected common-axis endpoints")
    if state["vix_multiplier"].isna().any() or bond.isna().any():
        raise AssertionError("missing VIX state or bond return")

    multiplier = state["vix_multiplier"].astype(float).clip(0.0, 1.0)
    turnover = multiplier.diff().abs().fillna(0.0)
    candidate = (
        multiplier * returns["ER_BASE"]
        + (1.0 - multiplier) * bond
        - COST * turnover
    )
    average = float(multiplier.mean())
    same_average = average * returns["ER_BASE"] + (1.0 - average) * bond
    stress = (
        multiplier * returns["ER_BASE"]
        + (1.0 - multiplier) * bond
        - 0.001 * turnover
    )
    arms = {
        "W_BASE": returns["W_BASE"],
        "W_GLOBAL_VIX": returns["W_GLOBAL_VIX"],
        "ER_BASE": returns["ER_BASE"],
        "ER_GLOBAL_VIX": candidate,
        "ER_GLOBAL_VIX_10BP": stress,
        "ER_BASE_SAME_AVG": same_average,
        "ER_RISK_VIX": returns["ER_RISK_VIX"],
    }
    windows = {
        "FULL": (START, END),
        "2019_2021": (START, pd.Timestamp("2021-12-31")),
        "2022_2024": (pd.Timestamp("2022-01-01"), pd.Timestamp("2024-12-31")),
        "2025_2026": (pd.Timestamp("2025-01-01"), END),
        "2026": (pd.Timestamp("2026-01-01"), END),
    }
    rows = []
    for arm, series in arms.items():
        for label, (start, end) in windows.items():
            rows.append(
                {"arm": arm, "window": label, **performance(series.loc[start:end])}
            )
    metrics = pd.DataFrame(rows)
    metrics.to_csv(args.output_dir / "metrics.csv", index=False)
    pd.DataFrame(arms).loc[START:END].to_csv(
        args.output_dir / "daily_returns.csv"
    )

    comparisons = [
        ("ER_GLOBAL_VIX", "ER_BASE"),
        ("ER_GLOBAL_VIX", "W_GLOBAL_VIX"),
        ("ER_GLOBAL_VIX", "ER_BASE_SAME_AVG"),
    ]
    bootstrap_rows = []
    for candidate_name, control_name in comparisons:
        for seed in SEEDS:
            bootstrap_rows.append(
                {
                    "candidate": candidate_name,
                    "control": control_name,
                    **paired_bootstrap(
                        arms[candidate_name],
                        arms[control_name],
                        seed,
                    ),
                }
            )
    bootstrap = pd.DataFrame(bootstrap_rows)
    bootstrap.to_csv(args.output_dir / "bootstrap.csv", index=False)

    fig, axes = plt.subplots(
        2,
        1,
        figsize=(14, 9),
        sharex=True,
        gridspec_kw={"height_ratios": [2.2, 1.0]},
    )
    plot_arms = {
        "W_BASE": ("W base", "#666666"),
        "W_GLOBAL_VIX": ("W + global VIX", "#1f77b4"),
        "ER_BASE": ("Effective-rank W/V2", "#2ca02c"),
        "ER_GLOBAL_VIX": ("Effective-rank + global VIX", "#d62728"),
    }
    for arm, (label, color) in plot_arms.items():
        value = arms[arm].loc[START:END].dropna()
        nav = (1.0 + value).cumprod()
        axes[0].plot(nav.index, nav, label=label, color=color, lw=1.6)
        axes[1].plot(
            nav.index,
            nav / nav.cummax() - 1.0,
            color=color,
            lw=0.9,
        )
    axes[0].set_title("Effective-rank W/V2 technology sleeve with global VIX")
    axes[0].set_ylabel("NAV")
    axes[0].grid(alpha=0.2)
    axes[0].legend(frameon=False, ncol=2)
    axes[1].set_ylabel("Drawdown")
    axes[1].grid(alpha=0.2)
    fig.tight_layout()
    fig.savefig(args.figure, dpi=180)
    plt.close(fig)

    full = metrics[metrics["window"].eq("FULL")].set_index("arm")
    summary = {
        "strategy_id": "ER-GLOBAL-VIX-252D80-HALF@20261123",
        "sample": [str(START.date()), str(END.date())],
        "alert_days": int((multiplier < 1.0).sum()),
        "alert_share": float((multiplier < 1.0).mean()),
        "average_sleeve_exposure": average,
        "decisions": full[["cagr", "sharpe", "mdd", "calmar"]].to_dict(
            orient="index"
        ),
        "conclusion": "POINT_ESTIMATE_IMPROVEMENT_STATISTICALLY_INCONCLUSIVE",
        "production_change": False,
    }
    (args.output_dir / "summary.json").write_text(
        json.dumps(summary, ensure_ascii=False, indent=2, allow_nan=False) + "\n",
        encoding="utf-8",
    )
    print(json.dumps(summary, ensure_ascii=False, indent=2, allow_nan=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
