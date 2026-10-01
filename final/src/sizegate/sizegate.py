"""
WO-32 (COO, Gabe "Go" 2026-09-30): size-leadership gate. Hold SPY instead of
the icw9_seas decile_volq book for a 40-day window when large caps have led:
S(t) = trailing 252-trading-day TOTAL return of IWM minus SPY (yfinance
adj_close, WO-31 bench pull, data <= t). S(t) < 0 -> SPY (excess 0), else book.
Flat 15 bp on every state switch; initial state BOOK; S undefined -> BOOK.
Pre-registration: final/models/2026-09-30-size-leadership-gate.md (committed
before any gated-vs-ungated number). Trial 1, size/market-timing family.
Era B = hold-out read #12 (unfitted; rule fixed in advance).

Harness (read-only imports): WO-31 pool_read / WO-21 drag_decomp / WO-23
model_audit_wo23.load_theo; v2 col c, cap150, net 15 bp, 40 offsets, h=40,
label close[t+40]/open[t+1] (outcome_cache_v2), SPY leg = cache SPY row.

Usage (one process per step):
  python sizegate.py --chains A     reconcile (hard assert) + dump ungated chains -> out/sizegate/parts/A_chains.json
  python sizegate.py --chains B
  python sizegate.py --prep         signal, Gate A (PIT, name-checks), WO-30 label reproduction,
                                    share in SPY, episodes (no performance) -> out/sizegate/prep.json
  python sizegate.py --run          gated vs ungated (AFTER the pre-reg commit) -> out/sizegate/sizegate.json
"""
import argparse
import hashlib
import json
import subprocess
import sys
import time
from pathlib import Path

import numpy as np
import pandas as pd

HERE = Path(__file__).resolve().parent
SRC = HERE.parent
FINAL = HERE.parents[1]
OUT = FINAL / "out" / "sizegate"
PARTS = OUT / "parts"
BENCH = Path("/Users/ggraham/pipe_dream/.claude/worktrees/agent-a224b0b3e3e4eaba0/final/out/pool/bench")
BENCH_META = FINAL / "out" / "pool" / "bench" / "pull_meta.json"      # committed copy (integration)
SEAS_EXT_RO = Path("/Users/ggraham/pipe_dream/.claude/worktrees/wo24-construction-drag/final/out/audit/seas_factor_ext.parquet")
POOL_READ = FINAL / "out" / "pool" / "pool_hedge_read.json"
CUT = pd.Timestamp("2011-10-01")
LOOKBACK = 252
SWITCH = 0.0015
ANN = 252.0 / 40
TOL_SPEC = 1e-4      # 0.01 pp
TOL_EXACT = 1e-10
SPEC = {("A", "full", "icw9_seas"): 0.0349, ("A", "post", "icw9_seas"): 0.0051, ("B", "full", "icw9_seas"): -0.0202,
        ("A", "full", "icw8"): 0.0285, ("A", "post", "icw8"): 0.0001, ("B", "full", "icw8"): -0.0199}
WINS = {"A": {"full": (None, None), "pre": (None, CUT), "post": (CUT, None)}, "B": {"full": (None, None)}}
MODELS = ("icw9_seas", "icw8")


def log(m):
    print(f"[{time.strftime('%H:%M:%S')}] {m}", flush=True)


def sha(p):
    return hashlib.sha256(p.read_bytes()).hexdigest()


# ------------------------------------------------------------------ signal
def load_bench():
    meta = json.loads(BENCH_META.read_text())
    g = {}
    for s in ("SPY", "IWM"):
        p = BENCH / f"{s}.parquet"
        assert sha(p) == meta[s]["sha256"], f"{s} bench parquet sha256 != WO-31 pull_meta"
        d = pd.read_parquet(p, columns=["date", "close", "adj_close"])
        d["date"] = pd.to_datetime(d["date"])
        g[s] = d.sort_values("date").set_index("date")
    return g


def size_signal(g, col="adj_close", upto=None):
    """S(t) on inner-joined dates; upto truncates the input (PIT test)."""
    j = pd.concat([g["SPY"][col].rename("spy"), g["IWM"][col].rename("iwm")], axis=1, join="inner").astype(np.float64)
    if upto is not None:
        j = j[j.index <= upto]
    return (j["iwm"] / j["iwm"].shift(LOOKBACK) - 1.0) - (j["spy"] / j["spy"].shift(LOOKBACK) - 1.0)


