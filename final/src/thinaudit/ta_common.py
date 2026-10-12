"""
WO-61 thin-slice book audit: shared loaders, fast picks and the two evaluators.
Plan: final/models/2026-10-10-thinbook-audit.md (committed bfcaa8d before any outcome statistic).

Imports read-only: final/src/cwbook (WO-58 frame and fast path), reset2026 (composite, ICW, run_backtest,
downcap_v2_readout = WO-6's harness), wrds_crsp/common.py (WO-51 crosswalk/CRSP loaders).
Research code only. It never places, modifies or cancels an order.
"""
from __future__ import annotations

import hashlib
import json
import sys
import time
from pathlib import Path

import numpy as np
import pandas as pd

HERE = Path(__file__).resolve().parent
SRC = HERE.parent
FINAL = HERE.parents[1]
REPO = FINAL.parent
for p in (SRC / "cwbook", SRC / "wrds_crsp", SRC / "reset2026"):
    if str(p) not in sys.path:
        sys.path.insert(0, str(p))
import cb_core as B                 # noqa: E402  (WO-58; also loads cw_core, tl_common, ICW)
import composite as C               # noqa: E402
import ic_weighted_composite as ICW  # noqa: E402

OUT = FINAL / "out" / "thinaudit"
OUT.mkdir(parents=True, exist_ok=True)
MAIN = Path("/Users/ggraham/pipe_dream/final")
R26 = MAIN / "out" / "reset2026"
PANEL_V2 = R26 / "composite_panel_v2.parquet"
OUTCOME_V2 = R26 / "outcome_cache_v2.parquet"
UNIVERSE = MAIN / "data" / "sharadar" / "downcap_universe_v2.parquet"
XWALK = MAIN / "data" / "wrds" / "link" / "permno_sharadar.parquet"
SPINFIX = MAIN / "data" / "wrds" / "crsp" / "derived" / "spinfix_labels.parquet"
FEATS1 = OUT / "feats_stage1_wo52.parquet"
SHA = {
    PANEL_V2: "48ef4e47c9e8e704c989ee6dbe0ee9cc00e969a04a1725929e7ad458ec6082b7",
    OUTCOME_V2: "434d353fe63d27bbaaaba47cd8238f049a95def72304e2989dfef1982e2212d4",
    UNIVERSE: "f4a40f4b71883b2010e9d8f97c790b46da89279c5f058a61a25c03512daccfeb",
    FEATS1: "c6783045523ca80c1f59e02ebb3035f76f1ade9b994327f14e97d8f69eb03801",
    B.SEAS_EXT: "ca9721d3879bca0b2340bea660ca43949a485fb9bd9cd2513614dd4137f52e2c",
    XWALK: "4db64e336fb1ec147cafa85a50a340c5bc1ba8a1a83bc787c42bb7365f72108c",
    SPINFIX: "84b3ff99585af9dc4dd2f05cb269ad1726c753c22d9a3ea09cbf356ec7f6d81a",
}
PLAN = "final/models/2026-10-10-thinbook-audit.md"
PLAN_SHA = "2d601f52b55f6347c8eb4a1419b38a2ea5bde064273214133321c429ce53b9db"
ERA = (pd.Timestamp("2008-01-01"), pd.Timestamp("2018-12-31"))      # entry dates
READ_CAP = pd.Timestamp("2019-03-31")                               # last exit leg of a 2018 entry
WO58_BASE = 0.08058666317545946
WO58_VAR = 0.08562552394725337
WO6_ICW8_CAP150 = 0.028541632641009042
W8 = dict(ICW.PRODUCTION_WEIGHTS)
W5 = dict(ICW.PRODUCTION_WEIGHTS_V5_SEAS)
MODELS = {"icw8": W8, "icw5_seas": W5}
ALLF = list(dict.fromkeys(list(W8) + list(W5)))
ANN = 252.0 / 40.0
H15 = 15.0 / 1e4 / 2.0

