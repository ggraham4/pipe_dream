"""
WO-36 core: call-put IV spread (opt_cw_spread) under fixed weights or as an
exclusion screen. Design is pre-registered in
final/models/2026-10-01-cw-spread-weights.md.

Loader, label, weight rule, book and cost model are imported from
options_wo25/run_expB.py and reset2026 (never edited). This module adds a fast
path (precomputed rank scores, numpy picks) that is checked against the
imported slow path before any null uses it (run_cw.py --mode reproduce).
"""
from __future__ import annotations

import sys
from pathlib import Path

import numpy as np
import pandas as pd

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE.parent / "options_wo25"))
import run_expB as RX          # noqa: E402  (also puts reset2026 on sys.path)

C, ET = RX.C, RX.ET
CW = "opt_cw_spread"
BASE = list(RX.BASE_SIGNS)
ANN = 252.0 / 40.0
H = (RX.COST_BPS / 1e4) / 2.0
N_OFF = RX.N_OFFSETS
NQ = C.N_VOL_QUINTILES
FIXED_X = {"V1": 0.05, "V2": 0.10, "V3": 0.20}
EXCL_Q = {"V5": 0.10, "V6": 0.20}
SIX = ["V1", "V2", "V3", "V4", "V5", "V6"]
NULL_PCTILE = 0.80


# ------------------------------------------------------------------ weights
def rule_x(base_t, t_cw):
    """cw weight when the project rule is applied to t_cw and all nine are normalised."""
    w9 = RX.refit(base_t, CW, t_cw)
    return float(w9[CW]), w9


def weights9(base_w, x):
    """Nine weights with cw at x of the total and the eight base weights scaled by (1 - x)."""
    w = {c: v * (1.0 - x) for c, v in base_w.items()}
    w[CW] = float(x)
    return w


# ------------------------------------------------------------------ data prep
def prep(m, spy, base_w):
    """Per-date arrays on the rows that have cw_spread (the Experiment B book universe)."""
    rows = m[m[CW].notna()].sort_values(["date", "ticker"]).reset_index(drop=True)
    tick_code = pd.factorize(rows["ticker"])[0]
    out = []
    for d, g in rows.groupby("date", sort=True):
        num = np.zeros(len(g)); den = np.zeros(len(g))
        for c, w in base_w.items():
            rz = C.rank_z(g[c]).to_numpy(np.float64)
            ok = np.isfinite(rz)
            num += np.where(ok, rz * w, 0.0)
            den += np.where(ok, abs(w), 0.0)
        out.append({
            "date": pd.Timestamp(d), "n": len(g),
            "vol": g["volatility_60"].to_numpy(np.float64),
            "num": num, "den": den,
            "rz": C.rank_z(g[CW]).to_numpy(np.float64),
            "pct": g[CW].rank(method="average", pct=True).to_numpy(np.float64),
            "ret": g["gross_return_40"].to_numpy(np.float64),
            "tick": tick_code[g.index.to_numpy()],
            "spy": float(spy.get(d, np.nan)),
        })
    return rows, out


def score(dd, x, rz):
    den = (1.0 - x) * dd["den"] + (x if x > 0 else 0.0)
    num = (1.0 - x) * dd["num"] + (x * rz if x > 0 else 0.0)
    with np.errstate(invalid="ignore", divide="ignore"):
        return np.where(den > 0, num / den, np.nan)


def pick(vol, comp, keep=None):
    """composite.pick_decile_volq on numpy arrays. Returns (row index, weight)."""
    sub = np.arange(len(vol)) if keep is None else np.flatnonzero(keep)
    vol_s, comp_s = vol[sub], comp[sub]
    valid = np.isfinite(vol_s) & np.isfinite(comp_s)
    if valid.sum() < NQ * 4:
        return np.empty(0, int), np.empty(0)
    idx = np.flatnonzero(valid)
    vol_v, comp_v = vol_s[idx], comp_s[idx]
    q = pd.qcut(vol_v, NQ, labels=False, duplicates="drop")
    chosen = []
    for b in np.unique(q):
        b_idx = np.flatnonzero(q == b)
        k = max(1, int(round(len(b_idx) * 0.10)))
        chosen.append(b_idx[np.argsort(-comp_v[b_idx])][:k])
    ch = np.concatenate(chosen)
    inv = 1.0 / np.maximum(vol_v[ch], 1e-4)
    return sub[idx[ch]], inv / inv.sum()


def build_picks(data, xs, rng=None, variants=None):
    """Picks per variant per date. rng given: cw_spread is permuted within date
    (ONE permutation per date, shared by every variant). 'base' is added when rng is None."""
    names = list(variants) if variants is not None else (["base"] + list(xs) + list(EXCL_Q))
    if rng is not None:
        names = [v for v in names if v != "base"]
    out = {v: [] for v in names}
    for dd in data:
        if rng is None:
            rz, pct = dd["rz"], dd["pct"]
        else:
            p = rng.permutation(dd["n"])
            rz, pct = dd["rz"][p], dd["pct"][p]
        s0 = None
        for v in names:
            if v in xs:
                out[v].append(pick(dd["vol"], score(dd, xs[v], rz)))
            else:
                if s0 is None:
                    s0 = score(dd, 0.0, rz)
                keep = None if v == "base" else (pct > EXCL_Q[v])
                out[v].append(pick(dd["vol"], s0, keep))
    return out


