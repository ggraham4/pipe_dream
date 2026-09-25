"""
PRODUCTION -- live buy signals for the app's Stock tab.

ROUND 18 (2026-09-16). This script now produces TWO signals from one panel
load, because Gabe asked for both on the app so a pick can be read against a
second opinion rather than taken on faith:

    PRIMARY    price_fund_h40_q75_trd_xgb_d3e01r100_expanding_cap500k_pit_s40
               binary top-quartile label, XGBClassifier. This is the deployed
               configuration and the one the app leads with.

    CANDIDATE  price_fund_h40_xrank_trd_xgb_reg_d3e01r100_expanding_cap500k_pit_s40
               within-date percentile-rank label, XGBRegressor. Identical
               features, identical hyperparameters, identical construction --
               the ONLY difference is the target.

WHY THE CANDIDATE IS NOT PRIMARY, stated here so nobody has to go find it:
Round 17b found that switching to the cross-sectional rank label flipped every
feature family's model-level IC positive, including price_fund (-0.0038 ->
+0.0104), which looked like the pipeline defect had been located. Round 18 put
it on the 2020-2026 hold-out and it FAILED:

    q75    (primary)    +7.33%/yr excess    1.526x SPY
    xrank  (candidate)  -4.28%/yr excess    0.771x SPY

So the label change recovers in-sample IC and loses out-of-sample money. It is
carried on the app as a tracked candidate -- visible, labelled, and NOT acted
on -- not as a replacement. See backtest/2026-09-12-xrank-fails-the-holdout-
do-not-switch.md and backtest/2026-09-12-round17b-the-label-was-the-defect.md.

--------------------------------------------------------------------------
TWO FAITHFULNESS FIXES MADE IN THIS REWRITE (both change today's picks)
--------------------------------------------------------------------------
The live script had drifted from the cell it claims to run. Both divergences
are fixed here and both are real changes to what gets picked:

 1. LABEL BASIS. The cell id ends in `_trd_` -- it is trained on
    forward_return_tradable_40 (close[t+H] / open[t+1]: what you actually get
    if you buy at the next open). This script was training on
    forward_return_40 (close[t]-to-close[t+H]), which credits a move that was
    already over before you could trade it. Every backtested number the app
    quotes comes from the tradable basis. Now switched to TRADABLE_LABEL_COL.

 2. CANDIDATE POOL -- and a warning, because this was got wrong once already.

    The pool is names with COMPLETE price features. It has to be, and the
    reason is not obvious from reading scorecache._run_cell, which contains no
    filter of its own: the filter is applied far upstream, when the panel is
    loaded. PanelContext calls

        W.load_panel_prepared(path, want, list(FEATURE_COLS), horizon)

    whose third argument is `filter_cols`, and which "keeps only rows with
    complete features". By the time _run_cell slices a test set, every
    incomplete row is already gone. The proof is in the cache: the deployed
    cell's 154,839 scored rows contain ZERO NaN volatility_60.

    On 2026-09-16 this script was changed to score every PIT-eligible name on
    the theory that the backtest did. It does not. The change admitted 59
    names (3.5% of the universe), and because volatility_60 is itself one of
    FEATURE_COLS, a name missing it reaches _bucket_idx as NaN -- which files
    it in BUCKET 0, the lowest-volatility quintile, since that array is
    initialised to zeros and only finite entries are overwritten. An unknown
    volatility is not a low volatility. Two of five deployed picks that day
    were names that should never have been scored, and one of them displaced
    the genuine low-vol pick in both signals.

    The filter below is therefore deliberate and load-bearing. If you are
    tempted to widen the pool again, the thing to check first is
    load_panel_prepared, not _run_cell.

--------------------------------------------------------------------------
CONSTRUCTION (identical for both signals, and to the backtest)
--------------------------------------------------------------------------
Train on the most recent TRAIN_CAP labelled rows (expanding history, capped),
apply the point-in-time universe screen to today's candidates, take the single
best name in each of 5 trailing-volatility quintiles, weight by inverse
volatility. Selection rules are imported from sweep/portfolio.py rather than
reimplemented -- DATA-PIPELINE-HANDOFF.md section 6.4: a live pick and a
backtested pick must not come from two copies of the same rule.

NOT A VALIDATED EDGE, and not claimed as one. Round 12's pre-registered sweep
of 1,152 configurations failed its acceptance criteria (Deflated Sharpe 0.746,
Reality Check p = 0.61), Round 13 showed the fundamental signal is a sector
bet, and Rounds 15/15b closed off breadth and horizon as levers. Round 18
measured the noise scale directly: ten hyperparameter-only variants of this
same cell span -8.01 to +9.15 %/yr, sd 5.03. What the model demonstrably owns
is a low-volatility tilt (score-vol correlation -0.134) plus a tech/healthcare
sector bet -- both of which are purchasable as ETFs, which is why the app now
shows SPY and USMV beside it.

Usage:
    python3 current_signal_pit.py              # both signals
    python3 current_signal_pit.py --only q75   # primary only (faster)

Prerequisites: out/features_with_fundamentals_sharadar_pit.parquet must exist
(build_features_sharadar.py -> build_features_fundamentals_sharadar.py).
"""
import argparse
import os

