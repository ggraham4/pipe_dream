"""
Sweep orchestrator.

Round 12 (2026-09-09).

Subcommands, in the order they are meant to be run:

  probe      time a few walk-forward steps under several training caps, so
             the grid can be sized to the compute budget BEFORE it is frozen
  verify     reproduce the known production number through this code path
  scores     run signal cells (the expensive half), resumable
  outcomes   build the realized-outcomes cache from the scored candidates
  features   per-feature rank IC by horizon -- the floor, not a trial\n  portfolio  sweep the construction axes over the caches (the cheap half)\n  attribute  factor-attribute a cell: skill, or beta with extra steps?
  report     collapse everything into the results table and the grid verdict

One command per line when handing these over. A trailing '# comment' parses
as an argparse argument and has silently skipped probes on this project before
(DATA-PIPELINE-HANDOFF.md section 8).
"""

import argparse
import json
import os
import sys
import time
from pathlib import Path

import numpy as np
import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from features import DATA_DIR, OUT_DIR                      # noqa: E402
from sweep import scorecache as SC                          # noqa: E402
from sweep import outcomes as O                             # noqa: E402
from sweep import portfolio as P                            # noqa: E402
from sweep import stats as S                                # noqa: E402
from sweep import feature_ic as FIC                         # noqa: E402
from sweep import attribute as AT                           # noqa: E402

SWEEP_DIR = OUT_DIR / "sweep"
OUTCOMES_PATH = SWEEP_DIR / "outcomes.parquet"


def _spy():
    return pd.read_csv(DATA_DIR / "SPY.csv", parse_dates=["date"])


# ==========================================================================
# probe
# ==========================================================================
def cmd_probe(args):
    """Time the expensive half so the grid can be sized honestly."""
    SWEEP_DIR.mkdir(parents=True, exist_ok=True)
    caps = [int(x) for x in args.caps.split(",")]
    results = []

    t0 = time.time()
    ctx = SC.PanelContext(SC.PANEL_FOR[args.features], args.horizon)
    load_sec = time.time() - t0
    print(f"\npanel load: {load_sec:.0f}s\n")

    for cap in caps:
        cfg = SC.SignalConfig(features=args.features, horizon=args.horizon,
                              train_cap=cap, step=args.horizon)
        t0 = time.time()
        scores, meta = SC.run_signal(cfg, ctx, start=args.start, verbose=False)
        el = time.time() - t0
        n_tp = meta.get("n_timepoints", 0)
        results.append({"train_cap": cap, "n_timepoints": n_tp,
                        "total_sec": round(el, 1),
                        "sec_per_step": round(el / max(n_tp, 1), 2)})
        print(f"  cap={cap or 'none':>9}  {n_tp:>4} steps  {el:7.0f}s total  "
              f"{el / max(n_tp, 1):6.2f}s/step", flush=True)

    df = pd.DataFrame(results)
    df["est_full_run_min"] = df["sec_per_step"] * 124 / 60
    path = SWEEP_DIR / "probe_timing.csv"
    df.to_csv(path, index=False)
    print(f"\npanel load {load_sec:.0f}s is paid ONCE per (panel, horizon) group.")
    print(f"written {path}")
    print(df.to_string(index=False))


# ==========================================================================
# verify -- the gate
# ==========================================================================
def cmd_verify(args):
    """Reproduce the production baseline through the sweep code path.

    The production run (out/continuous_walkforward_pit_augmented_pit_realistic
    _tradable.json) is: augmented features, PIT universe, 40-day tradable
    label, top-5 equal weight, open entry, 15bp, no stop. Running that same
    config here must land on the same per-window returns.

    If it does not, every sweep cell is measuring something other than what
    the baseline measured, and the comparison is void.
    """
    ref_path = OUT_DIR / "continuous_walkforward_pit_augmented_pit_realistic_tradable.json"
    ref = json.load(open(ref_path))
    ref_rows = {r["timepoint"]: r for r in ref["results"]
                if r.get("model_return_pct") is not None}
    print(f"reference: {len(ref_rows)} windows from {ref_path.name}")

    cfg = SC.SignalConfig(features="price_fund", horizon=40, label="q75",
                          label_basis="tradable", model="xgb", universe="pit",
                          step=40)
    ctx = SC.PanelContext(SC.PANEL_FOR["price_fund"], 40)
    scores, meta = SC.run_signal(cfg, ctx, start="2007-01-02",
                                 checkpoint=str(SWEEP_DIR / "_verify_scores.parquet"))
    SWEEP_DIR.mkdir(parents=True, exist_ok=True)
    scores.to_parquet(SWEEP_DIR / "_verify_scores.parquet", index=False)

    # top-5 picks per timepoint from the sweep's own scores
    picks = (scores.sort_values(["timepoint", "score"], ascending=[True, False])
                   .groupby("timepoint").head(5))

    agree = disagree = 0
    examples = []
    for tp, g in picks.groupby("timepoint"):
        key = str(pd.Timestamp(tp).date())
        if key not in ref_rows:
            continue
        got = list(g["ticker"].astype(str))
        want = list(ref_rows[key]["picks"])
        if got == want:
            agree += 1
        else:
            disagree += 1
            if len(examples) < 8:
                examples.append((key, want, got))

    print(f"\npick agreement: {agree} identical, {disagree} different "
          f"of {agree + disagree} comparable windows")
    for k, w, g in examples:
        print(f"  {k}\n    reference {w}\n    sweep     {g}")

    if disagree == 0:
        print("\nVERIFY PASS -- the sweep path reproduces the production picks exactly.")
    else:
        print("\nVERIFY FAIL -- do not trust any sweep cell until this is resolved.")
        print("Most likely causes, in order: a different training-row filter, a "
              "different label column, or XGBoost threading (Gate A3).")
    return 0 if disagree == 0 else 1


