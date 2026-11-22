"""Rebase prior local W13612 exceedance candidates on the refreshed inputs."""
from __future__ import annotations

import json
from pathlib import Path

import numpy as np
import pandas as pd
from helpers import paired_bootstrap, performance

HERE = Path(__file__).resolve().parent
DATA = HERE.parent / "data"
OUT = HERE.parent / "outputs"
END = pd.Timestamp("2026-11-16")
SELECT_START = pd.Timestamp("2020-09-01")
PORT_START = pd.Timestamp("2019-08-01")
BASE_COST = 0.0005
SWITCH_COST = 0.001

def load_new_base_returns() -> pd.DataFrame:
    frame = pd.read_csv(
        DATA / "comparison_returns.csv", parse_dates=["date"]
    ).set_index("date").sort_index()
    required = [
        "W_CAUSAL_NEWDATA",
        "V2",
        "EFFECTIVE_RANK_HIGH_W",
    ]
    missing = [column for column in required if column not in frame]
    if missing:
        raise ValueError(f"missing refreshed base returns: {missing}")
    return frame.loc[:END]


def selector_returns(
    schedule: pd.DataFrame,
    base: pd.DataFrame,
    selector: str,
) -> pd.Series:
    selected = schedule.loc[
        schedule["selector"].eq(selector),
        ["month", "selected", "changed"],
    ].copy()
    selected["month"] = pd.PeriodIndex(selected["month"], freq="M")
    values = []
    for row in selected.itertuples(index=False):
        dates = base.index[base.index.to_period("M") == row.month]
        if dates.empty:
            continue
        source = "W_CAUSAL_NEWDATA" if row.selected == "W" else "V2"
        path = base.loc[dates, source].copy()
        if bool(row.changed) and len(path):
            path.iloc[0] -= SWITCH_COST
        values.append(path)
    if not values:
        raise ValueError(f"no return path for {selector}")
    return pd.concat(values).sort_index().rename(selector).loc[SELECT_START:END]


def floor_returns(
    v2_weight: float,
) -> tuple[pd.Series, pd.Series]:
    diagnostics = pd.read_csv(
        DATA / "voteonly_diagnostics.csv",
        parse_dates=["date"],
    ).set_index("date").sort_index().loc[:END]
    v2 = pd.read_csv(
        DATA / "nav_nofb_v20261116.csv",
        parse_dates=["date"],
    ).set_index("date").sort_index().loc[:END]
    frame = pd.DataFrame(
        {
            "W": diagnostics["return"].astype(float),
            "equity": diagnostics["equity_return"].astype(float),
            "bond": diagnostics["bond_return"].astype(float),
            "W_EXPOSURE": diagnostics["final_exposure"].astype(float),
            "V2_EXPOSURE": v2["exposure"].astype(float),
            "V2_NAV": v2["nav"].astype(float),
        }
    ).loc[PORT_START:END].dropna()
    trend = frame["V2_NAV"].shift(1) / frame["V2_NAV"].shift(64) - 1.0
    active_v2 = frame["V2_EXPOSURE"].where(trend.gt(0.0), 0.0)
    exposure = np.maximum(
        frame["W_EXPOSURE"], v2_weight * active_v2
    )
    extra = exposure - frame["W_EXPOSURE"]
    extra_turnover = 2.0 * extra.diff().abs()
    if len(extra_turnover):
        extra_turnover.iloc[0] = 2.0 * abs(float(extra.iloc[0]))
    result = (
        frame["W"]
        + extra * (frame["equity"] - frame["bond"])
        - BASE_COST * extra_turnover
    ).rename(f"FLOOR_{int(v2_weight * 100)}_TREND63")
    return result, exposure.rename(result.name)


