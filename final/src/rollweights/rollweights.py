"""
WO-33 (COO) Step 1, in-era: rolling-window refit of the icw9_seas weights,
walk-forward. Pre-registration: final/models/2026-09-30-rolling-weights.md
(committed before any arm-vs-control statistic is computed).

Weight rule = the live icw9_seas rule, unchanged:
    w_k = sign_k * max(0.1, |t_k| - 1) / sum_j max(0.1, |t_j| - 1)
    (screen_insider.fit_weights with ic_weighted_composite.SIGNS_V9_SEAS)
t_k = NW(39) t of the per-date Spearman IC of factor k vs
forward_return_tradable_40, estimated on the SAME data the live weights came
from: the 8 production factors on composite_panel.parquet (v1) cap150, `seas`
on v2 col c cap150 (WO-18 universe, screen_seas.load_universe). Only the
estimation window changes:
    R252  the 252 most recent matured label dates
    R756  the 756 most recent matured label dates (fewer until available)
    EXP   all matured label dates from panel start (CONTROL)
Matured (Gate A): calendar idx(d) + 41 <= idx(refit date). Refit on
all_dates[0::21] (v2 union calendar); weights held until the next refit.

Evaluation: v2 col c cap150 books (screen_insider_v2grid.Book, decile_volq,
40 offsets, net 15 bp), sub-calendar 2010-01-04..2019-12-31.
Nothing on or after 2020-01-01 is read (asserted on every frame).

Stages (shared modules imported read-only, never edited):
  --stage build   IC series, full-window weight reproduction (hard assert),
                  weight paths + embargo asserts, scorer + book reconcile.
                  No arm-vs-control statistic.
  --stage eval    primary metric + descriptive (run ONLY after the pre-reg
                  commit).
  --stage null --seeds a,b,...   R252 label-shuffle null draws (after eval).
  --stage nullagg aggregate null draws.
"""
import argparse
import json
import pickle
import sys
import time
from pathlib import Path

import numpy as np
import pandas as pd

HERE = Path(__file__).resolve().parent
SRC = HERE.parent
sys.path.insert(0, str(SRC / "construction"))
sys.path.insert(0, str(SRC / "seasonality"))
sys.path.insert(0, str(SRC / "insider"))
sys.path.insert(0, str(SRC / "reset2026"))
import screen_seas as S                 # noqa: E402  (sets V.COL = "seas", V.SIGNS9)
import drag_decomp as DD                # noqa: E402
import composite as C                   # noqa: E402

V, SI, ICW, DR = S.V, S.SI, S.ICW, S.DR

MAIN = Path("/Users/ggraham/pipe_dream/final")
WO18_SEAS_DIR = Path("/Users/ggraham/pipe_dream/.claude/worktrees/agent-a790eb27c4530aa0a/final/out/seasonality")
OUT = HERE.parents[1] / "out" / "rollweights"
IC_PARQ = OUT / "ic_series_real.parquet"
PATH_CSV = OUT / "weight_paths.csv"
BUILD_JSON = OUT / "build_validate.json"
EVAL_JSON = OUT / "rollweights_eval.json"
PICKS_PKL = Path("/tmp/wo33_rollweights_arm_picks.pkl")   # regenerable cache (eval stage), never committed
NULL_DIR = OUT / "null_draws"
NULL_JSON = OUT / "null_r252.json"

HOLDOUT = pd.Timestamp("2020-01-01")
START = pd.Timestamp("2007-01-02")
END = pd.Timestamp("2019-12-31")
EVAL_START = pd.Timestamp("2010-01-04")
LABEL = "forward_return_tradable_40"
EMBARGO = 41                               # idx(d) + 40 + 1 <= idx(t)
REFIT_EVERY = 21
ARMS = {"R252": 252, "R756": 756, "EXP": None}
SIGNS = dict(ICW.SIGNS_V9_SEAS)
FT = list(ICW.PRODUCTION_WEIGHTS_V9_SEAS)  # 9 factors, live order
FC8 = [c for c in FT if c != "seas"]
W_LIVE = dict(ICW.PRODUCTION_WEIGHTS_V9_SEAS)
REF_A_ICW9 = 0.0348710                     # WO-23 REF_A: W9 full precision, 2007-2019
NULL_SEEDS = [3300 + k for k in range(20)]
ANN = 252.0 / 40
log = V.log


def hold(ts, what):
    assert pd.Timestamp(ts) < HOLDOUT, f"HOLD-OUT BREACH ({what}): {ts}"


# ------------------------------------------------------------------ data
# The live 8-factor t's (ic_weighted_composite_report.json, 2026-09-22) are NOT
# reproducible from today's composite_panel.parquet (rewritten 2026-09-30 10:46;
# e.g. momentum t 1.533 vs stored 1.382). They ARE reproduced exactly by the
# dated, frozen snapshot composite_panel_v2_through_2026-09-08.parquet restricted
# to v1 tickers and eligible_cap150_v1 (= the v1 cap150 frame as of 2026-09-22).
# That snapshot is the fitting frame for the 8 factors in both steps.
FIT_PANEL = MAIN / "out" / "reset2026" / "composite_panel_v2_through_2026-09-08.parquet"
FIT_FLAG = "eligible_cap150_v1"


