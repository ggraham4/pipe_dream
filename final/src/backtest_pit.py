"""
Point-in-time (survivorship-bias-corrected) 8-timepoint backtest: baseline
(price-only), augmented (price + fundamentals, no_staleness), and the HMM
regime-gate blend of the two -- same 8 timepoints and $10k-per-trial
methodology as src/backtest.py and models/dollar-simulation-results.md, so
the results are directly comparable to the numbers Gabe already has. The
ONLY thing that changes here is the candidate pool each model is allowed
to pick from at each timepoint: instead of today's 1,620-ticker universe
applied retroactively (the survivorship-bias-affected version), each
timepoint scores today's universe UNION that timepoint's real point-in-
time S&P 500 gap tickers (pit_universe.py) -- so a model CAN pick a stock
that's about to go bankrupt or get delisted, exactly as it could have in
real life. See features_pit.py's docstring for the full background,
including the delisting-exit-floor label fix this depends on (without it,
a picked stock that goes bankrupt mid-holding-period would be silently
dropped from the $ simulation instead of counting as a loss).

Training data is NOT point-in-time restricted -- it uses the full merged
panel (current + gap tickers) up to the embargo cutoff, same as before.
Only the CANDIDATE SET AT EACH DECISION DATE is restricted. This is
deliberate: training on more historical regimes (including real failures)
is a benefit, not a bias risk; the bias specifically comes from which
stocks are ELIGIBLE TO BE PICKED.

Prerequisites (run in this order):
    1. local_data_pull_delisted.py          (on your own machine)
    2. local_fundamentals_pull_delisted.py   (on your own machine)
    3. features_pit.py
    4. fundamentals_features_pit.py
    5. this script

Usage:
    python3 backtest_pit.py

Output: out/backtest_pit_results.json (full detail) and a printed summary
table matching the format of models/dollar-simulation-results.md.
"""
import json

import numpy as np
import pandas as pd
from xgboost import XGBClassifier

from features import FEATURE_COLS, FORWARD_WINDOW, LABEL_COL, DATA_DIR, OUT_DIR
from fundamentals_features_beta import FUNDAMENTAL_FEATURE_COLS
from regime_signals_beta import build_spy_returns, hmm_weight
from pit_universe import allowed_universe_for, ALL_GAP_TICKERS, membership_summary

TOP_N = 5
CUTOFF_PERCENTILE = 75
NO_STALE_COLS = [c for c in FUNDAMENTAL_FEATURE_COLS if c != "fundamentals_age_days"]
AUGMENTED_FEATURE_COLS = FEATURE_COLS + NO_STALE_COLS

TIMEPOINTS = [
    "2013-01-02", "2015-01-02", "2017-01-03", "2019-01-02",
    "2021-01-04", "2023-01-03", "2025-01-02", "2026-06-01",
]


def nearest_trading_date(target, available_dates):
    target = pd.Timestamp(target)
    candidates = available_dates[available_dates <= target]
    return candidates.max() if len(candidates) else None


def train_and_pick(train, test_rows_allowed, feature_cols, cutoff_val):
    y_train = (train[LABEL_COL] > cutoff_val).astype(int)
    model = XGBClassifier(n_estimators=100, max_depth=3, learning_rate=0.1,
                           eval_metric="logloss", verbosity=0)
    model.fit(train[feature_cols], y_train)
    scored = test_rows_allowed.copy()
    scored["buy_proba"] = model.predict_proba(scored[feature_cols])[:, 1]
    return scored.sort_values("buy_proba", ascending=False).head(TOP_N)


def dollar_sim(picks: pd.DataFrame):
    """Same math as backtest.py: $10k equal-weight across realized picks.
    With the delisting exit-floor fix (features_pit.py), a NaN label here
    should only ever happen for a still-live ticker whose +40-day window
    genuinely hasn't resolved yet at the most recent timepoint (2026-06-01)
    -- not from a gap ticker going bankrupt, which now has a real (if ugly)
    realized return instead of NaN."""
    realized = picks.dropna(subset=[LABEL_COL])
    n = len(realized)
    if n == 0:
        return None, None
    per_stock = 10000 / n
    ending_value = float((per_stock * (1 + realized[LABEL_COL])).sum())
    return ending_value, ending_value / 10000 - 1


