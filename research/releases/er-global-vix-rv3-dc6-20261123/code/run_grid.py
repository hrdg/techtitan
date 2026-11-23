"""Evaluate a bounded RV/Delta-C top-K grid for ER_GLOBAL_VIX."""
from __future__ import annotations

import json
import os
import argparse
import subprocess
import sys
from pathlib import Path

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt
import numpy as np
import pandas as pd

PACKAGE = Path(__file__).resolve().parent.parent
ROOT = PACKAGE.parents[2]
OUT = PACKAGE / "outputs"
ART = PACKAGE / "artifacts"
LOGS = PACKAGE / "logs"
V2_SCRIPT = ROOT / "scripts/v2_etf_normalized_backtest.py"
INPUTS = PACKAGE / "inputs"
TECH_RETURNS = INPUTS / "daily_returns_common_axis.csv"
VIX_STATE = INPUTS / "vix_state.csv"
BOND_RETURNS = INPUTS / "bond_returns.csv"
INDUSTRY = ROOT / "data/raw/industry_panel_18_ext.parquet"
SELECTIONS = INPUTS / "monthly_selections.csv"
START = pd.Timestamp("2019-08-01")
END = pd.Timestamp("2026-11-16")
SWITCH_COST = 0.001
OVERLAY_COST = 0.0005
OVERLAY_STRESS = 0.001
RV_GRID = (1, 2, 3, 4, 5)
DC_GRID = (3, 4, 5, 6, 7)
BOOT_BLOCK = 63
BOOT_DRAWS = 5000
SEED = 20261123


def performance(values: pd.Series) -> dict:
    clean = values.dropna().astype(float)
    nav = (1.0 + clean).cumprod()
    years = len(clean) / 250.0
    cagr = float(nav.iloc[-1] ** (1.0 / years) - 1.0)
    vol = float(clean.std(ddof=1) * np.sqrt(250.0))
    downside = float(
        np.sqrt(np.mean(np.minimum(clean.to_numpy(float), 0.0) ** 2))
        * np.sqrt(250.0)
    )
    mdd = float((nav / nav.cummax() - 1.0).min())
    return {
        "start": str(clean.index.min().date()),
        "end": str(clean.index.max().date()),
        "cagr": cagr,
        "vol": vol,
        "sharpe": cagr / vol if vol > 0 else np.nan,
        "sortino": cagr / downside if downside > 0 else np.nan,
        "mdd": mdd,
        "calmar": cagr / abs(mdd) if mdd < 0 else np.nan,
        "total_return": float(nav.iloc[-1] - 1.0),
        "n_days": len(clean),
    }


def build_v2_grid(run_root: Path) -> None:
    run_root.mkdir(parents=True, exist_ok=True)
    for rv_k in RV_GRID:
        for dc_k in DC_GRID:
            path = run_root / f"rv{rv_k}_dc{dc_k}"
            path.mkdir(parents=True, exist_ok=True)
            env = os.environ.copy()
            env.update(
                {
                    "K1": str(rv_k),
                    "K2": str(dc_k),
                    "OUT_DIR": str(path),
                    "V2_INDUSTRY_PANEL": str(INDUSTRY),
                    "START": str(START.date()),
                    "END": str(END.date()),
                    "V2_EXCLUDE_PARTIAL_MONTH": "0",
                }
            )
            with (path / "run.log").open("w", encoding="utf-8") as handle:
                completed = subprocess.run(
                    [str(ROOT / ".venv/bin/python"), str(V2_SCRIPT)],
                    cwd=str(ROOT),
                    env=env,
                    stdout=handle,
                    stderr=subprocess.STDOUT,
                )
            if completed.returncode != 0:
                raise RuntimeError(
                    f"V2 grid {rv_k},{dc_k} failed; see {path / 'run.log'}"
                )


def effective_rank_path(
    w_returns: pd.Series,
    v2_returns: pd.Series,
) -> pd.Series:
    frame = pd.concat(
        [w_returns.rename("W"), v2_returns.rename("V2")],
        axis=1,
        sort=True,
    ).dropna()
    selections = pd.read_csv(SELECTIONS, parse_dates=["decision_date"])
    selections = selections[
        selections["selector"].eq("EFFECTIVE_RANK_HIGH_W")
    ].set_index("month")["selected"]
    months = pd.PeriodIndex(sorted(frame.index.to_period("M").unique()), freq="M")
    parts = []
    previous = "W"
    for month in months:
        days = frame.index[frame.index.to_period("M") == month]
        if days.empty:
            continue
        selected = selections.get(str(month), previous)
        values = frame.loc[days, selected].copy()
        if selected != previous:
            values.iloc[0] -= SWITCH_COST
        parts.append(values)
        previous = selected
    return pd.concat(parts).sort_index().rename("ER_BASE")