def cal_year(s, y):
    return float(s[s.index.year == y].iloc[-1] / s[s.index.year == y - 1].iloc[-1] - 1.0)


def state_on(S, dates):
    """'SPY' / 'BOOK' / 'undef' per date; exact same-day S required."""
    idx = pd.DatetimeIndex(dates)
    missing = idx.difference(S.index)
    assert len(missing) == 0, f"rebalance dates without same-day S: {list(missing[:5])}"
    v = S.reindex(idx)
    st = np.where(v.isna(), "undef", np.where(v < 0, "SPY", "BOOK"))
    return pd.Series(st, index=idx), v


# ------------------------------------------------------------------ step 1: chains
def chains_job(period):
    sys.path.insert(0, str(SRC / "audit"))
    sys.path.insert(0, str(SRC / "construction"))
    import model_audit_wo23 as MA
    import drag_decomp as DD
    V, SI, DR, ICW = MA.V, MA.SI, MA.DR, MA.ICW
    MA.SEAS_EXT = SEAS_EXT_RO
    T0 = time.time()
    W = {"icw9_seas": dict(ICW.PRODUCTION_WEIGHTS_V9_SEAS), "icw8": dict(ICW.PRODUCTION_WEIGHTS)}
    assert W["icw9_seas"] == MA.W9 and W["icw8"] == MA.W8
    U, all_dates, spy = MA.load_theo(period, "cap150")
    all_dates = [pd.Timestamp(d) for d in all_dates]
    V.add_ranks(U, MA.FT)
    book = V.Book(U, all_dates, spy)
    pk = {m: book.picks(SI.composite_score(U, w).to_numpy()) for m, w in W.items()}
    del U, book
    log(f"[{period}] books built ({time.time()-T0:.0f}s)")
    ref = json.loads(POOL_READ.read_text())["tables"]
    out = {"period": period, "all_dates": [str(d.date()) for d in all_dates], "reconcile": [], "chains": {}}
    for wn, (lo, hi) in WINS[period].items():
        for m in MODELS:
            p_, ds = DD.window(pk[m], all_dates, lo, hi)
            ch = DD.chains(p_, ds, spy, DR.COST_BPS)
            po = DD.per_offset(ch)
            bt = DR.backtest(p_, ds, spy)["excess_cagr_vs_spy_mean40"]
            assert abs(po.mean() - bt) < 1e-12, "chains vs DR.backtest oracle"
            r_exact = ref[m][f"{period}_{wn}"]["cap150"]["book_vs_spy"]
            rec = {"name": f"{period} {wn} {m}", "got": float(po.mean()), "wo31_exact": r_exact,
                   "diff_exact": float(po.mean() - r_exact)}
            if (period, wn, m) in SPEC:
                rec["spec"] = SPEC[(period, wn, m)]
                rec["diff_spec"] = float(po.mean() - SPEC[(period, wn, m)])
            log(f"reconcile {rec}")
            assert abs(rec["diff_exact"]) < TOL_EXACT, f"RECONCILE FAIL (WO-31 exact) {rec}"
            if "spec" in rec:
                assert abs(rec["diff_spec"]) < TOL_SPEC, f"RECONCILE FAIL (spec) {rec}"
            out["reconcile"].append(rec)
            out["chains"][f"{wn}|{m}"] = [{"date": [str(pd.Timestamp(d).date()) for d in c["date"]],
                                          "exc": [float(x) for x in c["exc"]]} for c in ch]
    PARTS.mkdir(parents=True, exist_ok=True)
    (PARTS / f"{period}_chains.json").write_text(json.dumps(out))
    log(f"[{period}] wrote {PARTS / f'{period}_chains.json'} ({time.time()-T0:.0f}s)")


