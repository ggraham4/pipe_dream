"""WO-60 short-book engine (pre-reg final/models/2026-10-10-short-book-prereg.md, frozen c8f32d1).

No code here places, modifies or cancels orders: it computes historical backtest statistics only.

Usage (python = /opt/anaconda3/envs/pipe_dream/bin/python, under caffeinate -i):
  engine.py --tier cap2000 --real          -> out/shortbook/real_<tier>.json (+ big parts in main out)
  engine.py --tier cap2000 --null 200 --procs 6
  engine.py --tier cap2000 --aggregate
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

import numpy as np
import pandas as pd

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
import sb_common as K  # noqa: E402

G = {}
FEE_CAP, PX_MIN = 0.10, 5.0
STRESS = 0.03


# ------------------------------------------------------------------ load
def load(tier):
    R = pd.read_parquet(K.OUT_BIG / f"rows_{tier}.parquet")
    assert R["date"].max() <= K.SIG_HI, "HOLD-OUT BREACH"
    all_dates = [pd.Timestamp(x) for x in pd.read_csv(K.OUT_BIG / f"all_dates_{tier}.csv").iloc[:, 0]]
    all_dates = [d for d in all_dates if d >= R["date"].min() and d <= K.SIG_HI]
    d = R["date"].to_numpy()
    starts = np.flatnonzero(np.r_[True, d[1:] != d[:-1]])
    ends = np.r_[starts[1:], len(d)]
    G.update(R=R, tier=tier, all_dates=all_dates, sl=[(pd.Timestamp(d[s]), s, e) for s, e in zip(starts, ends)],
             code=pd.factorize(R["ticker"])[0].astype(np.int64))
    G["dpos"] = {x[0]: i for i, x in enumerate(G["sl"])}
    vol = R["volatility_60"].to_numpy(np.float64)
    G["vol"] = vol
    G["volq"] = volq(vol, R["score"].to_numpy(np.float64))
    G["r"] = R["r_tot"].to_numpy(np.float64)
    G["fee"] = R["fee"].to_numpy(np.float64)
    G["beta"] = R["beta_252"].to_numpy(np.float64)
    G["shortable"] = ((R["entry_open"].to_numpy(np.float64) >= PX_MIN) & (G["fee"] <= FEE_CAP))
    G["spy"] = spy_tr()
    # H1 universe leg: EW over every eligible row of the date
    uni = {}
    for dt, s, e in G["sl"]:
        uni[dt] = (float(np.mean(G["r"][s:e])), np.sort(G["code"][s:e]))
    G["uni"] = uni
    return R


def volq(vol, score):
    """vol quintile per date over valid (finite vol & score) rows, pd.qcut(duplicates='drop') as composite.pick_decile_volq."""
    out = np.full(len(vol), -1, dtype=np.int64)
    for dt, s, e in G["sl"]:
        v = vol[s:e]; ok = np.isfinite(v) & np.isfinite(score[s:e])
        if ok.sum() < 20:
            continue
        idx = np.flatnonzero(ok)
        out[s + idx] = pd.qcut(v[idx], 5, labels=False, duplicates="drop")
    return out


def spy_tr():
    b = pd.read_parquet(K.SPY_BENCH)
    b["date"] = pd.to_datetime(b["date"])
    b = b[b["date"] <= K.PRICE_HI].sort_values("date").reset_index(drop=True)
    f = (b["adj_close"] / b["close"]).to_numpy()
    o = b["open"].to_numpy() * f; c = b["close"].to_numpy() * f
    n = len(b); idx = np.arange(n); ok = idx + K.H <= n - 1
    out = np.full(n, np.nan)
    out[ok] = c[idx[ok] + K.H] / o[idx[ok] + 1] - 1.0
    s = pd.Series(out, index=pd.DatetimeIndex(b["date"]))
    return s[s.index <= K.SIG_HI]


# ------------------------------------------------------------------ picking
def pick_cells(score, cell, frac, eligible=None):
    """Bottom `frac` (lowest score) within each (date, cell) among rows with cell >= 0 and finite score.
    k = max(1, round(n*frac)) (Python round, as composite.pick_decile_volq). Returns bool mask."""
    m = np.zeros(len(score), dtype=bool)
    for dt, s, e in G["sl"]:
        c = cell[s:e]; sc = score[s:e]
        ok = (c >= 0) & np.isfinite(sc)
        if ok.sum() < 20:
            continue
        idx = np.flatnonzero(ok)
        for b in np.unique(c[idx]):
            bi = idx[c[idx] == b]
            k = max(1, int(round(len(bi) * frac)))
            order = bi[np.argsort(sc[bi], kind="stable")][:k]
            m[s + order] = True
    return m


def sector_cells():
    sec = G["R"]["sector"].fillna("Unknown").astype(str)
    c = pd.factorize(sec)[0].astype(np.int64)
    c[~np.isfinite(G["R"]["score"].to_numpy(np.float64))] = -1
    return c


# ------------------------------------------------------------------ book -> per-date
def per_date(mask, fee_add=0.0, rclip=None):
    """{date: (r_book, fee_book, beta_book, codes_sorted, n)} over picked & shortable rows, EW."""
    sel = mask & G["shortable"]
    out = {}
    r = G["r"] if rclip is None else np.minimum(G["r"], rclip)
    for dt, s, e in G["sl"]:
        w = np.flatnonzero(sel[s:e])
        if len(w) == 0:
            continue
        idx = s + w
        b = G["beta"][idx]; b = b[np.isfinite(b)]
        out[dt] = (float(r[idx].mean()), float(G["fee"][idx].mean() + fee_add),
                   float(b.mean()) if len(b) else 1.0, np.sort(G["code"][idx]), len(idx))
    return out


def turnover(a, b):
    """sum |w_b - w_a| for equal-weight sets a (prev) and b (cur) of sorted codes."""
    na, nb = len(a), len(b)
    if na == 0:
        return 1.0
    c = len(np.intersect1d(a, b, assume_unique=True))
    return c * abs(1.0 / nb - 1.0 / na) + (nb - c) / nb + (na - c) / na


def chains(pd_book, hedge="H1"):
    """40 offset chains -> list of dicts with per-period arrays (date, R net, parts)."""
    ch = []
    for off in range(K.H):
        recs = []
        prev_b, prev_u, prev_k = np.array([], dtype=np.int64), np.array([], dtype=np.int64), 0.0
        dts = [d for d in G["all_dates"][off::K.H] if d in pd_book]
        for i, d in enumerate(dts):
            rb, fee, beta, codes, n = pd_book[d]
            last = i == len(dts) - 1
            c_short = K.COST * (turnover(prev_b, codes) + (1.0 if last else 0.0))
            if hedge == "H1":
                ru, ucodes = G["uni"][d]
                hed = ru
                c_hed = K.COST * (turnover(prev_u, ucodes) + (1.0 if last else 0.0))
                prev_u = ucodes
            else:
                sp = G["spy"].get(d, np.nan)
                k = beta if hedge == "H2" else 1.0
                hed = k * sp
                c_hed = K.COST * (abs(k - prev_k) + (k if last else 0.0))
                prev_k = k
            borrow = fee * K.H / 252.0
            R = -rb + hed - c_short - c_hed - borrow
            recs.append((d, R, -rb, hed, c_short + c_hed, borrow, n))
            prev_b = codes
        a = np.array([x[1:] for x in recs], dtype=np.float64)
        ok = np.isfinite(a[:, 0])
        ch.append({"date": np.array([x[0] for x in recs], dtype="datetime64[ns]")[ok], "R": a[ok, 0],
                   "short": a[ok, 1], "hedge": a[ok, 2], "cost": a[ok, 3], "borrow": a[ok, 4], "n": a[ok, 5]})
    return ch


def M_of(ch):
    return float(np.mean([c["R"].mean() * K.ANN for c in ch]))


def stats(ch):
    po = np.array([c["R"].mean() * K.ANN for c in ch])
    years = sorted({pd.Timestamp(t).year for c in ch for t in c["date"]})
    loyo = {}
    for y in years:
        v = [c["R"][np.array([pd.Timestamp(t).year != y for t in c["date"]])].mean() * K.ANN for c in ch]
        loyo[y] = float(np.mean(v))
    # per-year effect: offset-averaged sum of per-period R in that year, and in-year annualized mean
    ysum, ymean = {}, {}
    for y in years:
        ss, mm = [], []
        for c in ch:
            k = np.array([pd.Timestamp(t).year == y for t in c["date"]])
            ss.append(c["R"][k].sum()); mm.append(c["R"][k].mean() * K.ANN if k.any() else np.nan)
        ysum[y] = float(np.mean(ss)); ymean[y] = float(np.nanmean(mm))
    tot = sum(ysum.values())
    shares = {y: v / tot for y, v in ysum.items()} if tot > 0 else None
    # drawdown, worst period per offset
    mdd, worst = [], []
    for c in ch:
        eq = np.cumprod(1.0 + c["R"]); pk = np.maximum.accumulate(eq)
        mdd.append(float((eq / pk - 1.0).min())); worst.append(float(c["R"].min()))
    parts = {k: float(np.mean([c[k].mean() * K.ANN for c in ch])) for k in ("short", "hedge", "cost", "borrow")}
    return {"M": float(po.mean()), "sd40": float(po.std()), "offsets_pos": int((po > 0).sum()), "per_offset": po.tolist(),
            "worst_offset": float(po.min()), "loyo_min": float(min(loyo.values())),
            "loyo_min_year": int(min(loyo, key=loyo.get)), "loyo": loyo,
            "year_sum": ysum, "year_ann_mean": ymean, "year_shares": shares,
            "max_year_share": (max(shares.values()) if shares else None),
            "max_share_year": (max(shares, key=shares.get) if shares else None),
            "max_dd_mean_over_offsets": float(np.mean(mdd)), "max_dd_worst_offset": float(min(mdd)),
            "worst_40d_period": float(min(worst)), "parts_ann": parts,
            "mean_names": float(np.mean([c["n"].mean() for c in ch])),
            "turnover_per_rebalance_mean": None}


# ------------------------------------------------------------------ real
def real(tier):
    load(tier)
    sc = G["R"]["score"].to_numpy(np.float64)
    out = {"tier": tier, "rows": int(len(G["R"])), "dates": len(G["sl"]),
           "first": str(G["sl"][0][0].date()), "last": str(G["sl"][-1][0].date())}
    base = pick_cells(sc, G["volq"], 0.10)
    np.save(K.OUT_BIG / f"pick_base_{tier}.npy", base)
    pdb = per_date(base)
    out["primary_H1_B1"] = stats(chains(pdb, "H1"))
    K.log(f"[{tier}] M (H1, B1) {out['primary_H1_B1']['M']*100:+.3f}%/yr, {out['primary_H1_B1']['offsets_pos']}/40")
    out["B3_stress_H1"] = stats(chains(per_date(base, fee_add=STRESS), "H1"))
    out["H2_beta_SPY_B1"] = stats(chains(pdb, "H2"))
    out["H3_spy1x_B1"] = stats(chains(pdb, "H3"))
    out["no_fee_H1"] = stats(chains({d: (v[0], 0.0) + v[2:] for d, v in pdb.items()}, "H1"))
    sec = pick_cells(sc, sector_cells(), 0.10)
    out["S6a_sector_neutral_H1"] = stats(chains(per_date(sec), "H1"))
    dtc = G["R"]["dtc"].to_numpy(np.float64)
    med = G["R"].groupby("date")["dtc"].transform("median").to_numpy(np.float64)
    low = np.isfinite(dtc) & (dtc < med)
    out["S6c_lowSIR_H1"] = stats(chains(per_date(base & low), "H1"))
    out["S6c_highSIR_H1_descr"] = stats(chains(per_date(base & ~low & np.isfinite(dtc)), "H1"))
    for f in (0.05, 0.20):
        out[f"S7_frac{f}_H1"] = stats(chains(per_date(pick_cells(sc, G["volq"], f)), "H1"))
    out["cap_2x_H1_descr"] = stats(chains(per_date(base, rclip=1.0), "H1"))
    # descriptives on the base book
    out["descr"] = descr(base, sc)
    for k, v in out.items():
        if isinstance(v, dict) and "M" in v:
            K.log(f"[{tier}] {k}: M {v['M']*100:+.3f}  pos {v['offsets_pos']}/40  loyo_min {v['loyo_min']*100:+.3f}")
    K.OUT.mkdir(parents=True, exist_ok=True)
    (K.OUT / f"real_{tier}.json").write_text(json.dumps(out, indent=1, default=str))


def descr(base, sc):
    R = G["R"]
    sel = base & G["shortable"]
    d = {}
    d["picked_rows"] = int(base.sum()); d["shortable_rows"] = int(sel.sum())
    d["excluded_share"] = float(1 - sel.sum() / base.sum())
    d["excluded_px_lt5"] = int((base & (R["entry_open"].to_numpy() < PX_MIN)).sum())
    d["excluded_no_entry"] = int((base & ~np.isfinite(R["entry_open"].to_numpy())).sum())
    d["excluded_fee_gt10"] = int((base & (G["fee"] > FEE_CAP)).sum())
    # A2: delisting / NaN labels in the book vs universe
    tr = R["trunc"].to_numpy() | ~R["has_next"].to_numpy()
    d["A2"] = {"book_trunc_share": float(tr[sel].mean()), "universe_trunc_share": float(tr.mean()),
               "book_label_nan": int(R["label_nan"].to_numpy()[sel].sum()), "dropped_nan_labels": 0,
               "book_later_delisted_by_2019_share": float((R["d_last"].to_numpy()[sel] < np.datetime64(K.PRICE_HI - pd.Timedelta(days=3))).mean()),
               "universe_later_delisted_by_2019_share": float((R["d_last"].to_numpy() < np.datetime64(K.PRICE_HI - pd.Timedelta(days=3))).mean())}
    # delisting classes: counts and P&L contribution (short side, per-row weight within date, offset-averaged ann.)
    nb = pd.Series(sel).groupby(R["date"].to_numpy()).transform("sum").to_numpy()
    w = np.where(sel, 1.0 / np.maximum(nb, 1), 0.0)
    contrib = -w * G["r"]                     # per-date short contribution; each date is in exactly one offset chain
    cls = R["dl_class"].to_numpy()
    n_dates = len(G["sl"])
    d["delist_classes"] = {c: {"book_rows": int((sel & (cls == c)).sum()),
                               "pnl_ann_contrib": float(contrib[cls == c].sum() / n_dates * K.ANN),
                               "dl_part_ann_contrib": float((-w * ((1 + G['r']) - (1 + G['r']) / (1 + R['dl'].to_numpy())))[cls == c].sum() / n_dates * K.ANN)}
                           for c in np.unique(cls)}
    d["delist_imputed_rows_in_book"] = int((sel & R["dl_imputed"].fillna(False).to_numpy(bool)).sum())
    # names
    df = pd.DataFrame({"ticker": R["ticker"], "date": R["date"], "r": G["r"], "c": contrib})[sel]
    d["largest_single_name_40d_loss"] = df.sort_values("r", ascending=False).head(5).assign(date=lambda x: x["date"].astype(str)).to_dict("records")
    d["worst10_names_pnl"] = (df.groupby("ticker")["c"].sum() / n_dates * K.ANN).sort_values().head(10).to_dict()
    d["top20_winning_shorts"] = df.sort_values("r").head(20).assign(date=lambda x: x["date"].astype(str)).to_dict("records")
    # overlaps: live long book (cap150 decile_volq top decile) and SI top decile
    d["overlap"] = overlaps(sel, sc)
    # turnover
    pdb = per_date(base)
    tv = []
    for off in range(K.H):
        dts = [x for x in G["all_dates"][off::K.H] if x in pdb]
        tv += [turnover(pdb[a][3], pdb[b][3]) / 2 for a, b in zip(dts[:-1], dts[1:])]
    d["one_way_turnover_per_rebalance"] = float(np.mean(tv)); d["one_way_turnover_ann"] = float(np.mean(tv) * K.ANN)
    d["fee_mean_book"] = float(G["fee"][sel].mean()); d["fee_mean_universe"] = float(G["fee"].mean())
    return d


def overlaps(sel, sc):
    R = G["R"]
    out = {}
    # SI top decile within date (tier universe)
    dtc = R["dtc"]
    top = (dtc.groupby(R["date"]).rank(pct=True) > 0.9).to_numpy()
    out["si_top_decile_share_of_book"] = float(top[sel].mean())
    # live long book = cap150 top decile within volq on the same score definition
    L = pd.read_parquet(K.OUT_BIG / "rows_cap150.parquet", columns=["date", "ticker", "score", "volatility_60"])
    tick_short = set(zip(R["date"].to_numpy()[sel], R["ticker"].to_numpy()[sel]))
    long_set = set()
    for dt, g in L.groupby("date"):
        v = g["volatility_60"].to_numpy(); s = g["score"].to_numpy()
        ok = np.isfinite(v) & np.isfinite(s)
        if ok.sum() < 20:
            continue
        gi = g[ok]
        q = pd.qcut(gi["volatility_60"].to_numpy(), 5, labels=False, duplicates="drop")
        for b in np.unique(q):
            gb = gi[q == b]
            k = max(1, int(round(len(gb) * 0.10)))
            long_set.update(zip(gb.nlargest(k, "score")["date"].to_numpy(), gb.nlargest(k, "score")["ticker"].to_numpy()))
    out["short_rows_in_live_long_book"] = int(len(tick_short & long_set))
    out["short_rows"] = len(tick_short)
    return out


# ------------------------------------------------------------------ null
def shuffle_within_date(score, seed):
    rng = np.random.default_rng(seed)
    v = score.copy()
    idx = np.flatnonzero(np.isfinite(v))
    dcode = np.searchsorted([s for _, s, _ in G["sl"]], idx, side="right") - 1
    order = np.lexsort((rng.random(len(idx)), dcode))
    v[idx] = score[idx][order]
    return v


def null_one(s):
    p = K.OUT_BIG / "null" / G["tier"] / f"{s:03d}.json"
    if p.exists():
        return s
    sc = shuffle_within_date(G["R"]["score"].to_numpy(np.float64), K.SEED0 + s)
    ch = chains(per_date(pick_cells(sc, G["volq"], 0.10)), "H1")
    p.write_text(json.dumps({"seed": K.SEED0 + s, "M": M_of(ch)}))
    return s


def run_null(tier, n, procs):
    import multiprocessing as mp
    (K.OUT_BIG / "null" / tier).mkdir(parents=True, exist_ok=True)
    load(tier)
    todo = [s for s in range(n) if not (K.OUT_BIG / "null" / tier / f"{s:03d}.json").exists()]
    K.log(f"[{tier}] null {len(todo)} draws on {procs} procs")
    with mp.get_context("fork").Pool(procs) as pool:
        for i, s in enumerate(pool.imap_unordered(null_one, todo)):
            if i % 20 == 0:
                K.log(f"null draw {s} done ({i+1}/{len(todo)})")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--tier", default="cap2000")
    ap.add_argument("--real", action="store_true")
    ap.add_argument("--null", type=int, default=0)
    ap.add_argument("--procs", type=int, default=6)
    a = ap.parse_args()
    if a.real:
        real(a.tier)
    if a.null:
        run_null(a.tier, a.null, a.procs)


if __name__ == "__main__":
    main()