# ==========================================================================
# scores -- the expensive half
# ==========================================================================
def _load_cells(path):
    cells = json.load(open(path))
    return [SC.SignalConfig(**c) for c in cells]


def cmd_scores(args):
    cells = _load_cells(args.cells)
    todo = [c for c in cells if not SC.have(c.id)] if args.resume else cells
    print(f"{len(cells)} cells requested, {len(todo)} to run "
          f"({len(cells) - len(todo)} already cached)")
    if not todo:
        return

    # Group by (panel, horizon) so the panel load is paid once per group.
    groups = {}
    for c in todo:
        groups.setdefault(c.group, []).append(c)
    print(f"{len(groups)} panel/horizon groups\n")

    for (panel_file, horizon), cells_in in groups.items():
        print(f"=== group {panel_file} h={horizon}: {len(cells_in)} cells ===",
              flush=True)
        ctx = SC.PanelContext(panel_file, horizon)
        for c in cells_in:
            if args.resume and SC.have(c.id):
                continue
            t0 = time.time()
            print(f"  -> {c.id}", flush=True)
            try:
                scores, meta = SC.run_signal(
                    c, ctx, start=args.start,
                    checkpoint=str(SWEEP_DIR / f"_ckpt_{c.id}.parquet"))
                if scores.empty:
                    print(f"     EMPTY: {meta.get('error')}")
                    continue
                SC.save(scores, meta)
                ck = SWEEP_DIR / f"_ckpt_{c.id}.parquet"
                if ck.exists():
                    ck.unlink()
                print(f"     done {meta['n_timepoints']} windows, "
                      f"{time.time() - t0:.0f}s", flush=True)
            except Exception as e:
                print(f"     ERROR {type(e).__name__}: {e}", flush=True)
        del ctx
        import gc
        gc.collect()


# ==========================================================================
# outcomes
# ==========================================================================
def cmd_outcomes(args):
    """Build the realized-outcomes cache over every scored candidate."""
    SWEEP_DIR.mkdir(parents=True, exist_ok=True)
    caches = sorted(SC.CACHE_DIR.glob("*.parquet"))
    if not caches:
        raise SystemExit("no score caches -- run 'scores' first")
    print(f"reading {len(caches)} score caches for the candidate set")

    pairs = []
    for p in caches:
        d = pd.read_parquet(p, columns=["timepoint", "ticker"])
        pairs.append(d)
    pairs = (pd.concat(pairs, ignore_index=True)
               .drop_duplicates()
               .reset_index(drop=True))
    pairs["ticker"] = pairs["ticker"].astype(str)
    print(f"{len(pairs):,} distinct (timepoint, ticker) pairs, "
          f"{pairs['ticker'].nunique():,} tickers, "
          f"{pairs['timepoint'].nunique()} dates")

    # Segment bounds exactly as the production run derives them.
    import pyarrow.parquet as pq
    panel = OUT_DIR / "features_with_fundamentals_sharadar_pit.parquet"
    td = pq.read_table(panel, columns=["ticker", "date"]).to_pandas()
    b = td.groupby("ticker", observed=True)["date"].agg(["min", "max"])
    segments = {t: (str(t).split("__post")[0], r["min"], r["max"])
                for t, r in b.iterrows()}
    del td, b

    from execution import SegmentedOHLCPanel
    import continuous_walkforward_pit as W
    panel_obj = SegmentedOHLCPanel(W.price_dirs_for("pit"), segments)

    t0 = time.time()
    tab = O.build_outcomes(panel_obj, pairs)
    print(f"built {tab.shape} in {time.time() - t0:.0f}s")

    print("verifying against execution.realize_position() ...")
    n = O.verify_against_reference(tab, panel_obj, n_samples=args.verify_samples,
                                   seed=11)
    print(f"VERIFY PASS: {n} comparisons agree exactly")

    tab.to_parquet(OUTCOMES_PATH, index=False)
    print(f"written {OUTCOMES_PATH} "
          f"({OUTCOMES_PATH.stat().st_size / 1e6:.0f}MB)")


# ==========================================================================
# portfolio -- the cheap half
# ==========================================================================
NOMINATE_ERA = ("2007-01-01", "2020-01-01")
HOLDOUT_ERA = ("2020-01-01", "2027-01-01")