def load_gap_validation():
    """Load features_pit.py's validate_gap_coverage() output -- per-timepoint
    sets of gap tickers whose pulled data actually cleared the trailing-
    history check (i.e. is very likely the real historical company, not a
    recycled ticker symbol currently trading under the old name -- see
    features_pit.py's validate_gap_coverage() docstring). Without this,
    allowed_universe_for() would trust every gap ticker in
    pit_universe_membership.json, including ones later shown to be a
    different, unrelated company (APC/AVB/BBBY/CSRA/EA and others,
    confirmed on Gabe's own local pull run 2026-08-28)."""
    path = OUT_DIR / "pit_gap_ticker_validation.json"
    if not path.exists():
        print("WARNING: pit_gap_ticker_validation.json not found -- run features_pit.py "
              "(with its validate_gap_coverage() step) first. Falling back to trusting "
              "every gap ticker unvalidated -- this risks recycled-ticker contamination.")
        return None
    with open(path) as f:
        validation = json.load(f)
    valid_by_tp = validation.get("valid_by_timepoint", {})
    n_quarantined = len(validation.get("quarantined", []))
    print(f"Loaded gap-ticker validation: {sum(len(v) for v in valid_by_tp.values())} "
          f"(ticker, timepoint) pairs cleared, {n_quarantined} tickers flagged as "
          f"quarantined for at least one timepoint (recycled-symbol risk).")
    return valid_by_tp


def run():
    print("Loading point-in-time panels...")
    feat = pd.read_parquet(OUT_DIR / "features_pit.parquet").sort_values(["ticker", "date"]).reset_index(drop=True)
    fund_path = OUT_DIR / "features_with_fundamentals_pit.parquet"
    feat_fund = None
    if fund_path.exists():
        feat_fund = pd.read_parquet(fund_path).sort_values(["ticker", "date"]).reset_index(drop=True)
    else:
        print("WARNING: features_with_fundamentals_pit.parquet not found -- run "
              "fundamentals_features_pit.py first. Baseline-only results will still run.")

    gap_validation = load_gap_validation()
    current_universe_tickers = set(feat["ticker"].unique()) - set(ALL_GAP_TICKERS)

    spy = pd.read_csv(DATA_DIR / "SPY.csv", parse_dates=["date"]).sort_values("date").reset_index(drop=True)
    spy["spy_fwd_return"] = spy["close"].shift(-FORWARD_WINDOW) / spy["close"] - 1
    spy_rets, spy_dates = build_spy_returns()

    all_dates = feat["date"].drop_duplicates().sort_values().reset_index(drop=True)
    embargo_days = FORWARD_WINDOW

    results = []
    for tp_str in TIMEPOINTS:
        tp = nearest_trading_date(tp_str, all_dates)
        if tp is None:
            print(f"skip {tp_str}: no trading date found")
            continue
        idx = all_dates[all_dates == tp].index[0]
        if idx < embargo_days:
            print(f"skip {tp_str}: not enough history for embargo")
            continue
        train_cutoff_date = all_dates.iloc[idx - embargo_days]

        validated_gap_for_tp = gap_validation.get(tp_str) if gap_validation is not None else None
        allowed = allowed_universe_for(tp_str, current_universe_tickers,
                                        validated_gap_tickers=validated_gap_for_tp)

        # ---- baseline (price-only) ----
        train_b = feat[feat["date"] <= train_cutoff_date].dropna(subset=FEATURE_COLS + [LABEL_COL])
        cutoff_b = np.percentile(train_b[LABEL_COL], CUTOFF_PERCENTILE)
        test_b = feat[(feat["date"] == tp) & (feat["ticker"].isin(allowed))].dropna(subset=FEATURE_COLS).copy()
        baseline_picks = train_and_pick(train_b, test_b, FEATURE_COLS, cutoff_b) if len(test_b) else pd.DataFrame()

        # ---- augmented (price + fundamentals, no_staleness) ----
        augmented_picks = pd.DataFrame()
        if feat_fund is not None:
            train_a = feat_fund[feat_fund["date"] <= train_cutoff_date].dropna(subset=FEATURE_COLS + [LABEL_COL])
            cutoff_a = np.percentile(train_a[LABEL_COL], CUTOFF_PERCENTILE)
            test_a = feat_fund[(feat_fund["date"] == tp) & (feat_fund["ticker"].isin(allowed))].dropna(subset=FEATURE_COLS).copy()
            if len(test_a):
                augmented_picks = train_and_pick(train_a, test_a, AUGMENTED_FEATURE_COLS, cutoff_a)

        # ---- HMM gate weight (SPY-only, no universe/bias issue) ----
        w = hmm_weight(spy_rets, spy_dates, tp)
        if w is None:
            w = 0.5

        # ---- $ sims: baseline alone, augmented alone, HMM-gated blend ----
        base_end, base_ret = dollar_sim(baseline_picks) if len(baseline_picks) else (None, None)
        aug_end, aug_ret = dollar_sim(augmented_picks) if len(augmented_picks) else (None, None)

        blend_end, blend_ret, alloc = None, None, []
        if len(baseline_picks) and len(augmented_picks):
            alloc_map = {}
            detail = pd.concat([baseline_picks, augmented_picks]).drop_duplicates(subset="ticker").set_index("ticker")
            for _, row in augmented_picks.iterrows():
                alloc_map[row["ticker"]] = alloc_map.get(row["ticker"], 0.0) + w / TOP_N
            for _, row in baseline_picks.iterrows():
                alloc_map[row["ticker"]] = alloc_map.get(row["ticker"], 0.0) + (1 - w) / TOP_N
            realized_pool = pd.concat([baseline_picks[["ticker", LABEL_COL]],
                                        augmented_picks[["ticker", LABEL_COL]]]).drop_duplicates(subset="ticker")
            realized_pool = realized_pool.dropna(subset=[LABEL_COL]).set_index("ticker")[LABEL_COL]
            total_weight_realized = sum(wt for t, wt in alloc_map.items() if t in realized_pool.index)
            if total_weight_realized > 0:
                ending = sum(10000 * (wt / total_weight_realized) * (1 + realized_pool[t])
                             for t, wt in alloc_map.items() if t in realized_pool.index)
                blend_end = float(ending)
                blend_ret = blend_end / 10000 - 1
            alloc = [{"ticker": t, "allocation_pct": round(wt * 100, 2)} for t, wt in
                     sorted(alloc_map.items(), key=lambda kv: -kv[1])]

        spy_row = spy[spy["date"] == tp]
        spy_return = float(spy_row["spy_fwd_return"].iloc[0]) if not spy_row.empty and spy_row["spy_fwd_return"].notna().any() else None

        n_gap_in_baseline = int(baseline_picks["ticker"].isin(ALL_GAP_TICKERS).sum()) if len(baseline_picks) else 0
        n_gap_in_augmented = int(augmented_picks["ticker"].isin(ALL_GAP_TICKERS).sum()) if len(augmented_picks) else 0

        results.append({
            "timepoint": str(tp.date()),
            "pit_snapshot_date": membership_summary().get(tp_str, {}).get("snapshot_date_used"),
            "n_candidates_scored": len(test_b),
            "n_gap_tickers_eligible": len(allowed) - len(current_universe_tickers),
            "baseline_picks": baseline_picks["ticker"].tolist() if len(baseline_picks) else [],
            "baseline_gap_picks": int(n_gap_in_baseline),
            "baseline_return_pct": round(base_ret * 100, 2) if base_ret is not None else None,
            "augmented_picks": augmented_picks["ticker"].tolist() if len(augmented_picks) else [],
            "augmented_gap_picks": int(n_gap_in_augmented),
            "augmented_return_pct": round(aug_ret * 100, 2) if aug_ret is not None else None,
            "hmm_weight_on_augmented": round(float(w), 4),
            "blend_allocation": alloc,
            "blend_return_pct": round(blend_ret * 100, 2) if blend_ret is not None else None,
            "spy_return_pct": round(spy_return * 100, 2) if spy_return is not None else None,
        })

        print(f"{tp.date()}  baseline={base_ret*100 if base_ret is not None else float('nan'):+.2f}% "
              f"({n_gap_in_baseline} gap-ticker picks)  "
              f"augmented={aug_ret*100 if aug_ret is not None else float('nan'):+.2f}% "
              f"({n_gap_in_augmented} gap-ticker picks)  "
              f"blend(w={w:.3f})={blend_ret*100 if blend_ret is not None else float('nan'):+.2f}%  "
              f"SPY={spy_return*100 if spy_return is not None else float('nan'):+.2f}%")

    return results


