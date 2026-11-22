# Tech rotation research overview (2026-11-22)

本目录是 `rotation/tech-rotation` 三个版本化研究包的只读发布镜像，用于让
`techtitan` 成为科技策略主库，同时保留对外的冻结回放材料。

```text
source repository: hrdg/rotation
source commit:     6a9f0fa140b9ecda6696e050dde2077253b0469b
techtitan base:    1ccf4414d1fe4befebf792f602a6fc1218d28539
import mode:       non-destructive mirror
```

原 `rotation/tech-rotation` 保留不删。本次没有复制或覆盖 `src/tech_rotation/`，
也没有替换 `techtitan` 原有冻结基线与研究运行记录。

## 迁入的上游 README 总览

以下内容迁自 `rotation@6a9f0fa14:tech-rotation/README.md`。基线附件仍保留在
rotation 的发布目录；三个最新版本包已完整迁入本目录。

### 科技行业轮动：ΔC∩RV + ΔAR×TIP 二值闸门

冻结标签：`BASE_DC_RV_DARxTIP_CALENDAR_H11006_V20261104`（v1 标签
`..._V20261103` 保留为对照）。

该发布目录对应西南证券《科技成长景气轮动与量化择时模型》（2026-09-10）的本地扩展：
月频用集中度变化 `ΔC` 与相对估值 `RV` 选择科技行业，日频用研报 `ΔAR(1.5)` 与
TIP 综合动量组成二值风险闸门，关闭时持有中证国债指数 `H11006`。

#### 模型配置

| 层 | 配置 |
| --- | --- |
| 行业池 | 10个申万2021版二级科技行业 |
| 集中度 | 125日加权PCA，前2主成分；半衰期125日并乘前一日流通市值平方根 |
| 月频选择 | `ΔC`前4与`RV`前2取交集，交集内等权；空交集延续原持仓 |
| TIP | TIP收盘重采样到A股交易日后，21/63/126/252日收益等权平均，正值为风险开启（v2 日历口径） |
| ΔAR | `<0`开启，`>1.5`关闭，中间区域保持原状态 |
| 最终风险仓位 | `ΔAR状态 × TIP状态`，收盘确认，下一交易日生效 |
| 防守资产 | 风险仓位之外全部持有H11006 |
| 评价 | 250交易日年化、无风险利率0、零成本指数模拟 |
| 滚动OOS | 2017–2020初始历史；2021–2026年度扩展窗测试；不重拟合且跨年不重置状态 |

