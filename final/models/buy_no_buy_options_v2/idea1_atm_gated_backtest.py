"""
Idea 1 (Gabe's framing): use the existing buy/no-buy stock classifier as a
pure gate for whether to buy a call -- for each of the top-5 buy/no-buy
picks at a timepoint, buy the ATM call (strike nearest the current day's
underlying price), hold to expiration. No options-specific regression
model at all -- this is the simplest of the three ideas, a baseline for
whether the options-premium model machinery is earning its complexity.

Methodology mirrors models/options-premium-model-design.md's production
calls backtest as closely as possible for comparability: same 6 annual
timepoints (mid-January 2021-2026), $2,000/pick equal-weight ($10,000
total for 5 picks), held to the contract's own expiration, benchmarked
against SPY buy-and-hold over the same matched window and a naive
"average return across the whole scored universe" baseline.
"""
from pathlib import Path
import pandas as pd
import numpy as np
import json

OUT_DIR = Path(__file__).resolve().parent
REPO_FINAL = Path(__file__).resolve().parents[2]

TIMEPOINTS = [pd.Timestamp(f"{y}-01-15") for y in range(2021, 2027)]
COHORT_WINDOW_DAYS = 15
TOP_N = 5
CAPITAL_PER_PICK = 2000

calls = pd.read_parquet(OUT_DIR / "options_calls_training_expanded_v2.parquet")
calls["entry_date"] = pd.to_datetime(calls["entry_date"])
calls["expiration_date"] = pd.to_datetime(calls["expiration_date"])

scores = pd.read_parquet(OUT_DIR / "buy_no_buy_walkforward_scores.parquet")
scores["entry_date"] = pd.to_datetime(scores["entry_date"])

spy = pd.read_csv(REPO_FINAL / "scripts" / "td_data_local" / "SPY.csv", parse_dates=["date"]).sort_values("date")

results = []
for T in TIMEPOINTS:
    # nearest scored entry_date to T within the cohort window
    cand_entry_dates = scores["entry_date"].drop_duplicates()
    cand_entry_dates = cand_entry_dates[(cand_entry_dates >= T - pd.Timedelta(days=COHORT_WINDOW_DAYS)) &
                                         (cand_entry_dates <= T + pd.Timedelta(days=COHORT_WINDOW_DAYS))]
    if cand_entry_dates.empty:
        print(f"skip {T.date()}: no scored entry date nearby", flush=True)
        continue
    entry_date = cand_entry_dates.iloc[(cand_entry_dates - T).abs().argsort().iloc[0]]

    cohort_scores = scores[scores["entry_date"] == entry_date].sort_values("buy_no_buy_proba", ascending=False)
    cohort_calls = calls[calls["entry_date"] == entry_date].copy()
    if cohort_calls.empty:
        print(f"skip {T.date()}: no option contracts at entry_date {entry_date.date()}", flush=True)
        continue

    # universe avg: naive "buy a random call from the whole cohort" baseline
    universe_avg_return = cohort_calls["pct_return_on_premium"].mean()

    picks = []
    for _, row in cohort_scores.iterrows():
        if len(picks) >= TOP_N:
            break
        ticker = row["act_symbol"]
        ticker_calls = cohort_calls[cohort_calls["act_symbol"] == ticker]
        if ticker_calls.empty:
            continue
        # ATM strike: nearest moneyness to 1.0 (strike closest to today's price)
        atm_row = ticker_calls.iloc[(ticker_calls["moneyness_strike_over_spot"] - 1.0).abs().argsort().iloc[0]]
        picks.append({
            "ticker": ticker, "buy_no_buy_proba": row["buy_no_buy_proba"],
            "strike": atm_row["strike"], "moneyness": atm_row["moneyness_strike_over_spot"],
            "entry_premium": atm_row["entry_premium"], "payoff_at_expiry": atm_row["payoff_at_expiry"],
            "pct_return_on_premium": atm_row["pct_return_on_premium"],
            "expiration_date": atm_row["expiration_date"],
        })

    if not picks:
        print(f"skip {T.date()}: no buy/no-buy picks had a matching call contract", flush=True)
        continue

    n_picks = len(picks)
    per_pick_capital = 10000 / n_picks
    ending_value = sum(per_pick_capital * (1 + p["pct_return_on_premium"]) for p in picks)
    model_return = ending_value / 10000 - 1

    expiry = picks[0]["expiration_date"]
    spy_entry = spy[spy["date"] <= entry_date].iloc[-1]
    spy_exit_candidates = spy[spy["date"] <= expiry]
    if spy_exit_candidates.empty:
        spy_return = None
    else:
        spy_exit = spy_exit_candidates.iloc[-1]
        spy_return = spy_exit["close"] / spy_entry["close"] - 1

    results.append({
        "timepoint": str(T.date()), "entry_date": str(entry_date.date()),
        "expiration_date": str(expiry.date()) if hasattr(expiry, "date") else str(expiry),
        "n_picks": n_picks,
        "picks": [p["ticker"] for p in picks],
        "pick_detail": [{"ticker": p["ticker"], "proba": round(float(p["buy_no_buy_proba"]), 3),
                          "moneyness": round(float(p["moneyness"]), 3),
                          "pct_return_on_premium": round(float(p["pct_return_on_premium"]) * 100, 2)} for p in picks],
        "model_return_pct": round(model_return * 100, 2),
        "spy_return_pct": round(float(spy_return) * 100, 2) if spy_return is not None else None,
        "universe_avg_return_pct": round(float(universe_avg_return) * 100, 2),
        "beat_spy": bool(spy_return is not None and model_return > spy_return),
    })

