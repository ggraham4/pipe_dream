"""
Realized-outcomes table -- the thing that makes a wide sweep affordable.

Round 12 (2026-09-09).

Why this exists
---------------
`execution.realize_position()` is the authority on what a position actually
returned. It is also a per-(ticker, timepoint, horizon, stop) Python call over
a pandas slice. The sweep needs outcomes for EVERY eligible candidate (~1,400
per date) rather than the top 5, at 4 horizons and 9 stop levels, across ~490
pick dates. That is ~25 million realize_position() calls, which is not a thing
that finishes.

So the same arithmetic is done once, vectorized per ticker, and cached. Every
portfolio-construction question -- how many names, how weighted, what stop,
what cost, what rebalance frequency -- then becomes a lookup into this table
instead of a re-run of the walk-forward.

CORRECTNESS IS THE WHOLE POINT. This module reimplements realize_position()'s
arithmetic in array form, which is exactly the kind of second-copy-of-a-formula
that DATA-PIPELINE-HANDOFF.md section 6.4 warns about. It is done anyway
because the vectorization is the entire reason the sweep is feasible -- and it
is defended by `verify_against_reference()`, which checks this table cell-for-
cell against real realize_position() calls on a random sample. That check runs
as a gate, not as an optional extra: if it does not pass, nothing downstream is
allowed to run.

What is stored
--------------
GROSS returns only. Net-of-cost is a deterministic transform of gross:

    net = (1 + gross) * (1 - half) / (1 + half) - 1,   half = cost_bps/2e4

so storing gross makes `cost_bps` a free axis in the portfolio sweep instead
of another dimension of the cache. Turnover-aware costing needs the pick sets,
which only exist downstream, so it is applied there too.

Schema (one row per eligible (timepoint, ticker) pair):

    timepoint     datetime64[ns]   signal date; close[tp] produced the score
    ticker        category
    entry_price   float32          open of the entry bar (tp + entry_lag)
    tradable      bool             False when no bar exists after tp
    g_h{H}_s{S}   float32          gross return, horizon H, stop S (S=000 none)
    st_h{H}_s{S}  bool             stop triggered
    tr_h{H}       bool             series ended inside the window (truncated)
    bh_h{H}       int16            bars actually held
"""

import numpy as np
import pandas as pd


# --------------------------------------------------------------------------
# Grid of horizons and stops the cache is built over. Anything not in here
# cannot be swept without rebuilding the cache, so it is deliberately generous.
# --------------------------------------------------------------------------
HORIZONS = (10, 20, 40, 60)
STOPS = (None, 0.05, 0.08, 0.10, 0.12, 0.15, 0.20, 0.25, 0.30, 0.40)


def _stop_tag(s):
    return "000" if s is None else f"{int(round(s * 100)):03d}"


def col_gross(h, s):
    return f"g_h{h}_s{_stop_tag(s)}"


def col_stopped(h, s):
    return f"st_h{h}_s{_stop_tag(s)}"


def col_trunc(h):
    return f"tr_h{h}"


def col_bars(h):
    return f"bh_h{h}"


def net_from_gross(gross, cost_bps):
    """Apply a round-trip cost in bps to a gross return.

    Mirrors realize_position(): buy at entry*(1 + c/2), sell at exit*(1 - c/2).
    """
    half = (cost_bps / 1e4) / 2.0
    return (1.0 + gross) * (1.0 - half) / (1.0 + half) - 1.0


