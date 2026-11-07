"""参数网格：V2 归一化 ETF 执行版的 IS/OOS 稳定性。"""
from __future__ import annotations

import json
import os
import subprocess
import sys
import tempfile
from pathlib import Path

import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / "results" / "v2_normalized" / "grid_is_oos.csv"
K_GRID = ((2, 4), (3, 5), (4, 6))
STICKY_GRID = (0.0, 0.05, 0.10, 0.20)


def run_one(out_dir: Path, k1: int, k2: int, sticky: float, fallback: bool) -> dict:
    env = os.environ.copy()
    env.update({
        "OUT_DIR": str(out_dir),
        "K1": str(k1),
        "K2": str(k2),
        "STICKY": str(sticky),
        "FB": "1" if fallback else "0",
        "COST": "0.0005",
        "START": "2019-08-01",
        "END": "2026-07-31",
    })
    subprocess.run(
        [sys.executable, str(ROOT / "scripts/v2_etf_normalized_backtest.py")],
        cwd=ROOT,
        env=env,
        check=True,
        stdout=subprocess.DEVNULL,
    )
    suffix = "fb" if fallback else "nofb"
    summary = json.loads((out_dir / f"summary_{suffix}.json").read_text(encoding="utf-8"))
    return {
        "k1": k1,
        "k2": k2,
        "sticky": sticky,
        "fb": int(fallback),
        "is_sharpe": summary["2019-2023"]["sharpe"],
        "oos_sharpe": summary["2024-2026"]["sharpe"],
        "full": summary["full"]["sharpe"],
        "is_ann": summary["2019-2023"]["ann"],
        "oos_ann": summary["2024-2026"]["ann"],
    }


def main() -> None:
    rows = []
    with tempfile.TemporaryDirectory(prefix="tech_v2_sweep_") as tmp:
        out_dir = Path(tmp)
        for k1, k2 in K_GRID:
            for sticky in STICKY_GRID:
                for fallback in (False, True):
                    rows.append(run_one(out_dir, k1, k2, sticky, fallback))
    frame = pd.DataFrame(rows)
    frame.to_csv(OUT, index=False)
    print(frame.to_string(index=False))


if __name__ == "__main__":
    main()
