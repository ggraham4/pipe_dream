"""
WO-28 pre-registered nomination screens, v2 grid column c, cap150, h = 40,
forward_return_tradable_40, nomination era 2007-01-02..2019-12-31.
Registration: models/2026-09-29-volshock-strlowturn-screen.md (committed before any outcome read).

  28a vol_shock    volume family trial 2 (Amihud = 1), sign +1, bar |t| >= 2.24
  28b str_lowturn  reversal family trial 2 (momentum_1_1 = 1), sign -1, bar |t| >= 2.24
Each trial is scored on its own. Base book = icw9_seas (LIVE Theoretical: 8
production factors + seas), not icw8.

Harness: insider/screen_insider_v2grid.py (V) imported as a module for Book,
reconcile, add_ranks, fit_t, oos_score, shuffle_within_date; its main()/gate6/
ic_gates are NOT used, because WO-28 retargets the gates (sign-aware, contiguous
halves, book-increment offsets, icw9_seas base). The retargeted gate function is
proven against V.ic_gates on seas (sign +1, odd/even) before any candidate number.

Modes
  --validate        checks only, NO candidate-vs-return statistic
                    -> out/volshock/validate_volshock.json
  --trial NAME      the registered screen for one trial
                    -> out/volshock/<NAME>_screen_report.json
Usage: python screen_volshock.py --validate | --trial vol_shock|str_lowturn [--null-draws 20]
"""
import argparse
import hashlib
import json
import sys
import time
from pathlib import Path

import numpy as np
import pandas as pd

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
sys.path.insert(0, str(HERE.parent / "insider"))
sys.path.insert(0, str(HERE.parent / "reset2026"))
import build_volshock as B             # noqa: E402
import screen_insider_v2grid as V      # noqa: E402
import screen_insider as SI            # noqa: E402
import downcap_v2_readout as DR        # noqa: E402
import run_backtest as RB              # noqa: E402
import ic_weighted_composite as ICW    # noqa: E402

V.OUT_JSON = B.OUT / "_never_written.json"      # never let the harness write under MAIN
log = V.log
HOLDOUT = pd.Timestamp("2020-01-01")
LABEL = V.LABEL
ICW_REPORT = B.MAIN / "out" / "reset2026" / "ic_weighted_composite_report.json"
SEAS_PQ = Path("/Users/ggraham/pipe_dream/.claude/worktrees/agent-a790eb27c4530aa0a/final/out/seasonality/seas_factor_v2.parquet")
SEAS_SHA = "8054af212270efbf0bffd8fc98a586083529c5dfb5879b669984172b60a38e45"
IO_PQ = Path("/Users/ggraham/pipe_dream/.claude/worktrees/overnight-intraday/final/out/overnight/io_gap_factor_v2.parquet")
IO_T_REF = 3.9953088782434265          # io_gap_screen_report.json ic.pooled.t (committed)
REF_ICW9_SEAS_4DP = 0.03486520057904396 # WO-23 model_audit_wo23_A.json theoretical.icw9_seas (frozen 4dp weights)
VAL_JSON = B.OUT / "validate_volshock.json"
GATE_A_JSON = B.OUT / "gate_a_volshock.json"

FC8 = V.FC8
SIGNS8 = V.SIGNS8
FC9 = FC8 + ["seas"]
SIGNS9S = {**SIGNS8, "seas": +1}
T_BAR = 2.24
SECTOR_T_BAR = 1.0
YEAR_SHARE_MAX = 0.45
HALF_SPLIT_YEAR = 2014          # gate 2 halves: 2007-2013 | 2014-2019
TRIALS = {"vol_shock": {"sign": +1, "family": "volume-based", "k": 2, "prior": "Amihud illiquidity (null)"},
          "str_lowturn": {"sign": -1, "family": "short-term reversal", "k": 2, "prior": "momentum_1_1 (t -0.39)"}}


# ------------------------------------------------------------------ data
def sha256_slice(U):
    h = hashlib.sha256()
    cols = ["ticker", "date", LABEL] + FC8 + ["eligible_cap150_row"]
    X = U[["ticker", "date", LABEL] + FC8].copy()
    X["eligible_cap150_row"] = True
    h.update(pd.util.hash_pandas_object(X[cols], index=False).to_numpy().tobytes())
    return h.hexdigest()