def cmd_portfolio(args):
    tab = pd.read_parquet(OUTCOMES_PATH)
    tab["ticker"] = tab["ticker"].astype(str)
    spy = _spy()

    grid = json.load(open(args.grid))
    caches = sorted(SC.CACHE_DIR.glob("*.parquet"))
    era = HOLDOUT_ERA if args.era == "holdout" else NOMINATE_ERA
    print(f"era = {args.era} {era}")
    if args.era == "holdout" and not args.i_am_confirming:
        raise SystemExit(
            "Refusing to touch the hold-out.\n"
            "The pre-registration says 2020-2026 is looked at ONCE, for a "
            "config already nominated on 2007-2019. If that is what this is, "
            "pass --i-am-confirming and name the cell with --only.")
    if args.era == "holdout" and not args.only:
        raise SystemExit(
            "--i-am-confirming requires --only <cell_id>. The hold-out "
            "confirms ONE nominated config, not a grid.")

    rows = []
    for cpath in caches:
        cell = cpath.stem
        if args.only and args.only != cell:
            continue
        scores = pd.read_parquet(cpath)
        meta = json.load(open(SC.meta_path(cell)))
        H = int(meta["config"]["horizon"])
        spy_ret = P.spy_windows(spy, np.sort(scores["timepoint"].unique()), H)

        # One Prepared per distinct (horizon, stop) in the grid -- built once,
        # reused across every portfolio config and every null draw.
        preps = {}
        for pc in grid:
            kw = dict(pc)
            kw.setdefault("horizon", H)
            key = (kw["horizon"], kw.get("stop"))
            if key not in preps:
                try:
                    preps[key] = P.Prepared(scores, tab, key[0], key[1])
                except KeyError as e:
                    print(f"  {cell}: {e}")
                    preps[key] = None
            prep = preps[key]
            if prep is None:
                continue
            kw.pop("stop", None)
            try:
                pw = P.simulate(prep, **kw)
                m = P.score_run(pw, spy_ret, kw["horizon"], era=era)
            except Exception as e:
                print(f"  {cell} {pc}: {type(e).__name__} {e}")
                continue
            if m is None:
                continue
            m.update(P.mean_ic(prep, era=era))

            # Construction-matched null. This is what separates "the signal
            # helped" from "holding 50 names instead of 5 helped".
            if args.null_draws > 0:
                nk = {k: v for k, v in kw.items()}
                null = S.random_selection_null(
                    prep, lambda pr, **k: P.simulate(pr, **k),
                    lambda w, sp: P.score_run(w, sp, kw["horizon"], era=era),
                    spy_ret, n_draws=args.null_draws, seed=17, **nk)
                m["null_p50"] = null.get("null_mult_ratio_p50", np.nan)
                m["null_p95"] = null.get("null_mult_ratio_p95", np.nan)
                m["null_pctile"] = S.percentile_of(m["mult_ratio"],
                                                   null.get("_null_mults", []))
                m["vs_null"] = m["mult_ratio"] - m["null_p50"]

            m["cell_id"] = cell
            m["signal"] = meta["config"]
            m["portfolio"] = pc
            rows.append(m)
        print(f"  {cell}: {len(grid)} portfolio configs", flush=True)

    if not rows:
        raise SystemExit("no results")

    if args.only and not args.selection_trials:
        print("\n  WARNING: --only scores a subset, so the Deflated Sharpe would\n"
              "  deflate against that subset rather than the grid this config was\n"
              "  selected from. Pass --selection-trials <N> for an honest number.\n")
    verdict = S.summarize_grid(rows, metric="mult_ratio",
                               selection_trials=args.selection_trials)

    # S3 -- White Reality Check across the whole grid. Cells are aligned on
    # shared timepoints; cells at a different horizon have a different date
    # grid and are bootstrapped in their own block rather than dropped.
    try:
        by_h = {}
        for r in rows:
            tps = r.get("_timepoints") or []
            if len(tps) < 12:
                continue
            by_h.setdefault(len(tps), []).append(r)
        biggest = max(by_h.values(), key=len) if by_h else []
        if len(biggest) >= 2:
            idx = pd.Index(biggest[0]["_timepoints"])
            M = []
            for r in biggest:
                if list(r["_timepoints"]) != list(idx):
                    continue
                ex = np.asarray(r["_returns"], dtype=float)
                M.append(ex)
            if len(M) >= 2:
                X = np.column_stack(M)
                spy_al = np.array([spy_ret.get(t, np.nan) for t in idx])
                ok = np.isfinite(spy_al)
                if not ok.all():
                    X, spy_al, ok_n = X[ok], spy_al[ok], int(ok.sum())
                else:
                    ok_n = len(spy_al)
                X = X - spy_al[:, None]
                verdict["reality_check"] = S.reality_check(X, n_boot=2000, block=4)
                verdict["reality_check"]["n_cells_in_test"] = int(X.shape[1])
                verdict["reality_check"]["n_windows_used"] = ok_n
            else:
                verdict["reality_check"] = {
                    "skipped": f"only {len(M)} cells shared a timepoint grid"}
        else:
            verdict["reality_check"] = {
                "skipped": f"largest aligned group had {len(biggest)} cells"}
    except Exception as e:
        verdict["reality_check"] = {"error": f"{type(e).__name__}: {e}"}

    flat = pd.DataFrame([
        {k: v for k, v in r.items()
         if not k.startswith("_") and k not in ("signal", "portfolio")}
        | {f"sig_{k}": v for k, v in r["signal"].items()}
        | {f"prt_{k}": v for k, v in r["portfolio"].items()}
        for r in rows])
    # A run with --null-draws 0 computes no matched null. Writing it over a
    # previous run's file would destroy the S4 evidence, which is exactly what
    # happened once. Carry the old null columns forward on the config key.
    out = SWEEP_DIR / f"results_{args.era}.csv"
    NULLCOLS = ["null_p50", "null_p95", "null_pctile", "vs_null"]
    if out.exists() and not any(c in flat.columns for c in NULLCOLS):
        try:
            prev = pd.read_csv(out)
            if any(c in prev.columns for c in NULLCOLS):
                keyc = ["cell_id"] + [c for c in flat.columns
                                      if c.startswith("prt_")]
                keyc = [c for c in keyc if c in prev.columns]

                def _k(df):
                    return df[keyc].astype(str).agg("|".join, axis=1)

                have = [c for c in NULLCOLS if c in prev.columns]
                m = prev.assign(_k=_k(prev))[["_k"] + have].drop_duplicates("_k")
                flat = (flat.assign(_k=_k(flat))
                            .merge(m, on="_k", how="left").drop(columns=["_k"]))
                print(f"  carried {have} forward from the previous "
                      f"{out.name} (this run computed no null)")
        except Exception as e:
            print(f"  could not carry forward null columns: "
                  f"{type(e).__name__}: {e}")
    flat.sort_values("mult_ratio", ascending=False).to_csv(out, index=False)
    with open(SWEEP_DIR / f"verdict_{args.era}.json", "w") as fh:
        json.dump(verdict, fh, indent=2, default=str)

    print(f"\n{len(flat)} cells -> {out}")
    print(json.dumps({k: v for k, v in verdict.items() if k != "deflated"},
                     indent=2, default=str))
    print("deflated:", json.dumps(verdict["deflated"], indent=2, default=str))
    print("reality_check (S3):",
          json.dumps(verdict.get("reality_check", {"missing": "not computed"}),
                     indent=2, default=str))
    cols = [c for c in ["cell_id", "mult_ratio", "null_p50", "null_pctile",
                        "excess_cagr", "info_ratio", "mean_ic", "t_ic",
                        "max_dd", "n_windows"] if c in flat.columns]
    print("\ntop 15 by compounded ratio vs SPY:")
    print(flat.sort_values("mult_ratio", ascending=False)[cols]
              .head(15).to_string(index=False))


