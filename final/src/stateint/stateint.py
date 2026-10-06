"""
WO-46 (COO; Gabe's idea 2026-10-02): per-stock state labels as factor
interactions. Zero-fit. Pre-registration: final/models/2026-10-02-state-interactions.md
(committed before any state-conditional number).

States (data <= t, own SEP bars, split-adjusted `close`):
  hi52  = close[t] / max(close[t-251..t])          (252 bars incl. t)
  vol60 = std(daily close-to-close returns, last 60 returns, ddof=1)
State quintile: within date, ordinal rank among finite values (ties broken by
ticker order), q = floor(pos*5/n); Q1 = lowest, Q5 = highest. NaN -> no quintile.

Era 2007-01-02..2019-12-31 ONLY. Nothing dated >= 2020-01-01 is read from SEP
or the panel; labels of late-2019 rebalance dates come from outcome_cache_v2 as
in every prior screen (WO-13 ruling).

Harness (read-only imports): model_audit_wo23.load_theo, screen_insider_v2grid
(Book, shuffle_within_date, ic_gates, gate6, reconcile), screen_insider
(rank_z, composite_score), composite.pick_decile_volq (oracle),
pool_read.picks_w, drag_decomp (chains, per_offset), trailfilter (chains2,
picks_fullsize, cash_fill, diff_stats), run_backtest.turnover_net_return.
fast_pick() below is pick_decile_volq + Book.picks arithmetic on numpy slices
(same pd.qcut and argsort calls); it is hard-asserted equal to Book.picks.

Usage (python = /opt/anaconda3/envs/pipe_dream/bin/python, under caffeinate -i):
  stateint.py --prep            states, PIT/AAPL/dead-name checks, overlap with panel
                                columns, book reconcile, picker oracle. No state-conditional number.
  stateint.py --run             real cells + book rule         -> parts/real.json
  stateint.py --null N [--procs P]   shuffled-state draws      -> parts/null/draw_XXX.json
  stateint.py --hi52            test 3 (DROPPED by the 2026-10-06 amendment; not run)
  stateint.py --aggregate       -> state_interactions_report.json
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
OUT = FINAL / "out" / "stateint"
PARTS = OUT / "parts"
NULLD = PARTS / "null"
CACHE = OUT / "cache"
MAIN = Path("/Users/ggraham/pipe_dream/final")
SEP_DIR = MAIN / "data" / "sharadar" / "panel" / "stocks"
TM = MAIN / "data" / "sharadar" / "tickers_master.csv"
POOL_READ = FINAL / "out" / "pool" / "pool_hedge_read.json"
HOLDOUT = pd.Timestamp("2020-01-01")
HI = pd.Timestamp("2019-12-31")
ANN = 252.0 / 40
W_HI, W_VOL = 252, 60
STATES = {"a_hi52": "hi52", "b_vol60": "vol60"}
SEED_OFF = {"a_hi52": 0, "b_vol60": 1000}
REF_ICW9, REF_ICW8 = 0.0348652, 0.0285416
N_OFF_MIN, YEAR_SHARE_MAX = 32, 0.45
SELF_CELLS = {("pct_from_high_252", "a_hi52"), ("volatility_60", "b_vol60")}
for d in ("audit", "construction", "pool", "trailfilter", "reset2026", "insider", "seasonality"):
    sys.path.insert(0, str(SRC / d))

G = {}      # process-global data (shared with forked null workers)


def log(m):
    print(f"[{time.strftime('%H:%M:%S')}] {m}", flush=True)


# ------------------------------------------------------------------ states
def load_close(tickers):
    files = sorted(f for f in SEP_DIR.glob("*.parquet") if f.stem <= "2019-12")
    tl = sorted(tickers)
    px = pd.concat([pd.read_parquet(f, columns=["ticker", "date", "close"], filters=[("ticker", "in", tl)])
                    for f in files], ignore_index=True)
    px["date"] = pd.to_datetime(px["date"])
    px["ticker"] = px["ticker"].astype(str)
    px = px[px["date"] <= HI]
    px = px.drop_duplicates(["ticker", "date"]).sort_values(["ticker", "date"]).reset_index(drop=True)
    assert px["date"].max() < HOLDOUT, "HOLD-OUT BREACH (SEP)"
    return px


def build_states(px):
    g = px.groupby("ticker", sort=False)["close"]
    mx = g.rolling(W_HI, min_periods=W_HI).max().reset_index(level=0, drop=True)
    px["hi52"] = px["close"] / mx
    r = px["close"] / g.shift(1) - 1.0
    px["vol60"] = r.groupby(px["ticker"], sort=False).rolling(W_VOL, min_periods=W_VOL).std().reset_index(level=0, drop=True)
    return px


def pit_check(px, n=400):
    """Truncate each sampled name's series at t and recompute both states from
    scratch; then rescale every bar after t (fake future split) -> unchanged."""
    rng = np.random.default_rng(46)
    ok = np.flatnonzero(np.isfinite(px["hi52"].to_numpy()) & np.isfinite(px["vol60"].to_numpy()))
    samp = rng.choice(ok, size=n, replace=False)
    tk = px["ticker"].to_numpy(); ca = px["close"].to_numpy(np.float64)
    h, v = px["hi52"].to_numpy(), px["vol60"].to_numpy()
    first = pd.Series(np.arange(len(px))).groupby(tk, sort=False).min()
    mh = mv = 0.0
    for i in samp:
        s0 = int(first.loc[tk[i]])
        sub = ca[s0:i + 1]                       # nothing after t
        assert len(sub) >= W_HI
        a = sub[-1] / sub[-W_HI:].max()
        rr = sub[-(W_VOL + 1):]
        b = np.std(rr[1:] / rr[:-1] - 1.0, ddof=1)
        mh, mv = max(mh, abs(a - h[i])), max(mv, abs(b - v[i]))
    assert mh < 1e-9 and mv < 1e-9, f"PIT FAIL hi52 {mh} vol60 {mv}"
    # future bars rescaled: recompute the whole table on a copy whose bars after a cut date are x7
    cut = pd.Timestamp("2013-06-28")
    p2 = px[["ticker", "date", "close"]].copy()
    p2.loc[p2["date"] > cut, "close"] *= 7.0
    p2 = build_states(p2)
    m = (px["date"] <= cut).to_numpy()
    for c in ("hi52", "vol60"):
        x, y = px[c].to_numpy()[m], p2[c].to_numpy()[m]
        assert ((x == y) | (np.isnan(x) & np.isnan(y))).all(), f"PIT FAIL future rescale {c}"
    return {"n_sampled": n, "max_abs_diff_hi52": float(mh), "max_abs_diff_vol60": float(mv), "tol": 1e-9,
            "future_bars_x7_after_2013-06-28_changes_any_state_on_or_before": False,
            "rows_checked_future_rescale": int(m.sum())}


def named_check(px):
    """AAPL: closing high 702.10 on 2012-09-19, close 390.53 on 2013-04-19 (pre-split
    prices, public record) -> hi52 = 0.5562. 2014-06-09 (first day after the 7:1 split)
    was a new closing high -> hi52 = 1.0, not 1/7."""
    a = px[px["ticker"] == "AAPL"].set_index("date")
    r1 = float(a.loc[pd.Timestamp("2013-04-19"), "hi52"])
    r2 = float(a.loc[pd.Timestamp("2014-06-09"), "hi52"])
    w = a.loc[pd.Timestamp("2012-04-20"):pd.Timestamp("2013-04-19"), "close"]
    res = {"AAPL_2013-04-19_hi52": r1, "expected_390.53/702.10": 390.53 / 702.10,
           "window_max_close_date": str(w.idxmax().date()), "window_max_close_x28": float(w.max() * 28),
           "close_2013-04-19_x28": float(a.loc[pd.Timestamp("2013-04-19"), "close"] * 28),
           "AAPL_2014-06-09_hi52": r2}
    assert abs(r1 - 390.53 / 702.10) < 0.003, res
    assert str(w.idxmax().date()) == "2012-09-19", res
    assert r2 > 0.99, res
    return res


def quintile(dcode, v):
    """Within-date ordinal quintile (0..4) of finite v; ties by row (ticker) order; -1 if NaN."""
    q = np.full(len(v), -1, dtype=np.int8)
    idx = np.flatnonzero(np.isfinite(v))
    order = idx[np.lexsort((idx, v[idx], dcode[idx]))]
    dc = dcode[order]
    st = np.flatnonzero(np.r_[True, dc[1:] != dc[:-1]])
    n = np.diff(np.r_[st, len(dc)])
    pos = np.arange(len(dc)) - np.repeat(st, n)
    q[order] = (pos * 5 // np.repeat(n, n)).astype(np.int8)
    return q


# ------------------------------------------------------------------ picker
def fast_pick(vol, comp, ret, code, both=True):
    """composite.pick_decile_volq (top book_frac=0.10 within vol quintile, inverse-vol
    weights) + Book.picks (drop NaN-return picks, renormalise) on one date's arrays.
    Returns [(gross, frozenset(codes))] for the top leg and, if both, the bottom leg
    (= the same call on -comp). None where the harness would skip the date."""
    if len(vol) < 20:
        return (None, None)
    valid = np.isfinite(vol) & np.isfinite(comp)
    if valid.sum() < 20:
        return (None, None)
    idx = np.flatnonzero(valid)
    vol_v, comp_v, ret_v, code_v = vol[idx], comp[idx], ret[idx], code[idx]
    q = pd.qcut(vol_v, 5, labels=False, duplicates="drop")
    buckets = [np.flatnonzero(q == b) for b in np.unique(q)]
    out = []
    for sgn in ((1.0, -1.0) if both else (1.0,)):
        cs = comp_v if sgn > 0 else -comp_v
        sel = np.concatenate([b[np.argsort(-cs[b])][:max(1, int(round(len(b) * 0.10)))] for b in buckets])
        inv = 1.0 / np.maximum(vol_v[sel], 1e-4)
        w = inv / inv.sum()
        r = ret_v[sel]
        k = np.isfinite(r)
        if not k.any():
            out.append(None)
            continue
        w = w[k] / w[k].sum()
        out.append((float((w * (1.0 + r[k])).sum() - 1.0), frozenset(code_v[sel][k].tolist())))
    return tuple(out) if both else (out[0], None)


def cell_books(mask, fcols):
    """{factor: (pk_top, pk_bot)} for the rows in mask (None = all rows)."""
    vol, ret, code, sl = G["vol"], G["ret"], G["code"], G["sl"]
    res = {f: ({}, {}) for f in fcols}
    for d, s, e in sl:
        if mask is None:
            m = slice(s, e)
        else:
            m = s + np.flatnonzero(mask[s:e])
            if len(m) < 20:
                continue
        v, r, c = vol[m], ret[m], code[m]
        for f in fcols:
            t, b = fast_pick(v, G["S"][f][m], r, c)
            if t is not None:
                res[f][0][d] = t
            if b is not None:
                res[f][1][d] = b
    return res


def ls_chain(pk_t, pk_b, dates_keep=None):
    """Long-short net per window, per offset. LS = net_top - gross_bot - cost_bot
    = net_top + net_bot - 2*gross_bot (15bp turnover cost charged on both legs)."""
    TF, RB, cost = G["TF"], G["RB"], G["cost"]
    common = set(pk_t) & set(pk_b)
    if dates_keep is not None:
        common &= dates_keep
    a = TF.chains2({d: pk_t[d] for d in common}, G["all_dates"], G["spy"], cost, RB)
    b = TF.chains2({d: pk_b[d] for d in common}, G["all_dates"], G["spy"], cost, RB)
    out = []
    for x, y in zip(a, b):
        assert np.array_equal(x["date"], y["date"])
        out.append({"date": x["date"], "ls": x["net"] + y["net"] - 2.0 * y["gross"],
                    "top_net": x["net"], "bot_net": y["net"]})
    return out


def off_mean(ch, key="ls"):
    return np.array([c[key].mean() * ANN for c in ch])


def spread_stats(books5, books1, full=True):
    """S = LS(Q5) - LS(Q1) on the dates where all four legs exist."""
    common = set(books5[0]) & set(books5[1]) & set(books1[0]) & set(books1[1])
    c5, c1 = ls_chain(*books5, dates_keep=common), ls_chain(*books1, dates_keep=common)
    assert all(np.array_equal(x["date"], y["date"]) for x, y in zip(c5, c1))
    d = [x["ls"] - y["ls"] for x, y in zip(c5, c1)]
    po = np.array([v.mean() * ANN for v in d])
    r = {"S": float(po.mean()), "S_per_offset": po.tolist()}
    if not full:
        return r
    sg = np.sign(r["S"])
    yrs = [np.array([pd.Timestamp(t).year for t in x["date"]]) for x in c5]
    ally, alld = np.concatenate(yrs), np.concatenate(d)
    tot = float(alld.sum())
    shares = {int(y): float(alld[ally == y].sum() / tot) for y in np.unique(ally)} if tot != 0 else {}
    loyo = {int(y): float(np.mean([v[yy != y].mean() * ANN for v, yy in zip(d, yrs)])) for y in np.unique(ally)}
    r.update({"offsets_same_sign": int((np.sign(po) == sg).sum()), "n_windows": int(len(alld)),
              "year_shares": shares, "max_year_share": max(shares.values()) if shares else None,
              "max_share_year": max(shares, key=shares.get) if shares else None,
              "loyo_S_by_dropped_year": loyo, "loyo_sign_flips": int(sum(np.sign(v) != sg for v in loyo.values())),
              "S_sd40": float(po.std())})
    return r


# ------------------------------------------------------------------ data
def load_all(need_states=True):
    import model_audit_wo23 as MA
    import trailfilter as TF
    import drag_decomp as DD
    import pool_read as PR
    import run_backtest as RB
    MA.SEAS_EXT = TF.SEAS_EXT_RO
    V, SI, DR, ICW = MA.V, MA.SI, MA.DR, MA.ICW
    assert DD.ANN == ANN and RB.HORIZON == 40 and DR.COST_BPS == 15.0
    U, all_dates, spy = MA.load_theo("A", "cap150")
    all_dates = [pd.Timestamp(d) for d in all_dates]
    assert U["date"].max() < HOLDOUT and spy.index.max() < HOLDOUT and max(all_dates) < HOLDOUT, "HOLD-OUT BREACH"
    if need_states:
        st = pd.read_parquet(CACHE / "states.parquet")
        n = len(U)
        U = U.merge(st, on=["ticker", "date"], how="left")
        assert len(U) == n and (U["date"].diff().dropna() >= pd.Timedelta(0)).all()
    W9 = dict(ICW.PRODUCTION_WEIGHTS_V9_SEAS)
    assert W9 == MA.W9 and list(W9) == MA.FT
    V.add_ranks(U, MA.FT)
    book = V.Book(U, all_dates, spy)
    G.update(MA=MA, TF=TF, DD=DD, PR=PR, RB=RB, V=V, SI=SI, DR=DR, ICW=ICW, U=U, all_dates=all_dates, spy=spy,
             book=book, W9=W9, FT=list(MA.FT), cost=DR.COST_BPS, sl=book.sl, vol=book.vol,
             ret=book.ret.astype(np.float64), code=pd.factorize(U["ticker"])[0].astype(np.int64),
             dcode=pd.factorize(U["date"])[0])
    assert np.array_equal(book.ret.astype(np.float64), U["gross_return_40"].to_numpy(np.float64), equal_nan=True)
    G["S"] = {f: (np.sign(W9[f]) * U[f"rz_{f}"].to_numpy(np.float64)) for f in G["FT"]}
    for f in G["FT"]:
        assert np.sign(W9[f]) == MA.SIGNS_T[f]
    G["score9"] = SI.composite_score(U, W9).to_numpy(np.float64)
    return U


def reconcile_book():
    """icw9_seas / icw8 unfiltered books vs the committed WO-31 numbers (hard assert)."""
    DD, PR, DR, SI, ICW = G["DD"], G["PR"], G["DR"], G["SI"], G["ICW"]
    ref = json.loads(POOL_READ.read_text())["tables"]
    out = {}
    pkw = PR.picks_w(G["book"], G["score9"])
    s8 = SI.composite_score(G["U"], dict(ICW.PRODUCTION_WEIGHTS)).to_numpy(np.float64)
    for m, pk, spec in (("icw9_seas", pkw, REF_ICW9), ("icw8", PR.picks_w(G["book"], s8), REF_ICW8)):
        ch = DD.chains({d: (v[0], v[1]) for d, v in pk.items()}, G["all_dates"], G["spy"], DR.COST_BPS)
        got = float(DD.per_offset(ch).mean())
        ex = ref[m]["A_full"]["cap150"]["book_vs_spy"]
        out[m] = {"got": got, "wo31_exact": ex, "diff_exact": got - ex, "spec": spec, "diff_spec": got - spec}
        assert abs(got - ex) < 1e-10 and abs(got - spec) < 1e-6, f"RECONCILE FAIL {m} {out[m]}"
    log(f"reconcile OK {out}")
    return out, pkw


# ------------------------------------------------------------------ prep
def prep():
    T0 = time.time()
    OUT.mkdir(parents=True, exist_ok=True); PARTS.mkdir(exist_ok=True); CACHE.mkdir(exist_ok=True)
    U = load_all(need_states=False)
    out = {"work_order": "WO-46", "era": ["2007-01-02", "2019-12-31"], "rows": int(len(U)), "tickers": int(U["ticker"].nunique()),
           "n_dates": len(G["all_dates"]), "first_date": str(G["all_dates"][0].date()), "last_date": str(G["all_dates"][-1].date()),
           "weights_icw9_seas": G["W9"]}
    px = build_states(load_close(set(U["ticker"].unique())))
    out["sep"] = {"rows": int(len(px)), "first": str(px["date"].min().date()), "last": str(px["date"].max().date())}
    log(f"states built on {len(px):,} SEP rows ({time.time()-T0:.0f}s)")
    out["pit"] = pit_check(px); log(f"PIT {out['pit']}")
    out["named_company"] = named_check(px); log(f"AAPL {out['named_company']}")
    px[["ticker", "date", "hi52", "vol60"]].to_parquet(CACHE / "states.parquet", index=False)
    n = len(U)
    U = U.merge(px[["ticker", "date", "hi52", "vol60"]], on=["ticker", "date"], how="left")
    assert len(U) == n
    del px
    # delisted names present
    tm = pd.read_csv(TM, dtype=str, usecols=["ticker", "isdelisted"]).drop_duplicates("ticker")
    dead = set(tm.loc[tm["isdelisted"] == "Y", "ticker"])
    ud = U[U["ticker"].isin(dead)]
    out["dead_names"] = {"dead_tickers_in_universe": int(ud["ticker"].nunique()), "share_of_tickers": float(ud["ticker"].nunique() / U["ticker"].nunique()),
                         "dead_rows_finite_hi52": int(ud["hi52"].notna().sum()), "dead_rows_finite_vol60": int(ud["vol60"].notna().sum()),
                         "dead_rows_with_label": int(ud["gross_return_40"].notna().sum())}
    assert out["dead_names"]["dead_rows_finite_hi52"] > 0 and out["dead_names"]["dead_rows_finite_vol60"] > 0
    log(f"dead names {out['dead_names']}")
    # overlap with the columns already in the panel / book
    ov = {}
    for mine, theirs, tr in (("hi52", "pct_from_high_252", lambda x: x + 1.0), ("vol60", "volatility_60", lambda x: x)):
        a, b = U[mine].to_numpy(np.float64), tr(U[theirs].to_numpy(np.float64))
        both = np.isfinite(a) & np.isfinite(b)
        dd = np.abs(a[both] - b[both])
        rk = pd.DataFrame({"d": U["date"], "a": U[mine], "b": U[theirs]})[both].groupby("d")[["a", "b"]].corr(method="spearman").xs("a", level=1)["b"]
        ov[mine] = {"panel_column": theirs, "coverage_mine": float(np.isfinite(a).mean()), "coverage_panel": float(np.isfinite(b).mean()),
                    "finite_mine_only": int((np.isfinite(a) & ~np.isfinite(b)).sum()), "finite_panel_only": int((~np.isfinite(a) & np.isfinite(b)).sum()),
                    "max_abs_diff": float(dd.max()), "p999_abs_diff": float(np.quantile(dd, 0.999)), "share_abs_diff_gt_1e-6": float((dd > 1e-6).mean()),
                    "within_date_spearman_min": float(rk.min()), "within_date_spearman_median": float(rk.median())}
        log(f"overlap {mine}: {ov[mine]}")
    out["overlap_with_panel_columns"] = ov
    dcode = G["dcode"]
    qs = {k: quintile(dcode, U[c].to_numpy(np.float64)) for k, c in STATES.items()}
    out["state_quintiles"] = {k: {"share_no_state": float((q < 0).mean()),
                                  "names_per_date_per_quintile_mean": float((q == 0).sum() / len(G["sl"])),
                                  "min_names_any_date_quintile": int(min(np.bincount(dcode[q == j]).min() for j in range(5))),
                                  "share_ties_at_high": float((U["hi52"] == 1.0).mean()) if k == "a_hi52" else None,
                                  "cross_tab_with_other_state": None} for k, q in qs.items()}
    m = (qs["a_hi52"] >= 0) & (qs["b_vol60"] >= 0)
    ct = pd.crosstab(qs["a_hi52"][m], qs["b_vol60"][m], normalize="all")
    out["state_quintiles"]["cross_tab_hi52_rows_vol60_cols"] = ct.round(4).values.tolist()
    log(f"quintiles {json.dumps(out['state_quintiles'])}")
    # book reconcile + picker oracle (equality only; no state-conditional number is reported)
    out["reconcile"], pkw = reconcile_book()
    G["U"] = U
    chk = {"pooled_dates": 0, "subset_dates": 0}
    V = G["V"]
    for f in ("score9", "gross_profitability", "seas"):
        sc = G["score9"] if f == "score9" else G["S"][f]
        ref = pkw if f == "score9" else G["book"].picks(sc)
        for d, s, e in G["sl"]:
            t, _ = fast_pick(G["vol"][s:e], sc[s:e], G["ret"][s:e], G["book"].tick[s:e], both=False)
            assert (t is None) == (d not in ref)
            if t is not None:
                assert t[1] == ref[d][1] and abs(t[0] - ref[d][0]) < 1e-12, (f, d)
                chk["pooled_dates"] += 1
    # subset oracle: state a Q1 and state b Q5, two factors, top and bottom legs, V.Book on the sub-frame
    for sk, qv in (("a_hi52", 0), ("b_vol60", 4)):
        mask = qs[sk] == qv
        sub = U.loc[mask, ["date", "ticker", "volatility_60", "gross_return_40"]].reset_index(drop=True)
        bk = V.Book(sub, G["all_dates"], G["spy"])
        G["code"] = U["ticker"].to_numpy()
        for f in ("momentum_12_1", "accruals"):
            fast = cell_books(mask, [f])[f]
            for leg, sgn in ((0, 1.0), (1, -1.0)):
                ref = bk.picks(sgn * G["S"][f][mask])
                assert set(ref) == set(fast[leg]), (sk, f, leg)
                for d in ref:
                    assert fast[leg][d][1] == ref[d][1] and abs(fast[leg][d][0] - ref[d][0]) < 1e-12
                    chk["subset_dates"] += 1
    out["picker_oracle"] = {**chk, "equal_to_V.Book.picks": True, "tol_gross": 1e-12}
    log(f"picker oracle OK {chk}")
    out["runtime_s"] = time.time() - T0
    (PARTS / "prep.json").write_text(json.dumps(out, indent=2, default=float))
    log(f"wrote {PARTS / 'prep.json'}")


# ------------------------------------------------------------------ real run
def book_rule(excl, pkw_u, detail):
    """Rule R: names with excl=True cannot be picked; next-ranked survivors fill each
    vol bucket's slots (trailfilter.picks_fullsize). Returns diff stats vs icw9_seas."""
    TF, DD, RB = G["TF"], G["DD"], G["RB"]
    pk_f, short = TF.picks_fullsize(G["book"], G["score9"], excl)
    n_cash = TF.cash_fill(pk_f, pkw_u)
    cu = TF.chains2(pkw_u, G["all_dates"], G["spy"], G["cost"], RB)
    cf = TF.chains2(pk_f, G["all_dates"], G["spy"], G["cost"], RB)
    if not detail:
        d = DD.per_offset(cf) - DD.per_offset(cu)
        return {"diff": float(d.mean()), "diff_offsets_pos": int((d > 0).sum())}
    r = TF.diff_stats(DD, cu, cf, 2008, per_year=True)
    r["short_buckets"], r["cash_dates"] = short, n_cash
    r["stats_unfiltered"], r["stats_filtered"] = TF.book_stats(cu), TF.book_stats(cf)
    dw = np.concatenate([b["exc"] - a["exc"] for a, b in zip(cu, cf)])
    yy = np.concatenate([[pd.Timestamp(t).year for t in a["date"]] for a in cu])
    tot = dw.sum()
    r["diff_year_shares"] = {int(y): float(dw[yy == y].sum() / tot) for y in np.unique(yy)}
    r["diff_per_offset"] = (DD.per_offset(cf) - DD.per_offset(cu)).tolist()
    return r


