"""
Score cache -- run the walk-forward once per SIGNAL config, keep everything.

Round 12 (2026-09-09).

The observation this is built on
-------------------------------
`continuous_walkforward_pit.run_walkforward()` trains a model at every
timepoint, scores the whole eligible cross-section, and then throws away all
but the top 5. Every question about top-N breadth, weighting, stops, costs,
entry timing, rebalance frequency and neutralization is answerable from the
scores it already computed and discarded.

So: split the sweep in two. This module runs the expensive half -- the part
that actually needs a retrain -- and writes the FULL score vector per
timepoint. `sweep/portfolio.py` then sweeps every construction parameter over
that cache in seconds instead of hours.

What counts as expensive (needs a run here):
    feature set, label horizon, label design, model family and
    hyperparameters, training-window shape, training cap, candidate universe

What is free (handled downstream):
    top-N, weighting, vol-targeting, stop level, cost, entry timing,
    rebalance frequency, sector/vol-bucket neutralization

Reuse, not restatement
----------------------
Feature definitions, panel loading, the point-in-time universe and the
eligibility rules are IMPORTED from the existing modules, never recopied --
DATA-PIPELINE-HANDOFF.md section 6.4. A difference between a sweep cell and the
production baseline must be attributable to the config, not to two copies of a
rule drifting apart. `sweep/verify.py` enforces that by reproducing the known
production number through this code path.
"""

import gc
import json
import os
import time
from pathlib import Path

import numpy as np
import pandas as pd
import xgboost as xgb

import continuous_walkforward_pit as W
from features import (FEATURE_COLS, DATA_DIR, OUT_DIR,
                      LABEL_COL, TRADABLE_LABEL_COL)
from fundamentals_features_beta import FUNDAMENTAL_FEATURE_COLS

CACHE_DIR = OUT_DIR / "sweep" / "scores"

# Feature-set definitions. Named so a cell is self-describing in the results
# table. "novol" exists to test the B6 finding directly: the gates recorded
# that dropping the top volatility decile removes 63% of the effect, and
# volatility_60 alone is 60.3% of XGBoost's importance. If the model is a
# volatility bet in a trenchcoat, removing those two columns should collapse it.
_VOL_COLS = ("volatility_20", "volatility_60")
_NO_STALE = [c for c in FUNDAMENTAL_FEATURE_COLS if c != "fundamentals_age_days"]

# Round 14: interest-rate sensitivities. Imported rather than restated so the
# screen, the model and the live signal cannot disagree about what the feature
# set is.
try:
    from sweep.rates import RATE_FEATURE_COLS
except Exception:                                  # rates panel not built yet
    RATE_FEATURE_COLS = []
_RATE_ALL = list(RATE_FEATURE_COLS) + (["d_y10_20"] if RATE_FEATURE_COLS else [])

FEATURE_SETS = {
    "price":      list(FEATURE_COLS),
    "price_fund": list(FEATURE_COLS) + list(_NO_STALE),
    "novol":      [c for c in FEATURE_COLS if c not in _VOL_COLS],
    "volonly":    list(_VOL_COLS),
    # Round 14. "rates" screens ONLY the new columns, so the multiple-testing
    # family is the 5 new hypotheses rather than a re-test of the 24 already
    # known to be dead. "price_fund_rates" is the combined set for modelling.
    "rates":            list(_RATE_ALL),
    "price_fund_rates": list(FEATURE_COLS) + list(_NO_STALE) + list(_RATE_ALL),
}

# Which panel each feature set needs.
PANEL_FOR = {
    "price":      "features_sharadar_pit.parquet",
    "novol":      "features_sharadar_pit.parquet",
    "volonly":    "features_sharadar_pit.parquet",
    "price_fund": "features_with_fundamentals_sharadar_pit.parquet",
    "rates":            "features_with_rates_sharadar_pit.parquet",
    "price_fund_rates": "features_with_rates_sharadar_pit.parquet",
}

# Extra columns carried into the score cache so the portfolio layer can weight,
# bucket and neutralize without reloading the panel.
CARRY_COLS = ("close", "market_cap", "volatility_20", "volatility_60")


