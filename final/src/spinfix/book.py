"""WO-54 Phase 2 (pre-registered): icw5_seas book with and without the spin-off label fix.

Pre-registration: final/models/2026-10-09-spinoff-label-fix-prereg.md (committed 09d829a, hash asserted).
icw5_seas, v2 column c, cap150, decile_volq, net 15bp, h=40, 40 offsets, 2007-01-02..2019-12-31, excess vs SPY.
Harness: WO-48b/WO-53 path (signcheck/dropcheck.load("A"), score, picks_fast, chains) from this worktree's
final/src (== origin/integration d09101b), reconciled to REF_V5 at 1e-10. Fixed run = same code with the label
array replaced by final/data/wrds/crsp/derived/spinfix_labels.parquet (built by events.py).
Writes final/out/spinfix/phase2.json (aggregates + top-20 name-dates).
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
PREREG = FINAL / "models" / "2026-10-09-spinoff-label-fix-prereg.md"
PREREG_SHA = "1c1a22ae7f898d85b1cf85db2ca8bed5b14b2ac0dea2037432ca0e15bae29ccd"
assert hashlib.sha256(PREREG.read_bytes()).hexdigest() == PREREG_SHA, "PRE-REG CHANGED SINCE FREEZE: STOP"
sys.path.insert(0, str(SRC / "signcheck"))
import dropcheck as D  # noqa: E402
sys.path.insert(0, str(SRC / "wrds_crsp"))
import common as K  # noqa: E402

S, G = D.S, D.G
REF_V5 = 0.036442521084825354          # WO-48b real_A.json arms.D4.arm_mean40 (weights == V5_SEAS)
HOLDOUT = pd.Timestamp("2020-01-01")
H = 40
OUT = FINAL / "out" / "spinfix"
log = D.log


def pick_weights(vol, comp, ret, code):
    """fast_pick (top leg) returning per-pick codes and normalised weights (after NaN-label drop)."""
    if len(vol) < 20:
        return None
    valid = np.isfinite(vol) & np.isfinite(comp)
    if valid.sum() < 20:
        return None
    idx = np.flatnonzero(valid)
    vol_v, comp_v, ret_v, code_v = vol[idx], comp[idx], ret[idx], code[idx]
    q = pd.qcut(vol_v, 5, labels=False, duplicates="drop")
    buckets = [np.flatnonzero(q == b) for b in np.unique(q)]
    sel = np.concatenate([b[np.argsort(-comp_v[b])][:max(1, int(round(len(b) * 0.10)))] for b in buckets])
    inv = 1.0 / np.maximum(vol_v[sel], 1e-4)
    w = inv / inv.sum()
    r = ret_v[sel]
    k = np.isfinite(r)
    if not k.any():
        return None
    w = w[k] / w[k].sum()
    return code_v[sel][k], w, idx[sel][k]


def stats(ch):
    po = G["DD"].per_offset(ch)
    return po, {"mean40": float(po.mean()), "sd40": float(po.std()), "min40": float(po.min()),
                "max40": float(po.max()), "offsets_positive": int((po > 0).sum())}


def sens_retx(lab, key, ret0, sc, po0):
    """Post-hoc, not judged: target CRSP retx instead of ret on the 9 events where they differ (a cash leg
    paid with the spin; the price-only label excludes cash). label_x = (1+label_fix) * prod (1+retx)/(1+ret)."""
    ev = pd.read_parquet(K.DERIVED / "spinfix_events.parquet", columns=["ticker", "exdt", "r_C", "r_Cx", "applied"])
    ev = ev[ev.applied.fillna(False).astype(bool)]
    ratio = {(t, str(pd.Timestamp(d).date())): (1 + rx) / (1 + rc) for t, d, rc, rx in
             zip(ev.ticker, ev.exdt, ev.r_C, ev.r_Cx)}
    adj = np.array([np.prod([ratio[(t, d)] for d in e.split(";")]) for t, e in zip(lab.ticker, lab.events)])
    lx = lab.assign(lx=(1 + lab.label_fix) * adj - 1).set_index(["ticker", "date"]).lx.reindex(key).to_numpy(np.float64)
    hit = np.isfinite(lx)
    r2 = ret0.copy()
    r2[hit] = lx[hit]
    G["ret"] = r2
    ch = S.chains(S.picks_fast(sc))
    G["ret"] = ret0
    d = G["DD"].per_offset(ch) - po0
    return {"events_changed": int(sum(abs(v - 1) > 1e-6 for v in ratio.values())),
            "delta_mean40": float(d.mean()), "offsets_positive": int((d > 0).sum())}


def main():
    t0 = time.time()
    U = D.load("A")
    assert U["date"].max() < HOLDOUT and max(G["all_dates"]) < HOLDOUT and G["spy"].index.max() < HOLDOUT, "HOLD-OUT BREACH"
    V5 = dict(G["ICW"].PRODUCTION_WEIGHTS_V5_SEAS)
    assert set(V5) <= set(G["rz"]), "harness has no rank array for a V5 factor"
    sc = S.score(V5)
    ret0 = G["ret"].copy()
    pk0 = S.picks_fast(sc)
    ch0 = S.chains(pk0)
    po0, st0 = stats(ch0)
    assert abs(st0["mean40"] - REF_V5) < 1e-10, f"V5 RECONCILE FAIL {st0['mean40']} vs {REF_V5}"
    log(f"unfixed icw5_seas {st0['mean40']:+.6%} reconcile OK (ref {REF_V5:+.6%})")

    lab = pd.read_parquet(K.DERIVED / "spinfix_labels.parquet", columns=["ticker", "date", "label_fix", "gross_return_40", "events"])
    lab["date"] = pd.to_datetime(lab.date)
    key = pd.MultiIndex.from_arrays([U["ticker"].astype(str), U["date"]])
    li = lab.set_index(["ticker", "date"])
    assert li.index.is_unique
    fix = li.label_fix.reindex(key).to_numpy(np.float64)
    old = li.gross_return_40.reindex(key).to_numpy(np.float64)
    hit = np.isfinite(fix)
    assert np.array_equal(old[hit].astype(np.float32), ret0[hit].astype(np.float32), equal_nan=True), "label cache != harness label"
    ret1 = ret0.copy()
    ret1[hit] = fix[hit]
    assert np.array_equal(np.isfinite(ret0), np.isfinite(ret1)), "fix changed NaN status"
    log(f"panel rows with a fixed label: {int(hit.sum()):,} (cap150 eligible rows of the book universe)")
    G["ret"] = ret1
    pk1 = S.picks_fast(sc)
    ch1 = S.chains(pk1)
    G["ret"] = ret0
    po1, st1 = stats(ch1)
    assert set(pk0) == set(pk1) and all(pk0[d][1] == pk1[d][1] for d in pk0), "pick sets differ"
    dpo = po1 - po0
    delta = float(dpo.mean())
    log(f"fixed {st1['mean40']:+.6%}  delta {delta:+.6%}  offsets>0 {(dpo > 0).sum()}/40")

    # LOYO of delta
    yrs, m0 = G["DD"].loyo_vec(ch0)
    yrs1, m1 = G["DD"].loyo_vec(ch1)
    assert yrs == yrs1
    loyo = {int(y): float(v) for y, v in zip(yrs, (m1 - m0).mean(axis=0))}

    # exact attribution
    h = (G["cost"] / 1e4) / 2.0
    knet, noff = {}, {}
    for c in ch0:
        for d, f in zip(c["date"], c["f_new"]):
            knet[pd.Timestamp(d)] = ((1 - h * f) / (1 + h * f), len(c["date"]))
    vol, code = G["vol"], G["code"]
    rows = []
    gross_chk = 0.0
    for d, s, e in G["sl"]:
        if d not in pk0:
            continue
        pw = pick_weights(vol[s:e], sc[s:e], ret0[s:e], code[s:e])
        cds, w, loc = pw
        g0 = float((w * (1 + ret0[s:e][loc])).sum() - 1)
        gross_chk = max(gross_chk, abs(g0 - pk0[d][0]))
        assert frozenset(cds.tolist()) == pk0[d][1]
        dr = ret1[s:e][loc] - ret0[s:e][loc]
        if not np.any(dr != 0) or pd.Timestamp(d) not in knet:
            continue
        k, n = knet[pd.Timestamp(d)]
        for j in np.flatnonzero(dr != 0):
            rows.append({"date": pd.Timestamp(d), "ticker": G["uniq"][cds[j]], "w": float(w[j]),
                         "r": float(ret0[s:e][loc[j]]), "r_fix": float(ret1[s:e][loc[j]]),
                         "contrib": float(w[j] * dr[j] * k * S.ANN / (H * n))})
    assert gross_chk < 1e-12, gross_chk
    cb = pd.DataFrame(rows)
    csum = float(cb.contrib.sum()) if len(cb) else 0.0
    assert abs(csum - delta) < 1e-9, (csum, delta)
    cb = cb.merge(lab[["ticker", "date", "events"]], on=["ticker", "date"], how="left")
    top = cb.reindex(cb.contrib.abs().sort_values(ascending=False).index).head(20)
    by_tk = cb.groupby("ticker").contrib.sum().sort_values(key=np.abs, ascending=False)
    out = {"model": "icw5_seas", "era": ["2007-01-02", "2019-12-31"], "tier": "cap150", "cost_bps": G["cost"],
           "reconcile_ref_REF_V5": REF_V5, "reconcile_diff": st0["mean40"] - REF_V5,
           "unfixed": st0, "fixed": st1,
           "delta_mean40": delta, "delta_offsets_positive": int((dpo > 0).sum()),
           "delta_offsets_zero": int((dpo == 0).sum()),
           "delta_min40": float(dpo.min()), "delta_max40": float(dpo.max()), "delta_loyo": loyo,
           "delta_loyo_min": min(loyo.values()), "delta_loyo_max": max(loyo.values()),
           "abs_delta_gt_0p25pp": bool(abs(delta) > 0.0025),
           "pick_rows_changed": int(len(cb)), "pick_dates_changed": int(cb.date.nunique()) if len(cb) else 0,
           "contrib_sum_check": csum, "picker_weight_gross_max_abs_diff": gross_chk,
           "fixed_label_rows_in_book_universe": int(hit.sum()),
           "top20_name_dates": [{"ticker": r.ticker, "date": str(r.date.date()), "w": round(r.w, 5), "r": round(r.r, 4),
                                 "r_fix": round(r.r_fix, 4), "contrib_pp": round(r.contrib * 100, 4), "events": r.events}
                                for r in top.itertuples()],
           "top10_tickers_contrib_pp": {k: round(float(v) * 100, 4) for k, v in by_tk.head(10).items()},
           "per_offset_unfixed": po0.tolist(), "per_offset_fixed": po1.tolist(),
           "units": "fractions per year (0.01 = 1%/yr), 40-offset mean, net 15bp, excess vs SPY"}
    out["sensitivity_retx_target_posthoc_not_judged"] = sens_retx(lab, key, ret0, sc, po0)
    OUT.mkdir(parents=True, exist_ok=True)
    (OUT / "phase2.json").write_text(json.dumps(out, indent=1, default=float))
    log(f"done ({time.time()-t0:.0f}s): delta {delta:+.4%}/yr, {out['delta_offsets_positive']}/40 positive, "
        f"{len(cb)} pick-rows changed, |delta|>0.25pp {out['abs_delta_gt_0p25pp']}")


if __name__ == "__main__":
    main()
