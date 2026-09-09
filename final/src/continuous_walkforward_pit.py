"""
PIT-corrected continuous/rolling walk-forward backtest -- the survivorship-
bias-correct version of continuous_walkforward_beta.py. Built 2026-09-01 in
response to Gabe's four-part follow-up on the first full PIT run:

  1. "lets do the rolling backtest like we did before" -- baseline vs
     augmented vs SPY, but with PIT-correct candidate eligibility at EVERY
     step (not just the 8 hand-picked timepoints backtest_pit.py uses).
  2. "Lets compare to a model that has a stop loss rule of auto sell if a
     stock loses 30% before the end of the models 40 day window and just
     pocket the cash" -- see --mode baseline_stoploss / augmented_stoploss.
  3. "Can we go farther back than 2011 ... I'd like to get coverage of
     2008" -- see --start (default 2007-01-02) and pit_universe_continuous.py.
  4. "how have model weights changed given this new data, is it still
     volatility driven" -- every model fit records
     XGBClassifier.feature_importances_; --mode combine aggregates and
     prints the ranked list.

Differences from continuous_walkforward_beta.py this is built on:

  - Reads features_pit.parquet / features_with_fundamentals_pit.parquet
    (current universe + point-in-time gap tickers merged, delisting exit-
    floor label fix already applied there) instead of the non-PIT
    features_with_fundamentals_beta.parquet.

  - At EVERY step, the candidate pool a model can pick from is restricted
    to: today's current-universe tickers, UNION the real point-in-time
    S&P 500 gap tickers as of that step's date
    (pit_universe_continuous.gap_tickers_asof() -- general-purpose for any
    date, not just the 8 fixed timepoints pit_universe.py covers) that ALSO
    clear a MIN_TRAILING_DAYS (380 calendar day) trailing-history check
    against their own earliest date actually found in this panel -- same
    purpose as features_pit.py's validate_gap_coverage() (protect the
    rolling 252/120-day feature windows, and guard against a recycled
    ticker symbol), just computed per-step here instead of only at 8 fixed
    dates. See allowed_universe_at() below.

  - START_DATE defaults to 2007-01-02, not 2020-01-02. How far back this
    ACTUALLY reaches depends on real trailing-history availability (the
    existing "skip if <300 training rows" / embargo checks handle any step
    that isn't viable yet) -- the printed step-date range after a run is
    the real answer to "how far back does this cover," not this default.

  - Two new modes, baseline_stoploss / augmented_stoploss, are NOT separate
    model fits -- they re-simulate the SAME picks a prior baseline/augmented
    run already made (loaded from that run's own JSON), walking each pick's
    actual day-by-day price path for up to FORWARD_WINDOW (40) trading
    days: if the daily LOW ever touches entry_price * 0.70, the position
    exits AT the stop price that day and the rest of the window is held in
    cash (flat, 0% return) instead of being reinvested or rolled into a new
    pick, per Gabe's "just pocket the cash." See simulate_stop_loss() for
    the exact mechanics and the modeling-assumption caveat: this triggers
    off the daily LOW (a resting-stop-order assumption, filled exactly at
    -30%), not off the daily CLOSE (a "sells if it closes down 30%" rule
    would trigger less often and fill worse on gap-down days) -- flagging
    this explicitly rather than silently picking one, since it changes the
    results materially and there's no obviously-correct choice.

  - Every baseline/augmented model fit records XGBClassifier.feature_
    importances_ for that step. --mode combine averages these across all
    steps per mode and prints/saves the ranked list.

  - --universe {expanded,sp500} (added 2026-09-01, Gabe's suggestion after
    the CHRD/Chord-Energy price-discontinuity bug turned up in this
    script's first real run): "expanded" (default) is the original
    behavior -- current-universe (~1,650 tickers, mkt cap > $2B) UNION
    valid PIT gap tickers. "sp500" further restricts the candidate pool at
    EVERY step to only tickers that were REAL S&P 500 constituents at that
    point in time (pit_universe_continuous.members_asof()) -- a much
    smaller, much more vetted pool, meant as an additional data-quality
    safeguard layered ON TOP OF (not instead of) price_discontinuity.py's
    fix. Output files get a _sp500 suffix so both universes' results can
    coexist and be compared side by side. See allowed_universe_at().

  - MIN_MARKET_CAP / MIN_PRICE point-in-time eligibility floor (Round 7,
    2026-09-01, Gabe's finding): the "current-universe" ticker list
    (scripts/td_data_local/) was built from ONE market-cap-and-price
    screen run against TODAY's values (mkt cap > $2B, price > $10/share) --
    that only decides which ticker SYMBOLS get their full history pulled
    at all, it was never reapplied AT EACH HISTORICAL DATE. That let the
    model "pick" a ticker on a date when it was really a nano-cap penny
    stock, just because it happens to be a $2B+ company TODAY -- confirmed
    concretely for MARA (Marathon Digital), picked in the 2013-07-10 and
    2017-10-20 windows of the first real run, years before the 2021+
    bitcoin-mining boom took it anywhere near mid-cap. This is look-ahead
    bias baked into universe construction, not a modeling choice, and it's
    a big part of why the "expanded" universe's totals were still
    implausibly high even after price_discontinuity.py fixed the CHRD-style
    data bug. Fix: every CURRENT-UNIVERSE candidate (not a validated PIT
    gap ticker -- those already carry a stronger, already point-in-time-
    correct eligibility test, see run_walkforward()) must ALSO have
    market_cap >= MIN_MARKET_CAP ($2B) and close > MIN_PRICE ($10) ON THAT
    SPECIFIC DATE to be scoreable at all -- reapplying the exact same
    screen production uses, just point-in-time instead of once. market_cap
    is Sharadar-filed-shares-outstanding x that day's close (already
    computed point-in-time-correctly in fundamentals_features_pit.py's
    asof_lookup, which carries the latest known share count forward until
    the next filing supersedes it) -- loaded via load_market_cap_series()
    regardless of --mode, since --mode baseline's price-only panel never
    carries fundamentals otherwise. Training data is deliberately NOT
    restricted by this floor (same reasoning backtest_pit.py already
    documents for its own training set) -- this only constrains what the
    model is ALLOWED TO PICK, which is what Gabe specifically asked to fix
    ("the model is following the same rules as it is now... always
    constrained to the mid cap universe").

Run order (baseline/augmented before their stoploss variants, either order
before combine; repeat the whole block with --universe sp500 to also get
the S&P-500-only comparison -- omit --universe entirely for the original
"expanded" behavior, unchanged):
    python3 continuous_walkforward_pit.py --mode baseline
    python3 continuous_walkforward_pit.py --mode augmented
    python3 continuous_walkforward_pit.py --mode baseline_stoploss
    python3 continuous_walkforward_pit.py --mode augmented_stoploss
    python3 continuous_walkforward_pit.py --mode combine

    python3 continuous_walkforward_pit.py --mode baseline --universe sp500
    python3 continuous_walkforward_pit.py --mode augmented --universe sp500
    python3 continuous_walkforward_pit.py --mode baseline_stoploss --universe sp500
    python3 continuous_walkforward_pit.py --mode augmented_stoploss --universe sp500
    python3 continuous_walkforward_pit.py --mode combine --universe sp500

Prerequisites: features_pit.py and fundamentals_features_pit.py must have
already been run (this script depends on out/features_pit.parquet, out/
features_with_fundamentals_pit.parquet, and the out/gap_tickers_used.json
sidecar features_pit.py now writes).
"""
import argparse
import gc
import json
import os

from pathlib import Path

import numpy as np
import pandas as pd
import xgboost as xgb
from xgboost import XGBClassifier

from features import (FEATURE_COLS, FORWARD_WINDOW, LABEL_COL, TRADABLE_LABEL_COL,
                       DATA_DIR, OUT_DIR)
from fundamentals_features_beta import FUNDAMENTAL_FEATURE_COLS
from features_pit import MIN_TRAILING_DAYS
from pit_universe_continuous import gap_tickers_asof, members_asof
from execution import (realize_portfolio, load_ohlc_panel, SegmentedOHLCPanel,
                        apply_turnover_costs,
                        DEFAULT_COST_BPS, DEFAULT_ENTRY_LAG, DEFAULT_ENTRY_AT)

# Hyperparameters, held identical to the XGBClassifier(n_estimators=100,
# max_depth=3, learning_rate=0.1, eval_metric="logloss") the pre-Round-9 runs
# used -- only the training API changed, for memory reasons.
XGB_PARAMS = {"objective": "binary:logistic", "max_depth": 3, "eta": 0.1,
              "eval_metric": "logloss", "tree_method": "hist", "verbosity": 0}