def _load_fit(hi):
    old_t = set(pd.read_parquet(MAIN / "out" / "reset2026" / "composite_panel.parquet",
                                columns=["ticker"])["ticker"].astype(str).unique())
    need = list(dict.fromkeys(["ticker", "date", FIT_FLAG, LABEL] + FC8))
    p = pd.read_parquet(FIT_PANEL, columns=need,
                        filters=[("date", ">=", "2007-01-02"), ("date", "<=", hi.date().isoformat())])
    p["date"] = pd.to_datetime(p["date"]); p["ticker"] = p["ticker"].astype(str)
    p = p[(p["date"] >= START) & (p["date"] <= hi) & p[FIT_FLAG].astype(bool) & p["ticker"].isin(old_t)]
    return p.drop(columns=[FIT_FLAG]).sort_values(["date", "ticker"]).reset_index(drop=True)


def load_v1():
    """v1 cap150 nomination-era fitting frame (see FIT_PANEL note)."""
    p = _load_fit(END)
    hold(p["date"].max(), "v1 fit frame")
    return p


def load_v2():
    """screen_seas.load_universe on the WO-18 seas file (== WO-23 period A)."""
    S.B.OUT = WO18_SEAS_DIR
    U, all_dates, spy = S.load_universe()
    hold(U["date"].max(), "v2 universe"); hold(max(all_dates), "calendar"); hold(spy.index.max(), "spy")
    all_dates = [pd.Timestamp(d) for d in all_dates]
    return U, all_dates, spy


def ic_series(v1, U, v1_label=None, v2_label=None):
    """Per-date Spearman IC per factor (SI.daily_corr, min 20 names).
    Optional label arrays replace LABEL (null draws)."""
    a = v1 if v1_label is None else v1.assign(**{LABEL: v1_label})
    b = U if v2_label is None else U.assign(**{LABEL: v2_label})
    cols = {c: SI.daily_corr(a[["date", c, LABEL]], c, LABEL) for c in FC8}
    cols["seas"] = SI.daily_corr(b[["date", "seas", LABEL]], "seas", LABEL)
    ic = pd.DataFrame(cols).sort_index()
    hold(ic.index.max(), "ic series")
    return ic[FT]


# ------------------------------------------------------------------ weights
def refit_indices(all_dates):
    return list(range(0, len(all_dates), REFIT_EVERY))


def window_t(ic, idx_of, i, W):
    """t per factor on matured IC dates in the arm's window; asserts Gate A."""
    di = idx_of                                # ndarray: calendar idx of each ic row
    hi = i - EMBARGO
    lo = 0 if W is None else hi - W + 1
    m = (di >= lo) & (di <= hi)
    ts, n = {}, {}
    for c in FT:
        x = ic[c].to_numpy()[m]
        x = x[np.isfinite(x)]
        ts[c] = SI.newey_west_mean_t(x)["t"]
        n[c] = int(len(x))
    used = di[m]
    if len(used):
        assert used.max() + EMBARGO <= i, "GATE A: immature label used"
    return ts, n, (int(used.min()) if len(used) else None, int(used.max()) if len(used) else None)


def weight_path(ic, all_dates, W):
    idx_of = np.searchsorted(np.array(all_dates, dtype="datetime64[ns]"), ic.index.values)
    assert (np.array(all_dates, dtype="datetime64[ns]")[idx_of] == ic.index.values).all(), "IC date off calendar"
    rows = []
    for i in refit_indices(all_dates):
        ts, n, (lo, hi) = window_t(ic, idx_of, i, W)
        w = SI.fit_weights(ts, SIGNS)
        r = {"refit_date": all_dates[i], "refit_idx": i,
             "first_used": all_dates[lo] if lo is not None else pd.NaT,
             "last_used": all_dates[hi] if hi is not None else pd.NaT,
             "n_min": min(n.values()), "n_seas": n["seas"], "n_mom": n["momentum_12_1"]}
        if hi is not None:
            assert hi + EMBARGO <= i
            hold(all_dates[hi], "fit window")
        r.update({f"w_{c}": w[c] for c in FT}); r.update({f"t_{c}": ts[c] for c in FT})
        rows.append(r)
    return pd.DataFrame(rows)


def score_path(U, path):
    """SI.composite_score with per-date weights: each row uses the last refit
    on or before its date. Same arithmetic/order as SI.composite_score."""
    rd = path["refit_date"].to_numpy(dtype="datetime64[ns]")
    k = np.searchsorted(rd, U["date"].to_numpy(dtype="datetime64[ns]"), side="right") - 1
    assert (k >= 0).all()
    num = pd.Series(0.0, index=U.index); den = pd.Series(0.0, index=U.index)
    cov = pd.Series(0, index=U.index)
    for c in FT:
        w = path[f"w_{c}"].to_numpy()[k]
        rz = U[f"rz_{c}"]
        num += (rz * w).fillna(0.0); den += np.where(rz.notna(), np.abs(w), 0.0); cov += rz.notna()
    out = num / den.replace(0, np.nan)
    return out.where(cov > 0)


