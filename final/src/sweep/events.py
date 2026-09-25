"""
Event and tail-shape features for the stage-2 model.

Round 16 (2026-09-12).

Why these, and why they are a different KIND of variable
--------------------------------------------------------
Stage 1 asks "is this a good company / a good factor exposure". That is a slow
state variable and the fundamentals panel answers it.

Stage 2 asks "which of these 50 pre-screened names produces a large move in the
next 40 trading days". Over 40 days large moves are overwhelmingly EVENTS --
earnings surprises, guidance changes, M&A, approvals. Every feature the project
currently has is a state variable, including the price ones: `momentum_60`
describes what already happened. That is a plausible reason the twelve price
features screened dead in Round 13 and it is the gap this module targets.

The panel already carries `fundamentals_age_days` -- days SINCE the last filing.
What it does not carry is anything pointing FORWARD, which is the half that
matters for "is there a catalyst inside my holding window".

THE LOOK-AHEAD TRAP, AND HOW IT IS AVOIDED
------------------------------------------
"Is there an earnings event in the holding window" is **look-ahead as stated**.
The next filing date is in the future; reading it from the SF1 table at time t
is reading tomorrow's newspaper. This is the same shape as the two defects that
cost this project Rounds 7 and 11 (the split-adjusted price floor; the spinoff
price basis), and it would be invisible downstream -- it would simply look like
a very good feature.

The causal construction used here estimates the next filing date from each
ticker's OWN past cadence:

    expected_next(t) = last_filing_on_or_before(t)  +  median(gaps observed so far)

The gap median is EXPANDING -- at time t it uses only gaps between filings that
had both already happened by t. Measured cadence is tight enough for this to be
meaningful: per-ticker median gap p10/p50/p90 = 78.5 / 91 / 92 days.

Every other feature here is a trailing window shifted by one, same discipline as
`rates.py`.

The features
------------
    days_to_next_filing_est   causal estimate of days until the next filing
    earnings_in_window        that estimate falls inside the holding horizon
    earnings_move_sens        this name's OWN historical |reaction| to its
                              filings -- a per-name tail-WIDTH estimate. Some
                              names routinely move 15% on earnings, some 2%.
    realized_skew_120         trailing skewness of daily returns. The existing
                              vol features are symmetric; this is the Bessembinder
                              question directly -- which names have a history of
                              producing right-tail outcomes.
    upside_vol_ratio_120      upside semi-deviation / downside semi-deviation.
                              Tail ASYMMETRY, orthogonal to both vol and skew.
    gross_margin_delta        change since the PRIOR filing, not the level. The
    revenue_growth_delta      panel has levels only, and revaluation tends to
    roe_delta                 follow the change rather than the level.
"""

import numpy as np
import pandas as pd

from features import OUT_DIR

SF1_PATH = OUT_DIR.parent / "data" / "sharadar" / "sf1_fundamentals.parquet"

ANNOUNCE_LEAD_DAYS = 21

EVENT_FEATURE_COLS = [
    "days_to_next_filing_est",
    "earnings_in_window",
    "days_to_next_filing_seasonal",
    "earnings_in_window_seasonal",
    "days_to_next_filing_known",
    "earnings_in_window_known",
    "days_to_next_filing_actual",
    "earnings_in_window_actual",
    "earnings_move_sens",
    "realized_skew_120",
    "upside_vol_ratio_120",
    "gross_margin_delta",
    "revenue_growth_delta",
    "roe_delta",
]

REACTION_DAYS = 3       # filing day + 2, the window the move lands in
SKEW_WINDOW = 120


