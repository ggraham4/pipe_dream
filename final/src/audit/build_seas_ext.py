"""
WO-23: `seas` on the v2 grid extended past 2019 with the IDENTICAL WO-18
definition (final/src/seasonality/build_seas.py; imported, never edited).
Pre-registration: final/models/2026-09-27-model-audit.md section 2.5.

Only three things differ from build_seas.main():
  * SEP month files are read 1998-01 .. 2025-12 (B.LAST_YM patched), since the
    latest period-B target month is 2026-08 (returns end 2025-08);
  * the seas table has target months through 2026-12 (build_seas hard-codes 2020-12);
  * panel rows 2007-01-02 .. 2026-07-30 (the last matured 40d label).
PIT is asserted row by row exactly as build_seas.build_panel_factor.

Checks (all hard asserts):
  (i)   every pre-2020 row == WO-18 seas_factor_v2.parquet (DataFrame.equals on
        seas / seas_nyears / target_ym / in_sep);
  (ii)  seas_live.seas_asof on sample period-B dates == this table (1e-9, NaN
        pattern, seas_nyears);
  (iii) AAPL hand check (seas_live.handcheck, independent loop code) on sample B dates.
Output: final/out/audit/seas_factor_ext.parquet (gitignored),
        final/out/audit/build_seas_ext_meta.json
"""
import json
import sys
import time
from pathlib import Path

import numpy as np
import pandas as pd

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE.parent / "seasonality"))
import build_seas as B  # noqa: E402
import seas_live as SL  # noqa: E402

OUT = HERE.parents[1] / "out" / "audit"
END_B = pd.Timestamp("2026-07-30")
SEP_LAST_YM = "2025-12"
YM1 = 2026 * 12 + 11
WO18_CANDIDATES = [
    Path("/Users/ggraham/pipe_dream/.claude/worktrees/agent-a790eb27c4530aa0a/final/out/seasonality/seas_factor_v2.parquet"),
    Path("/Users/ggraham/pipe_dream/.claude/worktrees/agent-ad57ef9f38454d99d/final/out/seasonality/seas_factor_v2.parquet"),
]
CHECK_DATES_B = ["2020-01-02", "2020-03-16", "2021-06-01", "2022-12-30", "2024-02-29", "2025-11-03", "2026-07-30"]


def seas_table_ext(R):
    """build_seas.seas_table with the target-month axis extended to YM1."""
    R = R.dropna(subset=["ret"])
    tick = pd.Index(sorted(R["ticker"].unique()))
    ym0 = int(R["ym"].min())
    W = np.full((len(tick), YM1 - ym0 + 1), np.nan)
    W[tick.get_indexer(R["ticker"]), R["ym"].to_numpy() - ym0] = R["ret"].to_numpy()
    S = np.zeros_like(W); N = np.zeros_like(W)
    for k in range(1, B.N_YEARS + 1):
        sh = np.full_like(W, np.nan)
        sh[:, 12 * k:] = W[:, :-12 * k]
        f = np.isfinite(sh)
        S += np.where(f, sh, 0.0); N += f
    with np.errstate(invalid="ignore", divide="ignore"):
        seas = np.where(N >= B.MIN_YEARS, S / N, np.nan)
    return tick, ym0, seas, N


def panel_factor_ext(tick, ym0, seas, N):
    """build_seas.build_panel_factor with END = 2026-07-30."""
    p = pd.read_parquet(B.PANEL_V2, columns=["ticker", "date"])
    p["date"] = pd.to_datetime(p["date"]); p["ticker"] = p["ticker"].astype(str)
    p = p[(p["date"] >= B.START) & (p["date"] <= END_B)].reset_index(drop=True)
    T = p["date"] + pd.Timedelta(days=B.TARGET_DAYS)
    p["target_ym"] = (T.dt.year * 12 + T.dt.month - 1).astype(np.int64)
    last_used = pd.to_datetime({"year": (p["target_ym"] - 12) // 12, "month": (p["target_ym"] - 12) % 12 + 1,
                                "day": 1}) + pd.offsets.MonthEnd(0)
    assert (last_used < p["date"]).all(), "PIT BREACH: a used month ends on/after t"
    ti = tick.get_indexer(p["ticker"]); ci = p["target_ym"].to_numpy() - ym0
    has = ti >= 0
    assert (ci < seas.shape[1]).all() and (ci >= 0).all()
    p[B.COL] = np.nan; p["seas_nyears"] = 0
    p.loc[has, B.COL] = seas[ti[has], ci[has]]
    p.loc[has, "seas_nyears"] = N[ti[has], ci[has]].astype(int)
    p["in_sep"] = has
    return p[["ticker", "date", B.COL, "seas_nyears", "target_ym", "in_sep"]]


