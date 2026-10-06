"""
WO-43 Step 1: leakage audit of the cached q75 score run (READ-ONLY).

Cache under audit:
  final/out/sweep/scores/price_fund_h40_q75_trd_xgb_d3e01r100_expanding_cap500k_pit_s40.parquet
  produced by sweep/scorecache.run_signal on the panel built by
  continuous_walkforward_pit.load_panel_prepared.

COO ruling: a training row whose label ENDS ON the score date's close passes
(that close is known at score time; entry is the next open). A label ending
strictly AFTER the score date is a violation.

Checks
  A  Row-shift risk. load_panel_prepared builds the 40-day tradable label
     close[i+40]/open[i+1]-1 by ROW position inside each ticker block of the
     raw panel. If a ticker is missing market days, row i+40 is later than 40
     market days. For every one of the 124 cached score dates we rebuild the
     exact training mask run_signal used (finite label, date <= cutoff, last
     500k rows) and count rows whose label EXIT DATE (date of raw row i+40)
     is after the score date. Pre-cap counts too. Also asserts dates strictly
     increase inside every ticker block (the shift's second assumption).
  B  Cutoff proof per scored date: cutoff date, max training row date, max
     label exit date, all vs the score date.
  C  Fingerprint of the current panel (rebuilt 2026-10-05) against the cache
     (built 2026-09-10) on pre-2020 dates: close, market_cap, vol20, vol60 per
     (timepoint, ticker) and the scored ticker set per date.
  D  PIT spot check of 3 features on 200 sampled rows (momentum_20,
     volatility_20 from the ticker's own close history dated <= t, plus panel
     close vs raw SEP close; gross_margin from the latest SF1 ARY filing with
     datekey <= t), and one named company/date.

Hold-out: for 2020+ score dates only dates and label FINITENESS are computed
(which rows train); no return, label value or performance number is computed
or written for any date >= 2020-01-01.

Output: final/out/xgbretrain/step1_audit.json
"""
import json
import sys
import time
from pathlib import Path

import numpy as np
import pandas as pd
import pyarrow.parquet as pq

HERE = Path(__file__).resolve().parent
SRC = HERE.parent
sys.path.insert(0, str(SRC))

MAIN = Path("/Users/ggraham/pipe_dream/final")
import features as F                      # noqa: E402
import continuous_walkforward_pit as W    # noqa: E402

# Code from this worktree (== integration e1f598d), data from the main checkout.
W.OUT_DIR = MAIN / "out"
W.PIT_UNIVERSE_PATH = MAIN / "data" / "sharadar" / "pit_universe.parquet"

PANEL = MAIN / "out" / "features_with_fundamentals_sharadar_pit.parquet"
CACHE = MAIN / "out" / "sweep" / "scores" / "price_fund_h40_q75_trd_xgb_d3e01r100_expanding_cap500k_pit_s40.parquet"
SF1 = MAIN / "data" / "sharadar" / "sf1_fundamentals.parquet"
SEP_DIR = MAIN / "data" / "sharadar" / "panel" / "stocks"
OUT = HERE.parents[1] / "out" / "xgbretrain" / "step1_audit.json"
H = 40
CAP = 500_000
HOLDOUT = pd.Timestamp("2020-01-01")
FEATURE_COLS = list(F.FEATURE_COLS)


def log(m):
    print(f"[{time.strftime('%H:%M:%S')}] {m}", flush=True)