# ==========================================================================
# Config
# ==========================================================================
class SignalConfig(dict):
    """One expensive cell. A plain dict with a stable id and defaults."""

    DEFAULTS = {
        "features": "price_fund",   # key into FEATURE_SETS
        "horizon": 40,              # label / hold horizon in trading days
        "label": "q75",             # q75 | q90 | q60 | raw | xrank | volresid
        "label_basis": "tradable",  # tradable | as_published
        "model": "xgb",             # xgb | xgb_reg | ridge | feat:<col> | feat:-<col>
        "depth": 3,
        "eta": 0.1,
        "rounds": 100,
        "train": "expanding",       # expanding | roll5 | roll8 | roll10
        "train_cap": 0,             # 0 = uncapped; else keep the most recent K rows
        "universe": "pit",          # pit | sp500
        "cap_tier": "all",          # all | mega | large | mid  (market-cap tercile)
        "step": 40,                 # rebalance frequency in trading days
        "seed": 0,
    }

    def __init__(self, **kw):
        bad = set(kw) - set(self.DEFAULTS)
        if bad:
            raise ValueError(f"unknown SignalConfig keys: {sorted(bad)}")
        super().__init__({**self.DEFAULTS, **kw})

    @property
    def id(self):
        """Deterministic, filesystem-safe, human-readable cell id."""
        d = self
        parts = [
            d["features"], f"h{d['horizon']}", d["label"],
            "trd" if d["label_basis"] == "tradable" else "pub",
            d["model"].replace(":", "").replace("-", "neg"),
        ]
        if d["model"].startswith("xgb"):
            parts.append(f"d{d['depth']}e{str(d['eta']).replace('.', '')}r{d['rounds']}")
        parts += [d["train"]]
        if d["train_cap"]:
            parts.append(f"cap{d['train_cap'] // 1000}k")
        parts += [d["universe"]]
        if d["cap_tier"] != "all":
            parts.append(d["cap_tier"])
        parts.append(f"s{d['step']}")
        return "_".join(parts)

    @property
    def group(self):
        """Cells sharing a group can share one panel load -- which is the
        expensive part of setup. The runner batches on this."""
        return (PANEL_FOR[self["features"]], self["horizon"])


