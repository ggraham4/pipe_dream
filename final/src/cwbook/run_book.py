"""
WO-58 runner. Pre-registration: final/models/2026-10-10-cwspread-downcap-book.md (sha256 asserted).

    PY=/opt/anaconda3/envs/pipe_dream/bin/python   (always under caffeinate -i)
    $PY run_book.py --mode reproduce   # WO-52 thin M 2.7394 + WO-36 base 0.053650011 (published numbers)
    $PY run_book.py --mode stage1      # real labels, 133 dates 2008-2018; refuses to overwrite
    $PY run_book.py --mode stage2      # hold-out read #23; only if stage1 PASS and the read is logged first

Research code only. It never places, modifies or cancels an order.
"""
from __future__ import annotations

import argparse
import json
import subprocess
import time

import numpy as np
import pandas as pd

import cb_core as B

K, RX, T = B.K, B.RX, B.T
REPO = B.FINAL.parent
DOC = "final/models/2026-10-10-cwspread-downcap-book.md"
DOC_SHA = "0f4d5fb63e9d53ba719cbb37eb0b901cc71b6ba8e8d1066d667d6ac0e57c92a3"
RESULTS_DOC = "final/models/2026-10-10-cwspread-downcap-book-results.md"
OUT = B.OUT
N_DRAWS = 100
SEED = {1: 20261010, 2: 20271010}
RESULT = {1: OUT / "stage1_result.json", 2: OUT / "stage2_result.json"}
STRESS_BPS = 50.0
BOOK_USD = 100_000.0
log = B.log


def dump(path, obj):
    path.write_text(json.dumps(obj, indent=1, default=float))
    log(f"wrote {path}")


def guard(stage):
    sha = B.sha256(REPO / DOC)
    if sha != DOC_SHA:
        raise SystemExit(f"refused: {DOC} sha256 {sha} != frozen {DOC_SHA}")
    r = subprocess.run(["git", "-C", str(REPO), "ls-files", "--error-unmatch", DOC], capture_output=True)
    if r.returncode != 0:
        raise SystemExit(f"refused: {DOC} is not committed")
    if RESULT[stage].exists():
        raise SystemExit(f"refused: {RESULT[stage].name} exists (a rerun is an iteration: log it in the doc first, "
                         "then move the old file aside by hand)")
    if stage == 2:
        s1 = json.loads(RESULT[1].read_text()) if RESULT[1].exists() else {}
        if s1.get("verdict") != "PASS":
            raise SystemExit("refused: Stage 1 verdict is not PASS; Stage 2 (hold-out read #23) does not run")
        rd = (REPO / RESULTS_DOC)
        if not rd.exists() or "HOLD-OUT READ #23 LOGGED" not in rd.read_text():
            raise SystemExit("refused: log hold-out read #23 in the results doc before the run")


# ------------------------------------------------------------------ reproduce
def reproduce():
    out = {}
    # (i) WO-52 thin M on the 133 dates, WO-52's own frame and denominator (signal AND label present)
    import run_arm1 as A1
    T.FEATS = B.FEATS[1]
    _, dates = B.load_signal(1)
    m, _nu = A1.load_frame("thin", dates)
    m["y"] = A1.attach_labels(m, "real", 0)
    D = A1.prep(m)
    ev = A1.evaluate(D, m.y.to_numpy(float), with_null=False)
    ref = json.loads((B.FINAL / "out" / "thinliq_om" / "arm1_results.json").read_text())["arm1"]["M_pct_per_40d"]
    out["wo52_thin_M_pct"] = {"got": ev["M_pct_per_40d"], "ref": ref, "n_dates": ev["n_dates"],
                              "abs_err_fraction": abs(ev["M_pct_per_40d"] - ref) / 100,
                              "pass": abs(ev["M_pct_per_40d"] - ref) / 100 <= 1e-6}
    # (ii) WO-36 base book from its own outputs
    s1 = json.loads((B.FINAL / "out" / "cwweights" / "stage1_nominate.json").read_text())
    mm, spy, _cov = RX.load(*RX.NOMINATE_B, B.OUT / "feats_wo36_av.parquet")
    _rows, data = K.prep(mm, spy, s1["base_weights"])
    pk = K.build_picks(data, {}, variants=["base"])
    evb, _ = K.evaluate(data, pk["base"])
    got = K.level(evb)
    out["wo36_base_excess_ann"] = {"got": got, "ref": s1["base"]["excess_ann"], "abs_err": abs(got - s1["base"]["excess_ann"]),
                                   "pass": abs(got - s1["base"]["excess_ann"]) <= 1e-6}
    out["pass"] = bool(out["wo52_thin_M_pct"]["pass"] and out["wo36_base_excess_ann"]["pass"])
    dump(OUT / "reproduce.json", out)
    if not out["pass"]:
        raise SystemExit("reproduction FAILED: stop and report")


