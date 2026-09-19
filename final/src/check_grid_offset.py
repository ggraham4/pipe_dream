"""
How much of a feature_ic result is the choice of grid OFFSET?

    python3 check_grid_offset.py
    python3 check_grid_offset.py --features accel_20,momentum_20 --era holdout

WHY THIS EXISTS
---------------
`sweep/feature_ic.py` measures each feature's IC on NON-OVERLAPPING windows:
one cross-section every `horizon` trading days. At h=40 over the nomination era
that is 82 of 3,272 available days. Non-overlapping is the right instinct --
consecutive days share 39/40 of their forward window, so a naive t over all days
is inflated by roughly sqrt(40).

But there are FORTY equally-valid such grids, one per starting offset, and the
screen silently uses offset 0. Nothing distinguishes it from the other 39.

Discovered 2026-09-16 while diagnosing why accel_20's feature_ic result
(+0.0226, t +1.88) disagreed in SIGN and by 20x in magnitude with the same
feature measured on all 3,272 days (-0.0011, t -0.54). It was not the label, the
universe, the neutralisation or the feature definition. It was the offset:

    accel_20          40 grids span IC -0.0350 .. +0.0272   21/40 flip sign
    momentum_20       40 grids span IC -0.0388 .. +0.0170   16/40 flip sign
    volatility_60     40 grids span IC -0.0174 .. -0.0034    0/40 flip sign
    pct_from_high_252 40 grids span IC +0.0041 .. +0.0251    0/40 flip sign

The estimator is stable for features with a real effect and a coin flip for
features near zero -- which are exactly the ones a screen exists to judge. Two
of accel_20's forty grids would have read |t| >= 2 and passed a gate; two others
would have read |t| >= 2 with the OPPOSITE sign.

HOW TO READ THE OUTPUT
----------------------
`all days` is the estimate that uses every cross-section. It is not directly
comparable to a single grid's t -- overlapping windows need Newey-West, which
screen_path_order.py does -- but its MEAN is the thing 40 grids are noisy draws
around, and its sign is the one to trust.

`sign flips` is the headline. Anything above zero means the screen's verdict on
that feature is partly a coin flip, and a near-miss or a narrow pass read off
one grid should not be believed without this check.
"""
import argparse
import sys
from pathlib import Path

import numpy as np
import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parent))
from features import OUT_DIR, TRADABLE_LABEL_COL           # noqa: E402
from sweep import _num                                     # noqa: E402
from screen_path_order import _pit_universe                # noqa: E402

PANEL = OUT_DIR / "features_with_fundamentals_sharadar_pit.parquet"
ERAS = {"nominate": ("2007-01-01", "2020-01-01"),
        "holdout": ("2020-01-01", "2027-01-01")}
DEFAULT = ["accel_20", "momentum_20", "volatility_60", "pct_from_high_252"]
MIN_NAMES = 20


def daily_ic(feats, era, horizon):
    lo, hi = ERAS[era]
    p = pd.read_parquet(PANEL, columns=["ticker", "date", TRADABLE_LABEL_COL] + feats,
                        filters=[("date", ">=", pd.Timestamp(lo)),
                                 ("date", "<", pd.Timestamp(hi))])
    pit = _pit_universe()
    out = {c: [] for c in feats}
    days = []
    for d_, g in p.groupby("date", observed=True, sort=True):
        ts = pd.Timestamp(d_)
        day = pit.get(str(ts.date()))
        if day:
            g = g[g["ticker"].isin(day)]
        y = g[TRADABLE_LABEL_COL].to_numpy(np.float64)
        if np.isfinite(y).sum() < MIN_NAMES:
            continue
        days.append(ts)
        for c in feats:
            x = g[c].to_numpy(np.float64)
            m = np.isfinite(y) & np.isfinite(x)
            out[c].append(_num.spearman(x[m], y[m]) if m.sum() >= MIN_NAMES
                          else np.nan)
    return pd.DatetimeIndex(days), out


def main(feats, era, horizon):
    days, daily = daily_ic(feats, era, horizon)
    print(f"{len(days):,} daily cross-sections, {era} era, horizon {horizon}")
    print(f"\nEvery {horizon}th day is ONE of {horizon} equally-valid "
          f"non-overlapping grids.")
    print(f"sweep.cli features uses offset 0. What the other {horizon - 1} say:\n")
    print(f"{'feature':<20}{'all days':>11}{'offset 0':>11}{'t':>7}"
          f"{'grid min':>11}{'grid max':>11}{'sign flips':>12}{'|t|>=2':>9}")
    rows = []
    for c in feats:
        v = np.asarray(daily[c], np.float64)
        allm = float(np.nanmean(v))
        ics, ts = [], []
        for off in range(horizon):
            s = v[off::horizon]
            s = s[np.isfinite(s)]
            if len(s) < 3 or s.std(ddof=1) == 0:
                continue
            ics.append(s.mean())
            ts.append(s.mean() / (s.std(ddof=1) / np.sqrt(len(s))))
        ics, ts = np.array(ics), np.array(ts)
        flips = int((np.sign(ics) != np.sign(allm)).sum())
        big = int((np.abs(ts) >= 2).sum())
        print(f"{c:<20}{allm:>+11.4f}{ics[0]:>+11.4f}{ts[0]:>+7.2f}"
              f"{ics.min():>+11.4f}{ics.max():>+11.4f}"
              f"{flips:>8} /{len(ics):<3}{big:>6} /{len(ics)}")
        rows.append({"feature": c, "ic_all_days": allm, "ic_offset0": ics[0],
                     "t_offset0": ts[0], "ic_min": ics.min(), "ic_max": ics.max(),
                     "t_min": ts.min(), "t_max": ts.max(),
                     "n_grids": len(ics), "sign_flips": flips,
                     "n_grids_abs_t_ge2": big})
    out = OUT_DIR / "sweep" / f"grid_offset_{era}_h{horizon}.csv"
    pd.DataFrame(rows).to_csv(out, index=False)
    print(f"\n  sign flips > 0 means that feature's screen verdict is partly a")
    print(f"  coin flip. A near-miss or narrow pass read off one grid should")
    print(f"  not be believed without this check.")
    print(f"\nwritten {out}")


if __name__ == "__main__":
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--features", default=",".join(DEFAULT))
    ap.add_argument("--era", default="nominate", choices=list(ERAS))
    ap.add_argument("--horizon", type=int, default=40)
    a = ap.parse_args()
    main([c.strip() for c in a.features.split(",") if c.strip()], a.era, a.horizon)
