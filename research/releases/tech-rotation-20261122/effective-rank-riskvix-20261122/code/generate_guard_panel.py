"""Rebuild RISK_VIX monthly diagnostics from the published frozen panels."""
from __future__ import annotations

import argparse
import ast
from pathlib import Path

import numpy as np
import pandas as pd


ROOT = Path(__file__).resolve().parents[1]


def selected_codes(value: object) -> list[str]:
    if isinstance(value, str):
        return [str(code) for code in ast.literal_eval(value)]
    if isinstance(value, (list, tuple)):
        return [str(code) for code in value]
    raise TypeError(f"unsupported selected value: {type(value)!r}")


def build_guard_panel(
    holdings: pd.DataFrame,
    industry_beta: pd.DataFrame,
    beta_state: pd.DataFrame,
) -> pd.DataFrame:
    holdings = holdings.copy()
    holdings["T"] = pd.to_datetime(holdings["T"])
    industry_beta = industry_beta.copy()
    industry_beta.index = pd.to_datetime(industry_beta.iloc[:, 0])
    industry_beta = industry_beta.iloc[:, 1:].sort_index()
    beta_state = beta_state.copy()
    beta_state.index = pd.to_datetime(beta_state.iloc[:, 0])
    beta_state = beta_state.iloc[:, 1:].sort_index()

    rows: list[dict[str, object]] = []
    for row in holdings.sort_values("T").itertuples(index=False):
        date = pd.Timestamp(row.T)
        if date not in industry_beta.index or date not in beta_state.index:
            raise ValueError(f"missing beta/state input on {date.date()}")
        selected = selected_codes(row.selected)
        beta_rank = industry_beta.loc[date].rank(pct=True)
        selected_rank = float(beta_rank.reindex(selected).dropna().mean())
        state_rank = float(beta_state.at[date, "state_rank_vix"])
        guard = (
            0.5
            if np.isfinite(state_rank)
            and state_rank >= 0.80
            and np.isfinite(selected_rank)
            and selected_rank <= 0.5
            else 1.0
        )
        rows.append(
            {
                "date": date,
                "selected": ",".join(selected),
                "state_rank": state_rank,
                "selected_beta_rank": selected_rank,
                "guard": guard,
            }
        )
    return pd.DataFrame(rows)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--output",
        type=Path,
        default=ROOT / "outputs" / "guard_diagnostics_replayed.csv",
    )
    args = parser.parse_args()
    panel = build_guard_panel(
        pd.read_csv(ROOT / "data" / "holdings_nofb_v20261116.csv"),
        pd.read_csv(ROOT / "data" / "industry_vix_beta.csv"),
        pd.read_csv(ROOT / "data" / "industry_beta_state.csv"),
    )
    args.output.parent.mkdir(parents=True, exist_ok=True)
    panel.to_csv(args.output, index=False, float_format="%.17g")
    published = pd.read_csv(ROOT / "outputs" / "guard_diagnostics.csv")
    check = panel.copy()
    check["date"] = pd.to_datetime(check["date"])
    published["date"] = pd.to_datetime(published["date"])
    maximum_difference = float(
        (
            check[["state_rank", "selected_beta_rank", "guard"]]
            - published[["state_rank", "selected_beta_rank", "guard"]]
        )
        .abs()
        .max()
        .max()
    )
    if not check["selected"].equals(published["selected"]):
        raise AssertionError("selected-industry replay differs from diagnostics")
    if maximum_difference > 1e-12:
        raise AssertionError(f"guard replay mismatch: {maximum_difference}")
    print(f"guard diagnostics reproduced; max_abs_diff={maximum_difference:.3e}")


if __name__ == "__main__":
    main()
