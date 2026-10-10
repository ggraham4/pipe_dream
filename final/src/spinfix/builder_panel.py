"""WO-57 Phase 1: build the spin-fixed patch panel through the hooked builder functions (branch only).

Pre-registration: final/models/2026-10-09-spinfix-builder-prereg.md (hash asserted).
For every ticker with an event, recompute through the SAME builder code, with the hook off (m = 1) and on:
  volatility_60, pct_from_high_252  build_features_sharadar.features_for  (SEP panel prices <= 2019-12-31)
  momentum_12_1                     reset2026/quality_factors.momentum_12_1 (features close, float32 like the panel)
  gross_return_40                   reset2026/build_outcome_cache.vectorized_outcomes (OHLC CSVs <= 2020-03-31)
  seas                              seasonality/build_seas month-ends + splice + monthly_returns + seas_table
Rows 2007-01-02..2019-12-31 only. Checks C1 (raw levels / market_cap identical), C2 (m = 1 recompute == stored),
C3 (labels == WO-54 label_fix). Every other ticker has multiplier 1, so it is unchanged by construction.
Writes (worktree, gitignored parquet): final/out/spinfix_builder/patch_panel.parquet, events_used.parquet;
committed: final/out/spinfix_builder/phase1_builder.json (aggregates only).
"""
from __future__ import annotations

import hashlib
import json
import sys
import time
from pathlib import Path

import numpy as np
import pandas as pd

HERE = Path(__file__).resolve().parent
SRC = HERE.parent
FINAL = HERE.parents[1]
MAIN = Path("/Users/ggraham/pipe_dream/final")
PREREG = FINAL / "models" / "2026-10-09-spinfix-builder-prereg.md"
PREREG_SHA = "a4c44e9b813a7e656f42da8cbba56da64cc22c9e02f009336a1ca33de1d85d56"   # committed 29514f4
assert hashlib.sha256(PREREG.read_bytes()).hexdigest() == PREREG_SHA, "PRE-REG CHANGED SINCE FREEZE: STOP"

sys.path.insert(0, str(SRC))
sys.path.insert(0, str(SRC / "reset2026"))
sys.path.insert(0, str(SRC / "seasonality"))
sys.path.insert(0, str(SRC / "wrds_crsp"))
sys.path.insert(0, str(HERE))
import adjust as SA  # noqa: E402
import build_features_sharadar as BF  # noqa: E402
import quality_factors as Q  # noqa: E402
import build_outcome_cache as OC  # noqa: E402
import build_seas as B  # noqa: E402
import common as K  # noqa: E402

LO, CUT = pd.Timestamp("2007-01-02"), pd.Timestamp("2019-12-31")
OUT = FINAL / "out" / "spinfix_builder"
SEP_MAIN = MAIN / "data" / "sharadar" / "panel" / "stocks"
SPY_CSV = MAIN / "scripts" / "td_data_local" / "SPY.csv"
SEAS_STORED = Path("/Users/ggraham/pipe_dream/.claude/worktrees/wo24-construction-drag/final/out/audit/seas_factor_ext.parquet")
PANEL_V2 = MAIN / "out" / "reset2026" / "composite_panel_v2.parquet"
OUTCOME_V2 = MAIN / "out" / "reset2026" / "outcome_cache_v2.parquet"
log = B.log


def sep_rows(tickers, cols, last="2019-12"):
    fr = []
    for f in sorted(SEP_MAIN.glob("*.parquet")):
        if f.stem > last:
            continue
        d = pd.read_parquet(f, columns=["ticker", "date"] + cols)
        d = d[d["ticker"].isin(tickers)]
        if len(d):
            fr.append(d)
    d = pd.concat(fr, ignore_index=True)
    d["date"] = pd.to_datetime(d["date"]).astype("datetime64[ns]")
    d["ticker"] = d["ticker"].astype(str)
    assert d["date"].max() <= CUT
    return d.sort_values(["ticker", "date"]).reset_index(drop=True)


