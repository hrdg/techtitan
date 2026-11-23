# ER-GLOBAL-VIX-RV3-DC6@20261123

Prospective research-shadow label:

```text
ER-GLOBAL-VIX-RV3-DC6@20261123
```

Status:

```text
PROSPECTIVE_SHADOW_CANDIDATE
PRODUCTION_CHANGE: NO
INDEPENDENT_OOS: NOT_AVAILABLE
```

This is the `RV Top3 ∩ ΔC Top6` configuration of the effective-rank W/V2
technology sleeve with the frozen global-VIX half-exposure overlay.

## Definition

```text
V2_BASE_RV3_DC6
  = 18 SW L2 industries
  -> RV top3 intersect Delta-C top6
  -> frozen ETF mapping
  -> discrete-ETF equal weight
  -> Delta-AR 1.5/0 hysteresis × TIP 21/63/126/252

ER-GLOBAL-VIX-RV3-DC6
  = month-end effective-rank choice between W_BASE and V2_BASE_RV3_DC6
  -> multiplier 0.5 when lagged VIX252 percentile >= 80%
  -> residual bond return
```

The W branch, ETF mapping, effective-rank selector and VIX rule are unchanged.
Only the V2 cross-sectional width changes from `RV3 / ΔC5` to
`RV3 / ΔC6`.

## Performance

Sample: `2019-08-01..2026-11-16`, 5bp.

| Strategy | CAGR | Sharpe | Max drawdown | Calmar |
|---|---:|---:|---:|---:|
| Baseline ER_GLOBAL_VIX, RV3/ΔC5 | 68.51% | 2.568 | -20.42% | 3.355 |
| **RV3/ΔC6 shadow** | **70.23%** | **2.625** | **-20.42%** | **3.439** |
| RV3/ΔC6, 10bp overlay stress | 69.65% | 2.604 | -20.42% | 3.411 |

The best full-sample configuration and `RV3/ΔC7` have identical returns.
The improvement over the baseline is small:

- CAGR `+1.72pp`
- Sharpe `+0.057`
- MDD unchanged
- Calmar `+0.084`
- 63-day block bootstrap Sharpe difference: `+0.057`,
  95% interval `[-0.092,+0.235]`

The sign is not statistically confirmed.

## Stability

| Configuration | 2019–2023 Sharpe | 2024–2026 Sharpe | 2026 Sharpe |
|---|---:|---:|---:|
| RV3 / ΔC5 baseline | 2.251 | 3.071 | 4.420 |
| RV3 / ΔC6 shadow | 2.248 | 3.228 | 4.688 |
| RV4 / ΔC3 | 2.302 | 2.998 | 4.109 |

The gain comes mostly from May–June 2025 and May 2026. In 2019–2023 the
candidate is effectively flat to slightly worse than the baseline.

There is a broad parameter neighborhood around RV3–RV4, ΔC3–ΔC7 rather than a
single isolated spike. The current point estimate nevertheless remains an
in-sample parameter choice and cannot be treated as confirmed OOS alpha.

## Why it may help

The original `RV3 / ΔC5` portfolio averaged 1.84 industries and 1.32 unique
ETFs. `RV3 / ΔC6` averaged 1.95 industries and 1.41 unique ETFs. The wider
intersection occasionally avoided a concentrated weaker ETF, but did not
change the VIX-controlled maximum drawdown.

## Files

| Path | Content |
|---|---|
| `ALGORITHM.md` | Text architecture, formulas and timing |
| `strategy.json` | Frozen machine-readable candidate |
| `REPORT.md` | Full 25-cell parameter analysis |
| `code/run_grid.py` | Rebuilds the 25-cell grid and candidate outputs |
| `inputs/` | Frozen W/ER/VIX/bond/selector snapshots |
| `outputs/grid_metrics.csv` | All 25 configurations |
| `outputs/candidate_metrics.csv` | Candidate by window |
| `outputs/candidate_rv3_dc6_daily_returns.csv` | Candidate daily net returns |
| `outputs/baseline_rv3_dc5_daily_returns.csv` | Baseline daily net returns |
| `artifacts/k_grid_heatmap.png` | Sharpe/drawdown parameter heatmap |
| `artifacts/nav_baseline_vs_candidate.png` | Candidate versus baseline NAV |

## Reproduction

```bash
python research/releases/er-global-vix-rv3-dc6-20261123/code/run_grid.py
```

The reconstruction requires the techtitan repository plus the local external
ETF/momentum data dependency declared by
`scripts/v2_etf_normalized_backtest.py`.

## Decision

Keep the existing production-level research baseline at `RV3 / ΔC5`.
Monitor `RV3 / ΔC6` prospectively as a research shadow. Do not re-optimize K
on the same history or claim validation from this parameter search.
