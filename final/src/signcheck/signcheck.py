"""
WO-48 (COO): factor sign vs decile_volq construction check.
Pre-registration: final/models/2026-10-07-factor-sign-construction.md
(committed and pushed before any outcome was computed).

Factors: pct_from_high_252, volatility_60, days_to_next_filing_seasonal
(WO-46: pooled decile_volq LS sign != signed IC sign).

Era 2007-01-02..2019-12-31 ONLY (hard assert). No hold-out read.
Harness: WO-46 final/src/stateint/stateint.py imported read-only
(load_all, reconcile_book, fast_pick, ls_chain), which itself imports
model_audit_wo23.load_theo, screen_insider(_v2grid), pool_read.picks_w,
drag_decomp, trailfilter.

Usage (python = /opt/anaconda3/envs/pipe_dream/bin/python, under caffeinate -i):
  signcheck.py --real              reconcile + Test 1 deciles + LOO + flip -> parts/real.json
  signcheck.py --null N --procs P  shuffled-factor draws                   -> parts/null/<f>_XXX.json
  signcheck.py --aggregate         -> signcheck_report.json
"""
import argparse
import json
import sys
import time
from pathlib import Path

import numpy as np
import pandas as pd

HERE = Path(__file__).resolve().parent
SRC = HERE.parent
FINAL = HERE.parents[1]
OUT = FINAL / "out" / "signcheck"
PARTS = OUT / "parts"
NULLD = PARTS / "null"
sys.path.insert(0, str(SRC / "stateint"))
import stateint as STI  # noqa: E402

G = STI.G
HOLDOUT = pd.Timestamp("2020-01-01")
SUB_LO = pd.Timestamp("2011-10-01")
ANN = 252.0 / 40
FACTORS = ["pct_from_high_252", "volatility_60", "days_to_next_filing_seasonal"]
SEED_BASE = {f: 1000 * j for j, f in enumerate(FACTORS)}
WO46_LS = {}          # filled from the committed WO-46 report (reconcile target)
OFF_MIN, YEAR_SHARE_MAX = 30, 0.45


def log(m):
    print(f"[{time.strftime('%H:%M:%S')}] {m}", flush=True)


# ------------------------------------------------------------------ setup
def setup():
    U = STI.load_all(need_states=False)
    assert U["date"].max() < HOLDOUT and max(G["all_dates"]) < HOLDOUT and G["spy"].index.max() < HOLDOUT, "HOLD-OUT BREACH"
    G["rz"] = {f: U[f"rz_{f}"].to_numpy(np.float64) for f in G["FT"]}
    rep = json.loads((FINAL / "out" / "stateint" / "state_interactions_report.json").read_text())
    for f in FACTORS:
        WO46_LS[f] = rep["pooled"][f]["ls_net"]
    return U


def score(weights, override=None):
    """numpy screen_insider.composite_score (same accumulation order); override = {factor: rz array}."""
    n = len(G["U"])
    num, den, cov = np.zeros(n), np.zeros(n), np.zeros(n, dtype=np.int64)
    for c, w in weights.items():
        rz = override[c] if (override and c in override) else G["rz"][c]
        ok = ~np.isnan(rz)
        num += np.where(ok, rz * w, 0.0)
        den += np.where(ok, abs(w), 0.0)
        cov += ok
    with np.errstate(invalid="ignore", divide="ignore"):
        out = num / np.where(den == 0, np.nan, den)
    out[cov == 0] = np.nan
    return out


def picks_fast(sc):
    vol, ret, code = G["vol"], G["ret"], G["code"]
    pk = {}
    for d, s, e in G["sl"]:
        t, _ = STI.fast_pick(vol[s:e], sc[s:e], ret[s:e], code[s:e], both=False)
        if t is not None:
            pk[d] = t
    return pk


def chains(pk):
    return G["DD"].chains(pk, G["all_dates"], G["spy"], G["cost"])


