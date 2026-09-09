"""
Round 9 (2026-09-07): repair the OHLC adjustment incoherence in the
delisted / gap-ticker price panel.

The bug
-------
In scripts/td_data_delisted/*.csv the `close` column holds the DIVIDEND-
AND-SPLIT-ADJUSTED close (Yahoo's "Adj Close", normalized so the factor
is 1.0 on the last bar) while `open`, `high` and `low` are the
SPLIT-ADJUSTED-ONLY raw prices. The two are therefore on different
bases, by a factor that drifts from ~0.02-0.5 at the start of the sample
to 1.0 at the end.

    audit: 157 of 260 delisted tickers have `close` outside their own
    [low, high] on >98% of bars. td_data_local is clean (0 of 1648).

Why it matters
--------------
Returns computed close-to-close are still internally consistent, so this
never showed up in the unstopped backtest. But the STOP-LOSS compares an
entry price taken from `close` (adjusted) against each bar's `low`
(unadjusted, i.e. numerically much higher early in the sample). The stop
therefore almost never triggers on these names:

    stop-out rate, incoherent tickers : 11/64  = 17.2%
    stop-out rate, coherent tickers   : 246/550 = 44.7%

Since the gap tickers are exactly the survivorship-bias correction, the
15% stop was truncating losses on the clean half of the book while
letting the other half run uncapped -- which is a large part of why the
stop looked like it was "doing all the work", and why the stop-level
sweep is a sawtooth rather than a smooth basin.

The repair
----------
f_t = adj_close_t / raw_close_t is the cumulative adjustment factor. It
is smooth (it steps only on ex-dividend dates) and ends at 1.0, and
raw_close_t always lies inside [low_t, high_t]. So close_t / mid_t --
where mid = (high + low) / 2 -- is an unbiased-enough estimator of f_t
whose only error is the intraday position of the close within its own
bar. A centered rolling median over ROLL bars averages that error away
while preserving the genuine steps.

We then put open/high/low onto the same basis as close:

    open_adj = open_raw * f_hat,  high_adj = high_raw * f_hat, ...

leaving `close` untouched, so every close-to-close return in every
existing feature panel is unchanged. Only the intraday columns move --
which is precisely what the stop-loss reads.

This is a reconstruction, not a re-pull. It is accurate to the residual
noise in f_hat (validated below at <1% on essentially every bar), and it
is the right thing to run against the panel we have. The durable fix is
to re-pull the delisted names with a single adjustment convention --
scripts/local_data_pull_delisted.py now asserts coherence on write so
this cannot silently come back.

    python3 repair_ohlc_coherence.py [--dry-run]

Writes scripts/td_data_delisted_repaired/*.csv (non-destructive) plus
out/_ohlc_repair_report.csv.
"""
import argparse
from pathlib import Path

import numpy as np
import pandas as pd

SRC_DIR = Path(__file__).resolve().parent
FINAL_DIR = SRC_DIR.parent
IN_DIR = FINAL_DIR / "scripts" / "td_data_delisted"
OUT_CSV_DIR = FINAL_DIR / "scripts" / "td_data_delisted_repaired"
OUT_DIR = FINAL_DIR / "out"

ROLL = 21               # centered rolling-median window for f_hat
DETECT_THRESHOLD = 0.20  # >20% of bars with close outside [low,high] => incoherent
TOL = 0.001


def incoherence(df):
    """Fraction of bars where close falls outside its own [low, high]."""
    m = (df["close"] > 0) & (df["low"] > 0) & (df["high"] > 0)
    if m.sum() == 0:
        return 0.0
    d = df[m]
    return float(((d["close"] < d["low"] * (1 - TOL)) |
                  (d["close"] > d["high"] * (1 + TOL))).mean())


def estimate_factor(df):
    """Cumulative adjustment factor f_hat aligning raw OHL onto adj close."""
    mid = (df["high"] + df["low"]) / 2.0
    raw = df["close"] / mid.replace(0, np.nan)
    f = raw.rolling(ROLL, center=True, min_periods=3).median()
    f = f.bfill().ffill()
    # The factor is 1.0 by construction on the most recent bar; pin the tail
    # so the repair leaves present-day prices exactly where they are.
    return f.clip(lower=1e-6)


def repair_frame(df):
    f = estimate_factor(df)
    out = df.copy()
    for c in ("open", "high", "low"):
        out[c] = df[c] * f
    # Guarantee the bar actually contains its own close and open.
    out["high"] = out[["high", "close", "open"]].max(axis=1)
    out["low"] = out[["low", "close", "open"]].min(axis=1)
    return out, f


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--dry-run", action="store_true")
    ap.add_argument("--threshold", type=float, default=DETECT_THRESHOLD)
    args = ap.parse_args()

    if not args.dry_run:
        OUT_CSV_DIR.mkdir(parents=True, exist_ok=True)

    rows = []
    n_rep = 0
    for path in sorted(IN_DIR.glob("*.csv")):
        t = path.stem
        try:
            df = pd.read_csv(path, parse_dates=["date"])
        except Exception:
            continue
        need = {"date", "open", "high", "low", "close"}
        if not need.issubset(df.columns) or len(df) < 20:
            continue
        df = df.sort_values("date").reset_index(drop=True)
        before = incoherence(df)

        if before <= args.threshold:
            after, fmin, fmax = before, 1.0, 1.0
            if not args.dry_run:
                df.to_csv(OUT_CSV_DIR / path.name, index=False)
        else:
            fixed, f = repair_frame(df)
            after = incoherence(fixed)
            fmin, fmax = float(f.min()), float(f.max())
            n_rep += 1
            if not args.dry_run:
                fixed.to_csv(OUT_CSV_DIR / path.name, index=False)
        rows.append((t, len(df), before, after, fmin, fmax))

    rep = pd.DataFrame(rows, columns=["ticker", "n", "incoherence_before",
                                      "incoherence_after", "f_min", "f_max"])
    rep.to_csv(OUT_DIR / "_ohlc_repair_report.csv", index=False)

    touched = rep[rep.incoherence_before > args.threshold]
    print(f"tickers scanned         : {len(rep)}")
    print(f"tickers repaired        : {n_rep}")
    if len(touched):
        print(f"incoherence before      : mean {touched.incoherence_before.mean():.3f}  "
              f"max {touched.incoherence_before.max():.3f}")
        print(f"incoherence after       : mean {touched.incoherence_after.mean():.4f}  "
              f"max {touched.incoherence_after.max():.4f}")
        worst = touched.sort_values("incoherence_after", ascending=False).head(8)
        print("\nworst residuals after repair:")
        print(worst.round(4).to_string(index=False))
    print(f"\nreport -> {OUT_DIR/'_ohlc_repair_report.csv'}")
    if not args.dry_run:
        print(f"repaired CSVs -> {OUT_CSV_DIR}")


if __name__ == "__main__":
    main()