# ------------------------------------------------------------------ evaluation
def evaluate(data, picks, rets=None, spys=None):
    """Mirror of run_expB.portfolio, keeping the per-date records.
    Returns per-offset list of dicts: dates, ex (net - spy), f_new."""
    kept = []
    for i, dd in enumerate(data):
        idx, w = picks[i]
        if len(idx) == 0:
            continue
        r = (dd["ret"] if rets is None else rets[i])[idx]
        ok = np.isfinite(r)
        if not ok.any():
            continue
        ww = w[ok] / w[ok].sum()
        gross = float(np.dot(ww, 1.0 + r[ok]) - 1.0)
        kept.append((dd["date"], gross, dd["tick"][idx[ok]], dd["spy"] if spys is None else spys[i]))
    per_off = []
    for off in range(N_OFF):
        prev = np.empty(0, int)
        ds, ex, fn = [], [], []
        for d, gross, cur, s in kept[off::N_OFF]:
            f = float((~np.isin(cur, prev)).mean())
            net = (1.0 + gross) * (1.0 - H * f) / (1.0 + H * f) - 1.0
            prev = cur
            fn.append(f)
            if np.isfinite(s):
                ds.append(d); ex.append(net - s)
        per_off.append({"dates": ds, "ex": np.array(ex), "f_new": float(np.mean(fn)) if fn else np.nan,
                        "year": np.array([d.year for d in ds])})
    return per_off, len(kept)


def level(ev, mask_fn=None):
    vals = []
    for o in ev:
        if len(o["ex"]) == 0:
            continue
        m = np.ones(len(o["ex"]), bool) if mask_fn is None else mask_fn(o["year"])
        vals.append(o["ex"][m].mean() * ANN if m.any() else np.nan)
    return float(np.mean(vals)) if vals else np.nan


def diff_stats(ev_v, ev_b, full=True):
    """Variant minus base. Subsets (halves, leave-one-year-out) drop dates from the per-date
    net-excess records of each offset; turnover chains stay as computed on the full sequence."""
    for a, b in zip(ev_v, ev_b):
        if a["dates"] != b["dates"]:
            raise SystemExit("variant and base books are not on the same dates: stop and report")
    d_off = [float((a["ex"] - b["ex"]).mean() * ANN) for a, b in zip(ev_v, ev_b)]
    out = {"excess_ann": level(ev_v), "per_offset": [float(o["ex"].mean() * ANN) for o in ev_v],
           "diff": float(np.mean(d_off)), "diff_per_offset": d_off}
    if not full:
        return out
    def sub(fn):
        return float(np.mean([(a["ex"] - b["ex"])[fn(a["year"])].mean() * ANN for a, b in zip(ev_v, ev_b)]))
    years = sorted(set(np.concatenate([o["year"] for o in ev_v]).tolist()))
    loyo = {int(y): sub(lambda yr, y=y: yr != y) for y in years}
    out.update({
        "diff_odd_years": sub(lambda yr: yr % 2 == 1), "diff_even_years": sub(lambda yr: yr % 2 == 0),
        "loyo_diff": loyo, "loyo_min": float(min(loyo.values())),
        "loyo_min_year_dropped": int(min(loyo, key=loyo.get)),
        "turnover_f_new": float(np.mean([o["f_new"] for o in ev_v])),
        "n_dates_per_offset": [len(o["ex"]) for o in ev_v],
    })
    return out


def nominated(st, null_p80):
    return bool(st["diff"] > null_p80 and all(v > 0 for v in st["diff_per_offset"]) and st["loyo_min"] > 0)


def analyse(data, xs, variants, n_draws, seed, rets=None, spys=None, null_picks=None, real_picks=None):
    """Real stats for `variants` plus the shuffled-cw null (max over `variants` per draw)."""
    rp = real_picks if real_picks is not None else build_picks(data, xs)
    ev_b, n_dates = evaluate(data, rp["base"], rets, spys)
    real = {v: diff_stats(evaluate(data, rp[v], rets, spys)[0], ev_b) for v in variants}
    base = {"excess_ann": level(ev_b), "per_offset": [float(o["ex"].mean() * ANN) for o in ev_b],
            "turnover_f_new": float(np.mean([o["f_new"] for o in ev_b])), "n_dates": n_dates,
            "n_dates_per_offset": [len(o["ex"]) for o in ev_b],
            "dates_per_year": {int(y): int(sum((o["year"] == y).sum() for o in ev_b))
                               for y in sorted(set(np.concatenate([o["year"] for o in ev_b]).tolist()))},
            "odd_years": level(ev_b, lambda yr: yr % 2 == 1), "even_years": level(ev_b, lambda yr: yr % 2 == 0)}
    draws = {v: [] for v in variants}
    for k in range(n_draws):
        if null_picks is not None:
            npk = null_picks[k]
        else:
            npk = build_picks(data, xs, np.random.default_rng(seed + k), variants)
        for v in variants:
            draws[v].append(diff_stats(evaluate(data, npk[v], rets, spys)[0], ev_b, full=False)["diff"])
    mx = np.max(np.array([draws[v] for v in variants]), axis=0)
    null = {"n_draws": n_draws, "max_over_variants_p80": float(np.quantile(mx, NULL_PCTILE)),
            "max_over_variants_median": float(np.median(mx)), "max_over_variants_draws": mx.tolist(),
            "per_variant_p80": {v: float(np.quantile(draws[v], NULL_PCTILE)) for v in variants},
            "per_variant_median": {v: float(np.median(draws[v])) for v in variants},
            "per_variant_draws": draws}
    return base, real, null