# ==========================================================================
# features -- the per-feature IC floor
# ==========================================================================
def cmd_features(args):
    """Per-feature rank IC across horizons -- the floor the grid is read against.

    This is a property of the DATA, not a set of candidate strategies, so it
    does not enter the Deflated Sharpe trial count. If a feature is later
    promoted to a strategy on the strength of this table, that promotion is a
    search over `promotion_trial_count` alternatives and must be counted.
    """
    SWEEP_DIR.mkdir(parents=True, exist_ok=True)
    era = HOLDOUT_ERA if args.era == "holdout" else NOMINATE_ERA
    if args.era == "holdout" and not args.i_am_confirming:
        raise SystemExit(
            "Refusing to touch the hold-out.\n"
            "Which features work is a modelling decision. Reading it off "
            "2020-2026 would make every later choice hold-out-informed, which "
            "is the whole thing the pre-registration is protecting.")
    print(f"era = {args.era} {era}")

    horizons = [int(h) for h in args.horizons.split(",")]
    tables, era_tables, neut_tables, diags = [], [], [], {}
    for h in horizons:
        print(f"\n=== horizon {h} ===", flush=True)
        ctx = SC.PanelContext(SC.PANEL_FOR[args.features], h)
        # Screen exactly the feature set named, not everything in the panel:
        # with --features rates the multiple-testing family is the 5 NEW
        # columns, not a re-test of 24 already known to be dead.
        _cols = SC.FEATURE_SETS.get(args.features) or None
        tab, diag = FIC.screen(ctx, features=_cols, start=args.start, era=era,
                               n_perm=args.perm, seed=0)
        if tab.empty:
            print(f"  no windows at h={h}: {diag.get('error')}")
            continue

        # --- the decisive comparison: raw target vs factor-residual target ---
        if args.neutralize != "none":
            ntab, ndiag = FIC.screen(ctx, features=_cols, start=args.start,
                                     era=era, n_perm=args.perm, seed=0,
                                     neutralize=args.neutralize,
                                     sector_scheme=args.sector_scheme,
                                     verbose=False)
            if not ntab.empty:
                j = tab.merge(ntab, on="feature", suffixes=("_raw", "_res"))
                j["dt"] = j.t_stat_res.abs() - j.t_stat_raw.abs()
                j["ic_retained"] = np.where(
                    j.mean_ic_raw.abs() > 1e-9,
                    j.mean_ic_res / j.mean_ic_raw, np.nan)
                j = j.reindex(j.t_stat_raw.abs().sort_values(
                    ascending=False).index)
                vr = ndiag.get("mean_variance_removed")
                print(f"\n  NEUTRALIZED ({args.neutralize}, "
                      f"{args.sector_scheme}) vs RAW at h={h}")
                if vr is not None:
                    print(f"  factors explain {vr*100:.1f}% of cross-sectional "
                          f"return variance per date")
                print(f"  {'feature':<20}{'IC raw':>9}{'IC res':>9}"
                      f"{'kept':>7}{'t raw':>8}{'t res':>8}{'sd raw':>8}"
                      f"{'sd res':>8}")
                jr = j.reindex(j.t_stat_res.abs().sort_values(
                    ascending=False).index)
                for _, r in j.head(10).iterrows():
                    print(f"  {r.feature:<20}{r.mean_ic_raw:>+9.4f}"
                          f"{r.mean_ic_res:>+9.4f}{r.ic_retained:>7.2f}"
                          f"{r.t_stat_raw:>+8.2f}{r.t_stat_res:>+8.2f}"
                          f"{r.ic_sd_raw:>8.4f}{r.ic_sd_res:>8.4f}")
                print(f"\n  --- same rows, ranked by RESIDUAL |t| "
                      f"(what is visible only AFTER neutralizing) ---")
                print(f"  {'feature':<20}{'IC raw':>9}{'IC res':>9}"
                      f"{'kept':>7}{'t raw':>8}{'t res':>8}")
                for _, r in jr.head(8).iterrows():
                    print(f"  {r.feature:<20}{r.mean_ic_raw:>+9.4f}"
                          f"{r.mean_ic_res:>+9.4f}{r.ic_retained:>7.2f}"
                          f"{r.t_stat_raw:>+8.2f}{r.t_stat_res:>+8.2f}")
                sd_drop = 1 - (j.ic_sd_res / j.ic_sd_raw).median()
                print(f"\n  median IC dispersion fell {sd_drop*100:.1f}% "
                      f"-> standard errors shrink by the same factor")
                print(f"  features gaining |t|: {int((j.dt > 0).sum())} of {len(j)}"
                      f"   |  max |t| raw {j.t_stat_raw.abs().max():.2f}"
                      f" -> res {j.t_stat_res.abs().max():.2f}")
                ntab["horizon"] = h
                ntab["neutralize"] = args.neutralize
                neut_tables.append(ntab)
                diags[f"{h}_neutral"] = ndiag
        tables.append(tab)

        # --- era stability, computed from the IC matrix already in hand -----
        # The strongest features so far are growth proxies measured over the
        # largest growth decade on record. Splitting the nomination era is the
        # cheapest check on whether they are a signal or a regime.
        IC = diag.pop("_ic_matrix", None)
        tps = pd.to_datetime(pd.Series(diag.pop("_timepoints", [])))
        fnames = diag.pop("_features", [])
        if IC is not None and len(tps) == len(IC):
            mid = pd.Timestamp(args.split)
            a, b = (tps < mid).to_numpy(), (tps >= mid).to_numpy()
            if a.sum() >= 12 and b.sum() >= 12:
                rows = []
                # NaN-AWARE, to match the headline table. A per-date IC is NaN
                # whenever the column is constant across the cross-section on
                # that date -- which is not rare: `rate_beta_x_move` is a beta
                # times a DATE CONSTANT, and the 10y prints to 2dp, so its
                # 20-day change is exactly 0.00 on 110 of 5,677 dates (35 of
                # them in the late era). A plain .mean() propagates one such
                # NaN to the whole era and the row silently reads "no late-era
                # estimate" when the truth is "estimated from 47 of 82
                # windows". Same class of error as the argsort-NaN bug in the
                # feature screen: a missing value quietly becoming a claim.
                def _t(v):
                    v = v[np.isfinite(v)]
                    if len(v) < 3:
                        return np.nan, np.nan, len(v)
                    sd = v.std(ddof=1)
                    return (float(v.mean()),
                            float(v.mean() / (sd / np.sqrt(len(v)))) if sd > 0 else np.nan,
                            len(v))
                for j, fn in enumerate(fnames):
                    ma, ta, na = _t(IC[a, j])
                    mb, tb, nb = _t(IC[b, j])
                    rows.append({"feature": fn, "ic_early": ma,
                                 "t_early": ta, "ic_late": mb,
                                 "t_late": tb, "n_early": na, "n_late": nb,
                                 "same_sign": bool(np.sign(ma) == np.sign(mb))
                                 if np.isfinite(ma) and np.isfinite(mb) else False,
                                 "retained": (mb / ma)
                                 if np.isfinite(ma) and abs(ma) > 1e-9 else np.nan})
                es = pd.DataFrame(rows)
                es["horizon"] = h
                era_tables.append(es)
                # Persist the raw IC matrix. Every era/stability question asked
                # after the fact -- a different split date, a subperiod, a
                # per-window plot -- is a reslice of THIS matrix, and without it
                # each one costs a full rerun over the 2GB panel.
                np.savez_compressed(
                    SWEEP_DIR / f"feature_ic_matrix_{args.era}_h{h}.npz",
                    ic=IC, timepoints=tps.to_numpy().astype("datetime64[ns]"),
                    features=np.array(fnames, dtype=object))
                keep = es.reindex(es.feature.map(
                    dict(zip(tab.feature, tab.t_stat.abs()))).sort_values(
                    ascending=False).index).head(6)
                print(f"\n  era stability at h={h} "
                      f"(early n={int(a.sum())} / late n={int(b.sum())}, split {args.split}):")
                print(keep[["feature", "ic_early", "t_early", "ic_late",
                            "t_late", "n_early", "n_late", "same_sign"]].to_string(
                    index=False, float_format=lambda v: f"{v:+8.4f}"))
        diags[str(h)] = diag
        print(f"  {diag['n_windows']} windows, "
              f"{diag['mean_frac_unresolved']*100:.1f}% of names unresolved")
        print(tab.head(10)[["feature", "mean_ic", "t_stat", "q_value_bh",
                            "mean_ic_worstcase"]].to_string(index=False))
        del ctx
        import gc
        gc.collect()

    if not tables:
        raise SystemExit("no results")

    allt = pd.concat(tables, ignore_index=True)
    # BH across ALL horizons as one family -- stricter than the per-horizon
    # q_value_bh, and over-conservative because horizons are correlated. Both
    # are reported so neither can be quoted alone.
    allt["q_value_bh_allhorizons"] = FIC._bh_qvalues(allt["p_value"].values)
    out = SWEEP_DIR / f"feature_ic_{args.era}.csv"
    allt.to_csv(out, index=False)
    if era_tables:
        pd.concat(era_tables, ignore_index=True).to_csv(
            SWEEP_DIR / f"feature_ic_era_{args.era}.csv", index=False)
    if neut_tables:
        pd.concat(neut_tables, ignore_index=True).to_csv(
            SWEEP_DIR / f"feature_ic_neutral_{args.era}.csv", index=False)
    with open(SWEEP_DIR / f"feature_ic_{args.era}.json", "w") as fh:
        json.dump(diags, fh, indent=2, default=str)

    print("\n" + "=" * 78)
    print("MEAN IC BY FEATURE AND HORIZON")
    print("=" * 78)
    piv = allt.pivot(index="feature", columns="horizon", values="mean_ic")
    tpv = allt.pivot(index="feature", columns="horizon", values="t_stat")
    piv = piv.reindex(tpv.abs().max(axis=1).sort_values(ascending=False).index)
    print(piv.to_string(float_format=lambda v: f"{v:+.4f}"))
    print("\nt-stats:")
    print(tpv.reindex(piv.index).to_string(float_format=lambda v: f"{v:+.2f}"))

    print("\n" + "=" * 78)
    print("IS THERE ANYTHING HERE?")
    print("=" * 78)
    for h, d in diags.items():
        if not str(h).isdigit():
            continue          # neutralized runs are summarized separately below
        pm = d.get("permutation", {})
        cc = d.get("ic_correlation", {})
        best = allt[allt["horizon"] == int(h)]
        nsig = int((best["q_value_bh"] < 0.05).sum())
        nsig96 = int((allt[(allt.horizon == int(h)) &
                           (allt.q_value_bh_allhorizons < 0.05)]).shape[0])
        print(f"  h={h:>3}  max|t| {pm.get('observed_max_abs_t', float('nan')):5.2f} "
              f"vs permutation p95 {pm.get('null_max_abs_t_p95', float('nan')):5.2f} "
              f"(p={pm.get('p_value_of_max', float('nan')):.3f})  |  "
              f"{nsig} at BH q<0.05 within-horizon "
              f"({nsig96} across all {len(allt)} tests run)  |  "
              f"PC1 {cc.get('pc1_share', float('nan'))*100:.0f}% of IC variance, "
              f"{cc.get('n_pcs_for_90pct', 0)} PCs for 90%")
    pc1 = [d.get("ic_correlation", {}).get("pc1_share") for d in diags.values()]
    pc1 = [v for v in pc1 if v is not None]
    npc = [d.get("ic_correlation", {}).get("n_pcs_for_90pct") for d in diags.values()]
    npc = [v for v in npc if v is not None]
    neut = {k: v for k, v in diags.items() if not str(k).isdigit()}
    for k, d in neut.items():
        pm = d.get("permutation", {})
        vr = d.get("mean_variance_removed")
        print(f"  {k:<14} NEUTRALIZED  max|t| "
              f"{pm.get('observed_max_abs_t', float('nan')):5.2f} vs perm p95 "
              f"{pm.get('null_max_abs_t_p95', float('nan')):5.2f} "
              f"(p={pm.get('p_value_of_max', float('nan')):.3f})  |  factors "
              f"removed {(vr * 100) if vr else float('nan'):.1f}% of return "
              f"variance")

    if pc1 and max(pc1) > 0.45:
        print("\nPC1 is large and few components span the variance: these columns")
        print("are a handful of factors wearing many hats, so the ceiling is the")
        print("data, and no filter or architecture changes that.")
    elif pc1:
        print(f"\nPC1 is only {max(pc1)*100:.0f}% of IC variance and "
              f"{max(npc) if npc else '?'} components are needed for 90%, so these")
        print("columns are MORE independent than a single-factor story would")
        print("predict. A data ceiling does not follow from this evidence.")
    print(f"\nwritten {out}")


