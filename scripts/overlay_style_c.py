"""在「组合 + ΔAR × TIP」上引入风格 C 信号与回撤闸，进一步压低最大回撤。

C 信号取自风格轮动项目的 CMS 三维：cms_crowding（+1 成长有利 / -1 价值有利 / 0 中性），
以及三维合计 breadth+crowding+macro。信号日收盘确认、次日生效。
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))
from tech_rotation import (  # noqa: E402
    PortfolioSpec, absorption_and_concentration, build_daily_weights, delta_zscore,
    metrics, nav_curve, portfolio_returns, relative_valuation, run_timing_overlay,
)

RAW = ROOT / "data" / "raw"
OUT = ROOT / "results"
CMS = Path("/Users/hsh/Documents/Quant/风格轮动/style-rotation/research/runs/"
           "v33_s2_backfill_2015_20261014/cms_dims_v1_2015.csv")
START, END, TH, COST = "2017-01-03", "2026-10-30", 1.5, 5e-4


def apply_dd_stop(eq: pd.Series, r: pd.Series, bond: pd.Series,
                  half: float = 0.10, flat: float = 0.15, release: float = 0.05) -> pd.Series:
    """以原始（未叠加闸的）影子净值做高水位触发与释放；用 t-1 收盘状态决定 t 日敞口。"""
    out = pd.Series(0.0, index=eq.index)
    nav, peak, state = 1.0, 1.0, 1.0
    for t in eq.index:
        e = float(eq.loc[t]) * state
        out.loc[t] = e
        # 影子净值：始终按未叠加回撤闸的敞口推进，用于下一日的状态判定
        e_raw = float(eq.loc[t])
        nav *= 1 + e_raw * float(r.loc[t]) + (1 - e_raw) * float(bond.loc[t])
        peak = max(peak, nav)
        dd = nav / peak - 1
        if dd <= -flat:
            state = 0.0
        elif dd <= -half:
            state = min(state, 0.5)
        elif dd >= -release:
            state = 1.0
    return out


def apply_dd_stop_ma(eq: pd.Series, r: pd.Series, bond: pd.Series, reentry: pd.Series,
                     trigger: float = 0.12) -> pd.Series:
    """实际净值回撤到 trigger 清仓；EW 指数回到 50 日均线上方再入场（t-1 信息）。"""
    out = pd.Series(0.0, index=eq.index)
    nav, peak, out_of_market = 1.0, 1.0, False
    for t in eq.index:
        e = 0.0 if out_of_market else float(eq.loc[t])
        out.loc[t] = e
        rr = e * float(r.loc[t]) + (1 - e) * float(bond.loc[t])
        nav *= 1 + rr
        peak = max(peak, nav)
        dd = nav / peak - 1
        if not out_of_market and dd <= -trigger:
            out_of_market = True
        elif out_of_market and bool(reentry.loc[t]):
            out_of_market = False
    return out


def main() -> None:
    df = pd.read_parquet(RAW / "industry_panel_latest.parquet")
    df["date"] = pd.to_datetime(df["date"]).dt.tz_localize(None)
    ret = df.pivot(index="date", columns="code", values="ret")
    pb = df.pivot(index="date", columns="code", values="pb")
    fmv = df.pivot(index="date", columns="code", values="float_mv")
    ar, conc = absorption_and_concentration(ret, fmv)
    dc, rv, d_ar = delta_zscore(conc), relative_valuation(pb), delta_zscore(ar)
    w = build_daily_weights(dc, rv, ret.index, PortfolioSpec(2, 4, "combined"), START, END)
    r = portfolio_returns(w, ret)
    r = r[r.index >= START]
    b = pd.read_parquet(RAW / "benchmark_csi_daily.parquet")
    b["date"] = pd.to_datetime(b["date"]).dt.tz_localize(None)
    bond = b[b["code"] == "H11006"].set_index("date")["close"].pct_change().reindex(r.index)
    _, st = run_timing_overlay(d_ar, r, bond, TH)
    st = st.clip(0, 1)

    tip = pd.read_parquet(RAW / "tip_daily.parquet")
    tip["date"] = pd.to_datetime(tip["date"])
    tp = tip.set_index("date")["close"].sort_index()
    tp.index = tp.index.astype("datetime64[ns]")
    score = pd.concat([tp / tp.shift(d) - 1 for d in (28, 84, 168, 364)], axis=1).mean(axis=1)
    g = pd.Series(np.where(score > 0, 1.0, 0.0), index=tp.index)
    g[score.isna()] = np.nan
    m = pd.merge_asof(pd.DataFrame({"date": r.index}), g.dropna().rename("tip").reset_index(),
                      on="date", direction="backward", allow_exact_matches=False).set_index("date")
    gate_tip = m["tip"].shift(1).reindex(r.index).fillna(0.0)

    cms = pd.read_csv(CMS)
    cms["date"] = pd.to_datetime(cms["date"])
    cms = cms.set_index("date").reindex(r.index).ffill().shift(1)
    c_crowd = cms["cms_crowding"].fillna(0.0)
    style_score = cms[["cms_breadth", "cms_crowding", "cms_macro"]].sum(axis=1).fillna(0.0)
    gate_c = pd.Series(np.where(c_crowd >= 0, 1.0, 0.0), index=r.index)      # 仅 C=-1 时清仓
    scale_c = pd.Series(np.where(c_crowd >= 0, 1.0, 0.5), index=r.index)     # C=-1 时半仓
    gate_style = pd.Series(np.where(style_score >= 0, 1.0, 0.0), index=r.index)

    # 针对 2021-03 那类"三信号都在场"的回撤，补测趋势与波动过滤
    ew = ret.mean(axis=1).reindex(r.index)
    level = (1 + ew.fillna(0)).cumprod()
    gate_ma50 = pd.Series(np.where(level > level.rolling(50).mean(), 1.0, 0.0), index=r.index).shift(1)
    gate_ma100 = pd.Series(np.where(level > level.rolling(100).mean(), 1.0, 0.0), index=r.index).shift(1)
    vol20 = r.rolling(20).std(ddof=1) * np.sqrt(250)
    gate_vol = pd.Series(np.where(vol20 < vol20.rolling(500).quantile(0.80), 1.0, 0.0), index=r.index).shift(1)

    base_eq = st * gate_tip
    rows, navs = [], {}
    def run(label: str, eq: pd.Series, stop: bool = False, stop_ma: float | None = None):
        eq = eq.reindex(r.index).fillna(0.0).clip(0, 1)
        if stop:
            eq = apply_dd_stop(eq, r.fillna(0.0), bond.fillna(0.0))
        if stop_ma is not None:
            eq = apply_dd_stop_ma(eq, r.fillna(0.0), bond.fillna(0.0),
                                  gate_ma50.fillna(0.0) > 0.5, trigger=stop_ma)
        rr = eq * r + (1 - eq) * bond
        rr = rr - COST * eq.diff().abs().fillna(0.0)
        m_ = metrics(rr.dropna())
        rows.append({"variant": label, "avg_equity": round(float(eq.mean()), 3),
                     "annual_return": round(m_["annual_return"], 4),
                     "annual_vol": round(m_["annual_vol"], 4), "sharpe": round(m_["sharpe"], 4),
                     "max_drawdown": round(m_["max_drawdown"], 4),
                     "calmar": round(m_["calmar"], 4),
                     "switches": int((eq.diff().abs() > 1e-9).sum())})
        navs[label] = nav_curve(rr.dropna())

    run("① 组合+ΔAR×TIP（基准）", base_eq)
    run("② +C闸（仅 C=-1 清仓）", base_eq * gate_c)
    run("③ +C半仓（C=-1 时半仓）", base_eq * scale_c)
    run("④ +三维合计<0 清仓", base_eq * gate_style)
    run("⑤ +回撤闸(10%半仓/15%清仓)", base_eq, stop=True)
    run("⑥ +C闸+回撤闸", base_eq * gate_c, stop=True)
    run("⑦ +C分档+回撤闸", base_eq * scale_c, stop=True)
    run("⑧ +EW指数50日均线", base_eq * gate_ma50.fillna(1.0))
    run("⑨ +EW指数100日均线", base_eq * gate_ma100.fillna(1.0))
    run("⑩ +20日波动过滤(>80分位则空仓)", base_eq * gate_vol.fillna(1.0))
    run("⑪ +50日均线+三维闸", base_eq * gate_ma50.fillna(1.0) * gate_style)
    run("⑫ +100日均线+三维闸", base_eq * gate_ma100.fillna(1.0) * gate_style)
    run("⑬ 回撤12%清仓·50日线上方再入", base_eq, stop_ma=0.12)
    run("⑭ 回撤15%清仓·50日线上方再入", base_eq, stop_ma=0.15)
    run("⑮ 敞口×70%（线性降风险）", base_eq * 0.7)
    t = pd.DataFrame(rows).sort_values("max_drawdown", ascending=False)
    t.to_csv(OUT / "style_c_overlay.csv", index=False)
    pd.DataFrame(navs).to_csv(OUT / "style_c_overlay_nav.csv")
    print(f"窗口 {START} ~ {END}｜C 非零占比 {(c_crowd != 0).mean():.1%}｜"
          f"C=-1 占比 {(c_crowd < 0).mean():.1%}")
    print(t.to_string(index=False))
    print("\nMDD 发生日:")
    for k, v in navs.items():
        dd = v / v.cummax() - 1
        print(f"  {k:<28} {dd.min():.2%} @ {dd.idxmin().date()}")
    (OUT / "style_c_overlay_summary.json").write_text(json.dumps({
        "window": [START, END],
        "c_signal": "CMS cms_crowding（+1 成长有利 / -1 价值有利 / 0 中性），次日生效",
        "results": t.to_dict(orient="records"),
    }, ensure_ascii=False, indent=2, default=float), encoding="utf-8")


if __name__ == "__main__":
    main()
