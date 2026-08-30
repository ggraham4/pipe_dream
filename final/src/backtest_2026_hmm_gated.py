"""
2026-YTD HMM regime-gated backtest, sequential 40-trading-day windows.

Runs the HMM-gated blend model (baseline price-only + augmented
price+fundamentals, blended by the causal 2-state Gaussian HMM regime
weight from regime_signals_beta.py -- same methodology as backtest_pit.py
and current_signal_gated.py / validation #6 in models/fundamentals-beta-
results.md) over SEQUENTIAL, NON-OVERLAPPING 40-trading-day windows
starting from the first trading day of 2026, instead of the fixed,
spaced-out Jan-anchored historical timepoints used elsewhere in this repo.

Why not the point-in-time (PIT) survivorship-bias-corrected universe from
backtest_pit.py: that correction exists because the production universe
(today's ~1,620 tickers) was being applied retroactively across 2013-2026,
silently excluding companies that failed along the way. Within 2026 alone
that risk is minimal -- almost nothing in this ~1,620-ticker mid-cap+
universe has gone bankrupt or been delisted in the first 8 months of 2026,
so the plain (non-PIT) feature panels (features.parquet / features_with_
fundamentals_beta.parquet -- same panels backtest.py and current_signal_
gated.py use) are a reasonable stand-in for what was actually investable
at each pick date this year. This is a simplifying assumption, not a
proven absence of bias.

Memory note: this ran OOM-killed (exit 137) on the first pass when both
~6.4M-row/20-34-col panels were loaded whole (with a redundant global
sort_values) at once on a ~8GB box. Fixed by: reading only the columns
each phase needs (pyarrow column pushdown via pd.read_parquet(columns=...)),
dropping the ticker/date global sort (never needed -- filtering by boolean
mask on date doesn't require sorted order), downcasting feature/label
columns to float32, and processing baseline and augmented as two fully
sequential phases (the fundamentals panel is loaded only after the price-
only panel has been scored and freed), so only one ~6.4M-row panel is
resident at a time.

Usage:
    python3 backtest_2026_hmm_gated.py
Output: out/backtest_2026_hmm_gated.json + printed summary table.
"""
import gc
import json
import numpy as np
import pandas as pd
from xgboost import XGBClassifier

from features import FEATURE_COLS, FORWARD_WINDOW, LABEL_COL, DATA_DIR, OUT_DIR
from fundamentals_features_beta import FUNDAMENTAL_FEATURE_COLS
from regime_signals_beta import build_spy_returns, hmm_weight

TOP_N = 5
CUTOFF_PERCENTILE = 75
START_DATE = "2026-01-01"
NO_STALE_COLS = [c for c in FUNDAMENTAL_FEATURE_COLS if c != "fundamentals_age_days"]
AUGMENTED_FEATURE_COLS = FEATURE_COLS + NO_STALE_COLS


def nearest_trading_date(target, available_dates):
    target = pd.Timestamp(target)
    candidates = available_dates[available_dates >= target]
    return candidates.min() if len(candidates) else None


def compute_pick_indices(all_dates):
    start = nearest_trading_date(START_DATE, all_dates)
    start_idx = all_dates[all_dates == start].index[0]
    last_idx = len(all_dates) - 1
    return list(range(start_idx, last_idx + 1, FORWARD_WINDOW)), last_idx


def train_and_pick(train, test_rows, feature_cols, cutoff_val):
    y_train = (train[LABEL_COL] > cutoff_val).astype(int)
    model = XGBClassifier(n_estimators=100, max_depth=3, learning_rate=0.1,
                           eval_metric="logloss", verbosity=0, n_jobs=2)
    model.fit(train[feature_cols], y_train)
    scored = test_rows.copy()
    scored["buy_proba"] = model.predict_proba(scored[feature_cols])[:, 1]
    del model
    return scored.sort_values("buy_proba", ascending=False).head(TOP_N)


def dollar_sim(picks):
    realized = picks.dropna(subset=[LABEL_COL])
    n = len(realized)
    if n == 0:
        return None, None
    per_stock = 10000 / n
    ending = float((per_stock * (1 + realized[LABEL_COL])).sum())
    return ending, ending / 10000 - 1


def run_phase(parquet_path, feature_cols, embargo_days):
    """Loads ONE panel (only the columns this phase needs, float32), runs
    every pick-date timepoint's train+pick against it, returns a dict of
    per-timepoint results, then the panel is freed before returning."""
    cols = sorted(set(["ticker", "date", LABEL_COL] + feature_cols))
    print(f"  loading {parquet_path.name} ({len(cols)} cols)...")
    feat = pd.read_parquet(parquet_path, columns=cols)
    float_cols = [c for c in feature_cols + [LABEL_COL] if feat[c].dtype == "float64"]
    feat[float_cols] = feat[float_cols].astype("float32")

    all_dates = feat["date"].drop_duplicates().sort_values().reset_index(drop=True)
    pick_indices, last_idx = compute_pick_indices(all_dates)

    phase_results = {}
    for pick_idx in pick_indices:
        tp = all_dates.iloc[pick_idx]
        if pick_idx < embargo_days:
            continue
        train_cutoff_date = all_dates.iloc[pick_idx - embargo_days]

        train = feat[feat["date"] <= train_cutoff_date].dropna(subset=feature_cols + [LABEL_COL])
        cutoff_val = np.percentile(train[LABEL_COL], CUTOFF_PERCENTILE)
        test_rows = feat[feat["date"] == tp].dropna(subset=feature_cols).copy()
        picks = train_and_pick(train, test_rows, feature_cols, cutoff_val) if len(test_rows) else pd.DataFrame()
        del train
        gc.collect()

        resolves_idx = pick_idx + FORWARD_WINDOW
        resolved = resolves_idx <= last_idx
        exit_date = all_dates.iloc[resolves_idx] if resolved else None

        end_val, ret = dollar_sim(picks) if len(picks) else (None, None)
        phase_results[str(tp.date())] = {
            "pick_date": str(tp.date()),
            "exit_date": str(exit_date.date()) if exit_date is not None else None,
            "resolved": bool(resolved),
            "n_candidates_scored": len(test_rows),
            "picks_df": picks,  # kept in memory (tiny) for the blend step
            "return_pct": round(ret * 100, 2) if ret is not None else None,
        }
        print(f"    {tp.date()}: n_scored={len(test_rows)}  return={ret*100 if ret is not None else float('nan'):+.2f}%")

    del feat
    gc.collect()
    return phase_results