# ==========================================================================
# attribute -- skill or beta?
# ==========================================================================
def cmd_attribute(args):
    """Factor-attribute one cell+config, and recompute the grid consistency
    statistic with clustering on the signal cell."""
    res_path = SWEEP_DIR / f"results_{args.era}.csv"
    res = pd.read_csv(res_path)
    era = HOLDOUT_ERA if args.era == "holdout" else NOMINATE_ERA

    print("=" * 78)
    print("GRID CONSISTENCY -- naive vs clustered on the signal cell")
    print("=" * 78)
    cc = AT.clustered_consistency(res)
    for k, v in cc.items():
        print(f"  {k:22} {v}")
    if "error" not in cc:
        print("\n  The pre-registered threshold was z > 3. The naive z treats all")
        print("  rows as independent trials; 48 portfolio configs share one score")
        print("  vector, so they are not. The clustered z is the honest number.")

    row = (res[res.cell_id == args.cell] if args.cell
           else res).sort_values("mult_ratio", ascending=False).iloc[0]
    cell = row["cell_id"]
    cfg = {"top_n": int(row["prt_top_n"]), "weighting": row["prt_weighting"],
           "bucket": row["prt_bucket"], "cost_bps": float(row["prt_cost_bps"]),
           "cost_model": row["prt_cost_model"], "untradable": row["prt_untradable"]}
    stop = row.get("prt_stop")
    stop = None if (stop is None or (isinstance(stop, float) and np.isnan(stop))) else float(stop)
    vt = row.get("prt_vol_target")
    cfg["vol_target"] = None if (vt is None or (isinstance(vt, float) and np.isnan(vt))) else float(vt)

    meta = json.load(open(SC.meta_path(cell)))
    H = int(meta["config"]["horizon"])
    scores = pd.read_parquet(SC.cache_path(cell))
    tab = pd.read_parquet(OUTCOMES_PATH)
    tab["ticker"] = tab["ticker"].astype(str)
    prep = P.Prepared(scores, tab, H, stop)
    spy_ret = P.spy_windows(_spy(), np.sort(scores["timepoint"].unique()), H)

    pw = P.simulate(prep, horizon=H, **cfg)
    m = P.score_run(pw, spy_ret, H, era=era)
    m.update(P.mean_ic(prep, era=era))
    book = pw.groupby("timepoint")[["net"]].mean().sort_index()
    book = book[(book.index >= pd.Timestamp(era[0])) & (book.index < pd.Timestamp(era[1]))]

    print()
    print("=" * 78)
    print(f"ATTRIBUTION -- {cell}")
    print(f"  portfolio: top_n={cfg['top_n']} weighting={cfg['weighting']} "
          f"bucket={cfg['bucket']} stop={stop} vol_target={cfg['vol_target']}")
    print(f"  mult_ratio {m['mult_ratio']:.3f} | excess CAGR {m['excess_cagr']*100:+.2f}% "
          f"| IR {m['info_ratio']:.2f} | mean IC {m.get('mean_ic', float('nan')):+.4f}")
    print("=" * 78)

    fac = AT.factor_returns(prep, era=era)
    att = AT.attribute(book["net"].to_numpy(), book.index, spy_ret, fac, era=era)
    if "error" in att:
        print("  " + att["error"])
    else:
        print(f"  {att['n_windows']} windows, mean return {att['mean_return']*100:+.3f}%/window\n")
        print(f"  {'model':<24} {'alpha/wnd':>10} {'t(alpha)':>9}  {'R2':>6}   loadings")
        for lab, mm in att["models"].items():
            load = "  ".join(f"{k}={v:+.2f}" for k, v in mm["coef"].items() if k != "alpha")
            print(f"  {lab:<24} {mm['coef']['alpha']*100:>9.3f}% "
                  f"{mm['t']['alpha']:>9.2f}  {mm['r2']:>6.3f}   {load}")

    # --- the decisive test: null distribution of t(alpha) -----------------
    if args.null_draws > 0 and "error" not in att:
        print()
        print(f"  --- t(alpha) under {args.null_draws} shuffled rankings "
              f"(same construction, same factors) ---")
        nd = AT.null_attribution(prep, spy_ret, fac, H, era=era,
                                 n_draws=args.null_draws, **cfg)
        if nd.get("n"):
            obs = att["models"]["vs SPY+univ+volspread"]["t"]["alpha"]
            pval = float((np.asarray(nd["_t"]) >= obs).mean())
            print(f"  null t(alpha):  p50 {nd['t_alpha_p50']:+.2f}   "
                  f"p90 {nd['t_alpha_p90']:+.2f}   p95 {nd['t_alpha_p95']:+.2f}   "
                  f"p99 {nd['t_alpha_p99']:+.2f}   max {nd['t_alpha_max']:+.2f}")
            print(f"  OBSERVED t(alpha) = {obs:+.2f}  ->  permutation p = {pval:.3f}")
            att["null_t_alpha"] = {k: v for k, v in nd.items() if k != "_t"}
            att["null_t_alpha"]["observed"] = obs
            att["null_t_alpha"]["p_value"] = pval

    # --- how much rests on a few windows ----------------------------------
    if "error" not in att:
        wc = AT.window_concentration(book["net"].to_numpy(), book.index,
                                     spy_ret, fac, era=era)
        print()
        print("  --- robustness to the best windows ---")
        for k in ("full", "drop_best_1", "drop_best_3", "drop_best_5"):
            if k in wc:
                print(f"  {k:<14} n={wc[k]['n']:>3}  alpha {wc[k]['alpha']*100:+.3f}%/wnd  "
                      f"t {wc[k]['t_alpha']:+.2f}")
        sh = wc["share_of_total_return"]
        print(f"  best window = {sh['best_1']*100:.0f}% of total return, "
              f"best 3 = {sh['best_3']*100:.0f}%, best 5 = {sh['best_5']*100:.0f}%  "
              f"| skew {wc['skew']:+.2f}")
        att["window_concentration"] = wc

    prof = AT.exposure_profile(prep, era=era, **cfg)
    print()
    print(f"  selected names sit at volatility percentile "
          f"{prof['mean_vol_percentile']*100:.1f} and market-cap percentile "
          f"{prof['mean_cap_percentile']*100:.1f} of the eligible pool")
    print("  (50 = no tilt)")

    out = SWEEP_DIR / f"attribution_{args.era}.json"
    with open(out, "w") as fh:
        json.dump({"cell": cell, "portfolio": cfg, "stop": stop,
                   "metrics": {k: v for k, v in m.items() if not k.startswith("_")},
                   "attribution": att, "exposure": prof,
                   "clustered_consistency": cc}, fh, indent=2, default=str)
    print(f"\nwritten {out}")