def diff_block(ch_b, ch_a, base_sd40=None, p80=None):
    DD, TF = G["DD"], G["TF"]
    r = TF.diff_stats(DD, ch_b, ch_a, 2008, per_year=True)
    dw = np.concatenate([a["exc"] - b["exc"] for b, a in zip(ch_b, ch_a)])
    yy = np.concatenate([[pd.Timestamp(t).year for t in b["date"]] for b in ch_b])
    tot = float(dw.sum())
    shares = {int(y): float(dw[yy == y].sum() / tot) for y in np.unique(yy)} if tot > 0 else None
    loyo = np.array(list(r["diff_loyo_by_dropped_year"].values()))
    Y = len(loyo)
    se = float(np.sqrt((Y - 1) / Y * ((loyo - loyo.mean()) ** 2).sum()))
    sub = np.array([((a["exc"] - b["exc"])[b["date"] >= np.datetime64(SUB_LO)]).mean() * ANN
                    for b, a in zip(ch_b, ch_a)])
    r.update({"diff_total_window_sum": tot, "diff_year_shares": shares,
              "max_year_share": (max(shares.values()) if shares else None),
              "max_share_year": (max(shares, key=shares.get) if shares else None),
              "loyo_min": float(loyo.min()), "loyo_min_dropped_year": int(list(r["diff_loyo_by_dropped_year"])[int(loyo.argmin())]),
              "jackknife_t": float(r["diff"] / se) if se > 0 else None,
              "diff_per_offset": (DD.per_offset(ch_a) - DD.per_offset(ch_b)).tolist(),
              "sub_2011_10": {"diff": float(sub.mean()), "offsets_pos": int((sub > 0).sum())}})
    return r


# ------------------------------------------------------------------ Test 1
def decile_tables(U, f):
    SI, V, MA = G["SI"], G["V"], G["MA"]
    lab = MA.LABEL
    sgn = int(np.sign(G["W9"][f]))
    d = U[["date", f, lab, "volatility_60"]].replace([np.inf, -np.inf], np.nan).dropna(subset=[f, lab]).copy()
    d["y"] = d[lab] - d.groupby("date")[lab].transform("mean")
    r = d.groupby("date")[f].rank(method="first")
    n = d.groupby("date")[f].transform("count")
    d = d[n >= 10]
    r, n = r[d.index], n[d.index]
    d["dec"] = (np.floor((r - 1) * 10 / n) + 1).astype(int)
    m = d.groupby(["date", "dec"])["y"].mean().unstack()
    dm = m.mean()                                     # each date equal weight
    yr = m.index.year
    from scipy.stats import spearmanr
    out = {"book_sign": sgn, "n_dates": int(len(m)),
           "decile_mean_demeaned_40d": {int(k): float(v) for k, v in dm.items()},
           "spearman_decile_vs_mean": float(spearmanr(np.arange(1, 11), dm.values)[0]),
           "D10_minus_D1": float(dm[10] - dm[1]),
           "tails": {"D1": float(dm[1]), "D10": float(dm[10]),
                     "middle_D2_D9_slope_per_decile": float(np.polyfit(np.arange(2, 10), dm.loc[2:9].values, 1)[0]),
                     "middle_D2_D9_spearman": float(spearmanr(np.arange(2, 10), dm.loc[2:9].values)[0]),
                     "D2_9_mean": float(dm.loc[2:9].mean())}}
    ic = SI.daily_corr(U, f, lab)
    out["ic"] = {**V.nw(ic.to_numpy()), "signed_t_book_dir": float(V.nw(ic.to_numpy())["t"] * sgn)}
    out["per_year"] = {int(y): {"ic_mean": float(ic[ic.index.year == y].mean()),
                                "D10_minus_D1": float((m[10] - m[1])[yr == y].mean())} for y in np.unique(yr)}
    # within volatility_60 quintile (the decile_volq bucketing), then averaged over quintiles
    dv = d.dropna(subset=["volatility_60"]).copy()
    rv = dv.groupby("date")["volatility_60"].rank(method="first")
    nv = dv.groupby("date")["volatility_60"].transform("count")
    dv["vq"] = np.floor((rv - 1) * 5 / nv).astype(int)
    r2 = dv.groupby(["date", "vq"])[f].rank(method="first")
    n2 = dv.groupby(["date", "vq"])[f].transform("count")
    dv = dv[n2 >= 10]
    r2, n2 = r2[dv.index], n2[dv.index]
    dv["dec"] = (np.floor((r2 - 1) * 10 / n2) + 1).astype(int)
    dv["yq"] = dv["y"] - dv.groupby(["date", "vq"])["y"].transform("mean")
    mq = dv.groupby(["vq", "date", "dec"])["yq"].mean().unstack().groupby(level="vq").mean()
    out["within_volq"] = {"decile_mean_avg_over_vq": {int(k): float(v) for k, v in mq.mean().items()},
                          "D10_minus_D1_by_vq": {int(q) + 1: float(mq.loc[q, 10] - mq.loc[q, 1]) for q in mq.index},
                          "spearman_avg": float(spearmanr(np.arange(1, 11), mq.mean().values)[0])}
    # top-minus-bottom decile in the book's direction: equal vs inverse-vol weight
    top, bot = (10, 1) if sgn > 0 else (1, 10)
    dd = d.dropna(subset=["volatility_60"]).copy()
    dd["iw"] = 1.0 / np.maximum(dd["volatility_60"], 1e-4)
    dd["iwy"] = dd["iw"] * dd["y"]
    def leg(k, w):
        s = dd[dd["dec"] == k]
        if not w:
            return s.groupby("date")["y"].mean()
        g = s.groupby("date")
        return g["iwy"].sum() / g["iw"].sum()
    out["book_dir_top_minus_bottom"] = {
        "equal_weight": float((leg(top, False) - leg(bot, False)).mean()),
        "inverse_vol_weight": float((leg(top, True) - leg(bot, True)).mean()),
        "note": "40d date-demeaned excess (not annualised); top = book-direction best decile"}
    return out


