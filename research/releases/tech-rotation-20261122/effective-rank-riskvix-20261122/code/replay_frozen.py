"""Replay the frozen effective-rank selector with the RISK_VIX branch overlay."""
from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path

import numpy as np
import pandas as pd


ROOT = Path(__file__).resolve().parents[1]
PERIODS_PER_YEAR = 250
SWITCH_COST = 0.001
START = pd.Timestamp("2019-08-01")
SELECTOR_START = pd.Period("2020-09", freq="M")
BOOTSTRAP_BLOCK = 21
BOOTSTRAP_DRAWS = 4000
BOOTSTRAP_SEED = 20261122


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def load_selections(path: Path) -> pd.DataFrame:
    frame = pd.read_csv(path, parse_dates=["decision_date"])
    required = {"month", "decision_date", "selector", "selected", "changed"}
    missing = required.difference(frame.columns)
    if missing:
        raise ValueError(f"monthly selections missing columns: {sorted(missing)}")
    frame = frame.loc[frame["selector"].eq("EFFECTIVE_RANK_HIGH_W")].copy()
    if frame.empty:
        raise ValueError("no EFFECTIVE_RANK_HIGH_W selector rows")
    frame["month"] = pd.PeriodIndex(frame["month"], freq="M")
    if not frame["selected"].isin(["W", "V2"]).all():
        raise ValueError("selected must contain only W or V2")
    if frame["month"].duplicated().any():
        raise ValueError("monthly selections contain duplicate months")
    return frame.set_index("month").sort_index()


def load_branch_returns(path: Path) -> pd.DataFrame:
    frame = pd.read_csv(path, parse_dates=["date"]).set_index("date").sort_index()
    required = {
        "W_BASE",
        "V2_BASE",
        "W_GUARDED",
        "V2_GUARDED",
        "W_MATCHED",
        "V2_MATCHED",
        "W_EXPOSURE",
        "V2_EXPOSURE",
        "GUARD",
    }
    missing = required.difference(frame.columns)
    if missing:
        raise ValueError(f"branch returns missing columns: {sorted(missing)}")
    if frame.index.duplicated().any() or not frame.index.is_monotonic_increasing:
        raise ValueError("branch dates must be unique and increasing")
    return frame.loc[START:]


def selector_switch_dates(
    dates: pd.DatetimeIndex, selections: pd.DataFrame
) -> list[pd.Timestamp]:
    """Return first trading days carrying the frozen selector switch cost.

    The first published row retains ``changed=True`` because the selector
    started before the portfolio evaluation window. Its cost must therefore be
    replayed from the frozen flag rather than inferred from a default W state.
    """
    months = pd.PeriodIndex(dates, freq="M")
    previous: str | None = None
    switches: list[pd.Timestamp] = []
    for month, row in selections.sort_index().iterrows():
        if month < SELECTOR_START:
            continue
        if month not in months:
            raise ValueError(f"selector schedule has no trading days for {month}")
        choice = str(row["selected"])
        changed = bool(row["changed"])
        if previous is not None and changed != (choice != previous):
            raise ValueError(
                f"changed flag is inconsistent with selected sleeve in {month}"
            )
        if changed:
            switches.append(dates[months == month][0])
        previous = choice
    return switches


def replay_selector(
    branches: pd.DataFrame,
    selections: pd.DataFrame,
    suffix: str,
) -> pd.Series:
    """Choose W or V2 monthly and charge 10bp on the first switched session."""
    month = pd.PeriodIndex(branches.index, freq="M")
    mapped = pd.Series(month, dtype="object").map(
        selections["selected"].to_dict()
    )
    choice = mapped.to_numpy(dtype=object)
    choice[pd.isna(choice)] = "W"
    w = branches[f"W_{suffix}"].to_numpy(float)
    v2 = branches[f"V2_{suffix}"].to_numpy(float)
    result = pd.Series(
        np.where(choice == "W", w, v2),
        index=branches.index,
        dtype=float,
    )
    for switch_date in selector_switch_dates(branches.index, selections):
        result.at[switch_date] -= SWITCH_COST
    return result


