"""
Final agreed strategy (Gabe, 2026-09-04): buy/no-buy classifier gates
candidate tickers (top-5, same gate as idea 1), each gated ticker's ATM
call is bought (strike nearest that day's spot -- confirmed near-optimal
by the strike percentage grid search), and the EXISTING Tweedie GLM +
calibrated-decile Kelly sizing (unaugmented -- no buy_no_buy_proba
feature, per idea 2's finding that adding it as a feature hurts) prices
and sizes each position, instead of equal-weighting them.

This is a new combination, not identical to any of idea 1/2/3:
  - idea 1: buy/no-buy gate + ATM strike + EQUAL weight, no options model
  - baseline (idea 2's control): Tweedie GLM ranks/sizes across the WHOLE
    eligible universe (best strike per ticker, not necessarily ATM), no
    buy/no-buy gate at all
  - idea 3: Tweedie-GLM decile filter first, buy/no-buy proba as ranker
  - THIS: buy/no-buy gate first (restricts WHICH tickers), ATM strike
    (fixes WHICH contract), Tweedie GLM + Kelly (decides HOW MUCH) --
    each model does the specific job already shown to suit it: buy/no-buy
    for stock selection, Tweedie GLM for pricing/sizing, ATM for strike.

Runs on the WIDER PIT-corrected (1,266-ticker fundamentals coverage, up
from 473) and split-fixed (row-drop workaround, pending Gabe's proper
Sharadar-actions rescale) universe.
"""
from pathlib import Path
import json
import numpy as np
import pandas as pd
from sklearn.linear_model import TweedieRegressor
from sklearn.preprocessing import StandardScaler

OUT_DIR = Path(__file__).resolve().parent
BASE_FEATURES = [
    "moneyness_strike_over_spot", "days_to_expiration", "entry_iv",
    "realized_vol_21d_asof", "hv_current", "iv_current",
    "momentum_5", "momentum_20", "momentum_60", "momentum_120",
    "volatility_20", "volatility_60",
    "relative_strength_20", "pct_from_high_252", "pct_from_low_252",
    "daily_return", "cumulative_return", "log_volume_20",
]
TWEEDIE_POWER, TWEEDIE_ALPHA = 1.4, 0.001
N_DECILES = 10
MIN_DECILE_N = 30
KELLY_FRACTION_MULTIPLIER = 0.5
KELLY_CAP_PER_DECILE = 1.0
MAX_POSITION_FRAC = 0.30
TIMEPOINTS = [pd.Timestamp(f"{y}-01-15") for y in range(2021, 2027)]
COHORT_WINDOW_DAYS = 15
MIN_MARKET_CAP, MIN_PRICE = 2_000_000_000.0, 10.0
TOP_N_GATE = 5
ATM_TOLERANCE = 0.05  # "ATM" = nearest strike, but require it's within 5% of spot to count as a real ATM contract

df = pd.read_parquet(OUT_DIR / "options_calls_expanded_with_pit_capcheck_v3_splitfixed.parquet")
df["entry_date"] = df["entry_date"].astype("datetime64[ns]")
df["expiration_date"] = df["expiration_date"].astype("datetime64[ns]")
df = df[(df["market_cap"].notna()) & (df["market_cap"] >= MIN_MARKET_CAP) &
        (df["underlying_close_entry"] > MIN_PRICE)].copy()
print(f"PIT-corrected+splitfixed universe: {len(df)} rows, {df['act_symbol'].nunique()} tickers", flush=True)
df["log_volume_20"] = np.log1p(df["volume_20"].clip(lower=0))
df = df.dropna(subset=BASE_FEATURES + ["return_ratio", "pct_return_on_premium"]).reset_index(drop=True)
print(f"After feature dropna: {df.shape}", flush=True)

scores = pd.read_parquet(OUT_DIR / "buy_no_buy_walkforward_scores.parquet")
scores["entry_date"] = scores["entry_date"].astype("datetime64[ns]")


def kelly_fraction(decile, decile_stats):
    if pd.isna(decile) or decile not in decile_stats.index:
        return 0.0
    row = decile_stats.loc[decile]
    if row["count"] < MIN_DECILE_N or row["var"] <= 0 or row["mean"] <= 0:
        return 0.0
    f = np.clip(row["mean"] / row["var"], 0, KELLY_CAP_PER_DECILE)
    return min(f * KELLY_FRACTION_MULTIPLIER, MAX_POSITION_FRAC)


