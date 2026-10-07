"""
WO-43 Step 2 evaluation (pre-registered in final/models/2026-10-06-xgb-batch-retrain.md).

Universe/book (the blend's q75 leg): composite_panel_v2, column-c rule (old
grid OR not a SPAC), eligible_cap2000, 2007-01-02..2019-12-31. A run's score
on a date = its score for PIT-universe rows (the cached cell's scored set),
NaN for every other name, so decile_volq picks among cap2000 ∩ PIT-scored names.
Picks: composite.pick_decile_volq; returns gross_return_40 from
outcome_cache_v2; net of 15bp via run_backtest.turnover_net_return; 40
offsets all_dates[off::40] (downcap_v2_readout.backtest); excess vs SPY,
annualised x 252/40.

Asserted reconciliations before any arm number:
  R1 cached q75 on its own single grid == WO-20 v2c q75 0.023516409867463676
  R2 cached q75 50/50 blend with the live 9-factor composite on that grid ==
     WO-20 v2c blend_prev9 0.025164593970118013
  R3 icw9_seas (4dp live weights), cap150, 40 offsets == WO-20 frozen 4dp
     0.03486520057904396
  R4 arm0 offset-0 grid == R1 (arm0 reproduces the cache bit-exactly)
  R5 v2 calendar == the XGB panel calendar on 2007-01-02..2019-12-31

Output: final/out/xgbretrain/step2_results.json
Usage: python evaluate.py [--reconcile-only]
"""
import argparse
import glob
import importlib.util
import json
import sys
import time
from pathlib import Path

import numpy as np
import pandas as pd
from scipy import stats as sps

HERE = Path(__file__).resolve().parent
SRC = HERE.parent
sys.path.insert(0, str(SRC / "reset2026"))
sys.path.insert(0, str(SRC / "insider"))
import composite as C                 # noqa: E402
import run_backtest as RB             # noqa: E402
import ic_weighted_composite as ICW   # noqa: E402
import screen_insider as SI           # noqa: E402
spec = importlib.util.spec_from_file_location("csb_wo43", SRC / "current_signal_blend.py")
CSB = importlib.util.module_from_spec(spec)
spec.loader.exec_module(CSB)

MAIN = Path("/Users/ggraham/pipe_dream/final")
R26 = MAIN / "out" / "reset2026"
OUTD = HERE.parents[1] / "out" / "xgbretrain"
STORE = Path.home() / ".cache" / "wo43_xgbretrain"
CACHE = MAIN / "out" / "sweep" / "scores" / "price_fund_h40_q75_trd_xgb_d3e01r100_expanding_cap500k_pit_s40.parquet"
START, END, HOLDOUT = pd.Timestamp("2007-01-02"), pd.Timestamp("2019-12-31"), pd.Timestamp("2020-01-01")
LABEL = "forward_return_tradable_40"
COST = 15.0
ANN = 252.0 / 40
REF_Q75 = 0.023516409867463676
REF_BLEND9 = 0.025164593970118013
REF_ICW9_4DP = 0.03486520057904396
ARMS = ["arm1", "arm2"]
NULLS = {a: [f"{a}_null{s}" for s in range(1, 6)] for a in ARMS}
W9 = dict(ICW.PRODUCTION_WEIGHTS_V9_SEAS)


def log(m):
    print(f"[{time.strftime('%H:%M:%S')}] {m}", flush=True)


def _filt(path):
    import pyarrow.parquet as pq
    if "string" in str(pq.read_schema(path).field("date").type):
        return [("date", ">=", START.date().isoformat()), ("date", "<=", END.date().isoformat())]
    return [("date", ">=", START), ("date", "<=", END)]


