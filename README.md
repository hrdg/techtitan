# techtitan

西南证券《因子选股系列：科技成长景气轮动与量化择时模型》(2026-09-10) 的复现与研究扩展。

策略骨架：10 个申万二级科技成长行业内部的截面轮动 —— PCA 集中度变化量 ΔC + 相对估值 RV 双因子选行业，
再用吸收比率变化量 ΔAR 做系统性风险择时（预警期全仓国债指数）。复现区间 2017-01-03 ~ 2026-07-31。

规格与验收：design.md（可读规格视图）、research/runs/swsc_tech_rotation_260910/（evidence / strategy /
validation / logs）。**这是一个部分复现**，与原文的差距、原因与限制都写在 design.md 第 6-7 节。

## 快速开始

        uv venv --python 3.12 .venv
        uv pip install --python .venv/bin/python akshare pyarrow pytest matplotlib

        # 1) 取数（申万宏源官网 + 中证指数官网）
        .venv/bin/python research/scripts/fetch_sw_l2.py
        .venv/bin/python research/scripts/fetch_index_csi.py

        # 2) 行业面板（仓库已附带重建结果，重跑需本地 quantdb，见 docs/external-dependencies.md）
        .venv/bin/python research/scripts/build_industry_panel.py
        .venv/bin/python research/scripts/build_final_panel.py
        .venv/bin/python research/scripts/validate_proxy_panel.py

        # 3) 回测、验收、图表
        .venv/bin/python scripts/run_reproduction.py --panel final
        .venv/bin/python -m pytest tests -q
        .venv/bin/python scripts/make_validation.py
        .venv/bin/python scripts/make_charts.py

## 目录

    src/tech_rotation/     因子（PCA 集中度 ΔC / 吸收比率 AR / 相对估值 RV）、组合、择时、指标
    tests/                 公式与口径用例（25 个）
    scripts/               复现入口与扩展实验
    research/runs/         证据 / 冻结规格 / 验收记录 / 命令日志
    research/scripts/      取数与面板构建
    data/raw/              面板与基准数据 + 各 *_manifest.json（含 sha256）
    results/               指标表、敏感性、净值、图表
    docs/                  外部依赖说明

## 三梯队内容

### 第一梯队：复现基座

- 因子与组合：src/tech_rotation/factors.py、backtest.py
- 数据层：申万官方取数 + 聚宽 2015-2016 暖机 + 成分股重建面板（申万 2021 版二级行业指数在
  官方 / 聚宽 / qlib / quantdb 四处都只有 2021-12-13 起的数据，这是本次最主要的工程问题）
- 验收：research/runs/swsc_tech_rotation_260910/validation.json（分项对照表 4-表 7）

复现结果（代理面板，2017-01-03 ~ 2026-07-31）：

| 组合 | 复现年化 | 研报年化 | 复现最大回撤 | 研报最大回撤 |
|---|---|---|---|---|
| 高估值（无择时） | 23.38% | 25.24% | -54.19% | -54.47% |
| 高集中度（无择时） | 16.33% | 14.29% | -42.72% | -50.82% |
| 高集中度高估值（无择时） | 28.90% | 37.23% | -48.88% | -54.90% |
| 高集中度高估值（叠 ΔAR 1.5） | 31.51% | 47.82% | -34.10% | -32.74% |
| 中证A500 | 4.41% | 4.83% | -44.30% | -44.30% |
| 科技50 | 10.67% | 11.95% | -63.05% | -63.05% |

已对齐：单因子腿的量级、基准的波动率与最大回撤、持仓路径（2020-2021 光伏设备+电池、2023 通信设备+
IT服务、2024H2 消费电子/通信设备/半导体）、ΔAR 预警区间、样本外夏普 2.27 vs 2.25。
未对齐：组合腿与择时后收益偏低 16%-34%，归因见下。

### 第二梯队：A016 择时、剖面迁移与两个负结果

**A016 叠加**（scripts/overlay_a016.py、combine_a016_dar.py、double_gate_check.py）

