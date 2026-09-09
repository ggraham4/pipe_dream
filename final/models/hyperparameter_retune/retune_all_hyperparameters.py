"""
Full hyperparameter re-evaluation on the new PIT-eligible + fundamentals
data, per Gabe's request (2026-09-02): "reevaluate all of the hyperparameters
given all of the new data we now have."

Two candidate model families get their hyperparameters swept fresh, on all
three universe/feature variants (OLD/BASE_PIT/AUG_PIT), same purged
walk-forward CV protocol as Round 2 (4 folds, cutoffs 2023/2024/2025/2026
-01-01, final holdout entry_date>=2026-04-01):

  1. TWEEDIE GLM -- power in {1.1..1.9 step 0.1} (9) x
     alpha in {0,0.001,0.01,0.03,0.1,0.3,1.0} (7) = 63 combos. This is a
     substantially finer/wider grid than Round 2's original 5x5=25 (which
     only spanned power 1.2-1.8, alpha 0-1.0 at coarse steps) -- covers the
     edges (1.1, 1.9) and fills in the gaps Round 2's grid skipped
     (1.1/1.3/1.7/1.9, alpha 0.03/0.3).
  2. GAM HURDLE -- sklearn LogisticRegression for P(ITM) (fast, not swept --
     matches the original design's hurdle structure) x GammaGAM for
     magnitude-given-ITM, lam in {20,100} x n_splines in {6,10} (4 combos,
     matching Round 2's grid -- a GAM fit with the new 32-feature set is
     ~15-45s per fit even capped at 150k training rows, so a wider grid
     wasn't practical in this pass; flagged as a real limitation below).

For each variant, the overall winner (by mean CV Tweedie deviance for the
Tweedie candidates, evaluated on the SAME holdout for a GAM-vs-Tweedie
final comparison) gets refit on all pre-holdout data and scored once on the
untouched final holdout.

Run from final/:  python3 models/hyperparameter_retune/retune_all_hyperparameters.py
"""
import gc
import json
import os
import time

import numpy as np
import pandas as pd
from pygam import GammaGAM, s
from sklearn.linear_model import LogisticRegression, TweedieRegressor
from sklearn.preprocessing import StandardScaler

os.makedirs("models/hyperparameter_retune/results", exist_ok=True)

BASE_FEATURES = [
    "moneyness_strike_over_spot", "days_to_expiration", "entry_iv",
    "garch_vol_forecast_1m", "realized_vol_21d_asof",
    "hv_current", "iv_current",
    "momentum_5", "momentum_20", "momentum_60", "momentum_120",
    "volatility_20", "volatility_60",
    "relative_strength_20", "pct_from_high_252", "pct_from_low_252",
    "daily_return", "cumulative_return",
]
FUND_FEATURES = [
    "pe_ratio", "pb_ratio", "ps_ratio", "debt_to_equity", "roe", "roa",
    "gross_margin", "operating_margin", "fcf_margin",
    "revenue_growth_yoy", "earnings_growth_yoy", "rnd_intensity",
    "fundamentals_age_days",
]

TWEEDIE_POWER_GRID = [round(1.1 + 0.1 * i, 2) for i in range(9)]  # 1.1..1.9
TWEEDIE_ALPHA_GRID = [0, 0.001, 0.01, 0.03, 0.1, 0.3, 1.0]
GAM_LAM_GRID = [20, 100]
GAM_NSPLINES_GRID = [6, 10]
GAM_TRAIN_CAP = 150_000  # matches Round 2's cap

FOLD_CUTOFFS = [pd.Timestamp(d) for d in
                ["2023-01-01", "2024-01-01", "2025-01-01", "2026-01-01"]]
FOLD_TEST_DAYS = 92
HOLDOUT_START = pd.Timestamp("2026-04-01")


