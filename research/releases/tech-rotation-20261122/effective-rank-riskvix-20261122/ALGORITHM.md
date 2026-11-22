# ER_RISK_VIX 算法与归档

规格版本：`strategy.json@1.0.0`
策略ID：`ER-RISKVIX-HA009-20261122`

## 1. 策略 text 流程图

```text
[原始研究路径，不在本包内重算供应商全量行情]
18行业月度收益 + VIX历史
  -> VIX按A股交易日ffill并shift(1)
  -> VIX月度点位差分
  -> 各行业36个月OLS beta
  -> VIX 252日滚动分位
  -> 月末 signal date

V2原策略：
  ΔC Top5 ∩ RV Top3 -> 行业集合 -> ETF映射 -> V2原exposure

风险覆盖：
  selected_beta_rank = mean(pct_rank(beta_i | selected industries))
  if VIX_pct>=0.80 and selected_beta_rank<=0.50:
      guard=0.5
  else:
      guard=1.0
  W_GUARDED = simulate(W原target, W原exposure*guard)
  V2_GUARDED = simulate(V2原target, V2原exposure*guard)

有效秩选择：
  63日18行业协方差 -> eigenvalues -> effective_rank
  月末对比过去252日 -> percentile
  percentile>0.5 -> 下一月W
  percentile<=0.5 -> 下一月V2
  切换首日扣10bp

输出：
  guard_diagnostics.csv + branch_returns_{5,10}bp.csv
  -> replay_frozen.py
  -> ER_BASE_COST / ER_RISK_VIX / ER_MATCHED
  -> metrics / bootstrap / performance_comparison
```

包内可执行边界是“冻结分支收益 → 月度选择 → 切换成本 → 绩效”。VIX Beta和
守卫月报可由`generate_beta_panel.py`及`generate_guard_panel.py`复核，但两者所需的
原始行业面板和VIX行情不随仓库分发。

## 2. 数学公式

| ID | 公式 | 代码符号 | 单位/窗口 | 可用时点 | 来源/决定 |
|---|---|---|---|---|---|
| F1 | `r_i,m=(1+r_i,d)月度复合-1` | `monthly` | decimal / 月 | 月末收盘后 | 本地派生 |
| F2 | `v_m=VIX_{a,m-1}`；`Δv_m=v_m-v_{m-1}` | `vix_aligned`, `shock_monthly` | VIX点 / 月 | 月度决策前最后已知A股收盘 | P-F01 |
| F3 | `b_i=Σ(v-mean(v))(r_i-mean(r_i))/Σ(v-mean(v))²`，36个月 | `beta` | 无量纲斜率 / 36月 | signal month-end | P-F01 |
| F4 | `q_t=rank_pct_252(VIX_t)` | `state_rank_vix` | [0,1] / 252日 | signal close | 本地冻结阈值 |
| F5 | `β̄_t=mean_j rank_pct(b_j,t)` | `selected_beta_rank` | [0,1] / 横截面 | signal month-end | P-F01、本地映射 |
| F6 | `g_t=.5*1[q_t>=.8,β̄_t<=.5]+1*1[otherwise]` | `guard` | {0.5,1} | signal close，次日生效 | D-001 |
| F7 | `e_t^G=e_t^branch*g_t` | branch exposure | [0,1] | next session | D-001 |
| F8 | `ER_t=exp(-Σp_k,t log p_k,t)`，63日协方差 | frozen selector | 实数 | prior month-end | P-F02 |
| F9 | `I_t=1[percentile_252(ER_t)>.5]`；1选W，0选V2 | `selected` | 二值 / 月 | 次月首个交易日 | P-F02 |
| F10 | `r_t=selected_branch_return_t-.001*1[switch_t]` | `replay_selector` | decimal / 日 | 切换月首交易日 | P-F02 |
| F11 | `Sharpe=CAGR/annualized_vol`；配对差用21日块bootstrap | `performance`, `block_bootstrap_delta` | 年化 | 全期末 | 验收协议 |

F6在W和V2中分别执行，但F8/F9不读取`guard`，因此守卫不能反向改变W/V2选择。

## 3. 变量状态图与时间契约

### 3.1 变量表

| 变量 | 含义 | 类型/单位 | 窗口 | available_at | 代码符号 |
|---|---|---|---|---|---|
| `r18` | 18行业日收益 | decimal | daily | A股收盘 | `industry_returns` |
| `VIX` | VIX收盘点位 | index points | daily | 当时最近可得A股收盘前 | `vix_aligned` |
| `b_i` | 行业对ΔVIX斜率 | real | 36月 | signal month-end | `industry_vix_beta.csv` |
| `q_t` | VIX历史分位 | [0,1] | 252日 | signal close | `state_rank_vix` |
| `β̄_t` | 入选行业Beta分位均值 | [0,1] | monthly | signal close | `selected_beta_rank` |
| `g_t` | 额外防守系数 | {0.5,1} | monthly | signal close | `guard` |
| `e_t` | 分支原风险敞口 | [0,1] | daily | next session | `W_EXPOSURE`, `V2_EXPOSURE` |
| `arm_t` | W/V2选择 | categorical | monthly | next month | `selected` |
| `r_t` | 日净收益 | decimal | daily | 收盘后记账 | replay output |

### 3.2 变量血缘图