# ------------------------------------------------------------------ step 2: prep (no performance)
def episodes(lab, ep_min=40):
    v = lab.to_numpy()
    starts = np.flatnonzero(np.r_[True, v[1:] != v[:-1]])
    ends = np.r_[starts[1:], len(v)]
    res = {}
    for s, e in zip(starts, ends):
        r = res.setdefault(v[s], {"raw_runs": 0, f"runs_ge{ep_min}d": 0, "runs": []})
        r["raw_runs"] += 1
        if e - s >= ep_min:
            r[f"runs_ge{ep_min}d"] += 1
            r["runs"].append([str(lab.index[s].date()), str(lab.index[e - 1].date()), int(e - s)])
    for k, r in res.items():
        r["days"] = int((v == k).sum())
    return res


def load_parts():
    P = {p: json.loads((PARTS / f"{p}_chains.json").read_text()) for p in "AB"}
    for p in P:
        P[p]["all_dates"] = [pd.Timestamp(d) for d in P[p]["all_dates"]]
    return P


def chain_states(chs, st):
    """per chain: dates, state list (undef -> BOOK), n switches (initial BOOK)."""
    res = []
    for c in chs:
        s = ["SPY" if st[pd.Timestamp(d)] == "SPY" else "BOOK" for d in c["date"]]
        sw = sum(1 for a, b in zip(["BOOK"] + s[:-1], s) if a != b)
        res.append((s, sw))
    return res