# ==========================================================================
# Panel context -- loaded once per (panel, horizon) group
# ==========================================================================
class PanelContext:
    def __init__(self, panel_file, horizon, universe="pit", verbose=True):
        self.panel_file = panel_file
        self.horizon = horizon
        self.universe = universe
        path = OUT_DIR / panel_file
        if not path.exists():
            raise FileNotFoundError(f"{path} not found")

        # Ask for every feature column any config in this group might use, so
        # one load serves all of them.
        want = list(dict.fromkeys(
            ["close", "open", "market_cap"] + list(FEATURE_COLS) + list(_NO_STALE)
            + list(_RATE_ALL)))
        t0 = time.time()
        if verbose:
            print(f"  [ctx] loading {panel_file} at horizon {horizon} ...", flush=True)
        # filter_cols = FEATURE_COLS only: a row is kept when the PRICE features
        # are complete, matching the production path exactly. Fundamental
        # columns may be NaN and XGBoost handles that natively.
        feat, n_before = W.load_panel_prepared(path, want, list(FEATURE_COLS), horizon)
        if verbose:
            print(f"  [ctx] {len(feat):,} of {n_before:,} rows carry complete "
                  f"price features ({time.time() - t0:.0f}s)", flush=True)

        self._mm_cache = {}
        self._mm_dir = None
        self.label_pub = LABEL_COL
        self.label_trd = TRADABLE_LABEL_COL
        self.feat = feat
        self.all_dates = pd.Series(sorted(feat["date"].unique()))

        # Universe machinery, straight from the production module.
        self.current_universe = set(feat["ticker"].cat.categories.tolist())
        self.gap_earliest = W.load_gap_ticker_set()
        self.pit_map = W.load_pit_universe()

        # Derived label variants, computed ONCE for the whole group.
        self._derive_labels()

        # Price panel for realized execution, segment-aware exactly as the
        # production run builds it.
        b = feat.groupby("ticker", observed=True)["date"].agg(["min", "max"])
        segments = {t: (str(t).split("__post")[0], r["min"], r["max"])
                    for t, r in b.iterrows()}
        from execution import SegmentedOHLCPanel
        self.price_panel = SegmentedOHLCPanel(W.price_dirs_for(universe), segments)
        del b
        gc.collect()

    def _derive_labels(self):
        """Precompute the label variants that need a pass over the panel."""
        f = self.feat
        for basis, col in (("tradable", self.label_trd),
                           ("as_published", self.label_pub)):
            if col not in f.columns:
                continue
            y = f[col].to_numpy(np.float32)

            # xrank: within-date cross-sectional percentile rank. Strips the
            # market-timing component out of the target entirely -- what is
            # left is purely "did this name beat its peers that day", which is
            # the only thing a cross-sectional selector can act on.
            g = pd.Series(y).groupby(f["date"].values)
            f[f"_xrank_{basis}"] = g.rank(pct=True).to_numpy(np.float32)

            # volresid: return scaled by trailing volatility. Targets
            # risk-adjusted outperformance rather than raw magnitude, which is
            # the obvious counter to a model that has repeatedly been shown to
            # just find the most volatile names.
            v = f["volatility_20"].to_numpy(np.float32)
            with np.errstate(divide="ignore", invalid="ignore"):
                f[f"_volresid_{basis}"] = np.where(v > 1e-8, y / v, np.nan).astype(np.float32)
        gc.collect()

    def featmat(self, feature_cols):
        """Memmapped float32 matrix for one feature set, built once per
        context and reused by every cell in the group.

        Spilled to scratch rather than held resident: it is ~1GB, it is needed
        for the whole run, and keeping it in RAM alongside XGBoost's own
        structures is what pinned peak RSS at the ceiling before Round 9 made
        the same change in the production walk-forward.
        """
        key = tuple(feature_cols)
        if key in self._mm_cache:
            return self._mm_cache[key]
        import atexit
        import shutil
        import tempfile
        if self._mm_dir is None:
            self._mm_dir = tempfile.mkdtemp(prefix="sweep_featmat_")
            atexit.register(lambda d=self._mm_dir: shutil.rmtree(d, ignore_errors=True))
        path = os.path.join(self._mm_dir, f"fm{len(self._mm_cache)}.npy")
        arr = np.ascontiguousarray(
            self.feat[list(feature_cols)].to_numpy(np.float32, copy=False))
        shape = arr.shape
        mm = np.memmap(path, dtype=np.float32, mode="w+", shape=shape)
        mm[:] = arr
        mm.flush()
        del arr, mm
        gc.collect()
        out = np.memmap(path, dtype=np.float32, mode="r", shape=shape)
        self._mm_cache[key] = out
        return out

    def target(self, cfg):
        """Return the continuous target array for a config."""
        basis = cfg["label_basis"]
        base = self.label_trd if basis == "tradable" else self.label_pub
        kind = cfg["label"]
        if kind in ("q60", "q75", "q90", "raw"):
            return self.feat[base].to_numpy(np.float32)
        if kind == "xrank":
            return self.feat[f"_xrank_{basis}"].to_numpy(np.float32)
        if kind == "volresid":
            return self.feat[f"_volresid_{basis}"].to_numpy(np.float32)
        raise ValueError(f"unknown label {kind}")


# ==========================================================================
# The run
# ==========================================================================
def _train_lo(dates_arr, hi, cfg, all_dates):
    """Start index of the training block -- 0 for expanding, else a rolling
    window of N years ending at the cutoff."""
    if cfg["train"] == "expanding":
        return 0
    years = int(cfg["train"].replace("roll", ""))
    cutoff = dates_arr[hi - 1] if hi > 0 else dates_arr[0]
    start = cutoff - np.timedelta64(365 * years, "D")
    return int(np.searchsorted(dates_arr, start, "left"))