B.FEATS[1] = FEATS1     # WO-58's frozen copy (sha asserted by cb_core.load_signal too)


def log(m):
    print(f"[{time.strftime('%H:%M:%S')}] {m}", flush=True)


def sha256(p):
    h = hashlib.sha256()
    with open(p, "rb") as f:
        for b in iter(lambda: f.read(1 << 20), b""):
            h.update(b)
    return h.hexdigest()


def guard_inputs(paths=None):
    got = sha256(REPO / PLAN)
    assert got == PLAN_SHA, f"plan doc changed: {got}"
    for p in (paths or SHA):
        assert sha256(p) == SHA[p], f"input changed since plan: {p}"


def dump(name, obj):
    (OUT / name).write_text(json.dumps(obj, indent=1, default=float))
    log(f"wrote {OUT / name}")


def spac_filter(p):
    old_t = set(pd.read_parquet(R26 / "composite_panel.parquet", columns=["ticker"])["ticker"].astype(str).unique())
    tm = pd.read_csv(MAIN / "data" / "sharadar" / "tickers_master.csv", dtype=str,
                     usecols=["ticker", "sicindustry"]).drop_duplicates("ticker")
    spac = set(tm.loc[tm["sicindustry"].fillna("").str.contains("Blank Check"), "ticker"])
    return p[p.ticker.isin(old_t) | ~p.ticker.isin(spac)]


def load_panel(lo=ERA[0], hi=ERA[1]):
    """v2 col c rows (cap150 or cap2000), SPAC-excluded, + seas + label + SPY. Entry dates in [lo, hi]."""
    assert lo >= pd.Timestamp("2007-01-01") and hi <= ERA[1]
    cols = ["ticker", "date", "eligible_cap150", "eligible_cap2000"] + [c for c in ALLF if c != "seas"]
    filt = [("date", ">=", lo), ("date", "<=", hi)]
    sfilt = [("date", ">=", lo.strftime("%Y-%m-%d")), ("date", "<=", hi.strftime("%Y-%m-%d"))]   # panel date is a string
    p = pd.read_parquet(PANEL_V2, columns=cols, filters=sfilt)
    p = p[p.eligible_cap150 | p.eligible_cap2000]
    p["date"] = pd.to_datetime(p.date); p["ticker"] = p.ticker.astype(str)
    p = spac_filter(p)
    s = pd.read_parquet(B.SEAS_EXT, columns=["ticker", "date", "seas"], filters=filt)
    s["date"] = pd.to_datetime(s.date); s["ticker"] = s.ticker.astype(str)
    p = p.merge(s, on=["ticker", "date"], how="left")
    o = pd.read_parquet(OUTCOME_V2, columns=["ticker", "date", "gross_return_40", "truncated"], filters=filt)
    o["date"] = pd.to_datetime(o.date); o["ticker"] = o.ticker.astype(str)
    assert o.date.max() <= hi
    spy = o[o.ticker == "SPY"].set_index("date").gross_return_40
    n = len(p)
    p = p.merge(o[~o.ticker.isin(["SPY", "USMV"])], on=["ticker", "date"], how="left")
    assert len(p) == n
    p["thin"] = p.eligible_cap150 & ~p.eligible_cap2000
    return p.sort_values(["date", "ticker"]).reset_index(drop=True), spy


def prep_dates(p, spy, tiers=("cap150", "cap2000", "thin")):
    """Per-date numpy blocks per tier (rows in ticker order, as WO-6/WO-58 frames)."""
    out = {t: [] for t in tiers}
    flag = {"cap150": "eligible_cap150", "cap2000": "eligible_cap2000", "thin": "thin"}
    for d, g in p.groupby("date", sort=True):
        for t in tiers:
            e = g[g[flag[t]].to_numpy()]
            out[t].append({"date": pd.Timestamp(d), "n": len(e), "tick": e.ticker.to_numpy(),
                           "vol": e.volatility_60.to_numpy(np.float64),
                           "F": {c: e[c].to_numpy(np.float64) for c in ALLF},
                           "ret": e.gross_return_40.to_numpy(np.float64),
                           "spy": float(spy.get(d, np.nan))})
    return out


