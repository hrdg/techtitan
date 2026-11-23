# ER_GLOBAL_VIX RV / ΔC Top-K 参数网格

## 结论

在 `RV K=1..5`、`ΔC K=3..7` 的 25 组参数中：

- 全期最佳是 `RV Top3 ∩ ΔC Top6`，`ΔC Top7` 与其表现相同；
- 最佳相对原基线 `(RV3, ΔC5)` 有轻微点估计改善：
  CAGR `68.51% -> 70.23%`，Sharpe `2.568 -> 2.625`，
  MDD 同为 `-20.42%`，Calmar `3.355 -> 3.439`；
- 最佳点 Sharpe 增量仅 `+0.057`，63日块 bootstrap 95%区间
  `[-0.092,+0.235]`，不能确认改进；
- 2019–2023 最佳组 Sharpe `2.248`，略低于基线 `2.251`；
  改善几乎全部来自 2024–2026 和 2026；
- 这是已查看历史上的25格参数搜索，不是独立 OOS，不晋升。

## 口径

```text
V2_BASE(K_rv,K_dc)
  = 18 SW2 industries
  -> Delta-C Top K_dc intersect RV Top K_rv
  -> frozen ETF mapping / equal weight / Delta-AR×TIP

ER_GLOBAL_VIX(K_rv,K_dc)
  = month-end effective-rank W/V2 selection
  + lagged VIX252 >=80% half exposure
```

固定：ETF相关性筛选、beta/动量排名、0.10粘性、5bp基础成本、10bp overlay
压力成本、有效秩和VIX参数。

样本：`2019-08-01..2026-11-16`。

## 全期排名

| RV K | ΔC K | CAGR | Sharpe | MDD | Calmar |
|---:|---:|---:|---:|---:|---:|
| 3 | **6** | **70.23%** | **2.625** | -20.42% | **3.439** |
| 3 | **7** | **70.23%** | **2.625** | -20.42% | **3.439** |
| 3 | 4 | 69.44% | 2.600 | -20.42% | 3.401 |
| 3 | 3 | 69.44% | 2.600 | -20.42% | 3.401 |
| 4 | 3 | 69.26% | 2.571 | -20.42% | 3.392 |
| **3** | **5（原基线）** | **68.51%** | **2.568** | **-20.42%** | **3.355** |
| 4 | 7 | 68.29% | 2.564 | -20.42% | 3.344 |
| 4 | 4 | 68.45% | 2.563 | -20.42% | 3.352 |
| 4 | 6 | 68.26% | 2.562 | -20.42% | 3.343 |
| 4 | 5 | 67.35% | 2.525 | -20.42% | 3.298 |

完整25组见 `outputs/grid_metrics.csv`。

## 分段稳定性

| 配置 | 2019–2023 Sharpe | 2024–2026 Sharpe | 2026 Sharpe |
|---|---:|---:|---:|
| RV3 / ΔC5 | 2.251 | 3.071 | 4.420 |
| RV3 / ΔC6 | 2.248 | **3.228** | **4.688** |
| RV4 / ΔC3 | **2.302** | 2.998 | 4.109 |

最佳全期点没有改善早期，增量来自 2025–2026。若只在2019–2023选择，
胜出的是 `(RV3, ΔC4)`，但其2024–2026表现与基线完全相同。

## 经济解释

放宽 `ΔC` 到6/7使 V2 平均持有行业从 `1.84` 增至 `1.95–2.06`，
平均唯一ETF从 `1.32` 增至 `1.41–1.49`。好处主要发生在 V2 被有效秩选中的：

- 2025-05 至 2025-06；
- 2026-05。

在这些月份，更宽的 ΔC 交集让 V2 从 IT服务/较弱ETF切换到其他电子、
电子化学品及对应ETF，减少单一行业暴露。但这不是连续、跨所有时期的稳定
alpha。

## 成本压力

最佳 `(RV3, ΔC6)` 在10bp overlay成本下：

- CAGR `69.65%`
- Sharpe `2.604`
- MDD `-20.42%`
- Calmar `3.411`

成本后仍略好于基线，但统计区间仍跨零。

## 裁决

```text
POINT_ESTIMATE: MILD_IMPROVEMENT
BEST_PARAMETER: RV3 / DeltaC6-or-7
STATISTICAL_CONFIRMATION: NOT_CONFIRMED
PSEUDO_OOS: NO_INCREMENT
PRODUCTION_CHANGE: NO
```

不将原 `(3,5)` 改为 `(3,6)`。可以保留 `(3,6)` 作为前瞻影子，但必须先冻结
参数再积累未来记录；不能把本次已查看历史的最优点当成 OOS 结论。

## 文件

- `outputs/grid_metrics.csv`
- `outputs/grid_daily_returns.csv`
- `outputs/holding_concentration.csv`
- `outputs/pseudo_oos.csv`
- `outputs/summary.json`
- `artifacts/k_grid_heatmap.png`
