"""Generate the 36-month industry DeltaVIX beta and VIX percentile panel.

This script documents the upstream boundary of the published replay. It needs
the project's frozen industry panel and VIX close snapshot, which are not
redistributed with this package.
"""
from __future__ import annotations

import argparse
from pathlib import Path

import numpy as np
import pandas as pd


def load_industry_returns(path: Path) -> pd.DataFrame:
    panel = pd.read_parquet(path)
    panel["date"] = pd.to_datetime(panel["date"]).dt.tz_localize(None)
    returns = panel.pivot(index="date", columns="code", values="ret").sort_index()
    returns.columns = returns.columns.astype(str)
    return returns


def load_vix(path: Path) -> pd.Series:
    frame = pd.read_csv(path)
    frame["DATE"] = pd.to_datetime(frame["DATE"], format="%m/%d/%Y")
    return frame.set_index("DATE")["CLOSE"].astype(float).sort_index()


def month_end_dates(index: pd.DatetimeIndex) -> pd.DatetimeIndex:
    values = pd.Series(index, index=index)
    return pd.DatetimeIndex(values.groupby([index.year, index.month]).last())


def build_panels(
    industry_returns: pd.DataFrame,
    vix: pd.Series,
    signal_dates: pd.DatetimeIndex,
) -> tuple[pd.DataFrame, pd.DataFrame]:
    """Estimate beta on monthly returns through each signal month-end.

    VIX is mapped to the latest available A-share session and shifted one day,
    so the month-end signal does not use a later VIX close.
    """
    monthly = (
        (1.0 + industry_returns)
        .groupby(industry_returns.index.to_period("M"))
        .prod()
        - 1.0
    )
    vix_aligned = vix.reindex(industry_returns.index, method="ffill").shift(1)
    month_end = month_end_dates(industry_returns.index)
    vix_month = vix_aligned.reindex(month_end)
    vix_month.index = month_end.to_period("M")
    shock_monthly = vix_month.sort_index().diff()
    daily_state = vix_aligned.rolling(252, min_periods=120).rank(pct=True)

    rows: dict[pd.Timestamp, pd.Series] = {}
    for date in pd.DatetimeIndex(signal_dates):
        period = date.to_period("M")
        history = monthly.loc[:period].dropna(how="all").tail(36)
        shock = shock_monthly.reindex(history.index)
        valid = shock.notna()
        history = history.loc[valid]
        shock = shock.loc[valid]
        if len(history) < 36 or float(shock.var(ddof=0)) <= 0.0:
            rows[date] = pd.Series(np.nan, index=industry_returns.columns)
            continue
        centered = shock - shock.mean()
        beta = history.sub(history.mean()).mul(centered, axis=0).sum(axis=0)
        beta = beta / float(centered.pow(2).sum())
        rows[date] = beta.reindex(industry_returns.columns)

    beta_panel = pd.DataFrame.from_dict(rows, orient="index").sort_index()
    beta_panel.index.name = "date"
    state_panel = pd.DataFrame(
        {"state_rank_vix": daily_state.reindex(signal_dates)},
        index=pd.DatetimeIndex(signal_dates),
    )
    state_panel.index.name = "date"
    state_panel["direction_vix"] = np.select(
        [
            state_panel["state_rank_vix"].ge(0.80),
            state_panel["state_rank_vix"].le(0.20),
        ],
        [1.0, -1.0],
        default=0.0,
    )
    return beta_panel, state_panel


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--industry-panel", type=Path, required=True)
    parser.add_argument("--vix", type=Path, required=True)
    parser.add_argument("--holdings", type=Path, required=True)
    parser.add_argument("--end", default="2026-11-16")
    parser.add_argument(
        "--output-dir", type=Path, default=Path(__file__).resolve().parents[1] / "data"
    )
    args = parser.parse_args()

    returns = load_industry_returns(args.industry_panel)
    returns = returns.loc[: pd.Timestamp(args.end)]
    holdings = pd.read_csv(args.holdings, parse_dates=["T"])
    signal_dates = pd.DatetimeIndex(holdings["T"].sort_values().unique())
    beta_panel, state_panel = build_panels(
        returns,
        load_vix(args.vix),
        signal_dates,
    )
    args.output_dir.mkdir(parents=True, exist_ok=True)
    beta_panel.to_csv(
        args.output_dir / "industry_vix_beta.csv", float_format="%.17g"
    )
    state_panel.to_csv(
        args.output_dir / "industry_beta_state.csv", float_format="%.17g"
    )
    print(
        f"wrote {len(beta_panel)} signal rows x {len(beta_panel.columns)} industries"
    )


if __name__ == "__main__":
    main()