# ------------------------------------------------------------------ descriptives
def ew_pool(D):
    """No-score thin equal-weight pool: every book-pool name with a label, gross, minus SPY, 2 offsets."""
    recs = [(dd["date"], float(np.nanmean(dd["ret"])) - dd["spy"]) for dd in D if np.isfinite(dd["spy"])]
    per = [np.mean([x for _, x in recs[o::B.N_OFF]]) * B.ANN for o in range(B.N_OFF)]
    return {"gross_minus_spy_ann": float(np.mean(per)), "per_offset": [float(x) for x in per]}


def dollar_volume(dates):
    """20-day median of close*volume (Sharadar SEP, split-adjusted both) on each date (label-free)."""
    out = []
    for ym in sorted({d.strftime("%Y-%m") for d in dates}):
        prev = (pd.Timestamp(ym + "-01") - pd.Timedelta(days=1)).strftime("%Y-%m")
        fs = [T.SEP / f"{x}.parquet" for x in (prev, ym) if (T.SEP / f"{x}.parquet").exists()]
        s = pd.concat([pd.read_parquet(f, columns=["ticker", "date", "volume", "close"]) for f in fs])
        s["date"] = pd.to_datetime(s.date); s["ticker"] = s.ticker.astype(str)
        s = s.sort_values(["ticker", "date"])
        s["dv"] = s.volume * s.close
        s["dv20"] = s.groupby("ticker").dv.transform(lambda x: x.rolling(20, min_periods=10).median())
        out.append(s[s.date.isin([d for d in dates if d.strftime("%Y-%m") == ym])][["date", "ticker", "dv20"]])
    return pd.concat(out, ignore_index=True)


def capacity(D, picks, uniq, dv):
    dvm = dv.set_index(["date", "ticker"]).dv20
    pos, ratio, adv, n = [], [], [], []
    for dd, (idx, w) in zip(D, picks):
        if len(idx) == 0:
            continue
        n.append(len(idx))
        tk = uniq[dd["tick"][idx]]
        a = dvm.reindex(pd.MultiIndex.from_arrays([[dd["date"]] * len(tk), tk])).to_numpy(float)
        p = w * BOOK_USD
        pos.extend(p); adv.extend(a); ratio.extend(p / a)
    ratio, adv = np.array(ratio, float), np.array(adv, float)
    ok = np.isfinite(ratio)
    return {"median_names_held": float(np.median(n)), "mean_position_usd": float(np.mean(pos)),
            "median_dv20_usd_of_held": float(np.nanmedian(adv)), "mean_position_over_dv20": float(np.mean(ratio[ok])),
            "p95_position_over_dv20": float(np.quantile(ratio[ok], 0.95)), "share_dv20_missing": float((~ok).mean())}