# --------------------------------------------------------------------------
# Core: one ticker, all timepoints, all (horizon, stop) combinations.
# --------------------------------------------------------------------------
def _ticker_outcomes(dates, o, h, l, c, timepoints, entry_lag, entry_at,
                     horizons, stops):
    """Vectorized realize_position() for one ticker over many signal dates.

    dates/o/h/l/c : that ticker's full OHLC series, ascending by date.
    timepoints    : signal dates to evaluate (np.datetime64[ns], ascending).

    Returns a dict of column-name -> array, each of length len(timepoints).
    Rows where the position was never tradable carry tradable=False and NaN
    returns; the caller decides what that means (it is NOT the same as a
    zero return, and it must not be silently dropped -- an untradable name
    is usually one that stopped existing).
    """
    n = len(dates)
    n_tp = len(timepoints)

    # j = index of the first bar strictly after tp  (future.iloc[0])
    j = np.searchsorted(dates, timepoints, side="right")

    tradable = j < n
    # entry bar index. realize_position: future.iloc[entry_lag - 1]
    e = np.clip(j + (entry_lag - 1), 0, max(n - 1, 0))
    tradable &= (j + (entry_lag - 1)) < n

    if entry_at == "open":
        entry_price = np.where(tradable, o[e], np.nan)
        # exposure starts on the entry bar itself
        first = j + (entry_lag - 1)
    else:
        entry_price = np.where(tradable, c[e], np.nan)
        # entering at the close means exposure starts the FOLLOWING bar
        first = j + entry_lag

    good = tradable & np.isfinite(entry_price) & (entry_price > 0)
    # window must be non-empty
    good &= first < n

    out = {
        "entry_price": entry_price.astype(np.float32),
        "tradable": good,
    }

    for H in horizons:
        # window = bars [first, first+H), clipped to the end of the series
        last = np.minimum(first + H, n)          # exclusive
        bars = np.maximum(last - first, 0)
        trunc = good & (bars < H)

        # ---- no-stop exit: close of the last bar in the window ----
        idx_last = np.clip(last - 1, 0, max(n - 1, 0))
        exit_close = np.where(good & (bars > 0), c[idx_last], np.nan)

        out[col_trunc(H)] = trunc
        out[col_bars(H)] = np.where(good, bars, 0).astype(np.int16)

        # ---- build the (n_tp, H) matrices of low and open over the window ----
        # offsets beyond the end of the series are masked out.
        off = np.arange(H)[None, :]
        pos = first[:, None] + off                       # (n_tp, H)
        valid = (pos < n) & (off < bars[:, None]) & good[:, None]
        pos_c = np.clip(pos, 0, max(n - 1, 0))
        low_w = np.where(valid, l[pos_c], np.inf)        # inf never triggers
        open_w = np.where(valid, o[pos_c], np.nan)

        for S in stops:
            if S is None:
                gross = exit_close / entry_price - 1.0
                out[col_gross(H, S)] = np.where(good, gross, np.nan).astype(np.float32)
                out[col_stopped(H, S)] = np.zeros(n_tp, dtype=bool)
                continue

            stop_price = entry_price * (1.0 - S)          # (n_tp,)
            hit = low_w <= stop_price[:, None]            # (n_tp, H)
            any_hit = hit.any(axis=1)
            k = np.argmax(hit, axis=1)                    # first True; 0 if none

            bar_open = np.take_along_axis(open_w, k[:, None], axis=1).ravel()
            # A bar that opened at or below the stop never offered the trigger
            # price -- the realistic fill is the open. NaN open falls back to
            # the trigger, matching realize_position().
            fill = np.where(np.isfinite(bar_open),
                            np.minimum(stop_price, bar_open),
                            stop_price)

            exit_price = np.where(any_hit, fill, exit_close)
            gross = exit_price / entry_price - 1.0
            out[col_gross(H, S)] = np.where(good, gross, np.nan).astype(np.float32)
            out[col_stopped(H, S)] = good & any_hit

    return out