XGB_ROUNDS = 100

TOP_N = 5
CUTOFF_PERCENTILE = 75
NO_STALE_COLS = [c for c in FUNDAMENTAL_FEATURE_COLS if c != "fundamentals_age_days"]
AUGMENTED_FEATURE_COLS = FEATURE_COLS + NO_STALE_COLS
DEFAULT_START_DATE = "2007-01-02"
STOP_LOSS_PCT = 0.30
# Point-in-time mid-cap+ eligibility floor (Round 7) -- the exact screen
# scripts/local_data_pull.py used to build the current-universe ticker list
# in the first place (mkt cap > $2B, price > $10/share), reapplied AT EACH
# STEP instead of only once against today's values. See module docstring.
MIN_MARKET_CAP = 2_000_000_000.0
MIN_PRICE = 10.0
# Repaired delisted panel takes precedence -- see repair_ohlc_coherence.py.
PRICE_DIRS = [DATA_DIR,
              DATA_DIR.parent / "td_data_delisted_repaired",
              DATA_DIR.parent / "td_data_delisted"]

# Round 11 (2026-09-09). With --universe pit, execution reads ONLY the
# Sharadar export. Not "first in the list" -- only. load_ohlc_panel resolves
# collisions by earliest-directory-wins, which would be enough for a ticker
# present in both, but not for one present only in the old directories:
#   * td_data_delisted still holds the 41 wrong-issuer files, so a name
#     missing from the export would silently supply another company's prices;
#   * the two sources sit on different corporate-action bases for ~13% of
#     tickers, so mixing them would price a position on a different series
#     from the one its features were computed on.
PRICE_DIRS_PIT = [DATA_DIR.parent / "td_data_sharadar"]


def price_dirs_for(universe):
    return PRICE_DIRS_PIT if universe == "pit" else PRICE_DIRS


class _ChunkIter(xgb.core.DataIter):
    """Feed XGBoost the training block in chunks.

    Round 9 (2026-09-07): QuantileDMatrix built from one dense array still
    peaks at roughly the size of that array on top of the sketch, and the
    walk-forward's training set GROWS at every step (expanding window), so
    peak RSS climbed ~0.3GB per 15 steps and the run died around step 62.
    Streaming fixed-size chunks makes the peak independent of how much
    history has accumulated -- the bins are the same either way, so the
    resulting model is unchanged.
    """

    def __init__(self, X, y, n, mask=None, chunk=400_000):
        self._X, self._y, self._n = X, y, n
        self._mask, self._chunk = mask, chunk
        self._i = 0
        super().__init__()

    def next(self, input_data):
        while self._i < self._n:
            j = min(self._i + self._chunk, self._n)
            xb = self._X[self._i:j]
            yb = self._y[self._i:j]
            if self._mask is not None:
                mb = self._mask[self._i:j]
                xb, yb = xb[mb], yb[mb]
            self._i = j
            if len(yb):
                input_data(data=xb, label=yb)
                return 1
        return 0

    def reset(self):
        self._i = 0


def _booster_importances(booster, feature_cols):
    """Match XGBClassifier.feature_importances_ (weight, normalized to 1)."""
    raw = booster.get_score(importance_type="weight")
    vals = [float(raw.get(f"f{i}", raw.get(c, 0.0)))
            for i, c in enumerate(feature_cols)]
    tot = sum(vals)
    if tot > 0:
        vals = [v / tot for v in vals]
    return {c: round(v, 5) for c, v in zip(feature_cols, vals)}


def _block_bounds(codes):
    """Start index of each contiguous ticker block, plus a trailing sentinel.
    The panel is written per-ticker in date order, so ticker blocks are
    contiguous -- verified at load time."""
    if len(codes) == 0:
        return np.array([0], dtype=np.int64)
    brk = np.flatnonzero(codes[1:] != codes[:-1]) + 1
    return np.concatenate(([0], brk, [len(codes)])).astype(np.int64)


def _forward_ratio(numer, denom, bounds, fwd_num, fwd_den):
    """(numer[i+fwd_num] / denom[i+fwd_den]) - 1, computed only where both
    offsets stay inside the same ticker block. Everything else is NaN.

    This replaces a pandas groupby().shift(), which on a 7M-row panel
    allocates several intermediate frames and is what pushed the augmented
    run over the memory ceiling.
    """
    n = len(numer)
    out = np.full(n, np.nan, dtype=np.float32)
    for b in range(len(bounds) - 1):
        lo, hi = bounds[b], bounds[b + 1]
        m = hi - lo
        k = m - max(fwd_num, fwd_den)
        if k <= 0:
            continue
        a = numer[lo + fwd_num: lo + fwd_num + k]
        d = denom[lo + fwd_den: lo + fwd_den + k]
        with np.errstate(divide="ignore", invalid="ignore"):
            out[lo: lo + k] = np.where(d > 0, a / d - 1.0, np.nan)
    return out


def load_panel_prepared(path, numeric_cols, filter_cols, horizon):
    """Round 9 (2026-09-07): load a large panel, derive the tradable label and
    apply the feature-NaN row filter, without ever materializing the whole
    thing.

    The naive path -- pd.read_parquet, then groupby().shift() for the label,
    then dropna().copy() -- peaks at roughly three times the finished frame
    (float64 upcast, Arrow's own copy, then a full copy for the filter). On
    the ~930MB augmented panel that is over 3GB and gets OOM-killed.

    Here: pass A reads only ticker/date/open/close and derives both labels
    over the full panel (they need every row, including ones the filter will
    later drop). Pass B streams the feature columns row group by row group,
    keeps only rows with complete features, and writes them straight into
    preallocated arrays. Peak memory is about the size of the result.

    Returns (DataFrame, n_rows_before_filter).
    """
    import pyarrow.parquet as pq

    pf = pq.ParquetFile(path)
    available = set(pf.schema_arrow.names)
    numeric_cols = [c for c in dict.fromkeys(numeric_cols) if c in available]
    filter_cols = [c for c in filter_cols if c in numeric_cols]
    n = pf.metadata.num_rows
    ngroups = pf.metadata.num_row_groups

    # ---- pass A: labels over the full panel -------------------------------
    close = np.empty(n, dtype=np.float32)
    open_ = np.empty(n, dtype=np.float32) if "open" in available else None
    dates = np.empty(n, dtype="datetime64[ns]")
    codes = np.empty(n, dtype=np.int32)
    lookup, order = {}, []
    cols_a = ["ticker", "date", "close"] + (["open"] if open_ is not None else [])
    off = 0
    for i in range(ngroups):
        tbl = pf.read_row_group(i, columns=cols_a)
        m = tbl.num_rows
        close[off:off + m] = tbl.column("close").to_numpy(zero_copy_only=False)
        if open_ is not None:
            open_[off:off + m] = tbl.column("open").to_numpy(zero_copy_only=False)
        dates[off:off + m] = tbl.column("date").to_numpy(zero_copy_only=False)
        for k, t in enumerate(tbl.column("ticker").to_pylist()):
            c = lookup.get(t)
            if c is None:
                c = lookup[t] = len(order)
                order.append(t)
            codes[off + k] = c
        off += m
        del tbl
        gc.collect()

    if not bool((codes[1:] >= codes[:-1]).all()):
        raise SystemExit(
            "  Panel ticker blocks are not contiguous -- load_panel_prepared assumes "
            "the per-ticker, date-ordered layout features_pit.py writes.")
    bounds = _block_bounds(codes)
    lbl_pub = _forward_ratio(close, close, bounds, horizon, 0)
    lbl_trd = (_forward_ratio(close, open_, bounds, horizon, 1)
               if open_ is not None else None)
    del open_
    gc.collect()

    # ---- pass B: filtered fill --------------------------------------------
    keep_numeric = [c for c in numeric_cols if c not in ("open",)]
    X = np.empty((n, len(keep_numeric)), dtype=np.float32)
    d_out = np.empty(n, dtype="datetime64[ns]")
    c_out = np.empty(n, dtype=np.int32)
    p_out = np.empty(n, dtype=np.float32)
    t_out = np.empty(n, dtype=np.float32) if lbl_trd is not None else None

    off = kept = 0
    for i in range(ngroups):
        tbl = pf.read_row_group(i, columns=keep_numeric)
        m = tbl.num_rows
        block = np.empty((m, len(keep_numeric)), dtype=np.float32)
        for j, c in enumerate(keep_numeric):
            block[:, j] = tbl.column(c).to_numpy(zero_copy_only=False)
        del tbl
        idx = [keep_numeric.index(c) for c in filter_cols]
        mask = np.isfinite(block[:, idx]).all(axis=1)
        k = int(mask.sum())
        if k:
            X[kept:kept + k] = block[mask]
            d_out[kept:kept + k] = dates[off:off + m][mask]
            c_out[kept:kept + k] = codes[off:off + m][mask]
            p_out[kept:kept + k] = lbl_pub[off:off + m][mask]
            if t_out is not None:
                t_out[kept:kept + k] = lbl_trd[off:off + m][mask]
            kept += k
        off += m
        del block, mask
        gc.collect()

    del close, dates, codes, lbl_pub, lbl_trd
    gc.collect()

    # Sort by date ONCE here. The walk-forward slices "everything on or before
    # the training cutoff" at every one of ~124 steps; on a date-sorted frame
    # that is a positional slice instead of a boolean mask over 6.6M rows,
    # which is the difference between a view and a full copy each step.
    ordr = np.argsort(d_out[:kept], kind="stable")
    df = pd.DataFrame(X[:kept][ordr], columns=keep_numeric, copy=False)
    df["date"] = d_out[:kept][ordr]
    df["ticker"] = pd.Categorical.from_codes(c_out[:kept][ordr], categories=order)
    df[LABEL_COL] = p_out[:kept][ordr]
    if t_out is not None:
        df[TRADABLE_LABEL_COL] = t_out[:kept][ordr]
    del ordr
    gc.collect()
    return df, n


