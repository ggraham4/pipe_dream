"""
Interest-rate sensitivity features.

Round 14 (2026-09-11). First genuinely new data in the project since the
Round 11 Sharadar rebuild.

Why rates, and why in this form
-------------------------------
Round 13 closed with a well-powered negative: within sectors, the 24 existing
columns contain nothing detectable (minimum detectable IC 0.021, largest
observed 0.014), and all twelve price/volume features are dead at every
horizon. What that licenses is NEW DATA, not a new model on the same data.

The critical design point, and the reason this module exists rather than a
one-line panel join: **a market-level rate series is constant across the
cross-section on any given date, so it carries exactly zero ranking
information on its own.** Adding `10y yield` as a column would do nothing. A
tree can only use it by interacting it with something that varies by name, and
axis-aligned trees are structurally poor at representing products.

So the features here are per-NAME sensitivities, which do vary cross-
sectionally on a single date:

    rate_beta_120     trailing sensitivity of the stock's daily return to
                      daily changes in the 10-year yield
    rate_beta_250     the same over a longer, more stable window
    curve_beta_120    sensitivity to changes in the 10y-2y slope; banks load
                      positively, and this is the one most likely to be
                      orthogonal to what the existing features capture
    rate_beta_x_move  rate_beta_120 * (trailing 20-day change in the 10y)

The last one is the product the model cannot easily form for itself. Note it
genuinely carries cross-sectional information despite being multiplied by a
date constant: the constant's SIGN flips the within-date ranking, which is
exactly the conditional statement "high-duration names do badly when rates
rise, and well when they fall".

Data provenance
---------------
US Treasury constant-maturity yields (H.15), pulled via Alpha Vantage. Two
properties make this the cleanest input this project has had:

  * **Never revised.** There is no analogue of the SF1 `date` vs
    `calendardate` trap, and no restatement risk.
  * **No distribution problem.** Bond ETFs (TLT/HYG/LQD) pay large monthly
    distributions that vendors adjust inconsistently, and a
    distribution-unadjusted series carries a sawtooth that looks like signal.
    Since the equity labels here use `close` and exclude dividends, mixing in
    a distribution-heavy ETF would be an inconsistency nearly impossible to
    detect downstream. Yields have no such problem.

The raw series uses "." for non-business days. Those are dropped at load, NOT
interpolated: an `interpolate()` would read tomorrow's yield backwards into
today, which is look-ahead. Where a trading day has no yield print the
forward-fill below carries the LAST KNOWN value, which is causally safe.

Causality
---------
Every beta at date t is estimated from returns and yield changes strictly
BEFORE t (the rolling window is shifted by one). Nothing here uses a
contemporaneous or future observation.
"""

import numpy as np
import pandas as pd

from features import OUT_DIR

YIELDS_CSV = OUT_DIR.parent / "data" / "rates" / "treasury_yields.csv"

RATE_FEATURE_COLS = [
    "rate_beta_120",
    "rate_beta_250",
    "curve_beta_120",
    "rate_beta_x_move",
]


# --------------------------------------------------------------------------
def load_yields(path=None, ffill_limit=5):
    """Daily 3m/2y/10y constant-maturity yields and their first differences.

    Forward-fills gaps up to `ffill_limit` trading days -- carrying the last
    KNOWN value forward is causally safe, where interpolation would not be.
    """
    p = path or YIELDS_CSV
    df = pd.read_csv(p, parse_dates=["date"]).sort_values("date")
    for c in ("y3m", "y2", "y10"):
        df[c] = pd.to_numeric(df[c], errors="coerce").ffill(limit=ffill_limit)
    df["slope"] = df["y10"] - df["y2"]
    # First differences in PERCENTAGE POINTS (the series is already in pct).
    df["d_y10"] = df["y10"].diff()
    df["d_slope"] = df["slope"].diff()
    # Trailing 20-day change -- the conditioning variable for the interaction.
    df["d_y10_20"] = df["y10"].diff(20)
    return df.set_index("date")[["y10", "slope", "d_y10", "d_slope", "d_y10_20"]]


