"""Ablate MOM20 as vote, multiplier, or both."""
from __future__ import annotations

import hashlib
import importlib.util
import json
import math
import sys
from pathlib import Path

import matplotlib
import numpy as np
import pandas as pd

matplotlib.use("Agg")
import matplotlib.pyplot as plt

ROOT = Path(__file__).resolve().parents[3]
RUN = Path(__file__).resolve().parent
ART = RUN / "artifacts"
DEADBAND_RUN = ROOT / "research/runs/w13612_deadband_bond30_20261113"
VOTE_RUN = ROOT / "research/runs/mom20_10_vote2_20261113"
VOTE_DIAGNOSTICS = VOTE_RUN / "artifacts/vote_diagnostics.csv"
VOTE_EXPOSURES = VOTE_RUN / "artifacts/exposures.csv"
VOTE_METRICS = VOTE_RUN / "artifacts/metrics.csv"
COST = 0.0005
COSTS = (0.0, COST, 0.001)
PERIODS = 250
BLOCK = 21
PATHS = 5_000
SEEDS = (20261114, 20261120)


def load_module(name: str, path: Path):
    spec = importlib.util.spec_from_file_location(name, path)
    module = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module


B = load_module("mom_arch_deadband_parent", DEADBAND_RUN / "run.py")


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def performance(values: pd.Series) -> dict[str, float | int]:
    point = B.point_metrics(values)
    down = float(
        np.sqrt(np.mean(np.minimum(values.to_numpy(float), 0.0) ** 2))
        * math.sqrt(PERIODS)
    )
    return {
        "cagr": float(point.cagr[0]),
        "vol": float(point.vol[0]),
        "sharpe": float(point.sharpe[0]),
        "downside_vol": down,
        "sortino": float(point.cagr[0] / down) if down > 0 else float("nan"),
        "mdd": float(point.mdd[0]),
        "calmar": float(point.calmar[0]),
        "final_nav": float((1.0 + values).prod()),
        "n_days": len(values),
    }


def block_indices(rng: np.random.Generator, n_days: int) -> np.ndarray:
    starts = rng.integers(0, n_days, size=math.ceil(n_days / BLOCK))
    return (
        (starts[:, None] + np.arange(BLOCK)[None, :]) % n_days
    ).ravel()[:n_days]


def metric_draws(samples: np.ndarray) -> dict[str, np.ndarray]:
    n_days = samples.shape[1]
    nav = np.cumprod(1.0 + samples, axis=1)
    cagr = np.power(nav[:, -1], PERIODS / n_days) - 1.0
    vol = np.std(samples, axis=1, ddof=1) * math.sqrt(PERIODS)
    down = (
        np.sqrt(np.mean(np.minimum(samples, 0.0) ** 2, axis=1))
        * math.sqrt(PERIODS)
    )
    sharpe = np.divide(cagr, vol, out=np.full_like(cagr, np.nan), where=vol > 0)
    sortino = np.divide(
        cagr,
        down,
        out=np.full_like(cagr, np.nan),
        where=down > 0,
    )
    peaks = np.maximum.accumulate(
        np.concatenate((np.ones((samples.shape[0], 1)), nav), axis=1),
        axis=1,
    )[:, 1:]
    mdd = np.min(nav / peaks - 1.0, axis=1)
    calmar = np.divide(
        cagr,
        np.abs(mdd),
        out=np.full_like(cagr, np.nan),
        where=mdd < 0,
    )
    return {
        "cagr": cagr,
        "sharpe": sharpe,
        "sortino": sortino,
        "mdd": mdd,
        "calmar": calmar,
    }


def bootstrap_draws(
    candidate: np.ndarray,
    control: np.ndarray,
    seed: int,
) -> tuple[dict[str, np.ndarray], dict[str, np.ndarray]]:
    rng = np.random.default_rng(seed)
    candidate_parts: dict[str, list[np.ndarray]] = {}
    control_parts: dict[str, list[np.ndarray]] = {}
    for _ in range(0, PATHS, 100):
        indices = np.stack(
            [block_indices(rng, len(candidate)) for _ in range(100)]
        )
        cm = metric_draws(candidate[indices])
        bm = metric_draws(control[indices])
        for key, values in cm.items():
            candidate_parts.setdefault(key, []).append(values)
        for key, values in bm.items():
            control_parts.setdefault(key, []).append(values)
    return (
        {key: np.concatenate(values) for key, values in candidate_parts.items()},
        {key: np.concatenate(values) for key, values in control_parts.items()},
    )