def const_path(w, all_dates):
    r = {"refit_date": all_dates[0]}; r.update({f"w_{c}": w[c] for c in FT})
    return pd.DataFrame([r])


def stability(path, eval_start=EVAL_START):
    p = path[path["refit_date"] >= eval_start].reset_index(drop=True)
    W = p[[f"w_{c}" for c in FT]].to_numpy()
    d = np.abs(np.diff(W, axis=0))
    T = p[[f"t_{c}" for c in FT]].to_numpy()
    sg = np.array([SIGNS[c] for c in FT])
    disagree = np.where(np.isfinite(T), np.sign(T) != sg, np.nan)
    return {"n_refits": int(len(p)),
            "mean_L1_change_per_refit": float(d.sum(axis=1).mean()),
            "mean_abs_change_per_factor": {c: float(d[:, j].mean()) for j, c in enumerate(FT)},
            "weight_sign_flip_share": 0.0,
            "weight_sign_flip_note": "signs fixed by the rule (sign_k * magnitude): 0 by construction",
            "t_sign_disagrees_with_fixed_sign_share": {c: (float(np.nanmean(disagree[:, j]))
                                                           if np.isfinite(disagree[:, j]).any() else None)
                                                       for j, c in enumerate(FT)},
            "weight_mean": {c: float(W[:, j].mean()) for j, c in enumerate(FT)},
            "weight_min": {c: float(W[:, j].min()) for j, c in enumerate(FT)},
            "weight_max": {c: float(W[:, j].max()) for j, c in enumerate(FT)}}


# ------------------------------------------------------------------ build
def stage_build():
    T0 = time.time()
    OUT.mkdir(parents=True, exist_ok=True)
    res = {"work_order": "WO-33 step 1", "stage": "build"}
    v1 = load_v1()
    U, all_dates, spy = load_v2()
    log(f"v1 cap150 {len(v1):,} rows {v1['date'].min().date()}..{v1['date'].max().date()}; "
        f"v2 U {len(U):,} rows; calendar {len(all_dates)} {all_dates[0].date()}..{all_dates[-1].date()} ({time.time()-T0:.0f}s)")
    cal = set(all_dates)
    off = sorted(set(v1["date"].unique()) - cal)
    assert not off, f"v1 dates off v2 calendar: {off[:5]}"
    res["calendar"] = {"n": len(all_dates), "first": str(all_dates[0].date()), "last": str(all_dates[-1].date()),
                       "v1_dates_on_calendar": True, "v1_n_dates": int(v1["date"].nunique())}

    ic = ic_series(v1, U)
    ic.to_parquet(IC_PARQ)
    log(f"IC series {ic.shape} saved ({time.time()-T0:.0f}s)")

    # ---- reproduction: full 2007-2019 window, through our own IC path
    t_rep = json.loads(S.ICW_REPORT.read_text())["per_factor_t"]["full"]
    t_full = {c: SI.newey_west_mean_t(ic[c].dropna().to_numpy())["t"] for c in FT}
    t_cmp = {}
    for c in FC8:
        a, b = t_full[c], t_rep[c]["t"]
        ok = (np.isnan(a) and np.isnan(b)) or abs(a - b) < 1e-6
        t_cmp[c] = {"recomputed": a, "stored_icw_report": b, "ok": bool(ok)}
    t_cmp["seas"] = {"recomputed": t_full["seas"], "stored_SEAS_T": ICW.SEAS_T,
                     "ok": bool(abs(t_full["seas"] - ICW.SEAS_T) < 1e-6)}
    w_full = SI.fit_weights(t_full, SIGNS)
    w_cmp = {c: {"recomputed": w_full[c], "rounded": round(w_full[c], 4), "live": W_LIVE[c],
                 "ok": round(w_full[c], 4) == W_LIVE[c]} for c in FT}
    res["reproduction"] = {"t": t_cmp, "weights": w_cmp,
                           "t_all_ok": all(v["ok"] for v in t_cmp.values()),
                           "weights_all_ok": all(v["ok"] for v in w_cmp.values())}
    BUILD_JSON.write_text(json.dumps(res, indent=2, default=str))
    for c in FT:
        log(f"  {c:32s} t {t_full[c]:+.6f}  w {w_full[c]:+.6f} -> {round(w_full[c],4):+.4f} live {W_LIVE[c]:+.4f}")
    assert res["reproduction"]["t_all_ok"], "T REPRODUCTION FAIL: stop"
    assert res["reproduction"]["weights_all_ok"], "WEIGHT REPRODUCTION FAIL: stop"
    log("full-window rule reproduces live icw9_seas weights to 4dp")

    # ---- weight paths (+ Gate A asserted per refit inside window_t / weight_path)
    paths = []
    for arm, W in ARMS.items():
        p = weight_path(ic, all_dates, W); p.insert(0, "arm", arm); paths.append(p)
    P = pd.concat(paths, ignore_index=True)
    hold(P["last_used"].dropna().max(), "paths")
    P.to_csv(PATH_CSV, index=False)
    # EXP at the last refit vs full window (sanity: full window = all 2007-2019 IC dates)
    res["paths"] = {"csv": str(PATH_CSV.relative_to(HERE.parents[2])), "n_refits_per_arm": int((P["arm"] == "EXP").sum()),
                    "refit_every": REFIT_EVERY, "embargo_days": EMBARGO,
                    "gate_a_asserted_on_every_refit": True,
                    "stability_2010_2019": {arm: stability(P[P["arm"] == arm]) for arm in ARMS}}
    ev = P[P["refit_date"] >= EVAL_START]
    res["paths"]["first_eval_refit"] = {arm: {k: str(v) for k, v in ev[ev["arm"] == arm].iloc[0][
        ["refit_date", "first_used", "last_used", "n_min", "n_seas"]].items()} for arm in ARMS}
    r756 = P[P["arm"] == "R756"].reset_index(drop=True); rexp = P[P["arm"] == "EXP"].reset_index(drop=True)
    wc = [f"w_{c}" for c in FT]
    same = (np.abs(r756[wc].to_numpy() - rexp[wc].to_numpy()).max(axis=1) == 0)
    res["paths"]["R756_identical_to_EXP_until"] = str(r756.loc[~same, "refit_date"].min().date())
    log(f"weight paths saved ({time.time()-T0:.0f}s); R756 == EXP until {res['paths']['R756_identical_to_EXP_until']}")
    BUILD_JSON.write_text(json.dumps(res, indent=2, default=str))

    # ---- scorer reconcile (constant weights) + book reconcile (W9 full precision, 2007-2019)
    V.add_ranks(U, FT)
    s_ref = SI.composite_score(U, w_full).to_numpy()
    s_new = score_path(U, const_path(w_full, all_dates)).to_numpy()
    eq = bool(((s_ref == s_new) | (np.isnan(s_ref) & np.isnan(s_new))).all())
    book = V.Book(U, all_dates, spy)
    r = book.run(s_new)
    res["reconcile"] = {"scorer_equals_SI_composite_score": eq,
                        "icw9_full_precision_2007_2019_mean40": r["excess_cagr_vs_spy_mean40"],
                        "ref_WO23_REF_A": REF_A_ICW9,
                        "book_ok": bool(abs(r["excess_cagr_vs_spy_mean40"] - REF_A_ICW9) < 1e-6)}
    log(f"reconcile: scorer eq {eq}; book {r['excess_cagr_vs_spy_mean40']:+.7f} vs {REF_A_ICW9:+.7f}")
    res["runtime_s"] = time.time() - T0
    BUILD_JSON.write_text(json.dumps(res, indent=2, default=str))
    assert eq and res["reconcile"]["book_ok"], "RECONCILE FAIL: stop"
    log(f"wrote {BUILD_JSON}")