def load(path, extra_feats):
    df = pd.read_parquet(path)
    df["entry_date"] = pd.to_datetime(df["entry_date"]).astype("datetime64[ns]")
    df["expiration_date"] = pd.to_datetime(df["expiration_date"]).astype("datetime64[ns]")
    df["return_ratio"] = df["payoff_at_expiry"] / df["entry_premium"]
    df["log_volume_20"] = np.log1p(df["volume_20"].clip(lower=0))
    feats = BASE_FEATURES + ["log_volume_20"] + extra_feats
    keep_cols = feats + ["entry_date", "expiration_date", "return_ratio", "act_symbol"]
    df = df[keep_cols].copy()
    df = df.dropna(subset=BASE_FEATURES + ["log_volume_20", "return_ratio"]).reset_index(drop=True)
    return df, feats


def tweedie_deviance(y_true, y_pred, power):
    y_pred = np.clip(y_pred, 1e-6, None)
    y_true = np.clip(y_true, 0, None)
    if power == 0:
        return float(np.mean((y_true - y_pred) ** 2))
    if power == 1:
        with np.errstate(divide="ignore", invalid="ignore"):
            term = np.where(y_true > 0, y_true * np.log(y_true / y_pred), 0)
        return float(2 * np.mean(term - (y_true - y_pred)))
    if power == 2:
        return float(2 * np.mean(np.log(y_pred / y_true) + y_true / y_pred - 1))
    a = y_true ** (2 - power) / ((1 - power) * (2 - power))
    b = y_true * y_pred ** (1 - power) / (1 - power)
    c = y_pred ** (2 - power) / (2 - power)
    return float(2 * np.mean(a - b + c))


def fit_impute(train_df, test_df, feats):
    train_df = train_df.copy()
    test_df = test_df.copy()
    for c in feats:
        if train_df[c].isna().any() or test_df[c].isna().any():
            med = train_df[c].median()
            if pd.isna(med):
                med = 0.0
            train_df[c] = train_df[c].fillna(med)
            test_df[c] = test_df[c].fillna(med)
    return train_df, test_df


def gam_hurdle_predict(clf, gam, X):
    p_itm = clf.predict_proba(X)[:, 1]
    mag = gam.predict(X)
    return p_itm * np.clip(mag, 0, None)


def precompute_folds(search_df, feats):
    """Build each fold's (Xtr, ytr, Xte, yte) ONCE -- these don't depend on
    power/alpha, only on the fold boundaries and feature set, so computing
    them fresh inside the hyperparameter loop (the original approach) was
    both slow (63x redundant scaling/imputation per fold) and the source of
    a real memory blowup (OOM-killed the first attempt at this sweep,
    6GB+ RSS) from repeatedly allocating full-size copies of the up-to-
    540k-row training pool 63 times over."""
    folds = []
    for cutoff in FOLD_CUTOFFS:
        test_start, test_end = cutoff, cutoff + pd.Timedelta(days=FOLD_TEST_DAYS)
        train = search_df[search_df["expiration_date"] <= cutoff]
        test = search_df[(search_df["entry_date"] >= test_start) & (search_df["entry_date"] < test_end)]
        if len(train) < 5000 or len(test) < 50:
            continue
        train_i, test_i = fit_impute(train, test, feats)
        scaler = StandardScaler().fit(train_i[feats].to_numpy())
        Xtr = np.clip(scaler.transform(train_i[feats].to_numpy()), -5, 5).astype(np.float32)
        Xte = np.clip(scaler.transform(test_i[feats].to_numpy()), -5, 5).astype(np.float32)
        ytr = train_i["return_ratio"].to_numpy().astype(np.float32)
        yte = test_i["return_ratio"].to_numpy().astype(np.float32)
        folds.append((cutoff, Xtr, ytr, Xte, yte))
        del train, test, train_i, test_i
    gc.collect()
    return folds


def sweep_tweedie(folds):
    grid_scores = {}
    n_done = 0
    for power in TWEEDIE_POWER_GRID:
        for alpha in TWEEDIE_ALPHA_GRID:
            fold_devs = []
            for cutoff, Xtr, ytr, Xte, yte in folds:
                model = TweedieRegressor(power=power, alpha=alpha, link="log", max_iter=300)
                model.fit(Xtr, ytr)
                pred = model.predict(Xte)
                fold_devs.append(tweedie_deviance(yte, pred, power))
            if fold_devs:
                grid_scores[(power, alpha)] = float(np.mean(fold_devs))
            n_done += 1
            if n_done % 10 == 0:
                print(f"    Tweedie combo {n_done}/{len(TWEEDIE_POWER_GRID)*len(TWEEDIE_ALPHA_GRID)} done", flush=True)
    gc.collect()
    return grid_scores


