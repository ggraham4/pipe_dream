"""
Two diagnostics the 15-window screen could not support: WHERE the signal is,
and whether it survives a properly powered estimator.

    python3 screen_options_power.py

--------------------------------------------------------------------------
1. PER-YEAR DECOMPOSITION
--------------------------------------------------------------------------
opt_vrp's neutralised t falls from 2.13 to 1.24 on a single year-drop. With
five years, dropping one removes ~20% of the data and sqrt(n) alone predicts an
~11% fall. A 42% fall means the effect is concentrated, and the era contains
2020 -- the largest volatility event in the sample, and precisely the regime
where a variance-risk-premium feature would be expected to look strongest for
reasons that will not repeat. Round 14 killed rate_beta_x_move on exactly this
pattern: 2019 was 8% of windows and 45% of the effect.

--------------------------------------------------------------------------
2. FAMA-MACBETH WITH NEWEY-WEST ERRORS
--------------------------------------------------------------------------
The 40-day non-overlapping grid exists so windows are independent, which is the
right default when there are 82 of them. Over a five-year era it throws away
39 of every 40 cross-sections and leaves 15 observations.

The standard alternative is to run the cross-sectional regression EVERY DAY and
correct the standard error for the overlap, rather than to avoid the overlap by
discarding data. Consecutive days share 39/40 of their forward window, so the
daily IC series is strongly autocorrelated and a naive t would be inflated by
roughly sqrt(40). Newey-West with a lag of 40 (Bartlett kernel) is the textbook
correction and is what the asset-pricing literature uses for exactly this
setup.

This is not a way to manufacture significance. The NW t will be far below the
naive daily t; the question is whether it is above the 15-window t, which it
should be if the 15-window estimate was merely imprecise rather than absent.
If NW and the 15-window t agree, the feature is weak and more data will not
help. If NW is much stronger, the 15-window screen was underpowered.
"""
import sys
from pathlib import Path

import numpy as np
import pandas as pd
import pyarrow.parquet as pq

sys.path.insert(0, str(Path(__file__).resolve().parent))
from features import FEATURE_COLS, TRADABLE_LABEL_COL, OUT_DIR   # noqa: E402
from build_options_features import OPTION_FEATURE_COLS           # noqa: E402
from sweep import factors as F                                   # noqa: E402
from sweep import _num                                           # noqa: E402

PANEL = OUT_DIR / "features_with_options_sharadar_pit.parquet"
ERA = ("2019-02-09", "2024-01-01")
HORIZON = 40
MIN_NAMES = 80

# opt_implied_move_40 is opt_atm_iv * sqrt(40/252) -- a positive constant, so
# it is the SAME FEATURE under any rank statistic. Identical ICs in the screen
# (0.1977, t 2.8360 for both) confirmed it. Dropped rather than reported twice.
SCREEN = [c for c in OPTION_FEATURE_COLS if c != "opt_implied_move_40"]
REFERENCE = ["momentum_20", "volatility_60"]


def newey_west_t(x, lag):
    """t for the mean of an autocorrelated series, Bartlett kernel."""
    x = np.asarray(x, np.float64)
    x = x[np.isfinite(x)]
    n = len(x)
    if n < lag + 5:
        return np.nan, np.nan, n
    d = x - x.mean()
    g0 = float(d @ d) / n
    var = g0
    for k in range(1, lag + 1):
        gk = float(d[k:] @ d[:-k]) / n
        var += 2.0 * (1.0 - k / (lag + 1.0)) * gk
    if var <= 0:
        return float(x.mean()), np.nan, n
    return float(x.mean()), float(x.mean() / np.sqrt(var / n)), n