import numpy as np
import pandas as pd
from xgboost import XGBClassifier, XGBRegressor

from features import (FEATURE_COLS, FORWARD_WINDOW, LABEL_COL, TRADABLE_LABEL_COL,
                      OUT_DIR, MODELS_DIR, atomic_to_csv, atomic_write_json)
from fundamentals_features_beta import FUNDAMENTAL_FEATURE_COLS
from continuous_walkforward_pit import (MIN_MARKET_CAP, MIN_PRICE,
                                        load_gap_ticker_set,
                                        load_pit_universe)

# ---------------------------------------------------------------------------
# Construction constants. These ARE the cell id -- change one and the app is no
# longer running the configuration whose backtest it quotes.
# ---------------------------------------------------------------------------
TOP_N = 5
N_VOL_BUCKETS = 5          # one name from each trailing-volatility quintile
WEIGHTING = "invvol"       # inverse trailing volatility, normalized to 1
TRAIN_CAP = 500_000        # most recent N labelled rows; 0 = expanding, uncapped
CUTOFF_PERCENTILE = 75     # the q75 label's binarization point
DEPTH, ETA, ROUNDS = 3, 0.1, 100
LABEL_BASIS_COL = TRADABLE_LABEL_COL   # see fix (1) in the module docstring

NO_STALE_COLS = [c for c in FUNDAMENTAL_FEATURE_COLS if c != "fundamentals_age_days"]
AUGMENTED_FEATURE_COLS = FEATURE_COLS + NO_STALE_COLS

# Round 8 stop-loss level. REPORTED ONLY. The selected configuration holds to
# the 40-day horizon with no stop; this number is per-name risk guidance and is
# NOT part of the backtested configuration.
OPTIMAL_STOP_PCT = 0.15

# Round 11. "pit" reads the rebuilt point-in-time panel and takes eligibility
# from pit_universe.parquet. PIPE_DREAM_UNIVERSE=expanded falls back to the
# pre-Round-11 behaviour.
UNIVERSE = os.environ.get("PIPE_DREAM_UNIVERSE", "pit")

CONTEXT_COLS = ["close", "momentum_20", "momentum_60", "momentum_120",
                "relative_strength_20", "pct_from_high_252", "pct_from_low_252",
                "volatility_20", "market_cap"]

