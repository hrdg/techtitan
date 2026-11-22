# 新版基准重算审计

| 检查 | 状态 | 结论 |
|---|---|---|
| 基准统一 | PASS | 所有候选均对 `W_CAUSAL_NEWDATA` |
| 日期轴 | PASS | 选择器至2026-11-16；组合腿至同日 |
| 有效秩复现 | PASS | 最大差7.47e-17 |
| 平均相关修正 | PASS | 不再四项全胜，Sharpe低于W |
| FLOOR修正 | PASS | 全期落后，仅24–26局部领先 |
| V2修正 | PASS | 2026收益/Sharpe高，但MDD更深 |
| bootstrap完整性 | PASS | 5000路径，窗口与候选齐全 |
| 独立OOS | BLOCKED | 历史已查看 |
| 未来盈利 | NOT_ASSESSED | 不构成承诺 |

最终裁决：

```text
strict full-window exceder: EFFECTIVE_RANK_HIGH_W
statistically confirmed exceder: NONE
production change: NONE
```
