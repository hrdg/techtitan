# 局部超越候选新版基准重算：算法

规格版本：`strategy.json@0.1.0`

## 1. 策略 text 流程图

```text
新版77选30与ETF映射（至2026-11-16）
  -> 因果MOMBIN的新版W
  -> 新版V2
  -> 复用已冻结的月频选择表
  -> 重新合成AVG_CORR / EFFECTIVE_RANK候选
  -> 用新版权益/债券分解重算FLOOR候选
  -> 同窗口对照新版W
```

## 2. 数学公式

选择器组合收益：

\[
r_t^{selector}=r_t^{arm_t}-0.001\cdot 1[arm_t\ne arm_{t-1}]
\]

其中 `arm` 只取新版 W 或新版 V2。

FLOOR候选：

\[
w_t^{floor}=\max(w_t^W,\kappa w_t^{V2}1[trend^{V2}_{63,t}>0])
\]

\[
r_t^{floor}=r_t^W+(w_t^{floor}-w_t^W)(r_t^{equity}-r_t^{bond})
-0.0005\Delta w_t^{extra}
\]

`κ` 仅测试 25% 和 50%。

## 3. 变量状态图与时间契约

| 输入 | 版本/时点 |
|---|---|
| 新版W | 77选30至2026-11-16，因果MOMBIN |
| 新版V2 | 新版V2映射 |
| 月频选择表 | 原选择器冻结表，下一月生效 |
| V2趋势 | 前收盘的63日收益 |
| 基准 | `W_CAUSAL_NEWDATA` |

## 4. 规格—代码—测试映射

| 规则 | 代码 |
|---|---|
| 新版基础腿 | `load_new_base_returns` |
| 选择器重算 | `selector_returns` |
| FLOOR重算 | `floor_returns` |
| 有效秩复现 | 与新数据账本最大差检查 |
| bootstrap | 复用冻结月度选择器bootstrap |

有效秩旧结果与新账本最大差为 `7.47e-17`。

## 5. 结果、验收与偏差

- 平均相关：新版下不严格超越。
- 有效秩：新版全期四指标超越，但bootstrap跨零。
- FLOOR50/25：仅24–26局部超越。
- V2：2026收益/Sharpe更高，MDD更差。
- 无独立OOS，未来盈利`NOT_ASSESSED`。

## 6. 归档索引

- `PREREG.md`
- `strategy.json`
- `REPORT.md`
- `AUDIT.md`
- `outputs/metrics_rebased.csv`
- `outputs/bootstrap_rebased.csv`
- `outputs/selector_returns_rebased.csv`
- `outputs/portfolio_returns_rebased.csv`
- `outputs/floor_exposures.csv`
- `outputs/summary.json`
