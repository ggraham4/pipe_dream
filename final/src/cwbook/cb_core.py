"""
WO-58 core: opt_cw_spread avoid-screen inside a thin-slice (cap150 AND NOT cap2000) long book.
Pre-registration: final/models/2026-10-10-cwspread-downcap-book.md.

Reuses, never edits: cwweights/cw_core.py (pick = composite.pick_decile_volq on numpy, evaluate =
run_expB.portfolio with 2 interleaved offsets, net 15bp via the turnover formula), thinliq/tl_common.py
(thin-slice definition, read_on_dates), reset2026 (composite.rank_z, ic_weighted_composite weights).
Signal: opt_cw_spread exactly as built by WO-52 (2008-2018) and WO-55 (2019-2025) -- their feature files
are copied byte-for-byte into final/out/cwbook/ (sha256 in the pre-reg).

Labels are attached only by attach_labels(); everything above it is label-free.
NEVER TRADES: research code, no broker or order code anywhere.
"""
from __future__ import annotations

import sys
import time
from pathlib import Path

import numpy as np
import pandas as pd
from scipy.stats import rankdata

HERE = Path(__file__).resolve().parent
SRC = HERE.parent
FINAL = HERE.parents[1]
for p in (SRC / "cwweights", SRC / "thinliq", SRC / "options_wo25", SRC / "reset2026"):
    if str(p) not in sys.path:
        sys.path.insert(0, str(p))
import cw_core as K                 # noqa: E402  (imports run_expB -> composite, era_transfer, run_backtest)
import tl_common as T               # noqa: E402
import ic_weighted_composite as ICW  # noqa: E402

RX, C = K.RX, K.C
OUT = FINAL / "out" / "cwbook"
FEATS = {1: OUT / "feats_stage1_wo52.parquet", 2: OUT / "feats_stage2_wo55.parquet"}
FEATS_SHA = {1: "c6783045523ca80c1f59e02ebb3035f76f1ade9b994327f14e97d8f69eb03801",
             2: "d7778e048964d3289ba7f78419ce8fe0e73f61081db520358013e9889f09ef0e"}
SEAS_EXT = Path("/Users/ggraham/pipe_dream/.claude/worktrees/wo24-construction-drag/final/out/audit/seas_factor_ext.parquet")
SEAS_SHA = "ca9721d3879bca0b2340bea660ca43949a485fb9bd9cd2513614dd4137f52e2c"
MAIN = Path("/Users/ggraham/pipe_dream/final")
R26 = MAIN / "out" / "reset2026"
PANEL_V2 = R26 / "composite_panel_v2.parquet"
OUTCOME_V2 = R26 / "outcome_cache_v2.parquet"
OLD_PANEL = R26 / "composite_panel.parquet"
TICKERS_MASTER = MAIN / "data" / "sharadar" / "tickers_master.csv"
SIG = "opt_cw_spread"
DECILE = 0.10
W5 = dict(ICW.PRODUCTION_WEIGHTS_V5_SEAS)     # frozen live icw5_seas weights
FT = list(W5)
STAGE_WINDOW = {1: (pd.Timestamp("2008-01-01"), pd.Timestamp("2018-12-31")),
                2: (pd.Timestamp("2019-01-01"), pd.Timestamp("2025-08-31"))}
N_DATES = {1: 133, 2: 80}
ANN = K.ANN
N_OFF = K.N_OFF


def log(m):
    print(f"[{time.strftime('%H:%M:%S')}] {m}", flush=True)


def sha256(p):
    import hashlib
    h = hashlib.sha256()
    with open(p, "rb") as f:
        for b in iter(lambda: f.read(1 << 20), b""):
            h.update(b)
    return h.hexdigest()


# ------------------------------------------------------------------ label-free loading
def load_signal(stage):
    assert sha256(FEATS[stage]) == FEATS_SHA[stage], "feature file changed since freeze"
    f = pd.read_parquet(FEATS[stage], columns=["date", "ticker", SIG])
    f["date"] = pd.to_datetime(f.date); f["ticker"] = f.ticker.astype(str)
    lo, hi = STAGE_WINDOW[stage]
    assert f.date.min() >= lo and f.date.max() <= hi, "signal outside stage window"
    dates = sorted(f.date.unique())
    assert len(dates) == N_DATES[stage], len(dates)
    return f, [pd.Timestamp(d) for d in dates]