# --------------------------------------------------------------------------
# Driver
# --------------------------------------------------------------------------
def build_outcomes(price_panel, pairs, entry_lag=1, entry_at="open",
                   horizons=HORIZONS, stops=STOPS, progress_every=250):
    """Build the outcomes table.

    price_panel : dict-like ticker -> OHLC DataFrame (execution.LazyOHLCPanel
                  or SegmentedOHLCPanel -- the SAME object the walk-forward
                  prices positions through, so segmentation is honoured).
    pairs       : DataFrame with columns ['timepoint', 'ticker'] listing every
                  (date, candidate) pair to evaluate.

    Returns a DataFrame in the schema documented at the top of this module.
    """
    pairs = pairs.sort_values(["ticker", "timepoint"]).reset_index(drop=True)
    frames = []
    tickers = pairs["ticker"].unique()

    for i, t in enumerate(tickers, 1):
        if progress_every and (i % progress_every == 0 or i == 1):
            print(f"  outcomes: ticker {i}/{len(tickers)} ({t})", flush=True)
        sub = pairs[pairs["ticker"] == t]
        g = price_panel.get(t)
        tps = sub["timepoint"].to_numpy(dtype="datetime64[ns]")

        if g is None or len(g) == 0:
            # Never tradable -- recorded, not dropped.
            rec = {"entry_price": np.full(len(tps), np.nan, np.float32),
                   "tradable": np.zeros(len(tps), bool)}
            for H in horizons:
                rec[col_trunc(H)] = np.zeros(len(tps), bool)
                rec[col_bars(H)] = np.zeros(len(tps), np.int16)
                for S in stops:
                    rec[col_gross(H, S)] = np.full(len(tps), np.nan, np.float32)
                    rec[col_stopped(H, S)] = np.zeros(len(tps), bool)
        else:
            g = g.sort_values("date")
            rec = _ticker_outcomes(
                g["date"].to_numpy(dtype="datetime64[ns]"),
                g["open"].to_numpy(np.float64),
                g["high"].to_numpy(np.float64),
                g["low"].to_numpy(np.float64),
                g["close"].to_numpy(np.float64),
                tps, entry_lag, entry_at, horizons, stops)

        rec["timepoint"] = tps
        rec["ticker"] = np.repeat(t, len(tps))
        frames.append(pd.DataFrame(rec))

    out = pd.concat(frames, ignore_index=True)
    out["ticker"] = out["ticker"].astype("category")
    return out.sort_values(["timepoint", "ticker"]).reset_index(drop=True)


# --------------------------------------------------------------------------
# The gate. Nothing downstream runs until this passes.
# --------------------------------------------------------------------------
def verify_against_reference(table, price_panel, n_samples=400, seed=0,
                             horizons=HORIZONS, stops=STOPS, atol=1e-6):
    """Check the vectorized table against real realize_position() calls.

    Samples random (timepoint, ticker) rows and, for every (horizon, stop)
    combination, compares the cached gross return and stop flag against what
    execution.realize_position() returns for the same inputs.

    Raises AssertionError on the first disagreement, with enough detail to
    debug it. Returns the number of comparisons made.
    """
    from execution import realize_position

    rng = np.random.default_rng(seed)
    idx = rng.choice(len(table), size=min(n_samples, len(table)), replace=False)
    checked = 0
    mismatches = []

    for i in idx:
        row = table.iloc[int(i)]
        t = str(row["ticker"])
        tp = pd.Timestamp(row["timepoint"])
        g = price_panel.get(t)
        if g is None or len(g) == 0:
            continue
        g = g.sort_values("date").reset_index(drop=True)

        for H in horizons:
            for S in stops:
                ref = realize_position(g, tp, H, entry_lag=1, entry_at="open",
                                       stop_pct=S, cost_bps=0.0)
                got_g = row[col_gross(H, S)]
                got_s = bool(row[col_stopped(H, S)])
                checked += 1

                if ref is None:
                    if bool(row["tradable"]) or np.isfinite(got_g):
                        mismatches.append(
                            (t, tp, H, S, "reference says untradable", got_g))
                    continue

                if not np.isfinite(got_g):
                    mismatches.append((t, tp, H, S, "cached NaN vs "
                                       f"{ref['gross_return']:.8f}", got_g))
                    continue
                if abs(float(got_g) - ref["gross_return"]) > atol:
                    mismatches.append(
                        (t, tp, H, S,
                         f"gross {float(got_g):.8f} vs {ref['gross_return']:.8f}",
                         float(got_g) - ref["gross_return"]))
                if got_s != bool(ref["stopped"]):
                    mismatches.append(
                        (t, tp, H, S,
                         f"stopped {got_s} vs {ref['stopped']}", None))

                if mismatches and len(mismatches) >= 10:
                    break
            if mismatches and len(mismatches) >= 10:
                break
        if mismatches and len(mismatches) >= 10:
            break

    if mismatches:
        lines = "\n".join(f"    {m[0]} {pd.Timestamp(m[1]).date()} H={m[2]} "
                          f"S={m[3]}: {m[4]}" for m in mismatches[:10])
        raise AssertionError(
            f"outcomes table disagrees with execution.realize_position() in "
            f"{len(mismatches)} of {checked} comparisons:\n{lines}")

    return checked
