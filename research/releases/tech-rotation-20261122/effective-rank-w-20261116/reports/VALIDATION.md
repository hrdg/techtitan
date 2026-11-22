# Validation

## Reproduction

Command:

```bash
python code/rebase_from_frozen_inputs.py
```

The standalone runner uses only the snapshots in `data/`.

| Check | Status | Evidence |
|---|---|---|
| Effective-rank path reproduction | PASS | Recomputed path differs from the refreshed ledger by at most `7.47e-17` |
| Metrics determinism | PASS | `metrics_rebased.csv` hash `5fa7f3a99797...` reproduced |
| Bootstrap determinism | PASS | `bootstrap_rebased.csv` hash `52ac5df4783a...` reproduced |
| Common W/V2 date axis | PASS | All candidate frames intersected and checked for missing values |
| Point-in-time selector | PASS | Frozen prior-month schedule reused |
| ETF membership history | PARTIAL | Inherited from the original V2 research snapshot |
| Vendor vintage | BLOCKED | No full vendor revision history |
| Independent OOS | BLOCKED | All history has been inspected |
| Future profitability | NOT_ASSESSED | Backtest does not establish future returns |

## Files

- `../outputs/metrics_rebased.csv`
- `../outputs/bootstrap_rebased.csv`
- `../outputs/summary.json`
- `../logs/run.log`