def score(F, w, keep=None, seas_neutral=False):
    """compute_composite_ic_weighted on numpy (rank within kept rows). seas_neutral: NaN seas -> rank_z 0."""
    n = len(next(iter(F.values())))
    sub = np.arange(n) if keep is None else np.flatnonzero(keep)
    num = np.zeros(len(sub)); den = np.zeros(len(sub)); cov = np.zeros(len(sub))
    for c, wc in w.items():
        rz = B.rank_z_np(F[c][sub])
        if seas_neutral and c == "seas":
            rz = np.where(np.isfinite(rz), rz, 0.0)
        ok = np.isfinite(rz)
        num += np.where(ok, rz * wc, 0.0)
        den += np.where(ok, abs(wc), 0.0)
        cov += ok
    sc = np.full(n, np.nan)
    with np.errstate(invalid="ignore", divide="ignore"):
        s = np.where(den > 0, num / den, np.nan)
    s[cov == 0] = np.nan
    sc[sub] = s
    return sc


def picks_fast(dd, w, keep=None, seas_neutral=False):
    if dd["n"] < C.N_VOL_QUINTILES * 4:
        return np.empty(0, int), np.empty(0)
    return B.K.pick(dd["vol"], score(dd["F"], w, keep, seas_neutral), keep)


def realise(dd, idx, w, ret=None):
    """(gross, ticker set) with NaN-label picks dropped and weights renormalised; None if nothing left."""
    r = (dd["ret"] if ret is None else ret)[idx]
    ok = np.isfinite(r)
    if len(idx) == 0 or not ok.any():
        return None
    ww = w[ok] / w[ok].sum()
    return float(np.dot(ww, 1.0 + r[ok]) - 1.0), set(dd["tick"][idx[ok]].tolist())


def net_formula(gross, f, h=H15):
    return (1.0 + gross) * (1.0 - h * f) / (1.0 + h * f) - 1.0


def eval_offsets(recs, dates, n_off, spy):
    """recs: {date: (gross, set)}. Offsets = dates[off::n_off] restricted to dates in recs (WO-6 backtest for
    n_off=40 over all dates; WO-58/WO-36 2-offset rule for n_off=2 over the kept dates). Net 15bp, minus SPY."""
    per_off, loyo_acc, nd = [], {}, []
    for off in range(n_off):
        prev, ex, yrs = set(), [], []
        for d in dates[off::n_off]:
            if d not in recs:
                continue
            g, cur = recs[d]
            f = sum(1 for t in cur if t not in prev) / len(cur)
            prev = cur
            s = spy.get(d, np.nan)
            if np.isfinite(s):
                ex.append(net_formula(g, f) - s); yrs.append(d.year)
        ex, yrs = np.array(ex), np.array(yrs)
        nd.append(len(ex))
        per_off.append(float(ex.mean() * ANN) if len(ex) else np.nan)
        for y in np.unique(yrs):
            loyo_acc.setdefault(int(y), []).append(float(ex[yrs != y].mean() * ANN))
    loyo = {y: float(np.mean(v)) for y, v in loyo_acc.items()}
    po = np.array(per_off)
    return {"mean": float(np.nanmean(po)), "sd": float(np.nanstd(po)), "min": float(np.nanmin(po)),
            "max": float(np.nanmax(po)), "n_offsets": int(np.isfinite(po).sum()),
            "offsets_positive": int((po > 0).sum()), "per_offset": per_off, "n_dates_per_offset": nd,
            "loyo_min": min(loyo.values()) if loyo else None,
            "loyo_min_year": min(loyo, key=loyo.get) if loyo else None}


def two_off_dates(recs):
    """WO-58 2-offset rule: interleave over the dates that have a realised book."""
    return sorted(recs)
