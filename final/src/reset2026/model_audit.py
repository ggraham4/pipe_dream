"""
Physics-style diagnostic audit of the sign-constrained linear composite.

See PREREGISTRATION.md's "Model-audit pre-registration (2026-09-22)" section
for the exact spec this implements -- written before this ran. Descriptive
only: reports what the already-confirmed nomination-era model does, selects
nothing, and touches 2007-2019 only. 2020-2026 is spent for this pipeline
(see PREREGISTRATION.md's hold-out section) and nothing here reopens it.

Two candidate variables (log_market_cap, momentum_1_1) are scored for IC/sign
as nominations only -- never added to composite.FACTOR_SIGNS, never
backtested as a portfolio. Trial count: 2.

Usage: python3 model_audit.py
Output: out/reset2026/model_audit_report.json
"""
import json
import sys
import time
from pathlib import Path

import numpy as np
import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parent))
import composite as C  # noqa: E402

MAIN_ROOT = Path("/Users/ggraham/pipe_dream/final")
OUT_DIR = MAIN_ROOT / "out" / "reset2026"
PANEL_PATH = OUT_DIR / "composite_panel.parquet"
OUTCOME_PATH = OUT_DIR / "outcome_cache.parquet"
OUT_JSON = OUT_DIR / "model_audit_report.json"

NOMINATE_START = pd.Timestamp("2007-01-02")
NOMINATE_END = pd.Timestamp("2019-12-31")
LABEL = "forward_return_tradable_40"
NW_LAG = 39  # 40-day-overlapping forward returns -> serial correlation to lag 39
MOM_1_1_LOOKBACK = 21  # ~1 trading month

CANDIDATE_SIGNS = {
    "log_market_cap": -1,   # size premium (Banz 1981 / Fama-French SMB)
    "momentum_1_1": -1,     # short-term reversal (Jegadeesh 1990)
}
ALL_FACTOR_COLS = C.FACTOR_COLS + list(CANDIDATE_SIGNS)
ALL_SIGNS = {**C.FACTOR_SIGNS, **CANDIDATE_SIGNS}


def log(msg):
    print(f"[{time.strftime('%H:%M:%S')}] {msg}", flush=True)


# ---------------------------------------------------------------------------
# Statistics
# ---------------------------------------------------------------------------
def newey_west_mean_t(x, lag=NW_LAG):
    """NW-corrected t-stat for the mean of a (possibly autocorrelated) series."""
    x = np.asarray(x, dtype=np.float64)
    x = x[np.isfinite(x)]
    n = len(x)
    if n < 10:
        return {"mean": float(np.nan), "t": float(np.nan), "n": n}
    xc = x - x.mean()
    L = min(lag, n - 1)
    gamma0 = np.dot(xc, xc) / n
    var = gamma0
    for l in range(1, L + 1):
        w = 1.0 - l / (L + 1.0)
        gamma_l = np.dot(xc[l:], xc[:-l]) / n
        var += 2.0 * w * gamma_l
    var = max(var, 1e-12)
    se_mean = np.sqrt(var / n)
    t = x.mean() / se_mean if se_mean > 0 else np.nan
    return {"mean": float(x.mean()), "t": float(t), "n": int(n)}


def daily_spearman(df, xcol, ycol, date_col="date"):
    """Per-date cross-sectional Spearman IC, as a {date: ic} pandas Series.
    Iterates groups explicitly (not groupby().apply(...)) -- with a
    constant-valued or near-duplicate column .apply()'s scalar/Series
    result-type inference is not reliable across pandas versions."""
    g = df[[date_col, xcol, ycol]].dropna()
    out = {}
    for d, gd in g.groupby(date_col):
        if len(gd) < 20:
            out[d] = np.nan
            continue
        c = gd[xcol].corr(gd[ycol], method="spearman")
        out[d] = float(c) if pd.notna(c) else np.nan
    return pd.Series(out)


