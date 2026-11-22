"""Replay the published W13612/global-VIX common-axis comparison."""
from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path

import numpy as np
import pandas as pd


ROOT = Path(__file__).resolve().parents[1]
PERIODS = 250
START = pd.Timestamp("2019-08-01")
END = pd.Timestamp("2026-11-16")
BOOTSTRAP_BLOCK = 21
BOOTSTRAP_DRAWS = 4000
BOOTSTRAP_SEED = 20261122


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1 << 20), b""):
            digest.update(chunk)
    return digest.hexdigest()


def performance(values: pd.Series) -> dict[str, float | int | str]:
    clean = values.dropna().astype(float)
    nav = (1.0 + clean).cumprod()
    years = len(clean) / PERIODS
    cagr = float(nav.iloc[-1] ** (1.0 / years) - 1.0)
    vol = float(clean.std(ddof=1) * np.sqrt(PERIODS))
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
        "n_days": int(len(clean)),
    }


def bootstrap_delta(
    candidate: pd.Series,
    baseline: pd.Series,
) -> dict[str, float]:
    frame = pd.concat(
        [candidate.rename("candidate"), baseline.rename("baseline")], axis=1
    ).dropna()
    difference = frame["candidate"] - frame["baseline"]
    n_days = len(frame)
    rng = np.random.default_rng(BOOTSTRAP_SEED)
    starts = rng.integers(
        0,
        n_days,
        size=(BOOTSTRAP_DRAWS, int(np.ceil(n_days / BOOTSTRAP_BLOCK))),
    )
    index = (
        starts[:, :, None]
        + np.arange(BOOTSTRAP_BLOCK)[None, None, :]
    ) % n_days
    index = index.reshape(BOOTSTRAP_DRAWS, -1)[:, :n_days]
    candidate_draws = frame["candidate"].to_numpy(float)[index]
    baseline_draws = frame["baseline"].to_numpy(float)[index]
    delta_sharpe = np.sqrt(PERIODS) * (
        candidate_draws.mean(axis=1) / candidate_draws.std(axis=1, ddof=1)
        - baseline_draws.mean(axis=1) / baseline_draws.std(axis=1, ddof=1)
    )
    low, high = np.quantile(delta_sharpe, [0.025, 0.975])
    return {
        "delta_ann": float(difference.mean() * PERIODS),
        "ci_low": float(low),
        "ci_high": float(high),
        "p_two_sided": float(
            min(1.0, 2.0 * min((delta_sharpe <= 0).mean(), (delta_sharpe >= 0).mean()))
        ),
    }


def validate_mapping(state: pd.DataFrame) -> float:
    expected = np.where(
        state["vix_pct_252"].shift(1).ge(0.80),
        0.5,
        1.0,
    )
    mapping_diff = float(
        np.abs(expected - state["vix_multiplier"].to_numpy(float)).max()
    )
    exposure_diff = float(
        (
            state["w_base_exposure"] * state["vix_multiplier"]
            - state["w_global_exposure"]
        )
        .abs()
        .max()
    )
    if mapping_diff > 1e-12 or exposure_diff > 1e-12:
        raise AssertionError(
            f"state mapping mismatch: multiplier={mapping_diff}, "
            f"exposure={exposure_diff}"
        )
    return max(mapping_diff, exposure_diff)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--output-dir",
        type=Path,
        default=ROOT / "outputs" / "replayed",
    )
    args = parser.parse_args()
    args.output_dir.mkdir(parents=True, exist_ok=True)

    returns = pd.read_csv(
        ROOT / "data/daily_returns_common_axis_20261116.csv",
        parse_dates=["date"],
    ).set_index("date")
    state = pd.read_csv(
        ROOT / "data/vix_state.csv",
        parse_dates=["date"],
    ).set_index("date")
    if returns.index.min() != START or returns.index.max() != END:
        raise AssertionError("unexpected common-axis endpoints")
    if not returns.index.equals(state.index):
        raise AssertionError("returns and VIX state date axes differ")
    state_diff = validate_mapping(state)

    metrics = pd.DataFrame(
        [
            {"arm": arm, **performance(returns[arm])}
            for arm in returns.columns
        ]
    )
    metrics.to_csv(args.output_dir / "metrics.csv", index=False)
    bootstrap = pd.DataFrame(
        [
            {
                "candidate": "W_GLOBAL_VIX",
                "baseline": baseline,
                **bootstrap_delta(returns["W_GLOBAL_VIX"], returns[baseline]),
            }
            for baseline in ("W_BASE", "W_MATCHED")
            if baseline in returns.columns
        ]
    )
    bootstrap.to_csv(args.output_dir / "bootstrap.csv", index=False)
    summary = {
        "start": str(returns.index.min().date()),
        "end": str(returns.index.max().date()),
        "n_days": int(len(returns)),
        "state_mapping_max_abs_diff": state_diff,
        "inputs": {
            "daily_returns_sha256": sha256_file(
                ROOT / "data/daily_returns_common_axis_20261116.csv"
            ),
            "vix_state_sha256": sha256_file(ROOT / "data/vix_state.csv"),
        },
        "metrics": metrics.to_dict(orient="records"),
        "bootstrap": bootstrap.to_dict(orient="records"),
    }
    (args.output_dir / "replay_summary.json").write_text(
        json.dumps(summary, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    print(json.dumps(summary, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