def run_real():
    T0 = time.time()
    U = load_all()
    out = {"reconcile": None, "cells": {}, "pooled": {}}
    out["reconcile"], pkw = reconcile_book()
    qs = {k: quintile(G["dcode"], U[c].to_numpy(np.float64)) for k, c in STATES.items()}
    FT = G["FT"]
    pooled = cell_books(None, FT)
    ict = json.loads((MAIN / "out" / "reset2026" / "ic_weighted_composite_report.json").read_text())["per_factor_t"]["full"]
    for f in FT:
        ch = ls_chain(*pooled[f])
        po = off_mean(ch)
        ic = G["V"].nw(G["SI"].daily_corr(U, f, G["MA"].LABEL).to_numpy())
        out["pooled"][f] = {"ls_net": float(po.mean()), "ls_offsets_pos": int((po > 0).sum()),
                            "top_net": float(off_mean(ch, "top_net").mean()), "bot_net": float(off_mean(ch, "bot_net").mean()),
                            "live_sign": int(np.sign(G["W9"][f])), "ic_mean_this_panel": ic["mean"], "ic_t_this_panel": ic["t"],
                            "ic_t_icw_report_old_grid": ict.get(f, {}).get("t"),
                            "ls_sign_matches_signed_ic": bool(np.sign(po.mean()) == np.sign(ic["mean"] * np.sign(G["W9"][f])))}
        log(f"pooled {f}: LS {po.mean():+.4f} ({(po > 0).sum()}/40) IC t {ic['t']:+.2f}")
    (PARTS / "real.json").write_text(json.dumps(out, indent=2, default=float))
    for sk in STATES:
        bq = {q: cell_books(qs[sk] == q, FT) for q in range(5)}
        log(f"{sk}: quintile books done ({time.time()-T0:.0f}s)")
        for f in FT:
            if (f, sk) in SELF_CELLS:          # dropped by the 2026-10-06 amendment (16 cells)
                continue
            if not (bq[4][f][0] and bq[0][f][0]):
                # factor has no finite value in this era (short interest data start after 2019): cell undefined, cannot pass
                out["cells"][f"{f}|{sk}"] = {"undefined_no_data": True, "S": None, "offsets_same_sign": 0, "max_year_share": None}
                log(f"cell {f}|{sk}: UNDEFINED (no factor data in era)")
                continue
            r = spread_stats(bq[4][f], bq[0][f])
            lsq = [float(off_mean(ls_chain(*bq[q][f])).mean()) for q in range(5)]
            r["ls_net_by_state_quintile_Q1_to_Q5"] = lsq
            r["ls_net_pooled"] = out["pooled"][f]["ls_net"]
            r["quintile_minus_pooled"] = [x - r["ls_net_pooled"] for x in lsq]
            r["self_conditioning_cell"] = (f, sk) in SELF_CELLS
            out["cells"][f"{f}|{sk}"] = r
            log(f"cell {f}|{sk}: S {r['S']:+.4f} same-sign {r['offsets_same_sign']}/40 max-year {r['max_year_share']:.2f} "
                f"({r['max_share_year']}) LS by Q {[round(x, 4) for x in lsq]} pooled {r['ls_net_pooled']:+.4f}")
        (PARTS / "real.json").write_text(json.dumps(out, indent=2, default=float))
    excl = qs["a_hi52"] == 0
    out["book_rule"] = book_rule(excl, pkw, True)
    out["book_rule"]["share_eligible_excluded"] = float(excl.mean())
    br = out["book_rule"]
    log(f"book rule: icw9_seas {br['unfiltered']:+.4f} rule {br['filtered']:+.4f} diff {br['diff']:+.4f} ({br['diff_offsets_pos']}/40) "
        f"drop2008 {br['diff_drop2008']}")
    out["runtime_s"] = time.time() - T0
    (PARTS / "real.json").write_text(json.dumps(out, indent=2, default=float))
    log(f"wrote {PARTS / 'real.json'} ({time.time()-T0:.0f}s)")