# --------------------------------------------------------------------------
def load_filings(path=None, dimension="ARQ"):
    """Filing dates with an EXPANDING median gap and prior-filing deltas.

    Sharadar's `date` is the date the filing became public -- the PIT key. Rows
    where `date <= reportperiod` are impossible (published before the period
    closed) and are dropped rather than trusted; there are ~18 of them.
    """
    df = pd.read_parquet(path or SF1_PATH)
    for c in ("date", "calendardate", "reportperiod"):
        # parquet round-trips these as datetime64[us] on pandas 2.x while the
        # panel carries [ns]; merge_asof refuses to join mismatched precisions.
        df[c] = pd.to_datetime(df[c], errors="coerce").astype("datetime64[ns]")
    df = df[df.dimension == dimension]
    bad = df["date"] <= df["reportperiod"]
    if bad.any():
        print(f"  dropping {int(bad.sum())} filings dated on/before their own "
              f"report period (impossible)")
        df = df[~bad]
    df = (df.dropna(subset=["ticker", "date"])
            .sort_values(["ticker", "date"])
            .drop_duplicates(["ticker", "date"], keep="last")
            .reset_index(drop=True))

    g = df.groupby("ticker", sort=False)
    gap = g["date"].diff().dt.days
    # EXPANDING median: at filing k it uses gaps 1..k, all of which are between
    # filings that have already happened. shift() is NOT needed because gap k is
    # known the moment filing k lands, which is when this row becomes usable.
    df["gap_med"] = (gap.groupby(df["ticker"], sort=False)
                        .transform(lambda s: s.expanding(min_periods=2).median()))
    df["gap_med"] = df["gap_med"].fillna(91.0)          # quarterly prior
    df["next_filing_est"] = df["date"] + pd.to_timedelta(df["gap_med"], unit="D")
    # The ACTUAL next filing date, carried alongside deliberately.
    #
    # Gabe's point, and it is correct: earnings dates are SCHEDULED and
    # announced weeks ahead, so a real trader at time t genuinely knows the
    # next date. Using it is not economically look-ahead.
    #
    # The narrower problem is that this dataset cannot PROVE that. Sharadar
    # records when the filing landed, not when the date was announced, so the
    # field exists only because the event happened. Typical announcement lead
    # is ~2-6 weeks, which covers roughly the first half of a 58-calendar-day
    # holding window and not the back half.
    #
    # So both are built and screened side by side. The cadence estimate is
    # provably causal but blunt (MAE ~19d). The gap between them BOUNDS what a
    # real earnings calendar would be worth, which is the number that decides
    # whether to go and source one.
    df["next_filing_actual"] = df.groupby("ticker", sort=False)["date"].shift(-1)

    # SEASONAL estimator -- the one Frazzini & Lamont (2007) use, and much the
    # better predictor. Earnings calendars are seasonally stable: the filing
    # after this one lands ~1 year after the filing three back (four filings
    # apart = 4 quarters). date[k-3] is known at filing k, so this is causal.
    #
    #   cadence  (last filing + median gap)  MAE 19d, 40% within a week
    #   seasonal (same quarter last year)    MAE  3d, 73% within a week
    #
    # Guard: date[k] - date[k-3] spans THREE quarterly gaps, ~273 days -- NOT a
    # year. Getting that band wrong rejects almost every row (13% vs 82.5%) and
    # looks exactly like a bad estimator rather than a bad check.
    _g = df.groupby("ticker", sort=False)["date"]
    _span = (df["date"] - _g.shift(3)).dt.days
    _seasonal = _g.shift(3) + pd.Timedelta(days=364)
    df["next_filing_seasonal"] = _seasonal.where(
        _span.between(210, 340)).fillna(df["next_filing_est"])
    # `_known`: the real date, but only VISIBLE once a company would plausibly
    # have announced it. Companies schedule earnings calls roughly 2-6 weeks
    # ahead, so ANNOUNCE_LEAD_DAYS is deliberately set at the short end -- a
    # conservative lead under-claims knowledge rather than over-claiming it,
    # and under-claiming only costs signal where over-claiming invents it.
    df["next_filing_known_from"] = (df["next_filing_actual"]
                                    - pd.Timedelta(days=ANNOUNCE_LEAD_DAYS))

    # deltas vs the PRIOR filing, computed on the filing grid then carried
    # forward -- never interpolated across the gap.
    with np.errstate(divide="ignore", invalid="ignore"):
        gm = np.where(df["revenue"] > 0, df["gp"] / df["revenue"], np.nan)
        roe = np.where(df["equity"] > 0, df["netinc"] / df["equity"], np.nan)
    df["_gm"], df["_roe"], df["_rev"] = gm, roe, df["revenue"].to_numpy(float)
    for src, dst in (("_gm", "gross_margin_delta"), ("_roe", "roe_delta")):
        df[dst] = df.groupby("ticker", sort=False)[src].diff()
    rev = df.groupby("ticker", sort=False)["_rev"]
    yoy = rev.transform(lambda s: s.pct_change(4, fill_method=None))
    df["revenue_growth_delta"] = yoy.groupby(df["ticker"], sort=False).diff()
    return df[["ticker", "date", "next_filing_est", "next_filing_actual",
               "next_filing_known_from", "next_filing_seasonal",
               "gross_margin_delta", "roe_delta", "revenue_growth_delta"]]