def raw_pass():
    """Raw panel in file order: dates, ticker codes (same coding as
    load_panel_prepared), the label EXIT date (raw row i+H in-block), whether
    the tradable label is finite, and the price-feature filter mask."""
    pf = pq.ParquetFile(PANEL)
    n = pf.metadata.num_rows
    dates = np.empty(n, dtype="datetime64[ns]")
    codes = np.empty(n, dtype=np.int32)
    close = np.empty(n, dtype=np.float32)
    open_ = np.empty(n, dtype=np.float32)
    keep = np.empty(n, dtype=bool)
    lookup, order = {}, []
    off = 0
    for i in range(pf.metadata.num_row_groups):
        tbl = pf.read_row_group(i, columns=["ticker", "date", "close", "open"] + FEATURE_COLS)
        m = tbl.num_rows
        dates[off:off + m] = tbl.column("date").to_numpy(zero_copy_only=False)
        close[off:off + m] = tbl.column("close").to_numpy(zero_copy_only=False)
        open_[off:off + m] = tbl.column("open").to_numpy(zero_copy_only=False)
        for k, t in enumerate(tbl.column("ticker").to_pylist()):
            c = lookup.get(t)
            if c is None:
                c = lookup[t] = len(order)
                order.append(t)
            codes[off + k] = c
        blk = np.column_stack([tbl.column(c).to_numpy(zero_copy_only=False).astype(np.float32)
                               for c in FEATURE_COLS])
        keep[off:off + m] = np.isfinite(blk).all(axis=1)
        off += m
        del tbl, blk
    assert (codes[1:] >= codes[:-1]).all(), "ticker blocks not contiguous"
    bounds = W._block_bounds(codes)
    # second assumption of the row shift: strictly increasing dates per block
    same = codes[1:] == codes[:-1]
    nondec = dates[1:][same] > dates[:-1][same]
    n_bad_order = int((~nondec).sum())
    exit_date = np.full(n, np.datetime64("NaT"), dtype="datetime64[ns]")
    for b in range(len(bounds) - 1):
        lo, hi = bounds[b], bounds[b + 1]
        k = hi - lo - H
        if k > 0:
            exit_date[lo:lo + k] = dates[lo + H: lo + H + k]
    lbl = W._forward_ratio(close, open_, bounds, H, 1)
    finite = np.isfinite(lbl)
    del lbl, close, open_
    return dict(dates=dates, codes=codes, order=order, exit_date=exit_date,
                finite=finite, keep=keep, n=n, n_bad_order=n_bad_order,
                bounds=bounds)