def load_book(stage):
    """Label-free frame: thin slice (WO-37: eligible_cap150 & ~eligible_cap2000 in downcap_universe_v2),
    intersected with v2 col c panel rows (col-c blank-check exclusion as in the live loader), plus seas,
    plus the WO-52/WO-55 signal and the bottom-decile flag. One row per (date, ticker)."""
    f, dates = load_signal(stage)
    u = T.universe_on(dates)
    thin = u[u.thin][["date", "ticker", "closeunadj"]].drop_duplicates(["date", "ticker"])
    # signal pool = thin names with a kept chain and a non-missing signal (WO-52 frame, label-free)
    pool = thin.merge(f, on=["date", "ticker"], how="left")
    chain_rows = f[["date", "ticker"]].drop_duplicates().assign(_c=True)   # a features row exists = kept chain
    pool = pool.merge(chain_rows, on=["date", "ticker"], how="left")
    pool["has_chain"] = pool._c.fillna(False).astype(bool)
    pool = pool.drop(columns="_c").sort_values(["date", "ticker"]).reset_index(drop=True)
    pool["bottom"] = False
    for d, g in pool.groupby("date", sort=True):
        g = g[g[SIG].notna()]
        n = len(g)
        k = max(1, int(round(DECILE * n)))
        b = np.argsort(g[SIG].to_numpy(float), kind="stable")[:k]
        pool.loc[g.index[b], "bottom"] = True
    # v2 col c features
    cols = ["ticker", "date", "sector", "volatility_60"] + [c for c in FT if c != "seas"]
    p = T.read_on_dates(PANEL_V2, cols, dates)
    p["date"] = pd.to_datetime(p.date); p["ticker"] = p.ticker.astype(str)
    old_t = set(pd.read_parquet(OLD_PANEL, columns=["ticker"])["ticker"].astype(str).unique())
    tm = pd.read_csv(TICKERS_MASTER, dtype=str, usecols=["ticker", "sicindustry"]).drop_duplicates("ticker")
    spac = set(tm.loc[tm["sicindustry"].fillna("").str.contains("Blank Check"), "ticker"])
    n_before = len(p)
    p = p[p.ticker.isin(old_t) | ~p.ticker.isin(spac)]
    assert sha256(SEAS_EXT) == SEAS_SHA
    s = pd.read_parquet(SEAS_EXT, columns=["ticker", "date", "seas"])
    s["date"] = pd.to_datetime(s.date); s["ticker"] = s.ticker.astype(str)
    s = s[s.date.isin(dates)]
    p = p.merge(s, on=["ticker", "date"], how="left")
    b = pool.merge(p, on=["date", "ticker"], how="inner").sort_values(["date", "ticker"]).reset_index(drop=True)
    info = {"stage": stage, "dates": len(dates), "thin_name_dates": int(len(pool)),
            "thin_with_kept_chain_share": float(pool.has_chain.mean()),
            "thin_with_signal_share": float(pool[SIG].notna().mean()),
            "book_pool_name_dates": int(len(b)),
            "book_pool_share_of_thin": float(len(b) / len(pool)),
            "col_c_blank_check_rows_dropped": int(n_before - len(p)),
            "seas_coverage_in_book_pool": float(b.seas.notna().mean()),
            "bottom_flags_in_pool": int(pool.bottom.sum()), "bottom_flags_in_book_pool": int(b.bottom.sum())}
    return b, pool, dates, info


def prep(b):
    """Per-date numpy arrays (label-free)."""
    tick_code, uniq = pd.factorize(b.ticker)
    D = []
    for d, g in b.groupby("date", sort=True):
        ix = g.index.to_numpy()
        D.append({"date": pd.Timestamp(d), "n": len(g), "ix": ix,
                  "vol": g.volatility_60.to_numpy(np.float64),
                  "F": np.column_stack([g[c].to_numpy(np.float64) for c in FT]),
                  "has_sig": g[SIG].notna().to_numpy(), "has_chain": g.has_chain.to_numpy(),
                  "bottom": g.bottom.to_numpy(), "tick": tick_code[ix], "close": g.closeunadj.to_numpy(np.float64)})
    return D, uniq


def rank_z_np(x):
    """composite.rank_z on a numpy column: average-rank to [-0.5, 0.5], NaN kept, n<2 -> all NaN."""
    out = np.full(len(x), np.nan)
    ok = np.isfinite(x)
    n = int(ok.sum())
    if n < 2:
        return out
    out[ok] = (rankdata(x[ok], method="average") - 1.0) / (n - 1.0) - 0.5
    return out


def score_icw5(F, keep=None):
    """ic_weighted_composite.compute_composite_ic_weighted(weights=W5) on the kept rows (ranked among them)."""
    n = F.shape[0]
    sub = np.arange(n) if keep is None else np.flatnonzero(keep)
    num = np.zeros(len(sub)); den = np.zeros(len(sub)); cov = np.zeros(len(sub))
    for j, c in enumerate(FT):
        rz = rank_z_np(F[sub, j])
        ok = np.isfinite(rz)
        num += np.where(ok, rz * W5[c], 0.0)
        den += np.where(ok, abs(W5[c]), 0.0)
        cov += ok
    sc = np.full(n, np.nan)
    with np.errstate(invalid="ignore", divide="ignore"):
        s = np.where(den > 0, num / den, np.nan)
    s[cov == 0] = np.nan
    sc[sub] = s
    return sc


def picks_for(dd, keep=None):
    """Rank (icw5_seas) and pick (pick_decile_volq) on the kept pool. Returns (row idx, weight)."""
    sc = score_icw5(dd["F"], keep)
    return K.pick(dd["vol"], sc, keep)


