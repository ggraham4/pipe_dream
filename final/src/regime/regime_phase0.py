"""
WO-30 Phase 0 (COO, 2026-09-30): does the live model's stock SELECTION depend
on market regime, or only the POOL's return? Descriptive, no trial counted.
Pre-registration (definitions + decision map, committed before Step 3 ran):
final/models/2026-09-30-regime-gate.md.

Harness = WO-21 drag_decomp / WO-20 frozen backtest: v2 col c, cap150, h=40,
decile_volq, 40 offsets, net 15 bp, label close[t+40]/open[t+1].
Books: icw8 (ICW.PRODUCTION_WEIGHTS), icw9_seas (ICW.PRODUCTION_WEIGHTS_V9_SEAS,
frozen 4dp), pool = WO-7 no-score cap150 book (drag_decomp.noscore_picks),
random = score shuffled within date, seeds 2000..2004 (secondary only).

  book vs SPY = pool vs SPY + selection over pool,  selection = book_net - pool_net
  (identity exact per window; same (offset, date) windows in both books).

Regime labels at rebalance date t use SPY/IWM prices dated <= t only.
IN-ERA ONLY: every loaded frame asserts max(date) < 2020-01-01. No HMM.

Usage:
  python regime_phase0.py --prereg   Step 1 reconcile + regime labels + n/episodes (no performance by state)
  python regime_phase0.py            full (Steps 1-3 + decision map)
Output: final/out/regime/regime_phase0_prereg.json | regime_phase0.json (this worktree)
"""
import argparse
import hashlib
import json
import sys
import time
from pathlib import Path

import numpy as np
import pandas as pd

SRC = Path(__file__).resolve().parents[1]
for sub in ("construction", "seasonality", "insider", "reset2026"):
    sys.path.insert(0, str(SRC / sub))
import screen_seas as S                 # noqa: E402
import drag_decomp as DD                # noqa: E402

V, SI, ICW, DR, HC, RB = S.V, S.SI, S.ICW, S.DR, DD.HC, DD.RB

MAIN = Path("/Users/ggraham/pipe_dream/final")
OUT_DIR = Path(__file__).resolve().parents[2] / "out" / "regime"
SPY_CSV = MAIN / "scripts" / "td_data_local" / "SPY.csv"
# seas factor (gitignored build output) read from the WO-18 worktree; sha256 recorded + icw9 reconcile asserted
SEAS_DIR = Path("/Users/ggraham/pipe_dream/.claude/worktrees/agent-ad57ef9f38454d99d/final/out/seasonality")
HOLDOUT = pd.Timestamp("2020-01-01")
ANN = 252.0 / RB.HORIZON
SEEDS = [2000 + k for k in range(5)]
REF = {"icw8": 0.0285416, "icw8_exact": 0.028541632641009042,
       "icw9_seas": 0.03486520057904396, "noscore": -0.00248503454823125}
TOL = 1e-6
EP_MIN = 40            # decision episode = contiguous run of >= 40 trading days (one holding horizon)
TREND_UP, TREND_DN = 0.10, -0.10   # old regime_backtest.py thresholds
VOL_WIN, VOL_MINP, MED_MINP = 60, 30, 252
LOOKBACK = 252
log = V.log


def hold(ts, what):
    assert pd.Timestamp(ts) < HOLDOUT, f"HOLD-OUT BREACH ({what}): {ts}"


def sha256(p):
    h = hashlib.sha256()
    with open(p, "rb") as f:
        for b in iter(lambda: f.read(1 << 20), b""):
            h.update(b)
    return h.hexdigest()


# ---------------------------------------------------------------- regimes
def load_spy_daily():
    d = pd.read_csv(SPY_CSV, usecols=["date", "close"], parse_dates=["date"])
    d = d[d["date"] < HOLDOUT].sort_values("date").reset_index(drop=True)
    hold(d["date"].max(), "spy daily")
    return d.set_index("date")["close"].astype(np.float64)


def load_iwm_daily():
    d = HC.load_iwm()                      # guard()s < 2020-01-01
    hold(d["date"].max(), "iwm daily")
    return d.set_index("date")["close"].astype(np.float64)