def main():
    global PANEL, OUT
    if len(sys.argv) > 1:                       # audit an alternative (older) panel build
        PANEL = Path(sys.argv[1])
        OUT = OUT.with_name(f"step1_audit_{PANEL.stem}.json")
    t0 = time.time()
    res = {"panel": str(PANEL), "panel_mtime": time.strftime("%Y-%m-%d %H:%M", time.localtime(PANEL.stat().st_mtime)),
           "cache": str(CACHE), "cache_mtime": time.strftime("%Y-%m-%d %H:%M", time.localtime(CACHE.stat().st_mtime)),
           "rule": "label exit date <= score date passes (COO); exit > score date = violation"}
    import xgboost
    res["xgboost_version"] = xgboost.__version__

    log("raw pass ...")
    R = raw_pass()
    res["raw_rows"] = int(R["n"])
    res["blocks"] = int(len(R["bounds"]) - 1)
    res["rows_with_nonincreasing_date_in_block"] = R["n_bad_order"]
    log(f"  raw rows {R['n']:,}, blocks {res['blocks']:,}, non-increasing date pairs {R['n_bad_order']}")

    # Filtered rows in load_panel_prepared's exact order.
    raw_idx = np.flatnonzero(R["keep"])
    ordr = np.argsort(R["dates"][raw_idx], kind="stable")
    raw_idx = raw_idx[ordr]
    f_dates = R["dates"][raw_idx]
    f_codes = R["codes"][raw_idx]
    f_exit = R["exit_date"][raw_idx]
    f_finite = R["finite"][raw_idx]

    log("cross-check against load_panel_prepared ...")
    df, n_before = W.load_panel_prepared(PANEL, ["close", "open", "market_cap", "volatility_20", "volatility_60"]
                                         + FEATURE_COLS, FEATURE_COLS, H)
    assert n_before == R["n"]
    assert len(df) == len(raw_idx), (len(df), len(raw_idx))
    assert (df["date"].to_numpy() == f_dates).all(), "date order mismatch"
    assert (df["ticker"].cat.codes.to_numpy() == f_codes).all(), "ticker order mismatch"
    assert (np.isfinite(df[F.TRADABLE_LABEL_COL].to_numpy()) == f_finite).all(), "label finiteness mismatch"
    res["filtered_rows"] = int(len(df))
    res["crosscheck_load_panel_prepared"] = "identical row order, tickers, dates, label finiteness"

    # Market calendar = dates of the filtered panel (what run_signal uses).
    all_dates = pd.Series(sorted(df["date"].unique()))
    cal_pos = {d: i for i, d in enumerate(all_dates.to_numpy())}

    cache = pd.read_parquet(CACHE)
    cache["timepoint"] = pd.to_datetime(cache["timepoint"]).astype("datetime64[ns]")
    tps = sorted(cache["timepoint"].unique())
    expect = W.build_step_dates(all_dates, "2007-01-02", 40)
    expect = [pd.Timestamp(x) for x in expect]
    res["n_cache_timepoints"] = len(tps)
    res["cache_timepoints_equal_step_grid_on_current_panel"] = (
        [pd.Timestamp(x) for x in tps] == expect[:len(tps)])
    res["step_grid_len_current_panel"] = len(expect)

    # Market-day exit position: label spans more than H market days?
    exit_ok = ~np.isnat(f_exit)
    pos_d = np.searchsorted(all_dates.to_numpy(), f_dates)
    pos_e = np.full(len(f_exit), -1, dtype=np.int64)
    pos_e[exit_ok] = np.searchsorted(all_dates.to_numpy(), f_exit[exit_ok])
    span = np.where(exit_ok, pos_e - pos_d, -1)
    lab_rows = f_finite
    long_span = lab_rows & (span > H)
    short_span = lab_rows & (span < H) & (span >= 0)
    res["label_span_market_days"] = {
        "finite_label_rows": int(lab_rows.sum()),
        "span_gt_40": int(long_span.sum()),
        "span_lt_40": int(short_span.sum()),
        "share_gt_40": float(long_span.sum() / max(lab_rows.sum(), 1)),
        "max_span": int(span[lab_rows].max()),
        "finite_label_but_no_exit_row": int((lab_rows & ~exit_ok).sum()),
    }
    log(f"  label spans: {res['label_span_market_days']}")

    log("per-score-date audit ...")
    per = []
    tot_v = tot_v_pre = tot_rows = 0
    for tp in tps:
        tp = pd.Timestamp(tp)
        idx = cal_pos[tp.to_datetime64()]
        cutoff = all_dates.iloc[idx - H]
        hi = int(np.searchsorted(f_dates, np.datetime64(cutoff), "right"))
        mask = f_finite[:hi].copy()
        pre_viol = int((mask & (f_exit[:hi] > np.datetime64(tp))).sum())
        n_sel = int(mask.sum())
        if n_sel > CAP:
            sel = np.flatnonzero(mask)
            mask[sel[:-CAP]] = False
        used = np.flatnonzero(mask)
        ex = f_exit[:hi][used]
        viol = ex > np.datetime64(tp)
        nv = int(viol.sum())
        tot_v += nv
        tot_v_pre += pre_viol
        tot_rows += len(used)
        rec = {"score_date": str(tp.date()), "cutoff": str(pd.Timestamp(cutoff).date()),
               "train_rows": int(len(used)),
               "train_first_date": str(pd.Timestamp(f_dates[used[0]]).date()),
               "train_last_date": str(pd.Timestamp(f_dates[used[-1]]).date()),
               "max_label_exit": str(pd.Timestamp(ex.max()).date()),
               "violations": nv, "violations_precap": pre_viol}
        if nv:
            vrows = used[viol]
            rec["violation_examples"] = [
                {"ticker": R["order"][f_codes[i]], "row_date": str(pd.Timestamp(f_dates[i]).date()),
                 "exit": str(pd.Timestamp(f_exit[i]).date())} for i in vrows[:5]]
            rec["violation_max_exit"] = str(pd.Timestamp(ex[viol].max()).date())
            rec["violation_tickers"] = int(len(np.unique(f_codes[vrows])))
        assert pd.Timestamp(rec["train_last_date"]) <= pd.Timestamp(cutoff)
        per.append(rec)
    res["per_score_date"] = per
    res["total_violations"] = int(tot_v)
    res["total_violations_precap"] = int(tot_v_pre)
    res["total_training_row_uses"] = int(tot_rows)
    res["violation_share"] = float(tot_v / tot_rows)
    res["score_dates_with_violation"] = [r["score_date"] for r in per if r["violations"]]
    res["cutoff_rule_all_dates"] = all(pd.Timestamp(r["max_label_exit"]) <= pd.Timestamp(r["score_date"]) for r in per)
    log(f"  violations {tot_v} of {tot_rows:,} row-uses ({len(res['score_dates_with_violation'])} dates); pre-cap {tot_v_pre}")

    # ---------- C. fingerprint vs cache (pre-2020 only)
    log("fingerprint pre-2020 ...")
    pit_map = W.load_pit_universe()
    cur_univ = set(df["ticker"].cat.categories.tolist())
    pre = cache[cache["timepoint"] < HOLDOUT]
    dsub = df[df["date"].isin(pre["timepoint"].unique())][["date", "ticker", "close", "market_cap",
                                                           "volatility_20", "volatility_60"]].copy()
    dsub["ticker"] = dsub["ticker"].astype(str)
    m = pre.merge(dsub, left_on=["timepoint", "ticker"], right_on=["date", "ticker"], how="left",
                  suffixes=("", "_now"))
    fp = {"cache_rows_pre2020": int(len(pre)), "found_in_current_panel": int(m["close_now"].notna().sum())}
    for c in ("close", "market_cap", "volatility_20", "volatility_60"):
        a, b = m[c].to_numpy(np.float32), m[f"{c}_now"].to_numpy(np.float32)
        eq = (a == b) | (np.isnan(a) & np.isnan(b))
        fp[f"{c}_bit_equal_share"] = float(eq.mean())
        with np.errstate(invalid="ignore", divide="ignore"):
            rel = np.abs(a - b) / np.maximum(np.abs(a), 1e-12)
        fp[f"{c}_max_rel_diff"] = float(np.nanmax(rel)) if np.isfinite(rel).any() else None
    set_eq = 0
    set_diff = []
    for tp, g in pre.groupby("timepoint"):
        allowed = W.allowed_universe_at(pd.Timestamp(tp), cur_univ, None, "pit", pit_map)
        now = set(dsub.loc[dsub["date"] == tp, "ticker"]) & allowed
        was = set(g["ticker"])
        if now == was:
            set_eq += 1
        else:
            set_diff.append({"date": str(pd.Timestamp(tp).date()), "only_cache": len(was - now),
                             "only_now": len(now - was)})
    fp["dates_scored_set_equal"] = set_eq
    fp["dates_scored_set_differs"] = set_diff[:20]
    fp["n_dates_pre2020"] = int(pre["timepoint"].nunique())
    res["fingerprint_pre2020"] = fp
    log(f"  fingerprint {fp['dates_scored_set_equal']}/{fp['n_dates_pre2020']} sets equal; "
        f"close eq {fp['close_bit_equal_share']:.4f}")

    # ---------- D. PIT spot checks on 200 sampled pre-2020 cache rows
    log("spot checks ...")
    rng = np.random.default_rng(43)
    samp = pre.iloc[rng.choice(len(pre), 200, replace=False)][["timepoint", "ticker"]].reset_index(drop=True)
    res["spot_check"] = spot_check(samp, df)
    res["named_example"] = named_example(cache, df, pit_map, cur_univ)

    res["verdict"] = "PASS" if tot_v == 0 and R["n_bad_order"] == 0 and res["cutoff_rule_all_dates"] else "FAIL"
    res["elapsed_sec"] = round(time.time() - t0, 1)
    OUT.parent.mkdir(parents=True, exist_ok=True)
    OUT.write_text(json.dumps(res, indent=1, default=str))
    log(f"VERDICT {res['verdict']} -> {OUT}")