def load_universe():
    p, spy = DR.load_column("c")
    all_dates = sorted(p["date"].unique())
    p = p[p["eligible_cap150"]].drop(columns=["eligible_cap500", "eligible_cap2000"])
    filt = [("date", ">=", "2007-01-02"), ("date", "<=", "2019-12-31")]
    sec = pd.read_parquet(DR.R26 / "composite_panel_v2.parquet", columns=["ticker", "date", "sector"], filters=filt)
    sec["date"] = pd.to_datetime(sec["date"]); sec["ticker"] = sec["ticker"].astype(str); B.guard(sec, "sector")
    def rd(path, cols):
        import pyarrow.parquet as pq
        is_ts = str(pq.read_schema(path).field("date").type).startswith("timestamp")
        f = filt if not is_ts else [("date", ">=", pd.Timestamp("2007-01-02")), ("date", "<=", pd.Timestamp("2019-12-31"))]
        return pd.read_parquet(path, columns=cols, filters=f)
    seas = rd(SEAS_PQ, ["ticker", "date", "seas"])
    io = rd(IO_PQ, ["ticker", "date", "io_gap"])
    fac = rd(B.FACT, ["ticker", "date", "vol_shock", "r_1m", "turnover_21", "r_5d", "r_21d"])
    for f, nm in ((seas, "seas"), (io, "io_gap"), (fac, "volshock inputs")):
        f["date"] = pd.to_datetime(f["date"]); f["ticker"] = f["ticker"].astype(str); B.guard(f, nm)
    n = len(p)
    p = (p.merge(sec, on=["ticker", "date"], how="left").merge(seas, on=["ticker", "date"], how="left")
          .merge(io, on=["ticker", "date"], how="left").merge(fac, on=["ticker", "date"], how="left"))
    assert len(p) == n, "merge changed row count"
    B.guard(p, "universe")
    assert spy.index.max() < HOLDOUT, "HOLD-OUT BREACH spy"
    old_t = set(pd.read_parquet(DR.R26 / "composite_panel.parquet", columns=["ticker"])["ticker"].astype(str).unique())
    p["added"] = ~p["ticker"].isin(old_t)
    U = p.sort_values(["date", "ticker"]).reset_index(drop=True)
    U["str_lowturn"], U["str_eligible"] = str_lowturn_rank(U)
    return U, all_dates, spy


def str_lowturn_rank(U):
    """28b: valid = finite turnover_21 and r_1m. Eligible = turnover_21 strictly below the
    date's median over valid cap150 rows. Value = rank_z of r_1m among eligible rows of the
    date (range -0.5..+0.5); valid non-eligible rows = exactly 0.0 (neutral mid-rank);
    invalid rows = NaN. This column IS the signed-rank input to the composite (not re-ranked)."""
    valid = U["turnover_21"].notna() & U["r_1m"].notna() & np.isfinite(U["turnover_21"]) & np.isfinite(U["r_1m"])
    med = U["turnover_21"].where(valid).groupby(U["date"]).transform("median")
    elig = valid & (U["turnover_21"] < med)
    tmp = pd.DataFrame({"date": U["date"], "x": U["r_1m"].where(elig)})
    rz = SI.rank_z(tmp, "x")
    out = pd.Series(np.nan, index=U.index)
    out[valid] = 0.0
    out[elig] = rz[elig]
    return out, elig


def cand_rz(U, name, values):
    """rank_z input to the composite for the candidate column."""
    if name == "str_lowturn":
        return pd.Series(values, index=U.index)
    tmp = pd.DataFrame({"date": U["date"], "x": values})
    return SI.rank_z(tmp, "x")