def build_labels(all_dates):
    """Daily regime labels on the panel calendar. PIT: every quantity on date t
    uses closes dated <= t (trailing windows, expanding median). 'undefined'
    during warm-up (never defaulted)."""
    spy = load_spy_daily()
    iwm = load_iwm_daily()
    # R1 trend (PIT replica of old Regime A): trailing 252-trading-day SPY return
    r252 = spy / spy.shift(LOOKBACK) - 1.0
    trend = pd.Series(np.where(r252 > TREND_UP, "up", np.where(r252 < TREND_DN, "down", "flat")), index=spy.index)
    trend[r252.isna()] = "undefined"
    # R2 vol (old Regime B, already causal): 60d realized vol vs expanding median (min 252 obs)
    ret = spy.pct_change()
    rv = ret.rolling(VOL_WIN, min_periods=VOL_MINP).std() * np.sqrt(252)
    med = rv.expanding(min_periods=MED_MINP).median()
    vol = pd.Series(np.where(rv > med, "high", "low"), index=spy.index)
    vol[rv.isna() | med.isna()] = "undefined"
    # R3 size: sign of trailing 252d IWM return - SPY return (price-only closes, common dates)
    j = pd.concat([spy.rename("spy"), iwm.rename("iwm")], axis=1, join="inner")
    rel = (j["iwm"] / j["iwm"].shift(LOOKBACK) - 1.0) - (j["spy"] / j["spy"].shift(LOOKBACK) - 1.0)
    size = pd.Series(np.where(rel > 0, "small_lead", "large_lead"), index=j.index)
    size[rel.isna()] = "undefined"
    # reference only (NOT PIT, not in decision): old Regime A, SPY's own calendar-year return
    yr = spy.groupby(spy.index.year).agg(lambda s: s.iloc[-1] / s.iloc[0] - 1.0)
    cal = pd.Series([("up" if yr[y] > TREND_UP else "down" if yr[y] < TREND_DN else "flat") for y in spy.index.year],
                    index=spy.index)
    idx = pd.DatetimeIndex(all_dates)
    out, diag = {}, {}
    for name, s in (("trend_pit", trend), ("vol", vol), ("size", size), ("calyear_ref_nonpit", cal)):
        s = s.sort_index()
        hold(s.index.max(), name)
        pos = s.index.searchsorted(idx, side="right") - 1          # as-of <= t
        assert (pos >= 0).all(), f"{name}: panel date before first price"
        src = s.index[pos]
        lag = (idx - src).days
        assert (np.asarray(src) <= np.asarray(idx)).all()
        lab = pd.Series(s.to_numpy()[pos], index=idx)
        lab[lag > 5] = "undefined"
        und = lab == "undefined"
        # undefined only in the warm-up at the start of the era
        u = und.to_numpy()
        assert (u == (np.arange(len(u)) < u.sum())).all(), f"{name}: undefined outside the start-of-era warm-up"
        if u.any():
            assert lab.index[u].max() < pd.Timestamp("2007-07-01"), f"{name}: warm-up too long"
        out[name] = lab
        diag[name] = {"first_defined": str(lab.index[~und].min().date()), "n_undefined_days": int(und.sum()),
                      "max_asof_lag_days": int(lag.max())}
    return out, diag


def episodes(lab):
    v = lab.to_numpy()
    starts = np.flatnonzero(np.r_[True, v[1:] != v[:-1]])
    ends = np.r_[starts[1:], len(v)]
    res = {}
    for s, e in zip(starts, ends):
        st = v[s]
        if st == "undefined":
            continue
        r = res.setdefault(st, {"raw": 0, f"ge{EP_MIN}d": 0, "runs_ge": []})
        r["raw"] += 1
        if e - s >= EP_MIN:
            r[f"ge{EP_MIN}d"] += 1
            r["runs_ge"].append([str(lab.index[s].date()), str(lab.index[e - 1].date()), int(e - s)])
    for st, r in res.items():
        r["days"] = int((v == st).sum())
    return res


