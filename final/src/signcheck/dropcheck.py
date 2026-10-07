"""
WO-48b (Gabe 2026-10-07): drop the floor-weight factors? Parsimony test.
Pre-registration: final/models/2026-10-07-floor-weight-drop-test.md
(committed and pushed before any number is computed).

Arms: D3 = drop pct_from_high_252, volatility_60, days_to_next_filing_seasonal;
      D4 = D3 + short_interest_days_to_cover. Remaining weights rescaled to the same |w|.
K = base - arm (value of keeping). Null: dropped columns shuffled within date at live
weights; K_null = shuffled - arm. Gate (era B only): KEEP iff K_B > 0 and K_B > p80_B.

Era A 2007-2019 (descriptive), era B 2020-01-02..2026-07-30 (hold-out read #21, unfitted).
One era per process (G is process-global).

Usage (python = /opt/anaconda3/envs/pipe_dream/bin/python, under caffeinate -i):
  dropcheck.py --era A --real            -> drop/parts/real_A.json
  dropcheck.py --era A --null 100 --procs 4
  dropcheck.py --era A --recheck
  (same for --era B)
  dropcheck.py --aggregate 100           -> drop/dropcheck_report.json
"""
import argparse
import json
import sys
import time
from pathlib import Path

import numpy as np
import pandas as pd

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
import signcheck as S  # noqa: E402  (also imports stateint, which sets sys.path)

STI, G = S.STI, S.G
OUT = S.OUT / "drop"
PARTS = OUT / "parts"
NULLD = PARTS / "null"
FLOOR = ["pct_from_high_252", "volatility_60", "days_to_next_filing_seasonal", "short_interest_days_to_cover"]
ARMS = {"D3": FLOOR[:3], "D4": FLOOR}
SEED0 = 48000
SI_SEED0 = 3000
HOLDOUT = pd.Timestamp("2020-01-01")
B_HI = pd.Timestamp("2026-07-30")
REF_A = 0.0348652
REF_B = -0.02016365566661011
SUB_LO = S.SUB_LO
log = S.log


# ------------------------------------------------------------------ load
def load(era):
    import model_audit_wo23 as MA
    import trailfilter as TF
    import drag_decomp as DD
    import pool_read as PR
    import run_backtest as RB
    MA.SEAS_EXT = TF.SEAS_EXT_RO
    V, SI, DR, ICW = MA.V, MA.SI, MA.DR, MA.ICW
    assert DD.ANN == S.ANN and RB.HORIZON == 40 and DR.COST_BPS == 15.0
    U, all_dates, spy = MA.load_theo(era, "cap150")
    all_dates = [pd.Timestamp(d) for d in all_dates]
    if era == "A":
        assert U["date"].max() < HOLDOUT and spy.index.max() < HOLDOUT and max(all_dates) < HOLDOUT, "HOLD-OUT BREACH"
    else:
        assert min(all_dates) >= HOLDOUT and max(all_dates) <= B_HI and U["date"].max() <= B_HI
    W9 = dict(ICW.PRODUCTION_WEIGHTS_V9_SEAS)
    assert W9 == MA.W9 and list(W9) == MA.FT
    for f in FLOOR:
        assert abs(abs(W9[f]) - 0.0105) < 1e-12, (f, W9[f])
    V.add_ranks(U, MA.FT)
    book = V.Book(U, all_dates, spy)
    G.update(MA=MA, TF=TF, DD=DD, PR=PR, RB=RB, V=V, SI=SI, DR=DR, ICW=ICW, U=U, all_dates=all_dates, spy=spy,
             book=book, W9=W9, FT=list(MA.FT), cost=DR.COST_BPS, sl=book.sl, vol=book.vol,
             ret=book.ret.astype(np.float64), code=pd.factorize(U["ticker"])[0].astype(np.int64))
    assert np.array_equal(book.ret.astype(np.float64), U["gross_return_40"].to_numpy(np.float64), equal_nan=True)
    G["uniq"] = pd.factorize(U["ticker"])[1].to_numpy()
    G["rz"] = {f: U[f"rz_{f}"].to_numpy(np.float64) for f in G["FT"]}
    G["score9"] = SI.composite_score(U, W9).to_numpy(np.float64)
    log(f"[{era}] loaded {len(U):,} rows, {len(all_dates)} dates {all_dates[0].date()}..{all_dates[-1].date()}")
    return U


def arm_weights(drop):
    W9 = G["W9"]
    tot = sum(abs(v) for v in W9.values())
    rest = {k: v for k, v in W9.items() if k not in drop}
    sc = tot / sum(abs(v) for v in rest.values())
    return {k: v * sc for k, v in rest.items()}


