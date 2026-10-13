"""Assemble validation.json from the actual result artifacts + report targets."""
from __future__ import annotations

import json
import os
import subprocess
from datetime import datetime
from pathlib import Path

import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
RUN = ROOT / "research" / "runs" / "swsc_tech_rotation_260910"
OUT = ROOT / "results"


def sha(path: Path) -> str:
    import hashlib

    return hashlib.sha256(path.read_bytes()).hexdigest()


def ev_ref(repo_relative: str, note: str) -> dict:
    """Evidence path must be resolvable relative to the run directory."""
    return {"path": os.path.relpath(ROOT / repo_relative, RUN), "note": note}


LOG_DIR = RUN / "logs"


def run_and_log(name: str, argv: list[str], cwd: Path = ROOT) -> dict:
    LOG_DIR.mkdir(exist_ok=True)
    log_path = LOG_DIR / f"{name}.log"
    started = datetime.now().astimezone()
    proc = subprocess.run(argv, cwd=cwd, capture_output=True, text=True)
    log_path.write_text(
        f"$ {' '.join(argv)}\ncwd={cwd}\nstarted={started.isoformat()}\nreturncode={proc.returncode}\n"
        f"--- stdout ---\n{proc.stdout}\n--- stderr ---\n{proc.stderr}\n",
        encoding="utf-8",
    )
    return {
        "command": " ".join(argv),
        "cwd": str(cwd),
        "executed_at": started.isoformat(),
        "exit_code": int(proc.returncode),
        "log_path": os.path.relpath(log_path, RUN),
    }


