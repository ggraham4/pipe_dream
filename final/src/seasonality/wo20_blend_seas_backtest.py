"""
WO-20 3' (2026-09-27, Gabe: "Yes the blend should get the seasonality"):
before/after backtest of the Today's Picks blend, the 9-factor frozen
equal-weight composite leg (previous) vs the same + seas as a 10th
equal-weight factor (new). Port of reset2026/blend_q75.py's harness
(q75 score cache, cap2000, 50/50 rank_z blend, decile_volq, net 15bp,
gross_return_40, SPY), with these changes:

  * PRE-2020 ONLY: q75 timepoints >= 2020-01-01 are dropped and the panel is
    read with date <= 2019-12-31; asserted. (The late-2019 windows' 40-day
    outcomes end in early 2020, the same convention WO-18 used.)
  * The composite legs are current_signal_blend.py's OWN frozen functions
    (_compute_composite_frozen, _compute_composite_frozen_v10_seas), not
    composite.compute_composite (which is 8 factors since 2026-09-22).
  * Two panels:
      v2c  composite_panel_v2 + the column-c universe rule applied before
           rank_z (what the LIVE blend's composite leg reads since WO-11)
           -- PRIMARY
      v1   composite_panel.parquet, the harness's original panel (rebuilt by
           Retrain ALL since 2026-09-19), reported as an anchor to the
           original "nominate_only" +2.52%/yr
    seas comes from WO-18's seas_factor_v2.parquet (ticker, date); a v1 row
    absent from it gets NaN (counted in the report).
  * No shuffle null (not asked for).

SINGLE GRID: q75's cache has ONE cadence (offset 0, ~60 calendar days), so
every number here is one grid, not a 40-offset average.

Output: final/out/seasonality/wo20_blend_seas_backtest.json
"""
import importlib.util
import json
import sys
from pathlib import Path

import numpy as np
import pandas as pd

HERE = Path(__file__).resolve().parent
SRC = HERE.parent
sys.path.insert(0, str(SRC / "reset2026"))
import blend_q75 as BQ  # noqa: E402  (turnover_net, COST_BPS, Q75_SCORES)
import composite as C  # noqa: E402
import working_panel as W  # noqa: E402

spec = importlib.util.spec_from_file_location("csb_wt", SRC / "current_signal_blend.py")
CSB = importlib.util.module_from_spec(spec)
spec.loader.exec_module(CSB)

HOLDOUT = pd.Timestamp("2020-01-01")
POST = pd.Timestamp("2011-10-01")
TIER = "cap2000"
SEAS_FILE = HERE.parent.parent / "out" / "seasonality" / "seas_factor_v2.parquet"
OUT = HERE.parent.parent / "out" / "seasonality" / "wo20_blend_seas_backtest.json"
ANN = 252.0 / C.HORIZON


def _in_dates(path, dates):
    """parquet 'in' filter matching the file's date column type (string or timestamp)."""
    import pyarrow.parquet as pq
    t = pq.read_schema(path).field("date").type
    vals = [d.date().isoformat() for d in dates] if "string" in str(t) else [d.to_pydatetime() for d in dates]
    return [("date", "in", vals)]


def load(panel_name):
    path = {"v2c": W.WORKING_PANEL, "v1": W.V1_PANEL}[panel_name]
    outc = {"v2c": W.WORKING_OUTCOME, "v1": W.R26 / "outcome_cache.parquet"}[panel_name]
    cols = list(dict.fromkeys(["ticker", "date", "sector", "volatility_60", f"eligible_{TIER}"]
                              + CSB._ORIGINAL_FACTOR_COLS))
    q75 = pd.read_parquet(BQ.Q75_SCORES, columns=["timepoint", "ticker", "score"])
    q75["timepoint"] = pd.to_datetime(q75["timepoint"]); q75["ticker"] = q75["ticker"].astype(str)
    q75 = q75[q75["timepoint"] < HOLDOUT]
    dates = sorted(q75["timepoint"].unique())
    dates = [pd.Timestamp(d) for d in dates]
    p = pd.read_parquet(path, columns=cols, filters=_in_dates(path, dates))
    p["date"] = pd.to_datetime(p["date"]); p["ticker"] = p["ticker"].astype(str)
    assert p["date"].max() < HOLDOUT and max(dates) < HOLDOUT, "HOLD-OUT BREACH"
    info = {"panel": path.name, "timepoints": len(dates), "first": str(pd.Timestamp(dates[0]).date()),
            "last": str(pd.Timestamp(dates[-1]).date())}
    if panel_name == "v2c":
        keep = W.universe_keep(p["ticker"])
        info["rows_dropped_spac_rule"] = int((~keep).sum())
        p = p[keep]
    o = pd.read_parquet(outc, columns=["ticker", "date", "gross_return_40"], filters=_in_dates(outc, dates))
    o["date"] = pd.to_datetime(o["date"]); o["ticker"] = o["ticker"].astype(str)
    spy = o[o["ticker"] == "SPY"].set_index("date")["gross_return_40"].to_dict()
    p = p.merge(o[~o["ticker"].isin(["SPY", "USMV"])], on=["ticker", "date"], how="left")
    s = pd.read_parquet(SEAS_FILE, columns=["ticker", "date", "seas"], filters=_in_dates(SEAS_FILE, dates))
    s["date"] = pd.to_datetime(s["date"]); s["ticker"] = s["ticker"].astype(str)
    n = len(p)
    p = p.merge(s, on=["ticker", "date"], how="left", indicator=True)
    assert len(p) == n
    e = p[f"eligible_{TIER}"].astype(bool)
    info["eligible_rows"] = int(e.sum())
    info["eligible_rows_absent_from_seas_file"] = int((e & (p["_merge"] != "both")).sum())
    info["seas_coverage_eligible"] = float(p.loc[e, "seas"].notna().mean())
    p = p.drop(columns="_merge")
    q75_by = {d: g.set_index("ticker")["score"] for d, g in q75.groupby("timepoint")}
    return p, dates, q75_by, spy, info