# ---------------------------------------------------------------------------
# The two signals. `role` drives how the app presents them; nothing in this
# script treats the candidate as advisory, so if it is ever promoted the only
# edit needed is here.
# ---------------------------------------------------------------------------
VARIANTS = [
    {
        "key": "q75",
        "role": "primary",
        "label": "q75",
        "model": "xgb",
        "cell_id": "price_fund_h40_q75_trd_xgb_d3e01r100_expanding_cap500k_pit_s40",
        "display_name": "Deployed (q75 / classifier)",
        "signal_csv": "current_signal_pit.csv",
        "signal_meta": "current_signal_pit_meta.json",
        "model_file": "xgb_pit_augmented_model.json",
        "holdout_excess_cagr_pct": 7.33,
        "holdout_mult_vs_spy": 1.526,
        "nominate_excess_cagr_pct": 8.71,
        "nominate_mult_vs_spy": 2.796,
        "note": ("The deployed configuration. Positive on both the 2007-2019 "
                 "selection era and the 2020-2026 hold-out, but selected from "
                 "a 1,152-cell sweep that failed its significance gates, and "
                 "sitting 1.06 sd above the mean of its own hyperparameter "
                 "family. Treat the size of the edge as unknown."),
    },
    {
        "key": "xrank",
        "role": "candidate",
        "label": "xrank",
        "model": "xgb_reg",
        "cell_id": "price_fund_h40_xrank_trd_xgb_reg_d3e01r100_expanding_cap500k_pit_s40",
        "display_name": "Candidate (xrank / regressor)",
        "signal_csv": "current_signal_pit_xrank.csv",
        "signal_meta": "current_signal_pit_xrank_meta.json",
        "model_file": "xgb_pit_xrank_model.json",
        "holdout_excess_cagr_pct": -4.28,
        "holdout_mult_vs_spy": 0.771,
        "nominate_excess_cagr_pct": None,
        "nominate_mult_vs_spy": None,
        "note": ("TRACKED, NOT ACTED ON. The rank label recovered model-level "
                 "IC in Round 17b and then LOST to SPY on the 2020-2026 "
                 "hold-out (-4.28%/yr excess, 0.771x). It is shown so its "
                 "picks can be compared against the deployed model's in real "
                 "time, not because it is an alternative to follow."),
    },
]


def variant(key):
    for v in VARIANTS:
        if v["key"] == key:
            return v
    raise KeyError(key)


def latest_complete_date_pit(feat, gap_tickers, min_coverage=0.9):
    """Latest date where >= min_coverage of THAT DAY'S point-in-time universe
    is present in the panel.

    features.latest_complete_date() cannot be used here. It requires
    min_coverage of ALL tickers in the panel to have a row, and this panel
    carries thousands of companies that are delisted, bankrupt or acquired --
    some inactive since 2008 -- which by definition never have a recent row.
    Confirmed the hard way on 2026-09-02 (Gabe's first real run): the plain
    version silently returned NaT, which cascaded into a 0-eligible
    RuntimeError much further down.

    Known, pre-existing limitation (see price_discontinuity.py): a gap ticker
    that was also split by the discontinuity check (e.g. "CHRD__post20201118")
    won't match load_gap_ticker_set()'s plain symbols, so its post-break
    segment counts as current-universe here. A handful of tickers; not fixed
    here."""
    if UNIVERSE == "pit":
        # Denominator = the names that were supposed to be trading that day,
        # not "every ticker in the panel that is not a known gap ticker".
        pit = load_pit_universe()
        have = feat.groupby("date")["ticker"].apply(set)
        for d in sorted(have.index, reverse=True):
            members = pit.get(str(pd.Timestamp(d).date()))
            if not members:
                continue
            cov = len(members & have[d]) / len(members)
            if cov >= min_coverage:
                print(f"Freshness: {pd.Timestamp(d).date()} has "
                      f"{len(members & have[d])}/{len(members)} "
                      f"({cov:.1%}) of that day's PIT universe in the panel")
                return d
        raise RuntimeError(
            f"No date reaches {min_coverage:.0%} coverage of its own PIT universe. "
            f"Panel runs to {pd.Timestamp(max(have.index)).date()}, "
            f"pit_universe.parquet to {max(pit)}. If those differ, rebuild the "
            f"later one; if they match, the price pull is stale.")

    current = feat[~feat["ticker"].isin(gap_tickers)]
    counts = current.groupby("date").size()
    total = current["ticker"].nunique()
    complete_dates = counts[counts >= min_coverage * total].index
    if len(complete_dates) == 0:
        raise RuntimeError(
            f"No date reaches {min_coverage:.0%} coverage of the {total} "
            f"current-universe tickers (gap tickers excluded) -- check that the "
            f"feature build ran against fresh price data.")
    return complete_dates.max()


def _modelling_frame(panel):
    """The panel the backtest actually sees: rows with COMPLETE price features.

    This is load_panel_prepared's `filter_cols` step, reproduced here. It has
    to happen before anything else -- before the label ranking, before the
    training mask, before today's candidate pool -- because in the sweep it
    happens at panel load and everything downstream inherits it. See the
    module docstring for what went wrong when it did not."""
    n_before = len(panel)
    feat = panel.dropna(subset=FEATURE_COLS)
    print(f"Complete price features: {len(feat):,} of {n_before:,} panel rows "
          f"({len(feat) / max(n_before, 1):.1%}) -- matches "
          f"load_panel_prepared(filter_cols=FEATURE_COLS)")
    return feat.reset_index(drop=True)


