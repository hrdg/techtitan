# W13612 + 全球VIX日频状态

## 结论

策略架构底座是当前W科技腿：

```text
W13612-A015-MOMBIN-3OF5-VOTEONLY-ETF-BC50-BOND30-v1
```

但本文指标的精确数据父版本是刷新研究账本：

```text
W13612-A015-MOMBIN-3OF5-VOTEONLY-ETF-BC50-BOND30-R20261116
```

只将W原`final_exposure`乘以VIX状态，不改变W的行业、ETF、A015、MOMBIN、
BC50或债券选择。

历史稳健性为`PASS`，当前标签为`ROBUST_SHADOW_ELIGIBLE`。由于历史已经查看、
W生产刷新后段仍阻塞，不能升级为生产。

冻结 `v1` tag 的 `70.53% / 2.459 / -20.05%` 与本文共同轴结果不是同一快照。
本文所有结果绑定刷新 `R20261116` 账本；刷新W在2019-08-01至2026-07-31的
对应基准为`67.17% / 2.346 / -20.52%`。

## 共同轴比较

2019-08-01至2026-11-16，5bp：

| 策略 | CAGR | Sharpe | MDD | Calmar |
|---|---:|---:|---:|---:|
| W base | 63.39% | 2.227 | -29.05% | 2.182 |
| W + global VIX | **66.67%** | **2.505** | **-20.42%** | **3.265** |
| ER base | 65.40% | 2.281 | -26.15% | 2.501 |
| ER + RISK_VIX | **67.41%** | 2.405 | -23.26% | 2.898 |

## 稳健性

W直接样本2019-08至2026-07：

- 5bp：70.21% / Sharpe2.600 / MDD-18.73%；
- 10bp：66.89% / 2.476 / -19.22%；
- 20bp：60.43% / 2.235 / -20.18%；
- 27/27参数邻域为正增量；
- 500次循环随机移位安慰剂单侧p约0.008；
- 四个起点均为正增量。

## 前瞻影子

首个信号：

```text
signal_date:      2026-11-20
effective_date:   2026-11-23
VIX last obs:     2026-11-18
VIX:              24.56
252日分位:         0.91865
multiplier:       0.5
```

当前只登记VIX乘数。W生产敞口和收益为`WAITING_FOR_W_SOURCE_WIRING`。

## 结论状态

```text
historical robustness: PASS
independent OOS: BLOCKED
production: NO_CHANGE
live profitability: NOT_ASSESSED
```
