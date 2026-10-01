"""
WO-36 runner. Pre-registration: final/models/2026-10-01-cw-spread-weights.md.

    python run_cw.py --mode reproduce           # base 5.36 and V0 3.65 (published numbers) + fast-path checks
    python run_cw.py --mode proof               # shuffled-label nomination rate (no real label statistic)
    python run_cw.py --mode stage2 --labels shuffled --force-variant V5   # plumbing on the confirm window
    python run_cw.py --mode stage1              # real labels, 2008-2018; refused until the doc is committed
    python run_cw.py --mode stage2              # ONE shot, hold-out read #16; refuses to overwrite
"""
from __future__ import annotations

import argparse
import json
import subprocess
import time
from pathlib import Path

import numpy as np
import pandas as pd

import cw_core as K

RX, ET, CW = K.RX, K.ET, K.CW
HERE = Path(__file__).resolve().parent
REPO = HERE.parents[2]
OUT = HERE.parents[1] / "out" / "cwweights"
FEATS = OUT / "av_options_features_wo25.parquet"
EXPB_JSON = HERE.parents[1] / "out" / "options_wo25" / "expB_screen.json"
DOC = "final/models/2026-10-01-cw-spread-weights.md"
FROZEN = OUT / "frozen_weights.json"
S1 = OUT / "stage1_nominate.json"
S2 = OUT / "stage2_confirm.json"
N_DRAWS = 100
SEED = 20261001
log = ET.log


def guard_doc():
    try:
        subprocess.run(["git", "-C", str(REPO), "ls-files", "--error-unmatch", DOC], check=True, capture_output=True)
        dirty = subprocess.run(["git", "-C", str(REPO), "status", "--porcelain", "--", DOC, "final/src/cwweights"],
                               check=True, capture_output=True, text=True).stdout.strip()
    except subprocess.CalledProcessError:
        raise SystemExit(f"refused: {DOC} is not committed")
    return dirty  # recorded in the output; non-empty means doc/code differ from the commit


def dump(path, obj):
    path.write_text(json.dumps(obj, indent=2, default=float))
    log(f"wrote {path}")


def slow_variant(rows, spy, base_w, name, xs):
    """Imported-function path: ET.score_frame + run_expB.portfolio."""
    if name in xs:
        return RX.portfolio(ET.score_frame(rows, K.weights9(base_w, xs[name])), spy)
    sb = ET.score_frame(rows, base_w)
    if name != "base":
        pct = sb.groupby("date")[CW].rank(method="average", pct=True)
        sb = sb[pct > K.EXCL_Q[name]]
    return RX.portfolio(sb, spy)


def check_fast(rows, data, spy, base_w, xs, names, tol=1e-9):
    picks = K.build_picks(data, xs)
    res = {}
    for v in names:
        slow = slow_variant(rows, spy, base_w, v, xs)
        ev, _ = K.evaluate(data, picks[v])
        fast = [float(o["ex"].mean() * K.ANN) for o in ev]
        err = float(np.max(np.abs(np.array(fast) - np.array(slow["per_offset"]))))
        if err > tol:
            raise SystemExit(f"fast path differs from run_expB.portfolio on {v}: {err:.3e}")
        res[v] = {"slow": slow, "fast_per_offset": fast, "max_abs_err": err}
    return res