# --------------------------------------------------------------------------
def _reaction_sensitivity(panel, filings):
    """Per-name expanding mean |3-day return| around its OWN past filings.

    Only filings whose reaction window has fully CLOSED by date t contribute,
    so the value at t is computable from t's information set.
    """
    p = panel[["ticker", "date", "daily_return"]].copy()
    p["_i"] = np.arange(len(p))
    ret = p["daily_return"].to_numpy(np.float64)

    # cumulative 3-day forward return magnitude, per row
    codes = pd.factorize(p["ticker"], sort=False)[0]
    same = np.zeros(len(p), bool)
    same[:-(REACTION_DAYS - 1)] = codes[:-(REACTION_DAYS - 1)] == codes[REACTION_DAYS - 1:]
    cum = np.full(len(p), np.nan)
    acc = np.zeros(len(p))
    for k in range(REACTION_DAYS):
        sl = ret[k:len(p) - (REACTION_DAYS - 1 - k)]
        acc[:len(sl)] += np.nan_to_num(sl)
    cum[same] = np.abs(acc[same])

    # attach to the first trading row on/after each filing date
    f = filings[["ticker", "date"]].sort_values(["date", "ticker"])
    hit = pd.merge_asof(f, p.sort_values("date")[["date", "ticker", "_i"]],
                        on="date", by="ticker", direction="forward",
                        tolerance=pd.Timedelta("7D"))
    hit = hit.dropna(subset=["_i"])
    hit["react"] = cum[hit["_i"].to_numpy(int)]
    hit = hit.dropna(subset=["react"])
    # the value becomes KNOWN only once the reaction window closes
    hit["known_at"] = hit["date"] + pd.Timedelta(days=REACTION_DAYS + 2)
    hit["sens"] = (hit.sort_values("known_at")
                      .groupby("ticker", sort=False)["react"]
                      .transform(lambda s: s.expanding(min_periods=2).mean()))
    return hit[["ticker", "known_at", "sens"]].sort_values("known_at")


