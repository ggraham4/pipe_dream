"""
WO-18: Heston-Sadka (2008) return seasonality factor `seas` on the v2 grid.
Frozen definition: models/2026-09-26-seasonality-screen.md.

Prices: Sharadar SEP `closeadj` (total return: split AND dividend adjusted).
  1998-01..2004-12  data/sharadar/sep_pre2005/stocks/*.parquet (WO-18 pull)
  2005-01..2019-12  data/sharadar/panel/stocks/*.parquet (files > 2019-12 are
                    never opened; any row dated >= 2020-01-01 is an error)

Monthly return  r(i, y, m) = ME(i, y, m) / ME(i, prev month) - 1, where ME is
  ticker i's LAST finite, positive closeadj observed in that calendar month;
  both months must exist for i, otherwise r is NaN.
Target month    T = t + 28 calendar days (about 20 trading days, the midpoint
  of the t+1..t+40 holding window); m = T.month, Y = T.year.
seas(i, t)      = mean of r(i, y, m) over y = Y-10..Y-1 with finite r;
  NaN when fewer than 5 of the 10 are finite. Sign +1.
PIT: the latest price feeding seas(i, t) is dated <= the last day of month m of
  year Y-1, which is < t (asserted row by row).

Outputs (worktree final/out/seasonality/): seas_factor_v2.parquet (gitignored),
build_seas_meta.json. Reads the v2 panel and SEP read-only.
"""
import hashlib
import json
import time
from pathlib import Path

import numpy as np
import pandas as pd

MAIN = Path("/Users/ggraham/pipe_dream/final")
SEP_PRE = MAIN / "data" / "sharadar" / "sep_pre2005" / "stocks"
SEP_MAIN = MAIN / "data" / "sharadar" / "panel" / "stocks"
PANEL_V2 = MAIN / "out" / "reset2026" / "composite_panel_v2.parquet"
OUT = Path(__file__).resolve().parents[2] / "out" / "seasonality"
START, END = pd.Timestamp("2007-01-02"), pd.Timestamp("2019-12-31")
HOLDOUT = pd.Timestamp("2020-01-01")
FIRST_YM, LAST_YM = "1998-01", "2019-12"
TARGET_DAYS = 28
N_YEARS, MIN_YEARS = 10, 5
COL = "seas"
# WO-57: spin-off correction (opt-in; default OFF): (ticker, exdt, m) with m the closeadj-series factor
# (1 + r_closeadj) / (1 + r_CRSP). Month-end closeadj dated before exdt is multiplied by m, after the splice.
SPINFIX_EVENTS_ADJ = None


def log(m):
    print(f"[{time.strftime('%H:%M:%S')}] {m}", flush=True)


def sha256(path, chunk=1 << 24):
    h = hashlib.sha256()
    with open(path, "rb") as f:
        while b := f.read(chunk):
            h.update(b)
    return h.hexdigest()


def sep_files():
    """(pre-2005 files 1998-01..2004-12, the 2005-01 overlap re-pull, main files 2005-01..2019-12)."""
    pre_all = sorted(SEP_PRE.glob("*.parquet"))
    pre = [f for f in pre_all if f.stem < "2005-01"]
    ovl = [f for f in pre_all if f.stem == "2005-01"]
    assert len(ovl) == 1 and len(pre_all) == len(pre) + 1, "sep_pre2005 must hold 1998-01..2005-01 exactly"
    main = [f for f in sorted(SEP_MAIN.glob("*.parquet")) if "2005-01" <= f.stem <= LAST_YM]
    stems = [f.stem for f in pre + main]
    want = pd.period_range(FIRST_YM, LAST_YM, freq="M").strftime("%Y-%m").tolist()
    assert stems == want, f"SEP month files incomplete: missing {sorted(set(want) - set(stems))[:10]}"
    return pre, ovl[0], main


def files_digest(files):
    h = hashlib.sha256()
    for f in files:
        h.update(f"{f.parent.name}/{f.name}:{sha256(f)}\n".encode())
    return h.hexdigest()


