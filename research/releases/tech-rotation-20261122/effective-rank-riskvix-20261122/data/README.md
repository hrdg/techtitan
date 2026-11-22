# 冻结输入说明

本目录是2026-11-16截止的最小研究账本，不包含供应商原始行情的全量副本。

| 文件 | SHA256 | 用途 |
|---|---|---|
| `branch_returns_5bp.csv` | `1a588fac0ecefb95dbcf3e3ab0654a908b4703f67eea2e53d8cecbc42a968bc6` | 5bp W/V2原始、守卫、同平均敞口匹配分支 |
| `branch_returns_10bp.csv` | `764e0919178c6aa6adf2ed79d2ee4423061644c455aec7fa77ab221fc5a91cc6` | 10bp分支换手压力 |
| `holdings_nofb_v20261116.csv` | `227d89c691c76209664cb68c4da84b40993fc189341e42302b667bb1a6887864` | 月末行业集合及ETF映射 |
| `monthly_selections.csv` | `018626ac3fdf3bc5fbafb2d4eb8e7257a9f00c9d765560672162071c733dbc9d` | 冻结月频选择表 |
| `industry_vix_beta.csv` | `776b0a450e2e6f9fb8195a3ec75318d963ba5819c7380b28900488afadb0d413` | 18行业36月β，85个月末 |
| `industry_beta_state.csv` | `03942336ae5b17af12fd156f0e2c6e24f1e876e3aee2271894b0145164b44f16` | VIX分位与方向状态，85个月末 |

## 时点

- 数据截止：2026-11-16；
- 最新完整月末：2026-10-30；
- 月末决策，下一交易日生效；
- VIX先映射到当时可获得的A股最近收盘，再shift一日；
- Beta窗口36个月，VIX分位252日；
- W/V2选择切换首日扣10bp。

## 成本

`branch_returns_5bp.csv`和`branch_returns_10bp.csv`已把分支内部换手成本计入
分支收益。`replay_frozen.py`随后再按冻结月度选择收取独立的10bp切换成本。
因此10bp实验是“分支换手10bp + W/V2切换10bp”，不是只对守卫增量计费。

## Beta面板边界

`industry_vix_beta.csv`和`industry_beta_state.csv`由
`code/generate_beta_panel.py`从冻结的18行业面板和VIX历史生成。这两个上游
原始文件不随仓库发布，但它们的来源和哈希记录在父研究的数据证书中。公开包可以：

1. 从已发布Beta面板重建`selected_beta_rank`与`guard`；
2. 从冻结分支收益重放选择器和绩效；
3. 重新计算bootstrap。

公开包不能仅凭这些文件重建供应商原始ETF成交账本。该缺口已明确标为边界，
不写成完整平台原生复现。

## 已知限制

- ETF历史成员、行业成员及供应商vintage为`PARTIAL`；
- 历史结果已经被查看，不是独立OOS；
- β采用18个A股科技行业，不是原文美国行业池；
- RISK_VIX是行业敏感性代理，不是原文组合的逐字复现。