# ------------------------------------------------------------------ eval helpers
def per_date(ch):
    s = {}
    for c in ch:
        for d, n in zip(c["date"], c["exc"]):
            assert d not in s
            s[d] = n
    return pd.Series(s).sort_index()


def compare(ch_arm, ch_ctl):
    po = DD.per_offset(ch_arm) - DD.per_offset(ch_ctl)
    a, b = per_date(ch_arm), per_date(ch_ctl)
    assert a.index.equals(b.index), "per-date calendars differ"
    diff = (a - b).to_numpy()
    nwr = SI.newey_west_mean_t(diff)
    years, la = DD.loyo_vec(ch_arm)
    years2, lc = DD.loyo_vec(ch_ctl)
    assert years == years2
    gl = (la - lc).mean(axis=0)
    return {"mean_diff_ann_40offset": float(po.mean()), "offsets_positive": int((po > 0).sum()),
            "offset_diff_min": float(po.min()), "offset_diff_max": float(po.max()),
            "per_date_diff_mean_per40d": nwr["mean"], "per_date_diff_ann": nwr["mean"] * ANN,
            "nw39_t": nwr["t"], "n_dates": nwr["n"],
            "loyo_min": float(gl.min()), "loyo_min_dropped_year": int(years[int(gl.argmin())]),
            "loyo_by_dropped_year": {int(y): float(v) for y, v in zip(years, gl)}}


def verdict(c):
    if c["mean_diff_ann_40offset"] <= 0 or c["loyo_min"] <= 0:
        return "KILL"
    if c["nw39_t"] >= 2.24 and c["offsets_positive"] >= 30:
        return "SUCCESS"
    return "MIDDLE"


def setup_eval():
    U, all_dates, spy = load_v2()
    V.add_ranks(U, FT)
    P = pd.read_csv(PATH_CSV, parse_dates=["refit_date", "first_used", "last_used"])
    hold(P["refit_date"].max(), "paths csv")
    book = V.Book(U, all_dates, spy)
    return U, all_dates, spy, P, book


