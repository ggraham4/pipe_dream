"""
Era-transfer (Experiment A) and AV option factors (Experiment B).
Spec: PREREGISTRATION.md, "Era-transfer + AV option factors (2026-09-22)".
Read it first -- every threshold below is copied from there, not chosen here.

    python3 era_transfer.py --smoke                 # plumbing + named asserts, no metrics
    python3 era_transfer.py --exp B --stage screen  # nominate era 2008-2018
    python3 era_transfer.py --exp B --stage confirm # ONE shot, frozen admitted list
    python3 era_transfer.py --exp A                 # needs the pre-2005 backfill panel

The IC machinery (pooled per-date Spearman, Newey-West t with lag 39) and the
IC-shrinkage weight rule are copied verbatim from the factor-composite-audit
worktree's ic_weighted_composite.py (not yet pushed when this was written), so
that both sessions measure the same thing the same way.
"""
from __future__ import annotations

import argparse
import json
import sys
import time
from pathlib import Path

import numpy as np
import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parent))
import composite as C  # noqa: E402

MAIN = Path("/Users/ggraham/pipe_dream/final")
PANEL_PATH = MAIN / "out" / "reset2026" / "composite_panel.parquet"
UNIVERSE_V2 = MAIN / "data" / "sharadar" / "downcap_universe_v2.parquet"
OPT_FEATURES = MAIN / "out" / "av_options_features.parquet"
OUT_DIR = MAIN / "out" / "reset2026"
LABEL = "forward_return_tradable_40"
NW_LAG = 39
FLOOR = 0.1
TIER = "cap2000"   # Amendment 1: cap500/cap150 grid is survivorship-selected
MIN_POOL_COVERAGE = 0.99

# audit worktree's 8-factor set, signs as FACTOR_SIGNS (asset_growth dropped)
BASE_SIGNS = {
    "momentum_12_1": +1, "pct_from_high_252": +1, "volatility_60": -1,
    "gross_profitability": +1, "accruals": -1, "net_issuance_pct": -1,
    "days_to_next_filing_seasonal": -1, "short_interest_days_to_cover": -1,
}
# audit worktree PRODUCTION_WEIGHTS (fit 2007-2019), for 2020+ reference only
PRODUCTION_WEIGHTS = {
    "momentum_12_1": 0.0497, "pct_from_high_252": 0.0130, "volatility_60": -0.0130,
    "gross_profitability": 0.5956, "accruals": -0.1627, "net_issuance_pct": -0.1399,
    "days_to_next_filing_seasonal": -0.0130, "short_interest_days_to_cover": -0.0130,
}
OPTION_SIGNS = {  # pre-registered table
    "opt_cw_spread": +1, "opt_rr25": -1, "opt_os_ratio": -1,
    "opt_pc_vol_ratio": -1, "opt_vrp": -1,
}
NOMINATE_B = (pd.Timestamp("2008-01-01"), pd.Timestamp("2018-12-31"))
CONFIRM_B = (pd.Timestamp("2019-01-01"), pd.Timestamp("2026-08-31"))
TRAIN_A = (pd.Timestamp("1998-12-01"), pd.Timestamp("2006-12-31"))
TEST_A = (pd.Timestamp("2007-01-01"), pd.Timestamp("2026-08-31"))
NULL_DRAWS = 20
NULL_PCTILE = 0.80


def log(m):
    print(f"[{time.strftime('%H:%M:%S')}] {m}", flush=True)


# ---------------------------------------------------------------- IC (verbatim)
def newey_west_mean_t(x, lag=NW_LAG):
    x = np.asarray(x, dtype=np.float64)
    x = x[np.isfinite(x)]
    n = len(x)
    if n < 10:
        return {"mean": np.nan, "t": np.nan, "n": n}
    xc = x - x.mean()
    L = min(lag, n - 1)
    var = np.dot(xc, xc) / n
    for l in range(1, L + 1):
        w = 1.0 - l / (L + 1.0)
        var += 2.0 * w * (np.dot(xc[l:], xc[:-l]) / n)
    var = max(var, 1e-12)
    t = x.mean() / np.sqrt(var / n) if var > 0 else np.nan
    return {"mean": float(x.mean()), "t": float(t), "n": int(n)}


def per_date_ic(df, xcol, ycol=LABEL):
    g = df[["date", xcol, ycol]].dropna()
    out = {}
    for d, gd in g.groupby("date"):
        if len(gd) < 20:
            continue
        c = gd[xcol].corr(gd[ycol], method="spearman")
        if pd.notna(c):
            out[d] = float(c)
    return pd.Series(out).sort_index()


def pooled(df, xcol):
    s = per_date_ic(df, xcol)
    st = newey_west_mean_t(s.to_numpy())
    st["n_dates"] = int(len(s))
    return st


