# VOTE_ONLY_HALF 与 VOTE_ONLY_BINARY

状态：历史研究变体；`VOTE_ONLY_HALF` 为优先影子候选，
`VOTE_ONLY_BINARY` 为对照并对应冻结标签
`W13612-A015-MOMBIN-3OF5-VOTEONLY-ETF-BC50-BOND30-v1`。
生产版本仍保留 `BOTH_HALF_VOTE`，未来盈利未评估。

## 变量的含义

MOM20 状态为：

```text
MOM_SCALE = 0.5  20日篮子收益 <= -10%，直到恢复到 -2%
MOM_SCALE = 1.0  其余时间
```

原有四票是 `DAR`、`TIP`、`MA120`、`DD`；`core_votes` 是四票之和，
`core_available` 是可计算的票数。`mother_exposure` 是
W13612/A015 母策略给出的权益敞口。

## 两个只投票版本

```text
VOTE_ONLY_HALF:
  gate = 1[core_votes + MOM_SCALE >= 3]
  exposure = mother_exposure * gate

VOTE_ONLY_BINARY:
  MOMBIN = 1[MOM_SCALE == 1]
  gate = 1[core_votes + MOMBIN >= 3]
  exposure = mother_exposure * gate
```

两者都不再额外乘以 `MOM_SCALE`。当只有部分票可计算时，门槛取
`min(3, available)`，与父策略冻结规则一致。

与当前生产架构的区别：

```text
BOTH_HALF_VOTE:
  exposure = mother_exposure
             * MOM_SCALE
             * 1[core_votes + MOM_SCALE >= 3]
```

当前生产架构把同一 MOM20 状态同时用于投票和仓位乘数。

## 冻结标签

完整标签：

```text
W13612-A015-MOMBIN-3OF5-VOTEONLY-ETF-BC50-BOND30-v1
```

其风险架构对应 `VOTE_ONLY_BINARY`：

- `W13612 > 0.5%` 是基础母闸门；
- `A015` 强信号与 `DAR` 分支按父策略规则取较大敞口；
- `DAR/TIP/MA120/DD/MOMBIN` 至少 3/5 票；
- MOM20 压力时 `MOMBIN=0`，正常时 `MOMBIN=1`；
- 投票通过时恢复母敞口，不再乘 `MOM_SCALE`；
- ETF 映射使用 `BC50`；
- 风险关闭资产为 `511260`（30年国债 ETF 上市前）后接 `511090`。

冻结清单在
[`research/runs/mom20_10_mom_vote_architecture_20261114/FROZEN_LABEL.json`](../research/runs/mom20_10_mom_vote_architecture_20261114/FROZEN_LABEL.json)。

## 历史结果

样本为 2019-08-01 至 2026-07-31，共 1697 个交易日，5bp 单边成本：

| 架构 | 年化 | Sharpe | Sortino | 最大回撤 | Calmar |
|---|---:|---:|---:|---:|---:|
| `BOTH_HALF_VOTE` | 67.79% | 2.397 | 4.090 | -20.05% | 3.381 |
| `VOTE_ONLY_HALF` | 70.53% | 2.459 | 4.205 | -20.05% | 3.517 |
| `VOTE_ONLY_BINARY` | 70.53% | 2.459 | 4.205 | -20.05% | 3.517 |

10bp 成本下，两个只投票版本仍为 67.55% 年化、2.355 Sharpe、
-20.43% 最大回撤。

本历史样本中没有出现 `core_votes=2.5` 且 `MOM_SCALE=0.5` 的日期，
所以半票和二值票的逐日闸门、敞口和收益完全相同。这一等价性是样本事实，
不是公式等价：

```text
VOTE_ONLY_HALF(2.5, 0.5) = 3/5 -> 放行
VOTE_ONLY_BINARY(2.5, 0.5) = 2.5/5 -> 拦截
```

该边界由 [公式测试](../tests/test_vote_architecture.py) 固定。

## 选择与限制

`VOTE_ONLY_HALF` 相对当前双用架构的点估计增量：

- 年化 `+2.74pp`，21日循环块 bootstrap 95% 区间
  `[-1.09pp, +7.43pp]`；
- Sharpe `+0.062`，95% 区间 `[-0.071, +0.200]`；
- 最大回撤差异约为 0。

区间跨 0，因此只投票版本是优先影子候选，不是已确认的统计改进。
`VOTE_ONLY_BINARY` 不应仅因历史并列而优先于半票版本：它改写了第五票
的语义，却没有获得额外样本证据。

数据与验收限制：

- 这是含历史代理的已查看样本，不是独立 OOS；
- V2 ETF 成员和历史时点认证仍为 `PARTIAL`；
- 只投票架构在 MOM 压力日可能由半仓变为满仓或空仓；
- 未搜索其他 MOM 阈值或仓位比例；
- 生产变更、实盘盈利和前瞻增量均未确认。

## 代码与复现

- 可复用纯函数：
  [`src/tech_rotation/vote_architecture.py`](../src/tech_rotation/vote_architecture.py)
- 测试：[`tests/test_vote_architecture.py`](../tests/test_vote_architecture.py)
- 完整实验：
  [`research/runs/mom20_10_mom_vote_architecture_20261114`](../research/runs/mom20_10_mom_vote_architecture_20261114)

```bash
.venv/bin/python -m pytest tests/test_vote_architecture.py -q
.venv/bin/python research/runs/mom20_10_mom_vote_architecture_20261114/run.py
.venv/bin/python research/runs/mom20_10_mom_vote_architecture_20261114/validate.py
```