# ------------------------------------------------------------------ eval
def stage_eval():
    T0 = time.time()
    b = json.loads(BUILD_JSON.read_text())
    assert b["reproduction"]["weights_all_ok"] and b["reconcile"]["book_ok"], "build not validated"
    U, all_dates, spy, P, book = setup_eval()
    scores = {arm: score_path(U, P[P["arm"] == arm].reset_index(drop=True)).to_numpy() for arm in ARMS}
    scores["LIVE_REF"] = SI.composite_score(U, W_LIVE).to_numpy()
    pk = {k: book.picks(v) for k, v in scores.items()}
    pk["noscore"] = DD.noscore_picks(book)
    for k, sd in enumerate(DD.SEEDS):
        pk[f"rand{k}"] = book.picks(V.shuffle_within_date(U.assign(_s=scores["EXP"]), "_s", sd))
    for k, v in pk.items():
        hold(max(v), f"picks {k}")
    with open(PICKS_PKL, "wb") as f:
        pickle.dump(pk, f)
    log(f"picks built ({time.time()-T0:.0f}s)")

    sub = {k: DD.window(v, all_dates, lo=EVAL_START) for k, v in pk.items()}
    ch = {(k, cn): DD.chains(sub[k][0], sub[k][1], spy, cost) for k in pk
          for cn, cost in (("net", DR.COST_BPS), ("gross", 0.0))}
    out = {"work_order": "WO-33 step 1", "prereg": "final/models/2026-09-30-rolling-weights.md",
           "eval_window": f"{EVAL_START.date()}..{END.date()}", "cost_bps": DR.COST_BPS,
           "arms": {k: v for k, v in ARMS.items()}, "control": "EXP"}
    prim = {}
    for arm in ("R252", "R756"):
        c = compare(ch[(arm, "net")], ch[("EXP", "net")])
        c["verdict"] = verdict(c)
        prim[arm] = c
        log(f"{arm} vs EXP: diff {c['mean_diff_ann_40offset']:+.4f}/yr, t {c['nw39_t']:+.2f}, "
            f"offsets+ {c['offsets_positive']}/40, LOYO min {c['loyo_min']:+.4f} -> {c['verdict']}")
    prim["LIVE_REF_vs_EXP_reference_only"] = compare(ch[("LIVE_REF", "net")], ch[("EXP", "net")])
    out["primary"] = prim

    desc = {}
    R = [f"rand{k}" for k in range(len(DD.SEEDS))]
    ns = DR.backtest(*sub["noscore"], spy)["excess_cagr_vs_spy_mean40"]
    rnd = float(np.mean([DD.per_offset(ch[(r, "net")]).mean() for r in R]))
    for arm in list(ARMS) + ["LIVE_REF"]:
        bt = DR.backtest(*sub[arm], spy)
        net = DD.per_offset(ch[(arm, "net")]).mean(); gross = DD.per_offset(ch[(arm, "gross")]).mean()
        assert abs(net - bt["excess_cagr_vs_spy_mean40"]) < 1e-12
        fnew = float(np.mean(np.concatenate([c["f_new"] for c in ch[(arm, "net")]])))
        desc[arm] = {"book_vs_spy": bt, "gross_vs_spy_mean40": float(gross),
                     "cost_drag_ann": float(gross - net), "mean_f_new": fnew,
                     "picks_over_pool_noscore": float(net - ns), "selection_over_random": float(net - rnd),
                     "per_year": DD.per_year(ch[(arm, "net")])}
    desc["pool_noscore_vs_spy"] = ns
    desc["random_mean_vs_spy"] = rnd
    out["descriptive"] = desc
    out["stability"] = b["paths"]["stability_2010_2019"]
    out["runtime_s"] = time.time() - T0
    EVAL_JSON.write_text(json.dumps(out, indent=2, default=float))
    log(f"wrote {EVAL_JSON} ({out['runtime_s']:.0f}s)")


# ------------------------------------------------------------------ null
def stage_null(seeds):
    T0 = time.time()
    NULL_DIR.mkdir(parents=True, exist_ok=True)
    v1 = load_v1()
    U, all_dates, spy, P, book = setup_eval()
    with open(PICKS_PKL, "rb") as f:
        pk = pickle.load(f)
    ctl = DD.chains(*DD.window(pk["EXP"], all_dates, lo=EVAL_START), spy, DR.COST_BPS)
    for sd in seeds:
        fn = NULL_DIR / f"draw_{sd}.json"
        if fn.exists():
            continue
        # shuffle LABEL within date in each fitting frame (one permutation per frame,
        # shared by every factor in it); gross_return_40 (book return) is never touched
        l1 = V.shuffle_within_date(v1, LABEL, sd)
        l2 = V.shuffle_within_date(U, LABEL, sd + 100000)
        ic = ic_series(v1, U, l1, l2)
        path = weight_path(ic, all_dates, ARMS["R252"])
        s = score_path(U, path).to_numpy()
        pkn = book.picks(s)
        hold(max(pkn), "null picks")
        chn = DD.chains(*DD.window(pkn, all_dates, lo=EVAL_START), spy, DR.COST_BPS)
        c = compare(chn, ctl)
        c["book_vs_spy_mean40"] = float(DD.per_offset(chn).mean())
        c["stability"] = stability(path)
        c.pop("loyo_by_dropped_year")
        fn.write_text(json.dumps({"seed": sd, **c}, indent=2, default=float))
        log(f"null seed {sd}: diff {c['mean_diff_ann_40offset']:+.4f} t {c['nw39_t']:+.2f} ({time.time()-T0:.0f}s)")


