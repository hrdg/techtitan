# ER-GLOBAL-VIX-252D80-HALF@20261123

Research shadow combining:

```text
EFFECTIVE_RANK_HIGH_W@R20261116
  + W13612-GLOBAL-VIX@20261116
```

The effective-rank selector chooses `W_BASE` or `V2_BASE` at month-end.
When the lagged trailing 252-day VIX percentile is at least 80%, the selected
technology sleeve is halved and the residual moves to the bond sleeve.

## Formula

```text
r_candidate,t =
    f_t * r_ER_BASE,t
  + (1-f_t) * r_bond,t
  - 0.0005 * abs(f_t - f_t-1)

f_t = 0.5 if VIX252Percentile_t >= 0.8 else 1.0
```

The bond residual is `511260` before `511090` has a usable history, then
`511090`, matching the parent W accounting.

## Results

Sample: `2019-08-01..2026-11-16`, 5bp.

| Strategy | CAGR | Sharpe | Max drawdown | Calmar |
|---|---:|---:|---:|---:|
| W_BASE | 63.39% | 2.227 | -29.05% | 2.182 |
| W + global VIX | 66.67% | 2.505 | -20.42% | 3.265 |
| ER_BASE | 65.40% | 2.281 | -26.15% | 2.501 |
| **ER_GLOBAL_VIX** | **68.42%** | **2.566** | **-20.42%** | **3.351** |
| ER_GLOBAL_VIX, 10bp overlay stress | 67.85% | 2.544 | -20.42% | 3.323 |
| ER_RISK_VIX | 67.41% | 2.405 | -23.26% | 2.898 |

The point estimate improves Sharpe and Calmar versus ER_BASE, but does not
robustly beat `W + global VIX`. The ER-relative Sharpe difference is +0.284
with a 63-day block-bootstrap 95% interval of `[+0.020,+0.569]`; after
predeclared multiplicity adjustment the q-value is `0.1008`.

## Mechanism

There were 317 VIX-alert days, 17.94% of the sample. On alert days:

- when effective rank selected W, candidate minus ER_BASE was about
  **+0.105%/day**;
- when effective rank selected V2, it was about **-0.041%/day**.

The overlay mainly repaired W-branch stress, including ER_BASE's
2025-03-06–2025-06-20 drawdown. It gave some performance back during
the 2026 rebound.

## Status

```text
POINT_ESTIMATE_IMPROVEMENT
STATISTICAL_CONFIRMATION: INCONCLUSIVE
PRODUCTION_CHANGE: NO
INDEPENDENT_OOS: NOT_AVAILABLE
```

## Reproduction

From the repository root:

```bash
python research/effective_rank_global_vix_20261123/run.py
```

Dependencies: Python, pandas, NumPy and Matplotlib.

Inputs are frozen CSV snapshots under `inputs/`. Outputs are written to
`outputs/`; the NAV/drawdown chart is `artifacts/nav_drawdown.png`.

See `REPORT.md` for the full research note and `strategy.json` for the frozen
specification.