def ls_pooled(f):
    """WO-46 pooled decile_volq long-short for factor f (reconciled to the WO-46 report), with per-year."""
    S = np.sign(G["W9"][f]) * G["rz"][f]
    pt, pb = {}, {}
    vol, ret, code = G["vol"], G["ret"], G["code"]
    for d, s, e in G["sl"]:
        t, b = STI.fast_pick(vol[s:e], S[s:e], ret[s:e], code[s:e])
        if t is not None:
            pt[d] = t
        if b is not None:
            pb[d] = b
    ch = STI.ls_chain(pt, pb)
    po = STI.off_mean(ch)
    got = float(po.mean())
    assert abs(got - WO46_LS[f]) < 1e-10, f"LS RECONCILE FAIL {f} {got} vs {WO46_LS[f]}"
    acc = {}
    for c in ch:
        yy = np.array([pd.Timestamp(t).year for t in c["date"]])
        for y in np.unique(yy):
            k = yy == y
            acc.setdefault(int(y), {"ls": [], "top": [], "bot": []})
            acc[int(y)]["ls"].append(c["ls"][k].mean() * ANN)
            acc[int(y)]["top"].append(c["top_net"][k].mean() * ANN)
            acc[int(y)]["bot"].append(c["bot_net"][k].mean() * ANN)
    return {"ls_net": got, "wo46_ls_net": WO46_LS[f], "ls_offsets_pos": int((po > 0).sum()),
            "top_net": float(STI.off_mean(ch, "top_net").mean()), "bot_net": float(STI.off_mean(ch, "bot_net").mean()),
            "per_year": {y: {k: float(np.mean(v)) for k, v in a.items()} for y, a in sorted(acc.items())}}