def load_gap_ticker_set():
    path = OUT_DIR / "gap_tickers_used.json"
    if not path.exists():
        raise FileNotFoundError(
            f"{path} not found -- run features_pit.py first (it now writes this "
            f"sidecar file listing exactly which tickers came from td_data_delisted/ "
            f"this run, so this script always matches whatever was actually pulled, "
            f"211 gap tickers or 339 or otherwise)."
        )
    with open(path) as f:
        return set(json.load(f))


def load_market_cap_series():
    """Point-in-time market_cap for every (ticker, date) that has fundamentals
    coverage, sourced from features_with_fundamentals_pit.parquet regardless
    of which panel (baseline/augmented) this run actually uses -- added
    2026-09-01 (Round 7) so the CURRENT-UNIVERSE portion of the candidate
    pool can be constrained to the SAME market-cap-and-price screen
    production uses (mkt cap > $2B, price > $10/share), reapplied AT EACH
    HISTORICAL DATE instead of only checked once against today's values.
    See the module docstring's Round 7 note for why this matters.

    Returns a DataFrame [ticker, date, market_cap]. A (ticker, date) with no
    row here (no fundamentals filed yet as of that date) has NaN market_cap
    after the merge, which correctly fails the >= MIN_MARKET_CAP check in
    run_walkforward() -- treated as INELIGIBLE, not assumed to pass, same
    "flag/quarantine rather than guess" philosophy as the rest of this
    project (validate_gap_coverage(), KNOWN_DELISTING_DATES,
    price_discontinuity.py)."""
    path = OUT_DIR / "features_with_fundamentals_pit.parquet"
    if not path.exists():
        raise FileNotFoundError(
            f"{path} not found -- run fundamentals_features_pit.py first. The "
            f"point-in-time mid-cap+ eligibility floor needs it even for "
            f"--mode baseline, since market_cap is only ever computed in the "
            f"fundamentals pipeline."
        )
    return pd.read_parquet(path, columns=["ticker", "date", "market_cap"])


def build_gap_validity(feat, gap_tickers):
    """Each gap ticker's earliest available date in THIS panel -- the input
    to the per-step MIN_TRAILING_DAYS check in allowed_universe_at()."""
    present = feat[feat["ticker"].isin(gap_tickers)]
    if present.empty:
        return pd.Series(dtype="datetime64[ns]")
    # observed=True is LOAD-BEARING, not a warning silencer. Round 9 stores
    # "ticker" as a pandas Categorical to fit the panel in memory, and a
    # groupby on a Categorical with observed=False returns EVERY category --
    # all 1,840 tickers -- not just the gap tickers actually present. That
    # made gap_earliest.index contain the whole universe, and since gap
    # tickers are EXEMT from the $2B market-cap and $10 price floors, every
    # candidate became exempt: 100% of picks came back gap-flagged, median
    # entry price fell from $35.63 to $9.46, and the backtest "made" 31x SPY
    # by buying sub-$2 nano-caps. Guarded below.
    out = present.groupby("ticker", observed=True)["date"].min()
    out = out[out.notna()]
    if len(out) > len(set(gap_tickers)):
        raise AssertionError(
            f"build_gap_validity returned {len(out)} tickers but only "
            f"{len(set(gap_tickers))} gap tickers exist -- a categorical groupby "
            f"has leaked unobserved categories into the gap set.")
    return out


PIT_UNIVERSE_PATH = OUT_DIR.parent / "data" / "sharadar" / "pit_universe.parquet"
_PIT_UNIVERSE_CACHE = {}


def load_pit_universe(path=None):
    """date string -> frozenset of tickers eligible on that date.

    Round 11 (2026-09-09). This REPLACES the "$2B today UNION gap tickers"
    pool, which was hindsight-determined: membership could only be known
    after the fact, so a model trained on it could separate survivors from
    non-survivors without learning anything about selection. Measured
    against the rebuilt point-in-time universe, the old pool was missing
    32.1% of eligible domestic names in June 2008, and 89% of what was
    missing had since died.

    pit_universe.parquet already encodes marketcap >= $2B and close > $10
    AS OF each date, and already excludes rows where the vendor's two
    independent market-cap columns disagree by more than 10x. So when this
    is the universe, the separate eligibility floor further down is
    redundant and is skipped -- applying it twice would silently re-impose
    a survivor screen on a pool built specifically to avoid one.
    """
    path = Path(path) if path else PIT_UNIVERSE_PATH
    key = str(path)
    if key in _PIT_UNIVERSE_CACHE:
        return _PIT_UNIVERSE_CACHE[key]
    if not path.exists():
        raise FileNotFoundError(
            f"{path} not found -- run build_pit_universe.py first.")
    u = pd.read_parquet(path, columns=["date", "ticker"])
    u["date"] = u["date"].astype(str).str.slice(0, 10)
    u["ticker"] = u["ticker"].astype(str)
    m = {d: frozenset(g) for d, g in u.groupby("date")["ticker"]}
    print(f"  PIT universe: {len(u):,} rows, {len(m):,} trading days, "
          f"{u['ticker'].nunique():,} distinct tickers, "
          f"{u['date'].min()} .. {u['date'].max()}")
    _PIT_UNIVERSE_CACHE[key] = m
    return m


def allowed_universe_at(tp, current_universe_tickers, gap_earliest,
                        universe="expanded", pit_map=None):
    """universe="expanded" (default, original behavior): current-universe
    tickers UNION valid PIT gap tickers.

    universe="sp500" (added 2026-09-01, Gabe's suggestion): the same set,
    further restricted to only tickers that were REAL S&P 500 constituents
    as of (the nearest snapshot at-or-before) this timepoint --
    pit_universe_continuous.members_asof(). Rationale: index membership
    requires sustained profitability/liquidity, so this pool should be much
    less exposed to the kind of micro-cap data artifact price_discontinuity.py
    was built to catch (e.g. CHRD/Chord-Energy) -- an additional safeguard on
    top of (not instead of) that fix.

    A ticker segmented by price_discontinuity.py (e.g.
    "CHRD__post20201118") won't match members_asof()'s real symbols
    directly, so the sp500 filter matches on the base symbol (the part
    before "__post") -- ticker_orig isn't threaded into this function, but
    the segmentation suffix format is fixed, so stripping it recovers the
    real symbol without needing that extra column here."""
    tp_str = str(tp.date())
    if universe == "pit":
        # The panel may carry price_discontinuity segments ("CHRD__post...")
        # that the universe file, built from raw Sharadar tickers, does not.
        # Match on the base symbol so a segmented ticker is not silently
        # dropped from a pool it belongs in.
        base = pit_map.get(tp_str, frozenset())
        return {t for t in current_universe_tickers
                if t.split("__post")[0] in base} | set(base)
    gap_candidates = gap_tickers_asof(tp_str, current_universe_tickers)
    min_trailing = pd.Timedelta(days=MIN_TRAILING_DAYS)
    valid_gap = {t for t in gap_candidates
                 if t in gap_earliest.index and (tp - gap_earliest[t]) >= min_trailing}
    allowed = set(current_universe_tickers) | valid_gap
    if universe == "sp500":
        sp500_members = members_asof(tp_str)
        allowed = {t for t in allowed if t.split("__post")[0] in sp500_members}
    return allowed