def fit_weights(t_stats, signs):
    raw = {c: signs[c] * (max(FLOOR, abs(t_stats[c]["t"]) - 1.0)
                          if np.isfinite(t_stats[c]["t"]) else FLOOR) for c in signs}
    tot = sum(abs(v) for v in raw.values())
    return {c: v / tot for c, v in raw.items()}


def weighted_score(g, weights):
    """Coverage-renormalised weighted rank score (audit's compute_weighted_score)."""
    num = pd.Series(0.0, index=g.index)
    den = pd.Series(0.0, index=g.index)
    for c, w in weights.items():
        rz = C.rank_z(g[c])
        num = num.add((rz * w).fillna(0.0))
        den = den.add(np.where(rz.notna(), abs(w), 0.0))
    return pd.Series(np.where(den > 0, num / den, np.nan), index=g.index)


def score_frame(df, weights, col="score"):
    parts = []
    for d, g in df.groupby("date"):
        parts.append(pd.Series(weighted_score(g, weights).to_numpy(), index=g.index))
    out = df.copy()
    out[col] = pd.concat(parts)
    return out


def neutralise(df, cols):
    parts = [C.neutralize_on_sector(g, cols) for _, g in df.groupby("date")]
    return pd.concat(parts)


# ---------------------------------------------------------------- data
def load_panel(start=None, end=None):
    cols = ["ticker", "date", "sector", LABEL] + list(BASE_SIGNS)
    p = pd.read_parquet(PANEL_PATH, columns=cols)
    p["date"] = pd.to_datetime(p["date"])
    if start is not None:
        p = p[(p.date >= start) & (p.date <= end)]
    u = pd.read_parquet(UNIVERSE_V2, columns=["date", "ticker", f"eligible_{TIER}"])
    u["date"] = pd.to_datetime(u["date"])
    # Pool integrity (Amendment 1): the panel must contain essentially every
    # v2-eligible name-date for this tier, or the tier is a selected sample.
    ue = u[u[f"eligible_{TIER}"]]
    if start is not None:
        ue = ue[(ue.date >= start) & (ue.date <= end)]
    have = ue.merge(p[["date", "ticker"]], on=["date", "ticker"], how="left", indicator=True)
    cov = (have["_merge"] == "both").mean()
    log(f"pool integrity: {cov:.2%} of v2 {TIER}-eligible name-dates present in the panel")
    if cov < MIN_POOL_COVERAGE:
        raise SystemExit(f"{TIER}: only {cov:.1%} of eligible name-dates are in the feature grid "
                         f"(< {MIN_POOL_COVERAGE:.0%}); the tier is a selected sample. See Amendment 1.")
    p = p.merge(u, on=["date", "ticker"], how="inner")
    p = p[p[f"eligible_{TIER}"]].drop(columns=[f"eligible_{TIER}"])
    return p


def load_options(panel):
    f = pd.read_parquet(OPT_FEATURES)
    f = f[f.source == "av_monthly"].drop(columns=["source"])
    f["date"] = pd.to_datetime(f["date"])
    m = panel.merge(f, on=["date", "ticker"], how="inner")   # exact AV dates only
    vol60 = pd.read_parquet(PANEL_PATH, columns=["ticker", "date", "volatility_60"])
    vol60["date"] = pd.to_datetime(vol60["date"])
    if "volatility_60" not in m:
        m = m.merge(vol60, on=["date", "ticker"], how="left")
    m["opt_vrp"] = m["opt_atm_iv"] - m["volatility_60"] * np.sqrt(252.0)
    return m


def named_asserts(m):
    """Gate A7c: name what must be there. These are facts, not statistics."""
    checks = []
    d0 = pd.Timestamp("2008-01-02")
    for tk in ["AAPL", "WB1", "LEHMQ", "BSC1"]:
        r = m[(m.ticker == tk) & (m.date == d0)]
        checks.append((f"{tk} present on {d0.date()}", len(r) == 1))
        if len(r):
            iv = r.opt_atm_iv.iloc[0]
            checks.append((f"{tk} ATM IV in (0.1, 1.5): {iv:.3f}", 0.1 < iv < 1.5))
    r = m[(m.ticker == "AAPL") & (m.date == d0)]
    if len(r):
        checks.append((f"AAPL vrp finite: {r.opt_vrp.iloc[0]:.3f}", np.isfinite(r.opt_vrp.iloc[0])))
        checks.append((f"AAPL label finite: {r[LABEL].iloc[0]:.3f}", np.isfinite(r[LABEL].iloc[0])))
    ok = all(c for _, c in checks)
    for name, c in checks:
        log(f"  {'PASS' if c else 'FAIL'}  {name}")
    return ok