def main() -> int:
    OUT.mkdir(exist_ok=True)
    base = load_new_base_returns()
    schedules = pd.read_csv(DATA / "monthly_selections.csv")

    avg_corr = selector_returns(schedules, base, "AVG_CORR_HIGH_V2")
    effective_rank = selector_returns(
        schedules, base, "EFFECTIVE_RANK_HIGH_W"
    )
    existing_er = base["EFFECTIVE_RANK_HIGH_W"].loc[SELECT_START:END]
    common = effective_rank.index.intersection(existing_er.index)
    effective_rank_check = float(
        (effective_rank.loc[common] - existing_er.loc[common]).abs().max()
    )

    floor50, exposure50 = floor_returns(0.50)
    floor25, exposure25 = floor_returns(0.25)
    portfolio = pd.DataFrame(
        {
            "W_CAUSAL_NEWDATA": base["W_CAUSAL_NEWDATA"],
            "V2_NEWDATA": base["V2"],
            "EFFECTIVE_RANK_HIGH_W": base["EFFECTIVE_RANK_HIGH_W"],
            "FLOOR_50_TREND63": floor50,
            "FLOOR_25_TREND63": floor25,
        }
    ).loc[PORT_START:END].dropna()
    selector = pd.DataFrame(
        {
            "W_CAUSAL_NEWDATA": base["W_CAUSAL_NEWDATA"],
            "V2_NEWDATA": base["V2"],
            "AVG_CORR_HIGH_V2": avg_corr,
            "EFFECTIVE_RANK_HIGH_W": effective_rank,
        }
    ).loc[SELECT_START:END].dropna()

    windows = {
        "selector_full": (SELECT_START, END),
        "selector_2020_2023": (SELECT_START, pd.Timestamp("2023-12-31")),
        "selector_2024_2026": (pd.Timestamp("2024-01-01"), END),
        "portfolio_full": (PORT_START, END),
        "portfolio_2019_2023": (PORT_START, pd.Timestamp("2023-12-31")),
        "portfolio_2024_2026": (pd.Timestamp("2024-01-01"), END),
        "selector_2026": (pd.Timestamp("2026-01-01"), END),
        "portfolio_2026": (pd.Timestamp("2026-01-01"), END),
    }
    rows = []
    for window, (start, end) in windows.items():
        frame = selector if window.startswith("selector_") else portfolio
        baseline_result = performance(
            frame["W_CAUSAL_NEWDATA"].loc[start:end]
        )
        baseline = frame["W_CAUSAL_NEWDATA"].loc[start:end]
        for arm in frame:
            result = performance(frame.loc[start:end, arm])
            strict_exceed = (
                result["cagr"] > baseline_result["cagr"]
                and result["sharpe"] > baseline_result["sharpe"]
                and result["mdd"] >= baseline_result["mdd"]
                and result["calmar"] > baseline_result["calmar"]
            )
            rows.append(
                {
                    "window": window,
                    "arm": arm,
                    "vs_W_strict_exceed": strict_exceed if arm != "W_CAUSAL_NEWDATA" else False,
                    **result,
                }
            )
    metrics = pd.DataFrame(rows)
    metrics.to_csv(OUT / "metrics_rebased.csv", index=False)
    selector.to_csv(OUT / "selector_returns_rebased.csv")
    portfolio.to_csv(OUT / "portfolio_returns_rebased.csv")
    pd.DataFrame(
        {
            "FLOOR_50_TREND63_EXPOSURE": exposure50,
            "FLOOR_25_TREND63_EXPOSURE": exposure25,
        }
    ).to_csv(OUT / "floor_exposures.csv")

    bootstrap_rows = []
    comparisons = {
        "AVG_CORR_HIGH_V2": (selector, "AVG_CORR_HIGH_V2", SELECT_START),
        "EFFECTIVE_RANK_SELECTOR": (
            selector,
            "EFFECTIVE_RANK_HIGH_W",
            SELECT_START,
        ),
        "EFFECTIVE_RANK_PORTFOLIO": (
            portfolio,
            "EFFECTIVE_RANK_HIGH_W",
            PORT_START,
        ),
        "FLOOR_50_TREND63": (
            portfolio,
            "FLOOR_50_TREND63",
            PORT_START,
        ),
        "FLOOR_25_TREND63": (
            portfolio,
            "FLOOR_25_TREND63",
            PORT_START,
        ),
    }
    for label, (frame, arm, start) in comparisons.items():
        for window_name, window_start, window_end in (
            ("full", start, END),
            ("2024_2026", pd.Timestamp("2024-01-01"), END),
            ("2026", pd.Timestamp("2026-01-01"), END),
        ):
            bootstrap_rows.append(
                {
                    "arm": label,
                    "window": window_name,
                    **paired_bootstrap(
                        frame.loc[window_start:window_end, arm],
                        frame.loc[
                            window_start:window_end, "W_CAUSAL_NEWDATA"
                        ],
                        20261122,
                    ),
                }
            )
    bootstrap = pd.DataFrame(bootstrap_rows)
    bootstrap.to_csv(OUT / "bootstrap_rebased.csv", index=False)

    index = metrics.set_index(["window", "arm"])
    summary = {
        "benchmark": "W_CAUSAL_NEWDATA",
        "effective_rank_existing_reproduction_max_abs_diff": effective_rank_check,
        "strict_exceeders": metrics.loc[
            metrics["vs_W_strict_exceed"], ["window", "arm"]
        ].to_dict(orient="records"),
        "full_selector": {
            arm: index.loc[("selector_full", arm)].to_dict()
            for arm in selector
        },
        "full_portfolio": {
            arm: index.loc[("portfolio_full", arm)].to_dict()
            for arm in portfolio
        },
        "recent_2026": metrics.loc[
            metrics["window"].isin(["selector_2026", "portfolio_2026"])
        ].to_dict(orient="records"),
        "status": "EXPLORATORY_NOT_OOS",
        "future_profitability": "NOT_ASSESSED",
    }
    (OUT / "summary.json").write_text(
        json.dumps(summary, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    print(
        metrics.query(
            "window in ['selector_full','portfolio_full',"
            "'selector_2026','portfolio_2026']"
        ).to_string(index=False)
    )
    print(bootstrap.to_string(index=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