def build_step_dates(all_dates, start_date, step):
    start_idx = all_dates[all_dates >= pd.Timestamp(start_date)].index
    if len(start_idx) == 0:
        return []
    idx = start_idx[0]
    steps = []
    while idx < len(all_dates):
        steps.append(all_dates.iloc[idx])
        idx += step
    return steps


def run_walkforward(feat, all_dates, feature_cols, tag, start_date,
                     current_universe_tickers, gap_earliest, universe="expanded",
                     price_panel=None, entry_lag=DEFAULT_ENTRY_LAG,
                     entry_at=DEFAULT_ENTRY_AT, cost_bps=DEFAULT_COST_BPS,
                     stop_pct=None, label_col=LABEL_COL, resume=False):
    spy = pd.read_csv(DATA_DIR / "SPY.csv", parse_dates=["date"]).sort_values("date").reset_index(drop=True)
    spy["spy_fwd_return"] = spy["close"].shift(-FORWARD_WINDOW) / spy["close"] - 1
    spy = spy.set_index("date")

    embargo_days = FORWARD_WINDOW
    step_dates = build_step_dates(all_dates, start_date, FORWARD_WINDOW)
    if not step_dates:
        print(f"[{tag}] no trading dates on/after {start_date} in this panel -- nothing to run")
        return []
    print(f"[{tag}] universe={universe}, {len(step_dates)} non-overlapping {FORWARD_WINDOW}-day "
          f"windows requested starting {step_dates[0].date()} (panel covers "
          f"{all_dates.min().date()} to {all_dates.max().date()})")

    # Round 9 (2026-09-07): hoist the feature matrix out of the loop.
    # `train[feature_cols]` inside the loop rebuilt a 6.6M x 24 float32 copy
    # at every one of ~124 steps -- ~630MB allocated and thrown away each
    # time, on top of the training slice and XGBoost's own copy. Extract it
    # once as a contiguous float32 array and index it positionally; the frame
    # is only needed for ticker/date/close/market_cap after this.
    # Round 9 (2026-09-07): spill the feature matrix to disk and read it back
    # as a memmap. It is ~640MB, it is needed for the whole run, and holding
    # it resident alongside XGBoost's growing DMatrix is what pins peak RSS
    # near the ceiling on a small box. The chunk iterator reads slices, so the
    # OS pages in only what each batch touches. Written to scratch (NOT into
    # the repo) and removed on exit.
    import tempfile, atexit
    _tmpdir = tempfile.mkdtemp(prefix="pipe_dream_featmat_")
    _mmpath = os.path.join(_tmpdir, "featmat.npy")
    _arr = np.ascontiguousarray(
        feat[feature_cols].to_numpy(dtype=np.float32, copy=False))
    _shape = _arr.shape
    _mm = np.memmap(_mmpath, dtype=np.float32, mode="w+", shape=_shape)
    _mm[:] = _arr
    _mm.flush()
    del _arr, _mm
    gc.collect()
    featmat = np.memmap(_mmpath, dtype=np.float32, mode="r", shape=_shape)

    def _cleanup_featmat(d=_tmpdir):
        import shutil
        shutil.rmtree(d, ignore_errors=True)
    atexit.register(_cleanup_featmat)
    labels = feat[label_col].to_numpy(dtype=np.float32, copy=False)
    dates_arr = feat["date"].values
    # The frame duplicated every feature column that featmat now holds -- on
    # this panel that is ~600MB of dead weight. After this point only
    # ticker/date/close/market_cap are read off the frame.
    _keep_cols = [c for c in ("ticker", "date", "close", "market_cap") if c in feat.columns]
    feat = feat[_keep_cols]
    gc.collect()
    print(f"[{tag}] feature matrix {featmat.shape} float32 "
          f"({featmat.nbytes/1e9:.2f}GB) built once; frame trimmed to {_keep_cols}")

    # Round 9 (2026-09-07): resumable. Each completed timepoint is
    # checkpointed, so a run that is interrupted (or has to be sliced across
    # limited compute windows) picks up where it stopped instead of starting
    # over. Delete out/_ckpt_<tag>.json to force a clean run.
    results = []
    ckpt = OUT_DIR / f"_ckpt_{tag}.json"
    done_tps = set()
    if resume and ckpt.exists():
        try:
            _prev = json.load(open(ckpt))
            results = _prev.get("results", [])
            done_tps = {r["timepoint"] for r in results}
            print(f"[{tag}] resuming from checkpoint: {len(results)} windows already "
                  f"done, last {results[-1]['timepoint'] if results else 'n/a'}")
        except Exception as e:
            print(f"[{tag}] checkpoint unreadable ({e}) -- starting fresh")
            results, done_tps = [], set()
    _pit_map = load_pit_universe() if universe == "pit" else None
    for _n, tp in enumerate(step_dates, 1):
        if str(tp.date()) in done_tps:
            continue
        if _n % 5 == 0 or _n == 1:
            try:
                import resource, sys as _sys
                # ru_maxrss is KILOBYTES on Linux and BYTES on macOS.
                _div = 1e9 if _sys.platform == "darwin" else 1e6
                _rss = resource.getrusage(resource.RUSAGE_SELF).ru_maxrss / _div
            except Exception:
                _rss = float("nan")
            print(f"[{tag}] step {_n}/{len(step_dates)} {tp.date()} "
                  f"({len(results)} windows kept, peakRSS {_rss:.2f}GB)", flush=True)
            with open(ckpt, "w") as f:
                json.dump({"tag": tag, "completed": _n, "results": results}, f)
        idx = all_dates[all_dates == tp].index[0]
        if idx < embargo_days:
            continue
        train_cutoff_date = all_dates.iloc[idx - embargo_days]
        # Round 9 (2026-09-07): the label filter belongs HERE, on the
        # TRAINING set only -- not on the whole panel before the loop. See
        # the note in main() on the survivorship hole that created.
        # feat is date-sorted (load_panel_prepared), so searchsorted gives the
        # cutoff boundary and the slice is positional rather than a boolean
        # mask over the whole panel.
        _hi = int(np.searchsorted(dates_arr, np.datetime64(train_cutoff_date), "right"))
        _lab = labels[:_hi]
        _fin = np.isfinite(_lab)
        _n_train = int(_fin.sum())
        if _n_train < 300:
            print(f"[{tag}] skip {tp.date()}: only {_n_train} training rows")
            continue

        allowed = allowed_universe_at(tp, current_universe_tickers,
                                      gap_earliest, universe, _pit_map)

        # Round 9 (2026-09-07): never materialize the training block.
        # `featmat[_keep]` was a fancy-index copy that grew with the expanding
        # window (~630MB by the last step) and is what kept OOM-killing the
        # run. The mask is applied inside the chunk iterator instead, so peak
        # memory is one chunk regardless of how much history has accumulated.
        y_lab = _lab[_fin]
        cutoff_val = np.percentile(y_lab, CUTOFF_PERCENTILE)
        del y_lab
        y_all = (_lab > cutoff_val).astype(np.int8)
        dtrain = xgb.QuantileDMatrix(
            _ChunkIter(featmat, y_all, _hi, mask=_fin), max_bin=256)
        del y_all, _lab, _fin
        gc.collect()
        booster = xgb.train(XGB_PARAMS, dtrain, num_boost_round=XGB_ROUNDS)
        del dtrain
        gc.collect()

        _lo = int(np.searchsorted(dates_arr, np.datetime64(tp), "left"))
        _hi2 = int(np.searchsorted(dates_arr, np.datetime64(tp), "right"))
        test_rows = feat.iloc[_lo:_hi2]
        test_pos = np.arange(_lo, _hi2)
        _sel = test_rows["ticker"].isin(allowed).values
        test_rows = test_rows[_sel]
        test_pos = test_pos[_sel]
        if test_rows.empty:
            del booster
            gc.collect()
            continue

        # Point-in-time mid-cap+ eligibility floor (Round 7) -- a
        # CURRENT-UNIVERSE candidate must ALSO clear market_cap >=
        # MIN_MARKET_CAP and close > MIN_PRICE ON THIS DATE, not just be a
        # $2B+ company today. Gap tickers are exempt: their eligibility
        # already comes from being a REAL historical S&P 500 constituent as
        # of this date (a stronger, already point-in-time-correct proxy),
        # and Sharadar's fundamentals coverage for many older delisted names
        # is too spotty to apply this cleanly -- a legitimately-eligible gap
        # ticker with no market_cap on file would otherwise be wrongly
        # disqualified. See module docstring.
        if universe == "pit":
            # Already applied, point-in-time, when the universe was built.
            # See load_pit_universe(): re-applying a market_cap floor here
            # would use the panel's own market_cap column, which is a
            # DIFFERENT quantity (close x sharesbas) from the one the
            # universe was screened on, and would reintroduce a survivor
            # screen on a pool built specifically to avoid one.
            _ok = np.ones(len(test_rows), dtype=bool)
        else:
            is_gap_candidate = test_rows["ticker"].isin(gap_earliest.index)
            meets_price = test_rows["close"] > MIN_PRICE
            meets_cap = test_rows["market_cap"] >= MIN_MARKET_CAP
            _ok = (is_gap_candidate | (meets_price & meets_cap)).values
        test_rows = test_rows[_ok]
        test_pos = test_pos[_ok]
        if test_rows.empty:
            print(f"[{tag}] skip {tp.date()}: no candidates cleared the point-in-time "
                  f"mid-cap+ eligibility floor")
            del booster
            gc.collect()
            continue

        test_rows = test_rows.copy()
        test_rows["buy_proba"] = booster.inplace_predict(featmat[test_pos])

        # Round 9 (2026-09-07): the picks are whatever the model ranked
        # highest -- a name is NOT quietly dropped because its forward label
        # is missing. A missing label overwhelmingly means the price series
        # ends inside the holding window, i.e. the position blew up or was
        # delisted, which is exactly the outcome that must be counted.
        picks_realized = test_rows.sort_values("buy_proba", ascending=False).head(TOP_N)
        if picks_realized.empty:
            del booster, test_rows
            gc.collect()
            continue

        if price_panel is not None:
            # Realistic execution: signal on close[tp], enter one bar later,
            # stop fills that honour gap-throughs, exit at the last available
            # print when the series ends mid-window, and transaction costs.
            port, per_ticker = realize_portfolio(
                picks_realized["ticker"].tolist(), price_panel, tp, FORWARD_WINDOW,
                entry_lag=entry_lag, entry_at=entry_at, stop_pct=stop_pct,
                cost_bps=cost_bps)
            if port is None:
                print(f"[{tag}] skip {tp.date()}: none of the picks were tradable")
                del booster, test_rows
                gc.collect()
                continue
            portfolio_return = port["net_return"]
        else:
            # Legacy path: same-bar entry off the precomputed label. Kept only
            # for reproducing the pre-Round-9 numbers.
            lbl = picks_realized[label_col].dropna()
            if lbl.empty:
                del booster, test_rows
                gc.collect()
                continue
            portfolio_return = (1.0 / len(lbl) * (1 + lbl)).sum() - 1
            port, per_ticker = None, {}

        spy_return = (float(spy.loc[tp, "spy_fwd_return"])
                      if tp in spy.index and pd.notna(spy.loc[tp, "spy_fwd_return"]) else None)

        n_gap_picks = int(picks_realized["ticker"].isin(gap_earliest.index).sum())

        results.append({
            "timepoint": str(tp.date()),
            "picks": picks_realized["ticker"].tolist(),
            "pick_entry_close": {row["ticker"]: float(row["close"]) for _, row in picks_realized.iterrows()},
            "n_candidates_scored": len(test_rows),
            "n_gap_tickers_eligible": len(allowed) - len(current_universe_tickers),
            "gap_picks": n_gap_picks,
            "model_return_pct": round(float(portfolio_return) * 100, 2),
            "execution": ({"entry_lag": entry_lag, "entry_at": entry_at,
                            "cost_bps": cost_bps, "stop_pct": stop_pct,
                            "n_positions": port["n_positions"],
                            "gross_return_pct": round(port["gross_return"] * 100, 2),
                            "n_stopped": port["n_stopped"],
                            "n_gap_through": port["n_gap_through"],
                            "n_series_end_exits": port["n_truncated"],
                            "per_ticker_gross": {k: round(v["gross_return"], 6)
                                                  for k, v in per_ticker.items()}}
                           if port is not None else None),
            "spy_return_pct": round(float(spy_return) * 100, 2) if spy_return is not None else None,
            "beat_spy": bool(spy_return is not None and portfolio_return > spy_return),
            "feature_importances": _booster_importances(booster, feature_cols),
        })

        del booster, test_rows
        gc.collect()

    return results