def load_month_ends(files):
    """One row per (ticker, calendar month): last finite positive closeadj."""
    frames = []
    for f in files:
        d = pd.read_parquet(f, columns=["ticker", "date", "closeadj"])
        d["date"] = pd.to_datetime(d["date"])
        assert d["date"].max() < HOLDOUT, f"HOLD-OUT BREACH in {f}"
        assert (d["date"].dt.strftime("%Y-%m") == f.stem).all(), f"{f} has rows outside its month"
        d = d[np.isfinite(d["closeadj"]) & (d["closeadj"] > 0)]
        d = d.sort_values(["ticker", "date"]).drop_duplicates("ticker", keep="last")
        frames.append(d)
    me = pd.concat(frames, ignore_index=True)
    me["ticker"] = me["ticker"].astype(str)
    me["ym"] = me["date"].dt.year * 12 + me["date"].dt.month - 1   # integer month index
    return me


def splice_month_ends(me_pre, me_ovl, me_main):
    """closeadj is re-based to its pull date. Put 1998-2004 (pulled 2026-09-26)
    on the basis of data/sharadar/panel/stocks (pulled 2026-09-09): per ticker,
    g = ME_new(2005-01) / ME_main(2005-01) on the same last-obs date; pre-2005
    closeadj /= g. A ticker with pre-2005 rows through 2004-12 and main rows in
    2005-01 but no valid g gets its 2004-12 month-end dropped, so the one
    boundary return is NaN rather than mis-scaled."""
    a = me_ovl.set_index("ticker")[["date", "closeadj"]]
    b = me_main[me_main["ym"] == 2005 * 12].set_index("ticker")[["date", "closeadj"]]
    j = a.join(b, how="inner", lsuffix="_new", rsuffix="_old")
    j = j[j["date_new"] == j["date_old"]]
    g = (j["closeadj_new"] / j["closeadj_old"]).rename("g")
    me_pre = me_pre.merge(g, left_on="ticker", right_index=True, how="left")
    dec04 = me_pre["ym"] == 2004 * 12 + 11
    no_g_boundary = dec04 & me_pre["g"].isna() & me_pre["ticker"].isin(set(b.index))
    info = {"tickers_with_g": int(len(g)),
            "g_quantiles": {q: float(g.quantile(q)) for q in (0.0, 0.01, 0.05, 0.5, 0.95, 0.99, 1.0)},
            "g_share_abs_dev_gt_1e-4": float((g.sub(1).abs() > 1e-4).mean()),
            "boundary_dropped_no_g": int(no_g_boundary.sum()),
            "boundary_dropped_tickers": sorted(me_pre.loc[no_g_boundary, "ticker"].tolist())[:50]}
    me_pre = me_pre[~no_g_boundary].copy()
    me_pre["closeadj"] = me_pre["closeadj"] / me_pre["g"].fillna(1.0)
    me = pd.concat([me_pre.drop(columns="g"), me_main], ignore_index=True)
    assert not me.duplicated(["ticker", "ym"]).any()
    return me, info


def monthly_returns(me):
    me = me.sort_values(["ticker", "ym"]).reset_index(drop=True)
    g = me.groupby("ticker", sort=False)
    prev_ym = g["ym"].shift(1)
    prev_px = g["closeadj"].shift(1)
    ok = prev_ym == me["ym"] - 1
    me["ret"] = np.where(ok, me["closeadj"] / prev_px - 1.0, np.nan)
    return me[["ticker", "ym", "ret"]]


def seas_table(R):
    """seas for every (ticker, target month index): mean of r at ym-12k, k=1..10, >= 5 finite."""
    R = R.dropna(subset=["ret"])
    tick = pd.Index(sorted(R["ticker"].unique()))
    ym0 = int(R["ym"].min())
    ym1 = 2020 * 12 + 11                      # targets can be as late as 2020-01 (t in late Dec 2019)
    W = np.full((len(tick), ym1 - ym0 + 1), np.nan)
    W[tick.get_indexer(R["ticker"]), R["ym"].to_numpy() - ym0] = R["ret"].to_numpy()
    S = np.zeros_like(W); N = np.zeros_like(W)
    for k in range(1, N_YEARS + 1):
        sh = np.full_like(W, np.nan)
        sh[:, 12 * k:] = W[:, :-12 * k]
        f = np.isfinite(sh)
        S += np.where(f, sh, 0.0); N += f
    with np.errstate(invalid="ignore", divide="ignore"):
        seas = np.where(N >= MIN_YEARS, S / N, np.nan)
    return tick, ym0, seas, N