# ------------------------------------------------------------------ gates 1-5 (sign-aware)
def ic_gates(U, xcol, sign, halves="calendar"):
    s = SI.daily_corr(U, xcol, LABEL)
    yrs = s.index.year
    r = {"pooled": {**V.nw(s.to_numpy()), "n_dates": int(len(s))}}
    r["h1_2007_2013"] = V.nw(s[yrs < HALF_SPLIT_YEAR].to_numpy())
    r["h2_2014_2019"] = V.nw(s[yrs >= HALF_SPLIT_YEAR].to_numpy())
    r["odd"] = V.nw(s[yrs % 2 == 1].to_numpy()); r["even"] = V.nw(s[yrs % 2 == 0].to_numpy())
    sec = U["sector"].fillna("Unknown")
    key = [U["date"], sec]
    W = U[["date"]].copy()
    W["x_sn"] = U[xcol] - U.groupby(key)[xcol].transform("mean")
    lab = U[LABEL].where(U[xcol].notna())
    W["y_sn"] = lab - lab.groupby(key).transform("mean")
    W[LABEL] = U[LABEL]
    r["sector_both_sides"] = V.nw(SI.daily_corr(W, "x_sn", "y_sn").to_numpy())
    r["sector_factor_only"] = V.nw(SI.daily_corr(W, "x_sn", LABEL).to_numpy())
    offs = [float(s.iloc[o::SI.HORIZON].mean()) for o in range(SI.HORIZON)]
    r["ic_offsets_DESCRIPTIVE"] = {"means": offs, "sign_flips_vs_registered_sign": int(sum(np.sign(m) != sign for m in offs))}
    tot = float(s.sum())
    by_year = s.groupby(yrs).sum()
    shares = {int(y): float(v / tot) for y, v in by_year.items()} if tot != 0 else {}
    r["year_share"] = {"total_sum_ic": tot, "shares": shares,
                       "max_share": max(shares.values()) if shares else np.nan,
                       "max_year": max(shares, key=shares.get) if shares else None}
    r["loyo_t"] = {int(y): V.nw(s[yrs != y].to_numpy())["t"] for y in sorted(set(yrs))}
    if halves == "calendar":
        h_ok = sign * r["h1_2007_2013"]["mean"] > 0 and sign * r["h2_2014_2019"]["mean"] > 0
    else:
        h_ok = sign * r["odd"]["mean"] > 0 and sign * r["even"]["mean"] > 0
    g = {"g1_pooled_t": bool(sign * r["pooled"]["t"] >= T_BAR),
         "g2_both_halves_right_sign": bool(h_ok),
         "g3_sector_both_sides_t": bool(sign * r["sector_both_sides"]["t"] >= SECTOR_T_BAR),
         "g5_year_share": bool(sign * tot > 0 and r["year_share"]["max_share"] <= YEAR_SHARE_MAX)}
    return r, g


# ------------------------------------------------------------------ books
def backtest_offsets(picks_by_date, all_dates, spy):
    """DR.backtest with the per-offset series returned (same arithmetic)."""
    ann = 252.0 / RB.HORIZON
    per_off = []
    for off in range(40):
        prev, recs = set(), []
        for tp in all_dates[off::RB.HORIZON]:
            if tp not in picks_by_date:
                continue
            gross, cur = picks_by_date[tp]
            f_new = sum(1 for t in cur if t not in prev) / len(cur)
            prev = cur
            recs.append({"date": tp, "gross": gross, "f_new": f_new, "spy": spy.get(tp, np.nan)})
        net = RB.turnover_net_return(recs, DR.COST_BPS)
        s = np.array([r["spy"] for r in recs], dtype=np.float64)
        ok = np.isfinite(s)
        per_off.append(float((net[ok] - s[ok]).mean() * ann))
    return {"excess_cagr_vs_spy_mean40": float(np.mean(per_off)), "per_offset": per_off}


def run_book(book, score):
    pk = book.picks(np.asarray(score, dtype=np.float64))
    full = DR.backtest(pk, book.all_dates, book.spy)
    off = backtest_offsets(pk, book.all_dates, book.spy)
    assert abs(off["excess_cagr_vs_spy_mean40"] - full["excess_cagr_vs_spy_mean40"]) < 1e-12
    full["per_offset"] = off["per_offset"]
    return full


def base_fit(U, cols, signs, odd):
    t = {"odd": V.fit_t(U, cols, odd), "even": V.fit_t(U, cols, ~odd)}
    w = (SI.fit_weights(t["odd"], signs), SI.fit_weights(t["even"], signs))
    return t, w


def cand_t(U, col, odd):
    slim = pd.DataFrame({"date": U["date"], "_c": U[col], LABEL: U[LABEL]})
    return {"odd": V.nw(SI.daily_corr(slim[odd], "_c", LABEL).to_numpy())["t"],
            "even": V.nw(SI.daily_corr(slim[~odd], "_c", LABEL).to_numpy())["t"]}