def run():
    print("Phase 1/2: baseline (price-only)...")
    baseline_by_tp = run_phase(OUT_DIR / "features.parquet", FEATURE_COLS, FORWARD_WINDOW)

    print("Phase 2/2: augmented (price + fundamentals, no_staleness)...")
    augmented_by_tp = run_phase(OUT_DIR / "features_with_fundamentals_beta.parquet",
                                 AUGMENTED_FEATURE_COLS, FORWARD_WINDOW)

    print("Computing HMM regime-gate weights (SPY-only, causal)...")
    spy = pd.read_csv(DATA_DIR / "SPY.csv", parse_dates=["date"]).sort_values("date").reset_index(drop=True)
    spy["spy_fwd_return"] = spy["close"].shift(-FORWARD_WINDOW) / spy["close"] - 1
    spy_rets, spy_dates = build_spy_returns()

    results = []
    for pick_date_str in sorted(baseline_by_tp.keys()):
        b = baseline_by_tp[pick_date_str]
        a = augmented_by_tp.get(pick_date_str)
        tp = pd.Timestamp(pick_date_str)

        baseline_picks = b["picks_df"]
        augmented_picks = a["picks_df"] if a is not None else pd.DataFrame()

        w = hmm_weight(spy_rets, spy_dates, tp)
        if w is None:
            w = 0.5

        blend_end, blend_ret, alloc = None, None, []
        if len(baseline_picks) and len(augmented_picks):
            alloc_map = {}
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

        results.append({
            "pick_date": pick_date_str,
            "exit_date": b["exit_date"],
            "resolved": b["resolved"],
            "n_candidates_scored": b["n_candidates_scored"],
            "baseline_picks": baseline_picks["ticker"].tolist() if len(baseline_picks) else [],
            "baseline_return_pct": b["return_pct"],
            "augmented_picks": augmented_picks["ticker"].tolist() if len(augmented_picks) else [],
            "augmented_return_pct": a["return_pct"] if a is not None else None,
            "hmm_weight_on_augmented": round(float(w), 4),
            "blend_allocation": alloc,
            "blend_return_pct": round(blend_ret * 100, 2) if blend_ret is not None else None,
            "spy_return_pct": round(spy_return * 100, 2) if spy_return is not None else None,
        })

        print(f"{tp.date()} -> {b['exit_date'] or 'unresolved'}  "
              f"baseline={b['return_pct']}%  augmented={a['return_pct'] if a else None}%  "
              f"blend(w={w:.3f})={round(blend_ret*100,2) if blend_ret is not None else None}%  "
              f"SPY={round(spy_return*100,2) if spy_return is not None else None}%")

    return results


def summarize(results):
    resolved = [r for r in results if r["resolved"]]
    print(f"\n=== Aggregate, {len(resolved)} resolved 40-trading-day windows, 2026 YTD ===")
    for label, key in [("Baseline (price-only)", "baseline_return_pct"),
                        ("Augmented (fundamentals)", "augmented_return_pct"),
                        ("HMM-gated blend", "blend_return_pct"),
                        ("SPY", "spy_return_pct")]:
        vals = [r[key] for r in resolved if r[key] is not None]
        if not vals:
            print(f"{label}: no data")
            continue
        ending = sum(10000 * (1 + v / 100) for v in vals)
        if key != "spy_return_pct":
            wins = sum(1 for r in resolved if r[key] is not None and r["spy_return_pct"] is not None
                       and r[key] > r["spy_return_pct"])
            win_str = f", beat SPY {wins}/{len(vals)}"
        else:
            win_str = ""
        print(f"{label}: {len(vals)} windows, avg {np.mean(vals):+.2f}%/trial{win_str}, "
              f"${len(vals)*10000:,} -> ${ending:,.2f}")

    unresolved = [r for r in results if not r["resolved"]]
    if unresolved:
        print(f"\n{len(unresolved)} window(s) still in progress (not yet 40 trading days old):")
        for r in unresolved:
            print(f"  {r['pick_date']}: baseline picks {r['baseline_picks']}, "
                  f"augmented picks {r['augmented_picks']}, "
                  f"hmm weight on augmented {r['hmm_weight_on_augmented']}")


if __name__ == "__main__":
    results = run()
    with open(OUT_DIR / "backtest_2026_hmm_gated.json", "w") as f:
        json.dump(results, f, indent=2)
    summarize(results)
    print(f"\nFull detail -> {OUT_DIR / 'backtest_2026_hmm_gated.json'}")