def mode_reproduce():
    m, spy, cov = RX.load(*RX.NOMINATE_B, FEATS)
    stored = json.loads(EXPB_JSON.read_text())
    # Weights are FROZEN at the published Experiment B values. The features file gained 10
    # name-dates on 2018-10-17 after that run (pull top-up), so a refit here differs in the
    # 4th decimal; the refit is recorded for comparison only and is not used.
    sf = stored["factors"][CW]
    base_w, base_t = stored["base_weights"], stored["base_t"]
    t_raw, t_neu = sf["ic_raw"]["t"], sf["ic_neutral"]["t"]
    refit_t = {c: ET.pooled(m, c) for c in RX.BASE_SIGNS}
    refit_w = ET.fit_weights(refit_t, RX.BASE_SIGNS)
    refit_t_raw = ET.pooled(m, CW)["t"]
    refit_t_neu = ET.pooled(ET.neutralise(m, [CW]), CW)["t"]
    assert max(abs(refit_w[c] - base_w[c]) for c in base_w) < 1e-3
    assert abs(refit_t_raw - t_raw) < 0.01 and abs(refit_t_neu - t_neu) < 0.01
    x0, w9 = K.rule_x(base_t, t_raw)
    x4, w9n = K.rule_x(base_t, t_neu)
    assert abs(x0 - sf["weights9"][CW]) < 1e-12
    for c in base_w:   # rule weights are base weights scaled by (1 - x)
        assert abs(w9[c] - base_w[c] * (1 - x0)) < 1e-12 and abs(w9n[c] - base_w[c] * (1 - x4)) < 1e-12
    xs = {"V0": x0, **K.FIXED_X, "V4": x4}
    rows, data = K.prep(m, spy, base_w)
    real = check_fast(rows, data, spy, base_w, xs, ["base", "V0"])
    log(f"base {real['base']['slow']['excess_ann_mean_offsets']:.5f} {real['base']['slow']['per_offset']}")
    log(f"V0   {real['V0']['slow']['excess_ann_mean_offsets']:.5f} {real['V0']['slow']['per_offset']}")
    ms, spys = RX.apply_label_mode(m, spy, "shuffled")
    rows_s, data_s = K.prep(ms, spys, base_w)
    shuf = check_fast(rows_s, data_s, spys, base_w, xs, ["base", "V0"] + K.SIX)
    log("fast path matches run_expB.portfolio on base, V0 (real) and base, V0..V6 (shuffled labels)")
    dump(FROZEN, {"base_weights": base_w, "base_t": base_t, "t_raw_cw": t_raw, "t_neutral_cw": t_neu,
                  "x": xs, "fit_window": [str(d.date()) for d in RX.NOMINATE_B],
                  "refit_on_current_file_not_used": {"base_weights": refit_w, "t_raw_cw": refit_t_raw,
                                                     "t_neutral_cw": refit_t_neu, "n_name_dates": len(m)},
                  "note": "frozen at Experiment B's published values (expB_screen.json); V4 x follows from its neutral t"})
    dump(OUT / "reproduce.json", {
        "pool_integrity": cov, "n_rows_with_cw": len(rows), "n_dates": int(rows.date.nunique()),
        "base_real": real["base"], "V0_real": real["V0"],
        "expB_stored": {"base": sf["companion"]["composite"], "V0": sf["companion"]["composite_plus"]},
        "x": xs, "shuffled_label_fast_vs_slow_max_abs_err": {v: r["max_abs_err"] for v, r in shuf.items()}})


def frozen():
    if not FROZEN.exists():
        raise SystemExit("run --mode reproduce first")
    f = json.loads(FROZEN.read_text())
    return f["base_weights"], f["x"]


def mode_proof(n_runs):
    base_w, xs_all = frozen()
    xs = {v: xs_all[v] for v in ("V1", "V2", "V3", "V4")}
    m, spy, _ = RX.load(*RX.NOMINATE_B, FEATS)
    _, data = K.prep(m, spy, base_w)
    t0 = time.time()
    real_picks = K.build_picks(data, xs)
    null_picks = [K.build_picks(data, xs, np.random.default_rng(SEED + k), K.SIX) for k in range(N_DRAWS)]
    log(f"picks built in {time.time() - t0:.0f}s")
    spys = [0.0] * len(data)
    runs = []
    for r in range(n_runs):
        rng = np.random.default_rng(7_000_000 + r)
        rets = []
        for dd in data:
            x = dd["ret"][rng.permutation(dd["n"])]
            rets.append(x - np.nanmean(x))
        _, real, null = K.analyse(data, xs, K.SIX, N_DRAWS, SEED, rets, spys, null_picks, real_picks)
        p80 = null["max_over_variants_p80"]
        nom = [v for v in K.SIX if K.nominated(real[v], p80)]
        runs.append({"run": r, "null_max_p80": p80, "nominated": nom,
                     "diff": {v: real[v]["diff"] for v in K.SIX},
                     "above_p80_only": [v for v in K.SIX if real[v]["diff"] > p80]})
        log(f"run {r}: p80 {p80:+.4f} nominated {nom}")
    rate = float(np.mean([bool(x["nominated"]) for x in runs]))
    log(f"shuffled-label nomination rate {rate:.2f} over {n_runs} runs")
    dump(OUT / "proof_SHUFFLED_TEST_labels-shuffled.json", {
        "n_runs": n_runs, "n_null_draws": N_DRAWS, "nomination_rate": rate,
        "rate_above_p80_ignoring_other_conditions": float(np.mean([bool(x["above_p80_only"]) for x in runs])),
        "per_variant_nomination_rate": {v: float(np.mean([v in x["nominated"] for x in runs])) for v in K.SIX},
        "mean_real_diff_by_variant": {v: float(np.mean([x["diff"][v] for x in runs])) for v in K.SIX},
        "mean_null_max_p80": float(np.mean([x["null_max_p80"] for x in runs])),
        "runs": runs,
        "note": "weights frozen at Experiment B values; outcomes permuted within date, demeaned, SPY = 0"})