def precompute_gam_folds(search_df, feats):
    """Same idea as precompute_folds, but caps training rows at
    GAM_TRAIN_CAP (matches Round 2's cap -- a GAM fit with the new
    32-feature set is 15-45s even at 150k rows) and precomputes the
    ITM/non-ITM split once, since that's shared across the lam/n_splines
    grid too."""
    folds = []
    for cutoff in FOLD_CUTOFFS:
        test_start, test_end = cutoff, cutoff + pd.Timedelta(days=FOLD_TEST_DAYS)
        train = search_df[search_df["expiration_date"] <= cutoff]
        test = search_df[(search_df["entry_date"] >= test_start) & (search_df["entry_date"] < test_end)]
        if len(train) < 5000 or len(test) < 50:
            continue
        if len(train) > GAM_TRAIN_CAP:
            train = train.sample(n=GAM_TRAIN_CAP, random_state=0)
        train_i, test_i = fit_impute(train, test, feats)
        scaler = StandardScaler().fit(train_i[feats].to_numpy())
        Xtr = np.clip(scaler.transform(train_i[feats].to_numpy()), -5, 5).astype(np.float32)
        Xte = np.clip(scaler.transform(test_i[feats].to_numpy()), -5, 5).astype(np.float32)
        ytr = train_i["return_ratio"].to_numpy().astype(np.float32)
        yte = test_i["return_ratio"].to_numpy().astype(np.float32)
        itm_tr = (ytr > 0).astype(int)
        clf = LogisticRegression(max_iter=500).fit(Xtr, itm_tr)
        Xtr_itm, ytr_itm = Xtr[itm_tr == 1], ytr[itm_tr == 1]
        folds.append((cutoff, Xtr_itm, ytr_itm, clf, Xte, yte))
        del train, test, train_i, test_i, Xtr
    gc.collect()
    return folds


def sweep_gam(gam_folds, feats):
    grid_scores = {}
    terms = s(0)
    for i in range(1, len(feats)):
        terms = terms + s(i)
    for lam in GAM_LAM_GRID:
        for nsp in GAM_NSPLINES_GRID:
            fold_devs = []
            for cutoff, Xtr_itm, ytr_itm, clf, Xte, yte in gam_folds:
                try:
                    gam = GammaGAM(terms, lam=lam, n_splines=nsp, max_iter=50).fit(Xtr_itm, ytr_itm)
                except Exception as e:
                    print(f"    GAM fit failed lam={lam} nsp={nsp} fold={cutoff.date()}: {e}", flush=True)
                    continue
                pred = gam_hurdle_predict(clf, gam, Xte)
                fold_devs.append(tweedie_deviance(yte, pred, 1.5))
                del gam
            if fold_devs:
                grid_scores[(lam, nsp)] = float(np.mean(fold_devs))
                print(f"    GAM lam={lam} nsp={nsp}: mean CV deviance={grid_scores[(lam, nsp)]:.4f} "
                      f"({len(fold_devs)} folds)", flush=True)
            gc.collect()
    return grid_scores


