"""
WO-61 Part 1, checks 1 and 2 (plan: final/models/2026-10-10-thinbook-audit.md).

    PY=/opt/anaconda3/envs/pipe_dream/bin/python ; caffeinate -i $PY run_level.py

Check 1: WO-6's construction (downcap_v2_readout: per_date_picks / backtest, slow pandas path) reproduces WO-6's
cap150 icw8 and WO-58's thin icw5_seas base; decomposition A..E one variable per step; cap150/cap2000/thin x
icw8/icw5_seas on identical dates; NaN-seas diagnostics.
Check 2: the thin book on the daily 40-offset grid 2008-2018 (fast path, asserted equal to the slow path first).
Research code only; never trades.
"""
from __future__ import annotations

import numpy as np
import pandas as pd

import ta_common as A

B, C, ICW, log = A.B, A.C, A.ICW, A.log
import downcap_v2_readout as R6  # noqa: E402  (WO-6 harness, read-only)


def slow_picks(g, w):
    """WO-6 construction on one date's frame: compute_composite_ic_weighted + pick_decile_volq."""
    g = g.reset_index(drop=True)
    if len(g) < C.N_VOL_QUINTILES * 4:
        return []
    return C.pick_decile_volq(g, ICW.compute_composite_ic_weighted(g, weights=dict(w)))


def recs_from_slow(frame, w):
    recs, picks = {}, {}
    for d, g in frame.groupby("date", sort=True):
        g = g.reset_index(drop=True)
        pk = slow_picks(g, w)
        picks[d] = pk
        ret = dict(zip(g.ticker, g.gross_return_40))
        pk = [(t, x) for t, x in pk if pd.notna(ret.get(t))]
        if not pk:
            continue
        ws = sum(x for _, x in pk)
        recs[d] = (sum((x / ws) * (1.0 + ret[t]) for t, x in pk) - 1.0, {t for t, _ in pk})
    return recs, picks


def recs_fast(blocks, w, seas_neutral=False, keep_fn=None):
    recs, picks = {}, {}
    for dd in blocks:
        keep = None if keep_fn is None else keep_fn(dd)
        idx, wt = A.picks_fast(dd, w, keep, seas_neutral)
        picks[dd["date"]] = (idx, wt)
        r = A.realise(dd, idx, wt)
        if r is not None:
            recs[dd["date"]] = r
    return recs, picks


def lvl2(recs, spy):
    return A.eval_offsets(recs, A.two_off_dates(recs), 2, spy)


