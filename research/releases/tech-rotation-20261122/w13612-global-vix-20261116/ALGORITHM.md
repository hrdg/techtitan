# W13612 全球VIX风险覆盖：算法

规格版本：`strategy.json@1.0.0`

父版本分两层：

```text
base architecture:
  W13612-A015-MOMBIN-3OF5-VOTEONLY-ETF-BC50-BOND30-v1
exact data parent:
  W13612-A015-MOMBIN-3OF5-VOTEONLY-ETF-BC50-BOND30-R20261116
```

`v1` 提供架构身份；本包全部历史比较绑定刷新后的 `R20261116` 研究账本。

## 1. 策略 text 流程图

```text
CBOE VIX daily close
  -> reindex to A-share trading dates, ffill
  -> shift(1)
  -> trailing 252-session percentile
  -> raw state = .5 if pct>=.8 else 1
  -> shift(1)
  -> W original final exposure
  -> candidate exposure
  -> same ETF target + bond residual
  -> full turnover cost
  -> net return / NAV

Forward shadow:
  -> multiplier registration
  -> W production source blocked -> no synthetic NAV
```

## 2. 数学公式

| ID | 公式 | 代码 | 单位/窗口 | 可用时点 |
|---|---|---|---|---|
| F1 | `v_t=VIX_{latest available before A-share t}` | `global_vix_guard_from_series` | index points/daily | decision before close |
| F2 | `q_t=1[rank_252(v_t)>=.80]` | rank | [0,1]/252 | signal close |
| F3 | `g_raw_t=1-.5q_t` | state | [0.5,1] | close |
| F4 | `g_t=g_raw_{t-1}` | guard | [0.5,1] | next session |
| F5 | `e_t^cand=e_t^W g_t` | candidate exposure | [0,1] | next session |
| F6 | `r_t^cand=Σ(e_t^cand w_i,t r_i,t)+(1-e_t^cand)r_b,t-c|Δtarget|` | `simulate` | decimal/day | daily accounting |
| F7 | `NAV_t=Π(1+r_t)` | `performance` | start=1 | end |

## 3. 变量状态图与时间契约

### 3.1 变量表

| 变量 | 含义 | 类型/单位 | 窗口 | available_at | 缺失处理 |
|---|---|---|---|---|---|
| `VIX` | CBOE VIX | index points | daily | prior US close mapped to A-share date | stale/missing -> guard off |
| `q_t` | VIX历史分位 | [0,1] | 252 | signal close | warm-up guard off |
| `g_t` | 额外风险乘数 | {0.5,1} | daily | next session | missing ->1 |
| `e_t^W` | W原final exposure | [0,1] | daily | inherited | parent rule |
| `e_t^cand` | 候选敞口 | [0,1] | daily | next session | clip |

### 3.2 变量血缘图

```text
VIX -> A-share alignment -> lag -> 252d rank -> guard
                                            |
W original target/exposure -----------------+-> candidate target
                                                   |
                                      turnover + bond residual
                                                   |
                                              net return
```

### 3.3 状态迁移图

```text
WARMUP/MISSING -> GUARD_OFF
VALID+LOW -> GUARD_OFF
VALID+HIGH -> GUARD_HALF
SIGNAL -> NEXT_SESSION_TARGET -> ACCOUNTED
FORWARD_SIGNAL_READY + W_SOURCE_MISSING -> EVALUATION_BLOCKED
```

## 4. 规格—代码—测试映射

| 规格/公式 | 代码入口 | 测试或结果 | 状态 |
|---|---|---|---|
| VIX状态与边界 | `global_vix_guard_from_series` | `test_vix_state_is_bounded_and_lagged` | PASS |
| 未来VIX不变性 | `global_vix_guard_from_series` | `test_future_vix_does_not_change_cutoff` | PASS |
| 共同截止日 | `main` | `test_public_result_has_common_endpoint` | PASS |
| W收益重建 | `R20261116` source refresh | max abs diff=`0` | PASS |
| 同平均敞口 | robustness run | Sharpe `1.182` vs candidate `2.600` | PASS |
| 参数邻域 | robustness run | `27/27` positive | PASS |
| 循环移位安慰剂 | robustness run | p≈`0.008` | PASS |
| 前瞻W净值 | upstream source | W refresh blocked | BLOCKED |

## 5. 结果、验收与偏差

2026-11-16共同轴：

| 策略 | CAGR | Sharpe | MDD | Calmar |
|---|---:|---:|---:|---:|
| W base | 63.39% | 2.227 | -29.05% | 2.182 |
| W + global VIX | **66.67%** | **2.505** | **-20.42%** | **3.265** |
| ER base | 65.40% | 2.281 | -26.15% | 2.501 |
| ER + RISK_VIX | **67.41%** | 2.405 | -23.26% | 2.898 |

当前裁决为`ROBUST_SHADOW_ELIGIBLE`，但不是生产候选。架构来自冻结 `v1`；
2026-07-31后的W生产刷新链路仍阻塞，本包使用 `R20261116` 刷新研究账本做历史比较，
不把结果写成冻结 `v1` 账本的增量。

## 6. 归档索引

见`archive_manifest.json`。四种比较策略的逐层差异另见
`reports/STRATEGY_ARCHITECTURES.md`。