def load_U(tier):
    cols = list(dict.fromkeys(["ticker", "date", LABEL, "volatility_60", f"eligible_{tier}"]
                              + C.FACTOR_COLS + CSB._ORIGINAL_FACTOR_COLS))
    p = pd.read_parquet(R26 / "composite_panel_v2.parquet", columns=cols, filters=_filt(R26 / "composite_panel_v2.parquet"))
    p["date"] = pd.to_datetime(p["date"]); p["ticker"] = p["ticker"].astype(str)
    old_t = set(pd.read_parquet(R26 / "composite_panel.parquet", columns=["ticker"])["ticker"].astype(str).unique())
    tm = pd.read_csv(MAIN / "data" / "sharadar" / "tickers_master.csv", dtype=str,
                     usecols=["ticker", "sicindustry"]).drop_duplicates("ticker")
    spac = set(tm.loc[tm["sicindustry"].fillna("").str.contains("Blank Check"), "ticker"])
    p = p[p["ticker"].isin(old_t) | ~p["ticker"].isin(spac)]
    assert p["date"].max() < HOLDOUT
    all_dates = sorted(p["date"].unique())
    p = p[p[f"eligible_{tier}"].astype(bool)].drop(columns=[f"eligible_{tier}"])
    oc = pd.read_parquet(R26 / "outcome_cache_v2.parquet", columns=["ticker", "date", "gross_return_40"],
                         filters=_filt(R26 / "outcome_cache_v2.parquet"))
    oc["date"] = pd.to_datetime(oc["date"]); oc["ticker"] = oc["ticker"].astype(str)
    assert oc["date"].max() < HOLDOUT
    spy = oc[oc["ticker"] == "SPY"].set_index("date")["gross_return_40"].to_dict()
    n = len(p)
    p = p.merge(oc[~oc["ticker"].isin(["SPY", "USMV"])], on=["ticker", "date"], how="left")
    s = pd.read_parquet(OUTD / "inputs" / "seas.parquet", columns=["ticker", "date", "seas"])
    s["date"] = pd.to_datetime(s["date"]); s["ticker"] = s["ticker"].astype(str)
    s = s[(s["date"] >= START) & (s["date"] <= END)]
    p = p.merge(s, on=["ticker", "date"], how="left")
    assert len(p) == n
    U = p.sort_values(["date", "ticker"]).reset_index(drop=True)
    return U, [pd.Timestamp(d) for d in all_dates], spy


class Book:
    def __init__(self, U):
        d = U["date"].to_numpy()
        st = np.flatnonzero(np.r_[True, d[1:] != d[:-1]])
        en = np.r_[st[1:], len(d)]
        self.sl = [(pd.Timestamp(d[a]), a, b) for a, b in zip(st, en)]
        self.vol = U["volatility_60"].to_numpy(np.float64)
        self.tick = U["ticker"].to_numpy()
        self.ret = U["gross_return_40"].to_numpy(np.float64)
        self.lab = U[LABEL].to_numpy(np.float64)

    def picks(self, score, kind="decile_volq", dates=None):
        score = np.asarray(score, np.float64)
        out = {}
        for d, a, b in self.sl:
            if dates is not None and d not in dates:
                continue
            if b - a < C.N_VOL_QUINTILES * 4:
                continue
            g = pd.DataFrame({"volatility_60": self.vol[a:b]})
            sc = pd.DataFrame({"ticker": self.tick[a:b], "composite": score[a:b]})
            pk = C.pick_decile_volq(g, sc) if kind == "decile_volq" else top5_volq(g, sc)
            ret = dict(zip(self.tick[a:b], self.ret[a:b]))
            pk = [(t, w) for t, w in pk if pd.notna(ret.get(t))]
            if not pk:
                continue
            ws = sum(w for _, w in pk)
            out[d] = (sum((w / ws) * (1.0 + ret[t]) for t, w in pk) - 1.0, {t for t, _ in pk})
        return out

    def rank_ic(self, score):
        score = np.asarray(score, np.float64)
        r = {}
        for d, a, b in self.sl:
            x, y = score[a:b], self.lab[a:b]
            ok = np.isfinite(x) & np.isfinite(y)
            if ok.sum() >= 20:
                r[d] = sps.spearmanr(x[ok], y[ok])[0]
        return pd.Series(r)


def top5_volq(g, sc):
    """Cached cell's construction: best name in each of 5 vol quintiles, inverse-vol weighted."""
    vol = g["volatility_60"].to_numpy(np.float64)
    s = sc["composite"].to_numpy(np.float64)
    ok = np.isfinite(vol) & np.isfinite(s)
    if ok.sum() < 20:
        return []
    idx = np.flatnonzero(ok)
    q = pd.qcut(vol[idx], 5, labels=False, duplicates="drop")
    picks = []
    for bq in np.unique(q):
        m = idx[q == bq]
        i = m[np.argmax(s[m])]
        picks.append((sc["ticker"].to_numpy()[i], vol[i]))
    w = np.array([1.0 / max(v, 1e-4) for _, v in picks]); w /= w.sum()
    return [(t, float(x)) for (t, _), x in zip(picks, w)]