def gate6(U, book, name, sign, null_draws):
    yrs = U["date"].dt.year.to_numpy()
    odd = pd.Series(yrs % 2 == 1, index=U.index)
    signs10 = {**SIGNS9S, name: sign}
    t9, w9 = base_fit(U, FC9, SIGNS9S, odd)
    s9 = V.oos_score(U, w9, odd)
    common = s9.notna()
    r = {"base": "icw9_seas split-half OOS (odd/even years)", "rows_dropped_base_nan": int((~common).sum()),
         "weights9_fit_odd": w9[0], "weights9_fit_even": w9[1]}
    base = run_book(book, s9.to_numpy()); r["icw9_seas"] = base

    def with_cand(values, fixed_w=None):
        U["_c"] = values
        U[f"rz_{name}"] = cand_rz(U, name, values)
        tin = cand_t(U, "_c", odd)
        w10 = fixed_w or (SI.fit_weights({**t9["odd"], name: tin["odd"]}, signs10),
                          SI.fit_weights({**t9["even"], name: tin["even"]}, signs10))
        return V.oos_score(U, w10, odd).where(common), tin, w10

    real_vals = U[name].to_numpy(np.float64)
    s10, tin, w10 = with_cand(real_vals)
    cand = run_book(book, s10.to_numpy()); r["cand_plus_icw9_seas"] = cand
    r["cand_t_fit_odd"], r["cand_t_fit_even"] = tin["odd"], tin["even"]
    r["cand_weight_fit_odd"], r["cand_weight_fit_even"] = w10[0][name], w10[1][name]
    r["weights10_fit_odd"], r["weights10_fit_even"] = w10
    inc = np.array(cand["per_offset"]) - np.array(base["per_offset"])
    r["increment_mean40"] = float(inc.mean())
    r["increment_per_offset"] = inc.tolist()
    r["g4_offsets_increment_le_0"] = int((inc <= 0).sum())
    for k, sc in (("oos_ic_cand_plus_icw9_seas", s10), ("oos_ic_icw9_seas", s9)):
        r[k] = V.nw(SI.daily_corr(pd.DataFrame({"date": U["date"], "_s": sc, LABEL: U[LABEL]}), "_s", LABEL).to_numpy())
    log(f"[{name}] icw9_seas {base['excess_cagr_vs_spy_mean40']:+.5f}  +cand {cand['excess_cagr_vs_spy_mean40']:+.5f}  "
        f"inc {inc.mean():+.5f} offsets<=0 {int((inc <= 0).sum())}/40  t fit {tin['odd']:+.2f}/{tin['even']:+.2f}  "
        f"w {w10[0][name]:+.4f}/{w10[1][name]:+.4f}")
    nulls, null_w, wm = [], [], []
    for seed in range(null_draws):
        sh = V.shuffle_within_date(U, name, seed)
        sn, tn, wn = with_cand(sh)
        nulls.append(run_book(book, sn.to_numpy())["excess_cagr_vs_spy_mean40"])
        null_w.append([wn[0][name], wn[1][name]])
        sm, _, _ = with_cand(sh, fixed_w=w10)          # weight-matched null (descriptive)
        wm.append(run_book(book, sm.to_numpy())["excess_cagr_vs_spy_mean40"])
        log(f"[{name}] null {seed}: refit {nulls[-1]:+.5f} (t {tn['odd']:+.2f}/{tn['even']:+.2f})  weight-matched {wm[-1]:+.5f}")
    nulls, wm = np.array(nulls), np.array(wm)
    real = cand["excess_cagr_vs_spy_mean40"]
    r["null"] = {"draws": nulls.tolist(), "cand_weights": null_w, "p50": float(np.percentile(nulls, 50)),
                 "p80": float(np.percentile(nulls, 80)), "mean": float(nulls.mean()), "sd": float(nulls.std()),
                 "percentile_of_real": float((nulls < real).mean())}
    r["weight_matched_null_DESCRIPTIVE"] = {"draws": wm.tolist(), "p50": float(np.percentile(wm, 50)),
                                            "p80": float(np.percentile(wm, 80)),
                                            "percentile_of_real": float((wm < real).mean())}
    r["g6_beats_null_p80"] = bool(real > r["null"]["p80"])
    U.drop(columns=["_c"], inplace=True)
    return r


