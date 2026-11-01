"""逐个加入三类新因子并验证（先声明假设，再看结果）。

H1 行业景气：营收增速的环比变化（加速）> 0 的行业，次月超额收益更高。
   数据：quantdb income/pershare_index 的 PIT 公告日 + 营收同比增速。
H2 盈利修正（代理）：净利润增速的环比变化（加速）> 0 的行业，次月超额收益更高。
   本地无分析师一致预期，用净利增速加速作为“正向修正”的代理。
H3 宏观流动性：M1-M2 剪刀差走阔 + 信用利差收窄 → 科技成长风险偏好上升；
   作为择时闸叠加在 ΔAR×TIP 之上（不是截面因子）。
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
QUANTDB = Path("/Users/hsh/quantmind/QuantMind_src/QuantMind-master/data/quantdb")
MACRO = Path("/Users/hsh/Documents/Quant/择时策略/data/macro")
CMS = Path("/Users/hsh/Documents/Quant/风格轮动/style-rotation/local/data/"
           "prepared_joinquant_20261001")
START, END, TH = "2017-01-03", "2026-10-30", 1.5


def load_fin(kind: str, syms: set[str], col: str) -> pd.DataFrame:
    rows = []
    for s in syms:
        p = QUANTDB / "3_financial_data" / kind / f"{s}.parquet"
        if not p.exists():
            continue
        d = pd.read_parquet(p)
        keep = ["m_timetag", "m_anntime", col]
        d = d[keep].dropna(subset=["m_anntime"])
        d["code"] = s
        rows.append(d)
    return pd.concat(rows, ignore_index=True)


def main() -> None:
    df = pd.read_parquet(RAW / "industry_panel_latest.parquet")
    df["date"] = pd.to_datetime(df["date"]).dt.tz_localize(None)
    ret = df.pivot(index="date", columns="code", values="ret")
    pb = df.pivot(index="date", columns="code", values="pb")
    fmv = df.pivot(index="date", columns="code", values="float_mv")
    codes = list(ret.columns)
    level = (1 + ret.fillna(0)).cumprod()
    ar, conc = absorption_and_concentration(ret, fmv)
    dc, rv, d_ar = delta_zscore(conc), relative_valuation(pb), delta_zscore(ar)
    b = pd.read_parquet(RAW / "benchmark_csi_daily.parquet")
    b["date"] = pd.to_datetime(b["date"]).dt.tz_localize(None)
    bond_all = b[b["code"] == "H11006"].set_index("date")["close"].pct_change()

    # 成员映射（聚宽 -> quantdb 后缀）
    mem = json.loads((RAW / "sw2_members.json").read_text(encoding="utf-8"))
    ind_members = {c: [s.replace(".XSHE", ".SZ").replace(".XSHG", ".SH") for s in v["union"]]
                   for c, v in mem["industries"].items()}
    all_syms = sorted({s for v in ind_members.values() for s in v})

    # 财务：营收增速与净利增速
    rev = load_fin("pershare_index", set(all_syms), "inc_revenue_rate")
    rev = rev.rename(columns={"inc_revenue_rate": "rev_yoy"})
    rev["m_timetag"] = pd.to_datetime(rev["m_timetag"], format="%Y%m%d", errors="coerce")
    rev["m_anntime"] = pd.to_datetime(rev["m_anntime"], format="%Y%m%d", errors="coerce")
    rev = rev.sort_values(["code", "m_timetag"])
    rev["rev_accel"] = rev.groupby("code")["rev_yoy"].diff()
    rev = rev.dropna(subset=["rev_accel", "m_anntime"])

    prof = load_fin("income", set(all_syms), "net_profit_excl_min_int_inc")
    prof["m_timetag"] = pd.to_datetime(prof["m_timetag"], format="%Y%m%d", errors="coerce")
    prof["m_anntime"] = pd.to_datetime(prof["m_anntime"], format="%Y%m%d", errors="coerce")
    prof = prof.sort_values(["code", "m_timetag"])
    # 净利增速 = 单季净利同比（用 net_profit_excl_min_int_inc 与其 4 期前比较）
    prof["np"] = prof["net_profit_excl_min_int_inc"]
    prof["np_yoy"] = prof.groupby("code")["np"].pct_change(4) * 100
    prof["prof_accel"] = prof.groupby("code")["np_yoy"].diff()
    prof = prof.dropna(subset=["prof_accel", "m_anntime"])

    s = pd.Series(ret.index, index=ret.index)
    me = pd.DatetimeIndex(s.groupby([ret.index.year, ret.index.month]).last().values)
    first = pd.DatetimeIndex(s.groupby([ret.index.year, ret.index.month]).first().values)
    me = me[(me >= pd.Timestamp(START)) & (me < pd.Timestamp(END))]

    def factor_panel(fin: pd.DataFrame, col: str) -> pd.DataFrame:
        out = pd.DataFrame(index=me, columns=codes, dtype=float)
        for T in me:
            sub = fin[fin["m_anntime"] <= T]
            if sub.empty:
                continue
            # 每只股票取最新公告
            latest = sub.sort_values("m_anntime").groupby("code").tail(1)
            for ind, members in ind_members.items():
                vals = latest[latest["code"].isin(members)][col]
                if len(vals) >= 3:
                    out.loc[T, ind] = vals.mean()
        return out

    rev_panel = factor_panel(rev, "rev_accel")
    prof_panel = factor_panel(prof, "prof_accel")

    # 宏观：M1-M2 剪刀差 + 信用利差
    money = pd.read_parquet(CMS / "macro_money.parquet")
    money["stat_month"] = pd.to_datetime(money["stat_month"])
    money = money.set_index("stat_month").sort_index()
    scissors = (money["m1_yoy"] - money["m2_yoy"]).rename("scissors")
    scissors_lag = scissors.shift(1)                     # 次月才可得
    spy = pd.read_csv(MACRO / "bond_aaa_note_yield.csv", parse_dates=["date"]).set_index("date")
    spread = spy["spread"].astype(float)

    # 截面秩相关（正交性检查）
    common = dc.dropna(how="all").index
    corr_rev = dc.loc[common].corrwith(rev_panel.reindex(common), axis=1).mean()
    corr_prof = dc.loc[common].corrwith(prof_panel.reindex(common), axis=1).mean()
    corr_rev_rv = rv.loc[common].corrwith(rev_panel.reindex(common), axis=1).mean()
    print(f"与 ΔC 的截面相关：景气 {corr_rev:+.2f}、盈利修正 {corr_prof:+.2f}；"
          f"RV 与景气 {corr_rev_rv:+.2f}")

    vol20 = ret.rolling(20).std(ddof=1) * np.sqrt(250)
    tip = pd.read_parquet(RAW / "tip_daily.parquet")
    tip["date"] = pd.to_datetime(tip["date"])
    tp = tip.set_index("date")["close"].sort_index()
    tp.index = tp.index.astype("datetime64[ns]")
    tsc = pd.concat([tp / tp.shift(d) - 1 for d in (28, 84, 168, 364)], axis=1).mean(axis=1)
    tg = pd.Series(np.where(tsc > 0, 1.0, 0.0), index=tp.index)
    tg[tsc.isna()] = np.nan
    mt = pd.merge_asof(pd.DataFrame({"date": ret.index}), tg.dropna().rename("tip").reset_index(),
                       on="date", direction="backward", allow_exact_matches=False).set_index("date")
    tip_gate = mt["tip"].shift(1).reindex(ret.index).fillna(0.0)

    def sel(T, panels):
        d, r = dc.loc[T].dropna(), rv.loc[T].dropna()
        base = set(d.nlargest(4).index) & set(r.nlargest(2).index)
        for pnl in panels:
            x = pnl.loc[T].dropna()
            if len(x) >= 3:
                base &= set(x.nlargest(4).index)
        return sorted(base)

    def weights(panels):
        w = pd.DataFrame(0.0, index=ret.index, columns=codes)
        cur = []
        for d in first:
            prior = me[me < d]
            if not len(prior):
                continue
            sx = sel(prior[-1], panels)
            if sx:
                cur = sx
            if cur:
                w.loc[d:] = 0.0
                w.loc[d:, cur] = 1.0 / len(cur)
        return w

    # 宏观择时：剪刀差 3 个月变化 > 0（信用利差条件另列对照）
    sc3 = scissors_lag.diff(3)
    sc_daily = sc3.reindex(ret.index, method="ffill")
    sp_chg = spread.diff(20).reindex(ret.index, method="ffill")
    macro_gate = pd.Series(
        np.where(sc_daily > 0, 1.0, 0.0), index=ret.index).shift(1).fillna(0.0)
    spread_gate = pd.Series(
        np.where(sp_chg < 0, 1.0, 0.0), index=ret.index).shift(1).fillna(0.0)
    macro_both = pd.Series(
        np.where((sc_daily > 0) & (sp_chg < 0), 1.0, 0.0), index=ret.index).shift(1).fillna(0.0)
    print(f"剪刀差闸开启占比 {macro_gate.mean():.1%}；信用利差闸 {spread_gate.mean():.1%}；"
          f"两者同时 {macro_both.mean():.1%}")

    rows, navs = [], {}
    cases = [
        ("① 基准 ΔC∩RV", [], False),
        ("② +景气(营收加速)", [rev_panel], False),
        ("③ +盈利修正(净利加速)", [prof_panel], False),
        ("④ +景气+盈利修正", [rev_panel, prof_panel], False),
        ("⑤ 基准 + 剪刀差闸", [], "sc"),
        ("⑥ 基准 + 信用利差闸（对照）", [], "sp"),
        ("⑦ +景气 + 剪刀差闸", [rev_panel], "sc"),
        ("⑧ 基准 + 两者同时", [], "both"),
    ]
    for label, panels, use_macro in cases:
        w = weights(panels)
        r = portfolio_returns(w, ret)
        r = r[r.index >= START]
        bass = bond_all.reindex(r.index)
        st = run_timing_overlay(d_ar, r, bass, TH)[1].clip(0, 1)
        eq = st * tip_gate.reindex(r.index).fillna(0.0)
        if use_macro == "sc":
            eq = eq * macro_gate.reindex(r.index)
        elif use_macro == "sp":
            eq = eq * spread_gate.reindex(r.index)
        elif use_macro == "both":
            eq = eq * macro_both.reindex(r.index)
        rr = eq * r + (1 - eq) * bass
        m = metrics(rr.dropna())
        rows.append({"variant": label, "annual_return": round(m["annual_return"], 4),
                     "annual_vol": round(m["annual_vol"], 4), "sharpe": round(m["sharpe"], 4),
                     "max_drawdown": round(m["max_drawdown"], 4), "calmar": round(m["calmar"], 4)})
        navs[label] = nav_curve(rr.dropna())
    t = pd.DataFrame(rows).sort_values("sharpe", ascending=False)
    t.to_csv(OUT / "fundamental_macro_comparison.csv", index=False)
    pd.DataFrame(navs).to_csv(OUT / "fundamental_macro_nav.csv")
    print(t.to_string(index=False))
    (OUT / "fundamental_macro_summary.json").write_text(json.dumps({
        "window": [START, END], "results": t.to_dict(orient="records"),
        "hypotheses": {"H1": "营收增速加速的行业次月超额更高",
                       "H2": "净利增速加速（盈利修正代理）的行业次月超额更高",
                       "H3": "M1-M2 剪刀差走阔且信用利差收窄时风险偏好上升"},
        "corr_with_dc": {"rev_accel": round(float(corr_rev), 3), "prof_accel": round(float(corr_prof), 3)},
        "macro_gate_share": round(float(macro_gate.mean()), 3),
        "note": "本地无分析师一致预期，H2 用净利增速加速代理；宏观闸只用已公布月份",
    }, ensure_ascii=False, indent=2, default=float), encoding="utf-8")


if __name__ == "__main__":
    main()