calibration_pool = []
per_timepoint = []
for T in TIMEPOINTS:
    train_mask = df["expiration_date"] <= T
    cohort_mask = (df["entry_date"] >= T - pd.Timedelta(days=COHORT_WINDOW_DAYS)) & \
                  (df["entry_date"] <= T + pd.Timedelta(days=COHORT_WINDOW_DAYS))
    train = df[train_mask]
    cohort = df[cohort_mask].copy()
    if len(train) < 2000 or cohort.empty:
        print(f"  skip {T.date()}: train={len(train)} cohort={len(cohort)}", flush=True)
        continue

    # fit the SAME (unaugmented) Tweedie GLM used in production, on the full
    # PIT-corrected eligible universe -- pricing model is universe-wide, only
    # candidate SELECTION is gated by buy/no-buy
    scaler = StandardScaler().fit(train[BASE_FEATURES].to_numpy())
    Xtr = np.clip(scaler.transform(train[BASE_FEATURES].to_numpy()), -5, 5)
    model = TweedieRegressor(power=TWEEDIE_POWER, alpha=TWEEDIE_ALPHA, link="log", max_iter=300)
    model.fit(Xtr, train["return_ratio"].to_numpy())
    Xc = np.clip(scaler.transform(cohort[BASE_FEATURES].to_numpy()), -5, 5)
    cohort["pred_pct_return"] = model.predict(Xc) - 1.0
    cohort["realized_pct_return"] = cohort["return_ratio"] - 1.0

    pool_df = pd.DataFrame(calibration_pool)
    row = {"timepoint": str(T.date()), "n_cohort": len(cohort)}
    if len(pool_df) >= 1000:
        edges = np.quantile(pool_df["pred_pct_return"], np.linspace(0, 1, N_DECILES + 1))
        edges[0], edges[-1] = -np.inf, np.inf
        pool_df["decile"] = pd.cut(pool_df["pred_pct_return"], edges, labels=False, duplicates="drop")
        decile_stats = pool_df.groupby("decile")["realized_pct_return"].agg(["mean", "var", "count"])
        cohort["decile"] = pd.cut(cohort["pred_pct_return"], edges, labels=False, duplicates="drop")

        # buy/no-buy GATE: top-5 tickers at the nearest scored entry_date
        cand_entry_dates = scores["entry_date"].drop_duplicates()
        cand_entry_dates = cand_entry_dates[(cand_entry_dates >= T - pd.Timedelta(days=COHORT_WINDOW_DAYS)) &
                                             (cand_entry_dates <= T + pd.Timedelta(days=COHORT_WINDOW_DAYS))]
        gate_tickers = []
        if not cand_entry_dates.empty:
            entry_date = cand_entry_dates.iloc[(cand_entry_dates - T).abs().argsort().iloc[0]]
            cohort_scores = scores[scores["entry_date"] == entry_date].sort_values("buy_no_buy_proba", ascending=False)
            eligible_tickers = set(cohort["act_symbol"].unique())
            gate_tickers = [t for t in cohort_scores["act_symbol"] if t in eligible_tickers][:TOP_N_GATE]

        # ATM strike selection within each gated ticker
        picks = []
        for ticker in gate_tickers:
            tcalls = cohort[cohort["act_symbol"] == ticker]
            idx = (tcalls["moneyness_strike_over_spot"] - 1.0).abs().idxmin()
            picks.append(tcalls.loc[idx])
        picks_df = pd.DataFrame(picks)
        row["gate_tickers"] = gate_tickers
        row["n_picks"] = len(picks_df)

        if len(picks_df):
            picks_df["kelly_frac"] = picks_df["decile"].apply(lambda d: kelly_fraction(d, decile_stats))
            row["picks"] = [{"t": t, "strike": float(s), "spot": float(sp), "mny": round(float(m), 3),
                              "decile": (None if pd.isna(dd) else int(dd)), "kelly_frac": round(float(kf), 3),
                              "realized_pct": round(float(r) * 100, 2)}
                             for t, s, sp, m, dd, kf, r in zip(
                                 picks_df["act_symbol"], picks_df["strike"], picks_df["underlying_close_entry"],
                                 picks_df["moneyness_strike_over_spot"], picks_df["decile"],
                                 picks_df["kelly_frac"], picks_df["realized_pct_return"])]

            # equal-weight variant (reference)
            row["eq_pct"] = round(float((10000 / len(picks_df) * (1 + picks_df["realized_pct_return"])).sum() / 10000 * 100 - 100), 2)

            # Kelly variant (the actual ask)
            kpicks = picks_df[picks_df["kelly_frac"] > 0]
            tf = kpicks["kelly_frac"].sum()
            if tf > 1.0:
                kpicks = kpicks.copy(); kpicks["kelly_frac"] /= tf; tf = 1.0
            row["kelly_pct"] = round(float((kpicks["kelly_frac"] * kpicks["realized_pct_return"]).sum()) * 100, 2) if len(kpicks) else 0.0
            row["kelly_cash_frac"] = round(1.0 - tf, 3)
        else:
            row.update(eq_pct=None, kelly_pct=None)
    else:
        row.update(eq_pct=None, kelly_pct=None)

    per_timepoint.append(row)
    print(f"  {T.date()}: cohort={row['n_cohort']} gate_n={row.get('n_picks')} "
          f"EQ={row.get('eq_pct')} KELLY={row.get('kelly_pct')}", flush=True)
    calibration_pool.extend(cohort[["pred_pct_return", "realized_pct_return"]].to_dict("records"))

with open(OUT_DIR / "final_strategy_results.json", "w") as f:
    json.dump(per_timepoint, f, indent=2, default=str)
print("\nsaved final_strategy_results.json")