# ---------------------------------------------------------------- windows
def chain_frame(pk, all_dates, spy):
    rows = []
    for off, c in enumerate(DD.chains(pk, all_dates, spy, DR.COST_BPS)):
        rows.append(pd.DataFrame({"offset": off, "date": pd.DatetimeIndex(c["date"]), "exc": c["exc"]}))
    return pd.concat(rows, ignore_index=True)


def state_stats(W, lab, states):
    """W: per (offset, date) window frame with columns book, pool, sel, [rand].
    Per-state: per-offset in-state mean x ANN, then mean over offsets with windows."""
    W = W.assign(state=lab.reindex(W["date"]).to_numpy(), year=W["date"].dt.year)
    res = {}
    for st in states:
        g = W[W["state"] == st]
        r = {"n_windows": int(len(g)), "n_dates": int(g["date"].nunique()),
             "years": sorted(int(y) for y in g["year"].unique())}
        if len(g) == 0:
            res[st] = r
            continue
        po = g.groupby("offset")[["book", "pool", "sel"] + (["rand"] if "rand" in g else [])].mean() * ANN
        po = po.reindex(range(40))
        r["offsets_with_windows"] = int(po["sel"].notna().sum())
        r["book_vs_spy"] = float(po["book"].mean())
        r["pool_vs_spy"] = float(po["pool"].mean())
        r["selection"] = float(po["sel"].mean())
        r["sel_offsets_positive"] = int((po["sel"] > 0).sum())      # out of 40 (no-window offsets count as neither)
        r["sel_offsets_negative"] = int((po["sel"] < 0).sum())
        r["sel_sd40"] = float(po["sel"].std(ddof=0))
        if "rand" in po:
            r["random_vs_spy"] = float(po["rand"].mean())
            r["selection_vs_random"] = float((po["book"] - po["rand"]).mean())
            r["selvr_offsets_positive"] = int(((po["book"] - po["rand"]) > 0).sum())
            r["selvr_offsets_negative"] = int(((po["book"] - po["rand"]) < 0).sum())

        def drop(y):
            h = g[g["year"] != y]
            if len(h) == 0:
                return np.nan, np.nan, 0
            q = (h.groupby("offset")[["sel"] + (["book", "rand"] if "rand" in h else [])].mean() * ANN).reindex(range(40))
            vr = float((q["book"] - q["rand"]).mean()) if "rand" in q else np.nan
            return float(q["sel"].mean()), vr, int((q["sel"] < 0).sum())

        loyo = {y: drop(y) for y in r["years"]}
        if len(r["years"]) < 2:
            r["sel_loyo_min"], r["sel_loyo_min_dropped_year"] = float("nan"), None
            r["selvr_loyo_min"] = float("nan")
        else:
            ymin = min(loyo, key=lambda y: loyo[y][0])
            r["sel_loyo_min"], r["sel_loyo_min_dropped_year"] = loyo[ymin][0], int(ymin)
            r["selvr_loyo_min"] = float(np.nanmin([v[1] for v in loyo.values()]))
        d08 = drop(2008)
        r["sel_drop2008"], r["selvr_drop2008"], r["sel_drop2008_offsets_negative"] = d08
        res[st] = r
    return res


# ---------------------------------------------------------------- decision map
def decide(tables, ep, ep_key):
    per_model = {}
    for m, defs in tables.items():
        a_ok, b_hits = True, []
        for dname, st in defs.items():
            if dname == "calyear_ref_nonpit":
                continue
            for s, r in st.items():
                if r["n_windows"] == 0:
                    continue
                if not (r["selection"] > 0 and r["sel_offsets_positive"] >= 30):
                    a_ok = False
                if (r["selection"] < 0 and r["sel_offsets_negative"] >= 30
                        and ep[dname].get(s, {}).get(ep_key, 0) >= 3
                        and np.isfinite(r["sel_drop2008"]) and r["sel_drop2008"] < 0):
                    b_hits.append(f"{dname}:{s}")
        per_model[m] = {"A_all_states_positive": a_ok, "B_hits": b_hits}
    if any(v["B_hits"] for v in per_model.values()):
        out = "B"
    elif all(v["A_all_states_positive"] for v in per_model.values()):
        out = "A"
    else:
        out = "C"
    return {"per_model": per_model, "outcome": out}