def events_all():
    """close-series events (WO-54 applied), closeadj-series events, and variant V1 (close, ±1-day drop)."""
    ev = pd.read_parquet(SA.EVENTS_PQ)
    ev["exdt"] = pd.to_datetime(ev["exdt"]).astype("datetime64[ns]")
    ok = ev[ev["status"].fillna("") == ""].copy()
    assert len(ok) == 274, len(ok)
    e_close = SA.load_events()
    assert len(e_close) == 242
    # closeadj factor from SEP on the same days (prev SEP row must be CRSP's previous trading day)
    sep = sep_rows(set(ok["ticker"]), ["closeadj"])
    rA = []
    for r in ok.itertuples():
        g = sep[sep["ticker"] == r.ticker]
        d = g["date"].to_numpy("datetime64[ns]")
        k = np.searchsorted(d, np.datetime64(r.exdt, "ns"))
        if k == 0 or k >= len(d) or d[k] != np.datetime64(r.exdt, "ns") or d[k - 1] != np.datetime64(r.crsp_prev_date, "ns"):
            rA.append(np.nan)
            continue
        c = g["closeadj"].to_numpy(np.float64)
        rA.append(c[k] / c[k - 1] - 1)
    ok["r_A"] = rA
    ok["m_adj"] = (1 + ok["r_A"]) / (1 + ok["r_C"])
    e_adj = SA.load_events(ok, m_col="m_adj")
    # variant V1: offset-0 below threshold, largest gap within ±1 trading day >= 2% at offset -1/+1
    v1 = ok[(~ok["applied"].astype(bool)) & ok["max_gap_offset"].isin([-1, 1]) & (ok["max_gap"].abs() >= SA.THRESH)].copy()
    ohlc = K.load_ohlc(sorted(v1["ticker"].unique()), CUT)
    rows = []
    for r in v1.itertuples():
        d = ohlc[r.ticker]["date"].to_numpy("datetime64[ns]")
        k = int(np.searchsorted(d, np.datetime64(r.exdt, "ns"))) + int(r.max_gap_offset)
        rows.append({"ticker": r.ticker, "exdt": pd.Timestamp(d[k]), "m": float(np.exp(r.max_gap)),
                     "crsp_exdt": r.exdt})
    e_v1 = pd.DataFrame(rows, columns=["ticker", "exdt", "m", "crsp_exdt"])
    info = {"candidates_ok": int(len(ok)), "close_applied": int(len(e_close)),
            "closeadj_finite": int(np.isfinite(ok["m_adj"]).sum()), "closeadj_applied": int(len(e_adj)),
            "closeadj_abs_log_m_median_on_close_applied": float(np.nanmedian(np.abs(np.log(
                ok.loc[ok["applied"].astype(bool), "m_adj"])))),
            "v1_events": [{"ticker": r.ticker, "sharadar_drop": str(r.exdt.date()), "crsp_exdt": str(pd.Timestamp(r.crsp_exdt).date()),
                           "m": round(r.m, 5)} for r in e_v1.itertuples()]}
    return e_close, e_adj, e_v1[["ticker", "exdt", "m"]], ok, info


def price_features(tickers, evs):
    """volatility_60, pct_from_high_252 (+ raw close for momentum) per ticker, hook off and per event set."""
    px = sep_rows(tickers, BF.PRICE_COLS)
    px = BF.segment_reused_symbols(px, entities=BF.load_reuse_entities((MAIN / "data" / "sharadar" / "tickers_master.csv",)))
    spy = pd.read_csv(SPY_CSV, parse_dates=["date"]).sort_values("date")
    spy["spy_momentum_20"] = spy["close"].pct_change(BF.RS_WINDOW)
    spy = spy[["date", "spy_momentum_20"]].reset_index(drop=True)
    out, c1 = [], {"tickers": 0, "price_cols_equal": True}
    for tk, g in px.groupby("ticker", sort=False):
        g = g[["ticker", "date"] + BF.PRICE_COLS]
        f0 = BF.features_for(g, spy)
        rec = pd.DataFrame({"ticker": tk, "date": f0["date"].to_numpy(), "close": f0["close"].to_numpy(),
                            "vol_u": f0["volatility_60"].to_numpy(), "pfh_u": f0["pct_from_high_252"].to_numpy()})
        for name, ev in evs.items():
            f1 = BF.features_for(g, spy, ev)
            # C1: raw level columns identical with the hook on
            same = all(np.array_equal(f0[c].to_numpy(), f1[c].to_numpy(), equal_nan=True) for c in BF.PRICE_COLS)
            c1["price_cols_equal"] &= bool(same)
            if name == "f":
                rec["close_f"] = f1["close"].to_numpy()
            rec[f"vol_{name}"] = f1["volatility_60"].to_numpy()
            rec[f"pfh_{name}"] = f1["pct_from_high_252"].to_numpy()
        c1["tickers"] += 1
        out.append(rec)
    return pd.concat(out, ignore_index=True), c1


def momentum(pf, evs):
    p = pf[["ticker", "date", "close"]].sort_values(["ticker", "date"]).reset_index(drop=True)
    p["mom_u"] = Q.momentum_12_1(p).astype(np.float32)
    for name, ev in evs.items():
        p[f"mom_{name}"] = Q.momentum_12_1(p, ev).astype(np.float32)
    return p.drop(columns="close")