def summarize(results):
    def agg(key):
        vals = [r[key] for r in results if r[key] is not None]
        return vals

    print("\n=== Aggregate ($80,000 = 8 x $10,000 independent trials) ===")
    for label, key in [("Baseline (price-only)", "baseline_return_pct"),
                        ("Augmented (fundamentals)", "augmented_return_pct"),
                        ("HMM-gated blend", "blend_return_pct"),
                        ("SPY", "spy_return_pct")]:
        vals = agg(key)
        if not vals:
            print(f"{label}: no data")
            continue
        ending = sum(10000 * (1 + v / 100) for v in vals)
        print(f"{label}: {len(vals)}/8 timepoints, avg {np.mean(vals):+.2f}%/trial, "
              f"${len(vals)*10000:,} -> ${ending:,.2f}")

    total_gap_picks = sum(r["baseline_gap_picks"] + r["augmented_gap_picks"] for r in results)
    print(f"\nTotal gap-ticker (survivorship-bias-restored) picks across both models, all "
          f"timepoints: {total_gap_picks}")


if __name__ == "__main__":
    results = run()
    with open(OUT_DIR / "backtest_pit_results.json", "w") as f:
        json.dump(results, f, indent=2)
    summarize(results)
    print(f"\nFull detail -> {OUT_DIR / 'backtest_pit_results.json'}")