def pooled_ic(df, xcol, ycol="__label__", date_col="date"):
    s = daily_spearman(df, xcol, ycol, date_col)
    stats = newey_west_mean_t(s.to_numpy())
    stats["n_dates"] = int(s.notna().sum())
    return stats, s


# ---------------------------------------------------------------------------
# Load + build candidate columns
# ---------------------------------------------------------------------------
def load_panel():
    log("loading composite_panel ...")
    cols = list(dict.fromkeys(
        ["ticker", "date", "sector", "volatility_60", "market_cap", "close",
         "eligible_cap150", "eligible_cap2000", LABEL]
        + C.FACTOR_COLS
    ))
    df = pd.read_parquet(PANEL_PATH, columns=cols)
    df["date"] = pd.to_datetime(df["date"])
    df = df.sort_values(["ticker", "date"]).reset_index(drop=True)
    log(f"  {len(df):,} rows, {df['date'].min().date()}..{df['date'].max().date()}")

    log("building candidate factors: log_market_cap, momentum_1_1 ...")
    df["log_market_cap"] = np.log(df["market_cap"].where(df["market_cap"] > 0))
    df["momentum_1_1"] = df.groupby("ticker")["close"].pct_change(MOM_1_1_LOOKBACK)

    df["__label__"] = df[LABEL]
    return df


def nomination_slice(df, tier):
    m = (df["date"] >= NOMINATE_START) & (df["date"] <= NOMINATE_END) & df[f"eligible_{tier}"]
    return df.loc[m].copy()


# ---------------------------------------------------------------------------
# 1+2. Per-factor IC, sign check, coverage split
# ---------------------------------------------------------------------------
def factor_availability(nom150):
    """First/last date each factor has ANY non-null value in the cap150
    nomination slice, and the fraction of (eligible-day) rows covered.
    Gate A7c ('verify by naming what should be there'): a factor's
    IC/sign is only evidence over the calendar range it actually has data,
    not over the whole 2007-2019 window by assumption."""
    out = {}
    n_total = len(nom150)
    for fcol in ALL_FACTOR_COLS:
        nn = nom150.loc[nom150[fcol].notna(), "date"]
        out[fcol] = {
            "first_date": str(nn.min().date()) if len(nn) else None,
            "last_date": str(nn.max().date()) if len(nn) else None,
            "coverage_frac_of_eligible_rows": float(nom150[fcol].notna().mean()),
            "n_nonnull": int(len(nn)),
            "n_total_eligible_rows": int(n_total),
        }
    return out


def audit_factor_ics(nom150):
    log("1/2: per-factor IC + coverage split (cap150, nomination era) ...")
    # coverage: how many of the 9 SIGNED factors this name has, per date
    cov_parts = []
    for d, g in nom150.groupby("date"):
        cov_parts.append(pd.Series(g[C.FACTOR_COLS].notna().sum(axis=1).to_numpy(), index=g.index))
    coverage = pd.concat(cov_parts).sort_index()
    nom150 = nom150.copy()
    nom150["coverage"] = coverage

    out = {}
    for fcol in ALL_FACTOR_COLS:
        stats, s = pooled_ic(nom150, fcol)
        assigned = ALL_SIGNS[fcol]
        measured_sign = int(np.sign(stats["mean"])) if np.isfinite(stats["mean"]) else 0
        # split-half: odd vs even calendar years
        years = nom150["date"].dt.year
        odd = nom150[years % 2 == 1]
        even = nom150[years % 2 == 0]
        odd_stats, _ = pooled_ic(odd, fcol)
        even_stats, _ = pooled_ic(even, fcol)
        out[fcol] = {
            "is_candidate": fcol in CANDIDATE_SIGNS,
            "assigned_sign": assigned,
            "pooled_ic": stats["mean"], "t": stats["t"], "n_dates": stats["n_dates"],
            "measured_sign": measured_sign,
            "sign_matches_assigned": (measured_sign == assigned) if measured_sign != 0 else None,
            "odd_years_ic": odd_stats["mean"], "odd_years_t": odd_stats["t"],
            "even_years_ic": even_stats["mean"], "even_years_t": even_stats["t"],
            "split_half_same_sign": (
                np.sign(odd_stats["mean"]) == np.sign(even_stats["mean"])
                if np.isfinite(odd_stats["mean"]) and np.isfinite(even_stats["mean"]) else None
            ),
        }
        log(f"    {fcol:32s} IC={stats['mean']:+.4f} t={stats['t']:+.2f} "
            f"assigned={assigned:+d} matches={out[fcol]['sign_matches_assigned']}")

    # coverage split, using the already-signed composite factors only
    hi = nom150[nom150["coverage"] >= 8]
    lo = nom150[nom150["coverage"] <= 4]
    signed_cols = C.FACTOR_COLS
    # a coverage-agnostic "mean of available signed ranks" needs the actual
    # composite; computed separately in section 3. Here just report how
    # coverage itself relates to the label and to score dispersion via one
    # representative signed factor's IC computed on each subset.
    coverage_block = {
        "hi_coverage_n_rows": int(len(hi)), "lo_coverage_n_rows": int(len(lo)),
        "hi_coverage_mean": float(hi["coverage"].mean()) if len(hi) else None,
        "lo_coverage_mean": float(lo["coverage"].mean()) if len(lo) else None,
    }
    return out, coverage_block, nom150[["ticker", "date", "coverage"]]