def _ticker_hist(df, tk):
    g = df[df["ticker"].astype(str) == tk][["date", "close", "momentum_20", "volatility_20", "gross_margin"]
                                           if "gross_margin" in df.columns else
                                           ["date", "close", "momentum_20", "volatility_20"]]
    return g.sort_values("date")


def spot_check(samp, df):
    """momentum_20 / volatility_20 recomputed from the RAW panel close history
    of the ticker truncated at t (no row after t is visible to the recompute),
    raw panel close vs SEP close at t, and gross_margin vs the latest SF1 ARY
    filing with datekey <= t."""
    tick = sorted(set(samp["ticker"]))
    raw = pd.read_parquet(PANEL, columns=["ticker", "date", "close", "momentum_20", "volatility_20", "gross_margin"],
                          filters=[("ticker", "in", tick)])
    raw["date"] = pd.to_datetime(raw["date"])
    raw = raw.sort_values(["ticker", "date"])
    sf1 = pd.read_parquet(SF1, columns=["ticker", "dimension", "date", "reportperiod", "revenue", "gp"],
                          filters=[("ticker", "in", sorted({t.split("__post")[0] for t in tick})), ("dimension", "==", "ARY")])
    sf1["filed"] = pd.to_datetime(sf1["date"], errors="coerce")
    out = {"n": len(samp), "momentum_20_match": 0, "volatility_20_match": 0,
           "sep_close_match": 0, "sep_close_checked": 0,
           "gross_margin_checked": 0, "gross_margin_match": 0,
           "gross_margin_next_filing_would_differ": 0, "mismatches": []}
    sep_cache = {}
    for _, r in samp.iterrows():
        t, tk = pd.Timestamp(r["timepoint"]), r["ticker"]
        g = raw[(raw["ticker"] == tk) & (raw["date"] <= t)]       # PIT truncation
        row = g.iloc[-1]
        assert row["date"] == t
        c = g["close"].to_numpy(np.float64)
        mom = c[-1] / c[-21] - 1 if len(c) > 20 else np.nan
        dr = pd.Series(c).pct_change().to_numpy()
        vol = np.std(dr[-20:], ddof=1) if len(c) > 20 else np.nan
        ok_m = np.isclose(mom, row["momentum_20"], rtol=1e-4, atol=1e-6)
        ok_v = np.isclose(vol, row["volatility_20"], rtol=1e-3, atol=1e-6)
        out["momentum_20_match"] += int(ok_m)
        out["volatility_20_match"] += int(ok_v)
        if not (ok_m and ok_v):
            out["mismatches"].append({"ticker": tk, "date": str(t.date()), "mom": [mom, float(row["momentum_20"])],
                                      "vol": [vol, float(row["volatility_20"])]})
        # SEP close at t
        ym = t.strftime("%Y-%m")
        if ym not in sep_cache:
            fp = SEP_DIR / f"{ym}.parquet"
            sep_cache[ym] = pd.read_parquet(fp, columns=["ticker", "date", "close"]) if fp.exists() else None
        s = sep_cache[ym]
        base = tk.split("__post")[0]
        if s is not None:
            sd = pd.to_datetime(s["date"])
            hit = s[(s["ticker"] == base) & (sd == t)]
            if len(hit):
                out["sep_close_checked"] += 1
                out["sep_close_match"] += int(np.isclose(float(hit["close"].iloc[0]), float(row["close"]), rtol=1e-4))
        # gross_margin from latest ARY filing with datekey <= t
        f = sf1[(sf1["ticker"] == base) & (sf1["filed"].notna())].sort_values("filed")
        f = f[f["revenue"].notna() & f["gp"].notna()]
        if np.isfinite(row["gross_margin"]) and len(f):
            past = f[f["filed"] <= t]
            if len(past):
                last = past.drop_duplicates("filed", keep="last").iloc[-1]
                gm = last["gp"] / last["revenue"] if last["revenue"] > 0 else np.nan
                out["gross_margin_checked"] += 1
                hit = bool(np.isclose(gm, row["gross_margin"], rtol=1e-4))
                out["gross_margin_match"] += int(hit)
                fut = f[f["filed"] > t]
                if len(fut):
                    nx = fut.iloc[0]
                    gm2 = nx["gp"] / nx["revenue"] if nx["revenue"] > 0 else np.nan
                    out["gross_margin_next_filing_would_differ"] += int(not np.isclose(gm2, row["gross_margin"], rtol=1e-4))
                if not hit:
                    out["mismatches"].append({"ticker": tk, "date": str(t.date()), "gm": [float(gm), float(row["gross_margin"])],
                                              "filed": str(last["filed"].date())})
    out["mismatches"] = out["mismatches"][:20]
    return out