print(f"\n{'timepoint':<12}{'model %':>10}{'SPY %':>10}{'univ avg %':>12}{'beat SPY':>10}")
for r in results:
    print(f"{r['timepoint']:<12}{r['model_return_pct']:>10.2f}{r['spy_return_pct']:>10.2f}"
          f"{r['universe_avg_return_pct']:>12.2f}{str(r['beat_spy']):>10}")

n = len(results)
wins = sum(r["beat_spy"] for r in results)
avg_model = np.mean([r["model_return_pct"] for r in results])
avg_spy = np.mean([r["spy_return_pct"] for r in results])
std_model = np.std([r["model_return_pct"] for r in results])
print(f"\nWin rate vs SPY: {wins}/{n}")
print(f"Avg model return/trial: {avg_model:.2f}% (std {std_model:.2f}%)")
print(f"Avg SPY return/trial: {avg_spy:.2f}%")
ending = 10000
for r in results:
    ending = ending  # trials are independent $10k, not compounded -- matches production convention
total_from_10k_trials = sum(10000 * (1 + r["model_return_pct"] / 100) for r in results)
total_spy = sum(10000 * (1 + r["spy_return_pct"] / 100) for r in results)
print(f"${10000*n} across {n} independent $10k trials -> ${total_from_10k_trials:,.2f} (model) vs ${total_spy:,.2f} (SPY)")

def _clean(o):
    import numpy as np
    if isinstance(o, dict):
        return {k: _clean(v) for k, v in o.items()}
    if isinstance(o, list):
        return [_clean(v) for v in o]
    if isinstance(o, (np.floating, np.float32, np.float64)):
        return float(o)
    if isinstance(o, (np.integer,)):
        return int(o)
    if isinstance(o, (np.bool_,)):
        return bool(o)
    return o

with open(OUT_DIR / "idea1_results.json", "w") as f:
    json.dump(_clean({"results": results, "summary": {"win_rate": f"{wins}/{n}", "avg_model_pct": avg_model,
                                                 "std_model_pct": std_model, "avg_spy_pct": avg_spy}}), f, indent=2)