def icw10_io_increment(U, book, name, sign):
    """Descriptive: (icw10_io + cand) vs icw10_io, both split-half OOS, no null."""
    yrs = U["date"].dt.year.to_numpy()
    odd = pd.Series(yrs % 2 == 1, index=U.index)
    U["rz_io_gap"] = SI.rank_z(U, "io_gap")
    cols, signs = FC9 + ["io_gap"], {**SIGNS9S, "io_gap": +1}
    t10, w10 = base_fit(U, cols, signs, odd)
    s10 = V.oos_score(U, w10, odd)
    U[f"rz_{name}"] = cand_rz(U, name, U[name].to_numpy(np.float64))
    tin = cand_t(U, name, odd)
    s11w = (SI.fit_weights({**t10["odd"], name: tin["odd"]}, {**signs, name: sign}),
            SI.fit_weights({**t10["even"], name: tin["even"]}, {**signs, name: sign}))
    s11 = V.oos_score(U, s11w, odd).where(s10.notna())
    a, b = run_book(book, s10.to_numpy()), run_book(book, s11.to_numpy())
    inc = np.array(b["per_offset"]) - np.array(a["per_offset"])
    return {"icw10_io": a["excess_cagr_vs_spy_mean40"], "icw10_io_plus_cand": b["excess_cagr_vs_spy_mean40"],
            "increment_mean40": float(inc.mean()), "offsets_increment_gt_0": int((inc > 0).sum()),
            "cand_weight_fit_odd_even": [s11w[0][name], s11w[1][name]]}


# ------------------------------------------------------------------ validation
def weight_rule_check():
    t_full = json.loads(ICW_REPORT.read_text())["per_factor_t"]["full"]
    w8 = SI.fit_weights({k: v["t"] for k, v in t_full.items()}, SIGNS8)
    w9 = SI.fit_weights({**{k: v["t"] for k, v in t_full.items()}, "seas": ICW.SEAS_T}, SIGNS9S)
    for k in FC8:
        assert round(w8[k], 4) == ICW.PRODUCTION_WEIGHTS[k], k
    for k in FC9:
        assert round(w9[k], 4) == ICW.PRODUCTION_WEIGHTS_V9_SEAS[k], f"V9_SEAS rule fail {k}"
    log("frozen rule reproduces PRODUCTION_WEIGHTS and PRODUCTION_WEIGHTS_V9_SEAS to 4dp")
    return {"pass": True, "w9_seas_full_precision": w9}


def validate_harness(U, book):
    out = {}
    ref = json.loads(V.READOUT.read_text())["columns"]["c"]["cap150"]
    out["icw8_reconcile"] = V.reconcile(U, book, ref)          # +0.0285416 and both OOS ICs, hard asserts
    s8 = SI.composite_score(U, ICW.PRODUCTION_WEIGHTS)
    b8 = run_book(book, s8.to_numpy())                         # asserts per-offset mean == DR.backtest
    assert abs(b8["excess_cagr_vs_spy_mean40"] - 0.0285416) < 1e-6
    out["icw8_per_offset_mean_equals_DR_backtest"] = b8["excess_cagr_vs_spy_mean40"]
    U["rz_seas"] = SI.rank_z(U, "seas")
    s9f = SI.composite_score(U, ICW.PRODUCTION_WEIGHTS_V9_SEAS)
    b9f = run_book(book, s9f.to_numpy())
    assert abs(b9f["excess_cagr_vs_spy_mean40"] - REF_ICW9_SEAS_4DP) < 1e-6, f"icw9_seas frozen {b9f['excess_cagr_vs_spy_mean40']}"
    out["icw9_seas_frozen_4dp_vs_wo23"] = [b9f["excess_cagr_vs_spy_mean40"], REF_ICW9_SEAS_4DP]
    # retargeted gate function == V.ic_gates on seas (sign +1, odd/even halves)
    r_mine, g_mine = ic_gates(U, "seas", +1, halves="oddeven")
    V.COL = "seas"; V.T_BAR = T_BAR
    r_v, g_v = V.ic_gates(U, xcol="seas")
    for k in ("pooled", "odd", "even", "sector_both_sides", "sector_factor_only"):
        assert r_mine[k]["t"] == r_v[k]["t"] and r_mine[k]["mean"] == r_v[k]["mean"], k
    assert r_mine["year_share"]["max_share"] == r_v["year_share"]["max_share"]
    assert r_mine["ic_offsets_DESCRIPTIVE"]["means"] == r_v["offsets"]["means"]
    for k in ("g1_pooled_t", "g3_sector_both_sides_t", "g5_year_share"):
        assert g_mine[k] == g_v[k], k
    assert g_mine["g2_both_halves_right_sign"] == g_v["g2_both_halves_positive"]
    assert abs(r_mine["pooled"]["t"] - ICW.SEAS_T) < 1e-9, f"seas t {r_mine['pooled']['t']} vs {ICW.SEAS_T}"
    out["gate_fn_equals_V_ic_gates_on_seas"] = True
    out["seas_pooled_t"] = [r_mine["pooled"]["t"], ICW.SEAS_T]
    r_io, _ = ic_gates(U, "io_gap", +1)
    assert abs(r_io["pooled"]["t"] - IO_T_REF) < 1e-9, f"io_gap t {r_io['pooled']['t']}"
    out["io_gap_pooled_t"] = [r_io["pooled"]["t"], IO_T_REF]
    # base book (no candidate): icw9_seas split-half OOS
    yrs = U["date"].dt.year.to_numpy()
    odd = pd.Series(yrs % 2 == 1, index=U.index)
    t9, w9 = base_fit(U, FC9, SIGNS9S, odd)
    out["icw9_seas_split_half_oos_base"] = run_book(book, V.oos_score(U, w9, odd).to_numpy())["excess_cagr_vs_spy_mean40"]
    log(f"harness validation OK: {json.dumps({k: v for k, v in out.items() if k != 'icw8_reconcile'}, default=float)}")
    return out