def _training_frame(feat):
    """Rows eligible to train on: finite label, then the most recent
    TRAIN_CAP of those. `feat` is already restricted to complete price
    features, so this is exactly scorecache._run_cell's mask over exactly
    scorecache's frame."""
    train = feat[np.isfinite(feat[LABEL_BASIS_COL].to_numpy(np.float64))]
    n_before = len(train)
    if TRAIN_CAP and len(train) > TRAIN_CAP:
        train = train.sort_values("date").tail(int(TRAIN_CAP))
    print(f"Training rows: {len(train):,} of {n_before:,} labelled "
          f"({train['date'].min().date()} .. {train['date'].max().date()}), "
          f"label basis = {LABEL_BASIS_COL}")
    return train


def _xrank_target(feat, train_index):
    """Within-date cross-sectional percentile rank of the tradable forward
    return.

    Two things about WHICH rows it is ranked against, both of which change the
    target if got wrong. scorecache._derive_labels runs on `self.feat`, the
    ALREADY-FILTERED frame, so the peer group is names with complete price
    features on that date -- not every row in the raw panel. And it ranks once
    per date over that whole frame, then the training mask is applied, so the
    peer group is not the capped training subset either; ranking inside the cap
    would rank against a truncated peer group on the boundary dates."""
    y = feat[LABEL_BASIS_COL].to_numpy(np.float32)
    r = pd.Series(y).groupby(feat["date"].values).rank(pct=True)
    r.index = feat.index
    return r.loc[train_index].to_numpy(np.float32)


def _fit(v, X, y):
    common = dict(n_estimators=ROUNDS, max_depth=DEPTH, learning_rate=ETA,
                  verbosity=0, random_state=0)
    if v["model"] == "xgb":
        m = XGBClassifier(eval_metric="logloss", **common)
    elif v["model"] == "xgb_reg":
        m = XGBRegressor(objective="reg:squarederror", eval_metric="rmse", **common)
    else:
        raise ValueError(v["model"])
    m.fit(X, y)
    return m


def _score(v, model, X):
    if v["model"] == "xgb":
        return model.predict_proba(X)[:, 1]
    return model.predict(X)