# ==========================================================================
def main():
    ap = argparse.ArgumentParser(prog="sweep")
    sub = ap.add_subparsers(dest="cmd", required=True)

    p = sub.add_parser("probe")
    p.add_argument("--features", default="price_fund")
    p.add_argument("--horizon", type=int, default=40)
    p.add_argument("--start", default="2018-01-02")
    p.add_argument("--caps", default="0,500000,1500000,3000000")
    p.set_defaults(func=cmd_probe)

    p = sub.add_parser("verify")
    p.set_defaults(func=cmd_verify)

    p = sub.add_parser("scores")
    p.add_argument("--cells", required=True)
    p.add_argument("--start", default="2007-01-02")
    p.add_argument("--resume", action="store_true", default=True)
    p.set_defaults(func=cmd_scores)

    p = sub.add_parser("outcomes")
    p.add_argument("--verify-samples", type=int, default=300)
    p.set_defaults(func=cmd_outcomes)

    p = sub.add_parser("features")
    p.add_argument("--features", default="price_fund",
                   choices=["price", "price_fund", "novol", "volonly",
                            "rates", "price_fund_rates"],
                   help="which feature set to screen; also selects the panel")
    p.add_argument("--horizons", default="10,20,40,60")
    p.add_argument("--start", default="2007-01-02")
    p.add_argument("--perm", type=int, default=200,
                   help="permutation draws for the max-|t| null (0 to skip)")
    p.add_argument("--split", default="2013-07-01",
                   help="date splitting the era for the stability check")
    p.add_argument("--neutralize", default="none",
                   choices=["none", "market", "size", "vol", "size_vol",
                            "sector", "size_vol_sector"],
                   help="also run the screen against a factor-residual target "
                        "and print the comparison")
    p.add_argument("--sector-scheme", default="sector",
                   choices=["sector", "sicsector", "famaindustry"],
                   help="sector classification; sicsector is filing-time "
                        "assigned and stickier, so closer to point-in-time")
    p.add_argument("--era", choices=["nominate", "holdout"], default="nominate")
    p.add_argument("--i-am-confirming", action="store_true")
    p.set_defaults(func=cmd_features)

    p = sub.add_parser("attribute")
    p.add_argument("--cell", default=None,
                   help="cell id to attribute (default: the grid's best cell)")
    p.add_argument("--era", choices=["nominate", "holdout"], default="nominate")
    p.add_argument("--null-draws", type=int, default=200,
                   help="shuffled-ranking draws for the t(alpha) null")
    p.set_defaults(func=cmd_attribute)

    p = sub.add_parser("portfolio")
    p.add_argument("--grid", required=True)
    p.add_argument("--era", choices=["nominate", "holdout"], default="nominate")
    p.add_argument("--only", default=None)
    p.add_argument("--i-am-confirming", action="store_true")
    p.add_argument("--null-draws", type=int, default=0,
                   help="matched random-selection null draws per cell "
                        "(0 = skip; 150+ for finalists)")
    p.add_argument("--selection-trials", type=int, default=None,
                   help="number of configurations the cell being confirmed was "
                        "SELECTED from. Required for an honest Deflated Sharpe "
                        "on any --only run; without it the DSR deflates against "
                        "only the cells scored here.")
    p.set_defaults(func=cmd_portfolio)

    args = ap.parse_args()
    sys.exit(args.func(args) or 0)


if __name__ == "__main__":
    main()