# ------------------------------------------------------------------ stages
def run_stage(stage):
    t0 = time.time()
    guard(stage)
    b, pool, dates, info = B.load_book(stage)
    D, uniq = B.prep(b)
    base = [B.picks_for(dd) for dd in D]
    var = [B.picks_for(dd, ~dd["bottom"]) for dd in D]
    n_rm = [int(dd["bottom"].sum()) for dd in D]
    # label-free Step-0 quantities on this stage's dates
    ov = [float(w[dd["bottom"][i]].sum()) for dd, (i, w) in zip(D, base) if len(i)]
    D = B.attach_labels(D, b, dates, stage)
    ev_b, nb = B.evaluate(D, base)
    ev_v, nv = B.evaluate(D, var)
    # check the cost-parameterised copy against cw_core.evaluate (15bp)
    for picks, ev in ((base, ev_b), (var, ev_v)):
        ek, _ = K.evaluate(D, picks)
        for a, c in zip(ev, ek):
            assert a["dates"] == c["dates"] and np.max(np.abs(a["ex"] - c["ex"])) < 1e-12, "evaluate copy != cw_core.evaluate"
    st = B.delta_stats(ev_v, ev_b)
    ev_b50, _ = B.evaluate(D, base, STRESS_BPS)
    ev_v50, _ = B.evaluate(D, var, STRESS_BPS)
    st50 = B.delta_stats(ev_v50, ev_b50)
    # paired random-removal null
    draws = []
    for k in range(N_DRAWS):
        rng = np.random.default_rng(SEED[stage] + k)
        npk = [B.picks_for(dd, B.null_keep(dd, r, rng)) for dd, r in zip(D, n_rm)]
        ev_n, _ = B.evaluate(D, npk)
        draws.append(float(np.mean([(a["ex"] - c["ex"]).mean() * B.ANN for a, c in zip(ev_n, ev_b)])))
        if (k + 1) % 20 == 0:
            log(f"  null {k + 1}/{N_DRAWS}")
    p50, p80 = float(np.median(draws)), float(np.quantile(draws, 0.80))
    d, do = st["delta"], st["delta_per_offset"]
    both_pos = all(x > 0 for x in do)
    if stage == 1:
        crit = {"delta_gt_0": d > 0, "delta_gt_null_p80": d > p80, "both_offsets_gt_0": both_pos,
                "loyo_min_gt_0": st["loyo_min"] > 0,
                "max_year_share_le_0.45": st["max_year_share"] is not None and st["max_year_share"] <= 0.45}
        kill = {"delta_le_0": d <= 0, "delta_le_null_p50": d <= p50, "offsets_opposite_sign": do[0] * do[1] < 0}
    else:
        crit = {"delta_gt_0": d > 0, "delta_gt_null_p80": d > p80, "both_offsets_gt_0": both_pos}
        kill = {"delta_le_0": d <= 0}
    verdict = "PASS" if all(crit.values()) else ("KILL" if any(kill.values()) else "MIDDLE")
    dv = dollar_volume(dates)
    out = {"stage": stage, "label_mode": "real", "window": [str(dates[0].date()), str(dates[-1].date())],
           "holdout_read": "none (2008-2018 in era)" if stage == 1 else "#23 (unfitted, frozen from Stage 1)",
           "load_info": info, "n_dates_book": [nb, nv], "cost_bps": RX.COST_BPS, "units": "fractions per year (x100 for %/yr)",
           "base": {"net_minus_spy_ann": B.level(ev_b), "per_offset": [float(o["ex"].mean() * B.ANN) for o in ev_b],
                    "gross_minus_spy_ann": B.level(ev_b, "gx"), "turnover_f_new": float(np.mean([o["f_new"] for o in ev_b]))},
           "variant": {"net_minus_spy_ann": B.level(ev_v), "per_offset": [float(o["ex"].mean() * B.ANN) for o in ev_v],
                       "gross_minus_spy_ann": B.level(ev_v, "gx"), "turnover_f_new": float(np.mean([o["f_new"] for o in ev_v]))},
           "delta": st, "null": {"n_draws": N_DRAWS, "seed": SEED[stage], "p50": p50, "p80": p80, "draws": draws},
           "criteria": crit, "kill": kill, "verdict": verdict,
           "DESCRIPTIVE": {"stress_50bp": {"base": B.level(ev_b50), "variant": B.level(ev_v50), "delta": st50["delta"],
                                           "delta_per_offset": st50["delta_per_offset"]},
                           "ew_thin_pool": ew_pool(D),
                           "base_minus_ew_pool_gross": B.level(ev_b, "gx") - ew_pool(D)["gross_minus_spy_ann"],
                           "variant_minus_ew_pool_gross": B.level(ev_v, "gx") - ew_pool(D)["gross_minus_spy_ann"],
                           "capacity_base": capacity(D, base, uniq, dv), "capacity_variant": capacity(D, var, uniq, dv),
                           "base_weight_in_bottom_decile": float(np.mean(ov)),
                           "median_names_removed": float(np.median(n_rm))},
           "runtime_s": time.time() - t0}
    if stage == 2:
        out["ex_2019_delta"] = st["loyo"].get(2019)
        out["ex_2020_delta"] = st["loyo"].get(2020)
    dump(RESULT[stage], out)
    log(f"stage {stage}: delta {100 * d:+.3f}%/yr offsets {[round(100 * x, 3) for x in do]} null p50 {100 * p50:+.3f} "
        f"p80 {100 * p80:+.3f} LOYO min {100 * st['loyo_min']:+.3f} -> {verdict}")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--mode", choices=["reproduce", "stage1", "stage2"], required=True)
    a = ap.parse_args()
    if a.mode == "reproduce":
        reproduce()
    else:
        run_stage(1 if a.mode == "stage1" else 2)


if __name__ == "__main__":
    main()
