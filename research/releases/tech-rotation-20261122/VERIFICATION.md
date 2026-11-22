# Migration verification (2026-11-22)

验证对象是 `rotation@6a9f0fa14` 的三个发布包。所有命令均在迁移后的
`techtitan` 隔离克隆中执行，回放输出写入临时目录。

## 命令

```bash
# effective-rank-w-20261116
uv run --python 3.12 --with pandas --with numpy python code/rebase_from_frozen_inputs.py

# effective-rank-riskvix-20261122
uv run --python 3.12 --with pandas --with numpy python code/test_replay.py
uv run --python 3.12 --with pandas --with numpy python code/replay_frozen.py --output-dir <tmp>

# w13612-global-vix-20261116
uv run --python 3.12 --with pandas --with numpy python code/test_replay.py
uv run --python 3.12 --with pandas --with numpy python code/replay_frozen.py --output-dir <tmp>
uv run --python 3.12 --with pandas --with numpy --with matplotlib python code/make_chart.py
```

## 结果

### Effective-rank W

- 发布指标重算最大绝对差：`7.532e-13`；
- 日收益最大绝对差：`9.975e-17`；
- bootstrap p值最大绝对差：`0.0124`；
- “有效秩全期点估计严格超越、统计确认不足”的裁决不变；
- 当前依赖环境不是发布时的逐字节环境，因此保留源提交的 CSV 字节，
  `metrics_rebased.csv` 与 `bootstrap_rebased.csv` 的发布哈希仍分别为
  `5fa7f3a9...` 和 `52ac5df4...`。

### Effective-rank + RISK_VIX

- `test_replay.py`：3/3 通过；
- 冻结回放摘要 SHA256：
  `00278bd98f8363db828598965ffb8c20490f38fe4e861028259f66e6b957905f`；
- 该摘要与包内 `logs/replay.log` 的哈希一致；
- 5bp 结果复现：`67.41% / 2.405 / -23.26% / 2.898`。

### W + global VIX

- `test_replay.py`：2/2 通过；
- 冻结回放摘要 SHA256：
  `63490a94e4804ad050ba46176ea5a3bed31a59bcf06c63119249cdb3de65450c`；
- 该摘要与包内 `logs/replay.log` 的哈希一致；
- 共同轴结果复现：`66.67% / 2.505 / -20.42% / 3.265`；
- `common_axis_nav_drawdown.png` 复现后 SHA256：
  `2e4b4069ccff3a0a6143d5330dccb0b335ae8e388fdc69254e3ce27b96c91944`。

## 归档与认证

- 两个带机器归档清单的包均通过逐文件 SHA256 校验；
- 全球VIX数据证书结构检查 `PASS`，声明状态为：
  `asof_available_at=PARTIAL`、`revision_vintage=BLOCKED`、
  `historical_membership=PARTIAL`、`mapping_taxonomy=PARTIAL`；
- 没有把结构检查通过解释为 PIT、生产可交易性或未来盈利通过。

## 边界

- 历史结果均已查看，不是独立 OOS；
- 全球VIX结果绑定精确数据父版本 `...-R20261116`，不是冻结 `v1` 原账本；
- 首个 2026-11-23 影子信号仅保存乘数，W生产源未接通，不生成前瞻净值；
- 三包均不授权生产变更。