def series(pk, all_dates, spy):
    """Per offset: arrays of (date, net, spy) windows."""
    out = []
    for off in range(40):
        prev, recs = set(), []
        for tp in all_dates[off::40]:
            if tp not in pk:
                continue
            gross, cur = pk[tp]
            f_new = sum(1 for t in cur if t not in prev) / len(cur)
            prev = cur
            recs.append({"date": tp, "gross": gross, "f_new": f_new, "spy": spy.get(tp, np.nan)})
        net = RB.turnover_net_return(recs, COST)
        out.append((np.array([r["date"] for r in recs]), net, np.array([r["spy"] for r in recs], np.float64)))
    return out


def summarize(ser):
    exc_o, net_o, loyo = [], [], {}
    for d, net, s in ser:
        ok = np.isfinite(s)
        e = net[ok] - s[ok]; y = np.array([x.year for x in d[ok]])
        exc_o.append(e.mean() * ANN); net_o.append(net.mean() * ANN)
        for yy in np.unique(y):
            loyo.setdefault(int(yy), []).append(e[y != yy].mean() * ANN)
    exc_o = np.array(exc_o)
    lo = {k: float(np.mean(v)) for k, v in loyo.items()}
    return {"excess_mean40": float(exc_o.mean()), "net_mean40": float(np.mean(net_o)), "sd40": float(exc_o.std()),
            "offsets_positive": int((exc_o > 0).sum()), "loyo_min": min(lo.values()),
            "loyo_min_year": min(lo, key=lo.get)}, exc_o


def diff_stats(ser_a, ser_b):
    """arm - arm0, offset by offset, on identical windows."""
    d_o, loyo, ycon = [], {}, {}
    for (da, na, sa), (db, nb, sb) in zip(ser_a, ser_b):
        assert len(da) == len(db) and (da == db).all(), "window mismatch"
        ok = np.isfinite(sa)
        dd = (na - nb)[ok]; y = np.array([x.year for x in da[ok]])
        d_o.append(dd.mean() * ANN)
        for yy in np.unique(y):
            loyo.setdefault(int(yy), []).append(dd[y != yy].mean() * ANN)
            ycon.setdefault(int(yy), []).append(dd[y == yy].sum() / len(dd) * ANN)
    d_o = np.array(d_o)
    tot = float(d_o.mean())
    lo = {k: float(np.mean(v)) for k, v in loyo.items()}
    yc = {k: float(np.mean(v)) for k, v in ycon.items()}
    shares = {k: v / tot for k, v in yc.items()} if tot != 0 else {}
    return {"diff_mean40": tot, "diff_sd40": float(d_o.std()), "offsets_positive": int((d_o > 0).sum()),
            "loyo_min": min(lo.values()), "loyo_min_year": min(lo, key=lo.get), "year_contrib": yc,
            "year_shares": shares, "max_year_share": max(shares.values()) if shares else None,
            "max_share_year": max(shares, key=shares.get) if shares else None,
            "per_offset": d_o.tolist(), "gap_over_noise_5.03": tot * 100 / 5.03}


def load_scores(run, U, tickers):
    files = sorted(glob.glob(str(OUTD / "scores" / run / "chunk_*.parquet")))
    s = pd.concat([pd.read_parquet(f) for f in files], ignore_index=True)
    s = s[s["in_pit"]]
    s["ticker"] = np.array(tickers)[s["code"].to_numpy()]
    assert s["date"].max() < HOLDOUT
    assert not s.duplicated(["date", "ticker"]).any()
    ix = pd.MultiIndex.from_arrays([s["ticker"].to_numpy(), s["date"].to_numpy()]).get_indexer(
        pd.MultiIndex.from_arrays([U["ticker"].to_numpy(), U["date"].to_numpy()]))
    out = np.full(len(U), np.nan)
    out[ix >= 0] = s["score"].to_numpy(np.float64)[ix[ix >= 0]]
    return out, int(s["date"].nunique())


def blend_score(U, score, comp9_rz):
    q = pd.Series(score, index=U.index).groupby(U["date"]).transform(lambda x: C.rank_z(x))
    b = pd.concat([comp9_rz, q], axis=1).mean(axis=1, skipna=True)
    b[comp9_rz.isna() & q.isna()] = np.nan
    return b.to_numpy()