# --------------------------------------------------------------------------
def build_event_features(panel, horizon=40, verbose=True):
    """Add EVENT_FEATURE_COLS to a feature panel (ticker, date, daily_return)."""
    panel = panel.sort_values(["ticker", "date"]).reset_index(drop=True)
    filings = load_filings()
    if verbose:
        print(f"  filings: {len(filings):,} rows, {filings.ticker.nunique():,} tickers")

    # ---- forward-looking, causally estimated ----------------------------
    # merge_asof RESETS the index, so sorting the left frame and then calling
    # .sort_index() on the result is a no-op: the rows come back in DATE order
    # while the panel is in (ticker, date) order, and every merged column lands
    # on the wrong row. Carry an explicit row position instead.
    left = panel[["ticker", "date"]].copy()
    left["_row"] = np.arange(len(panel), dtype=np.int64)
    left = left.sort_values(["date", "ticker"])
    fa = filings.sort_values(["date", "ticker"])
    m = (pd.merge_asof(left, fa, on="date", by="ticker", direction="backward")
           .sort_values("_row").reset_index(drop=True))
    assert len(m) == len(panel) and (m["_row"].to_numpy() == np.arange(len(panel))).all(), \
        "filing merge lost or reordered rows"
    dd = (m["next_filing_est"].to_numpy("datetime64[ns]")
          - panel["date"].to_numpy("datetime64[ns]")) / np.timedelta64(1, "D")
    panel["days_to_next_filing_est"] = dd.astype(np.float32)
    # a horizon in TRADING days is ~1.4523 calendar days per trading day
    span = horizon * 1.4523
    panel["earnings_in_window"] = ((dd > 0) & (dd <= span)).astype(np.float32)
    da = (m["next_filing_actual"].to_numpy("datetime64[ns]")
          - panel["date"].to_numpy("datetime64[ns]")) / np.timedelta64(1, "D")
    panel["days_to_next_filing_actual"] = da.astype(np.float32)
    panel["earnings_in_window_actual"] = ((da > 0) & (da <= span)).astype(np.float32)
    # `_known`: identical to `_actual` but blind to any filing whose date the
    # company would not yet have announced at t.
    ds = (m["next_filing_seasonal"].to_numpy("datetime64[ns]")
          - panel["date"].to_numpy("datetime64[ns]")) / np.timedelta64(1, "D")
    panel["days_to_next_filing_seasonal"] = ds.astype(np.float32)
    panel["earnings_in_window_seasonal"] = ((ds > 0) & (ds <= span)).astype(np.float32)

    kf = (m["next_filing_known_from"].to_numpy("datetime64[ns]")
          - panel["date"].to_numpy("datetime64[ns]")) / np.timedelta64(1, "D")
    announced = kf <= 0                       # the date is public by t
    panel["days_to_next_filing_known"] = np.where(announced, da, np.nan).astype(np.float32)
    panel["earnings_in_window_known"] = (
        (announced & (da > 0) & (da <= span))).astype(np.float32)
    for c in ("gross_margin_delta", "roe_delta", "revenue_growth_delta"):
        panel[c] = m[c].to_numpy(np.float32)

    # ---- per-name reaction size ----------------------------------------
    sens = _reaction_sensitivity(panel, filings)
    l2 = panel[["ticker", "date"]].copy()
    l2["_row"] = np.arange(len(panel), dtype=np.int64)
    l2 = l2.sort_values(["date", "ticker"])
    sm = (pd.merge_asof(l2, sens.rename(columns={"known_at": "date"})
                            .sort_values(["date", "ticker"]),
                        on="date", by="ticker", direction="backward")
            .sort_values("_row").reset_index(drop=True))
    assert (sm["_row"].to_numpy() == np.arange(len(panel))).all(), \
        "sensitivity merge lost or reordered rows"
    panel["earnings_move_sens"] = sm["sens"].to_numpy(np.float32)

    # ---- tail shape, trailing and shifted -------------------------------
    r = panel.groupby("ticker", sort=False)["daily_return"]
    panel["realized_skew_120"] = (
        r.transform(lambda s: s.rolling(SKEW_WINDOW, min_periods=60).skew().shift(1))
         .astype(np.float32))
    up = r.transform(lambda s: s.clip(lower=0).rolling(SKEW_WINDOW, min_periods=60)
                     .std().shift(1))
    dn = r.transform(lambda s: s.clip(upper=0).rolling(SKEW_WINDOW, min_periods=60)
                     .std().shift(1))
    with np.errstate(divide="ignore", invalid="ignore"):
        panel["upside_vol_ratio_120"] = np.where(
            dn.to_numpy() > 1e-9, up.to_numpy() / dn.to_numpy(), np.nan).astype(np.float32)

    # SANITIZE. XGBoost handles NaN natively -- that is the whole design of the
    # fundamentals panel -- but it REFUSES inf ("Input data contains `inf` or a
    # value too large, while `missing` is not set to `inf`"). `pct_change` over
    # a zero prior revenue produces exactly that: revenue_growth_delta carried
    # 6,207 +inf and 20,690 -inf, which killed three of six Round 17 cells at
    # training time rather than at build time.
    #
    # An infinite growth rate is not a large growth rate, it is an undefined
    # one, so NaN is the correct value and not merely the tolerated one.
    n_inf = 0
    for c in EVENT_FEATURE_COLS:
        v = panel[c].to_numpy(np.float64)
        bad = ~np.isfinite(v) & ~np.isnan(v)
        if bad.any():
            n_inf += int(bad.sum())
            panel[c] = np.where(bad, np.nan, v).astype(np.float32)
    if verbose and n_inf:
        print(f"  sanitized {n_inf:,} infinite values -> NaN")

    if verbose:
        for c in EVENT_FEATURE_COLS:
            v = panel[c].to_numpy(np.float64)
            f = np.isfinite(v)
            print(f"  {c:<24} {f.mean()*100:5.1f}% populated  "
                  f"median {np.nanmedian(v[f]) if f.any() else np.nan:+.4f}")
    return panel