def stage_nullagg():
    d = [json.loads(p.read_text()) for p in sorted(NULL_DIR.glob("draw_*.json"))]
    ev = json.loads(EVAL_JSON.read_text())
    real = ev["primary"]["R252"]
    diffs = np.array([x["mean_diff_ann_40offset"] for x in d]); ts = np.array([x["nw39_t"] for x in d])
    out = {"n_draws": len(d), "seeds": [x["seed"] for x in d],
           "diff_mean": float(diffs.mean()), "diff_sd": float(diffs.std()), "diff_min": float(diffs.min()),
           "diff_max": float(diffs.max()), "diff_p80": float(np.quantile(diffs, 0.8)),
           "t_mean": float(ts.mean()), "t_min": float(ts.min()), "t_max": float(ts.max()),
           "book_vs_spy_mean": float(np.mean([x["book_vs_spy_mean40"] for x in d])),
           "mean_L1_change_per_refit_mean": float(np.mean([x["stability"]["mean_L1_change_per_refit"] for x in d])),
           "real_R252_diff": real["mean_diff_ann_40offset"],
           "real_R252_rank_share_null_below": float((diffs < real["mean_diff_ann_40offset"]).mean()),
           "draws": d}
    NULL_JSON.write_text(json.dumps(out, indent=2, default=float))
    log(f"null: diff mean {out['diff_mean']:+.4f} sd {out['diff_sd']:.4f}; real R252 {real['mean_diff_ann_40offset']:+.4f} "
        f"above {out['real_R252_rank_share_null_below']:.0%} of draws")


# ================================================================== STEP 2
# Gabe 2026-09-30 ("wo-33 is also a go"): walk-forward continued through
# 2020-01-02..2026-07-30 (last matured 40d label, = WO-23 period B).
# Hold-out read #13, FITTING on 2020+. The <2020 assert is lifted ONLY on
# these code paths (hold2); every Step-1 function above keeps hold().
B_START = pd.Timestamp("2020-01-02")
B_END = pd.Timestamp("2026-07-30")
SEAS_EXT = Path("/Users/ggraham/pipe_dream/.claude/worktrees/wo23-model-audit/final/out/audit/seas_factor_ext.parquet")
REF_B_LIVE = -0.02016365566661011          # WO-23 model_audit_wo23_B.json theoretical.icw9_seas
IC2_PARQ = OUT / "ic_series_step2.parquet"
PATH2_CSV = OUT / "weight_paths_step2.csv"
BUILD2_JSON = OUT / "build_validate_step2.json"
EVAL2_JSON = OUT / "rollweights_eval_step2.json"


def hold2(ts, what):
    assert pd.Timestamp(ts) <= B_END, f"STEP-2 BOUND BREACH ({what}): {ts}"


def load_v1_ext():
    p = _load_fit(B_END)
    hold2(p["date"].max(), "v1 fit frame ext")
    return p


def load_B():
    """model_audit_wo23.load_theo('B', 'cap150') with its SEAS_EXT path."""
    lo, hi = B_START, B_END
    cols = list(dict.fromkeys(["ticker", "date", LABEL, "sector", "eligible_cap150", "asset_growth"] + C.FACTOR_COLS))
    old_t = set(pd.read_parquet(DR.R26 / "composite_panel.parquet", columns=["ticker"])["ticker"].astype(str).unique())
    f = [("date", ">=", lo.date().isoformat()), ("date", "<=", hi.date().isoformat())]
    p = pd.read_parquet(DR.R26 / "composite_panel_v2.parquet", columns=cols, filters=f)
    p["date"] = pd.to_datetime(p["date"]); p["ticker"] = p["ticker"].astype(str)
    tm = pd.read_csv(DR.SH / "tickers_master.csv", dtype=str, usecols=["ticker", "sicindustry"]).drop_duplicates("ticker")
    spac = set(tm.loc[tm["sicindustry"].fillna("").str.contains("Blank Check"), "ticker"])
    p = p[p["ticker"].isin(old_t) | ~p["ticker"].isin(spac)]
    p = p[(p["date"] >= lo) & (p["date"] <= hi)]
    oc = pd.read_parquet(DR.R26 / "outcome_cache_v2.parquet", columns=["ticker", "date", "gross_return_40"],
                         filters=[("date", ">=", lo), ("date", "<=", hi)])
    oc["date"] = pd.to_datetime(oc["date"]); oc["ticker"] = oc["ticker"].astype(str)
    spy = oc[oc["ticker"] == "SPY"].set_index("date")["gross_return_40"]
    all_dates = sorted(p["date"].unique())
    p = p[p["eligible_cap150"].astype(bool)].drop(columns=["eligible_cap150"])
    n = len(p)
    p = p.merge(oc[~oc["ticker"].isin(["SPY", "USMV"])], on=["ticker", "date"], how="left")
    fac = pd.read_parquet(SEAS_EXT, columns=["ticker", "date", "seas"], filters=[("date", ">=", lo), ("date", "<=", hi)])
    fac["date"] = pd.to_datetime(fac["date"]); fac["ticker"] = fac["ticker"].astype(str)
    p = p.merge(fac, on=["ticker", "date"], how="left")
    assert len(p) == n, "merge changed row count"
    hold2(p["date"].max(), "B universe"); hold2(spy.index.max(), "B spy")
    U = p.sort_values(["date", "ticker"]).reset_index(drop=True)
    return U, [pd.Timestamp(d) for d in all_dates], spy


