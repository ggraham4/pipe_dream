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
from sweep import _num                                     # noqa: E402
from sweep import factors as F                             # noqa: E402
from sweep import breadth as B                             # noqa: E402

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


def cmd_breadth(args):
    """Round 15. Effective breadth: B1 measure, B2 rank-depth, B3 intervention.

    Pre-registered in claude/2026-09-11-round15-breadth-preregistration.md.
    The gates below are the ones written there and are not restated loosely:
      B1  instrumentation only, NO decision rides on it
      B2  CONCENTRATED if top decile beats second by >= 2 SE, else FLAT
      B3  PASS requires (a) BR_eff x>=1.5 AND (b) matched-null pctile >= 0.95
    """
    cell = args.cell
    meta = json.load(open(SC.meta_path(cell)))
    H = int(meta["config"]["horizon"])
    scores = pd.read_parquet(SC.cache_path(cell))
    tab = pd.read_parquet(OUTCOMES_PATH)
    tab["ticker"] = tab["ticker"].astype(str)
    era = HOLDOUT_ERA if args.era == "holdout" else NOMINATE_ERA
    if args.era == "holdout":
        raise SystemExit(
            "Round 15 is declared nomination-era only. The 2020-2026 hold-out "
            "was spent on the Round 13 breadth choice and no result in this "
            "round licenses touching it again.")
    print(f"era = {args.era} {era}\ncell = {cell}  (horizon {H})")

    stop = None if args.stop is None else float(args.stop)
    prep = P.Prepared(scores, tab, H, stop)
    spy_ret = P.spy_windows(_spy(), np.sort(scores["timepoint"].unique()), H)
    smap = F.load_sector_map()

    print("\n--- definition anchors (independent -> N, correlated -> 1) ---")
    if not B.self_test():
        raise SystemExit("breadth definition failed its own anchors; nothing below is usable")

    base = dict(horizon=H, top_n=args.top_n, weighting=args.weighting,
                bucket=args.bucket)

    # ------------------------------------------------------------------ B1
    print("\n" + "=" * 78)
    print("B1 -- WHERE THE BREADTH GOES  (instrumentation; no gate)")
    print("=" * 78)
    lad = B.breadth_ladder(prep, spy_ret, sector_map=smap, **base)
    if len(lad):
        cols = ["stage", "n_windows", "mean_positions", "N_w", "ceiling",
                "BR_eff", "BR_eff_annual", "rho_bar", "capture"]
        print(lad[[c for c in cols if c in lad.columns]].to_string(
            index=False, float_format=lambda v: f"{v:8.3f}"))
        print("\n  'ceiling' is the max breadth these weights could reach if the")
        print("  positions were independent; BR_eff <= ceiling always. Under")
        print("  invvol with a good vol forecast the risk weights come out")
        print("  uniform, so the ceiling sits at ~N and any shortfall below it")
        print("  is CORRELATION, not weighting. 'capture' = BR_eff / ceiling is")
        print("  the fraction of the nominal bets that are actually independent.")
        print("  (N_w is the cash-weight count, shown for reference only -- it is")
        print("  NOT the ceiling when position variances differ, which is the")
        print("  error the first version of this module shipped.) If BR_eff rises")
        print("  as factors are removed, the portfolio is re-loading a factor the")
        print("  feature screen already stripped -- a CONSTRUCTION defect, and")
        print("  fixable. If it does not move, the correlation is in the assets")
        print("  and no selection rule buys breadth.")

    for n in args.breadth_scan:
        r = B.effective_breadth(
            B.position_rows(prep, spy_ret, **{**base, "top_n": int(n)}), H)
        if r.get("n_windows", 0):
            print(f"  top_n={int(n):3d}   ceiling {r['ceiling']:6.2f}   "
                  f"BR_eff {r['BR_eff']:6.2f}   capture {r['capture']:5.3f}   "
                  f"rho_bar {r['rho_bar']:+.3f}")

    # ------------------------------------------------------------------ B2
    print("\n" + "=" * 78)
    print("B2 -- IS IC CONCENTRATED AT THE TOP, OR FLAT?")
    print("=" * 78)
    dec = B.decile_active(prep, spy_ret, era=era)
    if len(dec):
        print(dec.to_string(index=False, float_format=lambda v: f"{v:+8.4f}"))
        tv = dec.attrs.get("top_vs_second", {})
        if tv:
            print(f"\n  top decile - second: {tv['diff']:+.4f} "
                  f"(SE {tv['se']:.4f}, t {tv['t']:+.2f})")
            print(f"  PRE-REGISTERED VERDICT: {tv['verdict']}")
            if tv["verdict"] == "FLAT":
                print("  -> the ranking does not concentrate. Extra breadth costs")
                print("     no IC, and the hold-out ordering (top-5 1.526x >")
                print("     top-20 0.909x > top-50 0.813x) was noise, consistent")
                print("     with 27% of ZERO-SIGNAL configs beating the market here.")
            else:
                print("  -> breadth genuinely trades off against IC; maximise")
                print("     IC(k)*sqrt(BR(k)), do not maximise breadth.")

    # ------------------------------------------------------------------ B3
    print("\n" + "=" * 78)
    print("B3 -- NEUTRALIZE AT SELECTION  (gate: BR_eff x>=1.5 AND null pctile >=0.95)")
    print("=" * 78)
    rprep = B.residualized_prepared(prep, spec=args.spec, sector_map=smap)

    out = []
    for label, pr in (("raw scores", prep), (f"resid ({args.spec})", rprep)):
        rows = B.position_rows(pr, spy_ret, **base)
        br = B.effective_breadth(rows, H)
        pw = P.simulate(pr, cost_bps=args.cost_bps, **base)
        m = P.score_run(pw, spy_ret, H, era=era)
        rec = {"variant": label, "ceiling": br.get("ceiling"),
               "BR_eff": br.get("BR_eff"),
               "capture": br.get("capture"), "rho_bar": br.get("rho_bar"),
               "mult_ratio": (m or {}).get("mult_ratio"),
               "excess_cagr": (m or {}).get("excess_cagr")}

        # (b) the gate that actually decides. Breadth cuts variance drag and
        # improves compounded return with ZERO signal, so the comparison is
        # against the construction-matched null, never against SPY.
        if args.null_draws:
            nl = S.random_selection_null(
                pr, P.simulate, lambda p, s: P.score_run(p, s, H, era=era),
                spy_ret, n_draws=args.null_draws, seed=17,
                cost_bps=args.cost_bps, **base)
            rec["null_p50"] = nl.get("null_mult_ratio_p50")
            rec["null_p95"] = nl.get("null_mult_ratio_p95")
            rec["null_pctile"] = S.percentile_of(rec["mult_ratio"],
                                                  nl.get("_null_mults", []))
        out.append(rec)

    res = pd.DataFrame(out)
    print(res.to_string(index=False, float_format=lambda v: f"{v:8.4f}"))

    if len(res) == 2 and res["BR_eff"].notna().all():
        ratio = res.BR_eff.iloc[1] / res.BR_eff.iloc[0]
        a_pass = ratio >= 1.5
        pct = res.get("null_pctile")
        b_pass = bool(pct is not None and pd.notna(pct.iloc[1]) and pct.iloc[1] >= 0.95)
        print(f"\n  (a) BR_eff {res.BR_eff.iloc[0]:.2f} -> {res.BR_eff.iloc[1]:.2f} "
              f"= {ratio:.2f}x   threshold 1.50x   {'PASS' if a_pass else 'FAIL'}")
        if pct is not None and pd.notna(pct.iloc[1]):
            print(f"  (b) matched-null percentile {pct.iloc[1]:.3f}   "
                  f"threshold 0.950   {'PASS' if b_pass else 'FAIL'}")
        else:
            print("  (b) NOT RUN -- pass --null-draws 200. Without it there is no")
            print("      gate at all: a breadth gain improves compounded return")
            print("      with zero signal, and (a) alone cannot tell the two apart.")
        print(f"\n  B3 VERDICT: {'PASS' if (a_pass and b_pass) else 'FAIL'}")
        if a_pass and not b_pass:
            print("  This is the failure mode named in the pre-registration:")
            print("  residualizing ranks the RESIDUAL of a model with no signal.")
            print("  Breadth was a construction defect AND there is nothing to")
            print("  amplify. Reported as FAIL, not as a breadth success.")

    # ------------------------------------------------------------------ B4
    print("\n" + "=" * 78)
    print("B4 -- POWER RESTATEMENT AT THE ACHIEVED BREADTH")
    print("=" * 78)
    for _, r in res.iterrows():
        if not np.isfinite(r.get("BR_eff", np.nan)):
            continue
        n_eff = r["BR_eff"] * len(prep.tps)
        mdi = 2.8 / np.sqrt(max(n_eff, 1.0))
        print(f"  {r['variant']:<22} BR_eff {r['BR_eff']:6.2f}  "
              f"effective n {n_eff:8.0f}  min detectable IC {mdi:.4f}")
    print("\n  Round 13 observed neutralized ICs were 0.001-0.014. If the minimum")
    print("  detectable IC above still exceeds those, the honest conclusion is")
    print("  STILL UNDERPOWERED, not 'no signal' -- the distinction Round 12 got")
    print("  wrong once and had to walk back.")

    res.to_csv(SWEEP_DIR / f"breadth_{args.era}.csv", index=False)
    if len(lad):
        lad.to_csv(SWEEP_DIR / f"breadth_ladder_{args.era}.csv", index=False)
    print(f"\nwritten {SWEEP_DIR / f'breadth_{args.era}.csv'}")