def coverage(U):
    res = {}
    y = U["date"].dt.year
    for c in ("vol_shock", "str_lowturn", "r_1m", "turnover_21", "seas", "io_gap"):
        fin = U[c].notna()
        res[c] = {"nonnull": float(fin.mean()), "nonnull_old": float(fin[~U["added"]].mean()),
                  "nonnull_added": float(fin[U["added"]].mean()),
                  "by_year": {int(k): float(v) for k, v in fin.groupby(y).mean().items()}}
    valid = U["str_lowturn"].notna()
    res["str_lowturn_detail"] = {
        "eligible_share_of_valid": float(U.loc[valid, "str_eligible"].mean()),
        "exact_zero_share_of_valid": float((U.loc[valid, "str_lowturn"] == 0.0).mean()),
        "noneligible_all_exact_zero": bool((U.loc[valid & ~U["str_eligible"], "str_lowturn"] == 0.0).all()),
        "eligible_range": [float(U.loc[U["str_eligible"], "str_lowturn"].min()), float(U.loc[U["str_eligible"], "str_lowturn"].max())],
        "eligible_added_share": float(U.loc[U["str_eligible"], "added"].mean()),
        "valid_added_share": float(U.loc[valid, "added"].mean())}
    assert res["str_lowturn_detail"]["noneligible_all_exact_zero"]
    res["vol_shock_value_counts"] = {str(k): float(v) for k, v in U["vol_shock"].value_counts(normalize=True).sort_index().items()}
    res["turnover_21_quantiles"] = {q: float(U["turnover_21"].quantile(q)) for q in (0.01, 0.25, 0.5, 0.75, 0.99)}
    return res


