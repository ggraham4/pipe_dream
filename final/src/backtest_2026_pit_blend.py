"""
2026-YTD HMM-gated BLEND backtest, sequential 40-trading-day windows,
PIT-inclusive universe -- and a "last 80 trading days" sub-comparison.

Extends backtest_2026_hmm_gated.py two ways, per Gabe's follow-up request:

1. **Include the PIT (point-in-time survivorship-bias-correction) data.**
   backtest_pit.py's mechanism is: today's universe UNION a timepoint's
   validated gap tickers (pit_universe.allowed_universe_for). The only
   2026-anchored PIT snapshot that exists is 2026-06-01
   (pit_universe_membership.json), with 6 raw gap tickers and only 2
   that cleared the recycled-ticker validation: FISV and MRSH. Since
   membership doesn't change day to day, that same 2026-06-01 snapshot is
   used as the stand-in for every 2026 pick date in this script (01-02,
   03-03, 04-29, 06-25, 08-21) -- there's no finer-grained PIT snapshot
   to fall back to within the year.

   IMPORTANT, discovered while wiring this up: FISV and MRSH are NOT
   genuine survivorship-bias recoveries (i.e. not bankrupt/delisted
   companies). They're the OLD ticker symbols for Fiserv and Marsh &
   McLennan -- both still very much alive, current S&P 500 members --
   and both trade today under FI and MMC. But FI and MMC are two of the
   known-missing tickers in the production universe pull
   (universe/2026-08-27-expanded-universe-methodology.md: "Two tickers
   came back missing: FI and MMC"). So including "the PIT data" here
   doesn't add back any failed companies (confirming Gabe's premise that
   2026 hasn't had much of that) -- it happens to plug a real, unrelated
   data gap: Fiserv and Marsh & McLennan were simply absent from the
   baseline universe, and are now present under their legacy ticker
   symbols. Implemented by copying FISV.csv/MRSH.csv from
   scripts/td_data_delisted/ and scripts/fundamentals_raw_delisted/ into
   the regular scripts/td_data_local/ and scripts/fundamentals_raw/
   directories before rebuilding features.parquet and features_with_
   fundamentals_beta.parquet -- mechanically equivalent to backtest_pit.
   py's allowed_universe_for() union for these two tickers at these
   dates, without needing the full features_pit.py delisting-exit-floor
   machinery (irrelevant here since neither ticker's price series ever
   actually stops).

2. **"Just the blend"** -- per Gabe's ask, the printed/returned summary
   reports ONLY the HMM-gated blend vs. SPY (baseline/augmented are still
   trained and blended under the hood, exactly as before, but aren't
   surfaced as separate columns in the output here).

3. **A "last 80 trading days" cut**, alongside the full 2026-YTD
   aggregate -- the last two resolved 40-trading-day windows
   (2026-04-29 -> 2026-06-25 and 2026-06-25 -> 2026-08-21).

Usage:
    python3 backtest_2026_pit_blend.py
Output: out/backtest_2026_pit_blend.json + printed summary table.
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
PIT_GAP_TICKERS_2026 = ["FISV", "MRSH"]  # validated gap tickers, 2026-06-01 snapshot


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
    cols = sorted(set(["ticker", "date", LABEL_COL] + feature_cols))
    print(f"  loading {parquet_path.name} ({len(cols)} cols, PIT-inclusive universe)...")
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
        n_pit_gap_picks = int(picks["ticker"].isin(PIT_GAP_TICKERS_2026).sum()) if len(picks) else 0
        phase_results[str(tp.date())] = {
            "pick_date": str(tp.date()),
            "exit_date": str(exit_date.date()) if exit_date is not None else None,
            "resolved": bool(resolved),
            "n_candidates_scored": len(test_rows),
            "picks_df": picks,
            "picks": picks["ticker"].tolist() if len(picks) else [],
            "n_pit_gap_picks": n_pit_gap_picks,
            "return_pct": round(ret * 100, 2) if ret is not None else None,
        }
        flag = f"  <-- includes {n_pit_gap_picks} PIT gap ticker(s)" if n_pit_gap_picks else ""
        print(f"    {tp.date()}: n_scored={len(test_rows)}  return={ret*100 if ret is not None else float('nan'):+.2f}%{flag}")

    del feat
    gc.collect()
    return phase_results


def run():
    print("Phase 1/2: baseline (price-only), PIT-inclusive universe...")
    baseline_by_tp = run_phase(OUT_DIR / "features.parquet", FEATURE_COLS, FORWARD_WINDOW)

    print("Phase 2/2: augmented (price + fundamentals, no_staleness), PIT-inclusive universe...")
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

        blend_ret, alloc = None, []
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
                ending = sum(10000 * (wt / total_weight_realized) * (1 + float(realized_pool[t]))
                             for t, wt in alloc_map.items() if t in realized_pool.index)
                blend_ret = float(ending) / 10000 - 1
            alloc = [{"ticker": t, "allocation_pct": round(wt * 100, 2)} for t, wt in
                     sorted(alloc_map.items(), key=lambda kv: -kv[1])]

        spy_row = spy[spy["date"] == tp]
        spy_return = float(spy_row["spy_fwd_return"].iloc[0]) if not spy_row.empty and spy_row["spy_fwd_return"].notna().any() else None

        results.append({
            "pick_date": pick_date_str,
            "exit_date": b["exit_date"],
            "resolved": b["resolved"],
            "hmm_weight_on_augmented": round(float(w), 4),
            "blend_allocation": alloc,
            "blend_return_pct": round(blend_ret * 100, 2) if blend_ret is not None else None,
            "spy_return_pct": round(spy_return * 100, 2) if spy_return is not None else None,
            "n_pit_gap_picks_baseline": b["n_pit_gap_picks"],
            "n_pit_gap_picks_augmented": a["n_pit_gap_picks"] if a is not None else 0,
        })

    return results


def summarize(results):
    resolved = [r for r in results if r["resolved"]]
    resolved_sorted = sorted(resolved, key=lambda r: r["pick_date"])
    last_80 = resolved_sorted[-2:] if len(resolved_sorted) >= 2 else resolved_sorted

    def agg(rows, label):
        blend_vals = [r["blend_return_pct"] for r in rows if r["blend_return_pct"] is not None]
        spy_vals = [r["spy_return_pct"] for r in rows if r["spy_return_pct"] is not None]
        wins = sum(1 for r in rows if r["blend_return_pct"] is not None and r["spy_return_pct"] is not None
                   and r["blend_return_pct"] > r["spy_return_pct"])
        n = len(rows)
        blend_end = sum(10000 * (1 + v / 100) for v in blend_vals)
        spy_end = sum(10000 * (1 + v / 100) for v in spy_vals)
        print(f"\n=== {label}: {n} window(s) ===")
        for r in rows:
            print(f"  {r['pick_date']} -> {r['exit_date']}: blend {r['blend_return_pct']:+.2f}%  "
                  f"SPY {r['spy_return_pct']:+.2f}%  (HMM w(aug)={r['hmm_weight_on_augmented']})")
        print(f"  HMM-gated blend: avg {np.mean(blend_vals):+.2f}%/trial, beat SPY {wins}/{n}, "
              f"${n*10000:,} -> ${blend_end:,.2f}")
        print(f"  SPY:              avg {np.mean(spy_vals):+.2f}%/trial, "
              f"${n*10000:,} -> ${spy_end:,.2f}")

    agg(resolved_sorted, "Full 2026 YTD (PIT-inclusive universe, blend only)")
    agg(last_80, "Last 80 trading days only (most recent 2 windows)")

    unresolved = [r for r in results if not r["resolved"]]
    if unresolved:
        print(f"\n{len(unresolved)} window(s) still open (not yet 40 trading days old):")
        for r in unresolved:
            print(f"  {r['pick_date']}: HMM w(aug)={r['hmm_weight_on_augmented']}, "
                  f"allocation={r['blend_allocation']}")

    n_pit = sum(r["n_pit_gap_picks_baseline"] + r["n_pit_gap_picks_augmented"] for r in results)
    print(f"\nTotal PIT gap-ticker (FISV/MRSH) picks across both sides, all windows: {n_pit}")


if __name__ == "__main__":
    results = run()
    with open(OUT_DIR / "backtest_2026_pit_blend.json", "w") as f:
        json.dump(results, f, indent=2)
    summarize(results)
    print(f"\nFull detail -> {OUT_DIR / 'backtest_2026_pit_blend.json'}")