def performance(values: pd.Series) -> dict[str, float | str | int]:
    clean = values.dropna().astype(float)
    n_days = len(clean)
    if n_days == 0:
        raise ValueError("cannot compute performance on an empty series")
    nav = (1.0 + clean).cumprod()
    total_return = float(nav.iloc[-1] - 1.0)
    cagr = float((1.0 + total_return) ** (PERIODS_PER_YEAR / n_days) - 1.0)
    vol = float(clean.std(ddof=1) * np.sqrt(PERIODS_PER_YEAR))
    mdd = float((nav / nav.cummax() - 1.0).min())
    return {
        "start": str(clean.index.min().date()),
        "end": str(clean.index.max().date()),
        "cagr": cagr,
        "vol": vol,
        "sharpe": cagr / vol if vol else np.nan,
        "mdd": mdd,
        "calmar": cagr / abs(mdd) if mdd < 0 else np.nan,
        "total_return": total_return,
        "n_days": n_days,
    }


def metric_rows(frame: pd.DataFrame) -> pd.DataFrame:
    windows = (
        ("full", START, None),
        ("2019_2023", START, pd.Timestamp("2023-12-31")),
        ("2024_2026", pd.Timestamp("2024-01-01"), None),
        ("2026", pd.Timestamp("2026-01-01"), None),
    )
    rows: list[dict[str, object]] = []
    for sample, start, end in windows:
        subset = frame.loc[start:end] if end is not None else frame.loc[start:]
        for arm in frame.columns:
            rows.append(
                {
                    "sample": sample,
                    "arm": arm,
                    **performance(subset[arm]),
                }
            )
    return pd.DataFrame(rows)


def block_bootstrap_delta(
    candidate: pd.Series,
    baseline: pd.Series,
    *,
    block: int = BOOTSTRAP_BLOCK,
    draws: int = BOOTSTRAP_DRAWS,
    seed: int = BOOTSTRAP_SEED,
) -> dict[str, float]:
    frame = pd.concat(
        [candidate.rename("candidate"), baseline.rename("baseline")], axis=1
    ).dropna()
    difference = frame["candidate"] - frame["baseline"]
    n_days = len(frame)
    if n_days < block * 2:
        raise ValueError("sample is too short for the frozen bootstrap")
    rng = np.random.default_rng(seed)
    starts = rng.integers(
        0,
        n_days - block + 1,
        size=(draws, int(np.ceil(n_days / block))),
    )
    offsets = np.arange(block)
    index = (starts[:, :, None] + offsets[None, None, :]) % n_days
    index = index.reshape(draws, -1)[:, :n_days]
    candidate_draws = frame["candidate"].to_numpy(float)[index]
    baseline_draws = frame["baseline"].to_numpy(float)[index]
    candidate_mean = candidate_draws.mean(axis=1)
    candidate_std = candidate_draws.std(axis=1, ddof=1)
    baseline_mean = baseline_draws.mean(axis=1)
    baseline_std = baseline_draws.std(axis=1, ddof=1)
    sharpe_delta = np.sqrt(PERIODS_PER_YEAR) * (
        candidate_mean / candidate_std - baseline_mean / baseline_std
    )
    ci_low, ci_high = np.quantile(sharpe_delta, [0.025, 0.975])
    return {
        "delta_ann": float(difference.mean() * PERIODS_PER_YEAR),
        "ci_low": float(ci_low),
        "ci_high": float(ci_high),
        "p_two_sided": float(
            min(
                1.0,
                2.0
                * min(
                    (sharpe_delta <= 0).mean(),
                    (sharpe_delta >= 0).mean(),
                ),
            )
        ),
    }