# ------------------------------------------------------------------ real
def run_real(reconcile_only=False):
    T0 = time.time()
    PARTS.mkdir(parents=True, exist_ok=True)
    U = setup()
    rec, pkw = STI.reconcile_book()
    out = {"reconcile": rec}
    W9 = dict(G["W9"])
    # numpy score == composite_score; fast picks == picks_w (same names, gross 1e-12)
    s9 = score(W9)
    assert np.array_equal(np.isnan(s9), np.isnan(G["score9"])) and np.nanmax(np.abs(s9 - G["score9"])) < 1e-15
    pk_b = picks_fast(G["score9"])
    tick = U["ticker"].to_numpy()
    assert set(pk_b) == set(pkw)
    for d, (g, cs) in pk_b.items():
        assert abs(g - pkw[d][0]) < 1e-12 and {tick[np.flatnonzero(G["code"] == c)[0]] for c in list(cs)[:3]} <= pkw[d][1]
        assert len(cs) == len(pkw[d][1])
    ch_b = chains(pk_b)
    po_b = G["DD"].per_offset(ch_b)
    assert abs(po_b.mean() - rec["icw9_seas"]["wo31_exact"]) < 1e-10 and abs(po_b.mean() - STI.REF_ICW9) < 1e-6
    base_sd40 = float(np.std(po_b))
    out["base"] = {"mean40": float(po_b.mean()), "sd40": base_sd40, "offsets_pos": int((po_b > 0).sum()),
                   "per_offset": po_b.tolist(),
                   "sub_2011_10_mean40": float(np.mean([c["exc"][c["date"] >= np.datetime64(SUB_LO)].mean() * ANN for c in ch_b]))}
    ident = diff_block(ch_b, chains(picks_fast(score(W9))))
    assert ident["diff"] == 0.0, "identity book diff != 0"
    log(f"base reconcile OK {po_b.mean():+.7f} (ref {STI.REF_ICW9}) sd40 {base_sd40:.5f}")
    G["ch_b"] = ch_b
    if reconcile_only:
        (PARTS / "reconcile.json").write_text(json.dumps(out, indent=1, default=float))
        log(f"reconcile-only: wrote {PARTS / 'reconcile.json'} ({time.time()-T0:.0f}s)")
        return
    (PARTS / "real.json").write_text(json.dumps(out, indent=1, default=float))
    out["factors"] = {}
    for f in FACTORS:
        r = {"weight": W9[f]}
        r["test1_deciles"] = decile_tables(U, f)
        r["test1_ls_decile_volq"] = ls_pooled(f)
        tot = sum(abs(v) for v in W9.values())
        rest = {k: v for k, v in W9.items() if k != f}
        sc = tot / sum(abs(v) for v in rest.values())
        w_loo = {k: v * sc for k, v in rest.items()}
        r["loo"] = diff_block(ch_b, chains(picks_fast(score(w_loo))))
        w_flip = dict(W9); w_flip[f] = -W9[f]
        r["flip"] = diff_block(ch_b, chains(picks_fast(score(w_flip))))
        out["factors"][f] = r
        log(f"{f}: LOO-base {r['loo']['diff']*100:+.4f}%/yr ({r['loo']['diff_offsets_pos']}/40) "
            f"flip-base {r['flip']['diff']*100:+.4f}% ({r['flip']['diff_offsets_pos']}/40) ({time.time()-T0:.0f}s)")
        (PARTS / "real.json").write_text(json.dumps(out, indent=1, default=float))
    out["runtime_s"] = time.time() - T0
    (PARTS / "real.json").write_text(json.dumps(out, indent=1, default=float))


# ------------------------------------------------------------------ null
def null_draw(job):
    f, s = job
    p = NULLD / f"{f}_{s:03d}.json"
    if p.exists():
        return job
    seed = SEED_BASE[f] + s
    U = G["U"]
    v = G["V"].shuffle_within_date(U, f, seed)
    tmp = pd.DataFrame({"date": U["date"], "x": v})
    rz = G["SI"].rank_z(tmp, "x").to_numpy(np.float64)
    ch = chains(picks_fast(score(G["W9"], {f: rz})))
    d = G["DD"].per_offset(ch) - G["DD"].per_offset(G["ch_b"])
    p.write_text(json.dumps({"factor": f, "draw": s, "seed": seed, "diff": float(d.mean()),
                             "offsets_pos": int((d > 0).sum())}))
    return job


def run_null(n, procs):
    import multiprocessing as mp
    NULLD.mkdir(parents=True, exist_ok=True)
    setup()
    G["ch_b"] = chains(picks_fast(G["score9"]))
    assert abs(G["DD"].per_offset(G["ch_b"]).mean() - STI.REF_ICW9) < 1e-6
    todo = [(f, s) for f in FACTORS for s in range(n) if not (NULLD / f"{f}_{s:03d}.json").exists()]
    log(f"null: {len(todo)} draws on {procs} procs")
    with mp.get_context("fork").Pool(procs) as pool:
        for i, j in enumerate(pool.imap_unordered(null_draw, todo)):
            if i % 10 == 0:
                log(f"null {j} done ({i+1}/{len(todo)})")