# ---------------------------------------------------------------------------
# 3. Composite scores (raw + neutral, cap150 + cap2000) via composite.py
# ---------------------------------------------------------------------------
def build_composite_scores(df, tier, neutral):
    log(f"3: computing composite scores tier={tier} neutral={neutral} ...")
    sub = nomination_slice(df, tier)
    need = list(dict.fromkeys(["ticker", "sector", "volatility_60"] + C.FACTOR_COLS))
    parts = []
    for d, g in sub.groupby("date", sort=True):
        gg = g[need].reset_index(drop=True)
        scored = C.compute_composite(gg, neutral=neutral)
        scored["date"] = d
        parts.append(scored)
    out = pd.concat(parts, ignore_index=True)
    out = out.merge(sub[["ticker", "date", "__label__", "volatility_60"]],
                     on=["ticker", "date"], how="left")
    log(f"    {len(out):,} scored rows, {out['composite'].notna().mean():.1%} non-null composite")
    return out


def decile_analysis(scored):
    log("3b: decile monotonicity ...")
    parts = []
    for d, g in scored.dropna(subset=["composite", "__label__"]).groupby("date"):
        if len(g) < 30:
            continue
        try:
            dec = pd.qcut(g["composite"], 10, labels=False, duplicates="drop")
        except ValueError:
            continue
        parts.append(pd.DataFrame({"decile": dec.to_numpy(), "label": g["__label__"].to_numpy(),
                                    "date": d}))
    pooled = pd.concat(parts, ignore_index=True)
    rows = []
    for dec, g in pooled.groupby("decile"):
        per_date_mean = g.groupby("date")["label"].mean()
        stats = newey_west_mean_t(per_date_mean.to_numpy())
        rows.append({"decile": int(dec), "n": int(len(g)), "mean_forward_return": stats["mean"],
                     "t": stats["t"]})
    rows.sort(key=lambda r: r["decile"])
    return rows


def coverage_ic_on_composite(scored, coverage_lookup):
    # `scored` already carries its own `coverage` from compute_composite
    # (tier/neutral-specific); no merge needed, and coverage_lookup would
    # collide with it under pandas' default merge suffixing.
    hi = scored[scored["coverage"] >= 8]
    lo = scored[scored["coverage"] <= 4]
    hi_stats, _ = pooled_ic(hi, "composite")
    lo_stats, _ = pooled_ic(lo, "composite")
    full_stats, _ = pooled_ic(scored, "composite")
    return {"full": full_stats, "hi_coverage": hi_stats, "lo_coverage": lo_stats}


