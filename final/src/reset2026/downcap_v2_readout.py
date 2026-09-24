"""
WO-6 Phase 2: the pre-registered re-measurement of the EXISTING composite on
the survivorship-safe down-cap grid (see 2026-09-24-downcap-grid-rebuild.md).
Descriptive, not a new trial, and it has no kill.

Books (no knob changes):
  icw8 = ic_weighted_composite.compute_composite_ic_weighted (frozen PRODUCTION_WEIGHTS)
  ew8  = composite.compute_composite(neutral=False); the equal-weight 8-factor
         book, used only to reconcile column a to correction_variants
         (+0.04321 at cap150)
Construction: composite.pick_decile_volq. 15bp via run_backtest.turnover_net_return.
40 grid offsets, excess vs SPY annualised x252/40, plus leave-one-year-out.
IC: split-half out-of-sample exactly as ic_weighted_composite.py (fit weights
on odd years and test on even, and vice versa), plus frozen PRODUCTION_WEIGHTS
pooled IC. Label forward_return_tradable_40, Spearman, NW lag 39.

Columns:
  a  old grid, v1 flags   composite_panel.parquet + outcome_cache.parquet
  b  old grid, v2 flags   composite_panel_v2 restricted to the old 4,011 tickers
  c  v2 grid,  v2 flags   composite_panel_v2, old tickers + added non-SPAC tickers

Era 2007-01-02 .. 2019-12-31 only; every frame read asserts max(date) < 2020-01-01.
Output: out/reset2026/downcap_v2/readout.json
"""
import json
import sys
import time
from pathlib import Path

import numpy as np
import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parent))
import composite as C                      # noqa: E402
import run_backtest as RB                  # noqa: E402
import ic_weighted_composite as ICW        # noqa: E402

MAIN = Path("/Users/ggraham/pipe_dream/final")
R26 = MAIN / "out" / "reset2026"
V2 = R26 / "downcap_v2"
SH = MAIN / "data" / "sharadar"
START, END = pd.Timestamp("2007-01-02"), pd.Timestamp("2019-12-31")
HOLDOUT = pd.Timestamp("2020-01-01")
COST_BPS = 15.0
LABEL = "forward_return_tradable_40"
TIERS = ["cap150", "cap500", "cap2000"]
REF_EW8_CAP150 = 0.04320852571388379          # correction_variants asset_growth_dropped
REF_IC_ODD_EVEN = 0.030441719669279048        # ic_weighted_composite, cap150
REF_IC_EVEN_ODD = 0.04958574071891833


def log(m):
    print(f"[{time.strftime('%H:%M:%S')}] {m}", flush=True)


def guard(df):
    assert df["date"].max() < HOLDOUT, "HOLD-OUT BREACH: date >= 2020-01-01"
    return df


def load_column(col):
    cols = ["ticker", "date", LABEL] + C.FACTOR_COLS
    flags = [f"eligible_{t}" for t in TIERS]
    filt = [("date", ">=", "2007-01-02"), ("date", "<=", "2019-12-31")]
    old_t = set(pd.read_parquet(R26 / "composite_panel.parquet", columns=["ticker"])["ticker"].unique())
    if col == "a":
        p = pd.read_parquet(R26 / "composite_panel.parquet", columns=cols + flags, filters=filt)
        oc_path = R26 / "outcome_cache.parquet"
    else:
        p = pd.read_parquet(R26 / "composite_panel_v2.parquet", columns=cols + flags, filters=filt)
        oc_path = R26 / "outcome_cache_v2.parquet"
        if col == "b":
            p = p[p["ticker"].isin(old_t)]
        else:
            tm = pd.read_csv(SH / "tickers_master.csv", dtype=str,
                             usecols=["ticker", "sicindustry"]).drop_duplicates("ticker")
            spac = set(tm.loc[tm["sicindustry"].fillna("").str.contains("Blank Check"), "ticker"])
            p = p[p["ticker"].isin(old_t) | ~p["ticker"].isin(spac)]
    p["date"] = pd.to_datetime(p["date"])
    p["ticker"] = p["ticker"].astype(str)
    p = guard(p[(p["date"] >= START) & (p["date"] <= END)])
    oc = pd.read_parquet(oc_path, columns=["ticker", "date", "gross_return_40"],
                         filters=[("date", ">=", START), ("date", "<=", END)])
    oc["date"] = pd.to_datetime(oc["date"])
    oc = guard(oc)
    spy = oc[oc["ticker"] == "SPY"].set_index("date")["gross_return_40"]
    n = len(p)
    p = p.merge(oc[~oc["ticker"].isin(["SPY", "USMV"])], on=["ticker", "date"], how="left")
    assert len(p) == n
    log(f"column {col}: {len(p):,} rows, {p['ticker'].nunique():,} tickers, "
        f"{p['date'].min().date()}..{p['date'].max().date()}")
    return p, spy


BOOKS = {
    "icw8": lambda g: ICW.compute_composite_ic_weighted(g),
    "ew8": lambda g: C.compute_composite(g, neutral=False),
}


def per_date_picks(p, tier):
    """Picks are deterministic per date, so compute once; offsets only
    stitch dates (dates[offset::40] partitions the calendar)."""
    out = {b: {} for b in BOOKS}
    for d, g in p.groupby("date", sort=True):
        elig = g[g[f"eligible_{tier}"]]
        if len(elig) < C.N_VOL_QUINTILES * 4:
            continue
        elig = elig.reset_index(drop=True)
        ret = dict(zip(elig["ticker"], elig["gross_return_40"]))
        for b, fn in BOOKS.items():
            picks = C.pick_decile_volq(elig, fn(elig))
            picks = [(t, w) for t, w in picks if pd.notna(ret.get(t))]
            if not picks:
                continue
            ws = sum(w for _, w in picks)
            gross = sum((w / ws) * (1.0 + ret[t]) for t, w in picks) - 1.0
            out[b][d] = (gross, {t for t, _ in picks})
    return out


