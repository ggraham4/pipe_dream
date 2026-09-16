"""
Build the app's two-model comparison artifact.

Round 18 (2026-09-16). Produces out/app_model_comparison.json: window-by-window
equity curves and summary statistics for

    q75    the deployed signal      (primary)
    xrank  the tracked candidate    (NOT acted on -- it lost on the hold-out)
    SPY    the benchmark every number in this project is quoted against
    USMV   iShares MSCI USA Min Vol

USMV is here for a specific reason, not for decoration. Round 18's attribution
showed that what the deployed model demonstrably owns is a LOW-VOLATILITY TILT
(score-vs-volatility correlation -0.134, and 88% of the volatility-bucketed
construction's edge is higher arithmetic return rather than reduced variance
drag) plus a tech/healthcare sector bet. Both of those are purchasable for an
expense ratio. USMV on the chart is the honest question put in front of the
model every time it is opened: is this beating the thing it is a complicated
way of being?

    python3 build_app_benchmarks.py

--------------------------------------------------------------------------
ON THE HOLD-OUT
--------------------------------------------------------------------------
This script evaluates 2020-2026, which every other command in the sweep
package refuses to touch. That is deliberate and it is NOT a loophole:

  * The cell list is HARD-CODED to the two configurations already chosen. You
    cannot pass a grid, a glob, or a cell id. There is nothing here to select
    over, and a report over a fixed set of two is not a search.
  * Both hold-out numbers are already spent and already published --
    q75 at +7.33%/yr (Round 13's one legitimate confirmation) and xrank at
    -4.28%/yr (Round 18). Re-plotting a number that has already been paid for
    costs nothing further.
  * What it must never become: a way to re-rank candidates on 2020-2026. If
    you find yourself adding a third cell here to see how it does, stop. That
    is the search this file is shaped to prevent.

The rule stands: nothing new may be confirmed on 2020-2026. New candidates are
nominated on 2007-2019 and confirmed only on data that does not exist yet.

--------------------------------------------------------------------------
WHAT THE CURVES ARE, PRECISELY
--------------------------------------------------------------------------
Non-overlapping 40-trading-day windows. Each window: select the top-scoring
name in each of 5 trailing-volatility quintiles, weight by inverse volatility,
enter at the next open, exit at the close 40 trading days later, charge 15bp
against turnover. Benchmarks use the identical entry/exit convention
(portfolio.spy_windows), so the comparison is like-for-like.

Both sides are PRICE returns. The panel's prices are split-adjusted but not
dividend-adjusted, and SPY.csv is a raw price series, so neither the model nor
the benchmarks are credited with dividends. That understates SPY (~1.8%/yr)
and USMV (~1.9%/yr) against a model whose own picks are likewise uncredited;
the excess figures are therefore roughly comparable, but they are not total
returns and must not be described as such.
"""
import json
import sys
from pathlib import Path

import numpy as np
import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parent))

from features import OUT_DIR                              # noqa: E402
from sweep import portfolio as P                          # noqa: E402

SWEEP_DIR = OUT_DIR / "sweep"
OUTCOMES_PATH = SWEEP_DIR / "outcomes.parquet"
# Deliberately NOT `from sweep import scorecache`. That module imports xgboost
# at module scope, and nothing here trains anything -- this script reads cached
# scores and compounds them. Keeping the training stack out of its import graph
# means the app's chart can be rebuilt on a machine that cannot fit xgboost.
SCORES_DIR = SWEEP_DIR / "scores"
SPY_CSV = Path(__file__).resolve().parents[1] / "scripts" / "td_data_local" / "SPY.csv"
BENCH_DIR = Path(__file__).resolve().parents[1] / "data" / "benchmarks"
DST = OUT_DIR / "app_model_comparison.json"

ERAS = {
    "nominate": ("2007-01-01", "2020-01-01"),
    "holdout": ("2020-01-01", "2027-01-01"),
}

# The LIVE construction. These must equal current_signal_pit.py's constants.
LIVE = dict(top_n=5, weighting="invvol", bucket="volq")
COST_BPS = 15.0
HORIZON = 40

# HARD-CODED. See the header -- this list is the reason this script is safe to
# point at the hold-out, so it does not come from a file or an argument.
CELLS = [
    {"key": "q75", "role": "primary",
     "display_name": "Deployed (q75 / classifier)",
     "cell_id": "price_fund_h40_q75_trd_xgb_d3e01r100_expanding_cap500k_pit_s40"},
    {"key": "xrank", "role": "candidate",
     "display_name": "Candidate (xrank / regressor)",
     "cell_id": "price_fund_h40_xrank_trd_xgb_reg_d3e01r100_expanding_cap500k_pit_s40"},
]