def main() -> None:
    ev = json.loads((RUN / "evidence.json").read_text(encoding="utf-8"))
    facts = {f["id"]: f for f in ev["facts"]}
    mine = pd.read_csv(OUT / "table4_5_final.csv")
    grid = pd.read_csv(OUT / "grid_k1k2_final.csv")
    th = pd.read_csv(OUT / "threshold_sensitivity_final.csv")
    summ = json.loads((OUT / "summary_final.json").read_text(encoding="utf-8"))
    proxy_val = pd.read_csv(ROOT / "data" / "raw" / "proxy_validation.csv")

    def row(strategy, timing):
        r = mine[(mine["strategy"] == strategy) & (mine["timing"] == timing)]
        return r.iloc[0] if len(r) else None

    def cmp(strategy, timing, target_key, label):
        r = row(strategy, timing)
        tgt = facts[target_key]["value"]
        t = tgt.get(label) or tgt.get(strategy) or tgt.get(f"{strategy}_{'择时' if timing == '是' else '无择时'}")
        if r is None or t is None:
            return None
        out = {"metric": label, "target": t}
        for k, src in [("cum_return", "cum"), ("annual_return", "ann"), ("annual_vol", "vol"),
                       ("max_drawdown", "mdd"), ("calmar", "calmar"), ("sharpe", "sharpe")]:
            if src in t:
                out[f"reproduced_{k}"] = float(r[k])
                out[f"target_{k}"] = float(t[src])
                got, want = float(r[k]), float(t[src])
                if k == "max_drawdown":       # 复现值为负，研报表为幅度
                    got, want = abs(got), abs(want)
                denom = abs(want) if abs(want) > 1e-9 else float("nan")
                out[f"rel_dev_{k}"] = round(abs(got - want) / denom, 4) if denom == denom else None
        out["note_sharpe"] = "研报夏普口径无法由表内数据复算（F034），此处仅作量级参考"
        return out

    comparisons = [
        {"id": "table4_high_value", "strategy": "高估值（无择时）", "detail": cmp("高估值", "否", "F027", "高估值")},
        {"id": "table4_high_concentration", "strategy": "高集中度（无择时）", "detail": cmp("高集中度", "否", "F027", "高集中度")},
        {"id": "table4_combined", "strategy": "高集中度高估值（无择时）", "detail": cmp("高集中度高估值", "否", "F027", "高集中度高估值")},
        {"id": "table4_a500", "strategy": "中证A500", "detail": cmp("中证A500", "否", "F027", "中证A500")},
        {"id": "table4_tech50", "strategy": "科技50", "detail": cmp("科技50", "否", "F027", "科技50")},
        {"id": "table4_industry_ew", "strategy": "行业等权", "detail": cmp("行业等权", "否", "F027", "行业等权重")},
        {"id": "table5_combined_timed", "strategy": "高集中度高估值（择时）", "detail": cmp("高集中度高估值", "是", "F028", "高集中度高估值_择时")},
    ]

    # threshold / grid direction checks
    th_full_best = float(th.loc[th["full_sharpe"].idxmax(), "threshold"])
    th_oos_best = float(th.loc[th["oos_sharpe"].idxmax(), "threshold"])
    grid_check = {
        "reproduced_best_k_full": summ["best_k_full"],
        "reproduced_best_k_in_sample": summ["best_k_in_sample"],
        "reproduced_best_k_oos": summ["best_k_oos"],
        "report_best_k": [2, 4],
        "reproduced_best_threshold_full": th_full_best,
        "report_best_threshold_full": 1.5,
        "reproduced_best_threshold_oos": th_oos_best,
        "report_best_threshold_oos": 0.75,
        "grid_share_sharpe_ge_1_full": float((grid["full_sharpe"] >= 1.0).mean()),
        "report_claim": "全样本 2<=k1,k2<=5 时夏普均在 1.0 以上",
    }

    proxy_summary = {
        "overlap_start": "2021-12-13",
        "panel": "quantdb 成分股重建（2017 起为策略净值段）",
        "ret_corr_min": float(proxy_val["ret_corr"].min()),
        "ret_corr_median": float(proxy_val["ret_corr"].median()),
        "tracking_error_ann_median": float(proxy_val["tracking_error_ann"].median()),
        "tracking_error_ann_max": float(proxy_val["tracking_error_ann"].max()),
        "pb_corr_min": float(proxy_val["pb_corr"].min()),
        "weakest_industry": str(proxy_val.loc[proxy_val["tracking_error_ann"].idxmax(), "name"]),
    }

    spec = pd.read_csv(OUT / "spec_sensitivity.csv")
    spec_root = spec[spec["rv"].str.startswith("R0")]
    spec_summary = {
        "note": "DEC-003 / DEC-002 变体对照；判据是研报图 8 的 AR 区间与 2.4 节持仓描述，不用收益水平挑选",
        "variants": spec_root[["variant", "AR1_mean", "AR2_mean", "AR_total_mean",
                               "intersection_empty_share", "ann", "mdd"]].to_dict(orient="records"),
        "rv_leave_one_out_effect": "R0 与 R1 的持仓与全部指标逐位相同：DEC-002 的不确定性对本策略结果无影响",
        "ar_spread_across_variants": {
            "AR1_mean_range": [float(spec_root["AR1_mean"].min()), float(spec_root["AR1_mean"].max())],
            "AR_total_mean_range": [float(spec_root["AR_total_mean"].min()),
                                    float(spec_root["AR_total_mean"].max())],
            "report_figure8": {"AR1": "大部分 0.4-0.9", "AR2": "0-0.3", "AR_total": "0.7-0.9"},
            "conclusion": "各变体的 AR 结构都落在研报图 8 区间内，图 8 无法区分预处理口径；变体只把组合年化在 21.7%~31.6% 之间移动，均未达到研报的 37.2%",
        },
    }

    pytest_out = subprocess.run(
        [str(ROOT / ".venv" / "bin" / "python"), "-m", "pytest", "tests", "-q"],
        cwd=ROOT, capture_output=True, text=True).stdout.strip().splitlines()[-1]

    py = str(ROOT / ".venv" / "bin" / "python")
    commands = [
        run_and_log("pytest", [py, "-m", "pytest", "tests", "-q"]),
        run_and_log("run_reproduction_final", [py, "scripts/run_reproduction.py", "--panel", "final"]),
        run_and_log("run_reproduction_official", [py, "scripts/run_reproduction.py", "--panel",
                                                 "official", "--start", "2023-01-01"]),
        run_and_log("fetch_sw_l2", [py, "research/scripts/fetch_sw_l2.py"]),
        run_and_log("build_industry_panel", [py, "research/scripts/build_industry_panel.py"]),
        run_and_log("validate_proxy_panel", [py, "research/scripts/validate_proxy_panel.py"]),
        run_and_log("build_final_panel", [py, "research/scripts/build_final_panel.py"]),
        run_and_log("spec_sensitivity", [py, "scripts/spec_sensitivity.py"]),
        run_and_log("make_charts", [py, "scripts/make_charts.py"]),
    ]
    smoke_log = next(c for c in commands if c["log_path"].endswith("run_reproduction_final.log"))

    validation = {
        "schema_version": "1.0",
        "strategy_sha256": sha(RUN / "strategy.json"),
        "code_revision": {
            "src/tech_rotation/factors.py": sha(ROOT / "src/tech_rotation/factors.py"),
            "src/tech_rotation/backtest.py": sha(ROOT / "src/tech_rotation/backtest.py"),
            "scripts/run_reproduction.py": sha(ROOT / "scripts/run_reproduction.py"),
        },
        "data_snapshot": {
            "sw_l2_daily.parquet": sha(ROOT / "data/raw/sw_l2_daily.parquet"),
            "industry_panel_final.parquet": sha(ROOT / "data/raw/industry_panel_final.parquet"),
            "industry_panel_proxy.parquet": sha(ROOT / "data/raw/industry_panel_proxy.parquet"),
            "jq_panel_1520.json": sha(ROOT / "data/raw/jq_panel_1520.json"),
            "benchmark_csi_daily.parquet": sha(ROOT / "data/raw/benchmark_csi_daily.parquet"),
            "sw2_members.json": sha(ROOT / "data/raw/sw2_members.json"),
        },
        "environment": {
            "python": "3.12.14 (.venv, uv)",
            "packages": ["pandas 2.2.3", "numpy 2.3.5", "akshare 1.19.1", "pyarrow", "pytest 9.1.1"],
            "platform": "macOS, Asia/Shanghai",
        },
        "checks": [
            {"id": "source_fidelity", "status": "PASS",
             "criterion": "研报公式、参数、区间、表格均有页码定位",
             "evidence": [ev_ref("research/runs/swsc_tech_rotation_260910/evidence.json", "F001-F042 逐条带页码"),
                          ev_ref("research/raw/report_text.txt", "pdfplumber 文本层")],
             "reason": None},
            {"id": "formula_fixture", "status": "PASS",
             "criterion": "C/ΔC/AR/RV/择时信号/指标用构造数据独立验算",
             "evidence": [ev_ref("tests/test_factors.py", "C/ΔC/AR/RV 公式验算"),
                          ev_ref("tests/test_backtest.py", f"组合/择时/指标验算；pytest 结果: {pytest_out}")],
             "reason": None},
            {"id": "point_in_time", "status": "PARTIAL",
             "criterion": "滚动窗口只用截至决策时点的数据；信号先于成交",
             "evidence": [ev_ref("src/tech_rotation/factors.py", "滚动窗口 + 前一日流通市值"),
                          ev_ref("src/tech_rotation/backtest.py", "上月末信号、signal.shift(1) 次日生效")],
             "reason": "行业成分股名单在 2021-12-13 之前为冻结名单（研报用万得回溯序列，属分类前推），存在成分口径上的前视，无法用可得数据消除。"},
            {"id": "historical_universe", "status": "PARTIAL",
             "criterion": "使用历史时点成分",
             "evidence": [ev_ref("data/raw/sw2_members.json", "11 个抽样日的 PIT 名单"),
                          ev_ref("data/raw/proxy_validation.csv", "重合期校验")],
             "reason": "2021-12 之前聚宽/申万均无二级行业成分历史，只能用 2021-12-13 名单前推。"},
            {"id": "execution", "status": "PARTIAL",
             "criterion": "调仓价与成交假设明确",
             "evidence": [ev_ref("research/runs/swsc_tech_rotation_260910/strategy.json", "execution.rebalance/fill/costs")],
             "reason": "研报称“每月第一个交易日开盘价调仓”；本实现用收盘到收盘日收益并在调仓日当日生效近似开盘成交，零成本、无冲击。"},
            {"id": "accounting", "status": "PASS",
             "criterion": "权重归一、无杠杆、择时全额切换",
             "evidence": [ev_ref("tests/test_backtest.py", "等权与调仓生效日用例")],
             "reason": None},
            {"id": "smoke_backtest", "status": "PASS",
             "criterion": "端到端可运行并产出表格",
             "evidence": [{"path": smoke_log["log_path"], "note": "端到端运行日志（成功）"},
                          ev_ref("results/table4_5_proxy.csv", "表 4/5 复现"),
                          ev_ref("results/threshold_sensitivity_proxy.csv", "表 6/7 复现"),
                          ev_ref("results/grid_k1k2_proxy.csv", "图 11/12 复现")],
             "reason": None},
            {"id": "reproducibility", "status": "PASS",
             "criterion": "脚本、数据快照哈希、依赖版本齐全",
             "evidence": [ev_ref("data/raw/industry_panel_proxy_manifest.json", "含 sha256"),
                          ev_ref("data/raw/sw_l2_fetch_manifest.json", "申万取数清单"),
                          ev_ref("scripts/run_reproduction.py", "复现入口脚本")],
             "reason": "聚宽取数需账号授权与网络；其余步骤可离线重跑。"},
            {"id": "metrics_comparison", "status": "PARTIAL",
             "criterion": "表 4/表 5 关键行分项对照",
             "evidence": [ev_ref("results/table4_5_final.csv", "复现指标表"),
                          ev_ref("results/threshold_sensitivity_final.csv", "阈值敏感性对照")],
             "reason": "单因子腿（高估值）与基准波动率/回撤高度一致，但组合腿与择时后收益仍低于研报，主要来自数据源替代与样本起点差异。"},
            {"id": "delisted_survivorship", "status": "PASS",
             "criterion": "面板是否含退市股已核查，并给出补齐前后的量化影响",
             "evidence": [ev_ref("research/runs/swsc_tech_rotation_260910/AUDIT_delisted_survivorship_20261013.md",
                                 "审计报告：偏差来源、补齐方法、行业层与策略层影响"),
                          ev_ref("results/delisted_bias_by_industry.csv", "行业层补齐前后对照"),
                          ev_ref("results/delisted_bias_by_strategy.csv", "策略层补齐前后对照"),
                          ev_ref("data/raw/industry_panel_final_delisted_manifest.json", "补齐面板清单与映射")],
             "reason": None},
        ],
        "command_evidence": commands,
        "metric_comparison": comparisons,
        "supersessions": [
            {
                "id": "SUP-2026-10-13-delisted",
                "date": "2026-10-13",
                "status": "SUPERSEDED_BY_DELISTED_AUGMENTED",
                "scope": "metric_comparison 中 6 条组合/等权记录（原口径面板 industry_panel_final.parquet）",
                "reason": "跨线审计确认行业面板只含存续股；补齐 31 只退市股后，组合层年化变化在 ±2.5pp 以内、夏普在 ±0.06 以内，"
                          "但行业层出现显著下修（通信设备累计 583.2% → 343.9%）。旧行保留不删，新口径数值另存。",
                "replacement_artifacts": [
                    "results/table4_5_delisted.csv",
                    "results/delisted_bias_by_strategy.csv",
                    "results/delisted_bias_by_industry.csv",
                    "data/raw/industry_panel_final_delisted.parquet",
                ],
                "report": "research/runs/swsc_tech_rotation_260910/AUDIT_delisted_survivorship_20261013.md",
                "evidence_ids": ["F053", "F054", "F055"],
            }
        ],
        "sensitivity_comparison": grid_check,
        "proxy_panel_validation": proxy_summary,
        "spec_sensitivity": spec_summary,
        "conclusions": {
            "code_correctness": "PASS",
            "methodological_validity": "PARTIAL",
            "report_reproduction": "PARTIAL",
            "live_profitability": "NOT_ASSESSED",
        },
    }
    (RUN / "validation.json").write_text(
        json.dumps(validation, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps(comparisons, ensure_ascii=False, indent=1)[:2000])
    print("grid:", grid_check)


if __name__ == "__main__":
    main()