def cmd_horizon(args):
    """Round 15b / gate B5. Does the horizon breadth lever survive its costs?

    Pre-registered in claude/2026-09-12-round15b-horizon-cost-preregistration.md.
    PASS requires ALL THREE, evaluated ONLY at 15bp:
      (a) best cell's net mult_ratio beats the deployed H=40/top-5 cell
      (b) that cell >= 95th pctile of its OWN construction-matched null
      (c) it survives leave-one-year-out against the deployed cell
    Multiplicity declared up front: 3 horizons x 4 book sizes = 12 cells.
    """
    tab = pd.read_parquet(OUTCOMES_PATH)
    tab["ticker"] = tab["ticker"].astype(str)
    spy = _spy()
    era = NOMINATE_ERA
    if args.era != "nominate":
        raise SystemExit(
            "Round 15b is nomination-era only. The 2020-2026 hold-out was spent "
            "on the Round 13 breadth choice and nothing in 15/15b licenses it.")
    print(f"era = nominate {era}")

    cells = dict(c.split("=", 1) for c in args.cells)
    cells = {int(k): v for k, v in cells.items()}
    GATE_BPS = 15.0
    print(f"grid: {len(cells)} horizons x {len(args.top_ns)} book sizes = "
          f"{len(cells) * len(args.top_ns)} cells   (gate evaluated at {GATE_BPS:.0f}bp only)")

    ctx, rows = {}, []
    for H in sorted(cells):
        scores = pd.read_parquet(SC.cache_path(cells[H]))
        prep = P.Prepared(scores, tab, H, None)
        spy_ret = P.spy_windows(spy, np.sort(scores["timepoint"].unique()), H)
        ctx[H] = (prep, spy_ret, cells[H])
        for tn in args.top_ns:
            base = dict(horizon=H, top_n=int(tn), weighting="invvol", bucket="volq")
            br = B.effective_breadth(B.position_rows(prep, spy_ret, **base), H)
            for cb in args.cost_bps:
                m = P.score_run(P.simulate(prep, cost_bps=float(cb), **base),
                                spy_ret, H, era=era)
                if m is None:
                    continue
                rows.append({"H": H, "top_n": int(tn), "cost_bps": float(cb),
                             "BR_eff": br.get("BR_eff"),
                             "BR_per_year": (br.get("BR_eff", np.nan) * 252.0 / H),
                             "mult_ratio": m["mult_ratio"],
                             "excess_cagr": m["excess_cagr"]})
            print(f"  H={H:<3} top_n={int(tn):<4} BR/yr "
                  f"{br.get('BR_eff', float('nan')) * 252.0 / H:7.1f}", flush=True)

    res = pd.DataFrame(rows)
    if res.empty:
        raise SystemExit("no cells scored")

    gate = res[res.cost_bps == GATE_BPS].copy()
    print("\n" + "=" * 78)
    print(f"B5(a) -- NET OF {GATE_BPS:.0f}bp COSTS  (the gate)")
    print("=" * 78)
    piv = gate.pivot(index="top_n", columns="H", values="mult_ratio")
    print(piv.to_string(float_format=lambda v: f"{v:8.4f}"))

    dep = gate[(gate.H == args.deployed_h) & (gate.top_n == args.deployed_top_n)]
    dep_mult = float(dep.mult_ratio.iloc[0]) if len(dep) else np.nan
    print(f"\n  deployed cell (H={args.deployed_h}, top_n={args.deployed_top_n}): "
          f"{dep_mult:.4f}")

    best = gate.sort_values("mult_ratio", ascending=False).iloc[0]
    a_pass = bool(np.isfinite(dep_mult) and best.mult_ratio > dep_mult)
    print(f"  best cell     (H={int(best.H)}, top_n={int(best.top_n)}): "
          f"{best.mult_ratio:.4f}   BR/yr {best.BR_per_year:.1f}")
    print(f"\n  (a) {best.mult_ratio:.4f} vs deployed {dep_mult:.4f}   "
          f"{'PASS' if a_pass else 'FAIL'}")

    # ---- cost sensitivity: REPORTED, never optimised -----------------------
    print("\n" + "=" * 78)
    print("COST SENSITIVITY  (reported only -- the gate is 15bp)")
    print("=" * 78)
    cs = res[(res.H == best.H) & (res.top_n == best.top_n)][["cost_bps", "mult_ratio"]]
    dp = res[(res.H == args.deployed_h) & (res.top_n == args.deployed_top_n)][
        ["cost_bps", "mult_ratio"]].rename(columns={"mult_ratio": "deployed"})
    print(cs.merge(dp, on="cost_bps").to_string(
        index=False, float_format=lambda v: f"{v:8.4f}"))
    same_cell = (int(best.H) == args.deployed_h
                 and int(best.top_n) == args.deployed_top_n)
    if same_cell:
        print("\n  The best cell IS the deployed cell, so the two columns above are")
        print("  the same series and no breakeven is defined. Reported as such")
        print("  rather than as a number: comparing a cell to itself at a")
        print("  different cost level is not a cost sensitivity.")
    be = cs[cs.mult_ratio > dep_mult]
    if not same_cell and len(be) and len(be) < len(cs):
        print(f"\n  breakeven: the best cell stops beating the deployed cell above "
              f"~{float(be.cost_bps.max()):.0f}bp.")
        print("  Informational. A cell that needs costs below the project's")
        print("  standing 15bp assumption is a FAIL -- that is a statement about")
        print("  execution quality, not about signal.")

    # ---- (b) matched null on the best cell --------------------------------
    b_pass = False
    print("\n" + "=" * 78)
    print("B5(b) -- CONSTRUCTION-MATCHED NULL ON THE BEST CELL")
    print("=" * 78)
    if args.null_draws:
        H = int(best.H)
        prep, spy_ret, _ = ctx[H]
        base = dict(horizon=H, top_n=int(best.top_n), weighting="invvol",
                    bucket="volq")
        nl = S.random_selection_null(
            prep, P.simulate, lambda p, s: P.score_run(p, s, H, era=era),
            spy_ret, n_draws=args.null_draws, seed=17, cost_bps=GATE_BPS, **base)
        pct = S.percentile_of(best.mult_ratio, nl.get("_null_mults", []))
        b_pass = bool(np.isfinite(pct) and pct >= 0.95)
        print(f"  null p50 {nl.get('null_mult_ratio_p50', float('nan')):.4f}   "
              f"p95 {nl.get('null_mult_ratio_p95', float('nan')):.4f}   "
              f"n={nl.get('n')}")
        print(f"  (b) percentile {pct:.3f}   threshold 0.950   "
              f"{'PASS' if b_pass else 'FAIL'}")
        print("\n  A wider book beats SPY with ZERO signal by cutting variance")
        print("  drag; 27% of zero-signal configs already do in this harness.")
        print("  Only this null separates that from selection.")
    else:
        print("  NOT RUN -- pass --null-draws 200. Gate (b) does not exist without it.")

    # ---- (c) leave-one-year-out -------------------------------------------
    c_pass = False
    print("\n" + "=" * 78)
    print("B5(c) -- LEAVE-ONE-YEAR-OUT  (standing procedure since Round 14)")
    print("=" * 78)
    if a_pass:
        H = int(best.H)
        prep, spy_ret, _ = ctx[H]
        bw = P.simulate(prep, cost_bps=GATE_BPS, horizon=H, top_n=int(best.top_n),
                        weighting="invvol", bucket="volq")
        dprep, dspy, _ = ctx[args.deployed_h]
        dw = P.simulate(dprep, cost_bps=GATE_BPS, horizon=args.deployed_h,
                        top_n=args.deployed_top_n, weighting="invvol", bucket="volq")
        yrs = sorted(set(pd.to_datetime(bw.timepoint).dt.year)
                     & set(pd.to_datetime(dw.timepoint).dt.year))
        yrs = [y for y in yrs
               if pd.Timestamp(era[0]).year <= y < pd.Timestamp(era[1]).year]
        out = []
        for y in yrs:
            mb = P.score_run(bw[pd.to_datetime(bw.timepoint).dt.year != y],
                             spy_ret, H, era=era)
            md = P.score_run(dw[pd.to_datetime(dw.timepoint).dt.year != y],
                             dspy, args.deployed_h, era=era)
            if mb and md:
                out.append({"dropped": y, "best": mb["mult_ratio"],
                            "deployed": md["mult_ratio"],
                            "still_beats": mb["mult_ratio"] > md["mult_ratio"]})
        lo = pd.DataFrame(out)
        if len(lo):
            print(lo.to_string(index=False, float_format=lambda v: f"{v:8.4f}"))
            c_pass = bool(lo.still_beats.all())
            bad = lo[~lo.still_beats]
            print(f"\n  (c) survives dropping every single year: "
                  f"{'PASS' if c_pass else 'FAIL'}")
            if len(bad):
                print(f"      carried by: {', '.join(str(int(v)) for v in bad.dropped)}")
                print("      One year carrying the result is what killed")
                print("      rate_beta_x_move in Round 14 (2019 was 8% of windows")
                print("      and 45% of the effect) AFTER max-|t| and BH had")
                print("      already said no for the wrong reason.")
    else:
        print("  NOT RUN -- (a) failed, so there is nothing to concentration-test.")

    print("\n" + "=" * 78)
    print(f"B5 VERDICT: {'PASS' if (a_pass and b_pass and c_pass) else 'FAIL'}"
          f"   [(a) {a_pass}  (b) {b_pass}  (c) {c_pass}]")
    print("=" * 78)
    if not a_pass:
        print("  FAIL as pre-registered -- but do NOT read the cause off this")
        print("  gate. (a) compares every cell against the deployed cell, and")
        print("  that cell was SELECTED from 1,152 configs on this same era, so")
        print("  it is the maximum of the search and not a fair benchmark.")
        print("  Diagnose the cause from the full cost table instead:")
        print("    - if the short-horizon cells are still far behind at 5bp,")
        print("      costs are NOT the cause and the horizon lever failed for")
        print("      lack of anything to amplify;")
        print("    - if they close the gap as costs fall, turnover is the cause.")
        print("  The decisive read is whether mult_ratio moves MONOTONICALLY with")
        print("  BR_per_year at FIXED book size. Grinold says it must if IC > 0.")

    print("\n  CAVEAT, declared in the pre-registration: the H=10/H=20 caches use")
    print("  `expanding` training and the deployed H=40 cell uses `cap500k`, so")
    print("  this horizon comparison is confounded by training window. A passing")
    print("  cell must be re-run with matched training before it is believed.")

    res.to_csv(SWEEP_DIR / "horizon_cost_nominate.csv", index=False)
    print(f"\nwritten {SWEEP_DIR / 'horizon_cost_nominate.csv'}")