正式配置见
[`config/strategy.json`](https://github.com/hrdg/rotation/blob/main/tech-rotation/config/strategy.json)，
输入字段与冻结哈希见
[`config/data_contract.json`](https://github.com/hrdg/rotation/blob/main/tech-rotation/config/data_contract.json)。

#### 滚动OOS绩效

年度测试折拼接区间为2021-01-04至2026-10-30，共1410个交易日（v2 日历口径）：

| 指标 | 数值 |
| --- | ---: |
| 累计收益 | 418.26% |
| 年化收益 | 33.87% |
| 年化波动 | 30.00% |
| Sharpe | **1.129** |
| 最大回撤 | **-25.99%** |
| Calmar | 1.303 |

全期2017-01-03至2026-10-30：年化36.73%、Sharpe 1.253、最大回撤 −31.50%。
训练期2017–2020 Sharpe 1.448，测试期1.129，衰减22.0%。

##### v1 → v2 变更（2026-11-04）

`28/84/168/364` 是日历天（1/3/6/12个月），但旧实现按美股交易日行数平移，
实际跨度被拉长到1.3/4/8/17个月。v2改为先把TIP收盘重采样到A股交易日，
再用21/63/126/252个交易日：

| 口径 | 测试年化 | 测试Sharpe | 测试回撤 | 训练Sharpe | 衰减 |
| --- | ---: | ---: | ---: | ---: | ---: |
| v1（28/84/168/364 美股行） | 33.03% | 1.113 | −28.41% | 1.234 | 9.8% |
| **v2（21/63/126/252 日历）** | **33.87%** | **1.129** | **−25.99%** | 1.448 | 22.0% |

绝对表现与回撤均改善，但训练期抬升更多，Sharpe衰减从9.8%升到22.0%；
按“衰减<20%”口径，v2不达标。两者是不同结论，不能只报其中一个。

逐折绩效、每日收益和净值见
[`results/`](https://github.com/hrdg/rotation/tree/main/tech-rotation/results)。

这是一条**历史伪实时滚动OOS**，不是独立OOS：策略设计已经查看过全历史；
2021-12-13以前的行业成员使用后期名单前推。2023年Sharpe异常高主要因为闸门
长期关闭、收益来自低波动国债，并不代表当年科技选行业能力很强。

#### 基线运行入口

供应商行情和券商研报原文不随仓库分发。把满足数据契约的3个文件放入
`tech-rotation/data/`后，运行：

```bash
cd tech-rotation
python -m venv .venv
.venv/bin/pip install -r requirements.txt
.venv/bin/python scripts/run_rolling_oos.py
.venv/bin/python -m pytest tests -q
```

基线代码入口仍见
[`scripts/run_rolling_oos.py`](https://github.com/hrdg/rotation/blob/main/tech-rotation/scripts/run_rolling_oos.py)。
三个最新版本包的回放命令见本文“回放”。

#### 上游基线已知限制

- 2021-12-13以前使用后期行业成员前推，历史股票池检查为FAIL；
- 行业指数由成分股代理重建，数据源与研报Wind口径不同；
- 收盘到收盘收益近似研报所述月初开盘成交，未计交易费、滑点和ETF跟踪误差；
- TIP增强是查看历史后提出的扩展，不属于研报原生模型；
- 发布绩效支持进入前瞻跟踪，不证明未来盈利。

### 扩展：77因子综合动量确认闸

`momentum77` 在基准之上叠加第三道月频确认闸：77个候选特征按过去3个月 ICIR
取前30、符号对齐后 z 相加，只保留综合动量前4的候选。早期价格量代理得到测试期
Sharpe 1.113→1.248、年化33.0%→36.8%、回撤不变，但增量全部集中在2026年；
剔除后0.852低于基准0.864，未采纳为主策略。

2026-11-04改用该窗口权威的77因子（研报图19市场状态变量 +
ICIR/Z_EQUAL/top30）后，月频测试Sharpe 1.038、周频0.946，均低于基准1.113。
确认闸不成立，周频版本同样不成立。实现与结果见
[`momentum77/`](https://github.com/hrdg/rotation/tree/main/tech-rotation/momentum77)。

### 扩展：有效秩高→W 月频选择器

使用18个科技行业过去63日协方差有效秩，与过去252日中位数比较：有效秩高时下月
持有新版 `W13612-A015-MOMBIN-3OF5-VOTEONLY-ETF-BC50-BOND30-R20261116`，
否则持有新版V2。标签为 `EFFECTIVE_RANK_HIGH_W@R20261116`。

2019-08至2026-11-16为65.44% / Sharpe 2.282 / MDD -26.15% / Calmar 2.503，
四项均超过新版W基准的63.43% / 2.228 / -29.05% / 2.183；但Sharpe增量的
63日块bootstrap区间跨零，因此仅作前瞻影子，不修改生产配置。

### 扩展：有效秩 + 行业 `RISK_VIX`

在W/V2两个候选分支内部先应用行业VIX Beta防守，再由原有效秩选择器选择分支。
5bp分支换手下，全期年化、Sharpe和MDD为67.41% / 2.405 / -23.26%，对同轴父策略
65.40% / 2.281 / -26.15%。10bp分支换手压力下方向不变。21日块bootstrap对原器及
同平均防守系数均跨零，故仍为`SHADOW_ONLY`。

### 扩展：W13612 + 全球VIX日频状态

仅对当前W科技腿的最终敞口增加一层全球VIX防守：252日VIX分位达到80%时，
W原敞口乘0.5；行业、ETF、A015、MOMBIN、BC50和债券切换保持不变。

统一到2019-08-01至2026-11-16，W原版、W+全球VIX、有效秩基准和ER_RISK_VIX
分别为63.39% / 2.227、66.67% / 2.505、65.40% / 2.281和67.41% / 2.405；
W+全球VIX的Sharpe和回撤最优，ER_RISK_VIX的CAGR最高。历史参数邻域、成本、
跨起点和循环移位安慰剂支持进入影子候选，但W生产刷新后段仍为
`BLOCKED_W_SOURCE_NOT_WIRED`，因此不修改生产。

## 发布包

| 标签 | 角色 | 截止日 | CAGR | Sharpe | MDD | 证据状态 |
|---|---|---|---:|---:|---:|---|
| `EFFECTIVE_RANK_HIGH_W@R20261116` | W/V2有效秩月频选择 | 2026-11-16 | 65.44% | 2.282 | -26.15% | `SHADOW_ONLY` |
| `ER_RISK_VIX@20261122` | 有效秩选择器内叠行业VIX Beta防守 | 2026-11-16 | 67.41% | 2.405 | -23.26% | `SHADOW_ONLY` |
| `W13612-GLOBAL-VIX@20261116` | W最终敞口外叠全球VIX状态 | 2026-11-16 | 66.67% | 2.505 | -20.42% | `ROBUST_SHADOW_ONLY` |

三包均不是生产配置，且历史已查看，不是独立 OOS。所有结果只支持影子观察、
解释性比较和下一轮预注册实验。

## 版本关系

```text
W13612-A015-MOMBIN-3OF5-VOTEONLY-ETF-BC50-BOND30-v1
  = 冻结架构父版本

W13612-A015-MOMBIN-3OF5-VOTEONLY-ETF-BC50-BOND30-R20261116
  = 刷新研究账本；三个发布包的唯一精确数据父版本

EFFECTIVE_RANK_HIGH_W@R20261116
  = R20261116 上的W/V2有效秩选择器
        |
        +-> ER_RISK_VIX@20261122
             在W、V2分支内部各加行业VIX Beta守卫

W13612-GLOBAL-VIX@20261116
  = 与上述选择器平行的W单腿实验
        |
        +-> 在W最终敞口上加全球VIX乘数
```

冻结 `v1` tag 的 `70.53% / 2.459 / -20.05%` 是另一条历史账本。刷新W在
`2019-08-01..2026-07-31` 为 `67.17% / 2.346 / -20.52%`；共同截止到
`2026-11-16` 为 `63.39% / 2.227 / -29.05%`。不能把全球VIX包的增量归到冻结
`v1` 的原始 `70.53%` 上。

## 包导航

- [`effective-rank-w-20261116/README.md`](effective-rank-w-20261116/README.md)
- [`effective-rank-riskvix-20261122/README.md`](effective-rank-riskvix-20261122/README.md)
- [`w13612-global-vix-20261116/README.md`](w13612-global-vix-20261116/README.md)
- [`w13612-global-vix-20261116/reports/STRATEGY_ARCHITECTURES.md`](w13612-global-vix-20261116/reports/STRATEGY_ARCHITECTURES.md)
- [`VERSION_MAP.json`](VERSION_MAP.json)
- [`VERIFICATION.md`](VERIFICATION.md)

## 回放

各包只依赖本目录内的冻结输入，不依赖原工作树绝对路径：

```bash
cd effective-rank-w-20261116
uv run --python 3.12 --with pandas --with numpy python code/rebase_from_frozen_inputs.py

cd ../effective-rank-riskvix-20261122
uv run --python 3.12 --with pandas --with numpy python code/test_replay.py
uv run --python 3.12 --with pandas --with numpy python code/replay_frozen.py

cd ../w13612-global-vix-20261116
uv run --python 3.12 --with pandas --with numpy python code/test_replay.py
uv run --python 3.12 --with pandas --with numpy python code/replay_frozen.py
uv run --python 3.12 --with pandas --with numpy --with matplotlib python code/make_chart.py
```

2026-11-22 的迁移验收入口为：

| 包 | 验证结果 |
|---|---|
| `EFFECTIVE_RANK_HIGH_W` | 指标重算最大差 `7.532e-13`，日收益最大差 `9.975e-17`；bootstrap p值因依赖版本最多差 `0.0124`，裁决不变。发布包保留源提交字节。 |
| `ER_RISK_VIX` | 3/3 测试通过；冻结回放摘要与归档日志 SHA256 相同。 |
| `W + global VIX` | 2/2 测试通过；冻结回放摘要与归档日志 SHA256 相同；净值图按字节复现。 |

全球VIX数据证书结构检查为 `PASS`，但 `asof_available_at` / 历史成员为
`PARTIAL`，供应商修订链为 `BLOCKED`。这只能证明归档声明完整，不能证明 PIT
或生产可交易性已通过。

## 迁移边界

- 这是发布包迁移，不是重新执行原论文复现，也不伪造补齐历史实验当时不存在的门禁文件。
- `ER_RISK_VIX` 与 `W + global VIX` 包含 `ALGORITHM.md`、验证记录和归档哈希链；
  `EFFECTIVE_RANK_HIGH_W` 保留原发布包结构和 `reports/ALGORITHM.md`。
- ETF历史成员、供应商修订链和VIX发布时间仍为部分认证；不能据此声称生产可交易。
- 全球VIX首个影子信号为 2026-11-23 的 `0.5` 乘数，但W生产刷新未接通，
  因此前瞻净值为 `BLOCKED_W_SOURCE_NOT_WIRED`，没有合成收益。
