"""
WO-13: standardized unexpected earnings (SUE), seasonal random walk
(Bernard-Thomas 1989). Frozen definition: models/2026-09-25-sue-drift-screen.md.

Source: data/sharadar/sf1_fundamentals.parquet, dimension == 'ARQ' only
(as-reported, not restated; asserts no MRQ rows exist). Availability date =
SF1 `date` (datekey = filing date; verified in validate_sue.py).

Filing level (one row per (ticker, reportperiod), FIRST ARQ row by `date`):
  D_q   = EPS_q - EPS_{q-4}; q-4 = same ticker, reportperiod nearest to
          rp_q - 12 months within +-15 days, filed on or before q's date
  SUE_q = D_q / sd(D_j, ddof=1) over j = q-1..q-8 (j = reportperiod nearest to
          rp_q - 3k months, k = 1..8, +-15 days; D_j and both its legs filed
          on or before q's date); needs >= 6 finite D_j and sd > 0; clipped
          at +-10.
Panel level (every composite_panel_v2 (ticker, date) row, 2007-01-02..2019-12-31):
  sue(t) = SUE of the latest ARQ filing with date <= previous trading day of t
           (ties on the same filing date: latest reportperiod); NaN when
           t - filing date > 100 calendar days.

Outputs (worktree final/out/sue/): sue_filings.parquet, sue_factor_v2.parquet,
build_sue_meta.json. Reads v2 files read-only.
"""
import hashlib
import json
import time
from pathlib import Path

import numpy as np
import pandas as pd

MAIN = Path("/Users/ggraham/pipe_dream/final")
SF1 = MAIN / "data" / "sharadar" / "sf1_fundamentals.parquet"
PANEL_V2 = MAIN / "out" / "reset2026" / "composite_panel_v2.parquet"
OUT = Path(__file__).resolve().parents[2] / "out" / "sue"
START, END = pd.Timestamp("2007-01-02"), pd.Timestamp("2019-12-31")
HOLDOUT = pd.Timestamp("2020-01-01")
TOL = pd.Timedelta(days=15)
MIN_D, N_D = 6, 8
WINSOR = 10.0
STALE_DAYS = 100


def log(m):
    print(f"[{time.strftime('%H:%M:%S')}] {m}", flush=True)


def sha256(path, chunk=1 << 24):
    h = hashlib.sha256()
    with open(path, "rb") as f:
        while b := f.read(chunk):
            h.update(b)
    return h.hexdigest()


def load_arq():
    df = pd.read_parquet(SF1, columns=["ticker", "dimension", "date", "reportperiod", "eps"])
    dims = set(df["dimension"].unique())
    assert "MRQ" not in dims and "MRT" not in dims and "MRY" not in dims, f"restated dims present: {dims}"
    n_all = int((df["dimension"] == "ARQ").sum())
    df = df[df["dimension"] == "ARQ"].drop(columns="dimension")
    df["date"] = pd.to_datetime(df["date"])
    df["rp"] = pd.to_datetime(df["reportperiod"])
    df["ticker"] = df["ticker"].astype(str)
    n_null = int(df[["date", "rp"]].isna().any(axis=1).sum())
    df = df.dropna(subset=["date", "rp"])
    df = df.sort_values(["ticker", "rp", "date"], kind="mergesort")
    df = df.drop_duplicates(["ticker", "rp"], keep="first").drop(columns="reportperiod")
    df = df.sort_values(["ticker", "rp"]).reset_index(drop=True)
    return df, {"arq_rows": n_all, "arq_after_dedup": int(len(df)), "dims": sorted(dims), "null_key_rows_dropped": n_null}


def match_back(df, months, value_cols):
    """For each row, the same-ticker row whose rp is nearest to rp - months
    (within +-15 days). Returns value_cols of the match (NaN if none)."""
    left = pd.DataFrame({"i": np.arange(len(df)), "ticker": df["ticker"].to_numpy(),
                         "target": df["rp"] - pd.DateOffset(months=months)})
    left = left.sort_values("target")
    right = df[["ticker", "rp"] + value_cols].sort_values("rp")
    m = pd.merge_asof(left, right, left_on="target", right_on="rp", by="ticker",
                      direction="nearest", tolerance=TOL)
    return m.sort_values("i").reset_index(drop=True)[value_cols]