def _fit_predict(cfg, featmat, y_full, hi, mask, X_te, seed, n_sel):
    """Train one model and score the cross-section.

    The training block is NEVER materialized. `mask` is a boolean over
    [0, hi) selecting the training rows, and W._ChunkIter streams fixed-size
    chunks into XGBoost, so peak memory is one chunk regardless of how much
    history has accumulated. This is not a micro-optimization: the production
    walk-forward was OOM-killed around step 62 before Round 9 made exactly
    this change, and the sweep's expanding window is the same shape.

    Single-threaded for determinism -- Gate A3 recorded that non-deterministic
    parallel histogram accumulation was what made two identical runs disagree.
    """
    model = cfg["model"]

    if model == "ridge":
        from sweep import _num
        # Ridge on 24 features needs a 24x24 normal equation, not 11M rows.
        # Subsampling to 2M is statistically indistinguishable here and keeps
        # this path from being the one that blows the memory ceiling.
        sel = np.flatnonzero(mask)
        if len(sel) > 2_000_000:
            sel = sel[np.linspace(0, len(sel) - 1, 2_000_000).astype(np.int64)]
        return _num.ridge_fit_predict(np.asarray(featmat[sel]), y_full[sel],
                                      X_te, alpha=1.0), {}

    params = {"max_depth": int(cfg["depth"]), "eta": float(cfg["eta"]),
              "tree_method": "hist", "verbosity": 0, "nthread": 1,
              "seed": int(seed)}
    if model == "xgb":
        params.update({"objective": "binary:logistic", "eval_metric": "logloss"})
    elif model == "xgb_reg":
        params.update({"objective": "reg:squarederror", "eval_metric": "rmse"})
    else:
        raise ValueError(f"unknown model {model}")

    dtr = xgb.QuantileDMatrix(W._ChunkIter(featmat, y_full, hi, mask=mask),
                              max_bin=256)
    booster = xgb.train(params, dtr, num_boost_round=int(cfg["rounds"]))
    del dtr
    gc.collect()
    score = booster.inplace_predict(np.asarray(X_te)).astype(np.float32)
    imp = booster.get_score(importance_type="gain")
    del booster
    gc.collect()
    return score, imp