def build_panel_factor(tick, ym0, seas, N):
    p = pd.read_parquet(PANEL_V2, columns=["ticker", "date"],
                        filters=[("date", ">=", START.date().isoformat()), ("date", "<=", END.date().isoformat())])
    p["date"] = pd.to_datetime(p["date"]); p["ticker"] = p["ticker"].astype(str)
    assert p["date"].max() < HOLDOUT
    T = p["date"] + pd.Timedelta(days=TARGET_DAYS)
    p["target_ym"] = (T.dt.year * 12 + T.dt.month - 1).astype(np.int64)
    # PIT: latest month used = target_ym - 12; its last calendar day must be < t
    last_used = pd.to_datetime({"year": (p["target_ym"] - 12) // 12, "month": (p["target_ym"] - 12) % 12 + 1,
                                "day": 1}) + pd.offsets.MonthEnd(0)
    assert (last_used < p["date"]).all(), "PIT BREACH: a used month ends on/after t"
    ti = tick.get_indexer(p["ticker"])
    ci = p["target_ym"].to_numpy() - ym0
    has = ti >= 0
    assert (ci < seas.shape[1]).all() and (ci >= 0).all()
    p[COL] = np.nan; p["seas_nyears"] = 0
    p.loc[has, COL] = seas[ti[has], ci[has]]
    p.loc[has, "seas_nyears"] = N[ti[has], ci[has]].astype(int)
    p["in_sep"] = has
    return p[["ticker", "date", COL, "seas_nyears", "target_ym", "in_sep"]]


def main():
    t0 = time.time()
    OUT.mkdir(parents=True, exist_ok=True)
    pre, ovl, main_f = sep_files()
    meta = {"sep_months": [pre[0].stem, main_f[-1].stem], "sep_files": len(pre) + len(main_f)}
    log("hashing inputs ...")
    meta["sep_pre2005_digest"] = files_digest(pre + [ovl])
    meta["sep_2005_2019_digest"] = files_digest(main_f)
    meta["composite_panel_v2_sha256"] = sha256(PANEL_V2)
    meta["composite_panel_v2_mtime"] = time.ctime(PANEL_V2.stat().st_mtime)
    me, splice = splice_month_ends(load_month_ends(pre), load_month_ends([ovl]), load_month_ends(main_f))
    meta["splice"] = splice
    if SPINFIX_EVENTS_ADJ is not None and len(SPINFIX_EVENTS_ADJ):
        import sys
        sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "spinfix"))
        import adjust as SA  # noqa: E402
        me = SA.adjust_month_ends(me, SPINFIX_EVENTS_ADJ)
        meta["spinfix_events_adj"] = int(len(SPINFIX_EVENTS_ADJ))
    log(f"month-ends {len(me):,} rows, {me['ticker'].nunique():,} tickers, max date {me['date'].max().date()}")
    meta["month_end_rows"] = int(len(me)); meta["sep_max_date"] = str(me["date"].max().date())
    R = monthly_returns(me)
    meta["monthly_returns_finite"] = int(R["ret"].notna().sum())
    r = R["ret"].dropna()
    meta["monthly_return_quantiles"] = {q: float(r.quantile(q)) for q in (0.001, 0.01, 0.5, 0.99, 0.999)}
    R.to_parquet(OUT / "monthly_returns_closeadj.parquet", index=False)
    tick, ym0, seas, N = seas_table(R)
    fac = build_panel_factor(tick, ym0, seas, N)
    meta["panel_rows"] = int(len(fac)); meta["panel_finite_seas"] = int(fac[COL].notna().sum())
    meta["panel_tickers"] = int(fac["ticker"].nunique())
    meta["panel_tickers_missing_from_sep"] = sorted(fac.loc[~fac["in_sep"], "ticker"].unique().tolist())
    fac.to_parquet(OUT / "seas_factor_v2.parquet", index=False)
    meta["runtime_s"] = time.time() - t0
    (OUT / "build_seas_meta.json").write_text(json.dumps(meta, indent=2, default=str))
    log(f"panel rows {len(fac):,}, finite seas {meta['panel_finite_seas']:,}, "
        f"{len(meta['panel_tickers_missing_from_sep'])} tickers missing from SEP ({time.time()-t0:.0f}s)")


if __name__ == "__main__":
    main()
