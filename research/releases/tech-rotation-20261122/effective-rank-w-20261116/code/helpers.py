"""Paired performance and block-bootstrap helpers for the rebase snapshot."""
from __future__ import annotations

import math

import numpy as np
import pandas as pd

PERIODS = 250
BOOT_DRAWS = 5000
BOOT_BLOCK = 63


def performance(values: pd.Series) -> dict[str, float | int | str]:
    clean = values.astype(float).dropna()
    nav = (1.0 + clean).cumprod()
    years = len(clean) / PERIODS
    cagr = float(nav.iloc[-1] ** (1.0 / years) - 1.0)
    vol = float(clean.std(ddof=1) * math.sqrt(PERIODS))
    downside = float(
        np.sqrt(np.mean(np.minimum(clean.to_numpy(float), 0.0) ** 2))
        * math.sqrt(PERIODS)
    )
    mdd = float((nav / nav.cummax() - 1.0).min())
    return {
        "start": str(clean.index.min().date()),
        "end": str(clean.index.max().date()),
        "cagr": cagr,
        "vol": vol,
        "sharpe": cagr / vol if vol > 0 else float("nan"),
        "sortino": cagr / downside if downside > 0 else float("nan"),
        "mdd": mdd,
        "calmar": cagr / abs(mdd) if mdd < 0 else float("nan"),
        "final_nav": float(nav.iloc[-1]),
        "n_days": len(clean),
    }


def metric_draws(samples: np.ndarray) -> dict[str, np.ndarray]:
    n_days = samples.shape[1]
    nav = np.cumprod(1.0 + samples, axis=1)
    cagr = nav[:, -1] ** (PERIODS / n_days) - 1.0
    vol = np.std(samples, axis=1, ddof=1) * math.sqrt(PERIODS)
    downside = (
        np.sqrt(np.mean(np.minimum(samples, 0.0) ** 2, axis=1))
        * math.sqrt(PERIODS)
    )
    sharpe = np.divide(
        cagr,
        vol,
        out=np.full_like(cagr, np.nan),
        where=vol > 0,
    )
    sortino = np.divide(
        cagr,
        downside,
        out=np.full_like(cagr, np.nan),
        where=downside > 0,
    )
    peaks = np.maximum.accumulate(
        np.concatenate((np.ones((samples.shape[0], 1)), nav), axis=1),
        axis=1,
    )[:, 1:]
    mdd = np.min(nav / peaks - 1.0, axis=1)
    return {"cagr": cagr, "sharpe": sharpe, "sortino": sortino, "mdd": mdd}


def paired_bootstrap(
    candidate: pd.Series,
    baseline: pd.Series,
    seed: int,
) -> dict[str, float]:
    frame = pd.concat(
        [candidate.rename("candidate"), baseline.rename("baseline")],
        axis=1,
        join="inner",
    ).dropna()
    values = frame.to_numpy(float)
    n = len(frame)
    rng = np.random.default_rng(seed)
    candidate_parts: dict[str, list[np.ndarray]] = {}
    baseline_parts: dict[str, list[np.ndarray]] = {}
    made = 0
    while made < BOOT_DRAWS:
        batch = min(100, BOOT_DRAWS - made)
        starts = rng.integers(
            0, n, size=(batch, math.ceil(n / BOOT_BLOCK))
        )
        offsets = np.arange(BOOT_BLOCK)
        indices = (
            (starts[:, :, None] + offsets[None, None, :]) % n
        ).reshape(batch, -1)[:, :n]
        cand = metric_draws(values[indices, 0])
        base = metric_draws(values[indices, 1])
        for key, draws in cand.items():
            candidate_parts.setdefault(key, []).append(draws)
        for key, draws in base.items():
            baseline_parts.setdefault(key, []).append(draws)
        made += batch
    candidate_point = performance(candidate)
    baseline_point = performance(baseline)
    result: dict[str, float | int] = {
        "seed": seed,
        "paths": BOOT_DRAWS,
        "days": n,
    }
    for key in ("cagr", "sharpe", "sortino", "mdd"):
        delta = (
            np.concatenate(candidate_parts[key])
            - np.concatenate(baseline_parts[key])
        )
        result[f"{key}_point_delta"] = float(
            candidate_point[key] - baseline_point[key]
        )
        result[f"{key}_ci025"] = float(np.nanquantile(delta, 0.025))
        result[f"{key}_ci975"] = float(np.nanquantile(delta, 0.975))
        p_low = float(np.nanmean(delta <= 0.0))
        p_high = float(np.nanmean(delta >= 0.0))
        result[f"{key}_p_two_sided"] = min(1.0, 2.0 * min(p_low, p_high))
    return result