def bootstrap_rows(frame: pd.DataFrame) -> pd.DataFrame:
    rows = []
    for baseline in ("ER_BASE_COST", "ER_MATCHED"):
        rows.append(
            {
                "candidate": "ER_RISK_VIX",
                "baseline": baseline,
                **block_bootstrap_delta(
                    frame["ER_RISK_VIX"], frame[baseline]
                ),
            }
        )
    return pd.DataFrame(rows)


def replay_cost_case(cost_bps: int) -> tuple[pd.DataFrame, pd.DataFrame]:
    branches = load_branch_returns(ROOT / "data" / f"branch_returns_{cost_bps}bp.csv")
    selections = load_selections(ROOT / "data" / "monthly_selections.csv")
    result = pd.DataFrame(
        {
            "ER_BASE_COST": replay_selector(branches, selections, "BASE"),
            "ER_RISK_VIX": replay_selector(branches, selections, "GUARDED"),
            "ER_MATCHED": replay_selector(branches, selections, "MATCHED"),
        }
    )
    return result, metric_rows(result)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--output-dir",
        type=Path,
        default=ROOT / "outputs" / "replayed",
    )
    args = parser.parse_args()
    args.output_dir.mkdir(parents=True, exist_ok=True)

    summary: dict[str, object] = {
        "status": "REPLAY_ONLY",
        "selection_cost": SWITCH_COST,
        "bootstrap": {
            "block": BOOTSTRAP_BLOCK,
            "draws": BOOTSTRAP_DRAWS,
            "seed": BOOTSTRAP_SEED,
        },
        "cases": {},
    }
    for cost_bps in (5, 10):
        daily, metrics_frame = replay_cost_case(cost_bps)
        bootstrap = bootstrap_rows(daily)
        daily.reset_index().to_csv(
            args.output_dir / f"daily_returns_{cost_bps}bp.csv",
            index=False,
            float_format="%.17g",
        )
        metrics_frame.to_csv(
            args.output_dir / f"metrics_{cost_bps}bp.csv",
            index=False,
            float_format="%.17g",
        )
        bootstrap.to_csv(
            args.output_dir / f"bootstrap_{cost_bps}bp.csv",
            index=False,
            float_format="%.17g",
        )
        published_daily = pd.read_csv(
            ROOT / "outputs" / f"daily_returns_{cost_bps}bp.csv",
            parse_dates=["date"],
        ).set_index("date")
        common_arms = daily.columns.intersection(published_daily.columns)
        max_daily_diff = float(
            (daily[common_arms] - published_daily[common_arms]).abs().max().max()
        )
        published_bootstrap = pd.read_csv(
            ROOT / "outputs" / f"bootstrap_{cost_bps}bp.csv"
        )
        numeric = ["delta_ann", "ci_low", "ci_high", "p_two_sided"]
        max_bootstrap_diff = float(
            (
                bootstrap[numeric].to_numpy(float)
                - published_bootstrap[numeric].to_numpy(float)
            )
            .__abs__()
            .max()
        )
        summary["cases"][str(cost_bps)] = {
            "max_abs_daily_return_diff": max_daily_diff,
            "max_abs_bootstrap_diff": max_bootstrap_diff,
            "daily_sha256": sha256_file(
                args.output_dir / f"daily_returns_{cost_bps}bp.csv"
            ),
            "metrics_sha256": sha256_file(
                args.output_dir / f"metrics_{cost_bps}bp.csv"
            ),
            "bootstrap_sha256": sha256_file(
                args.output_dir / f"bootstrap_{cost_bps}bp.csv"
            ),
        }
        if max_daily_diff > 1e-12 or max_bootstrap_diff > 1e-12:
            raise AssertionError(
                f"{cost_bps}bp replay mismatch: daily={max_daily_diff}, "
                f"bootstrap={max_bootstrap_diff}"
            )

    (args.output_dir / "replay_summary.json").write_text(
        json.dumps(summary, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    print(json.dumps(summary, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