# --------------------------------------------------------------------------
def _rolling_beta(ret, x, window, min_periods=None):
    """Rolling univariate beta of `ret` on `x`, both aligned 1-D arrays.

    beta = cov(ret, x) / var(x), computed from rolling means so the whole
    panel can be done with four rolling sums per ticker rather than a
    regression per row.

    `x` is a DATE-level series (identical for every ticker), so var(x) could
    be hoisted -- it is not, because a ticker with missing returns must get
    the covariance over ITS OWN observed window, and hoisting would silently
    pair a ticker's covariance with a different window's variance.
    """
    mp = min_periods or max(window // 2, 20)
    r = pd.Series(ret)
    xs = pd.Series(x)
    valid = r.notna() & xs.notna()
    r = r.where(valid)
    xs = xs.where(valid)

    mr = r.rolling(window, min_periods=mp).mean()
    mx = xs.rolling(window, min_periods=mp).mean()
    mrx = (r * xs).rolling(window, min_periods=mp).mean()
    mxx = (xs * xs).rolling(window, min_periods=mp).mean()

    cov = mrx - mr * mx
    var = mxx - mx * mx
    with np.errstate(divide="ignore", invalid="ignore"):
        beta = np.where(var > 1e-12, cov / var, np.nan)
    # SHIFT BY ONE: the beta attached to date t must use only data before t.
    return pd.Series(beta).shift(1).to_numpy()


def build_rate_features(panel, yields=None, windows=(120, 250), verbose=True):
    """Add per-ticker rate-sensitivity columns to a feature panel.

    panel : DataFrame with at least ['ticker', 'date', 'daily_return'],
            sorted per ticker by date (the project's panel layout).

    Returns the panel with RATE_FEATURE_COLS added. Rows whose trailing window
    is incomplete get NaN -- they are NOT imputed, because a fabricated zero
    beta would read as "this name is rate-insensitive", which is a claim.
    """
    y = yields if yields is not None else load_yields()
    if verbose:
        print(f"  yields: {len(y):,} dates, {y.index.min().date()} .. "
              f"{y.index.max().date()}")

    panel = panel.sort_values(["ticker", "date"]).reset_index(drop=True)
    dates = pd.DatetimeIndex(panel["date"])
    aligned = y.reindex(dates)
    d_y10 = aligned["d_y10"].to_numpy()
    d_slope = aligned["d_slope"].to_numpy()
    panel["d_y10_20"] = aligned["d_y10_20"].to_numpy()

    ret = panel["daily_return"].to_numpy(np.float64)
    codes = pd.factorize(panel["ticker"], sort=False)[0]
    bounds = np.flatnonzero(np.diff(codes)) + 1
    starts = np.concatenate(([0], bounds))
    ends = np.concatenate((bounds, [len(panel)]))

    out = {c: np.full(len(panel), np.nan) for c in
           ("rate_beta_120", "rate_beta_250", "curve_beta_120")}
    n_tick = len(starts)
    for i, (lo, hi) in enumerate(zip(starts, ends)):
        if verbose and (i % 500 == 0 or i == n_tick - 1):
            print(f"  rate betas: ticker {i + 1}/{n_tick}", flush=True)
        if hi - lo < 40:
            continue
        r = ret[lo:hi]
        out["rate_beta_120"][lo:hi] = _rolling_beta(r, d_y10[lo:hi], 120)
        out["rate_beta_250"][lo:hi] = _rolling_beta(r, d_y10[lo:hi], 250)
        out["curve_beta_120"][lo:hi] = _rolling_beta(r, d_slope[lo:hi], 120)

    for k, v in out.items():
        panel[k] = v.astype(np.float32)

    # The interaction the trees cannot easily form. Multiplying by a date
    # constant preserves |ranking| but FLIPS it when the constant is negative
    # -- which is the whole conditional statement.
    panel["rate_beta_x_move"] = (panel["rate_beta_120"].to_numpy(np.float64)
                                 * panel["d_y10_20"].to_numpy(np.float64)
                                 ).astype(np.float32)

    if verbose:
        for c in RATE_FEATURE_COLS:
            v = panel[c].to_numpy(np.float64)
            f = np.isfinite(v)
            print(f"  {c:<18} {f.mean()*100:5.1f}% populated  "
                  f"median {np.nanmedian(v[f]) if f.any() else float('nan'):+.4f}")
    return panel