# ---------------------------------------------------------------------------
# 4. IC -> IR consistency check (single offset, gross, cap150_raw decile_volq)
# ---------------------------------------------------------------------------
def ic_to_ir_check(df):
    log("4: IC -> IR consistency check (cap150_raw, decile_volq, offset 0, gross) ...")
    sub = nomination_slice(df, "cap150")
    outcomes = pd.read_parquet(OUTCOME_PATH)
    outcomes["date"] = pd.to_datetime(outcomes["date"])
    spy = outcomes[outcomes["ticker"] == "SPY"].set_index("date")["gross_return_40"]
    stock_outcomes = outcomes[~outcomes["ticker"].isin(["SPY", "USMV"])]
    sub = sub.merge(stock_outcomes[["ticker", "date", "gross_return_40"]],
                     on=["ticker", "date"], how="left")
    by_date = {d: g.reset_index(drop=True) for d, g in sub.groupby("date", sort=True)}
    dates = sorted(by_date.keys())
    rebal = dates[0::C.HORIZON]  # offset 0
    excess = []
    for tp in rebal:
        g = by_date[tp]
        if len(g) < C.N_VOL_QUINTILES * 4:
            continue
        cc_cols = list(dict.fromkeys(["ticker", "sector", "volatility_60"] + C.FACTOR_COLS))
        scored = C.compute_composite(g[cc_cols], neutral=False)
        picks = C.pick_decile_volq(g, scored)
        ret_lookup = dict(zip(g["ticker"], g["gross_return_40"]))
        picks = [(t, w) for t, w in picks if pd.notna(ret_lookup.get(t))]
        if not picks:
            continue
        wsum = sum(w for _, w in picks)
        gross = sum((w / wsum) * (1.0 + ret_lookup[t]) for t, w in picks) - 1.0
        spy_ret = spy.get(tp, np.nan)
        if pd.notna(spy_ret):
            excess.append(gross - spy_ret)
    excess = np.array(excess)
    n_windows_per_year = 252.0 / C.HORIZON
    mean_w, std_w = excess.mean(), excess.std(ddof=1)
    ir_annual = (mean_w / std_w) * np.sqrt(n_windows_per_year) if std_w > 0 else np.nan
    return {
        "n_windows": int(len(excess)),
        "mean_excess_per_window": float(mean_w),
        "std_excess_per_window": float(std_w),
        "ir_annualized_realized": float(ir_annual),
        "note": "single offset (0), gross of cost -- a quick check, not the 40-offset headline",
    }


# ---------------------------------------------------------------------------
# 5. Factor correlation matrix + Grinold-Kahn implied weights
# ---------------------------------------------------------------------------
def factor_correlation_and_gk(nom150):
    log("5: factor correlation matrix + Grinold-Kahn implied weights (cap150) ...")
    # short_interest_days_to_cover has 0% coverage in the nomination era
    # (factor_availability: first/last date both null) -- excluded from the
    # solvable 8x8 system, reported separately as unmeasurable-here.
    cols = [c for c in C.FACTOR_COLS if nom150[c].notna().any()]
    dropped = [c for c in C.FACTOR_COLS if c not in cols]
    # pooled, date-standardized signed ranks (rank_z * sign), same units as
    # what compute_composite averages -- approximates avg cross-sectional corr.
    parts = {c: [] for c in cols}
    idx_parts = []
    for d, g in nom150.groupby("date"):
        for c in cols:
            parts[c].append(C.rank_z(g[c]) * C.FACTOR_SIGNS[c])
        idx_parts.append(g.index)
    ranked = pd.DataFrame({c: pd.concat(parts[c]) for c in cols})
    corr = ranked.corr(method="pearson")

    ic_vec = np.array([pooled_ic(nom150, c)[0]["mean"] * C.FACTOR_SIGNS[c] for c in cols])
    Sigma = corr.to_numpy()
    try:
        w_gk = np.linalg.solve(Sigma + 1e-6 * np.eye(len(cols)), ic_vec)
    except np.linalg.LinAlgError:
        w_gk = np.full(len(cols), np.nan)
    w_gk_norm = w_gk / np.sum(np.abs(w_gk)) if np.isfinite(w_gk).all() and np.sum(np.abs(w_gk)) > 0 else w_gk
    w_eq = np.full(len(cols), 1.0 / len(cols))
    cos_sim = (
        float(np.dot(w_gk_norm, w_eq) / (np.linalg.norm(w_gk_norm) * np.linalg.norm(w_eq)))
        if np.isfinite(w_gk_norm).all() else None
    )
    return {
        "factor_order": cols,
        "dropped_no_data_this_era": dropped,
        "correlation_matrix": corr.round(4).to_dict(),
        "signed_ic_vector": {c: float(v) for c, v in zip(cols, ic_vec)},
        "grinold_kahn_weights_normalized": {c: float(v) for c, v in zip(cols, w_gk_norm)},
        "equal_weights": {c: float(v) for c, v in zip(cols, w_eq)},
        "cosine_similarity_gk_vs_equal": cos_sim,
    }