def base_chain(era):
    """Reconcile + oracle; returns base chains."""
    DD, PR, DR = G["DD"], G["PR"], G["DR"]
    s9 = S.score(G["W9"])
    assert np.array_equal(np.isnan(s9), np.isnan(G["score9"])) and np.nanmax(np.abs(s9 - G["score9"])) < 1e-15
    pkw = PR.picks_w(G["book"], G["score9"])
    chw = DD.chains({d: (v[0], v[1]) for d, v in pkw.items()}, G["all_dates"], G["spy"], DR.COST_BPS)
    ref_got = float(DD.per_offset(chw).mean())
    ref = REF_A if era == "A" else REF_B
    assert abs(ref_got - ref) < 1e-6, f"RECONCILE FAIL {era} {ref_got} vs {ref}"
    pk = S.picks_fast(G["score9"])
    assert set(pk) == set(pkw), "picker date set differs"
    for d, (g, cs) in pk.items():
        assert abs(g - pkw[d][0]) < 1e-12 and set(G["uniq"][list(cs)]) == set(pkw[d][1]), d
    ch = S.chains(pk)
    got = float(DD.per_offset(ch).mean())
    assert abs(got - ref_got) < 1e-12, (got, ref_got)
    log(f"[{era}] base reconcile OK {got:+.7f} (ref {ref}); fast picker == picks_w on {len(pk)} dates")
    return ch, {"got": got, "ref": ref, "picks_w_mean40": ref_got, "n_pick_dates": len(pk)}


def kblock(ch_b, ch_a):
    """K = base - arm, via diff_block(arm, base) (diff_block reports second - first)."""
    r = S.diff_block(ch_a, ch_b)
    r["K"] = r.pop("diff")
    r["K_offsets_pos"] = r.pop("diff_offsets_pos")
    return r


# ------------------------------------------------------------------ real
def run_real(era):
    T0 = time.time()
    PARTS.mkdir(parents=True, exist_ok=True)
    load(era)
    ch_b, rec = base_chain(era)
    po_b = G["DD"].per_offset(ch_b)
    out = {"era": era, "holdout_read": 21 if era == "B" else None, "reconcile": rec,
           "base": {"mean40": float(po_b.mean()), "sd40": float(np.std(po_b)), "offsets_pos": int((po_b > 0).sum())},
           "arms": {}}
    ident = S.diff_block(ch_b, S.chains(S.picks_fast(S.score(G["W9"]))))
    assert ident["diff"] == 0.0, "identity book diff != 0"
    for a, drop in ARMS.items():
        w = arm_weights(drop)
        assert abs(sum(abs(v) for v in w.values()) - sum(abs(v) for v in G["W9"].values())) < 1e-12
        ch_a = S.chains(S.picks_fast(S.score(w)))
        r = kblock(ch_b, ch_a)
        r["weights"] = w
        r["arm_mean40"] = float(G["DD"].per_offset(ch_a).mean())
        pb, pa = S.picks_fast(G["score9"]), S.picks_fast(S.score(w))
        r["pick_overlap_mean"] = float(np.mean([len(pb[d][1] & pa[d][1]) / len(pb[d][1]) for d in pb if d in pa]))
        out["arms"][a] = r
        log(f"[{era}] {a}: K = base - arm {r['K']*100:+.4f} pp/yr, K>0 on {r['K_offsets_pos']}/40 ({time.time()-T0:.0f}s)")
    if era == "A":
        f = "short_interest_days_to_cover"
        ch_a = S.chains(S.picks_fast(S.score(arm_weights([f]))))
        out["si_alone"] = kblock(ch_b, ch_a)
        log(f"[A] si alone: K {out['si_alone']['K']*100:+.4f} ({out['si_alone']['K_offsets_pos']}/40)")
    out["runtime_s"] = time.time() - T0
    (PARTS / f"real_{era}.json").write_text(json.dumps(out, indent=1, default=float))


# ------------------------------------------------------------------ null
def shuffled_rz(f, seed):
    v = G["V"].shuffle_within_date(G["U"], f, seed)
    return G["SI"].rank_z(pd.DataFrame({"date": G["U"]["date"], "x": v}), "x").to_numpy(np.float64)


def null_one(job, path=None):
    era, a, s = job
    p = path or NULLD / f"{era}_{a}_{s:03d}.json"
    if p.exists():
        return job
    if a == "SI":
        cols = ["short_interest_days_to_cover"]
        ov = {cols[0]: shuffled_rz(cols[0], SI_SEED0 + s)}
        w_arm = arm_weights(cols)
    else:
        cols = ARMS[a]
        ov = {f: shuffled_rz(f, SEED0 + 1000 * FLOOR.index(f) + s) for f in cols}
        w_arm = arm_weights(cols)
    ch_s = S.chains(S.picks_fast(S.score(G["W9"], ov)))
    po = G["DD"].per_offset
    k = po(ch_s) - po(G["ch_arm"][a])
    p.write_text(json.dumps({"era": era, "arm": a, "draw": s, "K_null": float(k.mean()), "offsets_pos": int((k > 0).sum())}))
    return job


def prep_null(era):
    load(era)
    G["ch_b"] = S.chains(S.picks_fast(G["score9"]))
    ref = REF_A if era == "A" else REF_B
    assert abs(G["DD"].per_offset(G["ch_b"]).mean() - ref) < 1e-6
    G["ch_arm"] = {a: S.chains(S.picks_fast(S.score(arm_weights(c)))) for a, c in ARMS.items()}
    if era == "A":
        G["ch_arm"]["SI"] = S.chains(S.picks_fast(S.score(arm_weights(["short_interest_days_to_cover"]))))


