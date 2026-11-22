# Frozen input snapshots

This directory contains the minimum inputs required to rerun the published
effective-rank comparison without the original project checkout.

| File | SHA256 | Purpose |
|---|---|---|
| `comparison_returns.csv` | `a87eb00b45d97046bc38116d280f6c20dcc5a3be1995ce67b29e17a731595ee4` | Refreshed W, V2 and effective-rank return ledgers |
| `voteonly_diagnostics.csv` | `09cd186ca111e27825e73a19ce05fb18f9a1da727d2c3795412206eaf932429c` | W equity/bond decomposition and exposure |
| `nav_nofb_v20261116.csv` | `f245a71c056bb38786f76149fe65310db2bc5595af36bc582a2ab264fd034544` | Refreshed V2 NAV and exposure |
| `monthly_selections.csv` | `018626ac3fdf3bc5fbafb2d4eb8e7257a9f00c9d765560672162071c733dbc9d` | Frozen monthly selector schedules |

The data cutoff is 2026-11-16. The last completed month-end score is
2026-10-30. These snapshots are research artifacts and inherit the parent
project's `PARTIAL` ETF-membership and vendor-vintage limitations.
