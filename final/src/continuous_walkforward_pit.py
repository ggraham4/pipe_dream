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

import numpy as np
import pandas as pd
from xgboost import XGBClassifier

from features import FEATURE_COLS, FORWARD_WINDOW, LABEL_COL, DATA_DIR, OUT_DIR
from fundamentals_features_beta import FUNDAMENTAL_FEATURE_COLS
from features_pit import MIN_TRAILING_DAYS
from pit_universe_continuous import gap_tickers_asof, members_asof

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
    return present.groupby("ticker")["date"].min()


def allowed_universe_at(tp, current_universe_tickers, gap_earliest, universe="expanded"):
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
                     current_universe_tickers, gap_earliest, universe="expanded"):
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

    results = []
    for tp in step_dates:
        idx = all_dates[all_dates == tp].index[0]
        if idx < embargo_days:
            continue
        train_cutoff_date = all_dates.iloc[idx - embargo_days]
        train = feat[feat["date"] <= train_cutoff_date]
        if len(train) < 300:
            print(f"[{tag}] skip {tp.date()}: only {len(train)} training rows")
            continue

        allowed = allowed_universe_at(tp, current_universe_tickers, gap_earliest, universe)

        cutoff_val = np.percentile(train[LABEL_COL], CUTOFF_PERCENTILE)
        y_train = (train[LABEL_COL] > cutoff_val).astype(int)
        model = XGBClassifier(n_estimators=100, max_depth=3, learning_rate=0.1,
                               eval_metric="logloss", verbosity=0)
        model.fit(train[feature_cols], y_train)

        test_rows = feat[(feat["date"] == tp) & (feat["ticker"].isin(allowed))].copy()
        if test_rows.empty:
            del model, train
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
        is_gap_candidate = test_rows["ticker"].isin(gap_earliest.index)
        meets_price = test_rows["close"] > MIN_PRICE
        meets_cap = test_rows["market_cap"] >= MIN_MARKET_CAP
        test_rows = test_rows[is_gap_candidate | (meets_price & meets_cap)]
        if test_rows.empty:
            print(f"[{tag}] skip {tp.date()}: no candidates cleared the point-in-time "
                  f"mid-cap+ eligibility floor")
            del model, train
            gc.collect()
            continue

        test_rows["buy_proba"] = model.predict_proba(test_rows[feature_cols])[:, 1]

        top_picks = test_rows.sort_values("buy_proba", ascending=False).head(TOP_N)
        picks_realized = top_picks.dropna(subset=[LABEL_COL])
        if picks_realized.empty:
            print(f"[{tag}] skip {tp.date()}: no picks with realized forward return")
            del model, test_rows, train
            gc.collect()
            continue

        per_stock_weight = 1.0 / len(picks_realized)
        portfolio_return = (per_stock_weight * (1 + picks_realized[LABEL_COL])).sum() - 1

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
            "spy_return_pct": round(float(spy_return) * 100, 2) if spy_return is not None else None,
            "beat_spy": bool(spy_return is not None and portfolio_return > spy_return),
            "feature_importances": {c: round(float(imp), 5)
                                     for c, imp in zip(feature_cols, model.feature_importances_)},
        })

        del model, test_rows, train
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
            per_ticker_returns[ticker] = -stop_pct
            stop_triggered_on[ticker] = str(hit.iloc[0]["date"].date())
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


def _load_lean_low_close_panel():
    """The [ticker, date, low, close] panel every stop-loss simulation needs,
    grouped per ticker -- factored out (Round 8) so the sweep mode loads it
    ONCE instead of once per stop percentage tested."""
    feat = pd.read_parquet(OUT_DIR / "features_pit.parquet")[["ticker", "date", "low", "close"]]
    feat = feat.sort_values(["ticker", "date"]).reset_index(drop=True)
    price_by_ticker = {t: g[["date", "low", "close"]].reset_index(drop=True)
                        for t, g in feat.groupby("ticker", sort=False)}
    del feat
    gc.collect()
    return price_by_ticker


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
    price_by_ticker = _load_lean_low_close_panel()

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
    price_by_ticker = _load_lean_low_close_panel()

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
    parser.add_argument("--universe", choices=["expanded", "sp500"], default="expanded",
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
    panel_path = OUT_DIR / ("features_with_fundamentals_pit.parquet" if args.mode == "augmented"
                             else "features_pit.parquet")
    if not panel_path.exists():
        raise FileNotFoundError(
            f"{panel_path} not found -- run features_pit.py"
            + (" and fundamentals_features_pit.py" if args.mode == "augmented" else "")
            + " first."
        )
    feat = pd.read_parquet(panel_path)
    feat = feat.sort_values(["ticker", "date"]).reset_index(drop=True)
    cols = NO_STALE_COLS if args.mode == "augmented" else []
    keep_cols = ["ticker", "date", "close"] + FEATURE_COLS + cols + [LABEL_COL]
    feat = feat[keep_cols]
    for c in FEATURE_COLS + cols + [LABEL_COL]:
        feat[c] = feat[c].astype("float32")
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
    current_universe_tickers = set(feat["ticker"].unique()) - gap_tickers
    gap_earliest = build_gap_validity(feat, gap_tickers)

    feat_restricted = feat.dropna(subset=FEATURE_COLS + [LABEL_COL]).copy()
    del feat
    gc.collect()
    all_dates = feat_restricted["date"].drop_duplicates().sort_values().reset_index(drop=True)
    print(f"  {len(feat_restricted)} rows, {feat_restricted['ticker'].nunique()} tickers "
          f"({len(current_universe_tickers)} current-universe, {len(gap_tickers)} gap tickers "
          f"found on disk, {len(gap_earliest)} of those present in this feature panel), "
          f"dates {all_dates.min().date()} to {all_dates.max().date()}")
    print(f"  Point-in-time mid-cap+ eligibility floor active for current-universe candidates: "
          f"market_cap >= ${MIN_MARKET_CAP:,.0f} and close > ${MIN_PRICE:.0f} ON THE PICK DATE "
          f"(gap tickers exempt, see module docstring Round 7)")

    feature_cols = AUGMENTED_FEATURE_COLS if args.mode == "augmented" else FEATURE_COLS
    results = run_walkforward(feat_restricted, all_dates, feature_cols, args.mode,
                               args.start, current_universe_tickers, gap_earliest, args.universe)

    out_path = OUT_DIR / f"continuous_walkforward_pit_{args.mode}{suffix}.json"
    with open(out_path, "w") as f:
        json.dump({"mode": args.mode, "universe": args.universe, "start_requested": args.start,
                    "results": results}, f, indent=2)
    if results:
        wins = sum(r["beat_spy"] for r in results)
        total_gap_picks = sum(r["gap_picks"] for r in results)
        print(f"{args.mode} (universe={args.universe}): {len(results)} windows, {wins} beat SPY "
              f"({wins/len(results):.0%}), {total_gap_picks} total gap-ticker picks, "
              f"steps {results[0]['timepoint']} to {results[-1]['timepoint']}")
    else:
        print(f"{args.mode} (universe={args.universe}): 0 windows produced -- nothing usable to save")
    print(f"Saved -> {out_path}")


if __name__ == "__main__":
    main()