# ------------------------------------------------------------------ null
def null_draw(seed):
    p = NULLD / f"draw_{seed:03d}.json"
    if p.exists():
        return seed
    t0 = time.time()
    U, V = G["U"], G["V"]
    res = {"seed": seed, "cells": {}}
    for sk, col in STATES.items():
        q = quintile(G["dcode"], V.shuffle_within_date(U, col, SEED_OFF[sk] + seed))
        if sk == "a_hi52":
            res["book_rule"] = book_rule(q == 0, G["pkw"], False)
        b5, b1 = cell_books(q == 4, G["FT"]), cell_books(q == 0, G["FT"])
        for f in G["FT"]:
            if (f, sk) in SELF_CELLS:
                continue
            if not (b5[f][0] and b1[f][0]):
                res["cells"][f"{f}|{sk}"] = None
                continue
            res["cells"][f"{f}|{sk}"] = spread_stats(b5[f], b1[f], full=False)["S"]
    res["runtime_s"] = time.time() - t0
    p.write_text(json.dumps(res))
    return seed


def run_null(n, procs):
    import multiprocessing as mp
    NULLD.mkdir(parents=True, exist_ok=True)
    load_all()
    _, G["pkw"] = reconcile_book()
    todo = [s for s in range(n) if not (NULLD / f"draw_{s:03d}.json").exists()]
    log(f"null: {len(todo)} draws to run on {procs} processes")
    if procs <= 1:
        for s in todo:
            null_draw(s); log(f"null draw {s} done")
        return
    with mp.get_context("fork").Pool(procs) as pool:
        for s in pool.imap_unordered(null_draw, todo):
            log(f"null draw {s} done")