def simulate_stop_loss(picks_result, price_by_ticker, stop_pct=STOP_LOSS_PCT):
    """Re-simulate one step's picks under a stop_pct stop-loss rule
    (default 30%, see STOP_LOSS_PCT -- parameterized 2026-09-02, Round 8,
    so callers can sweep it instead of only ever testing 30%). See the
    module docstring for the LOW-vs-CLOSE trigger caveat. Falls back to
    each ticker's own (entry -> last available close in the 40-day window)
    return when the stop never triggers -- this already reflects the
    delisting exit-floor behavior for a ticker that stops trading mid-
    window, same as the original label did."""
    tp = pd.Timestamp(picks_result["timepoint"])
    picks = picks_result["picks"]
    entry_prices = picks_result["pick_entry_close"]

    per_ticker_returns = {}
    stop_triggered_on = {}
    for ticker in picks:
        entry = entry_prices.get(ticker)
        if ticker not in price_by_ticker or entry is None or entry <= 0:
            continue
        g = price_by_ticker[ticker]
        window = g[g["date"] > tp].head(FORWARD_WINDOW)
        if window.empty:
            continue
        stop_price = entry * (1 - stop_pct)
        hit = window[window["low"] <= stop_price]
        if not hit.empty:
            # Round 9 (2026-09-07): fill at min(stop, that bar's open) rather
            # than at exactly -stop_pct. 42% of positions were being booked at
            # precisely -15.00% on names selected for maximum trailing
            # volatility; a bar that opened below the trigger never offered
            # the trigger price, and roughly 12% of stopped names ended the
            # window below -50% on the unstopped path -- those gapped straight
            # through. Booking them at -15% is a fiction worth several
            # percentage points of annual return.
            bar = hit.iloc[0]
            bar_open = float(bar["open"]) if "open" in bar else float("nan")
            fill = min(stop_price, bar_open) if np.isfinite(bar_open) else stop_price
            per_ticker_returns[ticker] = float(fill / entry - 1.0)
            stop_triggered_on[ticker] = str(bar["date"].date())
        else:
            last_close = window["close"].iloc[-1]
            per_ticker_returns[ticker] = float(last_close / entry - 1)

    if not per_ticker_returns:
        return None

    per_stock_weight = 1.0 / len(per_ticker_returns)
    portfolio_return = sum(per_stock_weight * (1 + r) for r in per_ticker_returns.values()) - 1
    spy_return_pct = picks_result["spy_return_pct"]

    return {
        "timepoint": picks_result["timepoint"],
        "picks": list(per_ticker_returns.keys()),
        "per_ticker_returns_pct": {t: round(r * 100, 2) for t, r in per_ticker_returns.items()},
        "stop_triggered_on": stop_triggered_on,
        "n_stopped_out": len(stop_triggered_on),
        "model_return_pct": round(float(portfolio_return) * 100, 2),
        "spy_return_pct": spy_return_pct,
        "beat_spy": bool(spy_return_pct is not None and portfolio_return * 100 > spy_return_pct),
    }


def _stop_pct_suffix(stop_pct):
    """Filename suffix for a non-default stop percentage (Round 8) --
    "" for the original 30% default (keeps existing filenames unchanged),
    "_stop{NN}" otherwise, e.g. 0.15 -> "_stop15"."""
    if abs(stop_pct - STOP_LOSS_PCT) < 1e-9:
        return ""
    return f"_stop{round(stop_pct * 100)}"


def _load_lean_low_close_panel(universe="expanded"):
    """The [ticker, date, low, close] panel every stop-loss simulation needs,
    grouped per ticker -- factored out (Round 8) so the sweep mode loads it
    ONCE instead of once per stop percentage tested."""
    # Round 9 (2026-09-07): this now reads the OHLC CSV panel rather than
    # features_pit.parquet, for two reasons. It needs `open` (a stop that
    # gapped through must fill at the open, not at the trigger), and the
    # repaired delisted panel is only available as CSVs -- see
    # repair_ohlc_coherence.py for why the raw delisted panel must not be
    # used for anything that reads intraday columns.
    return load_ohlc_panel(price_dirs_for(universe))