def backtest(picks_by_date, all_dates, spy):
    ann = 252.0 / RB.HORIZON
    per_off, loyo_acc = [], {}
    for off in range(40):
        prev, recs = set(), []
        for tp in all_dates[off::RB.HORIZON]:
            if tp not in picks_by_date:
                continue
            gross, cur = picks_by_date[tp]
            f_new = sum(1 for t in cur if t not in prev) / len(cur)
            prev = cur
            recs.append({"date": tp, "gross": gross, "f_new": f_new, "spy": spy.get(tp, np.nan)})
        net = RB.turnover_net_return(recs, COST_BPS)
        s = np.array([r["spy"] for r in recs], dtype=np.float64)
        yrs = np.array([r["date"].year for r in recs])
        ok = np.isfinite(s)
        exc, yrs = net[ok] - s[ok], yrs[ok]
        per_off.append(float(exc.mean() * ann))
        for y in np.unique(yrs):
            loyo_acc.setdefault(int(y), []).append(float(exc[yrs != y].mean() * ann))
    loyo = {y: float(np.mean(v)) for y, v in loyo_acc.items()}
    ymin = min(loyo, key=loyo.get)
    return {"excess_cagr_vs_spy_mean40": float(np.mean(per_off)),
            "sd40": float(np.std(per_off)), "min40": float(np.min(per_off)),
            "max40": float(np.max(per_off)),
            "offsets_positive": int(sum(v > 0 for v in per_off)),
            "loyo_min": loyo[ymin], "loyo_min_dropped_year": ymin,
            "loyo_max": max(loyo.values())}


def ic_block(p, tier):
    nom = p[p[f"eligible_{tier}"]].copy()
    fc = list(ICW.PRODUCTION_WEIGHTS)
    yrs = nom["date"].dt.year
    odd, even = nom[yrs % 2 == 1], nom[yrs % 2 == 0]
    w_odd = ICW.fit_weights(ICW.per_factor_t(odd, fc), fc)
    w_even = ICW.fit_weights(ICW.per_factor_t(even, fc), fc)

    def ic(df, w):
        parts = []
        for d, g in df.groupby("date"):
            gg = g.reset_index(drop=True)
            parts.append(pd.DataFrame({"date": d, "score": ICW.compute_weighted_score(gg, w, fc).to_numpy(),
                                       "label": gg[LABEL].to_numpy()}))
        s = pd.concat(parts, ignore_index=True)
        return ICW.pooled_corr(s, "score", "label")

    r = {"oos_fit_odd_test_even": ic(even, w_odd), "oos_fit_even_test_odd": ic(odd, w_even),
         "frozen_full": ic(nom, ICW.PRODUCTION_WEIGHTS),
         "weights_odd": w_odd, "weights_even": w_even}
    r["oos_split_half_mean"] = 0.5 * (r["oos_fit_odd_test_even"]["mean"] + r["oos_fit_even_test_odd"]["mean"])
    return r


def main():
    out = {"era": "2007-01-02..2019-12-31", "cost_bps": COST_BPS, "columns": {}}
    for col in ("a", "b", "c"):
        p, spy = load_column(col)
        all_dates = sorted(p["date"].unique())
        cres = {}
        for tier in TIERS:
            t0 = time.time()
            pk = per_date_picks(p, tier)
            cres[tier] = {b: backtest(pk[b], all_dates, spy) for b in BOOKS}
            log(f"  {col} {tier}: icw8 {cres[tier]['icw8']['excess_cagr_vs_spy_mean40']:+.4f}  "
                f"ew8 {cres[tier]['ew8']['excess_cagr_vs_spy_mean40']:+.4f} ({time.time()-t0:.0f}s)")
            if col == "a" and tier == "cap150":
                got = cres[tier]["ew8"]["excess_cagr_vs_spy_mean40"]
                assert abs(got - REF_EW8_CAP150) < 1e-6, f"RECONCILE FAIL ew8 cap150 {got} vs {REF_EW8_CAP150}"
                log("  reconcile OK: ew8 cap150 column a == correction_variants")
            if tier != "cap2000":
                t0 = time.time()
                cres[tier]["ic"] = ic_block(p, tier)
                log(f"  {col} {tier} IC split-half OOS {cres[tier]['ic']['oos_split_half_mean']:+.4f} "
                    f"frozen {cres[tier]['ic']['frozen_full']['mean']:+.4f} ({time.time()-t0:.0f}s)")
                if col == "a" and tier == "cap150":
                    a1 = cres[tier]["ic"]["oos_fit_odd_test_even"]["mean"]
                    a2 = cres[tier]["ic"]["oos_fit_even_test_odd"]["mean"]
                    out["ic_reconcile"] = {"odd_even": [a1, REF_IC_ODD_EVEN], "even_odd": [a2, REF_IC_EVEN_ODD]}
                    assert abs(a1 - REF_IC_ODD_EVEN) < 1e-6 and abs(a2 - REF_IC_EVEN_ODD) < 1e-6, \
                        f"RECONCILE FAIL IC {out['ic_reconcile']}"
                    log("  reconcile OK: split-half IC column a == ic_weighted_composite")
        out["columns"][col] = cres
        (V2 / "readout.json").write_text(json.dumps(out, indent=2, default=str))
        del p
    log("done")


if __name__ == "__main__":
    main()