# ---------------------------------------------------------------------------
# 6. Fama-MacBeth R^2
# ---------------------------------------------------------------------------
def fama_macbeth_r2(scored):
    log("6: Fama-MacBeth cross-sectional R^2 ...")
    slopes, r2s = [], []
    for d, g in scored.dropna(subset=["composite", "__label__"]).groupby("date"):
        if len(g) < 30:
            continue
        x = g["composite"].to_numpy(np.float64)
        y = g["__label__"].to_numpy(np.float64)
        X = np.column_stack([np.ones(len(x)), x])
        beta, *_ = np.linalg.lstsq(X, y, rcond=None)
        yhat = X @ beta
        ss_res = np.sum((y - yhat) ** 2)
        ss_tot = np.sum((y - y.mean()) ** 2)
        r2 = 1 - ss_res / ss_tot if ss_tot > 0 else np.nan
        slopes.append(beta[1])
        r2s.append(r2)
    slope_stats = newey_west_mean_t(np.array(slopes))
    return {
        "mean_slope": slope_stats["mean"], "slope_t": slope_stats["t"],
        "mean_r2": float(np.nanmean(r2s)), "n_dates": int(len(r2s)),
    }


def main():
    t0 = time.time()
    df = load_panel()
    nom150 = nomination_slice(df, "cap150")

    report = {"generated": pd.Timestamp.now().isoformat(), "era": "nominate_2007_2019",
              "label_col": LABEL}

    report["factor_availability"] = factor_availability(nom150)
    factor_ic, coverage_block, coverage_lookup = audit_factor_ics(nom150)
    report["factor_ic"] = factor_ic
    report["coverage"] = coverage_block

    scores = {}
    for tier in ("cap150", "cap2000"):
        for neutral in (False, True):
            key = f"{tier}_{'neutral' if neutral else 'raw'}"
            scores[key] = build_composite_scores(df, tier, neutral)

    report["decile_cap150_raw"] = decile_analysis(scores["cap150_raw"])
    report["decile_cap150_neutral"] = decile_analysis(scores["cap150_neutral"])
    report["coverage_ic_cap150_raw"] = coverage_ic_on_composite(scores["cap150_raw"], coverage_lookup)

    report["fama_macbeth"] = {
        key: fama_macbeth_r2(sc) for key, sc in scores.items()
    }

    report["factor_correlation_gk"] = factor_correlation_and_gk(nom150)
    report["ic_to_ir_check"] = ic_to_ir_check(df)

    OUT_JSON.parent.mkdir(parents=True, exist_ok=True)
    with open(OUT_JSON, "w") as f:
        json.dump(report, f, indent=2, default=str)
    log(f"wrote {OUT_JSON} ({time.time() - t0:.0f}s total)")


if __name__ == "__main__":
    main()