# ---------------------------------------------------------------- Experiment B
def exp_b_screen(m, rng):
    m = m[(m.date >= NOMINATE_B[0]) & (m.date <= NOMINATE_B[1])].copy()
    log(f"B/screen: {len(m):,} optionable name-dates, {m.date.nunique()} dates")
    neu = neutralise(m, list(OPTION_SIGNS) + list(BASE_SIGNS))
    base_t = {c: pooled(m, c) for c in BASE_SIGNS}
    base_w = fit_weights(base_t, BASE_SIGNS)  # same rule, fit on these matched rows
    res = {}
    for c, sgn in OPTION_SIGNS.items():
        raw, nt = pooled(m, c), pooled(neu, c)
        res[c] = {"sign": sgn, "ic_raw": raw, "ic_neutral": nt}
    # Holm on sector-neutral t, sign must match
    from scipy.stats import norm
    ps = {c: 2 * (1 - norm.cdf(abs(r["ic_neutral"]["t"]))) for c, r in res.items()}
    order = sorted(ps, key=ps.get)
    passed_screen = set()
    for i, c in enumerate(order):
        if ps[c] <= 0.05 / (len(order) - i):
            if np.sign(res[c]["ic_neutral"]["mean"]) == res[c]["sign"]:
                passed_screen.add(c)
        else:
            break
    # admission: composite+factor vs composite, same rows, vs shuffle null
    for c in OPTION_SIGNS:
        rows = m[m[c].notna()].copy()
        w_plus = dict(base_w)
        w_plus[c] = OPTION_SIGNS[c] * max(FLOOR, abs(res[c]["ic_neutral"]["t"]) - 1.0) \
            / sum(abs(v) for v in base_w.values()) if np.isfinite(res[c]["ic_neutral"]["t"]) else OPTION_SIGNS[c] * FLOOR
        ic_base = per_date_ic(score_frame(rows, base_w), "score")
        ic_plus = per_date_ic(score_frame(rows, w_plus), "score")
        diff = (ic_plus - ic_base).dropna()
        real = float(diff.mean())
        nulls = []
        for _ in range(NULL_DRAWS):
            sh = rows.copy()
            sh[c] = sh.groupby("date")[c].transform(lambda s: s.sample(frac=1, random_state=int(rng.integers(1 << 30))).to_numpy())
            nulls.append(float((per_date_ic(score_frame(sh, w_plus), "score") - ic_base).dropna().mean()))
        p80 = float(np.quantile(nulls, NULL_PCTILE))
        res[c].update({"admission_ic_gain": real, "admission_gain_t": newey_west_mean_t(diff.to_numpy())["t"],
                       "null_p80": p80, "null_median": float(np.median(nulls)),
                       "passed_screen": c in passed_screen, "admitted": (c in passed_screen) and real > p80,
                       "weight_if_admitted": w_plus[c]})
    return {"stage": "screen", "era": [str(x.date()) for x in NOMINATE_B], "base_weights": base_w,
            "factors": res, "admitted": [c for c in res if res[c]["admitted"]]}


def exp_b_confirm(m, screen):
    admitted = screen["admitted"]
    if not admitted:
        return {"stage": "confirm", "note": "nothing admitted at screen; confirmation not run"}
    m = m[(m.date >= CONFIRM_B[0]) & (m.date <= CONFIRM_B[1])].copy()
    base_w = screen["base_weights"]
    w_plus = dict(base_w)
    for c in admitted:
        w_plus[c] = screen["factors"][c]["weight_if_admitted"]
    rows = m.dropna(subset=admitted)
    diff = (per_date_ic(score_frame(rows, w_plus), "score") - per_date_ic(score_frame(rows, base_w), "score")).dropna()
    st = newey_west_mean_t(diff.to_numpy())
    yrs = diff.groupby(diff.index.year).mean()
    loyo = {int(y): float(diff[diff.index.year != y].mean()) for y in yrs.index}
    ok = st["mean"] > 0 and st["t"] >= 1.5 and all(v > 0 for v in loyo.values())
    return {"stage": "confirm", "era": [str(x.date()) for x in CONFIRM_B], "admitted": admitted,
            "ic_gain": st, "by_year": {int(k): float(v) for k, v in yrs.items()}, "loyo": loyo, "confirmed": ok}


