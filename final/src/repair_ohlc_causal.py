"""
Round 10 (2026-09-08): CAUSAL replacement for repair_ohlc_coherence.py.

The bug being fixed is mine, introduced this morning
--------------------------------------------------
repair_ohlc_coherence.py estimated each bar's cumulative adjustment factor as

    f = (close / mid).rolling(ROLL, center=True, min_periods=3).median()

`center=True` means the factor at bar t is estimated from roughly ten bars
BEFORE and ten bars AFTER t. That factor then multiplies open/high/low. So the
repaired open at date t embeds information from dates up to t+10.

Why that is not cosmetic:
  * the tradable training label is close[t+H] / open[t+1]
  * execution enters positions at open[t+1]
so future information sits inside both the training target and the realized
entry price -- for the 177 delisted tickers the repair touched.

Those are precisely the gap tickers: exempt from the market-cap/price floor,
and far more common early in the sample. The measured IC was +0.195 in
2007-2019 against +0.025 in 2020-2026, invariant to doubling the embargo.
A centered smoother on early-sample names fits that fingerprint exactly.

The fix is trivial and strictly causal: a TRAILING window. The factor at bar t
uses only bars <= t. It is a slightly noisier estimate of a quantity that
changes only on ex-dividend dates, which is the correct trade -- a noisier
honest number beats a cleaner impossible one.

Writes scripts/td_data_delisted_repaired_causal/. Point PRICE_DIRS at it (or
rename) and re-run the validation before believing any cross-sectional result.

    python3 repair_ohlc_causal.py [--roll 21]
"""
import argparse
from pathlib import Path

import numpy as np
import pandas as pd

SRC = Path(__file__).resolve().parent
FINAL = SRC.parent
IN_DIR = FINAL / "scripts" / "td_data_delisted"
OUT_DIR = FINAL / "scripts" / "td_data_delisted_repaired_causal"
OUT = FINAL / "out"
TOL = 0.001
DETECT = 0.20


def incoherence(df):
    m = (df["close"] > 0) & (df["low"] > 0) & (df["high"] > 0)
    if m.sum() == 0:
        return 0.0
    d = df[m]
    return float(((d["close"] < d["low"] * (1 - TOL)) |
                  (d["close"] > d["high"] * (1 + TOL))).mean())


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--roll", type=int, default=21)
    ap.add_argument("--threshold", type=float, default=DETECT)
    args = ap.parse_args()
    OUT_DIR.mkdir(parents=True, exist_ok=True)

    rows, n_rep = [], 0
    for path in sorted(IN_DIR.glob("*.csv")):
        try:
            df = pd.read_csv(path, parse_dates=["date"])
        except Exception:
            continue
        if not {"date", "open", "high", "low", "close"}.issubset(df.columns) or len(df) < 20:
            continue
        df = df.sort_values("date").reset_index(drop=True)
        before = incoherence(df)
        if before <= args.threshold:
            df.to_csv(OUT_DIR / path.name, index=False)
            rows.append((path.stem, len(df), before, before, 1.0, 1.0))
            continue

        mid = (df["high"] + df["low"]) / 2.0
        raw = df["close"] / mid.replace(0, np.nan)
        # TRAILING ONLY -- bar t uses bars <= t. This is the whole fix.
        f = raw.rolling(args.roll, center=False, min_periods=3).median()
        f = f.bfill().ffill().clip(lower=1e-6)

        out = df.copy()
        for c in ("open", "high", "low"):
            out[c] = df[c] * f
        out["high"] = out[["high", "close", "open"]].max(axis=1)
        out["low"] = out[["low", "close", "open"]].min(axis=1)
        after = incoherence(out)
        out.to_csv(OUT_DIR / path.name, index=False)
        rows.append((path.stem, len(df), before, after, float(f.min()), float(f.max())))
        n_rep += 1

    rep = pd.DataFrame(rows, columns=["ticker", "n", "incoherence_before",
                                      "incoherence_after", "f_min", "f_max"])
    rep.to_csv(OUT / "_ohlc_repair_causal_report.csv", index=False)
    t = rep[rep.incoherence_before > args.threshold]
    print(f"scanned  : {len(rep)}")
    print(f"repaired : {n_rep}  (trailing window, roll={args.roll})")
    if len(t):
        print(f"incoherence before : mean {t.incoherence_before.mean():.3f}")
        print(f"incoherence after  : mean {t.incoherence_after.mean():.4f}  "
              f"max {t.incoherence_after.max():.4f}")
        print("\nNote: a trailing estimator leaves slightly more residual than the")
        print("centered one did. That residual is the price of not using the future.")
    print(f"\n-> {OUT_DIR}")
    print("Now re-run:  python3 validate_xsec.py --mode real   (after pointing")
    print("PRICE_DIRS at the causal folder), and compare the IC.")


if __name__ == "__main__":
    main()