# ------------------------------------------------------------------ aggregate
def holm(ps):
    o = np.argsort(ps); m = len(ps); adj = np.empty(m); run = 0.0
    for i, k in enumerate(o):
        run = max(run, min(1.0, (m - i) * ps[k])); adj[k] = run
    return adj.tolist()


def aggregate(n):
    from scipy.stats import norm
    real = json.loads((PARTS / "real.json").read_text())
    base_sd = real["base"]["sd40"]
    rep = {"work_order": "WO-48", "prereg": "final/models/2026-10-07-factor-sign-construction.md",
           "era": "2007-01-02..2019-12-31 (rebalance dates); no hold-out read",
           "units": "fractions per year unless noted; decile tables are 40d date-demeaned returns",
           "reconcile": real["reconcile"], "base": {k: v for k, v in real["base"].items() if k != "per_offset"},
           "factors": {}}
    ts = {}
    for f in FACTORS:
        r = real["factors"][f]
        dr = [json.loads((NULLD / f"{f}_{s:03d}.json").read_text()) for s in range(n)]
        nd = np.array([x["diff"] for x in dr])
        p80 = float(np.percentile(nd, 80))
        L = r["loo"]
        bar = max(base_sd, p80)
        c = {"1_loo_gt_max_sd40_p80": bool(L["diff"] > bar), "2_offsets_ge_30": bool(L["diff_offsets_pos"] >= OFF_MIN),
             "3_loyo_min_gt_0": bool(L["loyo_min"] > 0),
             "4_max_year_share_le_045": bool(L["max_year_share"] is not None and L["max_year_share"] <= YEAR_SHARE_MAX)}
        r["null"] = {"n_draws": n, "p50": float(np.percentile(nd, 50)), "p80": p80, "p95": float(np.percentile(nd, 95)),
                     "mean": float(nd.mean()), "sd": float(nd.std()),
                     "pct_of_loo": float((nd < L["diff"]).mean()), "pct_of_flip": float((nd < r["flip"]["diff"]).mean())}
        r["gate"] = {"bar": bar, "base_sd40": base_sd, **c}
        r["verdict"] = "FLAGGED" if all(c.values()) else "CLOSED"
        rep["factors"][f] = r
        ts[f] = (L["jackknife_t"], r["flip"]["jackknife_t"])
    for i, lab in enumerate(("loo", "flip")):
        ps = [2 * norm.sf(abs(ts[f][i])) if ts[f][i] is not None else 1.0 for f in FACTORS]
        for f, p, a in zip(FACTORS, ps, holm(ps)):
            rep["factors"][f][lab]["jackknife_p"] = p
            rep["factors"][f][lab]["jackknife_p_holm3"] = a
    rep["verdicts"] = {f: rep["factors"][f]["verdict"] for f in FACTORS}
    OUT.mkdir(parents=True, exist_ok=True)
    (OUT / "signcheck_report.json").write_text(json.dumps(rep, indent=1, default=float))
    for f in FACTORS:
        r = rep["factors"][f]; L = r["loo"]; F = r["flip"]
        print(f"{f}: LOO-base {L['diff']*100:+.4f}%/yr {L['diff_offsets_pos']}/40 sd40 {L['diff_sd40']*100:.4f} "
              f"LOYO min {L['loyo_min']*100:+.4f} maxshare {L['max_year_share']} | null p80 {r['null']['p80']*100:+.4f} "
              f"| flip {F['diff']*100:+.4f} {F['diff_offsets_pos']}/40 | sub11 LOO {L['sub_2011_10']['diff']*100:+.4f} "
              f"flip {F['sub_2011_10']['diff']*100:+.4f} | {r['verdict']}")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--real", action="store_true")
    ap.add_argument("--null", type=int, default=0)
    ap.add_argument("--procs", type=int, default=4)
    ap.add_argument("--aggregate", type=int, default=0)
    ap.add_argument("--reconcile", action="store_true")
    a = ap.parse_args()
    if a.reconcile:
        run_real(reconcile_only=True)
    if a.real:
        run_real()
    if a.null:
        run_null(a.null, a.procs)
    if a.aggregate:
        aggregate(a.aggregate)


if __name__ == "__main__":
    main()