BENCHMARKS = [
    {"key": "spy", "display_name": "SPY", "symbol": "SPY",
     "note": "The benchmark every number in this project is quoted against."},
    {"key": "usmv", "display_name": "USMV (min-vol ETF)", "symbol": "USMV",
     "note": ("iShares MSCI USA Min Vol. On the chart because the model's "
              "identified edge is a low-volatility tilt, which this buys for "
              "an expense ratio. Inception 2011-10-18, so it is absent from "
              "the early part of the 2007-2019 span.")},
]


# --------------------------------------------------------------------------
# benchmark price series
# --------------------------------------------------------------------------
def _load_spy():
    if not SPY_CSV.exists():
        raise SystemExit(f"{SPY_CSV} not found -- run scripts/local_data_pull.py first.")
    return pd.read_csv(SPY_CSV, parse_dates=["date"])


def _load_benchmark(symbol):
    """Cached daily OHLC for a benchmark ETF.

    SPY already lives in scripts/td_data_local/. Anything else is cached under
    data/benchmarks/ and pulled once via yfinance if missing. A failed pull is
    NOT fatal: the artifact records the benchmark as unavailable and the app
    draws the chart without that line, which is the honest outcome. Silently
    substituting a different series, or dropping the line without saying so,
    would be worse than the missing line.
    """
    if symbol == "SPY":
        return _load_spy(), None
    BENCH_DIR.mkdir(parents=True, exist_ok=True)
    cache = BENCH_DIR / f"{symbol}.csv"
    if cache.exists():
        return pd.read_csv(cache, parse_dates=["date"]), None
    try:
        import yfinance as yf
    except ImportError:
        return None, ("yfinance is not installed in this environment, so "
                      f"{symbol} could not be pulled.")
    try:
        h = yf.Ticker(symbol).history(period="max", auto_adjust=False)
    except Exception as e:                                   # network, rate limit
        return None, f"{symbol} pull failed: {type(e).__name__}: {e}"
    if h is None or h.empty:
        return None, f"{symbol} pull returned no rows."
    df = (h.reset_index()[["Date", "Open", "High", "Low", "Close", "Volume"]]
          .rename(columns={"Date": "date", "Open": "open", "High": "high",
                           "Low": "low", "Close": "close", "Volume": "volume"}))
    df["date"] = pd.to_datetime(df["date"]).dt.tz_localize(None)
    df.to_csv(cache, index=False)
    print(f"  pulled {symbol}: {len(df):,} rows "
          f"{df['date'].min().date()} .. {df['date'].max().date()} -> {cache}")
    return df, None


# --------------------------------------------------------------------------
# curve + summary
# --------------------------------------------------------------------------
def _curve(timepoints, rets):
    """Compounded value of $1 across the windows, as [{timepoint, value}]."""
    out, v = [], 1.0
    for tp, r in zip(timepoints, rets):
        v *= (1.0 + float(r))
        out.append({"timepoint": str(pd.Timestamp(tp).date()), "value": round(v, 6)})
    return out


def _summary(rets, spy_rets, horizon, first_tp, last_tp):
    r = np.asarray(rets, dtype=np.float64)
    b = np.asarray(spy_rets, dtype=np.float64)
    n = len(r)
    if n == 0:
        return None
    span_days = (pd.Timestamp(last_tp) - pd.Timestamp(first_tp)).days + horizon * 1.4523
    years = max(span_days / 365.25, 1e-6)

    def ann(m):
        return m ** (1.0 / years) - 1.0 if m > 0 else -1.0

    mult = float(np.prod(1.0 + r))
    bmult = float(np.prod(1.0 + b)) if len(b) == n else np.nan
    eq = np.cumprod(1.0 + r)
    dd = float(np.min(eq / np.maximum.accumulate(eq)) - 1.0)
    return {
        "n_windows": n,
        "years": round(years, 2),
        "mult": round(mult, 4),
        "cagr_pct": round(ann(mult) * 100, 2),
        "excess_cagr_pct": (round((ann(mult) - ann(bmult)) * 100, 2)
                            if np.isfinite(bmult) else None),
        "mult_vs_spy": (round(mult / bmult, 4)
                        if np.isfinite(bmult) and bmult > 0 else None),
        "max_drawdown_pct": round(dd * 100, 2),
        "win_rate_vs_spy": (round(float(np.mean(r > b)), 4)
                            if len(b) == n else None),
        "first_window": str(pd.Timestamp(first_tp).date()),
        "last_window": str(pd.Timestamp(last_tp).date()),
    }


