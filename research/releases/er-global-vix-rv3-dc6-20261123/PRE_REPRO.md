# Pre-reproduction gate — er_global_vix_k_grid_20261123

## 1. 基准/待复现策略 text 架构

```text
18 SW L2 industries
  -> Delta-C rolling score and RV rolling score
  -> Delta-C top K_dc intersect RV top K_rv
  -> map each selected industry to one ETF
  -> equal weight unique ETFs
  -> Delta-AR × TIP daily risk gate
V2_BASE(K_dc,K_rv)

W_BASE and V2_BASE(K_dc,K_rv)
  -> month-end 63-day effective-rank selector
  -> lagged VIX252 >=80%: sleeve ×0.5, residual bond
  -> ER_GLOBAL_VIX(K_dc,K_rv)
```

Baseline: `ER-GLOBAL-VIX-252D80-HALF@20261123`, whose V2 branch is
`V2_18K53_ETF_NORMALIZED_V20261107` with `K_rv=3`, `K_dc=5`.

All industry factors, ETF mapping, costs, ΔAR×TIP risk gate, effective-rank
selector and VIX rule remain frozen. Only `(K_rv,K_dc)` changes.

## 2. 待改进环节

```text
[CHANGE] V2 industry-selection width:
  RV Top K_rv, Delta-C Top K_dc, intersection

Unchanged:
  - industry factor formulas and rolling windows
  - ETF correlation >=0.80, top8, beta/momentum rank, 0.10 stickiness
  - unique-ETF equal weight
  - Delta-AR 1.5/0 hysteresis × TIP 13612 calendar gate
  - effective-rank monthly W/V2 selector
  - global VIX 252-day 80% half-exposure overlay
```

Widening the intersection changes portfolio concentration. More ETFs may
reduce single-theme risk, but if the additional names have weaker factor
scores, expected returns and turnover can deteriorate.

## 3. 公式

| ID | 公式 | 窗口/时点 |
|---|---|---|
| F1 | `S_t = TopK_dc(DeltaC_t) ∩ TopK_rv(RV_t)` | month-end |
| F2 | `V2(K_dc,K_rv)` uses frozen ETF mapping and ΔAR×TIP | next-session |
| F3 | `select_t = W if rank252(ER_t)>0.5 else V2` | month-end |
| F4 | `f_t=.5 if rank252(VIX_t)>=.8 else 1` | inherited double lag |
| F5 | `r=f*r_select+(1-f)*r_bond-5bp*|Δf|` | daily |

Grid:

```text
K_rv ∈ {1,2,3,4,5}
K_dc ∈ {3,4,5,6,7}
```

Total 25 configurations, including the baseline `(3,5)`.

## 4. 直觉逻辑

Wider `K_rv` admits more moderately valued industries; wider `K_dc` admits
more moderately concentrated industries. The intersection can expand enough
to diversify idiosyncratic ETF risk, but it can also dilute the original
top-tail signal. The useful configuration should show a smooth parameter
neighborhood, not one isolated winner.

## 5. 竞争解释与反证

| 竞争解释 | 可区分现象 | 反证条件 |
|---|---|---|
| Wider K only increases market beta | compare Sharpe, MDD and effective broad-market beta | no risk-adjusted improvement |
| Improvement only from one period | inspect 2019–2023, 2024–2026 and 2026 | sign unstable |
| Improvement is parameter mining | check adjacent K cells | isolated spike/no plateau |
| More ETFs only add turnover | compare ETF count, turnover and 10bp stress | gains vanish after costs |
| Effective-rank selector masks V2 quality | compare V2-only and ER_GLOBAL for each K | no monotone inheritance |

## 6. 有界实验与验收

- Use the frozen common return/ETF/VIX panels through `2026-11-16`.
- Run all 25 cells; do not silently omit failures.
- Report full-period and each 2019–2023/2024–2026/2026 segment.
- Report ETF count, risk exposure and annual turnover.
- Apply 5bp base cost and 10bp overlay stress for the top plateau.
- Bootstrap the best full-sample candidate versus the `(3,5)` baseline.
- Treat the grid as post-hoc exploration; no independent OOS claim.
- A parameter is not promoted if gains are isolated, sign-flip across periods,
  or fail after 10bp stress.