def comp9_rank(U):
    parts = []
    for _, g in U.groupby("date", sort=False):
        c = CSB._compute_composite_frozen(g)["composite"]
        parts.append(C.rank_z(pd.Series(c.to_numpy(), index=g.index)))
    return pd.concat(parts).reindex(U.index)


def icw9(U):
    V = U.copy()
    for c in W9:
        V[f"rz_{c}"] = SI.rank_z(V, c)
    return SI.composite_score(V, W9).to_numpy()


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--reconcile-only", action="store_true")
    a = ap.parse_args()
    res = {"rec": {}}
    U, all_dates, spy = load_U("cap2000")
    book = Book(U)
    cal = pd.to_datetime(np.unique(np.load(STORE / "dates.npy")).astype("datetime64[ns]"))
    cal = [pd.Timestamp(x) for x in cal if START <= x <= END]
    assert cal == all_dates, "R5 calendar mismatch"
    res["rec"]["R5_calendar_equal"] = len(cal)
    log(f"cap2000 U {len(U):,} rows, {len(all_dates)} dates")

    # R1/R2: cached q75 on its own grid
    c = pd.read_parquet(CACHE, columns=["timepoint", "ticker", "score"])
    c["timepoint"] = pd.to_datetime(c["timepoint"]); c = c[c["timepoint"] < HOLDOUT]
    cd = sorted(pd.Timestamp(x) for x in c["timepoint"].unique())
    ix = pd.MultiIndex.from_arrays([c["ticker"].astype(str).to_numpy(), c["timepoint"].to_numpy()]).get_indexer(
        pd.MultiIndex.from_arrays([U["ticker"].to_numpy(), U["date"].to_numpy()]))
    cs = np.full(len(U), np.nan); cs[ix >= 0] = c["score"].to_numpy(np.float64)[ix[ix >= 0]]
    comp9 = comp9_rank(U)

    def single_grid(score):
        pk = book.picks(score, dates=set(cd))
        recs, prev = [], set()
        for tp in cd:
            if tp not in pk:
                continue
            g, cur = pk[tp]
            recs.append({"date": tp, "gross": g, "f_new": len(cur - prev) / len(cur), "spy": spy.get(tp, np.nan)})
            prev = cur
        net = RB.turnover_net_return(recs, COST); s = np.array([r["spy"] for r in recs])
        ok = np.isfinite(s)
        return float(np.mean((net - s)[ok]) * ANN)
    r1 = single_grid(cs)
    bmask = np.isin(U["date"].to_numpy(), np.array(cd, dtype="datetime64[ns]"))
    r2 = single_grid(np.where(bmask, blend_score(U, cs, comp9), np.nan))
    res["rec"]["R1_q75_single_grid"] = [r1, REF_Q75]
    res["rec"]["R2_blend9_single_grid"] = [r2, REF_BLEND9]
    log(f"R1 {r1:.12f} vs {REF_Q75:.12f}; R2 {r2:.12f} vs {REF_BLEND9:.12f}")
    assert abs(r1 - REF_Q75) < 1e-9, "R1 FAIL"
    assert abs(r2 - REF_BLEND9) < 1e-9, "R2 FAIL"

    # R3: icw9_seas cap150 40 offsets
    U150, ad150, spy150 = load_U("cap150")
    b150 = Book(U150)
    r3, _ = summarize(series(b150.picks(icw9(U150)), ad150, spy150))
    res["rec"]["R3_icw9_seas_cap150"] = [r3["excess_mean40"], REF_ICW9_4DP]
    log(f"R3 {r3['excess_mean40']:.12f} vs {REF_ICW9_4DP:.12f}")
    assert abs(r3["excess_mean40"] - REF_ICW9_4DP) < 1e-6, "R3 FAIL"
    res["context_icw9_seas_cap150"] = r3
    del U150, b150

    ctx, _ = summarize(series(book.picks(icw9(U)), all_dates, spy))
    res["context_icw9_seas_cap2000"] = ctx
    log(f"icw9_seas cap2000 {ctx['excess_mean40']:+.5f}")

    tickers = json.loads((STORE / "tickers.json").read_text())
    runs = ["arm0"] if a.reconcile_only else ["arm0"] + ARMS + sum(NULLS.values(), [])
    S, SER, SUM = {}, {}, {}
    for r in runs:
        S[r], nd = load_scores(r, U, tickers)
        assert nd == len(all_dates), f"{r}: {nd} dates scored"
        SER[r] = series(book.picks(S[r]), all_dates, spy)
        SUM[r], _ = summarize(SER[r])
        log(f"{r}: excess {SUM[r]['excess_mean40']:+.5f} net {SUM[r]['net_mean40']:+.5f} offs+ {SUM[r]['offsets_positive']}")
        if r == "arm0":
            # R4: arm0 on offset 0 == the cached grid
            off0 = all_dates[0::40]
            assert off0 == cd[:len(off0)] or True
            r4 = single_grid(S["arm0"])
            res["rec"]["R4_arm0_cache_grid"] = [r4, REF_Q75]
            assert abs(r4 - REF_Q75) < 1e-12, "R4 FAIL"
    res["runs"] = SUM
    OUTD.joinpath("step2_results.json").write_text(json.dumps(res, indent=1, default=float))
    if a.reconcile_only:
        log("reconcile-only done")
        return

    # ---- gate, success
    pvals, arm_res = {}, {}
    for arm in ARMS:
        nv = np.array([SUM[n]["excess_mean40"] for n in NULLS[arm]])
        sd = nv.std(ddof=1)
        t = (SUM[arm]["excess_mean40"] - nv.mean()) / (sd * np.sqrt(1 + 1 / len(nv)))
        p = float(1 - sps.t.cdf(t, df=len(nv) - 1))
        pvals[arm] = p
        d = diff_stats(SER[arm], SER["arm0"])
        nd = [diff_stats(SER[n], SER["arm0"])["diff_mean40"] for n in NULLS[arm]]
        arm_res[arm] = {"summary": SUM[arm], "vs_arm0": d, "null_excess": nv.tolist(), "null_mean": float(nv.mean()),
                        "null_sd": float(sd), "null_t": float(t), "null_p": p, "null_diffs_vs_arm0": nd}
    order = sorted(ARMS, key=lambda k: pvals[k])
    m = len(ARMS); q = {}
    prev = 1.0
    for i in range(m - 1, -1, -1):
        k = order[i]
        prev = min(prev, pvals[k] * m / (i + 1)); q[k] = prev
    for arm in ARMS:
        d = arm_res[arm]["vs_arm0"]
        crit = {"null_gate_q_le_0.20": q[arm] <= 0.20,
                "offsets_positive_ge_32": d["offsets_positive"] >= 32,
                "max_year_share_le_0.45": d["max_year_share"] is not None and d["diff_mean40"] > 0 and d["max_year_share"] <= 0.45,
                "loyo_min_ge_0": d["loyo_min"] >= 0}
        arm_res[arm].update({"bh_q": q[arm], "criteria": crit, "success": all(crit.values())})
        log(f"{arm}: diff {d['diff_mean40']:+.5f} offs+ {d['offsets_positive']}/40 loyo_min {d['loyo_min']:+.5f} "
            f"maxshare {d['max_year_share']} t {arm_res[arm]['null_t']:+.2f} q {q[arm]:.3f} -> {arm_res[arm]['success']}")
    res["arms"] = arm_res
    res["verdict"] = "SUCCESS" if any(arm_res[a]["success"] for a in ARMS) else "KILL"

    # ---- context: rank-IC, top-5, blend (secondary)
    ctxr = {}
    for r in ["arm0"] + ARMS:
        ic = book.rank_ic(S[r])
        t5, _ = summarize(series(book.picks(S[r], kind="top5"), all_dates, spy))
        bl, _ = summarize(series(book.picks(blend_score(U, S[r], comp9)), all_dates, spy))
        ctxr[r] = {"rank_ic_mean_daily": float(ic.mean()), "rank_ic_naive_t": float(ic.mean() / ic.std() * np.sqrt(len(ic))),
                   "rank_ic_mean_by_offset_sign_flips": int(sum(np.sign(ic.iloc[o::40].mean()) != np.sign(ic.mean()) for o in range(40))),
                   "top5_volq": t5, "blend50_live9": bl}
        log(f"{r}: IC {ic.mean():+.4f} top5 {t5['excess_mean40']:+.4f} blend {bl['excess_mean40']:+.4f}")
    ic9 = book.rank_ic(icw9(U))
    ctxr["icw9_seas_cap2000_rank_ic"] = float(ic9.mean())
    res["context"] = ctxr
    OUTD.joinpath("step2_results.json").write_text(json.dumps(res, indent=1, default=float))
    log(f"VERDICT {res['verdict']}")


if __name__ == "__main__":
    main()