def named_example(cache, df, pit_map, cur_univ):
    """AAPL on the 2015 cache date: in the PIT universe, scored, and its
    cached close/market_cap/vol equal the panel row and SEP close."""
    tp = sorted(t for t in cache["timepoint"].unique() if pd.Timestamp(t).year == 2015)[0]
    tp = pd.Timestamp(tp)
    c = cache[(cache["timepoint"] == tp) & (cache["ticker"] == "AAPL")]
    p = df[(df["date"] == tp) & (df["ticker"].astype(str) == "AAPL")]
    s = pd.read_parquet(SEP_DIR / f"{tp.strftime('%Y-%m')}.parquet", columns=["ticker", "date", "close"])
    s = s[(s["ticker"] == "AAPL") & (pd.to_datetime(s["date"]) == tp)]
    in_pit = "AAPL" in W.allowed_universe_at(tp, cur_univ, None, "pit", pit_map)
    return {"ticker": "AAPL", "date": str(tp.date()), "in_cache": bool(len(c)), "in_pit_universe": in_pit,
            "cache_close": float(c["close"].iloc[0]) if len(c) else None,
            "panel_close": float(p["close"].iloc[0]) if len(p) else None,
            "sep_close": float(s["close"].iloc[0]) if len(s) else None,
            "cache_mcap": float(c["market_cap"].iloc[0]) if len(c) else None,
            "panel_mcap": float(p["market_cap"].iloc[0]) if len(p) else None,
            "cache_vol60": float(c["volatility_60"].iloc[0]) if len(c) else None,
            "panel_vol60": float(p["volatility_60"].iloc[0]) if len(p) else None,
            "cache_score": float(c["score"].iloc[0]) if len(c) else None,
            "cache_score_rank_pct": float((cache[cache["timepoint"] == tp]["score"] < c["score"].iloc[0]).mean()) if len(c) else None}


if __name__ == "__main__":
    main()