def main():
    A.guard_inputs()
    out = {"plan": A.PLAN, "plan_sha": A.PLAN_SHA, "units": "fractions per year, net 15bp minus SPY"}

    # ---------------- step A/B/C: WO-6's own harness, column c
    R6.BOOKS = {"icw8": lambda g: ICW.compute_composite_ic_weighted(g)}
    assert dict(ICW.PRODUCTION_WEIGHTS) == A.W8
    p6, spy6 = R6.load_column("c")
    d6 = sorted(p6.date.unique())
    _, dates133 = B.load_signal(1)
    stepA, pk6 = {}, {}
    for tier in ("cap150", "cap2000"):
        pk6[tier] = R6.per_date_picks(p6, tier)["icw8"]
        stepA[tier] = R6.backtest(pk6[tier], d6, spy6)
        log(f"A {tier} icw8 2007-2019 40-off: {stepA[tier]['excess_cagr_vs_spy_mean40']:+.6f}")
    d0818 = [d for d in d6 if A.ERA[0] <= d <= A.ERA[1]]
    stepB = {t: R6.backtest(pk6[t], d0818, spy6) for t in pk6}
    stepC = {t: lvl2({d: pk6[t][d] for d in dates133 if d in pk6[t]}, spy6) for t in pk6}
    resA = stepA["cap150"]["excess_cagr_vs_spy_mean40"]
    out["check1"] = {"A_wo6_2007_2019_40off": stepA, "B_2008_2018_40off": stepB, "C_133dates_2off": stepC,
                     "A_reproduces_wo6": {"got": resA, "ref": A.WO6_ICW8_CAP150, "abs_err": abs(resA - A.WO6_ICW8_CAP150),
                                          "pass": abs(resA - A.WO6_ICW8_CAP150) <= 1e-6}}
    cap150_sets133 = {d: pk6["cap150"][d][1] for d in dates133 if d in pk6["cap150"]}
    del p6

    # ---------------- WO-58 frame, slow path (steps D on the WO-58 pool, E)
    b, _pool, dates, info = B.load_book(1)
    o = pd.read_parquet(A.OUTCOME_V2, columns=["ticker", "date", "gross_return_40"],
                        filters=[("date", "in", [d.to_pydatetime() for d in dates])])
    o["ticker"] = o.ticker.astype(str); o["date"] = pd.to_datetime(o.date)
    spy = o[o.ticker == "SPY"].set_index("date").gross_return_40
    b = b.merge(o[~o.ticker.isin(["SPY", "USMV"])], on=["date", "ticker"], how="left")
    extra = [c for c in A.ALLF if c not in b.columns]
    if extra:
        px = B.T.read_on_dates(A.PANEL_V2, ["ticker", "date"] + extra, dates)
        px["date"] = pd.to_datetime(px.date); px["ticker"] = px.ticker.astype(str)
        b = b.merge(px, on=["ticker", "date"], how="left")
    b = b.sort_values(["date", "ticker"]).reset_index(drop=True)
    E_recs, E_picks = recs_from_slow(b, A.W5)
    D_recs, D_picks = recs_from_slow(b, A.W8)
    E = lvl2(E_recs, spy); Dw = lvl2(D_recs, spy)
    out["check1"]["E_thin_icw5_seas_wo58pool_slow"] = E
    out["check1"]["D_thin_icw8_wo58pool_slow"] = Dw
    out["check1"]["E_reproduces_wo58"] = {"got": E["mean"], "ref": A.WO58_BASE, "abs_err": abs(E["mean"] - A.WO58_BASE),
                                          "pass": abs(E["mean"] - A.WO58_BASE) <= 1e-6}
    out["check1"]["wo58_load_info"] = info
    log(f"E slow thin icw5_seas: {E['mean']:+.8f} (WO-58 {A.WO58_BASE:+.8f}); D thin icw8 {Dw['mean']:+.6f}")

    # ---------------- my panel frame on the 133 dates; thin via panel flags vs WO-58 pool
    p, spyp = A.load_panel()
    p133 = p[p.date.isin(dates)]
    th = set(zip(p133.date[p133.thin], p133.ticker[p133.thin]))
    wb = set(zip(b.date, b.ticker))
    out["check1"]["thin_flag_agreement_133"] = {"panel_thin": len(th), "wo58_pool": len(wb), "both": len(th & wb),
                                                "jaccard": len(th & wb) / len(th | wb)}
    blk133 = A.prep_dates(p133, spyp)
    # fast == slow on the 133 dates (thin both models, cap150 icw8)
    mism = {}
    for m, w, sp in (("icw5_seas", A.W5, E_picks), ("icw8", A.W8, D_picks)):
        bad = 0
        fb = [x for x in blk133["thin"]]
        for dd in fb:
            idx, wt = A.picks_fast(dd, w)
            slow = dict(sp.get(dd["date"], []))
            fast = dict(zip(dd["tick"][idx].tolist(), wt.tolist()))
            if set(slow) != set(fast) or any(abs(slow[t] - fast[t]) > 1e-12 for t in slow):
                bad += 1
        mism[f"thin_{m}"] = bad
    bad = 0
    for dd in blk133["cap150"]:
        idx, wt = A.picks_fast(dd, A.W8)
        r = A.realise(dd, idx, wt)
        if r is not None and dd["date"] in cap150_sets133 and r[1] != cap150_sets133[dd["date"]]:
            bad += 1
    mism["cap150_icw8_vs_wo6_sets"] = bad
    out["check1"]["fast_vs_slow_dates_mismatched"] = mism
    log(f"fast vs slow mismatched dates: {mism}")
    assert all(v == 0 for v in mism.values()), "fast path != slow path"

    grid133 = {}
    for t in ("cap150", "cap2000", "thin"):
        for m, w in A.MODELS.items():
            grid133[f"{t}_{m}"] = lvl2(recs_fast(blk133[t], w)[0], spyp)
    out["check1"]["grid_133dates_2off"] = grid133
    # NaN seas diagnostics (thin icw5_seas, 133 dates)
    pk_share, pool_share = [], []
    for dd in blk133["thin"]:
        idx, wt = A.picks_fast(dd, A.W5)
        s = dd["F"]["seas"]
        pool_share.append(np.mean(~np.isfinite(s)))
        if len(idx):
            pk_share.append((np.mean(~np.isfinite(s[idx])), float(wt[~np.isfinite(s[idx])].sum())))
    out["check1"]["nan_seas"] = {
        "scoring": "NaN seas is skipped; score = sum(w*rank_z)/sum(|w|) over the 4 present factors",
        "pool_share_nan_seas": float(np.mean(pool_share)),
        "pick_count_share_nan_seas": float(np.mean([a for a, _ in pk_share])),
        "pick_weight_share_nan_seas": float(np.mean([b_ for _, b_ in pk_share])),
        "level_seas_neutral": lvl2(recs_fast(blk133["thin"], A.W5, seas_neutral=True)[0], spyp),
        "level_seas_present_only": lvl2(recs_fast(blk133["thin"], A.W5,
                                                  keep_fn=lambda dd: np.isfinite(dd["F"]["seas"]))[0], spyp)}
    log(f"133 grid: " + ", ".join(f"{k} {v['mean']:+.4f}" for k, v in grid133.items()))
    A.dump("check1_reconcile.json", out)

    # ---------------- check 2: daily 40-offset grid 2008-2018 (fast path)
    blk = A.prep_dates(p, spyp)
    alld = sorted(p.date.unique())
    c2 = {"dates": len(alld), "first": str(alld[0].date()), "last": str(alld[-1].date())}
    for t in ("thin", "cap150", "cap2000"):
        for m, w in A.MODELS.items():
            recs = recs_fast(blk[t], w)[0]
            c2[f"{t}_{m}"] = A.eval_offsets(recs, alld, 40, spyp)
            log(f"40-off {t} {m}: {c2[f'{t}_{m}']['mean']:+.4f} sd {c2[f'{t}_{m}']['sd']:.4f}")
    # seas diagnostics on the daily grid
    c2["thin_icw5_seas_seas_neutral"] = A.eval_offsets(recs_fast(blk["thin"], A.W5, seas_neutral=True)[0], alld, 40, spyp)
    c2["thin_icw5_seas_seas_present_only"] = A.eval_offsets(
        recs_fast(blk["thin"], A.W5, keep_fn=lambda dd: np.isfinite(dd["F"]["seas"]))[0], alld, 40, spyp)
    # equal-weight thin pool, gross, 40 offsets (no costs)
    ew = {}
    for dd in blk["thin"]:
        r = dd["ret"][np.isfinite(dd["ret"])]
        if len(r) and np.isfinite(dd["spy"]):
            ew[dd["date"]] = float(r.mean()) - dd["spy"]
    per = [np.mean([ew[d] for d in alld[o::40] if d in ew]) * A.ANN for o in range(40)]
    c2["ew_thin_pool_gross_minus_spy"] = {"mean": float(np.mean(per)), "sd": float(np.std(per))}
    th = c2["thin_icw5_seas"]
    c2["pass"] = bool(th["n_offsets"] >= 30 and min(th["n_dates_per_offset"]) >= 60)
    c2["within_2pp_of_8.06"] = bool(abs(th["mean"] - A.WO58_BASE) <= 0.02)
    out["check2"] = c2
    A.dump("check2_offsets40.json", c2)
    A.dump("check1_reconcile.json", out)


if __name__ == "__main__":
    main()