| 配置 | 平均股票权重 | 年化 | 夏普 | 最大回撤 | Calmar |
|---|---|---|---|---|---|
| 组合 + ΔAR(1.5)（研报原生） | 0.72 | 31.4% | 0.97 | -34.1% | 0.92 |
| 组合 + A016(IC)（含万五成本） | 0.22 | 25.8% | 1.58 | -19.6% | 1.32 |
| 组合 + A016(IC) + ΔAR 软闸 | 0.20 | 23.0% | 1.49 | -17.1% | 1.34 |

关键事实：A016 有 52% 的交易日空仓、多头最高 1.5 倍杠杆，且 IC 与 IM 逐日相同、IF 与 IH 逐日相同
（只有两条独立腿），因此「同一个敞口乘两次」不等于双闸。ΔAR 独占的 885 天是**负超额**
（日均 +0.063% vs 全样本 +0.131%），这是 ΔAR 与 A016 结合时的主要结论。

**横截面迁移**（scripts/universe_transfer_test.py、run_universe_variant.py、run_theme_variant.py）

ΔAR 的阈值能跨截面规模迁移（10 资产与 27 资产的 1.5 触发率都在 8%-11%、约 90 分位），但 AR 水平
不能（0.83 → 0.72）。申万一级 27 行业等权加该闸：年化 1.37% → 7.09%、回撤 -36.8% → -19.9%。
主题横截面缺可信的行业级 PB/流通市值，只能做单因子（ΔC）版本。

**两个负结果**

- 拥挤度（scripts/crowding_overlay.py）：8 个结构变体 + 6 个变化量变体全部未能提高夏普。拥挤度与
  ΔAR 相关性只有 -0.006，不是冗余，而是与「在热点中选最强」的 alpha 相冲。副产品：用成分股重建的
  板块成交额占比复现了研报图 1（2026-07-10 峰值 46.1% vs 研报 46.5%）。
- 资源类（scripts/universe_15_test.py、resource_satellite_test.py）：把科技上游资源行业并入选行业池
  会显著变差（夏普 0.97 → 0.53-0.81）；但作为 20%-30% 固定比例卫星仓则单调改善（夏普 → 1.20-1.31）。

### 第三梯队：跨策略组合（依赖外部项目产出，见 docs/external-dependencies.md）

- scripts/tech_as_growth_leg.py：把科技池接进风格轮动 v3.3 当成长腿（价值腿 512890），
  再叠分腿 A016。科技池成长腿明显优于通用成长 ETF 载体。
- scripts/combine_tech_v33.py、leg01_decompose.py、double_gate_check.py：并列袖子与分层拆解。
- scripts/etf_weekly_holdings.py：周频 ETF 持仓只数（1-2 只，含 ETF 映射缺口说明）。

## 已知限制（务必与结果一起读）

- 研报原始数据源为万得，本机不可达；5 条申万 2021 版二级行业指数缺 2015-2021 历史，用成分股重建，
  重合期日收益相关性 0.968-0.997、年化跟踪误差中位 3.7%（消费电子最弱 9.4%）。
- 组合腿与择时后收益低于研报 16%-34%；归因显示不是因子口径选择造成的（PCA 预处理五个变体的
  AR 结构都落在研报图 8 区间内，只把组合年化在 21.7%-31.6% 间移动）。
- 零成本、零冲击；调仓按「每月首个交易日开盘价」的定义用收盘到收盘收益近似。
- 成分股名单在 2021-12-13 之前为冻结名单（分类前推），存在分类前视，无法用可得数据消除。
- 扩展实验均在单段历史上做过多次比较，存在选择偏差；涉及 A016 与 v3.3 的部分，两套信号本身也在
  重叠历史上开发过，不构成独立样本外验证。
- check_run.py 的 audit gate 仍为 BLOCKED（point_in_time / historical_universe / execution /
  metrics_comparison 四项如实标为 PARTIAL）。

所有结论为费前历史模拟，不构成投资建议。
