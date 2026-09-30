"""
WO-29 pre-registered screen of `ear` (earnings announcement return, CJL 1996 /
BKSV 2008) on the v2 grid, column c, cap150, h = 40, forward_return_tradable_40,
nomination era 2007-01-02..2019-12-31.
Registration: models/2026-09-30-ear-screen.md (committed cf8eec7 before any EAR
outcome statistic). SUE/PEAD family trial 2, bar pooled NW(39) IC t >= +2.24, sign +.

Harness: insider/screen_insider_v2grid.py + insider/screen_insider.py imported as
modules (never edited; their main() is never called). WO-29 overrides:
  gate 2  halves 2007-2013 / 2014-2019 (odd/even reported, not gated)
  gate 4  0/40 offset flips of the BOOK increment (icw9_seas+ear - icw9_seas),
          flip = increment_o <= 0 (IC-offset flips reported, not gated)
  gate 6  base = icw9_seas (FC8 + seas) split-half OOS, candidate adds ear;
          ear's rank_z is the stored signed rank (neutral 0), never re-ranked;
          null permutes live signed ranks among live rows within date.

Modes
  --validate   Gate A checks only (harness reconcile, weight rule, base icw9_seas
               reproduces WO-18, label trace, Step 0 coverage from build meta).
               NO EAR outcome number. -> out/ear/validate_ear.json
  (default)    the registered screen -> out/ear/ear_screen_report.json
Usage: python screen_ear.py [--validate] [--null-draws 20]
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
sys.path.insert(0, str(HERE))
sys.path.insert(0, str(SRC / "insider"))
sys.path.insert(0, str(SRC / "reset2026"))
import build_ear as B                  # noqa: E402
import screen_insider_v2grid as V      # noqa: E402
import screen_insider as SI            # noqa: E402
import downcap_v2_readout as DR        # noqa: E402
import ic_weighted_composite as ICW    # noqa: E402

COL = "ear"
V.COL = COL
V.SIGN = +1
V.T_BAR = 2.24
OUT = B.OUT
OUT_JSON = OUT / "ear_screen_report.json"
VAL_JSON = OUT / "validate_ear.json"
V.OUT_JSON = OUT_JSON                  # never let the harness write under MAIN
HOLDOUT = pd.Timestamp("2020-01-01")
LABEL = V.LABEL
ICW_REPORT = B.MAIN / "out" / "reset2026" / "ic_weighted_composite_report.json"
WT = Path("/Users/ggraham/pipe_dream/.claude/worktrees")
SEAS = WT / "agent-ad57ef9f38454d99d" / "final" / "out" / "seasonality" / "seas_factor_v2.parquet"
SEAS_SHA = "8054af212270efbf0bffd8fc98a586083529c5dfb5879b669984172b60a38e45"
SEAS_REPORT = WT / "agent-ad57ef9f38454d99d" / "final" / "out" / "seasonality" / "seas_screen_report.json"
SUE = WT / "agent-a505179eca9ed9bf2" / "final" / "out" / "sue" / "sue_factor_v2.parquet"
SUE_SHA = "198cef0b5a387cab0104a982b1e80250f371938e97bbf7931ce7ae399d4ea6de"
IOGAP = WT / "overnight-intraday" / "final" / "out" / "overnight" / "io_gap_factor_v2.parquet"
FC8 = V.FC8
FC9 = FC8 + ["seas"]
SIGNS_B = {**V.SIGNS8, "seas": +1}
SIGNS_C = {**SIGNS_B, COL: +1}
log = V.log


def weight_rule_check():
    t_full = json.loads(ICW_REPORT.read_text())["per_factor_t"]["full"]
    w_icw = ICW.fit_weights(t_full, FC8)
    w_si = SI.fit_weights({k: v["t"] for k, v in t_full.items()}, V.SIGNS8)
    out = {k: [round(w_icw[k], 4), round(w_si[k], 4), ICW.PRODUCTION_WEIGHTS[k]] for k in FC8}
    for k, (a, b, c) in out.items():
        assert a == c and b == c, f"WEIGHT RULE FAIL {k}: {a} {b} vs {c}"
    return {"t_source": str(ICW_REPORT), "weights_icw_si_production": out, "pass": True}


def load_universe():
    p, spy = DR.load_column("c")
    all_dates = sorted(p["date"].unique())
    p = p[p["eligible_cap150"]].drop(columns=["eligible_cap500", "eligible_cap2000"])
    sec = pd.read_parquet(DR.R26 / "composite_panel_v2.parquet", columns=["ticker", "date", "sector"],
                          filters=[("date", ">=", "2007-01-02"), ("date", "<=", "2019-12-31")])
    sec["date"] = pd.to_datetime(sec["date"]); sec["ticker"] = sec["ticker"].astype(str)
    assert B.sha256(SEAS) == SEAS_SHA, "seas factor file changed"
    seas = pd.read_parquet(SEAS, columns=["ticker", "date", "seas"])
    ear = pd.read_parquet(OUT / "ear_factor_v2.parquet", columns=["ticker", "date", "ear_raw", "ear_age", "cov100"])
    for f in (seas, ear):
        f["date"] = pd.to_datetime(f["date"]); f["ticker"] = f["ticker"].astype(str)
    assert ear["date"].max() < HOLDOUT
    n = len(p)
    p = p.merge(sec, on=["ticker", "date"], how="left").merge(seas, on=["ticker", "date"], how="left") \
         .merge(ear, on=["ticker", "date"], how="left")
    assert len(p) == n, "merge changed row count"
    assert p["date"].max() < HOLDOUT and spy.index.max() < HOLDOUT, "HOLD-OUT BREACH"
    del sec, seas, ear
    old_t = set(pd.read_parquet(DR.R26 / "composite_panel.parquet", columns=["ticker"])["ticker"].astype(str).unique())
    p["added"] = ~p["ticker"].isin(old_t)
    U = p.sort_values(["date", "ticker"]).reset_index(drop=True)
    # signed rank over live rows of this universe; everything else neutral 0 (never NaN)
    U["ear_live"] = SI.rank_z(U, "ear_raw")                  # NaN off live rows
    U[COL] = U["ear_live"].fillna(0.0)
    assert U[COL].notna().all()
    return U, all_dates, spy


def backtest_per_off(picks_by_date, all_dates, spy):
    """downcap_v2_readout.backtest, copied to also return the 40 per-offset values."""
    ann = 252.0 / DR.RB.HORIZON
    per_off = []
    for off in range(40):
        prev, recs = set(), []
        for tp in all_dates[off::DR.RB.HORIZON]:
            if tp not in picks_by_date:
                continue
            gross, cur = picks_by_date[tp]
            f_new = sum(1 for t in cur if t not in prev) / len(cur)
            prev = cur
            recs.append({"date": tp, "gross": gross, "f_new": f_new, "spy": spy.get(tp, np.nan)})
        net = DR.RB.turnover_net_return(recs, DR.COST_BPS)
        s = np.array([r["spy"] for r in recs], dtype=np.float64)
        ok = np.isfinite(s)
        per_off.append(float((net[ok] - s[ok]).mean() * ann))
    return per_off


def run_book(book, score):
    pk = book.picks(np.asarray(score, dtype=np.float64))
    r = DR.backtest(pk, book.all_dates, book.spy)
    r["per_offset"] = backtest_per_off(pk, book.all_dates, book.spy)
    assert abs(np.mean(r["per_offset"]) - r["excess_cagr_vs_spy_mean40"]) < 1e-12
    return r, pk


class Stack:
    """Split-half (odd/even year) OOS weights for a factor list; rz_<c> must exist."""

    def __init__(self, U):
        self.U = U
        yrs = U["date"].dt.year.to_numpy()
        self.odd = pd.Series(yrs % 2 == 1, index=U.index)
        self.t = {"odd": {}, "even": {}}

    def fit(self, cols, overwrite=()):
        for c in cols:
            if c in self.t["odd"] and c not in overwrite:
                continue
            tt = V.fit_t(self.U, [c], self.odd); te = V.fit_t(self.U, [c], ~self.odd)
            self.t["odd"][c] = tt[c]; self.t["even"][c] = te[c]

    def weights(self, signs):
        return (SI.fit_weights({c: self.t["odd"][c] for c in signs}, signs),
                SI.fit_weights({c: self.t["even"][c] for c in signs}, signs))

    def score(self, w):
        return V.oos_score(self.U, w, self.odd)


def label_trace(U):
    """close[t+40]/open[t+1]-1 from v2 open/close (rows <= 2019-12-31), compared on
    cap150 rows whose t+40 (the ticker's 40th next panel row) is itself < 2020."""
    q = pd.read_parquet(B.PANEL_V2, columns=["ticker", "date", "open", "close", LABEL],
                        filters=[("date", ">=", "2006-12-01"), ("date", "<=", "2019-12-31")])
    q["date"] = pd.to_datetime(q["date"]); q["ticker"] = q["ticker"].astype(str)
    assert q["date"].max() < HOLDOUT
    q = q.sort_values(["ticker", "date"]).reset_index(drop=True)
    g = q.groupby("ticker", sort=False)
    q["lab"] = g["close"].shift(-40) / g["open"].shift(-1) - 1.0
    q = q.merge(U[["ticker", "date"]], on=["ticker", "date"], how="inner")
    both = q["lab"].notna() & q[LABEL].notna()
    d = (q.loc[both, "lab"] - q.loc[both, LABEL]).abs()
    tr = {"rows_compared": int(both.sum()), "share_abs_diff_lt_1e-9": float((d < 1e-9).mean()),
          "median_abs_diff": float(d.median()), "p99_abs_diff": float(d.quantile(0.99)),
          "sample": q.loc[both, ["ticker", "date", "open", "close", LABEL, "lab"]].sample(5, random_state=3).astype(str).to_dict("records")}
    tr["pass"] = bool(tr["share_abs_diff_lt_1e-9"] >= 0.99)
    return tr


def base_reconcile(U, book, st):
    """icw9_seas split-half book must reproduce WO-18 seas_screen_report portfolio.icw9."""
    ref = json.loads(SEAS_REPORT.read_text())["portfolio"]
    w8 = st.weights(V.SIGNS8)
    s8 = st.score(w8)
    common = s8.notna()
    w9 = st.weights(SIGNS_B)
    s9 = st.score(w9).where(common)
    r9, pk9 = run_book(book, s9.to_numpy())
    got, want = r9["excess_cagr_vs_spy_mean40"], ref["icw9"]["excess_cagr_vs_spy_mean40"]
    assert abs(got - want) < 1e-6, f"BASE RECONCILE FAIL {got} vs {want}"
    assert abs(w9[0]["seas"] - ref["ins_weight_fit_odd"]) < 1e-12 and abs(w9[1]["seas"] - ref["ins_weight_fit_even"]) < 1e-12
    log(f"base icw9_seas reconcile OK {got:+.6f} == WO-18 {want:+.6f}")
    return {"icw9_seas_split_half": [got, want], "seas_w_odd_even": [w9[0]["seas"], w9[1]["seas"]], "pass": True}, \
        common, s9, r9, w9


def shuffle_live(U, seed):
    """Permute the live signed ranks among live rows within each date; neutral stays 0."""
    return np.nan_to_num(V.shuffle_within_date(U, "ear_live", seed), nan=0.0)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--null-draws", type=int, default=20)
    ap.add_argument("--validate", action="store_true")
    args = ap.parse_args()
    t0 = time.time()
    meta = json.loads((OUT / "build_ear_meta.json").read_text())
    rep = {"spec": "models/2026-09-30-ear-screen.md", "family": "SUE/PEAD", "trial": 2,
           "t_bar": V.T_BAR, "sign": +1, "column": COL, "label": LABEL, "null_draws": args.null_draws}
    rep["composite_panel_v2_sha256_at_start"] = B.sha256(B.PANEL_V2)
    assert rep["composite_panel_v2_sha256_at_start"] == meta["composite_panel_v2_sha256"], "panel changed since build"
    rep["weight_rule_check"] = weight_rule_check()
    step0 = {"coverage": meta["coverage_step0"], "dead_name_LEH": meta["dead_name_LEH"],
             "cadence_check": meta["cadence_check"], "pit_assert": meta["pit_assert"]}
    rep["step0"] = step0

    U, all_dates, spy = load_universe()
    V.add_ranks(U, FC9)                 # rz_<FC8>, rz_seas (production rank_z)
    U[f"rz_{COL}"] = U[COL]             # signed rank, neutral 0; never re-ranked
    book = V.Book(U, all_dates, spy)
    rep["rows"] = int(len(U)); rep["tickers"] = int(U["ticker"].nunique()); rep["added_rows"] = int(U["added"].sum())
    rep["ear_live_share"] = float(U["ear_live"].notna().mean())
    rep["ear_live_share_old"] = float(U.loc[~U["added"], "ear_live"].notna().mean())
    rep["ear_live_share_added"] = float(U.loc[U["added"], "ear_live"].notna().mean())
    rep["cov100_share_old_added_in_U"] = [float(U.loc[~U["added"], "cov100"].mean()), float(U.loc[U["added"], "cov100"].mean())]
    ref = json.loads(V.READOUT.read_text())["columns"]["c"]["cap150"]
    rep["harness_reconcile"] = V.reconcile(U, book, ref)
    st = Stack(U)
    st.fit(FC9)
    rep["base_reconcile"], common, s9, r9, w9 = base_reconcile(U, book, st)
    rep["label_trace"] = label_trace(U)
    log(f"label trace {rep['label_trace']['share_abs_diff_lt_1e-9']:.5f} of {rep['label_trace']['rows_compared']:,}")
    gateA = bool(step0["coverage"]["pass_within_10pp"] and step0["pit_assert"]["pass"] and rep["label_trace"]["pass"]
                 and rep["weight_rule_check"]["pass"] and rep["base_reconcile"]["pass"]
                 and step0["dead_name_LEH"]["n_original_202"] > 0)
    rep["gate_A_validate"] = gateA

    if args.validate:
        rep["runtime_s"] = time.time() - t0
        VAL_JSON.write_text(json.dumps(rep, indent=2, default=str))
        log(f"wrote {VAL_JSON} (validate only; no EAR outcome statistic). Gate A {gateA}")
        return

    prereg = json.loads(VAL_JSON.read_text())
    assert prereg["composite_panel_v2_sha256_at_start"] == rep["composite_panel_v2_sha256_at_start"], "panel != validate"
    assert prereg["gate_A_validate"] and gateA, "Gate A not clean; screen must not run"
    OUT_JSON.write_text(json.dumps(rep, indent=2, default=str))

    # ---------------- gates 1, 3, 5 (+ harness IC offsets, odd/even as descriptive)
    ic, g_h = V.ic_gates(U, xcol=COL)
    s = SI.daily_corr(U, COL, LABEL)
    ic["half_2007_2013"] = V.nw(s[s.index.year <= 2013].to_numpy())
    ic["half_2014_2019"] = V.nw(s[s.index.year >= 2014].to_numpy())
    rep["ic"] = ic
    log(f"IC {ic['pooled']['mean']:+.5f} t {ic['pooled']['t']:+.2f} | 07-13 {ic['half_2007_2013']['mean']:+.5f} "
        f"14-19 {ic['half_2014_2019']['mean']:+.5f} | sector both {ic['sector_both_sides']['t']:+.2f} | "
        f"max year share {ic['year_share']['max_share']} ({ic['year_share']['max_year']})")
    OUT_JSON.write_text(json.dumps(rep, indent=2, default=str))

    # ---------------- gate 6 (+ gate 4 from its per-offset increments)
    st.fit([COL])
    w10 = st.weights(SIGNS_C)
    s10 = st.score(w10).where(common)
    r10, _ = run_book(book, s10.to_numpy())
    inc = np.array(r10["per_offset"]) - np.array(r9["per_offset"])
    port = {"icw9_seas": r9, "icw10_ear": r10, "increment": float(r10["excess_cagr_vs_spy_mean40"] - r9["excess_cagr_vs_spy_mean40"]),
            "increment_per_offset": inc.tolist(), "increment_flips_le0": int((inc <= 0).sum()),
            "ear_t_fit_odd": st.t["odd"][COL], "ear_t_fit_even": st.t["even"][COL],
            "ear_weight_fit_odd": w10[0][COL], "ear_weight_fit_even": w10[1][COL],
            "weights10_fit_odd": w10[0], "weights10_fit_even": w10[1], "rows_dropped_base_nan": int((~common).sum())}
    for k, sc in (("icw10_oos_ic", s10), ("icw9_seas_oos_ic", s9)):
        port[k] = V.nw(SI.daily_corr(pd.DataFrame({"date": U["date"], "_s": sc, LABEL: U[LABEL]}), "_s", LABEL).to_numpy())
    log(f"icw9_seas {r9['excess_cagr_vs_spy_mean40']:+.5f} icw10 {r10['excess_cagr_vs_spy_mean40']:+.5f} "
        f"inc flips {port['increment_flips_le0']}/40 | ear t fit {st.t['odd'][COL]:+.2f}/{st.t['even'][COL]:+.2f}")
    nulls, wm_nulls, null_w = [], [], []
    real_ear = U[COL].to_numpy().copy()
    for seed in range(args.null_draws):
        U[COL] = shuffle_live(U, seed); U[f"rz_{COL}"] = U[COL]
        st.fit([COL], overwrite=[COL])
        wn = st.weights(SIGNS_C)
        nulls.append(run_book(book, st.score(wn).where(common).to_numpy())[0]["excess_cagr_vs_spy_mean40"])
        wm_nulls.append(run_book(book, st.score(w10).where(common).to_numpy())[0]["excess_cagr_vs_spy_mean40"])
        null_w.append([wn[0][COL], wn[1][COL]])
        log(f"null {seed}: refit {nulls[-1]:+.5f} weight-matched {wm_nulls[-1]:+.5f} (t {st.t['odd'][COL]:+.2f}/{st.t['even'][COL]:+.2f})")
    U[COL] = real_ear; U[f"rz_{COL}"] = real_ear
    st.fit([COL], overwrite=[COL])
    nulls, wm_nulls = np.array(nulls), np.array(wm_nulls)
    real = r10["excess_cagr_vs_spy_mean40"]
    port["null"] = {"draws": nulls.tolist(), "ear_weights": null_w, "p50": float(np.percentile(nulls, 50)),
                    "p80": float(np.percentile(nulls, 80)), "mean": float(nulls.mean()), "sd": float(nulls.std()),
                    "percentile_of_real": float((nulls < real).mean())}
    port["weight_matched_null_DESCRIPTIVE"] = {"draws": wm_nulls.tolist(), "p50": float(np.percentile(wm_nulls, 50)),
                                               "p80": float(np.percentile(wm_nulls, 80)),
                                               "percentile_of_real": float((wm_nulls < real).mean())}
    port["g6_beats_null_p80"] = bool(real > port["null"]["p80"])
    rep["portfolio"] = port

    g = {"g1_pooled_t_ge_2.24": bool(ic["pooled"]["t"] >= V.T_BAR),
         "g2_halves_2007_2013_and_2014_2019_positive": bool(ic["half_2007_2013"]["mean"] > 0 and ic["half_2014_2019"]["mean"] > 0),
         "g3_sector_both_sides_t_ge_1": g_h["g3_sector_both_sides_t"],
         "g4_zero_book_increment_offset_flips": bool(port["increment_flips_le0"] == 0),
         "g5_max_year_share_le_0.45": g_h["g5_year_share"],
         "g6_beats_null_p80": port["g6_beats_null_p80"],
         "g7_gate_A_clean": gateA}
    rep["gates"] = g
    failed = [k for k, v in g.items() if not v]
    rep["verdict"] = "PASS-nomination" if not failed else "DEAD"
    rep["failed_gates"] = failed
    rep["descriptive_harness_gates"] = {"odd_even_both_positive": g_h["g2_both_halves_positive"],
                                        "ic_offset_zero_flips": g_h["g4_zero_offset_flips"]}
    log(f"gates {g} -> {rep['verdict']}")
    OUT_JSON.write_text(json.dumps(rep, indent=2, default=str))

    # ---------------- descriptive only (cannot rescue a fail)
    desc = {}
    yrs = np.array([pd.Timestamp(d).year for d in all_dates])
    # book-increment LOYO: per-year contribution is not separable from per_offset; report
    # the harness LOYO min/max of each book instead
    desc["loyo_icw9_seas"] = {k: r9[k] for k in ("loyo_min", "loyo_min_dropped_year", "loyo_max")}
    desc["loyo_icw10"] = {k: r10[k] for k in ("loyo_min", "loyo_min_dropped_year", "loyo_max")}
    sl = U.loc[U["ear_live"].notna(), ["date", "ear_live", LABEL]]
    desc["ic_live_rows_only"] = {**V.nw(SI.daily_corr(sl, "ear_live", LABEL).to_numpy())}
    assert B.sha256(SUE) == SUE_SHA, "sue factor file changed"
    sue = pd.read_parquet(SUE, columns=["ticker", "date", "sue"]); sue["date"] = pd.to_datetime(sue["date"]); sue["ticker"] = sue["ticker"].astype(str)
    sue = sue[sue["date"] < HOLDOUT]
    io = pd.read_parquet(IOGAP, columns=["ticker", "date", "io_gap"], filters=[("date", "<", HOLDOUT)])
    io["date"] = pd.to_datetime(io["date"]); io["ticker"] = io["ticker"].astype(str)
    assert io["date"].max() < HOLDOUT
    n = len(U)
    U = U.merge(sue, on=["ticker", "date"], how="left").merge(io, on=["ticker", "date"], how="left")
    assert len(U) == n
    del sue, io
    desc["coverage_sue_io_gap"] = [float(U["sue"].notna().mean()), float(U["io_gap"].notna().mean())]
    for c in ["sue", "momentum_12_1", "io_gap"]:
        desc[f"median_spearman_ear_vs_{c}"] = float(SI.daily_corr(U, COL, c).median())
        desc[f"median_spearman_ear_live_vs_{c}"] = float(SI.daily_corr(U, "ear_live", c).median())
    # icw9_seas + sue (+ ear), same split-half method, same common mask
    U["rz_sue"] = SI.rank_z(U, "sue")
    book2 = V.Book(U, all_dates, spy)
    st2 = Stack(U); st2.t = {h: dict(st.t[h]) for h in st.t}
    st2.fit(["sue"])
    sb = st2.score(st2.weights({**SIGNS_B, "sue": +1})).where(common)
    sc = st2.score(st2.weights({**SIGNS_C, "sue": +1})).where(common)
    rb = book2.run(sb.to_numpy()); rc = book2.run(sc.to_numpy())
    desc["icw9_seas_sue"] = rb["excess_cagr_vs_spy_mean40"]
    desc["icw9_seas_sue_ear"] = rc["excess_cagr_vs_spy_mean40"]
    desc["increment_over_seas_sue"] = rc["excess_cagr_vs_spy_mean40"] - rb["excess_cagr_vs_spy_mean40"]
    desc["sue_t_fit_odd_even"] = [st2.t["odd"]["sue"], st2.t["even"]["sue"]]
    rep["descriptive"] = desc
    log(f"descriptive {json.dumps(desc, default=float)}")
    rep["runtime_s"] = time.time() - t0
    OUT_JSON.write_text(json.dumps(rep, indent=2, default=str))
    log(f"wrote {OUT_JSON} ({time.time()-t0:.0f}s)")


if __name__ == "__main__":
    main()