def cmd_prune(args):
    """Round 17. Rank feature subsets x tree depths by MODEL IC.

    Selection metric is IC, not terminal value, and that is deliberate. IC uses
    every eligible name every window -- ~1,100 x 164 = 180,000 observations --
    where a portfolio result is 82 numbers dominated by which five names
    happened to be held. Standing rule 4. Rounds 15/15b showed terminal value
    moves by several hundred basis points on pure construction while IC does
    not move at all, so ranking 24 cells on mult_ratio would rank them on noise.

    The family is 6 feature sets x 4 depths, DECLARED before the run. This is a
    fixed grid, not a greedy search over subsets.
    """
    cells = _load_cells(args.cells)
    era = NOMINATE_ERA
    print(f"era = nominate {era}")
    tab = pd.read_parquet(OUTCOMES_PATH)
    tab["ticker"] = tab["ticker"].astype(str)
    spy = _spy()
    smap = F.load_sector_map()

    rows = []
    for c in cells:
        if not SC.have(c.id):
            print(f"  [skip, not built] {c.id}")
            continue
        meta = json.load(open(SC.meta_path(c.id)))
        cfg = meta["config"]
        H = int(cfg["horizon"])
        scores = pd.read_parquet(SC.cache_path(c.id))
        prep = P.Prepared(scores, tab, H, None)
        spy_ret = P.spy_windows(spy, np.sort(scores["timepoint"].unique()), H)

        # --- per-window IC, raw and with a SECTOR-NEUTRALIZED target --------
        # Round 13/15 both showed apparent signal collapsing once sector came
        # out. A subset that wins only on the raw target is a sector bet.
        raw, neu, tps = [], [], []
        for tp, d in prep.g.items():
            t = pd.Timestamp(tp)
            if not (pd.Timestamp(era[0]) <= t < pd.Timestamp(era[1])):
                continue
            m = np.isfinite(d["ret"]) & np.isfinite(d["score"])
            if m.sum() < 40:
                continue
            y, s = d["ret"][m], d["score"][m]
            r = _num.spearman(s, y)
            D, _ = F.build_design(d["ticker"][m], d["cap"][m], d["vol"][m],
                                  spec="size_vol_sector", sector_map=smap)
            yr = F.residualize(y, D)
            ok = np.isfinite(yr)
            n = _num.spearman(s[ok], yr[ok]) if ok.sum() >= 40 else np.nan
            if np.isfinite(r):
                raw.append(r); neu.append(n); tps.append(t)

        if len(raw) < 8:
            print(f"  [skip, too few windows] {c.id}")
            continue
        raw = np.asarray(raw); neu = np.asarray(neu, dtype=np.float64)
        tps = pd.DatetimeIndex(tps)

        def _t(v):
            v = v[np.isfinite(v)]
            if len(v) < 3 or v.std(ddof=1) <= 0:
                return np.nan, np.nan
            return float(v.mean()), float(v.mean() / (v.std(ddof=1) / np.sqrt(len(v))))

        ic_r, t_r = _t(raw)
        ic_n, t_n = _t(neu)

        # --- leave-one-year-out on the NEUTRALIZED IC -----------------------
        # Standing procedure since Round 14: a result carried by one year has a
        # near-zero forward expectation whatever its t-statistic. This is what
        # killed rate_beta_x_move after BH and max-|t| had already said no for
        # the wrong reason.
        yrs = sorted(set(tps.year))
        loyo = []
        for y in yrs:
            _, tt = _t(neu[np.asarray(tps.year != y)])
            if np.isfinite(tt):
                loyo.append(tt)
        loyo_min = float(min(np.abs(loyo))) if loyo else np.nan
        same_sign = bool(len(set(np.sign(loyo))) == 1) if loyo else False

        # portfolio number, REPORTED ONLY -- never the selection metric
        pw = P.simulate(prep, horizon=H, top_n=args.top_n, weighting="invvol",
                        bucket="volq", cost_bps=15.0)
        m = P.score_run(pw, spy_ret, H, era=era)

        rows.append({
            "features": cfg["features"], "depth": int(cfg["depth"]),
            "n_cols": len(meta.get("feature_cols", [])),
            "ic_raw": ic_r, "t_raw": t_r,
            "ic_neutral": ic_n, "t_neutral": t_n,
            "loyo_min_t": loyo_min, "loyo_same_sign": same_sign,
            "n_windows": int(np.isfinite(neu).sum()),
            "mult_ratio": (m or {}).get("mult_ratio"),
            "cell_id": c.id,
        })
        print(f"  {cfg['features']:<18} d{cfg['depth']}  "
              f"IC_neutral {ic_n:+.4f} (t {t_n:+.2f})  LOYO min|t| {loyo_min:.2f}",
              flush=True)

    if not rows:
        raise SystemExit("no cells evaluated -- build them with `scores` first")
    res = pd.DataFrame(rows).sort_values("t_neutral", key=np.abs, ascending=False)

    print("\n" + "=" * 84)
    print("RANKED BY SECTOR-NEUTRALIZED IC  (the selection metric)")
    print("=" * 84)
    cols = ["features", "depth", "n_cols", "ic_raw", "t_raw", "ic_neutral",
            "t_neutral", "loyo_min_t", "loyo_same_sign", "mult_ratio"]
    print(res[cols].to_string(index=False, float_format=lambda v: f"{v:8.4f}"))

    print("\n--- marginal effect of each axis (median neutralized |t|) ---")
    for ax in ("features", "depth"):
        g = res.groupby(ax)["t_neutral"].apply(lambda s: np.median(np.abs(s)))
        print(f"  by {ax}:")
        for k, v in g.sort_values(ascending=False).items():
            print(f"    {str(k):<20} {v:.2f}")

    best = res.iloc[0]
    print(f"\nbest cell: {best.features} d{int(best.depth)} "
          f"({int(best.n_cols)} columns)")
    print(f"  neutralized IC {best.ic_neutral:+.4f}  t {best.t_neutral:+.2f}")
    print(f"  LOYO min |t| {best.loyo_min_t:.2f}, same sign {best.loyo_same_sign}")
    print(f"\n  Deflation reference: this is the best of {len(res)} declared cells.")
    print(f"  Under the decision bar (validation-gates.md) the question is the")
    print(f"  EXPECTED IC, not whether it clears a threshold -- but a max over 24")
    print(f"  cells is biased upward, so the honest estimate of the winner's")
    print(f"  forward IC is below its in-sample value, and the LOYO column is")
    print(f"  what says whether it is carried by one period.")
    if not best.loyo_same_sign:
        print("  WARNING: the best cell changes sign on a year-drop. Treat as noise.")

    res.to_csv(SWEEP_DIR / "prune_nominate.csv", index=False)
    print(f"\nwritten {SWEEP_DIR / 'prune_nominate.csv'}")