def decide_secondary(tables, ep, ep_key):
    """Same map, selection measured vs the random (5-seed) book instead of the pool."""
    t2 = {m: {d: {s: {**r, "selection": r.get("selection_vs_random", np.nan),
                      "sel_offsets_positive": r.get("selvr_offsets_positive", 0),
                      "sel_offsets_negative": r.get("selvr_offsets_negative", 0),
                      "sel_drop2008": r.get("selvr_drop2008", np.nan)} for s, r in st.items()}
              for d, st in defs.items()} for m, defs in tables.items()}
    return decide(t2, ep, ep_key)


# ---------------------------------------------------------------- main
def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--prereg", action="store_true")
    args = ap.parse_args()
    T0 = time.time()
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    S.B.OUT = SEAS_DIR                                   # read-only: seas_factor_v2.parquet
    seas_pq = SEAS_DIR / "seas_factor_v2.parquet"
    U, all_dates, spy = S.load_universe()
    hold(U["date"].max(), "universe"); hold(spy.index.max(), "spy40"); hold(max(all_dates), "calendar")
    V.add_ranks(U, V.FC8 + ["seas"])
    book = V.Book(U, all_dates, spy)
    log(f"universe {len(U):,} rows ({time.time()-T0:.0f}s)")

    scores = {"icw8": SI.composite_score(U, ICW.PRODUCTION_WEIGHTS).to_numpy(),
              "icw9_seas": SI.composite_score(U, ICW.PRODUCTION_WEIGHTS_V9_SEAS).to_numpy()}
    pk = {m: book.picks(s) for m, s in scores.items()}
    pk["pool"] = DD.noscore_picks(book)
    for v in pk.values():
        hold(max(v), "picks")

    # ---- Step 1 reconcile (hard asserts, before any regime split)
    rec = {m: DR.backtest(pk[m], all_dates, spy)["excess_cagr_vs_spy_mean40"] for m in pk}
    checks = {"icw8_vs_wo21_0.0285416": abs(rec["icw8"] - REF["icw8"]) < TOL,
              "icw8_exact_1e-9": abs(rec["icw8"] - REF["icw8_exact"]) < 1e-9,
              "icw9_seas_vs_wo20": abs(rec["icw9_seas"] - REF["icw9_seas"]) < 1e-9,
              "pool_vs_wo21_noscore": abs(rec["pool"] - REF["noscore"]) < 1e-9}
    for k, v in checks.items():
        log(f"  reconcile {k}: {'OK' if v else 'FAIL'}")
    log(f"icw8 {rec['icw8']:+.7f}  icw9_seas {rec['icw9_seas']:+.7f}  pool {rec['pool']:+.9f}")
    assert all(checks.values()), f"RECONCILE FAIL {rec}"

    labels, ldiag = build_labels(all_dates)
    ep = {n: episodes(l) for n, l in labels.items()}
    states = {"trend_pit": ["up", "flat", "down"], "vol": ["high", "low"],
              "size": ["small_lead", "large_lead"], "calyear_ref_nonpit": ["up", "flat", "down"]}

    # windows on full-calendar chains, tagged by state at t
    fr = {m: chain_frame(pk[m], all_dates, spy) for m in ("icw8", "icw9_seas", "pool")}
    for m in fr:   # oracle: chain mean == DR.backtest
        assert abs((fr[m].groupby("offset")["exc"].mean() * ANN).mean() - rec[m]) < 1e-12, m
    key = lambda f: set(zip(f["offset"], f["date"]))
    assert key(fr["icw8"]) == key(fr["pool"]) == key(fr["icw9_seas"]), "window sets differ"
    hold(fr["pool"]["date"].max(), "windows")
    n_tot = len(fr["pool"])
    counts = {}
    for n, l in labels.items():
        st = l.reindex(fr["pool"]["date"]).to_numpy()
        c = pd.Series(st).value_counts().to_dict()
        assert sum(c.values()) == n_tot and set(c) <= set(states[n]) | {"undefined"}
        counts[n] = {k: int(v) for k, v in c.items()}

    out = {"work_order": "WO-30 Phase 0", "prereg": "final/models/2026-09-30-regime-gate.md",
           "era": "2007-01-02..2019-12-31 (rebalance dates)", "cost_bps": DR.COST_BPS,
           "seas_parquet": {"path": str(seas_pq), "sha256": sha256(seas_pq)},
           "reconcile": {"values": rec, "refs": REF, "checks": checks},
           "labels": ldiag, "windows_total": n_tot, "window_counts_by_state": counts,
           "episodes": {n: {s: {k: v for k, v in r.items() if k != "runs_ge"} for s, r in e.items()} for n, e in ep.items()},
           "episode_runs_ge40d": {n: {s: r["runs_ge"] for s, r in e.items()} for n, e in ep.items()}}
    if args.prereg:
        p = OUT_DIR / "regime_phase0_prereg.json"
        p.write_text(json.dumps(out, indent=1, default=float))
        log(f"wrote {p} ({time.time()-T0:.0f}s)")
        return

    # ---- Step 3 (only after the pre-reg commit)
    rnd = {}
    for m in ("icw8", "icw9_seas"):
        fs = []
        for sd in SEEDS:
            f = chain_frame(book.picks(V.shuffle_within_date(U.assign(_s=scores[m]), "_s", sd)), all_dates, spy)
            fs.append(f.set_index(["offset", "date"])["exc"])
        rnd[m] = pd.concat(fs, axis=1).mean(axis=1)       # mean over seeds where present
        log(f"random {m} done ({time.time()-T0:.0f}s)")
    tables, overall = {}, {}
    for m in ("icw8", "icw9_seas"):
        W = fr[m].rename(columns={"exc": "book"}).merge(fr["pool"].rename(columns={"exc": "pool"}),
                                                          on=["offset", "date"], validate="1:1")
        W["sel"] = W["book"] - W["pool"]
        W["rand"] = rnd[m].reindex(pd.MultiIndex.from_frame(W[["offset", "date"]])).to_numpy()
        allst = pd.Series("all", index=pd.DatetimeIndex(sorted(W["date"].unique())))
        overall[m] = state_stats(W, allst, ["all"])["all"]
        tables[m] = {n: state_stats(W, labels[n], states[n]) for n in states}
        for n in states:
            for s, r in tables[m][n].items():
                if r["n_windows"]:
                    log(f"{m:9s} {n:18s} {s:10s} n={r['n_windows']:5d} book {r['book_vs_spy']*100:+6.2f} "
                        f"pool {r['pool_vs_spy']*100:+6.2f} sel {r['selection']*100:+6.2f} "
                        f"+{r['sel_offsets_positive']}/-{r['sel_offsets_negative']} loyo {r['sel_loyo_min']*100:+.2f} "
                        f"d08 {r['sel_drop2008']*100:+.2f} | vs rnd {r['selection_vs_random']*100:+.2f}")
    assert abs(overall["icw8"]["book_vs_spy"] - rec["icw8"]) < 1e-12
    dec = {"primary_ge40d_episodes": decide(tables, ep, f"ge{EP_MIN}d"),
           "raw_episodes": decide(tables, ep, "raw"),
           "secondary_vs_random_ge40d": decide_secondary(tables, ep, f"ge{EP_MIN}d")}
    dec["outcome"] = dec["primary_ge40d_episodes"]["outcome"]
    dec["episode_rule_flips_outcome"] = dec["raw_episodes"]["outcome"] != dec["outcome"]
    dec["secondary_flips_outcome"] = dec["secondary_vs_random_ge40d"]["outcome"] != dec["outcome"]
    out.update({"overall": overall, "tables": tables, "decision": dec, "runtime_s": time.time() - T0})
    p = OUT_DIR / "regime_phase0.json"
    p.write_text(json.dumps(out, indent=1, default=float))
    log(f"decision {dec['outcome']} (raw-episode {dec['raw_episodes']['outcome']}, "
        f"vs-random {dec['secondary_vs_random_ge40d']['outcome']}); wrote {p} ({time.time()-T0:.0f}s)")


if __name__ == "__main__":
    main()