def run_variant(v, feat, train, eligible, latest_date):
    print(f"\n=== {v['display_name']} ({v['role'].upper()}) ===")
    print(f"cell: {v['cell_id']}")
    X = train[AUGMENTED_FEATURE_COLS]

    if v["label"] == "q75":
        lab = train[LABEL_BASIS_COL].to_numpy(np.float64)
        cut = float(np.percentile(lab, CUTOFF_PERCENTILE))
        y = (lab > cut).astype(int)
        print(f"label cutoff ({CUTOFF_PERCENTILE}th pct of {FORWARD_WINDOW}d "
              f"tradable fwd return) = {cut:.4f}  ->  {y.mean():.1%} positives")
        label_detail = {"label_cutoff_fwd_return": round(cut, 4)}
    elif v["label"] == "xrank":
        y = _xrank_target(feat, train.index)
        cut = None
        print(f"label: within-date percentile rank, mean {float(np.nanmean(y)):.4f}")
        label_detail = {"label_cutoff_fwd_return": None}
    else:
        raise ValueError(v["label"])

    model = _fit(v, X, y)

    d = eligible.copy()
    d["score"] = _score(v, model, d[AUGMENTED_FEATURE_COLS])
    d["rank"] = d["score"].rank(ascending=False, method="min").astype(int)
    d["percentile"] = d["rank"] / len(d)

    from sweep.portfolio import _pick_idx, _weights
    arr = {
        "score": d["score"].to_numpy(np.float64),
        "vol": (d["volatility_60"].to_numpy(np.float64) if "volatility_60" in d.columns
                else np.full(len(d), np.nan)),
        "cap": (d["market_cap"].to_numpy(np.float64) if "market_cap" in d.columns
                else np.full(len(d), np.nan)),
    }
    idx = _pick_idx(arr, TOP_N, "volq", n_buckets=N_VOL_BUCKETS)
    picks = d.iloc[idx].copy()
    picks["weight_pct"] = _weights(arr, idx, WEIGHTING) * 100.0
    picks["stop_loss_price"] = picks["close"] * (1 - OPTIMAL_STOP_PCT)

    rows_out = []
    for _, r in picks.iterrows():
        def g(c, nd=4):
            return round(float(r[c]), nd) if pd.notna(r.get(c)) else None
        rows_out.append({
            "ticker": r["ticker"],
            "allocation_pct": round(float(r["weight_pct"]), 3),
            "score": round(float(r["score"]), 4),
            "rank": int(r["rank"]),
            "percentile": round(float(r["percentile"]), 4),
            "close": g("close", 2),
            "suggested_stop_loss_price": round(float(r["stop_loss_price"]), 2),
            "stop_loss_pct": OPTIMAL_STOP_PCT,
            "market_cap": g("market_cap", 0),
            "momentum_20": g("momentum_20"),
            "momentum_60": g("momentum_60"),
            "relative_strength_20": g("relative_strength_20"),
            "pct_from_high_252": g("pct_from_high_252"),
            "volatility_20": g("volatility_20"),
        })

    out_df = pd.DataFrame(rows_out)
    print(out_df.to_string(index=False))
    print(f"inverse-vol weights: {picks['weight_pct'].min():.2f}% .. "
          f"{picks['weight_pct'].max():.2f}% per name")

    atomic_to_csv(out_df, OUT_DIR / v["signal_csv"], index=False)
    meta = {
        "variant": v["key"],
        "role": v["role"],
        "display_name": v["display_name"],
        "cell_id": v["cell_id"],
        "as_of_date": str(pd.Timestamp(latest_date).date()),
        "label": v["label"],
        "label_basis_column": LABEL_BASIS_COL,
        "model": v["model"],
        "depth": DEPTH, "eta": ETA, "rounds": ROUNDS,
        "train_cap": TRAIN_CAP,
        "train_rows": int(len(train)),
        "forward_window_trading_days": FORWARD_WINDOW,
        "top_n": TOP_N, "n_vol_buckets": N_VOL_BUCKETS, "weighting": WEIGHTING,
        "stop_loss_pct": OPTIMAL_STOP_PCT,
        "stop_loss_is_reported_only": True,
        "min_market_cap": MIN_MARKET_CAP,
        "min_price": MIN_PRICE,
        "n_eligible_today": int(len(eligible)),
        "picks": picks["ticker"].tolist(),
        "allocation": rows_out,
        "holdout_excess_cagr_pct": v["holdout_excess_cagr_pct"],
        "holdout_mult_vs_spy": v["holdout_mult_vs_spy"],
        "nominate_excess_cagr_pct": v["nominate_excess_cagr_pct"],
        "nominate_mult_vs_spy": v["nominate_mult_vs_spy"],
        "note": v["note"],
        **label_detail,
    }
    atomic_write_json(meta, OUT_DIR / v["signal_meta"], indent=2)

    MODELS_DIR.mkdir(parents=True, exist_ok=True)
    model.save_model(str(MODELS_DIR / v["model_file"]))
    print(f"wrote out/{v['signal_csv']}, out/{v['signal_meta']}, "
          f"out/models/{v['model_file']}")
    return meta


