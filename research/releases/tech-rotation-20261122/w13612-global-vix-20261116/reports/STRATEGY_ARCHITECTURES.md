# 四种科技轮动策略的 text 架构

本文解释 `W base`、`W + global VIX state`、`Effective-rank base` 和
`ER + RISK_VIX` 的结构差异。四条策略使用同一回测截止日
`2026-11-16`。

这里的 `W base` 是 `W13612-A015-MOMBIN-3OF5-VOTEONLY-ETF-BC50-BOND30-R20261116`
刷新研究账本，不是冻结 `v1` tag 的原始账本。架构相同，但W数据快照和绩效口径不同。

## 1. W base

```text
W13612冻结的行业与ETF目标
  -> ETF目标权重
  -> W equity_return

TIP W13612 + DAR + A015
  -> mother_exposure

MOMBIN20
  -> MOMBIN状态
  -> 与DAR、TIP、MA120、DD组成五票
  -> VOTEONLY 3/5

W原最终敞口
  = mother_exposure × vote_gate

W net return
  = exposure × equity_return
  + (1-exposure) × bond_return
  - turnover cost
```

这是单腿W策略，不含有效秩选择器、全球VIX额外乘数或行业RISK_VIX。

## 2. W + global VIX state

```text
W13612冻结的行业与ETF目标
  -> W原五票、母敞口和债券切换
  -> W原final_exposure

CBOE VIX
  -> 映射到最近可得A股日期
  -> 滞后
  -> 252日历史分位
  -> percentile>=80%：multiplier=0.5
  -> 否则：multiplier=1.0
  -> 再滞后一个A股交易日

candidate exposure
  = W final_exposure × VIX multiplier

同一ETF目标与债券余额
  -> 完整换手成本
  -> W + global VIX return
```

这是单腿W策略。全球VIX只作用于最终敞口，不改变行业、ETF、A015、MOMBIN、
BC50或债券切换，也不包含W/V2选择。

## 3. Effective-rank base

```text
W base分支 ─────────────────┐
                            │
V2 base分支 ────────────────┤
                            │
18行业日收益                │
  -> 63日协方差             │
  -> 有效秩ER               │
  -> 过去252日分位          │
  -> 月末状态               │
                            │
ER分位>50% -> 下月选W       │
ER分位<=50% -> 下月选V2     │
                            │
W/V2切换首日额外扣10bp      │
                            v
                      Effective-rank
                      base return
```

这是W/V2月频单边选择器，不是资金比例混合。W和V2内部原有的选择与风控保持不变。

## 4. ER + RISK_VIX

```text
W base分支
  -> W原final_exposure

V2 base分支
  -> V2原final_exposure

18行业月度收益对ΔCBOE VIX
  -> 36个月滚动Beta
  -> 选中行业Beta分位均值

CBOE VIX
  -> 252日历史分位

VIX分位>=80%
且选中行业Beta分位均值<=50%
  -> RISK_VIX guard=0.5
否则
  -> guard=1.0

W_GUARDED
  = W final_exposure × RISK_VIX guard

V2_GUARDED
  = V2 final_exposure × RISK_VIX guard

原63日有效秩
  -> 仍选择W_GUARDED或V2_GUARDED
  -> W/V2切换仍扣10bp

最终收益
  = 选中guarded分支收益
```

该策略同时改造W、V2两个分支，但守卫发生在有效秩选择之前，不改变选择规则。

## 结构差异

| 项目 | W base | W + global VIX | ER base | ER + RISK_VIX |
|---|---:|---:|---:|---:|
| W科技腿 | 有 | 有 | 有 | 有 |
| V2候选腿 | 无 | 无 | 有 | 有 |
| 有效秩W/V2选择 | 无 | 无 | 有 | 有 |
| W/V2切换10bp | 无 | 无 | 有 | 有 |
| W原五票风控 | 有 | 有 | 有 | 有 |
| 全球VIX直接乘数 | 无 | 有 | 无 | 无 |
| 行业VIX Beta守卫 | 无 | 无 | 无 | 有 |
| 守卫位置 | 无 | W最终敞口之后 | 无 | W、V2选择器之前 |

关系概括：

```text
W base
  = 单腿W

W + global VIX
  = 单腿W + 市场级VIX总开关

ER base
  = W/V2单边选择器

ER + RISK_VIX
  = W/V2单边选择器
  + 两个分支各自的行业VIX敏感度守卫
```

`W + global VIX` 与 `ER + RISK_VIX` 是平行候选，不是父子策略。当前尚未测试
把全球VIX总开关再叠加到ER_RISK_VIX上。

## 同一截止日结果

| 策略 | CAGR | Sharpe | MDD | Calmar |
|---|---:|---:|---:|---:|
| W base | 63.39% | 2.227 | -29.05% | 2.182 |
| W + global VIX | 66.67% | **2.505** | **-20.42%** | **3.265** |
| ER base | 65.40% | 2.281 | -26.15% | 2.501 |
| ER + RISK_VIX | **67.41%** | 2.405 | -23.26% | 2.898 |

收益优先看`ER + RISK_VIX`；Sharpe和回撤优先看`W + global VIX`。