def run_null(era, n, procs):
    import multiprocessing as mp
    NULLD.mkdir(parents=True, exist_ok=True)
    prep_null(era)
    arms = list(ARMS) + (["SI"] if era == "A" else [])
    todo = [(era, a, s) for a in arms for s in range(n) if not (NULLD / f"{era}_{a}_{s:03d}.json").exists()]
    log(f"[{era}] null: {len(todo)} draws on {procs} procs")
    with mp.get_context("fork").Pool(procs) as pool:
        for i, j in enumerate(pool.imap_unordered(null_one, todo)):
            if i % 20 == 0:
                log(f"null {j} done ({i+1}/{len(todo)})")


def run_recheck(era):
    prep_null(era)
    out = {}
    for a in list(ARMS) + (["SI"] if era == "A" else []):
        q = PARTS / f"recheck_{era}_{a}.json"
        q.unlink(missing_ok=True)
        null_one((era, a, 0), q)
        x = json.loads((NULLD / f"{era}_{a}_000.json").read_text())["K_null"]
        y = json.loads(q.read_text())["K_null"]
        q.unlink()
        out[a] = {"draw0": x, "rerun": y, "identical": x == y}
        log(f"[{era}] recheck {a}: identical={x == y}")
    (PARTS / f"null_recheck_{era}.json").write_text(json.dumps(out, indent=1))
    assert all(v["identical"] for v in out.values()), "NULL RERUN MISMATCH"


# ------------------------------------------------------------------ aggregate
def aggregate(n):
    rep = {"work_order": "WO-48b", "prereg": "final/models/2026-10-07-floor-weight-drop-test.md",
           "units": "fractions per year; K = base - arm (value of keeping the dropped factors)",
           "gate": "era B only: KEEP iff K_B > 0 and K_B > p80(K_null_B); else DROP", "eras": {}, "verdict": {}}
    for era in ("A", "B"):
        real = json.loads((PARTS / f"real_{era}.json").read_text())
        e = {"reconcile": real["reconcile"], "base": real["base"], "arms": {},
             "null_draw0_rerun": json.loads((PARTS / f"null_recheck_{era}.json").read_text())}
        arms = dict(real["arms"])
        if era == "A":
            arms["SI"] = real["si_alone"]
        for a, r in arms.items():
            kn = np.array([json.loads((NULLD / f"{era}_{a}_{s:03d}.json").read_text())["K_null"] for s in range(n)])
            r["null"] = {"n": n, "p50": float(np.percentile(kn, 50)), "p80": float(np.percentile(kn, 80)),
                         "p95": float(np.percentile(kn, 95)), "mean": float(kn.mean()), "sd": float(kn.std()),
                         "pct_null_below_K": float((kn < r["K"]).mean())}
            e["arms"][a] = r
        rep["eras"][era] = e
    for a in ARMS:
        r = rep["eras"]["B"]["arms"][a]
        keep = bool(r["K"] > 0 and r["K"] > r["null"]["p80"])
        rep["verdict"][a] = {"K_B": r["K"], "p80_B": r["null"]["p80"], "KEEP": keep, "verdict": "KEEP" if keep else "DROP"}
    v3, v4 = rep["verdict"]["D3"]["verdict"], rep["verdict"]["D4"]["verdict"]
    rep["recommendation"] = ("keep all four" if v3 == "KEEP" else
                             "drop all four at the next batch retune" if v4 == "DROP" else
                             "drop the three, keep short_interest_days_to_cover")
    OUT.mkdir(parents=True, exist_ok=True)
    (OUT / "dropcheck_report.json").write_text(json.dumps(rep, indent=1, default=float))
    for era in ("A", "B"):
        for a, r in rep["eras"][era]["arms"].items():
            print(f"[{era}] {a}: K {r['K']*100:+.4f} pp/yr K>0 {r['K_offsets_pos']}/40 LOYO min K {r['loyo_min']*100:+.4f} "
                  f"| null p50 {r['null']['p50']*100:+.4f} p80 {r['null']['p80']*100:+.4f} pct<K {r['null']['pct_null_below_K']:.2f} "
                  f"| sub11 K {r['sub_2011_10']['diff']*100:+.4f}")
    print(json.dumps(rep["verdict"], indent=1), "\n", rep["recommendation"])


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--era", choices=["A", "B"])
    ap.add_argument("--real", action="store_true")
    ap.add_argument("--null", type=int, default=0)
    ap.add_argument("--procs", type=int, default=4)
    ap.add_argument("--recheck", action="store_true")
    ap.add_argument("--aggregate", type=int, default=0)
    a = ap.parse_args()
    if a.real:
        run_real(a.era)
    if a.null:
        run_null(a.era, a.null, a.procs)
    if a.recheck:
        run_recheck(a.era)
    if a.aggregate:
        aggregate(a.aggregate)


if __name__ == "__main__":
    main()