def labels(tickers, evs):
    oh = K.load_ohlc(sorted(tickers), K.EXIT_CUTOFF, cols=("date", "open", "close"))
    out = []
    for t, g in oh.items():
        g = g.sort_values("date").reset_index(drop=True)
        rec = pd.DataFrame({"ticker": t, "date": g["date"].to_numpy("datetime64[ns]")})
        rec["lab_u"] = OC.vectorized_outcomes(g)[0]
        for name, ev in evs.items():
            rec[f"lab_{name}"] = OC.vectorized_outcomes(OC.spin_adjust_ohlc(t, g, ev))[0]
        out.append(rec[rec["date"] <= CUT])
    return pd.concat(out, ignore_index=True)


def seas(tickers, e_adj, panel_keys):
    pre, ovl, main_f = B.sep_files()

    def me_of(files):
        m = B.load_month_ends(files)
        return m[m["ticker"].isin(tickers)].reset_index(drop=True)

    me, _ = B.splice_month_ends(me_of(pre), me_of([ovl]), me_of(main_f))
    res = {}
    for name, ev in (("u", None), ("f", e_adj)):
        m = SA.adjust_month_ends(me, ev) if ev is not None else me
        tick, ym0, S, N = B.seas_table(B.monthly_returns(m))
        p = panel_keys.copy()
        T = p["date"] + pd.Timedelta(days=B.TARGET_DAYS)
        tym = (T.dt.year * 12 + T.dt.month - 1).to_numpy()
        ti = tick.get_indexer(p["ticker"])
        ci = tym - ym0
        v = np.full(len(p), np.nan)
        has = ti >= 0
        v[has] = S[ti[has], ci[has]]
        res[name] = v
    return res