# ------------------------------------------------------------------ test 3
def run_hi52(null_draws=20):
    T0 = time.time()
    U = load_all()
    MA, V, S = G["MA"], G["V"], G["MA"].S
    COL = "hi52"
    V.COL, V.SIGN, V.T_BAR = COL, +1, 1.96
    V.SIGNS9 = {**V.SIGNS8, COL: +1}
    V.OUT_JSON = PARTS / "hi52_harness_unused.json"
    rep = {"family": "52-week-high (George-Hwang 2004)", "k": 1, "t_bar": 1.96, "sign": +1, "column": COL, "label": V.LABEL,
           "null_draws": null_draws, "note": "hi52 = 1 + pct_from_high_252, a factor already in icw8/icw9_seas; gate 6 adds it to icw8 a second time"}
    rep["weight_rule_check"] = S.weight_rule_check()
    V.add_ranks(U, V.FC8)
    book = V.Book(U, G["all_dates"], G["spy"])
    ref = json.loads(V.READOUT.read_text())["columns"]["c"]["cap150"]
    rep["harness_reconcile"] = V.reconcile(U, book, ref)
    ic, g = V.ic_gates(U, xcol=COL)
    rep["ic"] = ic
    log(f"hi52 IC {ic['pooled']['mean']:+.5f} t {ic['pooled']['t']:+.2f} odd {ic['odd']['mean']:+.5f} even {ic['even']['mean']:+.5f} "
        f"sector both t {ic['sector_both_sides']['t']:+.2f} flips {ic['offsets']['sign_flips']}/40 max year share {ic['year_share']['max_share']}")
    icp, _ = V.ic_gates(U, xcol="pct_from_high_252")
    rep["ic_panel_pct_from_high_252_same_harness"] = {"mean": icp["pooled"]["mean"], "t": icp["pooled"]["t"]}
    (PARTS / "hi52.json").write_text(json.dumps(rep, indent=2, default=float))
    rep["portfolio"] = V.gate6(U, book, null_draws, "primary")
    g["g6_beats_null_p80"] = rep["portfolio"]["g6_beats_null_p80"]
    g["g7_weight_rule_reproduces_production_4dp"] = rep["weight_rule_check"]["pass"]
    rep["gates"] = g
    rep["failed_gates"] = [k for k, v in g.items() if not v]
    rep["verdict"] = "PASS-nomination" if not rep["failed_gates"] else "DEAD"
    rep["runtime_s"] = time.time() - T0
    log(f"hi52 gates {g} -> {rep['verdict']}")
    (PARTS / "hi52.json").write_text(json.dumps(rep, indent=2, default=float))