def mode_stage1(labels):
    real_mode = labels is None
    path = S1 if real_mode else OUT / "stage1_SHUFFLED_TEST_labels-shuffled.json"
    dirty = ""
    if real_mode:
        dirty = guard_doc()
        if path.exists():
            raise SystemExit(f"{path} exists: Stage 1 already run; a rerun is an iteration")
    base_w_f, xs_all = frozen()
    m, spy, cov = RX.load(*RX.NOMINATE_B, FEATS)
    if not real_mode:
        m, spy = RX.apply_label_mode(m, spy, "shuffled")
    base_w = base_w_f
    xs = {v: xs_all[v] for v in ("V0", "V1", "V2", "V3", "V4")}
    rows, data = K.prep(m, spy, base_w)
    chk = check_fast(rows, data, spy, base_w, xs, ["base", "V0"] + K.SIX)
    xs6 = {v: xs[v] for v in ("V1", "V2", "V3", "V4")}
    t0 = time.time()
    real_picks = K.build_picks(data, xs)
    base, real, null = K.analyse(data, xs6, K.SIX, N_DRAWS, SEED, real_picks=real_picks)
    ev_b, _ = K.evaluate(data, real_picks["base"])
    v0 = K.diff_stats(K.evaluate(data, real_picks["V0"])[0], ev_b)
    p80 = null["max_over_variants_p80"]
    for v in K.SIX:
        real[v]["nominated"] = K.nominated(real[v], p80)
        real[v]["checks"] = {"above_null_max_p80": bool(real[v]["diff"] > p80),
                             "both_offsets_positive": bool(all(d > 0 for d in real[v]["diff_per_offset"])),
                             "loyo_min_positive": bool(real[v]["loyo_min"] > 0)}
        real[v]["slow_path"] = chk[v]["slow"]
        log(f"  {v}: {real[v]['excess_ann']:+.4f} diff {real[v]['diff']:+.4f} off {real[v]['diff_per_offset']} "
            f"loyo_min {real[v]['loyo_min']:+.4f} nominated {real[v]['nominated']}")
    noms = [v for v in K.SIX if real[v]["nominated"]]
    chosen = max(noms, key=lambda v: real[v]["loyo_min"]) if noms else None
    log(f"base {base['excess_ann']:+.4f} | null max-over-six p80 {p80:+.4f} | nominated {noms} | to Stage 2: {chosen}")
    dump(path, {
        "stage": "stage1", "label_mode": "real" if real_mode else "shuffled", "window": [str(d.date()) for d in RX.NOMINATE_B],
        "pool_integrity": cov, "n_rows_with_cw": len(rows), "base_weights": base_w, "x": xs,
        "base": base, "V0_reference": v0, "variants": real, "null_shuffled_cw": null,
        "thinning_null": {v: {"p80": null["per_variant_p80"][v], "median": null["per_variant_median"][v],
                              "real_diff": real[v]["diff"],
                              "real_above_p80": bool(real[v]["diff"] > null["per_variant_p80"][v])} for v in ("V5", "V6")},
        "nominated": noms, "chosen_for_stage2": chosen,
        "verdict": "to Stage 2" if chosen else "KILL at Stage 1",
        "git_dirty_at_run": dirty, "seed": SEED, "runtime_s": time.time() - t0})