def ic_series2(v1x, UA, UB):
    cols = {c: SI.daily_corr(v1x[["date", c, LABEL]], c, LABEL) for c in FC8}
    seasf = pd.concat([UA[["date", "seas", LABEL]], UB[["date", "seas", LABEL]]], ignore_index=True)
    cols["seas"] = SI.daily_corr(seasf, "seas", LABEL)
    ic = pd.DataFrame(cols).sort_index()
    hold2(ic.index.max(), "ic2")
    return ic[FT]


def weight_path2(ic, cal, W):
    """weight_path on the combined calendar, with hold2 instead of hold."""
    c64 = np.array(cal, dtype="datetime64[ns]")
    idx_of = np.searchsorted(c64, ic.index.values)
    assert (c64[idx_of] == ic.index.values).all(), "IC date off calendar"
    rows = []
    for i in refit_indices(cal):
        ts, n, (lo, hi) = window_t(ic, idx_of, i, W)
        w = SI.fit_weights(ts, SIGNS)
        r = {"refit_date": cal[i], "refit_idx": i,
             "first_used": cal[lo] if lo is not None else pd.NaT,
             "last_used": cal[hi] if hi is not None else pd.NaT,
             "n_min": min(n.values()), "n_seas": n["seas"], "n_mom": n["momentum_12_1"]}
        if hi is not None:
            assert hi + EMBARGO <= i
            hold2(cal[hi], "fit window")
        r.update({f"w_{c}": w[c] for c in FT}); r.update({f"t_{c}": ts[c] for c in FT})
        rows.append(r)
    return pd.DataFrame(rows)


def stage_build2():
    """Step-2 validation: no arm-vs-control statistic."""
    T0 = time.time()
    res = {"work_order": "WO-33 step 2", "stage": "build2", "holdout_read": 13, "window": f"{B_START.date()}..{B_END.date()}"}
    v1x = load_v1_ext()
    UA, cal_A, _ = load_v2()
    UB, cal_B, spyB = load_B()
    assert cal_A[-1] < cal_B[0]
    cal = cal_A + cal_B
    off = sorted(set(v1x["date"].unique()) - set(cal))
    assert not off, f"v1 dates off combined calendar: {off[:5]}"
    ic = ic_series2(v1x, UA, UB)
    ic.to_parquet(IC2_PARQ)
    ic1 = pd.read_parquet(IC_PARQ)
    a = ic.loc[ic.index < HOLDOUT, FT]
    assert a.index.equals(ic1.index), "pre-2020 IC dates differ from Step 1"
    d = np.nanmax(np.abs(a.to_numpy() - ic1[FT].to_numpy()))
    res["pre2020_ic_equal_step1_maxabs"] = float(d if np.isfinite(d) else 0.0)
    assert res["pre2020_ic_equal_step1_maxabs"] < 1e-12
    paths = []
    for arm, W in ARMS.items():
        p = weight_path2(ic, cal, W); p.insert(0, "arm", arm); paths.append(p)
    P = pd.concat(paths, ignore_index=True)
    P.to_csv(PATH2_CSV, index=False)
    # exact (in-memory; the CSV round-trip is not bit-exact) continuation of Step-1 paths
    wc = [f"w_{c}" for c in FT]
    for arm, W in ARMS.items():
        p1 = weight_path(ic1[FT], cal_A, W)
        pa = P[(P["arm"] == arm) & (P["refit_date"] < HOLDOUT)].reset_index(drop=True)
        assert len(pa) == len(p1) and (pa["refit_date"].values == p1["refit_date"].values).all()
        assert (pa[wc].to_numpy() == p1[wc].to_numpy()).all(), f"Step-2 path does not continue Step-1 ({arm})"
    P1 = pd.read_csv(PATH_CSV, parse_dates=["refit_date"])
    pre = P[P["refit_date"] < HOLDOUT].reset_index(drop=True)
    res["csv_roundtrip_maxabs_vs_step1_csv"] = float(np.abs(pre[wc].to_numpy() - P1[wc].to_numpy()).max())
    res["paths_pre2020_identical_to_step1"] = True
    res["stability_2020_2026"] = {arm: stability(P[P["arm"] == arm], B_START) for arm in ARMS}
    res["short_interest_note"] = ("short_interest_days_to_cover has no v1 data before 2020, so its t is NaN "
                                  "(floor weight) until its matured IC dates reach n>=10 in the window")
    # frozen live reconcile on B (WO-23 period B, tol 1e-6)
    V.add_ranks(UB, FT)
    bookB = V.Book(UB, cal_B, spyB)
    rB = bookB.run(SI.composite_score(UB, W_LIVE).to_numpy())["excess_cagr_vs_spy_mean40"]
    res["reconcile_B_live"] = {"mean40": rB, "ref_wo23_B": REF_B_LIVE, "ok": bool(abs(rB - REF_B_LIVE) < 1e-6)}
    res["runtime_s"] = time.time() - T0
    BUILD2_JSON.write_text(json.dumps(res, indent=2, default=str))
    log(f"step2 build: live B {rB:+.7f} vs {REF_B_LIVE:+.7f}; wrote {BUILD2_JSON} ({res['runtime_s']:.0f}s)")
    assert res["reconcile_B_live"]["ok"], "STEP-2 RECONCILE FAIL"