def cmd_live(args):
    """Rank cells on the LIVE construction, by profit.

    Round 18. This exists because Rounds 17b/17c ranked on sector-NEUTRAL
    performance, which deliberately discards factor exposure -- and Gabe has
    been explicit, more than once, that factor and sector bets are acceptable
    and that the objective is profit. Selecting on a criterion the owner has
    rejected is not conservatism, it is answering the wrong question.

    So: the ranking metric here is excess CAGR on the construction that is
    actually deployed (top-5, volq buckets, inverse-vol weights), against its
    own construction-matched null.

    The sector-neutral number is still computed and printed, but as a
    DIAGNOSTIC in its own column -- it is the only way to tell how much of a
    result is stock selection versus factor loading, which is worth knowing
    even when both are wanted. It does not drive the ranking.
    """
    tab = pd.read_parquet(OUTCOMES_PATH)
    tab["ticker"] = tab["ticker"].astype(str)
    spy = _spy()
    era = NOMINATE_ERA
    if args.era != "nominate":
        raise SystemExit(
            "Live evaluation is nomination-era only. The 2020-2026 hold-out was "
            "spent in Round 13 and was touched once more in error on 2026-09-12; "
            "it is not a clean test of anything and must not be used to choose.")
    smap = F.load_sector_map()
    base = dict(top_n=args.top_n, weighting=args.weighting, bucket=args.bucket)
    print(f"era = nominate {era}")
    print(f"LIVE construction: top_n={args.top_n}, {args.weighting}, "
          f"bucket={args.bucket}, {args.cost_bps:.0f}bp\n")

    cells = _load_cells(args.cells) if args.cells else None
    ids = [c.id for c in cells] if cells else sorted(
        p.stem for p in SC.CACHE_DIR.glob("*.parquet"))

    rows = []
    for cid in ids:
        if not SC.have(cid):
            continue
        meta = json.load(open(SC.meta_path(cid)))
        cfg = meta["config"]
        H = int(cfg["horizon"])
        if H != args.horizon:
            continue
        scores = pd.read_parquet(SC.cache_path(cid))
        prep = P.Prepared(scores, tab, H, None)
        spy_ret = P.spy_windows(spy, np.sort(scores["timepoint"].unique()), H)

        pw = P.simulate(prep, horizon=H, cost_bps=args.cost_bps, **base)
        m = P.score_run(pw, spy_ret, H, era=era)
        if m is None:
            continue

        # matched null on the SAME construction -- the only thing that separates
        # "this ranking earned it" from "this construction earned it"
        pct = np.nan
        if args.null_draws:
            nl = S.random_selection_null(
                prep, P.simulate, lambda p, s: P.score_run(p, s, H, era=era),
                spy_ret, n_draws=args.null_draws, seed=17,
                horizon=H, cost_bps=args.cost_bps, **base)
            pct = S.percentile_of(m["mult_ratio"], nl.get("_null_mults", []))

        # leave-one-year-out on the live construction
        d = pw[(pw.timepoint >= era[0]) & (pw.timepoint < era[1])]
        yrs = sorted(set(pd.to_datetime(d.timepoint).dt.year))
        lo = []
        for y in yrs:
            mm = P.score_run(pw[pd.to_datetime(pw.timepoint).dt.year != y],
                             spy_ret, H, era=era)
            if mm:
                lo.append(mm["excess_cagr"] * 100)
        worst = float(min(lo)) if lo else np.nan
        allpos = bool(all(v > 0 for v in lo)) if lo else False

        # DIAGNOSTIC ONLY: how much survives removing the sector bet
        sn = _sector_neutral_excess(prep, spy_ret, smap, H, era,
                                    per_sector=args.diag_per_sector,
                                    cost_bps=args.cost_bps)

        rows.append({"features": cfg["features"], "label": cfg["label"],
                     "model": cfg["model"], "n_cols": len(meta.get("feature_cols", [])),
                     "excess_cagr": m["excess_cagr"] * 100,
                     "mult_ratio": m["mult_ratio"],
                     "null_pctile": pct, "loyo_worst": worst,
                     "loyo_all_pos": allpos,
                     "diag_sector_neutral": sn, "cell_id": cid})
        print(f"  {cfg['features']:<26} {cfg['label']:<6} {cfg['model']:<8} "
              f"{m['excess_cagr']*100:>+7.2f}%/yr  pctile {pct:.3f}", flush=True)

    if not rows:
        raise SystemExit("no cells evaluated")
    res = pd.DataFrame(rows).sort_values("excess_cagr", ascending=False)

    print("\n" + "=" * 92)
    print("RANKED BY EXCESS CAGR ON THE LIVE CONSTRUCTION  (the objective)")
    print("=" * 92)
    cols = ["features", "label", "model", "n_cols", "excess_cagr", "mult_ratio",
            "null_pctile", "loyo_worst", "loyo_all_pos", "diag_sector_neutral"]
    print(res[cols].to_string(index=False, float_format=lambda v: f"{v:8.3f}"))

    print("\n  excess_cagr          THE RANKING METRIC -- profit on what is live.")
    print("  null_pctile          same construction, rankings shuffled. Below ~0.95")
    print("                       the construction earned it, not the model.")
    print("  loyo_worst           worst single-year-drop. A result that goes")
    print("                       negative on one drop has a fragile expectation.")
    print("  diag_sector_neutral  DIAGNOSTIC, not a gate: excess CAGR with the")
    print("                       sector bet removed. Says how much is stock")
    print("                       selection vs factor loading. Both are wanted,")
    print("                       but knowing the split is how we know what we")
    print("                       have and what will happen when factors turn.")

    best = res.iloc[0]
    print(f"\nbest on the objective: {best.features} / {best.label} / {best.model}")
    print(f"  {best.excess_cagr:+.2f}%/yr   null pctile {best.null_pctile:.3f}   "
          f"worst year-drop {best.loyo_worst:+.2f}%/yr")
    if len(res) > 1:
        d = best.excess_cagr - res.iloc[1].excess_cagr
        print(f"  margin over #2: {d:+.2f}%/yr")
    print(f"\n  Selected from {len(res)} cells. In-sample and biased upward; the")
    print(f"  2020-2026 hold-out is spent and cannot adjudicate this.")

    res.to_csv(SWEEP_DIR / "live_nominate.csv", index=False)
    print(f"\nwritten {SWEEP_DIR / 'live_nominate.csv'}")