def mode_stage2(labels, force_variant):
    real_mode = labels is None
    path = S2 if real_mode else OUT / "stage2_SHUFFLED_TEST_labels-shuffled.json"
    dirty = ""
    if real_mode:
        dirty = guard_doc()
        if force_variant:
            raise SystemExit("--force-variant is for shuffled-label plumbing only")
        if path.exists():
            raise SystemExit(f"{path} exists: Stage 2 is ONE shot (hold-out read #16)")
        if not S1.exists():
            raise SystemExit("run --mode stage1 first")
        s1 = json.loads(S1.read_text())
        chosen = s1["chosen_for_stage2"]
        if chosen is None:
            raise SystemExit("Stage 1 nominated nothing: KILL at Stage 1, hold-out read #16 NOT used")
        base_w, xs_all = s1["base_weights"], s1["x"]
    else:
        chosen = force_variant or "V5"
        base_w, xs_all = frozen()
    xs = {chosen: xs_all[chosen]} if chosen in xs_all else {}
    m, spy, cov = RX.load(*RX.CONFIRM_B, FEATS)      # raises if cap2000 pool integrity < 99%
    if not real_mode:
        m, spy = RX.apply_label_mode(m, spy, "shuffled")
    rows, data = K.prep(m, spy, base_w)               # weights frozen from 2008-2018; nothing fit here
    t0 = time.time()
    real_picks = K.build_picks(data, xs, variants=["base", chosen])
    base, real, null = K.analyse(data, xs, [chosen], N_DRAWS, SEED + 10_000, real_picks=real_picks)
    st = real[chosen]
    p80 = null["max_over_variants_p80"]
    checks = {"both_offsets_positive": bool(all(d > 0 for d in st["diff_per_offset"])),
              "both_halves_positive": bool(st["diff_odd_years"] > 0 and st["diff_even_years"] > 0),
              "loyo_min_positive": bool(st["loyo_min"] > 0),
              "above_shuffle_null_p80": bool(st["diff"] > p80)}
    ok = all(checks.values())
    log(f"Stage 2 {chosen}: base {base['excess_ann']:+.4f} variant {st['excess_ann']:+.4f} diff {st['diff']:+.4f} "
        f"offsets {st['diff_per_offset']} halves {st['diff_odd_years']:+.4f}/{st['diff_even_years']:+.4f} "
        f"loyo_min {st['loyo_min']:+.4f} drop-2020 {st['loyo_diff'].get(2020)} null p80 {p80:+.4f} -> {'PASS' if ok else 'KILL'}")
    dump(path, {
        "stage": "stage2", "label_mode": "real" if real_mode else "shuffled",
        "holdout_read": "#16" if real_mode else "none (test labels)",
        "window": [str(d.date()) for d in RX.CONFIRM_B], "pool_integrity": cov, "n_rows_with_cw": len(rows),
        "feature_dates_in_window": int(rows.date.nunique()),
        "chosen": chosen, "x": xs, "base_weights_frozen": base_w, "base": base, "variant": st,
        "diff_with_2020_dropped": st["loyo_diff"].get(2020), "null_shuffled_cw": null,
        "checks": checks, "verdict": "PASS" if ok else "KILL at Stage 2",
        "git_dirty_at_run": dirty, "seed": SEED + 10_000, "runtime_s": time.time() - t0})


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--mode", choices=["reproduce", "proof", "stage1", "stage2"], required=True)
    ap.add_argument("--labels", choices=["shuffled"], default=None)
    ap.add_argument("--force-variant", default=None)
    ap.add_argument("--runs", type=int, default=50)
    a = ap.parse_args()
    OUT.mkdir(parents=True, exist_ok=True)
    if a.mode == "reproduce":
        mode_reproduce()
    elif a.mode == "proof":
        mode_proof(a.runs)
    elif a.mode == "stage1":
        mode_stage1(a.labels)
    else:
        mode_stage2(a.labels, a.force_variant)


if __name__ == "__main__":
    main()