# ------------------------------------------------------------------ labels
def attach_labels(D, b, dates, stage):
    lo, hi = STAGE_WINDOW[stage]
    assert all(lo <= d <= hi for d in dates), "HOLD-OUT BREACH: date outside stage window"
    o = pd.read_parquet(OUTCOME_V2, columns=["ticker", "date", "gross_return_40"],
                        filters=[("date", "in", [d.to_pydatetime() for d in dates])])
    o["ticker"] = o.ticker.astype(str); o["date"] = pd.to_datetime(o.date)
    assert o.date.max() <= hi
    spy = o[o.ticker == "SPY"].set_index("date").gross_return_40
    y = b[["date", "ticker"]].merge(o[~o.ticker.isin(["SPY", "USMV"])], on=["date", "ticker"], how="left").gross_return_40
    y = y.to_numpy(np.float64)
    for dd in D:
        dd["ret"] = y[dd["ix"]]
        dd["spy"] = float(spy.get(dd["date"], np.nan))
    return D


# ------------------------------------------------------------------ evaluation
def evaluate(D, picks, cost_bps=15.0):
    """cw_core.evaluate with a cost parameter (checked equal to it at 15bp). Also returns per-date gross,
    names held and pick sets."""
    h = (cost_bps / 1e4) / 2.0
    kept = []
    for i, dd in enumerate(D):
        idx, w = picks[i]
        if len(idx) == 0:
            continue
        r = dd["ret"][idx]
        ok = np.isfinite(r)
        if not ok.any():
            continue
        ww = w[ok] / w[ok].sum()
        gross = float(np.dot(ww, 1.0 + r[ok]) - 1.0)
        kept.append((dd["date"], gross, dd["tick"][idx[ok]], dd["spy"]))
    per_off = []
    for off in range(N_OFF):
        prev = np.empty(0, int)
        ds, ex, fn, gr = [], [], [], []
        for d, gross, cur, s in kept[off::N_OFF]:
            f = float((~np.isin(cur, prev)).mean())
            net = (1.0 + gross) * (1.0 - h * f) / (1.0 + h * f) - 1.0
            prev = cur
            fn.append(f)
            if np.isfinite(s):
                ds.append(d); ex.append(net - s); gr.append(gross - s)
        per_off.append({"dates": ds, "ex": np.array(ex), "gx": np.array(gr), "f_new": float(np.mean(fn)) if fn else np.nan,
                        "year": np.array([d.year for d in ds])})
    return per_off, len(kept)


def level(ev, key="ex"):
    return float(np.mean([o[key].mean() * ANN for o in ev if len(o[key])]))


def delta_stats(ev_v, ev_b):
    """Variant minus base, net %/yr (fractions here). Offsets = 2 interleaved monthly date sets (WO-36 rule).
    LOYO drops a calendar year from each offset's per-date records (turnover chains kept as on the full
    sequence, WO-36 rule). Year share = year's sum of per-date deltas / total sum (all dates pooled)."""
    for a, b in zip(ev_v, ev_b):
        if a["dates"] != b["dates"]:
            raise SystemExit("variant and base books are not on the same dates: stop and report")
    d_off = [float((a["ex"] - b["ex"]).mean() * ANN) for a, b in zip(ev_v, ev_b)]
    years = sorted(set(np.concatenate([o["year"] for o in ev_v]).tolist()))
    loyo = {int(y): float(np.mean([(a["ex"] - b["ex"])[a["year"] != y].mean() * ANN for a, b in zip(ev_v, ev_b)]))
            for y in years}
    dd = np.concatenate([a["ex"] - b["ex"] for a, b in zip(ev_v, ev_b)])
    yy = np.concatenate([a["year"] for a in ev_v])
    tot = dd.sum()
    share = {int(y): float(dd[yy == y].sum() / tot) for y in years} if tot > 0 else {}
    by_year = {int(y): float(dd[yy == y].mean() * ANN) for y in years}
    halves = {"odd_years": float(np.mean([(a["ex"] - b["ex"])[a["year"] % 2 == 1].mean() * ANN for a, b in zip(ev_v, ev_b)])),
              "even_years": float(np.mean([(a["ex"] - b["ex"])[a["year"] % 2 == 0].mean() * ANN for a, b in zip(ev_v, ev_b)]))}
    return {"delta": float(np.mean(d_off)), "delta_per_offset": d_off,
            "delta_gross": float(np.mean([(a["gx"] - b["gx"]).mean() * ANN for a, b in zip(ev_v, ev_b)])),
            "loyo": loyo, "loyo_min": float(min(loyo.values())), "loyo_min_year_dropped": int(min(loyo, key=loyo.get)),
            "year_share": share, "max_year_share": (max(share.values()) if share else None),
            "delta_by_year_DESCRIPTIVE": by_year, "halves_DESCRIPTIVE": halves,
            "n_dates_per_offset": [len(o["ex"]) for o in ev_v]}


def null_keep(dd, n_remove, rng):
    """Paired random removal: n_remove names drawn uniformly from book-pool names with a kept chain (WO-58 frozen design)."""
    cand = np.flatnonzero(dd["has_chain"])
    keep = np.ones(dd["n"], bool)
    if n_remove > 0:
        keep[rng.choice(cand, size=n_remove, replace=False)] = False
    return keep