def run_signal(cfg, ctx, start="2007-01-02", verbose=True, checkpoint=None):
    """Run one signal config across the walk-forward, returning the full
    per-timepoint score cross-section.

    Returns (scores_df, meta). scores_df columns:
        timepoint, ticker, score, close, market_cap, volatility_20/60
    """
    cfg = SignalConfig(**cfg) if not isinstance(cfg, SignalConfig) else cfg
    feature_cols = [c for c in FEATURE_SETS[cfg["features"]]
                    if c in ctx.feat.columns]
    if not feature_cols:
        raise ValueError(f"no feature columns available for {cfg['features']}")

    f = ctx.feat
    dates_arr = f["date"].values
    horizon = int(cfg["horizon"])
    step = int(cfg["step"])
    step_dates = W.build_step_dates(ctx.all_dates, start, step)
    if not step_dates:
        return pd.DataFrame(), {"error": "no step dates"}

    y_all = ctx.target(cfg)
    featmat = ctx.featmat(feature_cols)

    carry = [c for c in CARRY_COLS if c in f.columns]
    frame = f[["ticker", "date"] + carry]

    # A feature model needs no training at all -- it IS the score. Kept in the
    # same code path so it faces the identical universe, eligibility screen and
    # timepoint grid as every trained cell. This is the control that answers
    # "is the ML contributing anything over ranking on one column".
    feat_model = None
    if cfg["model"].startswith("feat:"):
        spec = cfg["model"][5:]
        sign = -1.0 if spec.startswith("-") else 1.0
        name = spec.lstrip("-")
        if name not in f.columns:
            raise ValueError(f"feature model column {name} not in panel")
        feat_model = (sign, f[name].to_numpy(np.float32))

    rows = []
    done = set()
    if checkpoint and Path(checkpoint).exists():
        prev = pd.read_parquet(checkpoint)
        rows.append(prev)
        done = set(prev["timepoint"].astype("datetime64[ns]").unique())

    t0 = time.time()
    n_skipped = 0
    for n, tp in enumerate(step_dates, 1):
        if np.datetime64(tp) in done:
            continue
        idx = ctx.all_dates[ctx.all_dates == tp].index[0]
        if idx < horizon:
            continue
        cutoff = ctx.all_dates.iloc[idx - horizon]
        hi = int(np.searchsorted(dates_arr, np.datetime64(cutoff), "right"))
        lo = _train_lo(dates_arr, hi, cfg, ctx.all_dates)

        allowed = W.allowed_universe_at(tp, ctx.current_universe, ctx.gap_earliest,
                                        cfg["universe"], ctx.pit_map)

        te_lo = int(np.searchsorted(dates_arr, np.datetime64(tp), "left"))
        te_hi = int(np.searchsorted(dates_arr, np.datetime64(tp), "right"))
        test = frame.iloc[te_lo:te_hi]
        pos = np.arange(te_lo, te_hi)
        sel = test["ticker"].isin(allowed).values
        test, pos = test[sel], pos[sel]

        # Market-cap tier, applied point-in-time within the eligible pool.
        if cfg["cap_tier"] != "all" and "market_cap" in test.columns:
            mc = test["market_cap"].to_numpy(np.float64)
            ok = np.isfinite(mc)
            if ok.sum() >= 30:
                q1, q2 = np.nanpercentile(mc[ok], [33.3, 66.7])
                keep = {"mid": mc <= q1, "large": (mc > q1) & (mc <= q2),
                        "mega": mc > q2}[cfg["cap_tier"]]
                test, pos = test[keep], pos[keep]

        if len(test) < 20:
            n_skipped += 1
            continue

        if feat_model is not None:
            sign, col = feat_model
            score = (sign * col[pos]).astype(np.float32)
            imp = {}
        else:
            # Training-row selection as a MASK over [0, hi), never as an
            # index copy. Rolling windows and the training cap are both
            # expressed by switching bits off, so nothing is materialized.
            lab = y_all[:hi]
            mask = np.isfinite(lab)
            if lo > 0:
                mask[:lo] = False
            n_sel = int(mask.sum())
            if n_sel < 300:
                n_skipped += 1
                continue
            if cfg["train_cap"] and n_sel > int(cfg["train_cap"]):
                sel = np.flatnonzero(mask)
                mask[sel[:-int(cfg["train_cap"])]] = False
                n_sel = int(cfg["train_cap"])
                del sel

            kind = cfg["label"]
            if kind in ("q60", "q75", "q90"):
                pct = {"q60": 60, "q75": 75, "q90": 90}[kind]
                cut = float(np.percentile(lab[mask], pct))
                y_full = (lab > cut).astype(np.float32)
            else:
                y_full = np.nan_to_num(lab, nan=0.0, posinf=0.0,
                                       neginf=0.0).astype(np.float32)

            score, imp = _fit_predict(cfg, featmat, y_full, hi, mask,
                                      featmat[pos], cfg["seed"], n_sel)
            del y_full, lab, mask
            gc.collect()

        rec = pd.DataFrame({
            "timepoint": np.repeat(np.datetime64(tp), len(test)),
            "ticker": test["ticker"].astype(str).values,
            "score": score,
        })
        for c in carry:
            rec[c] = test[c].to_numpy(np.float32)
        rows.append(rec)

        if verbose and (n % 10 == 0 or n == 1):
            el = time.time() - t0
            print(f"    [{cfg.id}] step {n}/{len(step_dates)} {tp.date()} "
                  f"({len(test)} scored, {el:.0f}s elapsed)", flush=True)
            if checkpoint:
                pd.concat(rows, ignore_index=True).to_parquet(checkpoint, index=False)

    if not rows:
        return pd.DataFrame(), {"error": "no windows produced"}

    out = pd.concat(rows, ignore_index=True)
    meta = {
        "cell_id": cfg.id,
        "config": dict(cfg),
        "n_timepoints": int(out["timepoint"].nunique()),
        "n_rows": int(len(out)),
        "n_skipped": n_skipped,
        "feature_cols": feature_cols,
        "elapsed_sec": round(time.time() - t0, 1),
        "last_importances": imp if isinstance(imp, dict) else {},
    }
    return out, meta


def cache_path(cell_id):
    CACHE_DIR.mkdir(parents=True, exist_ok=True)
    return CACHE_DIR / f"{cell_id}.parquet"


def meta_path(cell_id):
    CACHE_DIR.mkdir(parents=True, exist_ok=True)
    return CACHE_DIR / f"{cell_id}.json"


def have(cell_id):
    return cache_path(cell_id).exists() and meta_path(cell_id).exists()


def save(scores, meta):
    scores.to_parquet(cache_path(meta["cell_id"]), index=False)
    with open(meta_path(meta["cell_id"]), "w") as fh:
        json.dump(meta, fh, indent=2, default=str)