def _run_stoploss(mode, universe="expanded", stop_pct=STOP_LOSS_PCT):
    suffix = "" if universe == "expanded" else f"_{universe}"
    stop_suffix = _stop_pct_suffix(stop_pct)
    base_mode = mode.replace("_stoploss", "")
    src_path = OUT_DIR / f"continuous_walkforward_pit_{base_mode}{suffix}.json"
    if not src_path.exists():
        raise FileNotFoundError(
            f"{src_path} not found -- run `--mode {base_mode} --universe {universe}` first. "
            f"The stop-loss modes re-simulate that run's picks day-by-day, they don't retrain "
            f"a model."
        )
    with open(src_path) as f:
        src = json.load(f)

    print(f"Loading daily low/close price panel for stop-loss re-simulation ({mode}, "
          f"universe={universe}, stop_pct={stop_pct:.0%})...")
    price_by_ticker = _load_lean_low_close_panel(universe)

    results = []
    for r in src["results"]:
        sim = simulate_stop_loss(r, price_by_ticker, stop_pct)
        if sim is not None:
            results.append(sim)

    out_path = OUT_DIR / f"continuous_walkforward_pit_{mode}{suffix}{stop_suffix}.json"
    with open(out_path, "w") as f:
        json.dump({"mode": mode, "universe": universe, "base_run": base_mode,
                    "stop_pct": stop_pct, "results": results}, f, indent=2)

    if results:
        wins = sum(r["beat_spy"] for r in results)
        total_stopped = sum(r["n_stopped_out"] for r in results)
        print(f"{mode} (universe={universe}, stop_pct={stop_pct:.0%}): {len(results)} windows, "
              f"{wins} beat SPY ({wins/len(results):.0%}), {total_stopped} individual picks "
              f"stopped out (-{stop_pct:.0%}) across all windows, steps {results[0]['timepoint']} "
              f"to {results[-1]['timepoint']}")
    else:
        print(f"{mode} (universe={universe}, stop_pct={stop_pct:.0%}): 0 windows produced")
    print(f"Saved -> {out_path}")


DEFAULT_STOP_GRID = [0.05, 0.10, 0.15, 0.20, 0.25, 0.30, 0.35, 0.40, 0.45, 0.50]


def _run_stoploss_sweep(mode, universe="expanded", grid=None):
    """Round 8 (2026-09-02, Gabe's ask: 'can we optimize the stop
    percentage'): re-simulates the SAME base picks (loaded once) across a
    grid of stop percentages instead of only ever testing the original
    30% default, so the optimal stop level can be picked empirically
    instead of assumed. mode is e.g. "augmented_stoploss_sweep" ->
    base_mode "augmented". Prints a comparison table (total $, win rate,
    stopped-out count per stop_pct) and saves it, plus writes each
    individual stop_pct's normal per-mode JSON (identical to what
    `--mode {base}_stoploss --stop-pct X` would produce) so `--mode
    combine --stop-pct X` can pick any of them up afterward."""
    grid = grid if grid is not None else DEFAULT_STOP_GRID
    suffix = "" if universe == "expanded" else f"_{universe}"
    base_mode = mode.replace("_stoploss_sweep", "")
    src_path = OUT_DIR / f"continuous_walkforward_pit_{base_mode}{suffix}.json"
    if not src_path.exists():
        raise FileNotFoundError(
            f"{src_path} not found -- run `--mode {base_mode} --universe {universe}` first."
        )
    with open(src_path) as f:
        src = json.load(f)

    print(f"Loading daily low/close price panel once for the sweep ({len(grid)} stop "
          f"percentages, universe={universe})...")
    price_by_ticker = _load_lean_low_close_panel(universe)

    sweep_rows = []
    for stop_pct in grid:
        results = []
        for r in src["results"]:
            sim = simulate_stop_loss(r, price_by_ticker, stop_pct)
            if sim is not None:
                results.append(sim)

        stoploss_mode = f"{base_mode}_stoploss"
        stop_suffix = _stop_pct_suffix(stop_pct)
        out_path = OUT_DIR / f"continuous_walkforward_pit_{stoploss_mode}{suffix}{stop_suffix}.json"
        with open(out_path, "w") as f:
            json.dump({"mode": stoploss_mode, "universe": universe, "base_run": base_mode,
                        "stop_pct": stop_pct, "results": results}, f, indent=2)

        if not results:
            sweep_rows.append({"stop_pct": stop_pct, "windows": 0})
            continue

        v = 10000.0
        for r in results:
            v = v * (1 + r["model_return_pct"] / 100)
        wins = sum(r["beat_spy"] for r in results)
        total_stopped = sum(r["n_stopped_out"] for r in results)
        window_returns = [r["model_return_pct"] / 100 for r in results]
        mean_ret = float(np.mean(window_returns))
        std_ret = float(np.std(window_returns))
        pseudo_sharpe = (mean_ret / std_ret) if std_ret > 0 else None
        sweep_rows.append({
            "stop_pct": stop_pct,
            "windows": len(results),
            "final_value": round(v, 2),
            "wins_vs_spy": wins,
            "win_rate": round(wins / len(results), 4),
            "total_stopped_out": total_stopped,
            "mean_window_return_pct": round(mean_ret * 100, 3),
            "std_window_return_pct": round(std_ret * 100, 3),
            "pseudo_sharpe_per_window": round(pseudo_sharpe, 3) if pseudo_sharpe is not None else None,
        })

    print(f"\n=== Stop-percentage sweep: {mode} (universe={universe}), $10k start ===")
    print(f"{'stop_pct':>9} {'windows':>8} {'final_value':>14} {'win_rate':>9} "
          f"{'stopped_out':>12} {'mean_win_%':>11} {'std_win_%':>10} {'pseudo_sharpe':>13}")
    best = max((r for r in sweep_rows if r.get("windows")), key=lambda r: r["final_value"], default=None)
    for r in sweep_rows:
        if not r.get("windows"):
            print(f"{r['stop_pct']:>8.0%}   0 windows produced")
            continue
        marker = "  <-- best final $" if best is not None and r is best else ""
        print(f"{r['stop_pct']:>9.0%} {r['windows']:>8} {r['final_value']:>14,.2f} "
              f"{r['win_rate']:>9.0%} {r['total_stopped_out']:>12} "
              f"{r['mean_window_return_pct']:>10.2f}% {r['std_window_return_pct']:>9.2f}% "
              f"{('—' if r['pseudo_sharpe_per_window'] is None else r['pseudo_sharpe_per_window']):>13}{marker}")

    out_path = OUT_DIR / f"continuous_walkforward_pit_{mode}{suffix}.json"
    with open(out_path, "w") as f:
        json.dump({"mode": mode, "universe": universe, "base_run": base_mode,
                    "grid": grid, "sweep": sweep_rows}, f, indent=2)
    print(f"\nSaved sweep summary -> {out_path}")
    print(f"Saved each grid point's own JSON too (e.g. "
          f"continuous_walkforward_pit_{base_mode}_stoploss{suffix}_stop{{NN}}.json) -- pick the best "
          f"stop_pct, then run `--mode combine --universe {universe} --stop-pct <that value>` to fold "
          f"it into the summary curves.")