def run_variant(name, path, extra_feats):
    print(f"\n{'='*70}\nVARIANT {name}: {path}\n{'='*70}", flush=True)
    df, feats = load(path, extra_feats)
    print(f"  {len(df):,} rows, {len(feats)} features", flush=True)

    holdout_mask = df["entry_date"] >= HOLDOUT_START
    search_df = df[~holdout_mask].reset_index(drop=True)
    holdout_df = df[holdout_mask].reset_index(drop=True)
    print(f"  search pool: {len(search_df):,} rows | final holdout: {len(holdout_df):,} rows", flush=True)

    t0 = time.time()
    print("  Precomputing Tweedie folds...", flush=True)
    tw_folds = precompute_folds(search_df, feats)
    print(f"  {len(tw_folds)} folds ready in {time.time()-t0:.0f}s. Sweeping Tweedie GLM (63 combos)...", flush=True)
    t0 = time.time()
    tweedie_scores = sweep_tweedie(tw_folds)
    best_tweedie = min(tweedie_scores, key=tweedie_scores.get)
    print(f"  Tweedie done in {time.time()-t0:.0f}s. Best: power={best_tweedie[0]}, "
          f"alpha={best_tweedie[1]}, CV deviance={tweedie_scores[best_tweedie]:.4f}", flush=True)
    del tw_folds
    gc.collect()

    t0 = time.time()
    print("  Precomputing GAM folds (train capped at 150k/fold)...", flush=True)
    gam_folds = precompute_gam_folds(search_df, feats)
    print(f"  {len(gam_folds)} folds ready in {time.time()-t0:.0f}s. Sweeping GAM hurdle (4 combos)...", flush=True)
    t0 = time.time()
    gam_scores = sweep_gam(gam_folds, feats)
    del gam_folds
    gc.collect()
    if gam_scores:
        best_gam = min(gam_scores, key=gam_scores.get)
        print(f"  GAM done in {time.time()-t0:.0f}s. Best: lam={best_gam[0]}, "
              f"n_splines={best_gam[1]}, CV deviance (power=1.5 proxy)={gam_scores[best_gam]:.4f}", flush=True)
    else:
        best_gam = None
        print("  GAM sweep produced no usable folds.", flush=True)

    # ---- refit both winners on all pre-holdout data, score once on holdout ----
    train_i, holdout_i = fit_impute(search_df, holdout_df, feats)
    scaler = StandardScaler().fit(train_i[feats].to_numpy())
    Xtr = np.clip(scaler.transform(train_i[feats].to_numpy()), -5, 5)
    Xho = np.clip(scaler.transform(holdout_i[feats].to_numpy()), -5, 5)
    y_tr = train_i["return_ratio"].to_numpy()
    y_ho = holdout_i["return_ratio"].to_numpy()

    tw_model = TweedieRegressor(power=best_tweedie[0], alpha=best_tweedie[1], link="log", max_iter=300)
    tw_model.fit(Xtr, y_tr)
    tw_pred_ho = tw_model.predict(Xho)
    tw_mae = float(np.mean(np.abs(y_ho - tw_pred_ho)))
    tw_dev = tweedie_deviance(y_ho, tw_pred_ho, best_tweedie[0])
    tw_dir_acc = float(np.mean((tw_pred_ho > 1.0) == (y_ho > 1.0)))

    gam_result = None
    if best_gam is not None:
        terms = s(0)
        for i in range(1, len(feats)):
            terms = terms + s(i)
        itm_tr = (y_tr > 0).astype(int)
        clf = LogisticRegression(max_iter=500).fit(Xtr, itm_tr)
        Xtr_itm, y_tr_itm = Xtr[itm_tr == 1], y_tr[itm_tr == 1]
        # cap the final refit the same way the CV sweep was capped (GAM_TRAIN_CAP)
        # -- fitting on the FULL uncapped pre-holdout pool (much bigger than any
        # single CV fold) hit a real PIRLS divergence on the first attempt at this
        # run, consistent with the design doc's earlier-documented GAM divergence
        # issue; capping keeps it consistent with what was actually validated in CV
        if len(y_tr_itm) > GAM_TRAIN_CAP:
            rng = np.random.RandomState(0)
            idx = rng.choice(len(y_tr_itm), size=GAM_TRAIN_CAP, replace=False)
            Xtr_itm, y_tr_itm = Xtr_itm[idx], y_tr_itm[idx]
        try:
            gam = GammaGAM(terms, lam=best_gam[0], n_splines=best_gam[1], max_iter=50).fit(Xtr_itm, y_tr_itm)
            gam_pred_ho = gam_hurdle_predict(clf, gam, Xho)
            gam_mae = float(np.mean(np.abs(y_ho - gam_pred_ho)))
            gam_dev = tweedie_deviance(y_ho, gam_pred_ho, 1.5)
            gam_dir_acc = float(np.mean((gam_pred_ho > 1.0) == (y_ho > 1.0)))
            gam_result = dict(lam=best_gam[0], n_splines=best_gam[1],
                               holdout_mae=gam_mae, holdout_deviance=gam_dev, holdout_dir_accuracy=gam_dir_acc)
        except Exception as e:
            print(f"  WARNING: final GAM refit diverged ({e}) -- GAM excluded from this "
                  f"variant's final comparison, Tweedie is the only holdout-scored candidate.", flush=True)
            gam_result = dict(lam=best_gam[0], n_splines=best_gam[1], failed=True, error=str(e))

    benchmark_mae = float(np.mean(np.abs(y_ho - 1.0)))
    benchmark_dev15 = tweedie_deviance(y_ho, np.ones_like(y_ho), 1.5)
    benchmark_dir_acc = float(np.mean(y_ho <= 1.0))

    overall_winner = "tweedie"
    if gam_result is not None and not gam_result.get("failed") and gam_result["holdout_mae"] < tw_mae:
        overall_winner = "gam"

    result = dict(
        variant=name, n_features=len(feats),
        tweedie_best=dict(power=best_tweedie[0], alpha=best_tweedie[1], cv_deviance=tweedie_scores[best_tweedie],
                           holdout_mae=tw_mae, holdout_deviance=tw_dev, holdout_dir_accuracy=tw_dir_acc),
        gam_best=gam_result,
        benchmark=dict(mae=benchmark_mae, deviance_power1_5=benchmark_dev15, dir_accuracy=benchmark_dir_acc),
        overall_winner=overall_winner,
        holdout_n=len(holdout_i),
        tweedie_grid={f"{p}_{a}": v for (p, a), v in tweedie_scores.items()},
        gam_grid={f"{l}_{n}": v for (l, n), v in gam_scores.items()},
    )
    print(f"\n  HOLDOUT ({len(holdout_i):,} rows) -- Tweedie: MAE={tw_mae:.4f} dev={tw_dev:.4f} dir.acc={tw_dir_acc:.4f}", flush=True)
    if gam_result and not gam_result.get("failed"):
        print(f"  HOLDOUT -- GAM: MAE={gam_result['holdout_mae']:.4f} dev={gam_result['holdout_deviance']:.4f} "
              f"dir.acc={gam_result['holdout_dir_accuracy']:.4f}", flush=True)
    elif gam_result and gam_result.get("failed"):
        print("  HOLDOUT -- GAM: final refit diverged, excluded from comparison", flush=True)
    print(f"  Benchmark: MAE={benchmark_mae:.4f} dir.acc={benchmark_dir_acc:.4f}", flush=True)
    print(f"  OVERALL WINNER (by MAE): {overall_winner.upper()}", flush=True)
    return result