# ---------------------------------------------------------------- Experiment A
def exp_a(panel):
    tr = panel[(panel.date >= TRAIN_A[0]) & (panel.date <= TRAIN_A[1])]
    te = panel[(panel.date >= TEST_A[0]) & (panel.date <= TEST_A[1])]
    if tr.date.nunique() < 1500:
        raise SystemExit(f"TRAIN era has {tr.date.nunique()} dates (< 1500): the pre-2005 backfill "
                         "has not been built into the panel yet. See sharadar_backfill_1998.sh.")
    t_tr = {c: pooled(tr, c) for c in BASE_SIGNS}
    w_tr = fit_weights(t_tr, BASE_SIGNS)
    w_eq = {c: s / len(BASE_SIGNS) for c, s in BASE_SIGNS.items()}
    ic_tr = per_date_ic(score_frame(te, w_tr), "score")
    ic_eq = per_date_ic(score_frame(te, w_eq), "score")
    diff = (ic_tr - ic_eq).dropna()
    st = newey_west_mean_t(diff.to_numpy())
    yrs = diff.groupby(diff.index.year).mean()
    adopt = st["t"] >= 2.0 and (yrs > 0).mean() >= 2 / 3
    late = te[te.date >= pd.Timestamp("2020-01-01")]
    ref = {"train_fit": newey_west_mean_t(per_date_ic(score_frame(late, w_tr), "score").to_numpy()),
           "production_2007_2019_fit": newey_west_mean_t(per_date_ic(score_frame(late, PRODUCTION_WEIGHTS), "score").to_numpy())}
    return {"train": [str(x.date()) for x in TRAIN_A], "test": [str(x.date()) for x in TEST_A],
            "train_t": t_tr, "train_weights": w_tr, "test_ic_trainfit": newey_west_mean_t(ic_tr.to_numpy()),
            "test_ic_equal": newey_west_mean_t(ic_eq.to_numpy()), "test_ic_gain": st,
            "gain_by_year": {int(k): float(v) for k, v in yrs.items()}, "adopt_trainfit_weights": bool(adopt),
            "reference_2020_2026": ref}


# ---------------------------------------------------------------- main
def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--smoke", action="store_true")
    ap.add_argument("--tier", default="cap2000", choices=["cap2000", "cap500", "cap150"])
    ap.add_argument("--exp", choices=["A", "B"])
    ap.add_argument("--stage", choices=["screen", "confirm"], default="screen")
    a = ap.parse_args()
    globals()["TIER"] = a.tier
    rng = np.random.default_rng(20260922)

    if a.smoke:
        f = pd.read_parquet(OPT_FEATURES)
        dates = sorted(pd.to_datetime(f[f.source == "av_monthly"].date).unique())
        log(f"smoke: {len(dates)} av_monthly dates in features: {[str(d.date()) for d in dates[:5]]}")
        p = load_panel(dates[0], dates[-1])
        m = load_options(p)
        log(f"smoke: panel {len(p):,} rows (v2 {TIER}), optionable matched {len(m):,} "
            f"({len(m)/max(len(p[p.date.isin(dates)]),1):.0%} of panel rows on those dates)")
        ok = named_asserts(m)
        for c in OPTION_SIGNS:
            log(f"  column {c}: non-null {m[c].notna().mean():.0%}")
        # one null draw end to end, result NOT printed (pre-registration: no metrics from 3 dates)
        sh = m.copy()
        sh["opt_cw_spread"] = sh.groupby("date")["opt_cw_spread"].transform(lambda s: s.sample(frac=1, random_state=1).to_numpy())
        _ = per_date_ic(score_frame(sh, {**{k: v / 8 for k, v in BASE_SIGNS.items()}, "opt_cw_spread": 0.1}), "score")
        log(f"smoke: shuffle-null path ran ({len(_)} dates scored). named asserts {'PASS' if ok else 'FAIL'}")
        sys.exit(0 if ok else 1)

    if a.exp == "B":
        p = load_panel(NOMINATE_B[0], CONFIRM_B[1])
        m = load_options(p)
        if not named_asserts(m):
            raise SystemExit("named asserts failed -- not computing anything")
        path = OUT_DIR / "av_option_factors_screen.json"
        if a.stage == "screen":
            if m[m.date <= NOMINATE_B[1]].date.nunique() < 120:
                raise SystemExit("nominate era needs >= 120 of the ~132 monthly dates landed; check the pull --status")
            out = exp_b_screen(m, rng)
            path.write_text(json.dumps(out, indent=2, default=float))
        else:
            if not path.exists():
                raise SystemExit("run --stage screen first; confirmation needs the frozen admitted list")
            out = exp_b_confirm(m, json.loads(path.read_text()))
            cpath = OUT_DIR / "av_option_factors_confirm.json"
            if cpath.exists():
                raise SystemExit(f"{cpath} exists: confirmation is ONE shot (pre-registered)")
            cpath.write_text(json.dumps(out, indent=2, default=float))
        log(json.dumps(out, indent=1, default=float)[:3000])
    elif a.exp == "A":
        out = exp_a(load_panel())
        (OUT_DIR / "era_transfer_A.json").write_text(json.dumps(out, indent=2, default=float))
        log(json.dumps(out, indent=1, default=float)[:3000])


if __name__ == "__main__":
    main()
