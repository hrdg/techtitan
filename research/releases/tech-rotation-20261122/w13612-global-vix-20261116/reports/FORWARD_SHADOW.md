# 前瞻影子

## 定义

```text
base architecture: W13612-A015-MOMBIN-3OF5-VOTEONLY-ETF-BC50-BOND30-v1
exact data parent: W13612-A015-MOMBIN-3OF5-VOTEONLY-ETF-BC50-BOND30-R20261116
rule: trailing 252-session CBOE VIX percentile >=0.80 => W exposure x0.5
lag: conservative A-share alignment plus next-session execution
```

## 当前状态

| 字段 | 数值 |
|---|---|
| signal date | 2026-11-20 |
| effective date | 2026-11-23 |
| VIX last observation | 2026-11-18 |
| VIX used | 24.56 |
| 252-day percentile | 0.91865 |
| multiplier | 0.5 |
| W base exposure | unavailable |
| shadow exposure | unavailable |
| status | `WAITING_FOR_W_SOURCE_WIRING` |

## 边界

W生产刷新链路仍为`BLOCKED_W_SOURCE_NOT_WIRED`。直到该链路完成：

- 不生成虚拟W仓位；
- 不生成前瞻NAV；
- 不将信号命中率当成策略绩效；
- 继续保存每日乘数以便未来回放。