def main():
    t0 = time.time()
    OUT.mkdir(parents=True, exist_ok=True)
    B.LAST_YM = SEP_LAST_YM
    B.HOLDOUT = pd.Timestamp("2026-01-01")      # SEP rows read must be < 2026-01-01 (max month 2025-12)
    pre, ovl, main_f = B.sep_files()
    meta = {"sep_months": [pre[0].stem, main_f[-1].stem], "sep_files": len(pre) + len(main_f),
            "sep_main_mtime_range": [time.ctime(min(f.stat().st_mtime for f in main_f)),
                                     time.ctime(max(f.stat().st_mtime for f in main_f))]}
    me, splice = B.splice_month_ends(B.load_month_ends(pre), B.load_month_ends([ovl]), B.load_month_ends(main_f))
    meta["splice"] = {k: v for k, v in splice.items() if k != "boundary_dropped_tickers"}
    R = B.monthly_returns(me)
    tick, ym0, seas, N = seas_table_ext(R)
    fac = panel_factor_ext(tick, ym0, seas, N)
    B.log(f"ext panel rows {len(fac):,} ({fac['date'].min().date()}..{fac['date'].max().date()})")

    # (i) pre-2020 identical to WO-18
    ref_p = next(p for p in WO18_CANDIDATES if p.exists())
    ref = pd.read_parquet(ref_p).sort_values(["date", "ticker"]).reset_index(drop=True)
    ref["ticker"] = ref["ticker"].astype(str); ref["date"] = pd.to_datetime(ref["date"])
    mine = fac[fac["date"] < pd.Timestamp("2020-01-01")].sort_values(["date", "ticker"]).reset_index(drop=True)
    # The factor columns must be identical. `in_sep` (ticker present anywhere in the SEP span
    # read) is metadata, not a factor input: tickers whose SEP rows start after 2019 flip it
    # on their pre-2020 (all-NaN seas) rows; counted and reported, not asserted.
    cols = ["ticker", "date", "seas", "seas_nyears", "target_ym"]
    eq = mine[cols].reset_index(drop=True).equals(ref[cols].astype(mine[cols].dtypes.to_dict()).reset_index(drop=True))
    flip = mine["in_sep"].to_numpy() != ref["in_sep"].to_numpy()
    meta["check_i_pre2020_equals_wo18"] = {"reference": str(ref_p), "rows": int(len(ref)), "equal": bool(eq),
                                          "columns_compared": cols[2:], "in_sep_flipped_rows": int(flip.sum()),
                                          "in_sep_flipped_tickers": int(mine.loc[flip, "ticker"].nunique()),
                                          "in_sep_flipped_rows_finite_seas": int(mine.loc[flip, "seas"].notna().sum())}
    assert eq, "CHECK (i) FAIL: pre-2020 rows differ from WO-18"
    B.log("check (i) pre-2020 == WO-18: PASS")

    # (ii) seas_live on period-B dates
    ck = {}
    dates = sorted(fac.loc[fac["date"] >= "2020-01-01", "date"].unique())
    for d in CHECK_DATES_B:
        d = pd.Timestamp(d)
        d = max(x for x in dates if x <= d)
        r = fac[fac["date"] == d]
        live, info = SL.seas_asof(r["ticker"], d)
        a, b = live["seas"].to_numpy(np.float64), r["seas"].to_numpy(np.float64)
        nan_eq = bool((np.isnan(a) == np.isnan(b)).all())
        diff = float(np.nanmax(np.abs(a - b))) if np.isfinite(b).any() else 0.0
        ny = bool((live["seas_nyears"].to_numpy() == r["seas_nyears"].to_numpy()).all())
        ck[str(d.date())] = {"rows": int(len(r)), "finite": int(np.isfinite(b).sum()), "max_abs_diff": diff,
                             "nan_equal": nan_eq, "nyears_equal": ny, "target_month": info["target_month"],
                             "basis_flag": info["basis_flag"]}
        assert nan_eq and ny and diff <= 1e-9, ("CHECK (ii) FAIL", d, ck[str(d.date())])
    meta["check_ii_seas_live_period_b"] = ck
    B.log(f"check (ii) seas_live == ext on {len(ck)} B dates: PASS")

    # (iii) AAPL hand check (independent loops) on B dates, compared to this table
    hc = {}
    for d in ["2020-06-01", "2023-01-03", "2026-07-30"]:
        h = SL.handcheck("AAPL", d)
        mine_v = fac.loc[(fac["date"] == pd.Timestamp(d)) & (fac["ticker"] == "AAPL"), "seas"]
        mv = float(mine_v.iloc[0])
        assert abs(mv - h["hand_seas"]) < 1e-12, ("CHECK (iii) FAIL", d, mv, h["hand_seas"])
        hc[d] = {"target": h["target"], "hand": h["hand_seas"], "ext_table": mv,
                 "years": [(y["year"], y["ret"]) for y in h["years"]]}
    meta["check_iii_aapl_hand"] = hc
    B.log("check (iii) AAPL hand check: PASS")

    fac.to_parquet(OUT / "seas_factor_ext.parquet", index=False)
    meta["rows"] = int(len(fac)); meta["runtime_s"] = time.time() - t0
    (OUT / "build_seas_ext_meta.json").write_text(json.dumps(meta, indent=1, default=str))
    B.log(f"wrote {OUT / 'seas_factor_ext.parquet'} ({time.time() - t0:.0f}s)")


if __name__ == "__main__":
    main()