def _sector_neutral_excess(prep, spy_ret, smap, H, era, per_sector=5,
                           cost_bps=15.0):
    """Excess CAGR with equal weight across sectors -- zero sector bet."""
    rows, prev = [], set()
    for tp in prep.tps:
        t = pd.Timestamp(tp)
        if not (pd.Timestamp(era[0]) <= t < pd.Timestamp(era[1])):
            continue
        d = prep.g.get(np.datetime64(tp))
        if d is None:
            continue
        labs = np.array([F._base_ticker(x) for x in d["ticker"]])
        labs = np.array([smap.get(x, "") for x in labs])
        ok = np.isfinite(d["ret"]) & d["tradable"] & np.isfinite(d["score"])
        picks = []
        for s in sorted(set(labs[ok]) - {""}):
            m = np.flatnonzero(ok & (labs == s))
            if len(m) < per_sector * 2:
                continue
            picks.append(m[np.argsort(-d["score"][m])[:per_sector]])
        if len(picks) < 6:
            continue
        w = np.zeros(len(d["score"]))
        for g in picks:
            w[g] = 1.0 / (len(picks) * len(g))
        idx = np.flatnonzero(w > 0)
        gr = float((w[idx] * d["ret"][idx]).sum())
        cur = set(d["ticker"][idx])
        turn = 1.0 - (len(cur & prev) / max(len(cur), 1))
        prev = cur
        rows.append({"sleeve": 0, "timepoint": t, "n": len(idx), "gross": gr,
                     "net": gr - turn * cost_bps / 1e4, "exposure": 1.0,
                     "turnover": turn})
    if not rows:
        return np.nan
    m = P.score_run(pd.DataFrame(rows), spy_ret, H, era=era)
    return m["excess_cagr"] * 100 if m else np.nan

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
        # A cell whose scores parquet exists but whose meta sidecar does not is
        # a half-written cache entry (fly_none_T20_s0 is one: the run_fly
        # --no-reservoir crash of 2026-09-16 wrote the scores and died before
        # the meta). It used to take the WHOLE portfolio run down with a
        # FileNotFoundError, which meant one stale artifact could block every
        # later experiment. Skip it and say so.
        mpath = SC.meta_path(cell)
        if not Path(mpath).exists():
            print(f"  {cell}: SKIPPED -- no meta sidecar ({Path(mpath).name}); "
                  f"the score cache for this cell is incomplete.")
            continue
        scores = pd.read_parquet(cpath)
        meta = json.load(open(mpath))
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
            # Round 19: the higher-powered metric. See portfolio.decile_stats.
            m.update(P.decile_stats(prep, era=era))

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
                            "rates", "price_fund_rates",
                            "events", "price_fund_events",
                            # Round 19: "path" screens accel_20 alone, so the
                            # multiple-testing family is the 1 new hypothesis.
                            "path", "price_fund_path"],
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

    p = sub.add_parser("breadth")
    p.add_argument("--cell", required=True,
                   help="score-cache cell id to measure breadth for")
    p.add_argument("--era", choices=["nominate"], default="nominate",
                   help="nomination era only; the hold-out is spent (Round 13)")
    p.add_argument("--top-n", type=int, default=5)
    p.add_argument("--weighting", default="invvol")
    p.add_argument("--bucket", default="volq")
    p.add_argument("--stop", default=None)
    p.add_argument("--cost-bps", type=float, default=15.0)
    p.add_argument("--spec", default="size_vol_sector",
                   help="factor design residualized out at SELECTION time")
    p.add_argument("--breadth-scan", type=int, nargs="*",
                   default=[5, 10, 20, 50, 100],
                   help="top_n values to measure BR_eff at (B1 instrumentation)")
    p.add_argument("--null-draws", type=int, default=0,
                   help="matched random-selection draws. Gate B3(b) does not "
                        "exist without this: a breadth gain improves compounded "
                        "return with ZERO signal, and only the matched null "
                        "separates the two. Use 200 for any run that decides.")
    p.set_defaults(func=cmd_breadth)

    p = sub.add_parser("horizon")
    p.add_argument("--cells", nargs="+", required=True,
                   help="H=cell_id pairs, e.g. 10=price_fund_h10_... 40=...")
    p.add_argument("--top-ns", type=int, nargs="+", default=[5, 20, 50, 100])
    p.add_argument("--cost-bps", type=float, nargs="+",
                   default=[5, 10, 15, 25, 40],
                   help="sensitivity curve. The GATE is evaluated at 15bp only; "
                        "a cell that needs cheaper execution is a FAIL.")
    p.add_argument("--deployed-h", type=int, default=40)
    p.add_argument("--deployed-top-n", type=int, default=5)
    p.add_argument("--era", choices=["nominate"], default="nominate")
    p.add_argument("--null-draws", type=int, default=0,
                   help="matched random-selection draws for gate B5(b). A wider "
                        "book beats SPY with ZERO signal by cutting variance "
                        "drag; without this there is no gate. Use 200.")
    p.set_defaults(func=cmd_horizon)

    p = sub.add_parser("prune")
    p.add_argument("--cells", default="sweep/grid_prune.json")
    p.add_argument("--top-n", type=int, default=5,
                   help="portfolio size for the REPORTED mult_ratio only; "
                        "selection is on IC, never on terminal value")
    p.set_defaults(func=cmd_prune)

    p = sub.add_parser("live")
    p.add_argument("--cells", default=None,
                   help="cell list; omit to evaluate every cached cell at --horizon")
    p.add_argument("--horizon", type=int, default=40)
    p.add_argument("--top-n", type=int, default=5)
    p.add_argument("--weighting", default="invvol")
    p.add_argument("--bucket", default="volq")
    p.add_argument("--cost-bps", type=float, default=15.0)
    p.add_argument("--era", choices=["nominate"], default="nominate")
    p.add_argument("--null-draws", type=int, default=150)
    p.add_argument("--diag-per-sector", type=int, default=5,
                   help="book size for the sector-neutral DIAGNOSTIC column")
    p.set_defaults(func=cmd_live)

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
