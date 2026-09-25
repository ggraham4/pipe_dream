"""
Screen the option-implied features, on an optionable-only universe.

    python3 screen_options_features.py

--------------------------------------------------------------------------
THE UNIVERSE IS RESTRICTED A PRIORI, AND THAT IS THE POINT
--------------------------------------------------------------------------
Option data exists for 497 large-cap names. Median market cap WITH coverage is
$34.9B; WITHOUT, $2.8B. Carried as a sparse column on the full universe, "has
an option chain" is a 12x size signal, and any model would learn it as one --
then the screen would have to disentangle a size proxy from an option signal
after the fact.

So the universe here is PIT-eligible AND optionable on that date, ~460-490
names. Nothing is NaN because it is a small company; the feature is either
informative within a population that all has it, or it is not. The control is
the same restricted universe without the option columns, which makes the
comparison exact rather than approximate.

The cost is honest and stated: results here do NOT transfer to the deployed
model's universe. This screens whether option-implied shape carries
cross-sectional information among large caps. Whether that survives being
bolted onto a 1,665-name strategy is a separate question and a later one.

--------------------------------------------------------------------------
ERA
--------------------------------------------------------------------------
The chain starts 2019-02-09, so these features have essentially no overlap with
the project's 2007-2019 nomination era. Per Gabe's 2026-09-16 decision the
options era gets its own split:

    nominate  2019-02-09 .. 2024-01-01
    confirm   2024-01-01 .. 2027-01-01   (REFUSED here; not yet earned)

The contamination is stated rather than hidden: the top-5 / volq / invvol
construction was itself confirmed on 2020-2026 in Round 13, so the construction
is not independent of this span even though the features are. A positive here
is a nomination, not a result.

--------------------------------------------------------------------------
WHAT IS MEASURED
--------------------------------------------------------------------------
Per-window Spearman IC of each feature against the tradable 40-day forward
return, plus the SIZE/SECTOR-NEUTRALISED IC. Round 13's whole lesson was that
an apparently strong feature can be a sector bet -- rnd_intensity went from
t 3.28 to t 0.77 under neutralisation. Implied volatility is correlated with
size and with sector by construction, so the neutralised column is the one to
read, not the raw one.

Leave-one-year-out is standing procedure since Round 14: a feature carried by
2020 has a near-zero forward expectation whatever its t-statistic, and 2020 is
a quarter of this era.
"""
import sys
from pathlib import Path

import numpy as np
import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parent))
from features import (FEATURE_COLS, TRADABLE_LABEL_COL, OUT_DIR)      # noqa: E402
from build_options_features import OPTION_FEATURE_COLS                # noqa: E402
from sweep import factors as F                                        # noqa: E402
from sweep import _num                                                # noqa: E402

PANEL = OUT_DIR / "features_with_options_sharadar_pit.parquet"
NOMINATE = ("2019-02-09", "2024-01-01")
CONFIRM = ("2024-01-01", "2027-01-01")
HORIZON = 40
MIN_NAMES = 80