def main():
    if not OUTCOMES_PATH.exists():
        raise SystemExit(f"{OUTCOMES_PATH} not found -- build it with "
                          f"`python3 -m sweep.cli outcomes` first.")
    tab = pd.read_parquet(OUTCOMES_PATH)
    tab["ticker"] = tab["ticker"].astype(str)

    print("benchmarks:")
    bench_px, bench_err = {}, {}
    for b in BENCHMARKS:
        df, err = _load_benchmark(b["symbol"])
        bench_px[b["key"]] = df
        bench_err[b["key"]] = err
        print(f"  {b['symbol']:<6} " + (f"UNAVAILABLE -- {err}" if err else
              f"{len(df):,} rows {df['date'].min().date()} .. {df['date'].max().date()}"))
    if bench_px["spy"] is None:
        raise SystemExit("SPY is required and could not be loaded.")

    # Per-window model returns, once, for the whole cached span.
    model_windows = {}
    for c in CELLS:
        path = SCORES_DIR / f"{c['cell_id']}.parquet"
        if not path.exists():
            raise SystemExit(
                f"score cache missing for {c['key']}: {path}\n"
                f"Build it with `python3 -m sweep.cli scores --cells <grid>`.")
        scores = pd.read_parquet(path)
        prep = P.Prepared(scores, tab, HORIZON, None)
        pw = P.simulate(prep, horizon=HORIZON, cost_bps=COST_BPS, **LIVE)
        if pw["sleeve"].nunique() != 1:
            # With a 40-day horizon on a 40-day pick grid there is exactly one
            # sleeve. If that ever changes, averaging across sleeves per date
            # is the right collapse -- but fail loudly rather than quietly
            # plotting one sleeve of several as if it were the book.
            raise SystemExit(
                f"{c['key']}: expected 1 sleeve, got {pw['sleeve'].nunique()}. "
                f"The curve code below assumes a single sleeve.")
        model_windows[c["key"]] = (pw.sort_values("timepoint")
                                     .set_index("timepoint")["net"])
        print(f"{c['key']:<6} simulated {len(pw)} windows "
              f"{pw['timepoint'].min().date()} .. {pw['timepoint'].max().date()}")

    out = {
        "generated_from": "final/src/build_app_benchmarks.py",
        "construction": {"top_n": LIVE["top_n"], "weighting": LIVE["weighting"],
                          "bucket": LIVE["bucket"], "horizon_trading_days": HORIZON,
                          "cost_bps": COST_BPS, "entry": "next open",
                          "returns": "price only, no dividends on either side"},
        "cells": {c["key"]: {k: c[k] for k in ("role", "display_name", "cell_id")}
                  for c in CELLS},
        "benchmarks": {b["key"]: {"display_name": b["display_name"],
                                   "symbol": b["symbol"], "note": b["note"],
                                   "unavailable_reason": bench_err[b["key"]]}
                       for b in BENCHMARKS},
        "eras": {},
    }

    for era_name, (lo, hi) in ERAS.items():
        # The window grid is the PRIMARY model's -- both cells were scored on
        # the same step dates, but pinning it to one of them means the curves
        # are plotted against an identical x-axis even if a cache is ever
        # rebuilt with a different step.
        s = model_windows["q75"]
        tps = [t for t in s.index
               if pd.Timestamp(lo) <= pd.Timestamp(t) < pd.Timestamp(hi)]
        if not tps:
            continue

        bench_ret = {}
        for b in BENCHMARKS:
            df = bench_px[b["key"]]
            bench_ret[b["key"]] = (P.spy_windows(df, np.array(tps), HORIZON)
                                   if df is not None else pd.Series(dtype=float))

        # A window is only comparable if SPY has it. Windows SPY cannot price
        # are dropped from every series together, so no series gets an x-axis
        # the others do not have.
        tps = [t for t in tps if pd.Timestamp(t) in bench_ret["spy"].index]
        spy_r = [float(bench_ret["spy"][pd.Timestamp(t)]) for t in tps]

        curves, summaries = {}, {}
        for c in CELLS:
            ser = model_windows[c["key"]]
            r = [float(ser[t]) if t in ser.index else np.nan for t in tps]
            if any(not np.isfinite(v) for v in r):
                missing = sum(1 for v in r if not np.isfinite(v))
                raise SystemExit(
                    f"{c['key']} is missing {missing} of {len(tps)} windows in "
                    f"{era_name}. The two cells must span the same windows or "
                    f"the curves are not comparable -- rebuild the cache.")
            curves[c["key"]] = _curve(tps, r)
            summaries[c["key"]] = _summary(r, spy_r, HORIZON, tps[0], tps[-1])

        for b in BENCHMARKS:
            got = bench_ret[b["key"]]
            have = [t for t in tps if pd.Timestamp(t) in got.index]
            if not have:
                continue
            r = [float(got[pd.Timestamp(t)]) for t in have]
            # USMV starts mid-span; its curve is rebased to $1 at ITS first
            # window and the summary says so, rather than being back-filled
            # with SPY or silently plotted from a different base.
            curves[b["key"]] = _curve(have, r)
            sr = [float(bench_ret["spy"][pd.Timestamp(t)]) for t in have]
            summ = _summary(r, sr, HORIZON, have[0], have[-1])
            summ["covers_full_era"] = (len(have) == len(tps))
            summ["rebased_at"] = str(pd.Timestamp(have[0]).date())
            summaries[b["key"]] = summ

        out["eras"][era_name] = {
            "span": [lo, hi], "n_windows": len(tps),
            "first_window": str(pd.Timestamp(tps[0]).date()),
            "last_window": str(pd.Timestamp(tps[-1]).date()),
            "curves": curves, "summary": summaries,
        }
        print(f"\n--- {era_name} ({len(tps)} windows) ---")
        for k, v in summaries.items():
            if v is None:
                continue
            ex = f"{v['excess_cagr_pct']:+6.2f}" if v["excess_cagr_pct"] is not None else "   n/a"
            print(f"  {k:<6} mult {v['mult']:7.3f}  CAGR {v['cagr_pct']:+6.2f}%  "
                  f"excess {ex}%/yr  maxDD {v['max_drawdown_pct']:+7.2f}%"
                  + ("" if v.get("covers_full_era", True) else "   [partial span]"))

    # The noise scale, if Round 18's live ranking is on disk. Without it a
    # reader sees two curves and no sense of how far apart two runs of the
    # SAME idea land, which is the single most important context for reading
    # the gap between them.
    live = SWEEP_DIR / "live_nominate.csv"
    if live.exists():
        d = pd.read_csv(live)
        # model == "xgb" matters: live_nominate.csv also carries single-feature
        # `feat:*` pseudo-models on the same features/label, and those are a
        # different idea, not a knob turned. Including them would inflate the
        # spread and make the noise band look worse than it is.
        fam = d[(d["features"] == "price_fund") & (d["label"] == "q75")
                & (d["model"] == "xgb")]
        if len(fam) >= 3:
            out["noise_scale"] = {
                "source": "out/sweep/live_nominate.csv",
                "family": ("price_fund / q75 / xgb -- same features, same label, "
                           "same model; only the training window, training cap, "
                           "tree depth, market-cap tier and label basis differ"),
                "n_cells": int(len(fam)),
                "excess_cagr_pct_min": round(float(fam["excess_cagr"].min()), 2),
                "excess_cagr_pct_max": round(float(fam["excess_cagr"].max()), 2),
                "excess_cagr_pct_mean": round(float(fam["excess_cagr"].mean()), 2),
                "excess_cagr_pct_sd": round(float(fam["excess_cagr"].std(ddof=1)), 2),
                "note": ("Cells nobody would call a different idea -- the same "
                         "model on the same features and label, with a knob "
                         "turned. The spread here is the scale of noise in a "
                         "single number out of this pipeline. A gap between two "
                         "curves smaller than this is not evidence of anything, "
                         "including the gap between the two models plotted above."),
            }
            ns = out["noise_scale"]
            print(f"\nnoise scale ({ns['n_cells']} same-idea variants): "
                  f"{ns['excess_cagr_pct_min']:+.2f} .. {ns['excess_cagr_pct_max']:+.2f} "
                  f"%/yr, sd {ns['excess_cagr_pct_sd']:.2f}")

    DST.write_text(json.dumps(out, indent=2))
    print(f"\nwritten {DST}")


if __name__ == "__main__":
    main()