```text
industry daily returns ──> monthly returns ──┐
VIX close -> A-share alignment -> shift(1) ─┴> 36m beta b_i
VIX close -> 252d percentile -> q_t
holdings.selected industries ─> β̄_t
                                 |
                         q_t,β̄_t -> guard
                                     |
W/V2 original exposure ─────────────┴> guarded exposure
W/V2 original branch returns -> guarded branch returns
                                     |
monthly effective-rank state ─> W/V2 choice + 10bp switch
                                     |
                                   daily return
```

### 3.3 状态迁移图

```text
Guard:
UNINITIALIZED -> WARMUP(<36 months) -> NO_ADJUSTMENT(1.0)
VALID_BETA + VIX_NOT_HIGH -> NO_ADJUSTMENT(1.0)
VALID_BETA + VIX_HIGH + SELECTED_BETA_HIGH -> NO_ADJUSTMENT(1.0)
VALID_BETA + VIX_HIGH + SELECTED_BETA_LOW -> HALF_EXPOSURE(0.5)
MISSING_BETA/STATE -> BLOCKED (replay fails closed)

Selector:
WARMUP(<126 trailing observations) -> HOLD_PREVIOUS_SLEEVE
VALID -> W_HIGH / V2_LOW
MONTH_BOUNDARY -> NEXT_MONTH_TARGET -> SWITCH_COST if changed
```

守卫的月末信号只影响次交易日后的敞口。2026-01至2026-11-16没有触发，故该窗口
与父策略逐日一致，不能把它解释为“防守在2026仍然贡献收益”。

## 4. 规格—代码—测试映射

| 规格/公式 | 代码入口 | 数据字段 | 测试或日志 | 状态 |
|---|---|---|---|---|
| F1–F4、36月Beta和VIX分位 | `code/generate_beta_panel.py::build_panels` | 行业收益、VIX | `outputs/beta_replayed`、`logs/generate_beta.log` | PASS |
| F5–F6、月度守卫 | `code/generate_guard_panel.py::build_guard_panel` | holdings、beta、state | `test_replay.py::test_guard_panel_replays` | PASS |
| F8–F10、有效秩选择及切换费 | `code/replay_frozen.py::replay_selector` | branch returns、selections | `test_replay.py`、`logs/test_replay.log` | PASS |
| 同平均敞口对照 | `data/branch_returns_*`的`*_MATCHED` | branch ledgers | `logs/replay.log` | PASS |
| 21日块bootstrap | `code/replay_frozen.py::block_bootstrap_delta` | daily returns | `outputs/bootstrap_*` | PASS |
| 5bp/10bp成本 | `branch_returns_5bp/10bp.csv` | 分支净收益 | `logs/replay.log` | PASS |
| 历史成员 | 继承父数据 | 18行业与ETF映射 | `data/README.md` | PARTIAL |
| 供应商修订链 | 冻结快照 | 全部字段 | `data/README.md` | BLOCKED |

实现偏差：

- 本包不重新交易原始ETF，只重放冻结分支收益；
- 行业VIX敏感度是Copeland式代理，不是原文49行业的逐字样本复现；
- 2024-2026改善的统计区间仍跨零；
- 2026子样本无守卫触发。

## 5. 结果、验收与偏差

5bp全期对`ER_BASE_COST`：

```text
CAGR   65.40% -> 67.41%
Sharpe 2.281  -> 2.405
MDD    -26.15% -> -23.26%
```

10bp全期：

```text
CAGR   63.26% -> 65.31%
Sharpe 2.207  -> 2.330
MDD    -26.45% -> -23.41%
```

对原器和同平均防守系数的bootstrap区间均跨零，因此验收结论为：

```text
POINT_ESTIMATE: SUPPORTIVE
COST_ROBUSTNESS: SUPPORTIVE
STATISTICAL_CONFIRMATION: NOT_ACHIEVED
DECISION: SHADOW_ONLY
PRODUCTION_CHANGE: NO
```

## 6. 归档索引

机器可读哈希见[`archive_manifest.json`](archive_manifest.json)。

| 角色 | 文件 | 用途/边界 |
|---|---|---|
| 规格 | `strategy.json` | 冻结公式、窗口、成本和验收 |
| 证据 | `evidence.json` | 原论文机制与本地扩展边界 |
| 代码 | `code/replay_frozen.py` | 公开冻结回放与bootstrap |
| 代码 | `code/generate_beta_panel.py` | 36月Beta及VIX状态生成 |
| 代码 | `code/generate_guard_panel.py` | 月末RISK_VIX诊断重放 |
| 测试 | `code/test_replay.py` | 合成测试与发布账本对拍 |
| 数据 | `data/branch_returns_5bp.csv` | 5bp W/V2原始、守卫、匹配分支 |
| 数据 | `data/branch_returns_10bp.csv` | 10bp分支压力成本 |
| 选择 | `data/monthly_selections.csv` | 冻结有效秩月频选择 |
| 结果 | `outputs/performance_comparison.csv` | 成本后绩效对比 |
| 结果 | `outputs/bootstrap_comparison.csv` | Sharpe差bootstrap |
| 结果 | `outputs/guard_diagnostics.csv` | 85个月末守卫状态 |
| 报告 | `reports/REPORT.md` | 研究结论与竞争解释 |
| 验收 | `reports/VALIDATION.md` | 分项状态和命令证据 |