# ------------------------------------------------------------------ main
def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--null-draws", type=int, default=20)
    ap.add_argument("--validate", action="store_true")
    ap.add_argument("--trial", choices=list(TRIALS))
    args = ap.parse_args()
    assert args.validate != bool(args.trial), "exactly one of --validate / --trial"
    t0 = time.time()
    meta = json.loads((B.OUT / "build_volshock_meta.json").read_text())
    rep = {"spec": "models/2026-09-29-volshock-strlowturn-screen.md", "label": LABEL, "t_bar": T_BAR}
    rep["composite_panel_v2_sha256_at_start"] = B.sha256(B.PANEL_V2)
    rep["composite_panel_v2_sha256_build"] = meta["composite_panel_v2_sha256"]
    rep["seas_parquet_sha256"] = B.sha256(SEAS_PQ)
    assert rep["seas_parquet_sha256"] == SEAS_SHA
    rep["weight_rule_check"] = weight_rule_check()
    U, all_dates, spy = load_universe()
    rep["panel_slice_2007_2019_hash"] = sha256_slice(U)
    V.add_ranks(U, FC8)
    U["rz_seas"] = SI.rank_z(U, "seas")
    book = V.Book(U, all_dates, spy)
    rep["rows"] = int(len(U)); rep["tickers"] = int(U["ticker"].nunique()); rep["added_rows"] = int(U["added"].sum())

    if args.validate:
        rep["harness"] = validate_harness(U, book)
        rep["coverage"] = coverage(U)
        rep["gate_a_pass"] = json.loads(GATE_A_JSON.read_text())["pass"]
        rep["runtime_s"] = time.time() - t0
        VAL_JSON.write_text(json.dumps(rep, indent=2, default=float))
        log(f"wrote {VAL_JSON} (validate only; no candidate-vs-return statistic)")
        return

    name = args.trial
    spec = TRIALS[name]; sign = spec["sign"]
    rep.update({"trial": name, **spec})
    out_json = B.OUT / f"{name}_screen_report.json"
    prereg = json.loads(VAL_JSON.read_text())
    if rep["composite_panel_v2_sha256_at_start"] != prereg["composite_panel_v2_sha256_at_start"]:
        assert rep["panel_slice_2007_2019_hash"] == prereg["panel_slice_2007_2019_hash"], "panel slice != prereg"
        rep["panel_full_hash_moved_slice_identical"] = True
    ref = json.loads(V.READOUT.read_text())["columns"]["c"]["cap150"]
    rep["harness_reconcile"] = V.reconcile(U, book, ref)     # before any candidate number
    ic, g = ic_gates(U, name, sign)
    rep["ic"] = ic
    log(f"[{name}] IC {ic['pooled']['mean']:+.5f} t {ic['pooled']['t']:+.2f} | H1 {ic['h1_2007_2013']['mean']:+.5f} "
        f"H2 {ic['h2_2014_2019']['mean']:+.5f} | sector both {ic['sector_both_sides']['t']:+.2f} | "
        f"max year share {ic['year_share']['max_share']} ({ic['year_share']['max_year']})")
    out_json.write_text(json.dumps(rep, indent=2, default=float))
    rep["portfolio"] = gate6(U, book, name, sign, args.null_draws)
    g["g4_zero_offset_flips_book_increment"] = bool(rep["portfolio"]["g4_offsets_increment_le_0"] == 0)
    g["g6_beats_null_p80"] = rep["portfolio"]["g6_beats_null_p80"]
    g["g7_gate_a"] = bool(json.loads(GATE_A_JSON.read_text())["pass"])
    order = ["g1_pooled_t", "g2_both_halves_right_sign", "g3_sector_both_sides_t",
             "g4_zero_offset_flips_book_increment", "g5_year_share", "g6_beats_null_p80", "g7_gate_a"]
    rep["gates"] = {k: g[k] for k in order}
    rep["failed_gates"] = [k for k in order if not g[k]]
    rep["verdict"] = "PASS-nomination" if not rep["failed_gates"] else "DEAD"
    log(f"[{name}] gates {rep['gates']} -> {rep['verdict']}")
    out_json.write_text(json.dumps(rep, indent=2, default=float))

    # ---------------- descriptive only (not gates)
    desc = {}
    for c in ("r_5d", "r_21d", "momentum_12_1", "io_gap", "volatility_60", "pct_from_high_252", "seas"):
        desc[f"median_spearman_vs_{c}"] = float(SI.daily_corr(U, name, c).median())
    if name == "str_lowturn":
        el = U[["date", LABEL]].copy(); el["x"] = U["r_1m"].where(U["str_eligible"])
        desc["eligible_only_ic"] = V.nw(SI.daily_corr(el, "x", LABEL).to_numpy())
    desc["icw10_io_increment"] = icw10_io_increment(U, book, name, sign)
    rep["descriptive"] = desc
    log(f"[{name}] descriptive {json.dumps(desc, default=float)}")
    rep["runtime_s"] = time.time() - t0
    out_json.write_text(json.dumps(rep, indent=2, default=float))
    log(f"wrote {out_json} ({time.time()-t0:.0f}s)")


if __name__ == "__main__":
    main()