def vix_overlay(
    sleeve: pd.Series,
    multiplier: pd.Series,
    bond: pd.Series,
    cost: float,
) -> pd.Series:
    frame = pd.concat(
        [sleeve.rename("sleeve"), multiplier.rename("f"), bond.rename("bond")],
        axis=1,
    ).dropna()
    f = frame["f"].clip(0.0, 1.0)
    return (
        f * frame["sleeve"]
        + (1.0 - f) * frame["bond"]
        - cost * f.diff().abs().fillna(0.0)
    )


def paired_bootstrap(candidate: pd.Series, control: pd.Series) -> dict:
    frame = pd.concat(
        [candidate.rename("candidate"), control.rename("control")], axis=1
    ).dropna()
    values = frame.to_numpy(float)
    n = len(values)
    rng = np.random.default_rng(SEED)
    starts = rng.integers(
        0, n, size=(BOOT_DRAWS, int(np.ceil(n / BOOT_BLOCK)))
    )
    idx = (
        starts[:, :, None] + np.arange(BOOT_BLOCK)[None, None, :]
    ) % n
    idx = idx.reshape(BOOT_DRAWS, -1)[:, :n]
    sampled = values[idx]
    nav = np.cumprod(1.0 + sampled, axis=1)
    cagr = nav[:, -1, :] ** (250.0 / n) - 1.0
    sd = sampled.std(axis=1, ddof=1) * np.sqrt(250.0)
    sharpe = np.divide(
        cagr,
        sd,
        out=np.full_like(cagr, np.nan),
        where=sd > 0,
    )
    delta = (sharpe[:, 0] - sharpe[:, 1])
    delta = delta[np.isfinite(delta)]
    point = performance(candidate)["sharpe"] - performance(control)["sharpe"]
    return {
        "sharpe_delta": float(point),
        "sharpe_ci025": float(np.nanquantile(delta, 0.025)),
        "sharpe_ci975": float(np.nanquantile(delta, 0.975)),
        "sharpe_p_two_sided": float(
            min(
                1.0,
                2.0
                * min(
                    np.nanmean(delta <= 0.0),
                    np.nanmean(delta >= 0.0),
                ),
            )
        ),
    }


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--skip-build", action="store_true")
    args = parser.parse_args()
    OUT.mkdir(parents=True, exist_ok=True)
    ART.mkdir(parents=True, exist_ok=True)
    LOGS.mkdir(parents=True, exist_ok=True)
    v2_root = PACKAGE / "v2_runs"
    if not args.skip_build:
        build_v2_grid(v2_root)

    tech = pd.read_csv(TECH_RETURNS, parse_dates=["date"]).set_index("date")
    state = pd.read_csv(VIX_STATE, parse_dates=["date"]).set_index("date")
    state = state.reindex(tech.index)
    bond = pd.read_csv(
        BOND_RETURNS, parse_dates=["date"]
    ).set_index("date")["bond_return"].reindex(tech.index).fillna(0.0)
    multiplier = state["vix_multiplier"].astype(float).clip(0.0, 1.0)

    windows = {
        "FULL": (START, END),
        "2019_2023": (START, pd.Timestamp("2023-12-31")),
        "2024_2026": (pd.Timestamp("2024-01-01"), END),
        "2026": (pd.Timestamp("2026-01-01"), END),
    }
    rows = []
    daily = {}
    holdings_summary = []
    for rv_k in RV_GRID:
        for dc_k in DC_GRID:
            path = v2_root / f"rv{rv_k}_dc{dc_k}"
            v2 = pd.read_csv(
                path / "nav_nofb.csv", parse_dates=["date"]
            ).set_index("date")
            v2_return = v2["nav"].pct_change(fill_method=None).rename("V2")
            er = effective_rank_path(tech["W_BASE"], v2_return)
            candidate = vix_overlay(
                er, multiplier, bond, OVERLAY_COST
            ).rename("ER_GLOBAL_VIX")
            stress = vix_overlay(
                er, multiplier, bond, OVERLAY_STRESS
            ).rename("ER_GLOBAL_VIX_10BP")
            common = candidate.index.intersection(tech.index)
            candidate = candidate.reindex(common)
            stress = stress.reindex(common)
            er = er.reindex(common)
            v2_return = v2_return.reindex(common)
            daily[(rv_k, dc_k)] = candidate
            for arm, series in (
                ("V2_BASE", v2_return),
                ("ER_BASE", er),
                ("ER_GLOBAL_VIX", candidate),
                ("ER_GLOBAL_VIX_10BP", stress),
            ):
                for label, (start, end) in windows.items():
                    rows.append(
                        {
                            "rv_k": rv_k,
                            "dc_k": dc_k,
                            "arm": arm,
                            "window": label,
                            **performance(series.loc[start:end]),
                        }
                    )
            holdings = pd.read_csv(path / "holdings_nofb.csv")
            etf_count = (
                holdings["etfs"].astype(str).str.extractall(r"([0-9]{6})")[0]
                .groupby(level=0)
                .nunique()
            )
            holdings_summary.append(
                {
                    "rv_k": rv_k,
                    "dc_k": dc_k,
                    "mean_holding_industries": float(
                        holdings["selected"].astype(str)
                        .str.count(",")
                        .add(1)
                        .mean()
                    ),
                    "mean_unique_etfs": float(etf_count.mean()),
                    "max_unique_etfs": int(etf_count.max()),
                }
            )

    metrics = pd.DataFrame(rows)
    metrics.to_csv(OUT / "grid_metrics.csv", index=False)
    pd.DataFrame(
        [
            {
                "rv_k": rv,
                "dc_k": dc,
                "date": date,
                "return": float(value),
            }
            for (rv, dc), series in daily.items()
            for date, value in series.to_dict().items()
        ]
    ).to_csv(OUT / "grid_daily_returns.csv", index=False)
    holding_summary = pd.DataFrame(holdings_summary)
    holding_summary.to_csv(OUT / "holding_concentration.csv", index=False)

    full = metrics[
        metrics["window"].eq("FULL")
        & metrics["arm"].eq("ER_GLOBAL_VIX")
    ].set_index(["rv_k", "dc_k"])
    early = metrics[
        metrics["window"].eq("2019_2023")
        & metrics["arm"].eq("ER_GLOBAL_VIX")
    ].set_index(["rv_k", "dc_k"])
    late = metrics[
        metrics["window"].eq("2024_2026")
        & metrics["arm"].eq("ER_GLOBAL_VIX")
    ].set_index(["rv_k", "dc_k"])

    baseline = (3, 5)
    best_key = full["sharpe"].idxmax()
    best_series = daily[best_key]
    baseline_series = daily[baseline]
    bootstrap = paired_bootstrap(best_series, baseline_series)
    pseudo_early_best = early["sharpe"].idxmax()
    pseudo_test = pd.DataFrame(
        [
            {
                "selected_on_2019_2023": pseudo_early_best,
                **performance(
                    daily[pseudo_early_best].loc["2024-01-01":END]
                ),
                "baseline_2024_2026": performance(
                    daily[baseline].loc["2024-01-01":END]
                ),
            }
        ]
    )
    pseudo_test.to_csv(OUT / "pseudo_oos.csv", index=False)

    sharpe_matrix = full["sharpe"].unstack("dc_k")
    mdd_matrix = full["mdd"].unstack("dc_k")
    fig, axes = plt.subplots(1, 2, figsize=(14, 5))
    for ax, matrix, title, cmap in (
        (axes[0], sharpe_matrix, "ER_GLOBAL_VIX Sharpe", "viridis"),
        (axes[1], mdd_matrix, "ER_GLOBAL_VIX Max Drawdown", "RdYlGn"),
    ):
        image = ax.imshow(matrix.to_numpy(float), cmap=cmap, aspect="auto")
        ax.set_xticks(range(len(matrix.columns)), [str(x) for x in matrix.columns])
        ax.set_yticks(range(len(matrix.index)), [str(x) for x in matrix.index])
        ax.set_xlabel("Delta-C K")
        ax.set_ylabel("RV K")
        ax.set_title(title)
        for i in range(matrix.shape[0]):
            for j in range(matrix.shape[1]):
                ax.text(
                    j,
                    i,
                    f"{matrix.iloc[i, j]:.3f}",
                    ha="center",
                    va="center",
                    fontsize=8,
                )
        fig.colorbar(image, ax=ax)
    fig.tight_layout()
    fig.savefig(ART / "k_grid_heatmap.png", dpi=180)
    plt.close(fig)

    summary = {
        "strategy": "ER-GLOBAL-VIX-252D80-HALF@20261123",
        "grid": {"rv_k": list(RV_GRID), "dc_k": list(DC_GRID)},
        "sample": [str(START.date()), str(END.date())],
        "baseline": {"rv_k": 3, "dc_k": 5},
        "best_full_sharpe": {
            "rv_k": int(best_key[0]),
            "dc_k": int(best_key[1]),
            **full.loc[best_key].to_dict(),
        },
        "best_full_vs_baseline_bootstrap": bootstrap,
        "pseudo_oos_selected_on_2019_2023": {
            "rv_k": int(pseudo_early_best[0]),
            "dc_k": int(pseudo_early_best[1]),
            "result": json.loads(pseudo_test.to_json(orient="records"))[0],
        },
        "production_change": False,
        "future_profitability": "NOT_ASSESSED",
    }
    (OUT / "summary.json").write_text(
        json.dumps(summary, ensure_ascii=False, indent=2, allow_nan=False) + "\n",
        encoding="utf-8",
    )
    print(full.sort_values("sharpe", ascending=False).to_string())
    print("\nBest vs baseline")
    print(json.dumps(summary, ensure_ascii=False, indent=2, allow_nan=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