def main():
    cols = list(dict.fromkeys(
        ["ticker", "date", TRADABLE_LABEL_COL, "market_cap", "volatility_60"]
        + FEATURE_COLS + OPTION_FEATURE_COLS))
    present = set(pq.ParquetFile(PANEL).schema_arrow.names)
    print(f"loading {PANEL.name} ...", flush=True)
    panel = pd.read_parquet(PANEL, columns=[c for c in cols if c in present])
    panel = panel.dropna(subset=FEATURE_COLS)
    panel = panel[(panel["date"] >= ERA[0]) & (panel["date"] < ERA[1])]
    panel = panel[panel["opt_atm_iv"].notna()]

    from continuous_walkforward_pit import load_pit_universe
    pit = load_pit_universe()
    smap = F.load_sector_map()

    # neutralised IC for EVERY trading day, not every 40th
    feats = [c for c in SCREEN + REFERENCE if c in panel.columns]
    daily = {c: [] for c in feats}
    days = []
    for d_, g in panel.groupby("date", observed=True, sort=True):
        day = pit.get(str(pd.Timestamp(d_).date()))
        if day:
            g = g[g["ticker"].isin(day)]
        y = g[TRADABLE_LABEL_COL].to_numpy(np.float64)
        m0 = np.isfinite(y)
        if m0.sum() < MIN_NAMES:
            continue
        g = g[m0]; y = y[m0]
        D, _ = F.build_design(g["ticker"].to_numpy(),
                              g["market_cap"].to_numpy(np.float64),
                              g["volatility_60"].to_numpy(np.float64),
                              spec="size_vol_sector", sector_map=smap)
        yr = F.residualize(y, D)
        ok = np.isfinite(yr)
        if ok.sum() < MIN_NAMES:
            continue
        days.append(pd.Timestamp(d_))
        for c in feats:
            x = g[c].to_numpy(np.float64)
            m = ok & np.isfinite(x)
            daily[c].append(_num.spearman(x[m], yr[m])
                            if m.sum() >= MIN_NAMES else np.nan)
    days = pd.DatetimeIndex(days)
    print(f"  {len(days)} daily cross-sections, "
          f"{days.min().date()} .. {days.max().date()}\n")

    print("=" * 100)
    print("NEUTRALISED IC -- daily cross-sections, Newey-West(40) vs the 15-window grid")
    print("=" * 100)
    print(f"{'feature':<22}{'IC':>9}{'naive t':>10}{'NW t':>8}{'n days':>8}   per-year neutralised IC")
    yrs = sorted(set(days.year))
    hdr = "".join(f"{y:>9}" for y in yrs)
    print(f"{'':<22}{'':>9}{'':>10}{'':>8}{'':>8}   {hdr}")
    rows = []
    for c in feats:
        v = np.asarray(daily[c], np.float64)
        m, tnw, n = newey_west_t(v, HORIZON)
        ok = np.isfinite(v)
        tn = float(v[ok].mean() / (v[ok].std(ddof=1) / np.sqrt(ok.sum())))
        per = []
        for y in yrs:
            s = v[np.asarray(days.year == y) & ok]
            per.append(float(s.mean()) if len(s) > 20 else np.nan)
        line = "".join(f"{p:>+9.4f}" if np.isfinite(p) else f"{'--':>9}" for p in per)
        print(f"{c:<22}{m:>+9.4f}{tn:>+10.2f}{tnw:>+8.2f}{n:>8}   {line}")
        rows.append({"feature": c, "ic": m, "t_naive": tn, "t_nw": tnw,
                     "n_days": n, **{f"ic_{y}": p for y, p in zip(yrs, per)}})

    res = pd.DataFrame(rows)
    out = OUT_DIR / "sweep" / "options_screen_power.csv"
    res.to_csv(out, index=False)

    print("\n  naive t treats overlapping days as independent and is inflated by")
    print(f"  roughly sqrt({HORIZON}) ~ {np.sqrt(HORIZON):.1f}x. NW t is the one to read.")
    print("\n  The per-year columns are the Round 14 test. A feature whose IC lives")
    print("  in one year has a near-zero forward expectation whatever its t: 2020")
    print("  is the largest volatility event in this sample and is exactly where a")
    print("  variance-risk-premium feature would look strongest for reasons that")
    print("  will not repeat.")
    print(f"\nwritten {out}")


if __name__ == "__main__":
    main()
