# Validation

## 复现命令

```bash
uv run --python 3.12 --with pandas --with numpy python code/test_replay.py
uv run --python 3.12 --with pandas --with numpy python code/replay_frozen.py
uv run --python 3.12 --with pandas --with numpy python code/generate_guard_panel.py
```

## 分项结果

| 检查 | 状态 | 证据 |
|---|---|---|
| 合成切换费用 | PASS | `test_selector_cost_is_charged_once_on_switch_day` |
| 5bp冻结账本逐日重放 | PASS | 最大差`4.30e-16` |
| 10bp冻结账本逐日重放 | PASS | 最大差`4.30e-16` |
| 5bp bootstrap重放 | PASS | 最大差`6.66e-16` |
| 10bp bootstrap重放 | PASS | 最大差`1.30e-15` |
| 85个月末守卫重建 | PASS | `generate_guard.log`，最大差0 |
| 两次重放哈希 | PASS | `replay_hash_diff.txt`为空 |
| 原始未来数据扰动 | NOT_RUN | 冻结包不包含完整供应商行情 |
| 历史ETF/行业成员 | PARTIAL | 继承父策略，本包未重新认证 |
| 供应商修订链 | BLOCKED | 仅有冻结快照 |
| 独立OOS | BLOCKED | 全历史已查看 |
| 未来盈利性 | NOT_ASSESSED | 回测不能证明未来收益 |

## 结论

```text
code_correctness: PASS
methodological_validity: PARTIAL
report_reproduction: NOT_APPLICABLE
live_profitability: NOT_ASSESSED
```

研究增量在5bp和10bp均为正点估计，但21日块bootstrap区间全部跨零。因此
`SHADOW_ONLY`，不修改生产策略。
