# Validation

| 检查 | 状态 | 证据 |
|---|---|---|
| W base重建 | PASS | 最大收益与敞口差均为0 |
| VIX状态规则 | PASS | `code/test_replay.py` |
| 未来VIX不变性 | PASS | 合成截断测试 |
| 共同末点 | PASS | 所有序列止于2026-11-16 |
| 参数邻域 | PASS | 27/27正增量 |
| 循环移位安慰剂 | PASS | 单侧p约0.008 |
| 重复运行 | PASS | 输出哈希一致 |
| W生产刷新 | BLOCKED | 2026-07-31后source未接回 |
| ETF历史成员/vintage | PARTIAL | 继承父策略限制 |
| 独立OOS | BLOCKED | 历史已查看 |
| 未来盈利 | NOT_ASSESSED | 回测不能证明未来 |

结论：

```text
code_correctness: PASS
historical_robustness: PASS
methodological_validity: PARTIAL
production_readiness: BLOCKED
live_profitability: NOT_ASSESSED
```