def main():
    t0 = time.time()
    OUT.mkdir(parents=True, exist_ok=True)
    e_close, e_adj, e_v1, ok, info = events_all()
    log(f"events: close {len(e_close)}, closeadj {len(e_adj)}, V1 {len(e_v1)}")
    e_b1 = pd.concat([e_close, e_v1], ignore_index=True).sort_values(["ticker", "exdt"]).reset_index(drop=True)
    ev_tickers = set(e_close["ticker"]) | set(e_adj["ticker"]) | set(e_v1["ticker"])
    grid = pd.read_parquet(PANEL_V2, columns=["ticker", "date", "eligible_cap150"],
                           filters=[("date", ">=", "2007-01-02"), ("date", "<=", "2019-12-31")])
    grid = sorted(set(grid.loc[grid["eligible_cap150"].astype(bool), "ticker"].astype(str)) - ev_tickers)
    rnd = set(np.random.default_rng(57).choice(grid, size=50, replace=False).tolist())
    tickers = ev_tickers | rnd
    evs = {"f": e_close, "f1": e_b1}

    pf, c1 = price_features(tickers, evs)
    c1["random_no_event_tickers"] = len(rnd)
    # C1b: market_cap through the fundamentals builder from the hook-off vs hook-on close
    import build_features_fundamentals_sharadar as FF
    FF.SF1 = MAIN / "data" / "sharadar" / "sf1_fundamentals.parquet"
    raw = FF.tidy_sf1()
    mc0 = FF.compute_fundamentals(pf[["ticker", "date", "close"]], raw)["market_cap"].to_numpy(np.float64)
    mc1 = FF.compute_fundamentals(pf[["ticker", "date", "close_f"]].rename(columns={"close_f": "close"}), raw)["market_cap"].to_numpy(np.float64)
    del raw
    c1["market_cap_rows"] = int(len(mc0))
    c1["market_cap_equal"] = bool(np.array_equal(mc0, mc1, equal_nan=True))
    assert c1["price_cols_equal"] and c1["market_cap_equal"], f"C1 FAIL {c1}"
    log(f"price features {len(pf):,} rows ({time.time()-t0:.0f}s)")
    mo = momentum(pf, evs)
    lab = labels(tickers, evs)
    log(f"labels {len(lab):,} rows ({time.time()-t0:.0f}s)")

    pan = pd.read_parquet(PANEL_V2, columns=["ticker", "date", "momentum_12_1", "volatility_60", "pct_from_high_252",
                                             "market_cap", "eligible_cap150", "eligible_cap500", "eligible_cap2000"],
                          filters=[("ticker", "in", sorted(tickers))])
    pan["date"] = pd.to_datetime(pan["date"]).astype("datetime64[ns]")
    pan["ticker"] = pan["ticker"].astype(str)
    pan = pan[(pan["date"] >= LO) & (pan["date"] <= CUT)].reset_index(drop=True)
    oc = pd.read_parquet(OUTCOME_V2, columns=["ticker", "date", "gross_return_40"],
                         filters=[("ticker", "in", sorted(tickers)), ("date", "<=", CUT)])
    oc["date"] = pd.to_datetime(oc["date"]).astype("datetime64[ns]")
    oc["ticker"] = oc["ticker"].astype(str)
    st = pd.read_parquet(SEAS_STORED, columns=["ticker", "date", "seas"],
                         filters=[("ticker", "in", sorted(tickers)), ("date", "<=", CUT)])
    st["date"] = pd.to_datetime(st["date"]).astype("datetime64[ns]")
    st["ticker"] = st["ticker"].astype(str)
    n = len(pan)
    pan = (pan.merge(pf.drop(columns=["close", "close_f"]), on=["ticker", "date"], how="left")
              .merge(mo, on=["ticker", "date"], how="left")
              .merge(oc.rename(columns={"gross_return_40": "lab_stored"}), on=["ticker", "date"], how="left")
              .merge(lab, on=["ticker", "date"], how="left")
              .merge(st.rename(columns={"seas": "seas_stored"}), on=["ticker", "date"], how="left"))
    assert len(pan) == n, "merge changed rows"
    sz = seas(tickers, e_adj, pan[["ticker", "date"]])
    pan["seas_u"], pan["seas_f"] = sz["u"], sz["f"]
    pan["seas_f1"] = pan["seas_f"]                       # V1 is close-series only
    log(f"seas done ({time.time()-t0:.0f}s)")

    # ---------------- C2: m = 1 recompute == stored
    def cmp(a, b, f32=False):
        x, y = pan[a].to_numpy(np.float64), pan[b].to_numpy(np.float64)
        if f32:
            x, y = x.astype(np.float32), y.astype(np.float32)
        nan_eq = np.isnan(x) == np.isnan(y)
        both = ~np.isnan(x) & ~np.isnan(y)
        d = np.abs(x[both] - y[both])
        return {"rows": int(len(x)), "nan_pattern_mismatch": int((~nan_eq).sum()),
                "max_abs_diff": float(d.max()) if len(d) else 0.0, "n_diff_gt_0": int((d > 0).sum()),
                "exact": bool(nan_eq.all() and (d == 0).all())}
    c2 = {"momentum_12_1": cmp("mom_u", "momentum_12_1", True), "volatility_60": cmp("vol_u", "volatility_60"),
          "pct_from_high_252": cmp("pfh_u", "pct_from_high_252"), "seas": cmp("seas_u", "seas_stored"),
          "gross_return_40": cmp("lab_u", "lab_stored", True)}
    for k, v in c2.items():
        log(f"C2 {k}: {v}")
    # C3: fixed labels vs WO-54
    w = pd.read_parquet(K.DERIVED / "spinfix_labels.parquet", columns=["ticker", "date", "label_fix"])
    w["date"] = pd.to_datetime(w["date"]).astype("datetime64[ns]")
    x = pan.merge(w, on=["ticker", "date"])
    dd = np.abs(x["lab_f"].to_numpy(np.float64) - x["label_fix"].to_numpy(np.float64))
    c3 = {"rows": int(len(x)), "max_abs_diff": float(np.nanmax(dd)), "share_le_1e6": float(np.nanmean(dd <= 1e-6)),
          "nan_mismatch": int((np.isnan(x["lab_f"]) != np.isnan(x["label_fix"])).sum())}
    log(f"C3 {c3}")
    # changed-row counts
    chg = {}
    for c in ("mom", "vol", "pfh", "seas", "lab"):
        a, b = pan[f"{c}_u"].to_numpy(np.float64), pan[f"{c}_f"].to_numpy(np.float64)
        diff = ~((a == b) | (np.isnan(a) & np.isnan(b)))
        chg[c] = {"rows_changed": int(diff.sum()),
                  "rows_changed_cap150": int((diff & pan["eligible_cap150"].astype(bool).to_numpy()).sum())}
    log(f"changed rows {chg}")
    keep = ["ticker", "date", "market_cap", "eligible_cap150", "eligible_cap500", "eligible_cap2000",
            "momentum_12_1", "volatility_60", "pct_from_high_252", "seas_stored", "lab_stored"] + \
           [f"{c}_{s}" for c in ("mom", "vol", "pfh", "seas", "lab") for s in ("u", "f", "f1")]
    pan[keep].to_parquet(OUT / "patch_panel.parquet", index=False)
    for nm, ev in (("close", e_close), ("closeadj", e_adj), ("v1", e_v1)):
        ev.assign(series=nm).to_parquet(OUT / f"events_{nm}.parquet", index=False)
    rep = {"prereg_sha256": PREREG_SHA, "events": info, "affected_tickers": len(tickers),
           "patch_rows_2007_2019": int(len(pan)), "C1_builder": c1, "C2_recompute_eq_stored": c2,
           "C3_labels_vs_wo54": c3, "changed_rows": chg, "runtime_s": round(time.time() - t0, 1)}
    (OUT / "phase1_builder.json").write_text(json.dumps(rep, indent=1, default=str))
    log(f"done ({time.time()-t0:.0f}s)")


if __name__ == "__main__":
    main()