def main():
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[1])
    ap.add_argument("--only", choices=[v["key"] for v in VARIANTS],
                    help="train just one variant (primary is 'q75')")
    args = ap.parse_args()
    wanted = [variant(args.only)] if args.only else list(VARIANTS)

    panel = (OUT_DIR / "features_with_fundamentals_sharadar_pit.parquet"
             if UNIVERSE == "pit"
             else OUT_DIR / "features_with_fundamentals_pit.parquet")
    print(f"Panel: {panel.name}  (universe={UNIVERSE})")
    raw = pd.read_parquet(panel)
    raw = raw.sort_values(["ticker", "date"]).reset_index(drop=True)
    feat = raw
    if LABEL_BASIS_COL not in feat.columns:
        raise RuntimeError(
            f"{LABEL_BASIS_COL} is not in {panel.name}. The deployed cell is "
            f"trained on the tradable (next-open entry) label; rebuild the "
            f"panel with a features.py that emits it rather than falling back "
            f"to {LABEL_COL}, which credits a move you could not have traded.")

    gap_tickers = load_gap_ticker_set()
    # Freshness is asked of the RAW panel: the question is whether the price
    # pull covers that day's universe, not whether every name has a 252-day
    # high yet. Filtering first would make a perfectly fresh panel look stale.
    latest_date = latest_complete_date_pit(raw, gap_tickers)
    print(f"Latest complete trading date: {pd.Timestamp(latest_date).date()}")

    feat = _modelling_frame(raw)
    del raw
    train = _training_frame(feat)

    today = feat[feat["date"] == latest_date].copy()
    if UNIVERSE == "pit":
        # Eligibility was already applied as of the date, on daily.marketcap
        # and closeunadj -- the correct quantities. Re-applying the panel's own
        # market_cap (= close x sharesbas) and split-adjusted close here would
        # screen on two different numbers than the universe was built from.
        day = load_pit_universe().get(str(pd.Timestamp(latest_date).date()), frozenset())
        if not day:
            raise RuntimeError(
                f"pit_universe.parquet has no rows for {latest_date} -- rebuild "
                f"it (build_pit_universe.py) after refreshing the panel.")
        eligible = today[today["ticker"].isin(day)].copy()
        print(f"PIT eligibility on {pd.Timestamp(latest_date).date()}: "
              f"{len(eligible)} of {len(today)} panel rows "
              f"({len(day)} names eligible that day)")
    else:
        eligible = today[(today["close"] > MIN_PRICE)
                         & (today["market_cap"] >= MIN_MARKET_CAP)].copy()
        print(f"Mid-cap+ floor: {len(eligible)}/{len(today)} eligible today")

    # Gate A7c, "verify by naming what should be there": every selectable name
    # must have a finite volatility_60, because that is the variable the
    # volatility-quintile buckets and the inverse-vol weights are BOTH built
    # from, and _bucket_idx silently files a NaN into bucket 0 -- the
    # lowest-volatility quintile -- rather than refusing it. The filter above
    # already guarantees this; the assert is here so that if some future change
    # widens the pool again, it fails loudly at the source instead of quietly
    # putting an unknown-volatility name in the low-volatility slot.
    _v = eligible["volatility_60"].to_numpy(np.float64)
    if not np.isfinite(_v).all():
        bad = eligible.loc[~np.isfinite(_v), "ticker"].tolist()
        raise RuntimeError(
            f"{len(bad)} eligible name(s) have a NaN volatility_60 "
            f"({', '.join(bad[:10])}{' ...' if len(bad) > 10 else ''}). "
            f"_bucket_idx would file these in the LOWEST-volatility quintile, "
            f"which is wrong -- an unknown volatility is not a low one. The "
            f"complete-price-feature filter is supposed to make this "
            f"impossible; something upstream changed.")
    if eligible.empty:
        raise RuntimeError(
            "No tickers cleared the point-in-time eligibility screen today -- "
            "check that the fundamentals feature build ran recently enough to "
            "have current market_cap data.")

    metas = {}
    for v in wanted:
        metas[v["key"]] = run_variant(v, feat, train, eligible, latest_date)

    if len(metas) > 1:
        a, b = metas["q75"]["picks"], metas["xrank"]["picks"]
        both = sorted(set(a) & set(b))
        print("\n--- agreement ---")
        print(f"primary  : {', '.join(a)}")
        print(f"candidate: {', '.join(b)}")
        print(f"overlap  : {len(both)}/{TOP_N}" + (f" ({', '.join(both)})" if both else ""))
        atomic_write_json({
            "as_of_date": metas["q75"]["as_of_date"],
            "primary": "q75",
            "variants": {k: {"picks": m["picks"], "cell_id": m["cell_id"],
                             "role": m["role"], "display_name": m["display_name"]}
                         for k, m in metas.items()},
            "overlap": both,
            "n_overlap": len(both),
            "caveat": ("Agreement between the two is NOT confirmation. They "
                       "share features, hyperparameters and construction and "
                       "differ only in the training target, so their errors "
                       "are correlated by design. The candidate lost to SPY "
                       "on the hold-out; overlap with it does not make a "
                       "primary pick safer."),
        }, OUT_DIR / "current_signal_compare.json", indent=2)
        print("wrote out/current_signal_compare.json")

    print("\nNOT A VALIDATED EDGE. See this file's docstring, "
          "backtest/2026-09-11-round12-sweep-results.md, and "
          "backtest/2026-09-12-xrank-fails-the-holdout-do-not-switch.md.")


if __name__ == "__main__":
    main()