def main():
    import argparse
    ap = argparse.ArgumentParser()
    ap.add_argument("--era", default="nominate", choices=["nominate", "confirm"])
    ap.add_argument("--i-am-confirming", action="store_true")
    args = ap.parse_args()
    if args.era == "confirm" and not args.i_am_confirming:
        raise SystemExit(
            "Refusing to touch 2024-2026.\n"
            "It is the confirmation half of the options split and has not been "
            "earned yet. Screen on 2019-2023, nominate ONE feature set, then "
            "come back with --i-am-confirming and expect to spend it.")
    era = NOMINATE if args.era == "nominate" else CONFIRM

    cols = list(dict.fromkeys(
        ["ticker", "date", TRADABLE_LABEL_COL, "market_cap", "volatility_60"]
        + FEATURE_COLS + OPTION_FEATURE_COLS))
    import pyarrow.parquet as pq
    present = set(pq.ParquetFile(PANEL).schema_arrow.names)
    print(f"loading {PANEL.name} ...", flush=True)
    panel = pd.read_parquet(PANEL, columns=[c for c in cols if c in present])
    panel = panel.dropna(subset=FEATURE_COLS)
    panel = panel[(panel["date"] >= era[0]) & (panel["date"] < era[1])]

    from continuous_walkforward_pit import load_pit_universe
    pit = load_pit_universe()

    # OPTIONABLE-ONLY UNIVERSE, applied before anything else is computed.
    panel = panel[panel["opt_atm_iv"].notna()]
    print(f"  {len(panel):,} optionable rows in {era[0]}..{era[1]}")

    dates = np.sort(panel["date"].unique())
    tps = dates[::HORIZON]
    smap = F.load_sector_map()
    print(f"  {len(tps)} non-overlapping windows, "
          f"{pd.Timestamp(tps[0]).date()} .. {pd.Timestamp(tps[-1]).date()}")

    by_date = {d: g for d, g in panel.groupby("date", observed=True)}
    n_eff = []
    windows = []
    for tp in tps:
        d = by_date.get(pd.Timestamp(tp))
        if d is None:
            continue
        day = pit.get(str(pd.Timestamp(tp).date()))
        if day:
            d = d[d["ticker"].isin(day)]
        y = d[TRADABLE_LABEL_COL].to_numpy(np.float64)
        ok = np.isfinite(y)
        if ok.sum() < MIN_NAMES:
            continue
        d = d[ok]
        n_eff.append(len(d))
        windows.append((pd.Timestamp(tp), d))
    print(f"  {len(windows)} usable windows, median {int(np.median(n_eff))} "
          f"names per window\n")

    rows = []
    for col in OPTION_FEATURE_COLS + ["momentum_20", "volatility_60"]:
        if col not in panel.columns:
            continue
        raw, neu, yrs = [], [], []
        for tp, d in windows:
            x = d[col].to_numpy(np.float64)
            y = d[TRADABLE_LABEL_COL].to_numpy(np.float64)
            m = np.isfinite(x) & np.isfinite(y)
            if m.sum() < MIN_NAMES:
                continue
            r = _num.spearman(x[m], y[m])
            D, _ = F.build_design(d["ticker"].to_numpy()[m],
                                  d["market_cap"].to_numpy(np.float64)[m],
                                  d["volatility_60"].to_numpy(np.float64)[m],
                                  spec="size_vol_sector", sector_map=smap)
            yr = F.residualize(y[m], D)
            g = np.isfinite(yr)
            n = _num.spearman(x[m][g], yr[g]) if g.sum() >= MIN_NAMES else np.nan
            if np.isfinite(r):
                raw.append(r); neu.append(n); yrs.append(tp.year)
        if len(raw) < 6:
            continue
        raw = np.asarray(raw); neu = np.asarray(neu, np.float64)
        yrs = np.asarray(yrs)

        def t(v):
            v = v[np.isfinite(v)]
            if len(v) < 3 or v.std(ddof=1) == 0:
                return np.nan, np.nan
            return float(v.mean()), float(v.mean() / (v.std(ddof=1) / np.sqrt(len(v))))

        ic_r, t_r = t(raw)
        ic_n, t_n = t(neu)
        loyo = []
        for yv in sorted(set(yrs)):
            _, tt = t(neu[yrs != yv])
            if np.isfinite(tt):
                loyo.append(tt)
        rows.append({"feature": col, "n_win": len(raw),
                     "ic_raw": ic_r, "t_raw": t_r,
                     "ic_neutral": ic_n, "t_neutral": t_n,
                     "loyo_min_t": min(loyo, key=abs) if loyo else np.nan,
                     "loyo_same_sign": (len(set(np.sign(loyo))) == 1
                                        if loyo else False)})

    res = pd.DataFrame(rows).sort_values("t_neutral", key=np.abs, ascending=False)
    print("=" * 96)
    print(f"OPTION FEATURE SCREEN -- optionable universe, {args.era} era "
          f"{era[0]}..{era[1]}")
    print("=" * 96)
    print(res.to_string(index=False, float_format=lambda v: f"{v:8.4f}"))
    print("\n  t_neutral is the column that matters: size/vol/sector removed from")
    print("  the target. Implied vol is correlated with both size and sector by")
    print("  construction, so t_raw will flatter these features. Round 13's")
    print("  rnd_intensity went 3.28 -> 0.77 under exactly this correction.")
    print("\n  momentum_20 and volatility_60 are included as REFERENCE ROWS -- known")
    print("  quantities on this same restricted universe, so the option features")
    print("  can be read against something whose behaviour is already understood")
    print("  rather than against zero.")
    out = OUT_DIR / "sweep" / f"options_screen_{args.era}.csv"
    res.to_csv(out, index=False)
    print(f"\nwritten {out}")


if __name__ == "__main__":
    main()