def _combine(universe="expanded", stop_pct=STOP_LOSS_PCT):
    suffix = "" if universe == "expanded" else f"_{universe}"
    stop_suffix = _stop_pct_suffix(stop_pct)
    modes = ["baseline", "augmented", "baseline_stoploss", "augmented_stoploss"]
    loaded = {}
    for m in modes:
        # the two stoploss modes carry the stop_pct suffix (Round 8); the
        # non-stoploss modes are unaffected by stop_pct, so no suffix there
        m_suffix = stop_suffix if m.endswith("_stoploss") else ""
        p = OUT_DIR / f"continuous_walkforward_pit_{m}{suffix}{m_suffix}.json"
        if p.exists():
            with open(p) as f:
                data = json.load(f)["results"]
            if data:
                loaded[m] = data
        else:
            print(f"NOTE: {p} not found, skipping {m} (run `--mode {m} --universe {universe}` "
                  + (f"--stop-pct {stop_pct} " if m.endswith("_stoploss") else "")
                  + "first if you want it included).")

    if not loaded:
        print("Nothing to combine -- run at least one mode first.")
        return

    def compound(results):
        curve = [{"timepoint": None, "value": 10000.0}]
        v = 10000.0
        for r in results:
            v = v * (1 + r["model_return_pct"] / 100)
            curve.append({"timepoint": r["timepoint"], "value": round(v, 2)})
        return curve

    def compound_spy(results):
        curve = [{"timepoint": None, "value": 10000.0}]
        v = 10000.0
        for r in results:
            if r["spy_return_pct"] is None:
                curve.append({"timepoint": r["timepoint"], "value": round(v, 2)})
                continue
            v = v * (1 + r["spy_return_pct"] / 100)
            curve.append({"timepoint": r["timepoint"], "value": round(v, 2)})
        return curve

    out = {"universe": universe, "stop_pct": stop_pct, "curves": {}, "results": loaded}
    print(f"\n=== Continuous PIT walk-forward summary (universe={universe}, "
          f"stop_pct={stop_pct:.0%}) ===")
    spy_source = next(iter(loaded.values()))
    out["curves"]["spy"] = compound_spy(spy_source)
    print(f"{'SPY':20s} $10k -> ${out['curves']['spy'][-1]['value']:>12,.2f}  "
          f"({len(spy_source)} windows, {spy_source[0]['timepoint']} to {spy_source[-1]['timepoint']})")

    for m in modes:
        if m not in loaded:
            continue
        results = loaded[m]
        curve = compound(results)
        out["curves"][m] = curve
        wins = sum(r["beat_spy"] for r in results)
        print(f"{m:20s} $10k -> ${curve[-1]['value']:>12,.2f}  "
              f"({len(results)} windows, {wins} beat SPY ({wins/len(results):.0%}), "
              f"{results[0]['timepoint']} to {results[-1]['timepoint']})")

    print("\n=== Aggregate feature importance (mean XGBClassifier.feature_importances_"
          " across all steps) ===")
    out["feature_importance_avg"] = {}
    for m in ("baseline", "augmented"):
        if m not in loaded:
            continue
        imps = [r["feature_importances"] for r in loaded[m] if "feature_importances" in r]
        if not imps:
            continue
        cols = list(imps[0].keys())
        avg = {c: float(np.mean([d.get(c, 0.0) for d in imps])) for c in cols}
        ranked = sorted(avg.items(), key=lambda kv: -kv[1])
        out["feature_importance_avg"][m] = {c: round(v, 5) for c, v in ranked}
        print(f"\n{m} ({len(imps)} steps):")
        for c, v in ranked:
            print(f"  {c:28s} {v*100:5.1f}%")

    out_path = OUT_DIR / f"continuous_walkforward_pit_summary{suffix}{stop_suffix}.json"
    with open(out_path, "w") as f:
        json.dump(out, f, indent=2)
    print(f"\nSaved -> {out_path}")


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--mode", choices=["baseline", "augmented", "baseline_stoploss",
                                            "augmented_stoploss", "baseline_stoploss_sweep",
                                            "augmented_stoploss_sweep", "combine"], required=True)
    parser.add_argument("--start", default=DEFAULT_START_DATE,
                         help="Earliest step date to attempt (default 2007-01-02 -- reaches "
                              "for 2008 coverage; the actual first step used depends on real "
                              "trailing-history availability, see the printed output).")
    parser.add_argument("--execution", choices=["realistic", "as_published"],
                         default="realistic",
                         help="Round 9 (2026-09-07). 'realistic' (default) prices every "
                              "position through execution.py: signal on close[t], entry one "
                              "bar later, gap-through-aware stop fills, exit at the last "
                              "available print when a series ends mid-window, and transaction "
                              "costs. 'as_published' reproduces the pre-Round-9 same-bar, "
                              "zero-cost numbers and should only be used for comparison.")
    parser.add_argument("--entry-at", choices=["open", "close"], default=DEFAULT_ENTRY_AT,
                         help="Which print of the entry bar is transacted (default open).")
    parser.add_argument("--cost-bps", type=float, default=DEFAULT_COST_BPS,
                         help="Round-trip transaction cost in basis points (default 50).")
    parser.add_argument("--walkforward-stop", type=float, default=None,
                         help="Stop-loss level applied INSIDE the walk-forward run, e.g. 0.15 "
                              "(distinct from --stop_pct, which re-simulates an already-"
                              "completed run). Omit for no stop.")
    parser.add_argument("--label", choices=["tradable", "as_published"], default="tradable",
                         help="Round 9 (2026-09-07). Training target. 'tradable' (default) "
                              "trains on close[t+H]/open[t+1] -- the return actually "
                              "obtainable from a signal computed on close[t]. 'as_published' "
                              "trains on close[t+H]/close[t], which credits an overnight move "
                              "the strategy cannot capture and which carried the entire "
                              "published edge. Requires features.py to have been re-run so the "
                              "panel carries the tradable label column.")
    parser.add_argument("--cost-model", choices=["turnover_aware", "per_window"],
                         default="turnover_aware",
                         help="Round 9 (2026-09-07). 'turnover_aware' (default) charges a "
                              "round trip only when a position is actually opened or closed "
                              "-- a name re-selected at the next step is held, not sold and "
                              "rebought. 'per_window' charges every position every window, "
                              "which overstates cost by ~33% at the measured ~75% turnover.")
    parser.add_argument("--resume", action="store_true",
                         help="Continue from out/_ckpt_<mode>.json instead of restarting. "
                              "Timepoints already recorded are skipped.")
    parser.add_argument("--panel", default=None,
                         help="Explicit path to the feature panel parquet, "
                              "overriding the mode/universe default.")
    parser.add_argument("--universe", choices=["expanded", "sp500", "pit"], default="expanded",
                         help="expanded (default, unchanged behavior): current-universe "
                              "(~1,650 tickers, mkt cap > $2B) UNION valid PIT gap tickers. "
                              "sp500 (added 2026-09-01, Gabe's suggestion): further restrict "
                              "the candidate pool at EVERY step to only tickers that were REAL "
                              "S&P 500 constituents at that point in time "
                              "(pit_universe_continuous.members_asof()) -- a much smaller, more "
                              "vetted pool, meant as an additional data-quality safeguard on top "
                              "of (not instead of) price_discontinuity.py's fix, not a "
                              "replacement for it. Output files get a _sp500 suffix so both "
                              "universes' results can coexist and be compared.")
    parser.add_argument("--stop-pct", type=float, default=STOP_LOSS_PCT,
                         help="Stop-loss percentage as a fraction (default 0.30 = 30%%, the "
                              "original hardcoded value). Only meaningful for --mode "
                              "{baseline,augmented}_stoploss and --mode combine -- picks which "
                              "stop_pct's saved stoploss JSON to read/write (Round 8, "
                              "2026-09-02). Ignored for --mode {baseline,augmented} (the base "
                              "picks don't depend on the stop rule) and for the _sweep modes "
                              "(use --stop-grid there instead).")
    parser.add_argument("--stop-grid", default=None,
                         help="Comma-separated stop percentages to sweep, e.g. "
                              "'0.10,0.20,0.30,0.40'. Only used by --mode "
                              "{baseline,augmented}_stoploss_sweep. Defaults to "
                              f"{DEFAULT_STOP_GRID} if not given.")
    args = parser.parse_args()

    suffix = "" if args.universe == "expanded" else f"_{args.universe}"

    if args.mode == "combine":
        _combine(args.universe, args.stop_pct)
        return

    if args.mode in ("baseline_stoploss_sweep", "augmented_stoploss_sweep"):
        grid = ([float(x) for x in args.stop_grid.split(",")] if args.stop_grid else None)
        _run_stoploss_sweep(args.mode, args.universe, grid)
        return

    if args.mode in ("baseline_stoploss", "augmented_stoploss"):
        _run_stoploss(args.mode, args.universe, args.stop_pct)
        return

    print(f"Loading PIT panel for mode={args.mode}...")
    if args.panel:
        panel_path = Path(args.panel)
    elif args.universe == "pit":
        panel_path = OUT_DIR / (
            "features_with_fundamentals_sharadar_pit.parquet"
            if args.mode == "augmented" else "features_sharadar_pit.parquet")
    else:
        panel_path = OUT_DIR / ("features_with_fundamentals_pit.parquet"
                                 if args.mode == "augmented"
                                 else "features_pit.parquet")
    if not panel_path.exists():
        raise FileNotFoundError(
            f"{panel_path} not found -- run features_pit.py"
            + (" and fundamentals_features_pit.py" if args.mode == "augmented" else "")
            + " first."
        )
    cols = NO_STALE_COLS if args.mode == "augmented" else []
    # Round 9 (2026-09-07): read ONLY the columns actually used. The full
    # panel is ~930MB on disk and materializing every column costs several GB
    # of RAM for no reason. "open" is read so the tradable label can be
    # derived here rather than requiring a full features.py rebuild.
    numeric = ["close", "open", "market_cap"] + FEATURE_COLS + cols
    feat, n_before = load_panel_prepared(panel_path, numeric, FEATURE_COLS, FORWARD_WINDOW)
    print(f"  {len(feat):,} of {n_before:,} rows carry complete features "
          f"({feat['ticker'].nunique()} tickers); both labels derived over the full panel "
          f"before filtering.")
    gc.collect()

    if "market_cap" not in feat.columns:
        # --mode baseline's price-only panel never carries fundamentals --
        # pull market_cap in from the fundamentals panel regardless, so the
        # point-in-time mid-cap+ eligibility floor (Round 7, MIN_MARKET_CAP
        # below) applies identically to baseline and augmented.
        print("  Loading point-in-time market_cap for the mid-cap+ eligibility "
              "floor (baseline mode doesn't carry fundamentals otherwise)...")
        feat = feat.merge(load_market_cap_series(), on=["ticker", "date"], how="left")
    feat["market_cap"] = feat["market_cap"].astype("float32")
    gc.collect()

    gap_tickers = load_gap_ticker_set()
    current_universe_tickers = set(map(str, feat["ticker"].unique())) - gap_tickers
    gap_earliest = build_gap_validity(feat, gap_tickers)

    # Round 9 (2026-09-07) -- SURVIVORSHIP FIX.
    #
    # This used to read `.dropna(subset=FEATURE_COLS + [LABEL_COL])`, which
    # removed every row with a missing FORWARD LABEL before the walk-forward
    # loop ever ran. A stock whose price series ends within the next 40
    # trading days has no forward label -- so it was deleted from the
    # candidate pool on precisely the dates it was about to stop trading.
    # The model literally could not pick a name on the eve of its blow-up.
    #
    # Candidates now only need FEATURES (you cannot score a row without
    # them). A missing label is no longer disqualifying: execution.py
    # realizes such a position at the last available print, which is the
    # honest outcome. The label filter moved into run_walkforward, where it
    # belongs -- on the TRAINING set only.
    label_col = TRADABLE_LABEL_COL if args.label == "tradable" else LABEL_COL
    if label_col not in feat.columns:
        raise SystemExit(
            f"\n  The feature panel does not carry '{label_col}'.\n"
            f"  Re-run features.py (and fundamentals_features_pit.py) to rebuild the panel "
            f"with the tradable label, or pass --label as_published to train on the old "
            f"close[t+H]/close[t] target.\n"
            f"  See AGENTS.md, Round 9, for why the tradable label is the right default.")
    print(f"  Training target: {label_col}")
    # Round 9: drop the label we are NOT training on before the row filter --
    # on a 7M-row panel every surviving column costs ~28MB and the filter
    # below copies the frame once.
    _unused = LABEL_COL if label_col == TRADABLE_LABEL_COL else TRADABLE_LABEL_COL
    if _unused in feat.columns:
        feat.drop(columns=[_unused], inplace=True)
        gc.collect()

    # The feature-NaN filter was applied during load (see
    # load_panel_prepared) -- the full unfiltered frame is never materialized.
    feat_restricted = feat
    del feat
    gc.collect()
    all_dates = feat_restricted["date"].drop_duplicates().sort_values().reset_index(drop=True)
    print(f"  {len(feat_restricted)} rows, {feat_restricted['ticker'].nunique()} tickers "
          f"({len(current_universe_tickers)} current-universe, {len(gap_tickers)} gap tickers "
          f"found on disk, {len(gap_earliest)} of those present in this feature panel), "
          f"dates {all_dates.min().date()} to {all_dates.max().date()}")
    if args.universe == "pit":
        # Do NOT print the old floor here -- it is not applied on this path,
        # and a log line claiming a screen that is not running is how a
        # wrong result gets believed later.
        print(f"  Eligibility comes from pit_universe.parquet: marketcap >= "
              f"${MIN_MARKET_CAP:,.0f} and closeunadj > ${MIN_PRICE:.0f} applied "
              f"AS OF each date, on domestic common stock, excluding rows where "
              f"the vendor's two market-cap columns disagree by >10x. The old "
              f"current-universe floor and the gap-ticker exemption are both "
              f"skipped -- see load_pit_universe().")
    else:
        print(f"  Point-in-time mid-cap+ eligibility floor active for current-universe candidates: "
              f"market_cap >= ${MIN_MARKET_CAP:,.0f} and close > ${MIN_PRICE:.0f} ON THE PICK DATE "
              f"(gap tickers exempt, see module docstring Round 7)")

    feature_cols = AUGMENTED_FEATURE_COLS if args.mode == "augmented" else FEATURE_COLS
    price_panel = None
    if args.execution == "realistic":
        needed = set(feat_restricted["ticker"].unique())
        print(f"  Loading OHLC panel for realistic execution "
              f"(entry_lag={DEFAULT_ENTRY_LAG}, entry_at={args.entry_at}, "
              f"cost={args.cost_bps:.0f}bp, stop={args.walkforward_stop})...")
        # Segment bounds straight off the panel: a "__post" identity is a
        # DIFFERENT security from its pre-break namesake, and execution must
        # not price across the break. See SegmentedOHLCPanel.
        _b = feat_restricted.groupby("ticker", observed=True)["date"].agg(["min", "max"])
        segments = {t: (str(t).split("__post")[0], r["min"], r["max"])
                    for t, r in _b.iterrows()}
        _nseg = sum(1 for t in segments if "__post" in str(t))
        price_panel = SegmentedOHLCPanel(price_dirs_for(args.universe), segments)
        print(f"  execution price panel is lazy and segment-aware "
              f"({len(needed)} tickers eligible, {_nseg} post-break segments)")
        del _b
        gc.collect()

    results = run_walkforward(feat_restricted, all_dates, feature_cols, args.mode,
                               args.start, current_universe_tickers, gap_earliest, args.universe,
                               price_panel=price_panel, entry_at=args.entry_at,
                               cost_bps=args.cost_bps, stop_pct=args.walkforward_stop,
                               label_col=label_col, resume=args.resume)

    results = sorted(results, key=lambda r: r["timepoint"])
    if args.execution == "realistic" and args.cost_model == "turnover_aware":
        # Re-price costs on actual turnover: a name the model re-selects is
        # held, not sold and rebought. See execution.apply_turnover_costs.
        results = apply_turnover_costs(results, args.cost_bps)
        _fn = np.mean([r["execution"]["frac_new"] for r in results
                        if r.get("execution", {}).get("frac_new") is not None])
        print(f"  turnover-aware costs applied at {args.cost_bps:.0f}bp: "
              f"{_fn:.0%} of each window's book is new (a per-window round trip on "
              f"every name would assume 100%)")
    # Round 9 (2026-09-07): a realistic-execution run writes to its OWN file.
    # It is not comparable to the pre-Round-9 same-bar, zero-cost numbers and
    # must never silently overwrite them -- the published baseline is the
    # reference every corrected result is measured against.
    _exec_tag = "" if args.execution == "as_published" else "_realistic"
    if _exec_tag and args.label == "tradable":
        _exec_tag += "_tradable"
    out_path = OUT_DIR / f"continuous_walkforward_pit_{args.mode}{suffix}{_exec_tag}.json"
    with open(out_path, "w") as f:
        json.dump({"mode": args.mode, "universe": args.universe, "start_requested": args.start,
                    "label_col": label_col, "execution": args.execution,
                    "entry_at": args.entry_at, "cost_bps": args.cost_bps,
                    "walkforward_stop": args.walkforward_stop,
                    "results": results}, f, indent=2)
    if results:
        wins = sum(r["beat_spy"] for r in results)
        total_gap_picks = sum(r["gap_picks"] for r in results)
        # Round 9 sanity print. The eligibility screen failing open is silent
        # in every other statistic, so surface it directly: if nearly every
        # pick is gap-flagged, or the median entry price collapses, the
        # market-cap/price floor is not doing its job.
        _npos = sum(len(r["picks"]) for r in results)
        _ngap = sum(r.get("gap_picks", 0) for r in results)
        _px = [v for r in results for v in r["pick_entry_close"].values()]
        _med = float(np.median(_px)) if _px else float("nan")
        _sub10 = (float(np.mean([p < 10 for p in _px])) if _px else float("nan"))
        print(f"  eligibility check: {_ngap}/{_npos} picks gap-flagged "
              f"({_ngap/max(_npos,1):.0%}), median entry ${_med:,.2f}, "
              f"{_sub10:.0%} under $10")
        if _npos and _ngap / _npos > 0.9:
            print("  *** WARNING: nearly every pick is gap-flagged. Gap tickers are "
                  "exempt from the market-cap/price floor, so this almost certainly "
                  "means the floor is failing open. Do not trust these results. ***")
        print(f"{args.mode} (universe={args.universe}): {len(results)} windows, {wins} beat SPY "
              f"({wins/len(results):.0%}), {total_gap_picks} total gap-ticker picks, "
              f"steps {results[0]['timepoint']} to {results[-1]['timepoint']}")
    else:
        print(f"{args.mode} (universe={args.universe}): 0 windows produced -- nothing usable to save")
    print(f"Saved -> {out_path}")


if __name__ == "__main__":
    main()