# ------------------------------------------------------------------ aggregate
def aggregate():
    real = json.loads((PARTS / "real.json").read_text())
    prep_ = json.loads((PARTS / "prep.json").read_text())
    draws = [json.loads(p.read_text()) for p in sorted(NULLD.glob("draw_*.json"))]
    n = len(draws)
    rep = {"work_order": "WO-46 per-stock state labels as factor interactions", "prereg": "final/models/2026-10-02-state-interactions.md",
           "era": prep_["era"], "units": "fractions per year (0.01 = 1%/yr), 40-offset mean, net 15bp",
           "null_draws": n, "prep": prep_, "pooled": real["pooled"], "reconcile": real["reconcile"], "cells": {}}
    n80 = n95 = 0
    zmax = 0.0
    assert len(real["cells"]) == 16
    for k, r in real["cells"].items():
        if r.get("undefined_no_data"):
            rep["cells"][k] = {**r, "pass_p80": False, "pass_p95": False, "beyond_p80": False, "beyond_p95": False}
            continue
        nd = np.array([d["cells"][k] for d in draws])
        a = np.abs(nd)
        p80, p95 = float(np.percentile(a, 80)), float(np.percentile(a, 95))
        z = float(nd.mean() / (nd.std(ddof=1) / np.sqrt(n)))
        zmax = max(zmax, abs(z))
        stable = r["offsets_same_sign"] >= N_OFF_MIN and r["max_year_share"] is not None and r["max_year_share"] <= YEAR_SHARE_MAX
        c = {**r, "null": {"mean": float(nd.mean()), "sd": float(nd.std(ddof=1)), "z_of_mean": z, "abs_p50": float(np.percentile(a, 50)),
                           "abs_p80": p80, "abs_p95": p95, "signed_p10": float(np.percentile(nd, 10)), "signed_p90": float(np.percentile(nd, 90)),
                           "pctile_of_abs_real": float((a < abs(r["S"])).mean()), "draws": nd.tolist()},
             "beyond_p80": bool(abs(r["S"]) > p80), "beyond_p95": bool(abs(r["S"]) > p95),
             "offsets_ok": bool(r["offsets_same_sign"] >= N_OFF_MIN), "year_share_ok": bool(r["max_year_share"] is not None and r["max_year_share"] <= YEAR_SHARE_MAX)}
        c["pass_p80"] = bool(c["beyond_p80"] and stable)
        c["pass_p95"] = bool(c["beyond_p95"] and stable)
        n80 += c["pass_p80"]; n95 += c["pass_p95"]
        rep["cells"][k] = c
    nb = np.array([d["book_rule"]["diff"] for d in draws])
    br = real["book_rule"]
    rep["book_rule"] = {**br, "null_random_exclusion": {"mean": float(nb.mean()), "sd": float(nb.std(ddof=1)), "p80": float(np.percentile(nb, 80)),
                                                         "p95": float(np.percentile(nb, 95)), "pctile_of_real": float((nb < br["diff"]).mean()),
                                                         "offsets_pos_mean": float(np.mean([d["book_rule"]["diff_offsets_pos"] for d in draws])), "draws": nb.tolist()}}
    book_ok = bool(br["diff"] > 0 and br["diff_offsets_pos"] >= N_OFF_MIN)
    cells_ok = bool(n95 >= 2)                # amendment 2026-10-06: >=2 of 16 cells pass at p95; p80 descriptive
    rep["shuffled_state_no_effect_check"] = {"max_abs_z_of_null_mean_over_16_cells": zmax, "pass_lt_3": bool(zmax < 3.0)}
    best = max([k for k in rep["cells"] if rep["cells"][k]["S"] is not None], key=lambda k: rep["cells"][k]["null"]["pctile_of_abs_real"] + 1e-9 * abs(rep["cells"][k]["S"]))
    rep["decision"] = {"cells_beyond_p80_band_only": int(sum(c["beyond_p80"] for c in rep["cells"].values())),
                       "cells_beyond_p95_band_only": int(sum(c["beyond_p95"] for c in rep["cells"].values())),
                       "cells_pass_p80_with_offsets_and_year_share_DESCRIPTIVE": int(n80), "cells_pass_p95_with_offsets_and_year_share": int(n95),
                       "cells_condition": cells_ok, "book_diff": br["diff"], "book_diff_offsets_pos": br["diff_offsets_pos"], "book_condition": book_ok,
                       "best_cell_by_null_percentile": best, "verdict": "PASS" if (cells_ok and book_ok) else "KILL"}
    hp = PARTS / "hi52.json"
    if hp.exists():
        rep["hi52_standalone_7gate"] = json.loads(hp.read_text())
    (OUT / "state_interactions_report.json").write_text(json.dumps(rep, indent=2, default=float))
    log(f"decision {json.dumps(rep['decision'])}")
    log(f"no-effect check {rep['shuffled_state_no_effect_check']}")
    for k, c in rep["cells"].items():
        if c["S"] is None:
            log(f"{k}: UNDEFINED"); continue
        log(f"{k}: S {c['S']:+.4f} |null| p80 {c['null']['abs_p80']:.4f} p95 {c['null']['abs_p95']:.4f} offs {c['offsets_same_sign']} "
            f"yr {c['max_year_share']:.2f} pass80 {c['pass_p80']} pass95 {c['pass_p95']}")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--prep", action="store_true")
    ap.add_argument("--run", action="store_true")
    ap.add_argument("--null", type=int, default=0)
    ap.add_argument("--procs", type=int, default=6)
    ap.add_argument("--hi52", action="store_true")
    ap.add_argument("--aggregate", action="store_true")
    a = ap.parse_args()
    if a.prep:
        prep()
    elif a.run:
        run_real()
    elif a.null:
        run_null(a.null, a.procs)
    elif a.hi52:
        run_hi52()
    elif a.aggregate:
        aggregate()


if __name__ == "__main__":
    main()