def stage_eval2():
    T0 = time.time()
    b = json.loads(BUILD2_JSON.read_text())
    assert b["reconcile_B_live"]["ok"] and b["paths_pre2020_identical_to_step1"]
    UB, cal_B, spyB = load_B()
    V.add_ranks(UB, FT)
    P = pd.read_csv(PATH2_CSV, parse_dates=["refit_date", "first_used", "last_used"])
    hold2(P["refit_date"].max(), "paths2")
    book = V.Book(UB, cal_B, spyB)
    scores = {arm: score_path(UB, P[P["arm"] == arm].reset_index(drop=True)).to_numpy() for arm in ARMS}
    scores["LIVE_REF"] = SI.composite_score(UB, W_LIVE).to_numpy()
    pk = {k: book.picks(v) for k, v in scores.items()}
    for k, v in pk.items():
        hold2(max(v), f"picks2 {k}")
    ch = {(k, cn): DD.chains(pk[k], cal_B, spyB, cost) for k in pk
          for cn, cost in (("net", DR.COST_BPS), ("gross", 0.0))}
    s1 = json.loads(EVAL_JSON.read_text())["primary"]
    out = {"work_order": "WO-33 step 2", "holdout_read": 13, "window": f"{B_START.date()}..{B_END.date()}",
           "cost_bps": DR.COST_BPS, "control": "EXP", "primary": {}, "descriptive": {}}
    for arm in ("R252", "R756"):
        c = compare(ch[(arm, "net")], ch[("EXP", "net")])
        c["step2_pass"] = bool(c["mean_diff_ann_40offset"] > 0 and c["offsets_positive"] >= 30
                               and c["loyo_by_dropped_year"].get(2020, -1) > 0)
        c["step1_verdict"] = s1[arm]["verdict"]
        c["promote_candidate"] = bool(c["step1_verdict"] == "SUCCESS" and c["step2_pass"])
        out["primary"][arm] = c
        log(f"[B] {arm} vs EXP: diff {c['mean_diff_ann_40offset']:+.4f}/yr t {c['nw39_t']:+.2f} "
            f"offsets+ {c['offsets_positive']}/40 drop2020 {c['loyo_by_dropped_year'].get(2020, float('nan')):+.4f} "
            f"-> step2_pass {c['step2_pass']} promote {c['promote_candidate']}")
    out["primary"]["LIVE_REF_vs_EXP_reference_only"] = compare(ch[("LIVE_REF", "net")], ch[("EXP", "net")])
    for arm in list(ARMS) + ["LIVE_REF"]:
        bt = DR.backtest(pk[arm], cal_B, spyB)
        net = DD.per_offset(ch[(arm, "net")]).mean(); gross = DD.per_offset(ch[(arm, "gross")]).mean()
        assert abs(net - bt["excess_cagr_vs_spy_mean40"]) < 1e-12
        out["descriptive"][arm] = {"book_vs_spy": bt, "gross_vs_spy_mean40": float(gross),
                                   "cost_drag_ann": float(gross - net),
                                   "mean_f_new": float(np.mean(np.concatenate([c["f_new"] for c in ch[(arm, "net")]]))),
                                   "per_year": DD.per_year(ch[(arm, "net")])}
    out["descriptive"]["live_ref_wo23_B"] = REF_B_LIVE
    out["stability"] = b["stability_2020_2026"]
    out["runtime_s"] = time.time() - T0
    EVAL2_JSON.write_text(json.dumps(out, indent=2, default=float))
    log(f"wrote {EVAL2_JSON} ({out['runtime_s']:.0f}s)")


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--stage", required=True, choices=["build", "eval", "null", "nullagg", "build2", "eval2"])
    ap.add_argument("--seeds", default=",".join(map(str, NULL_SEEDS)))
    a = ap.parse_args()
    if a.stage == "build":
        stage_build()
    elif a.stage == "eval":
        stage_eval()
    elif a.stage == "null":
        stage_null([int(x) for x in a.seeds.split(",")])
    elif a.stage == "nullagg":
        stage_nullagg()
    elif a.stage == "build2":
        stage_build2()
    else:
        stage_eval2()