def summarize_delta(
    candidate: pd.Series,
    control: pd.Series,
    candidate_draws: dict[str, np.ndarray],
    control_draws: dict[str, np.ndarray],
) -> dict[str, float]:
    cp = performance(candidate)
    bp = performance(control)
    result = {}
    for metric in ("cagr", "sharpe", "sortino", "mdd", "calmar"):
        delta = candidate_draws[metric] - control_draws[metric]
        p_low = float(np.nanmean(delta <= 0.0))
        p_high = float(np.nanmean(delta >= 0.0))
        result[f"{metric}_point_delta"] = float(cp[metric] - bp[metric])
        result[f"{metric}_ci025"] = float(np.nanquantile(delta, 0.025))
        result[f"{metric}_ci975"] = float(np.nanquantile(delta, 0.975))
        result[f"{metric}_p_two_sided"] = min(1.0, 2.0 * min(p_low, p_high))
    return result


def gate(score: pd.Series, available: pd.Series, threshold: int) -> pd.Series:
    required = np.minimum(threshold, available.replace(0, 1))
    return pd.Series(
        np.where((score >= required) | available.eq(0), 1.0, 0.0),
        index=score.index,
    )


def episode(values: pd.Series) -> dict[str, str | float]:
    nav = (1.0 + values).cumprod()
    dd = nav / nav.cummax() - 1.0
    trough = dd.idxmin()
    peak = nav.loc[:trough].idxmax()
    after = nav.loc[trough:]
    recovered = after[after >= nav.at[peak]]
    recovery = recovered.index[0] if len(recovered) else pd.NaT
    return {
        "peak": str(peak.date()),
        "trough": str(trough.date()),
        "recovery": str(recovery.date()) if pd.notna(recovery) else "not_recovered",
        "mdd": float(dd.at[trough]),
        "peak_to_trough_days": int(len(nav.loc[peak:trough]) - 1),
    }