results = {}
results["OLD"] = run_variant("OLD (unfiltered universe, price/vol only)",
                              "data/training/options_calls_training.parquet", [])
results["BASE_PIT"] = run_variant("BASE-PIT (PIT-eligible universe, price/vol only)",
                                   "data/training/options_calls_training_pit.parquet", [])
results["AUG_PIT"] = run_variant("AUG-PIT (PIT-eligible universe + fundamentals)",
                                  "data/training/options_calls_training_pit.parquet", FUND_FEATURES)

print(f"\n\n{'='*70}\nFINAL SUMMARY\n{'='*70}")
for k, r in results.items():
    tw = r["tweedie_best"]
    print(f"{k}: winner={r['overall_winner']} | Tweedie(power={tw['power']},alpha={tw['alpha']}) "
          f"MAE={tw['holdout_mae']:.4f} dev={tw['holdout_deviance']:.4f}", end="")
    if r["gam_best"] and not r["gam_best"].get("failed"):
        g = r["gam_best"]
        print(f" | GAM(lam={g['lam']},n_splines={g['n_splines']}) MAE={g['holdout_mae']:.4f} dev={g['holdout_deviance']:.4f}")
    elif r["gam_best"] and r["gam_best"].get("failed"):
        print(" | GAM: final refit diverged")
    else:
        print()

with open("models/hyperparameter_retune/results/retune_all_hyperparameters_results.json", "w") as f:
    json.dump(results, f, indent=2, default=str)
print("\nSaved retune_all_hyperparameters_results.json")
