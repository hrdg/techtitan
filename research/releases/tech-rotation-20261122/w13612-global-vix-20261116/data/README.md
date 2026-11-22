# Frozen data

| File | Purpose |
|---|---|
| `daily_returns_common_axis_20261116.csv` | W base, W+global VIX, ER base and ER_RISK_VIX on one axis |
| `vix_state.csv` | Lagged VIX, 252-day percentile, multiplier and W exposures |
| `forward_shadow.csv` | Current shadow signal; evaluation blocked until W source is wired |

`daily_returns_common_axis_20261116.csv` starts 2019-08-01 and ends
2026-11-16. It is a frozen research ledger, not a production trading record.

The 2026-07-31-to-2026-11-16 W segment comes from the refreshed research
rebuild. The production refresh remains `BLOCKED_W_SOURCE_NOT_WIRED`.

The exact data parent for every comparison is
`W13612-A015-MOMBIN-3OF5-VOTEONLY-ETF-BC50-BOND30-R20261116`. The frozen
architecture parent `...-v1` must not be treated as the same return snapshot.
