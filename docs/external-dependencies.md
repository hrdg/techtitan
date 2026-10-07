# 外部依赖说明

本仓库有两类依赖：一类是可自助获取的公开数据（脚本已内置取数），另一类是**本地其它项目产出的
信号/净值文件，不随仓库分发**。所有受影响的脚本都把路径写成环境变量可覆盖的形式，默认值指向
本机原路径；缺文件时脚本会直接报错，不会静默降级。

## 1. 可自助获取（无需额外准备）

| 数据 | 获取方式 |
|---|---|
| 申万二级行业日度行情 / PB / 流通市值 | research/scripts/fetch_sw_l2.py（申万宏源官网） |
| 科技上游资源类行业 | research/scripts/fetch_sw_resource.py |
| 中证A500 / 科技50 / 中证国债 | research/scripts/fetch_index_csi.py（中证指数官网） |
| 上证国债指数 | research/scripts/fetch_index_csi.py（新浪） |
| 聚宽侧 2015-2016 暖机聚合 | research/scripts/jq_fetch_industry_panel.py、jq_fetch_2015_industry.py（需聚宽账号） |
| 申万 sw_l2 成分股名单 | research/scripts/jq_fetch_sw2_members.py、jq_fetch_resource_members.py（需聚宽账号） |

已随仓库附带的衍生数据（约 10MB）：data/raw/industry_panel_final*.parquet、三个成员名单 JSON、
聚宽聚合 JSON、基准与国债 parquet、以及各 *_manifest.json（含 sha256）。

## 2. 本地项目产出（不随仓库分发）

### 2.1 A016 目标敞口（来自「择时策略」项目）

- 需要文件：output/e247_lev_sig_daily.csv（列 date,hs300,zz500,zz1000,cyb,kc50,sz50,IC,IF,IM,IH）
- 环境变量：A016_SIG_CSV
- 口径要点（影响结果，务必一致）：
  - 敞口映射 exp = min(1.5, 3·s)⁺ + min(s, 0)（多头最高 1.5 倍、空头不杠杆），定义见该项目
    sentiment/execution/exposure_map.py；
  - **时序对齐用 shift(2)**（T 日收盘信号 → T+1 9:31 成交，close-to-close 收益需滞后两日，
    该项目 POS_SHIFT=2）。用 shift(1) 或当日对齐会引入前视；
  - IC 与 IM 逐日完全相同（同为 zz500/zz1000 系单层门控），IF 与 IH 亦然，实际只有两条独立腿。
- 受影响脚本：scripts/overlay_a016.py、combine_a016_dar.py、double_gate_check.py、
  leg01_decompose.py、tech_as_growth_leg.py、combine_tech_v33.py、run_universe_variant.py、
  run_theme_variant.py

### 2.2 风格轮动 v3.3（来自「风格轮动」项目）

- 需要文件：
  - 周频风格信号：research/runs/aw_equity_swap_20261006/v33_style_weekly.csv（列 signal_date,style，
    style=+1 成长 / -1 价值，2020-12-31 起周频）→ 环境变量 V33_STYLE_WEEKLY_CSV
  - 大小盘 ETF 版净值：research/runs/v33_size_etf_20261005/nav_platform.csv
    （列含 ungated / gated，其中 gated 为分腿 A016 口径）→ 环境变量 V33_NAV_CSV
  - ETF 复权价目录：local/data/etf_legs_20261005/（etf_159915.csv、etf_588000.csv、
    etf_512890.csv，列 close_adj）→ 环境变量 V33_ETF_LEGS_DIR
- 口径要点：v3.3 为 12 票等权（九因子 + CMS breadth/crowding/macro）周频方向；signal_date 为信号
  计算日，**次一交易日执行**；分腿 A016 为「持中证1000 用 exp_im、持沪深300 用 exp_if」。
- 受影响脚本：scripts/combine_tech_v33.py、tech_as_growth_leg.py、leg01_decompose.py、
  double_gate_check.py

### 2.3 本地数据湖 quantdb（仅用于重建行业面板）

- 需要路径：<quantdb>/1_kline_data/daily_unadjusted、5_technical_derived/valuation、
  3_financial_data/dividend_factors → 环境变量 QUANTDB_DIR
- 用途：research/scripts/build_industry_panel.py 用个股数据重建 10 个申万二级行业指数、行业 PB
  （整体法）与行业流通市值。
- 该数据湖不在本仓库内，因此**行业面板的重建无法由外部独立完成**；仓库直接附带重建结果
  data/raw/industry_panel_final*.parquet，策略本身可离线复现。

### 2.4 申万一级 / 主题变体的本地缓存（来自「行业轮动」项目）

- scripts/universe_transfer_test.py：<行业轮动>/data/raw/local_cache/sw_indices（申万一级指数 CSV）
  → 环境变量 SW_INDEX_CACHE_DIR
- scripts/run_theme_variant.py：.../local_cache/etf 与 timing17_etf_map/etf_industry_map.csv
  → 环境变量 SW_ETF_CACHE_DIR、SW_ETF_MAP_CSV

## 3. 研报原文

两份西南证券研报 PDF **不随仓库分发**（版权）。请自备 PDF 放在仓库根目录，然后用
research/scripts/extract_pdf.py 生成文本层。注意：research/runs/.../evidence.json 的
source_documents 记录了 PDF 的 sha256，缺少该 PDF 时 check_run.py 会报 D1 文件不存在——
这不影响任何策略代码的执行。