def run(p, dates, q75_by, spy):
    recs = {"q75": [], "blend_prev9": [], "blend_seas10": [], "comp_prev9": [], "comp_seas10": []}
    prev = {k: set() for k in recs}
    picks_by = {k: {} for k in recs}
    by_date = dict(tuple(p.groupby("date")))
    for tp in dates:
        g = by_date.get(tp)
        if g is None:
            continue
        elig = g[g[f"eligible_{TIER}"].astype(bool)].reset_index(drop=True)
        if len(elig) < 20 or tp not in q75_by:
            continue
        ret = dict(zip(elig["ticker"], elig["gross_return_40"]))
        qv = pd.Series(elig["ticker"].map(q75_by[tp]).to_numpy(np.float64), index=elig.index)
        c9 = CSB._compute_composite_frozen(elig)["composite"]
        c10 = CSB._compute_composite_frozen_v10_seas(elig)["composite"]
        qr = C.rank_z(qv)

        def blend(c):
            cr = C.rank_z(c)
            b = pd.concat([cr, qr], axis=1).mean(axis=1, skipna=True)
            b[cr.isna() & qr.isna()] = np.nan
            return b
        for key, sc in (("q75", qv), ("comp_prev9", c9), ("comp_seas10", c10),
                        ("blend_prev9", blend(c9)), ("blend_seas10", blend(c10))):
            fr = pd.DataFrame({"ticker": elig["ticker"].to_numpy(), "composite": sc.to_numpy()})
            pk = C.pick_decile_volq(elig, fr)
            pk = [(t, w) for t, w in pk if pd.notna(ret.get(t))]
            if not pk:
                continue
            ws = sum(w for _, w in pk)
            gross = sum((w / ws) * (1.0 + ret[t]) for t, w in pk) - 1.0
            cur = {t for t, _ in pk}
            f_new = len(cur - prev[key]) / len(cur)
            prev[key] = cur
            picks_by[key][tp] = dict(pk)
            recs[key].append({"date": tp, "gross": gross, "f_new": f_new, "spy": spy.get(tp, np.nan)})
    return recs, picks_by


def summarize(records):
    df = pd.DataFrame(records).sort_values("date")
    net = BQ.turnover_net(df["gross"].to_numpy(), df["f_new"].to_numpy(), BQ.COST_BPS)
    s = df["spy"].to_numpy(np.float64)
    ok = np.isfinite(s)
    ex = (net - s)[ok]
    d = pd.to_datetime(df["date"]).to_numpy()[ok]
    yrs = pd.DatetimeIndex(d).year.to_numpy()
    loyo = {int(y): float(np.mean(ex[yrs != y]) * ANN) for y in np.unique(yrs)}
    ymin = min(loyo, key=loyo.get)
    post = pd.DatetimeIndex(d) >= POST
    return {"n_windows": int(ok.sum()), "excess_cagr_vs_spy": float(np.mean(ex) * ANN),
            "loyo_min": loyo[ymin], "loyo_min_dropped_year": ymin,
            "post2011_10": float(np.mean(ex[post]) * ANN), "n_windows_post2011_10": int(post.sum()),
            "yearly_mean_excess_ann": {int(y): float(np.mean(ex[yrs == y]) * ANN) for y in np.unique(yrs)}}


def main():
    out = {"note": "SINGLE GRID (q75's own cadence), pre-2020 windows only; composite legs are "
                   "current_signal_blend.py's frozen functions. seas weights: equal (1/10), no fitting.",
           "hold_out": "no q75 timepoint or panel row dated >= 2020-01-01 is read (asserted)"}
    for name in ("v2c", "v1"):
        p, dates, q75_by, spy, info = load(name)
        recs, picks = run(p, dates, q75_by, spy)
        res = {"info": info}
        for k, r in recs.items():
            res[k] = summarize(r)
        common = sorted(set(picks["blend_prev9"]) & set(picks["blend_seas10"]))
        res["blend_pick_overlap_mean_share"] = float(np.mean(
            [len(set(picks["blend_seas10"][d]) & set(picks["blend_prev9"][d])) / len(picks["blend_seas10"][d])
             for d in common]))
        out[name] = res
        print(name, json.dumps({k: (v if k == "info" else {kk: vv for kk, vv in v.items() if kk != "yearly_mean_excess_ann"})
                                for k, v in res.items() if isinstance(v, dict)}, default=float), flush=True)
    OUT.write_text(json.dumps(out, indent=1, default=float))
    print(f"-> {OUT}")


if __name__ == "__main__":
    main()
