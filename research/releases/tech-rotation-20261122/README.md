# Tech rotation release mirror (2026-11-22)

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