def prep():
    g = load_bench()
    S = size_signal(g)
    S_px = size_signal(g, "close")
    P = load_parts()
    out = {"bench": {s: {"file": str(BENCH / f"{s}.parquet"), "sha256_ok": True} for s in g}}
    # ---- Gate A: name-checks (calendar-year total return, hedged_composite.cal_year convention)
    nc = {}
    for s, y, tgt, tol in (("IWM", 2008, -0.3414, 0.001), ("IWM", 2017, 0.1458, 0.001),
                           ("SPY", 2008, -0.368, 0.02), ("SPY", 2017, 0.217, 0.02)):
        tr, pr = cal_year(g[s]["adj_close"], y), cal_year(g[s]["close"], y)
        nc[f"{s}_{y}"] = {"total": tr, "price": pr, "target": tgt, "tol": tol, "ok": abs(tr - tgt) <= tol}
        log(f"name-check {s} {y}: total {tr:+.4f} (target {tgt:+.4f}) price {pr:+.4f}")
        assert nc[f"{s}_{y}"]["ok"], f"NAME-CHECK FAIL {s} {y}"
    out["name_check"] = nc
    # ---- Gate A: PIT append-invariance (truncate input at t, recompute S(t))
    samp = [pd.Timestamp(x) for x in ("2007-01-05", "2008-10-10", "2011-10-03", "2015-06-15", "2019-12-31",
                                      "2020-03-23", "2021-06-15", "2023-06-15", "2026-07-30")]
    pit = {}
    for t in samp:
        t = S.index[S.index.searchsorted(t)]
        a, b = S.loc[t], size_signal(g, upto=t).iloc[-1]
        pit[str(t.date())] = {"full": float(a), "truncated": float(b)}
        assert (np.isnan(a) and np.isnan(b)) or abs(a - b) < 1e-12, f"PIT FAIL {t}"
    # also: a fake future dividend shock (rescale adj_close before t) cannot move S(t)
    t = pd.Timestamp("2015-06-15")
    g2 = {k: v.copy() for k, v in g.items()}
    g2["IWM"].loc[g2["IWM"].index <= t, "adj_close"] *= 0.97
    assert abs(size_signal(g2).loc[t] - S.loc[t]) < 1e-12, "PIT FAIL: cumulative rescale moved S"
    out["pit_append_invariance"] = {"dates": pit, "tol": 1e-12, "rescale_invariant": True}
    # ---- labels per era
    lab = {}
    for p in "AB":
        ad = P[p]["all_dates"]
        st, v = state_on(S, ad)
        stp, _ = state_on(S_px, ad)
        und = st == "undef"
        u = und.to_numpy()
        assert (u == (np.arange(len(u)) < u.sum())).all(), "undefined outside the start-of-era warm-up"
        lab[p] = st
        e = {"n_dates": len(ad), "undefined_dates": [str(d.date()) for d in st.index[und]],
             "share_spy_panel_calendar": float((st == "SPY").mean()),
             "tr_vs_price_sign_disagree_days": int(((st != stp) & ~und).sum()),
             "episodes": episodes(st.where(~und, "BOOK").map({"SPY": "large_lead", "BOOK": "small_lead"}))}
        if p == "A":
            e["share_spy_post"] = float((st[st.index >= CUT] == "SPY").mean())
        chs = P[p]["chains"]
        for wn in WINS[p]:
            cs = chain_states(chs[f"{wn}|icw9_seas"], st)
            e[f"chains_{wn}"] = {"share_spy_mean40": float(np.mean([np.mean([x == "SPY" for x in s]) for s, _ in cs])),
                                 "switches_mean40": float(np.mean([sw for _, sw in cs])),
                                 "switches_min_max": [int(min(sw for _, sw in cs)), int(max(sw for _, sw in cs))],
                                 "rebalances_per_chain_mean": float(np.mean([len(s) for s, _ in cs]))}
        out[f"labels_{p}"] = e
        log(f"[{p}] share SPY {e['share_spy_panel_calendar']:.3f}, undefined {len(e['undefined_dates'])}, "
            f"tr/px disagree {e['tr_vs_price_sign_disagree_days']}, large-lead episodes >=40d "
            f"{e['episodes'].get('large_lead', {}).get('runs_ge40d')}; chains full {e['chains_full']}")
    # ---- WO-30 reproduction: price-only S on this parquet vs regime_phase0 size labels (era A), separate process
    code = ("import sys,json,pandas as pd;sys.path.insert(0,%r);import regime_phase0 as RP;"
            "d=[pd.Timestamp(x) for x in json.load(open(%r))['all_dates']];"
            "lab,_=RP.build_labels(d);print(json.dumps({str(k.date()):v for k,v in lab['size'].items()}))"
            % (str(SRC / "regime"), str(PARTS / "A_chains.json")))
    r = subprocess.run([sys.executable, "-c", code], capture_output=True, text=True, cwd=str(SRC / "regime"))
    assert r.returncode == 0, r.stderr[-2000:]
    wo30 = pd.Series(json.loads(r.stdout.strip().splitlines()[-1]))
    wo30.index = pd.to_datetime(wo30.index)
    stp, _ = state_on(S_px, P["A"]["all_dates"])
    mine = stp.map({"SPY": "large_lead", "BOOK": "small_lead", "undef": "undefined"})
    both = (wo30 != "undefined") & (mine != "undefined")
    mism = int((wo30[both] != mine[both]).sum())
    st_tr = lab["A"].map({"SPY": "large_lead", "BOOK": "small_lead", "undef": "undefined"})
    out["wo30_reproduction_A"] = {"n_compared": int(both.sum()), "price_only_mismatch_days": mism,
                                  "wo30_undefined": int((wo30 == "undefined").sum()),
                                  "total_return_vs_wo30_disagree_days": int((st_tr[both] != wo30[both]).sum()),
                                  "wo30_share_large_lead": float((wo30[both] == "large_lead").mean())}
    log(f"WO-30 reproduction: {out['wo30_reproduction_A']}")
    out["reconcile"] = {p: P[p]["reconcile"] for p in "AB"}
    OUT.mkdir(parents=True, exist_ok=True)
    (OUT / "prep.json").write_text(json.dumps(out, indent=2, default=float))
    log(f"wrote {OUT / 'prep.json'}")