def build_filings(df):
    # stage 1: D for every quarter, and the later of its two filing dates
    m12 = match_back(df, 12, ["eps", "date"])
    df["eps_lag4"] = m12["eps"].to_numpy()
    df["date_lag4"] = m12["date"].to_numpy()
    df["D"] = df["eps"] - df["eps_lag4"]
    df["D_known"] = df[["date", "date_lag4"]].max(axis=1)
    # own D only usable if q-4 was filed on or before q
    own_D = df["D"].where(df["date_lag4"] <= df["date"])
    # stage 2: D_j of the 8 prior quarters, point-in-time at q's filing date
    Ds = []
    for k in range(1, N_D + 1):
        mk = match_back(df, 3 * k, ["D", "D_known"])
        ok = mk["D_known"].to_numpy() <= df["date"].to_numpy()
        Ds.append(np.where(ok, mk["D"].to_numpy(np.float64), np.nan))
    Dm = np.column_stack(Ds)
    n_fin = np.isfinite(Dm).sum(axis=1)
    with np.errstate(invalid="ignore", divide="ignore"):
        sd = np.nanstd(np.where(n_fin[:, None] >= 2, Dm, np.nan), axis=1, ddof=1)
    sd = np.where(n_fin >= MIN_D, sd, np.nan)
    sd = np.where(sd > 0, sd, np.nan)
    raw = own_D.to_numpy(np.float64) / sd
    df["n_hist"] = n_fin
    df["sd_hist"] = sd
    df["sue_raw"] = raw
    df["sue"] = np.clip(raw, -WINSOR, WINSOR)
    return df


def build_panel_factor(fil):
    p = pd.read_parquet(PANEL_V2, columns=["ticker", "date"],
                        filters=[("date", ">=", "2006-12-01"), ("date", "<=", "2019-12-31")])
    p["date"] = pd.to_datetime(p["date"])
    p["ticker"] = p["ticker"].astype(str)
    cal = np.sort(p["date"].unique())
    p = p[(p["date"] >= START) & (p["date"] <= END)].reset_index(drop=True)
    assert p["date"].max() < HOLDOUT
    pos = np.searchsorted(cal, p["date"].to_numpy()) - 1
    assert (pos >= 0).all()
    p["prev_td"] = cal[pos]
    # latest filing with date <= prev_td; ties on date -> latest reportperiod
    f = fil[["ticker", "date", "rp", "sue"]].rename(columns={"date": "fdate"})
    f = f.sort_values(["fdate", "rp"]).drop_duplicates(["ticker", "fdate"], keep="last")
    left = p[["ticker", "date", "prev_td"]].reset_index().sort_values("prev_td")
    m = pd.merge_asof(left, f.sort_values("fdate"), left_on="prev_td", right_on="fdate",
                      by="ticker", direction="backward", allow_exact_matches=True)
    m = m.sort_values("index").reset_index(drop=True)
    age = (m["date"] - m["fdate"]).dt.days
    m["sue"] = m["sue"].where(age <= STALE_DAYS)
    m["sue_age_days"] = age
    return m[["ticker", "date", "sue", "fdate", "rp", "sue_age_days"]].rename(
        columns={"fdate": "sue_filing_date", "rp": "sue_reportperiod"})


def main():
    t0 = time.time()
    OUT.mkdir(parents=True, exist_ok=True)
    meta = {"sf1_sha256": sha256(SF1)}
    log("hashing composite_panel_v2 ...")
    meta["composite_panel_v2_sha256"] = sha256(PANEL_V2)
    meta["composite_panel_v2_mtime"] = time.ctime(PANEL_V2.stat().st_mtime)
    df, info = load_arq()
    meta.update(info)
    log(f"ARQ {info}")
    fil = build_filings(df)
    meta["filings_finite_sue"] = int(np.isfinite(fil["sue"]).sum())
    meta["filings_neg_lag"] = int((fil["date"] < fil["rp"]).sum())
    fil.to_parquet(OUT / "sue_filings.parquet", index=False)
    log(f"filings: {len(fil):,}, finite SUE {meta['filings_finite_sue']:,}")
    fac = build_panel_factor(fil)
    meta["panel_rows"] = int(len(fac))
    meta["panel_finite_sue"] = int(fac["sue"].notna().sum())
    fac.to_parquet(OUT / "sue_factor_v2.parquet", index=False)
    (OUT / "build_sue_meta.json").write_text(json.dumps(meta, indent=2, default=str))
    log(f"panel factor rows {len(fac):,}, finite {meta['panel_finite_sue']:,} ({time.time()-t0:.0f}s)")


if __name__ == "__main__":
    main()