def main() -> None:
    ART.mkdir(parents=True, exist_ok=True)
    parent = B.load_parent()
    prices, _, _, _ = parent.load_prices_and_returns()
    signals = pd.read_csv(B.SIGNALS, parse_dates=["date"]).set_index("date")
    days = signals.index
    target, _ = parent.build_v2_targets(days, prices.columns)
    etf_returns = prices.pct_change(fill_method=None).reindex(days)

    benchmark = pd.read_parquet(B.BENCHMARK)
    benchmark["date"] = pd.to_datetime(benchmark["date"])
    h11006 = (
        benchmark.loc[benchmark["code"].eq("H11006")]
        .set_index("date")["close"]
        .sort_index()
        .pct_change(fill_method=None)
        .reindex(days)
    )
    bond10 = B.qfq_return(B.BOND_10Y, days)
    source30 = pd.read_csv(B.BOND_30Y_SOURCE, parse_dates=["time"])
    bond30 = (
        source30.loc[source30["code"].eq("511090.XSHG")]
        .set_index("time")["close"]
        .sort_index()
        .pct_change(fill_method=None)
        .reindex(days)
    )
    first30 = bond30.first_valid_index()
    splice30 = bond10.copy()
    splice30.loc[first30:] = bond30.loc[first30:]

    diag = pd.read_csv(
        VOTE_DIAGNOSTICS,
        parse_dates=["date"],
    ).set_index("date").reindex(days)
    exp = pd.read_csv(
        VOTE_EXPOSURES,
        parse_dates=["date"],
    ).set_index("date").reindex(days)
    mom_scale = diag["MOM_SCALE"].astype(float)
    core_votes = diag["votes"].astype(float)
    core_available = diag["available"].astype(float)
    base_mom_scale = exp["MOM_BASE"].astype(float)
    mother_exposure = (base_mom_scale / mom_scale).clip(0.0, 1.0)
    if not np.isfinite(mother_exposure).all():
        raise AssertionError("cannot recover parent exposure")

    gate2of4 = gate(core_votes, core_available, 2)
    gate3of4 = gate(core_votes, core_available, 3)
    score_half = core_votes + mom_scale
    gate3of5_half = gate(score_half, core_available + 1, 3)
    mom_binary = mom_scale.ge(1.0).astype(float)
    score_binary = core_votes + mom_binary
    gate3of5_binary = gate(score_binary, core_available + 1, 3)

    current_both = exp["VOTE2_MOM_3OF5"].astype(float)
    scales = {
        "BASE_MOM": base_mom_scale,
        "BOTH_HALF_VOTE": current_both,
        "VOTE_ONLY_HALF": (mother_exposure * gate3of5_half).clip(0.0, 1.0),
        "VOTE_ONLY_BINARY": (mother_exposure * gate3of5_binary).clip(0.0, 1.0),
        "MULT_ONLY_2OF4": (
            mother_exposure * mom_scale * gate2of4
        ).clip(0.0, 1.0),
        "MULT_ONLY_3OF4": (
            mother_exposure * mom_scale * gate3of4
        ).clip(0.0, 1.0),
        "BOTH_BINARY": (
            mother_exposure * mom_scale * gate3of5_binary
        ).clip(0.0, 1.0),
    }

    metrics_rows = []
    daily = {}
    exposures = {}
    turnover_frame = {}
    for arm, exposure in scales.items():
        risky = target.mul(exposure, axis=0)
        bond_weight = 1.0 - exposure
        turnover = (
            risky.diff().abs().sum(axis=1)
            + bond_weight.diff().abs()
        ).fillna(0.0)
        turnover.loc[first30] += 2.0 * bond_weight.loc[first30]
        gross = (
            risky
            * etf_returns.reindex(columns=risky.columns).fillna(0.0)
        ).sum(axis=1) + bond_weight * splice30.fillna(0.0)
        daily[arm] = gross - COST * turnover
        exposures[arm] = exposure
        turnover_frame[arm] = turnover
        for cost in COSTS:
            metrics_rows.append(
                {
                    "arm": arm,
                    "cost": cost,
                    **performance(gross - cost * turnover),
                    "avg_exposure": float(exposure.mean()),
                    "annual_turnover": float(turnover.mean() * PERIODS),
                }
            )

    daily_frame = pd.DataFrame(daily, index=days)
    daily_frame.index.name = "date"
    daily_frame.to_csv(ART / "daily_returns_5bp.csv")
    pd.DataFrame(exposures, index=days).to_csv(ART / "exposures.csv")
    pd.DataFrame(turnover_frame, index=days).to_csv(ART / "turnover.csv")
    metrics = pd.DataFrame(metrics_rows)
    metrics.to_csv(ART / "metrics.csv", index=False)

    state_columns = {
        "MOTHER_EXPOSURE": mother_exposure,
        "MOM_SCALE": mom_scale,
        "CORE_VOTES": core_votes,
        "CORE_AVAILABLE": core_available,
        "GATE2OF4": gate2of4,
        "GATE3OF4": gate3of4,
        "GATE3OF5_HALF": gate3of5_half,
        "GATE3OF5_BINARY": gate3of5_binary,
    }
    for arm, value in scales.items():
        state_columns[f"EXPOSURE_{arm}"] = value
    pd.DataFrame(state_columns, index=days).to_csv(ART / "architecture_diagnostics.csv")

    episodes = {
        arm: episode(values) for arm, values in daily_frame.items()
    }
    pd.DataFrame(episodes).T.to_csv(ART / "drawdown_episodes.csv")

    segment_map = {
        "full": ("2019-08-01", "2026-07-31"),
        "2019-08_to_2023-06": ("2019-08-01", "2023-06-13"),
        "2023-06_to_2026-07": ("2023-06-14", "2026-07-31"),
        "2019_2022": ("2019-08-01", "2022-12-31"),
        "2023_2024": ("2023-01-01", "2024-12-31"),
        "2025_2026": ("2025-01-01", "2026-07-31"),
        "mom_base_maxdd": ("2025-03-06", "2025-06-20"),
    }
    segment_rows = []
    for segment, (start, end) in segment_map.items():
        for arm in daily_frame.columns:
            segment_rows.append(
                {
                    "segment": segment,
                    "arm": arm,
                    **performance(daily_frame[arm].loc[start:end]),
                    "avg_exposure": float(exposures[arm].loc[start:end].mean()),
                }
            )
    pd.DataFrame(segment_rows).to_csv(ART / "segments.csv", index=False)

    yearly_rows = []
    for year, frame in daily_frame.groupby(daily_frame.index.year):
        for arm in frame.columns:
            yearly_rows.append(
                {
                    "year": int(year),
                    "arm": arm,
                    "return": float((1.0 + frame[arm]).prod() - 1.0),
                }
            )
    pd.DataFrame(yearly_rows).to_csv(ART / "yearly_returns.csv", index=False)

    baseline = daily_frame["BOTH_HALF_VOTE"]
    bootstrap_rows = []
    for arm in [name for name in daily_frame.columns if name not in ("BASE_MOM", "BOTH_HALF_VOTE")]:
        cparts: dict[str, list[np.ndarray]] = {}
        bparts: dict[str, list[np.ndarray]] = {}
        for seed in SEEDS:
            cd, bd = bootstrap_draws(
                daily_frame[arm].to_numpy(float),
                baseline.to_numpy(float),
                seed,
            )
            bootstrap_rows.append(
                {
                    "arm": arm,
                    "seed": seed,
                    "paths": PATHS,
                    **summarize_delta(daily_frame[arm], baseline, cd, bd),
                }
            )
            for key, values in cd.items():
                cparts.setdefault(key, []).append(values)
            for key, values in bd.items():
                bparts.setdefault(key, []).append(values)
        bootstrap_rows.append(
            {
                "arm": arm,
                "seed": "pooled",
                "paths": PATHS * len(SEEDS),
                **summarize_delta(
                    daily_frame[arm],
                    baseline,
                    {key: np.concatenate(values) for key, values in cparts.items()},
                    {key: np.concatenate(values) for key, values in bparts.items()},
                ),
            }
        )
    pd.DataFrame(bootstrap_rows).to_csv(ART / "bootstrap.csv", index=False)

    matched_rows = []
    for arm in daily_frame.columns:
        matched_scale = pd.Series(float(exposures[arm].mean()), index=days)
        risky = target.mul(matched_scale, axis=0)
        bond_weight = 1.0 - matched_scale
        turnover = (
            risky.diff().abs().sum(axis=1)
            + bond_weight.diff().abs()
        ).fillna(0.0)
        turnover.loc[first30] += 2.0 * bond_weight.loc[first30]
        gross = (
            risky
            * etf_returns.reindex(columns=risky.columns).fillna(0.0)
        ).sum(axis=1) + bond_weight * splice30.fillna(0.0)
        matched_return = gross - COST * turnover
        matched_rows.append(
            {
                "arm": arm,
                "avg_exposure": float(exposures[arm].mean()),
                "arm_cagr": performance(daily_frame[arm])["cagr"],
                "arm_sharpe": performance(daily_frame[arm])["sharpe"],
                "arm_mdd": performance(daily_frame[arm])["mdd"],
                "matched_cagr": performance(matched_return)["cagr"],
                "matched_sharpe": performance(matched_return)["sharpe"],
                "matched_mdd": performance(matched_return)["mdd"],
            }
        )
    pd.DataFrame(matched_rows).to_csv(ART / "exposure_matched.csv", index=False)

    stress = mom_scale.lt(1.0)
    stress_rows = []
    for arm, exposure in exposures.items():
        values = exposure[stress]
        stress_rows.append(
            {
                "arm": arm,
                "stress_days": int(stress.sum()),
                "full_share": float(values.ge(0.999).mean()),
                "half_share": float(values.between(0.001, 0.999).mean()),
                "zero_share": float(values.le(0.001).mean()),
                "average_exposure": float(values.mean()),
            }
        )
    pd.DataFrame(stress_rows).to_csv(ART / "stress_state_distribution.csv", index=False)

    nav = (1.0 + daily_frame).cumprod()
    fig, ax = plt.subplots(figsize=(12, 6.5))
    for arm in nav.columns:
        ax.plot(
            nav.index,
            nav[arm],
            linewidth=2.2 if arm in ("BASE_MOM", "BOTH_HALF_VOTE") else 1.2,
            label=arm,
        )
    ax.set_title("MOM20 architecture ablation (5bp)")
    ax.set_ylabel("NAV")
    ax.grid(alpha=0.25)
    ax.legend(fontsize=8, ncol=2)
    fig.tight_layout()
    fig.savefig(ART / "nav_architecture.png", dpi=160)
    plt.close(fig)

    current_metrics = pd.read_csv(VOTE_METRICS)
    saved_current = current_metrics[
        current_metrics["arm"].eq("VOTE2_MOM_3OF5")
        & current_metrics["cost"].eq(COST)
    ].iloc[0]
    current_repro = metrics[
        metrics["arm"].eq("BOTH_HALF_VOTE")
        & metrics["cost"].eq(COST)
    ].iloc[0]
    reproduction_error = {
        key: float(abs(float(current_repro[key]) - float(saved_current[key])))
        for key in ("cagr", "vol", "sharpe", "sortino", "mdd", "calmar", "avg_exposure")
    }

    summary = {
        "evaluation_days": len(days),
        "start": str(days.min().date()),
        "end": str(days.max().date()),
        "current_reproduction_error": reproduction_error,
        "mom_stress_days": int(stress.sum()),
        "input_hashes": {
            "vote_diagnostics": sha256(VOTE_DIAGNOSTICS),
            "vote_exposures": sha256(VOTE_EXPOSURES),
            "vote_metrics": sha256(VOTE_METRICS),
            "run.py": sha256(RUN / "run.py"),
        },
        "limitations": [
            "Historical architecture comparison, not independent OOS.",
            "Parent ETF membership and PIT remain PARTIAL.",
            "No alternative MOM thresholds or vote thresholds were searched.",
        ],
    }
    (ART / "summary.json").write_text(
        json.dumps(summary, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    print(metrics[metrics["cost"].eq(COST)].to_string(index=False))
    print("\nSTRESS DISTRIBUTION")
    print(pd.DataFrame(stress_rows).to_string(index=False))


if __name__ == "__main__":
    main()