# ------------------------------------------------------------------ step 3: run (after pre-reg commit)
def run():
    sys.path.insert(0, str(SRC / "construction"))
    import drag_decomp as DD
    assert DD.ANN == ANN
    g = load_bench()
    S = size_signal(g)
    P = load_parts()
    res = {"work_order": "WO-32", "trial": "size/market-timing family, trial 1", "holdout_read": 12,
           "units": "fractions per year (0.01 = 1%/yr); 40-offset mean of annualised per-rebalance excess vs SPY",
           "switch_cost": SWITCH, "results": {}}
    for p in "AB":
        st, _ = state_on(S, P[p]["all_dates"])
        for wn in WINS[p]:
            for m in MODELS:
                chs = P[p]["chains"][f"{wn}|{m}"]
                ung, gat = [], []
                sw_l, spy_l = [], []
                for c in chs:
                    d = np.array([pd.Timestamp(x) for x in c["date"]])
                    e = np.array(c["exc"], dtype=np.float64)
                    s = np.array(["SPY" if st[x] == "SPY" else "BOOK" for x in d])
                    prev = np.r_[["BOOK"], s[:-1]]
                    swm = s != prev
                    ge = np.where(s == "SPY", 0.0, e) - SWITCH * swm
                    # oracle
                    lhs = (ge.mean() - e.mean())
                    rhs = (-(e[s == "SPY"]).sum() - SWITCH * swm.sum()) / len(e)
                    assert abs(lhs - rhs) < 1e-12, "gate oracle"
                    ung.append({"date": d, "exc": e})
                    gat.append({"date": d, "exc": ge})
                    sw_l.append(int(swm.sum())); spy_l.append(float((s == "SPY").mean()))
                assert all(np.array_equal(a["date"], b["date"]) for a, b in zip(ung, gat))
                po_u, po_g = DD.per_offset(ung), DD.per_offset(gat)
                ys, lu = DD.loyo_vec(ung)
                ys2, lg = DD.loyo_vec(gat)
                assert ys == ys2
                dl = (lg - lu).mean(axis=0)
                diff = po_g - po_u
                r = {"ungated": float(po_u.mean()), "ungated_offsets_pos": int((po_u > 0).sum()),
                     "gated": float(po_g.mean()), "gated_offsets_pos": int((po_g > 0).sum()),
                     "gated_minus_ungated": float(diff.mean()), "diff_sd40": float(diff.std()),
                     "diff_offsets_pos": int((diff > 0).sum()), "diff_min40": float(diff.min()), "diff_max40": float(diff.max()),
                     "diff_loyo_by_dropped_year": {int(y): float(v) for y, v in zip(ys, dl)},
                     "diff_loyo_min": float(dl.min()), "diff_loyo_min_year": int(ys[int(dl.argmin())]),
                     "share_spy_mean40": float(np.mean(spy_l)), "switches_mean40": float(np.mean(sw_l)),
                     "switch_cost_drag_ann": float(np.mean([SWITCH * sw / len(c["exc"]) for sw, c in zip(sw_l, ung)]) * ANN)}
                if p == "B" or wn == "full":
                    py_u, py_g = DD.per_year(ung), DD.per_year(gat)
                    r["per_year"] = {y: {"ungated": py_u[y], "gated": py_g[y], "diff": py_g[y] - py_u[y]} for y in py_u}
                res["results"][f"{p}_{wn}|{m}"] = r
                log(f"[{p} {wn} {m}] ungated {r['ungated']:+.4f} gated {r['gated']:+.4f} diff {r['gated_minus_ungated']:+.4f} "
                    f"({r['diff_offsets_pos']}/40) loyo-min {r['diff_loyo_min']:+.4f} ({r['diff_loyo_min_year']}) "
                    f"SPY share {r['share_spy_mean40']:.3f} switches {r['switches_mean40']:.2f}")
    R = res["results"]
    a, b = R["A_full|icw9_seas"], R["B_full|icw9_seas"]
    chk = {"A_full": a["gated_minus_ungated"], "B": b["gated_minus_ungated"],
           "A_full_drop2008": a["diff_loyo_by_dropped_year"][2008], "B_drop2020": b["diff_loyo_by_dropped_year"][2020]}
    if chk["A_full"] <= 0 or chk["B"] <= 0:
        verdict = "KILL"
    elif chk["A_full_drop2008"] > 0 and chk["B_drop2020"] > 0:
        verdict = "SUCCESS"
    else:
        verdict = "MIDDLE"
    res["decision"] = {"checks": chk, "verdict": verdict}
    log(f"decision {chk} -> {verdict}")
    (OUT / "sizegate.json").write_text(json.dumps(res, indent=2, default=float))
    log(f"wrote {OUT / 'sizegate.json'}")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--chains", choices=["A", "B"])
    ap.add_argument("--prep", action="store_true")
    ap.add_argument("--run", action="store_true")
    a = ap.parse_args()
    if a.chains:
        chains_job(a.chains)
    elif a.prep:
        prep()
    elif a.run:
        run()


if __name__ == "__main__":
    main()
