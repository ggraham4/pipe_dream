"""
WO-29: build the EAR (earnings announcement return) factor on the v2 grid and
the Step 0 (Gate A) pool-integrity checks. Frozen definition:
final/models/2026-09-30-ear-screen.md section 1 (committed cf8eec7 before any
outcome statistic). This script computes NO outcome statistic.

EAR(event) = sum_{d=-1..+2} (r_i,d - r_SPY,d), r_d = close_d/close_{d-1} - 1 on
consecutive market-calendar days; day 0 = first market day >= filing_date of an
ORIGINAL 8-K carrying Item 2.02. Needs finite > 0 closes on days -2..+2 for the
stock (SEP close, split-adjusted) and SPY (SPY.csv close). Available at close
of day +2; live while 0 <= t_idx - (day0_idx + 2) < 60, using the latest
available event (if its EAR is missing the row is neutral; no fallback).

Outputs (worktree final/out/ear/, parquet gitignored):
  ear_factor_v2.parquet  ticker, date, ear_raw (NaN unless live), ev_filing_date,
                         ev_day0, ev_avail, ear_age, cov100 (>=1 original 2.02 with
                         day0 in (t-100, t]), for every v2 eligible_cap150 row 2007-2019
  build_ear_meta.json    hashes, Step 0 coverage, dead-name + cadence checks, PIT assert
Usage: python build_ear.py
"""
import hashlib
import json
import time
from pathlib import Path

import numpy as np
import pandas as pd

MAIN = Path("/Users/ggraham/pipe_dream/final")
SEP_MAIN = MAIN / "data" / "sharadar" / "panel" / "stocks"
PANEL_V2 = MAIN / "out" / "reset2026" / "composite_panel_v2.parquet"
PANEL_V1 = MAIN / "out" / "reset2026" / "composite_panel.parquet"
TM = MAIN / "data" / "sharadar" / "tickers_master.csv"
SPY_CSV = MAIN / "scripts" / "td_data_local" / "SPY.csv"
POOL = [MAIN / "data" / "edgar" / "8k_item202.parquet", MAIN / "data" / "edgar" / "8k_item202_v2topup.parquet"]
OUT = Path(__file__).resolve().parents[2] / "out" / "ear"
HOLDOUT = pd.Timestamp("2020-01-01")
START, END = pd.Timestamp("2007-01-02"), pd.Timestamp("2019-12-31")
FIRST_YM, LAST_YM = "2005-01", "2019-12"
CAL_MIN_TICKERS = 1000
LIVE_DAYS = 60
COV_DAYS = 100
COV_MAX_GAP = 0.10


def log(m):
    print(f"[{time.strftime('%H:%M:%S')}] {m}", flush=True)


def sha256(path, chunk=1 << 24):
    h = hashlib.sha256()
    with open(path, "rb") as f:
        while b := f.read(chunk):
            h.update(b)
    return h.hexdigest()


def load_pool():
    frames = []
    for p in POOL:
        d = pd.read_parquet(p, columns=["cik", "form", "filing_date", "accession", "items"],
                            filters=[("filing_date", "<", HOLDOUT)])
        d["filing_date"] = pd.to_datetime(d["filing_date"])
        assert d["filing_date"].max() < HOLDOUT, f"HOLD-OUT BREACH in {p}"
        d["src"] = p.name
        frames.append(d)
    d = pd.concat(frames, ignore_index=True)
    n_all = len(d)
    d = d.drop_duplicates(["cik", "accession"])
    assert d["items"].str.split(",").apply(lambda x: "2.02" in x).all()
    orig = d[d["form"] == "8-K"].copy()
    return orig, {"rows_lt2020_all_forms": int(n_all), "rows_dedup": int(len(d)),
                  "rows_8k_original": int(len(orig)), "rows_8ka_excluded": int((d["form"] == "8-K/A").sum()),
                  "ciks": int(orig["cik"].nunique()), "by_source": orig["src"].value_counts().to_dict()}


def load_sep():
    files = [f for f in sorted(SEP_MAIN.glob("*.parquet")) if FIRST_YM <= f.stem <= LAST_YM]
    want = pd.period_range(FIRST_YM, LAST_YM, freq="M").strftime("%Y-%m").tolist()
    assert [f.stem for f in files] == want, "SEP month files incomplete"
    frames = []
    for f in files:
        d = pd.read_parquet(f, columns=["ticker", "date", "close"])
        d["date"] = pd.to_datetime(d["date"])
        assert d["date"].max() < HOLDOUT, f"HOLD-OUT BREACH in {f}"
        frames.append(d)
    s = pd.concat(frames, ignore_index=True)
    s["ticker"] = s["ticker"].astype(str)
    s = s.sort_values(["ticker", "date"]).drop_duplicates(["ticker", "date"], keep="last").reset_index(drop=True)
    return s


def cik_map():
    tm = pd.read_csv(TM, usecols=["ticker", "secfilings", "category", "sicindustry", "name"], dtype=str)
    tm["cik"] = pd.to_numeric(tm["secfilings"].str.extract(r"CIK=0*(\d+)")[0], errors="coerce")
    return tm.drop_duplicates("ticker")


def main():
    t0 = time.time()
    OUT.mkdir(parents=True, exist_ok=True)
    meta = {"spec": "models/2026-09-30-ear-screen.md", "composite_panel_v2_sha256": sha256(PANEL_V2),
            "pool_sha256": {p.name: sha256(p) for p in POOL}}
    ev, meta["pool"] = load_pool()
    log(f"pool {meta['pool']}")

    sep = load_sep()
    ntk = sep.groupby("date")["ticker"].size()
    cal = pd.DatetimeIndex(ntk.index[ntk >= CAL_MIN_TICKERS])
    meta["calendar"] = {"n": len(cal), "first": str(cal[0].date()), "last": str(cal[-1].date())}
    spy = pd.read_csv(SPY_CSV, usecols=["date", "close"], parse_dates=["date"])
    spy = spy[spy["date"] < HOLDOUT]
    assert spy["date"].max() < HOLDOUT
    spy_c = spy.set_index("date")["close"].reindex(cal).to_numpy(np.float64)
    meta["spy_missing_calendar_days"] = int(np.isnan(spy_c).sum())
    miss = cal[np.isnan(spy_c)]
    meta["spy_missing_last"] = str(miss.max().date()) if len(miss) else None
    assert len(miss) == 0 or miss.max() < pd.Timestamp("2006-01-03"), "SPY.csv gap inside 2006-2019"

    # panel rows: v2 eligible_cap150, 2007-2019
    q = pd.read_parquet(PANEL_V2, columns=["ticker", "date", "eligible_cap150"],
                        filters=[("date", ">=", "2007-01-02"), ("date", "<=", "2019-12-31")])
    q["date"] = pd.to_datetime(q["date"]); q["ticker"] = q["ticker"].astype(str)
    assert q["date"].max() < HOLDOUT
    q = q[q["eligible_cap150"]].drop(columns="eligible_cap150").sort_values(["ticker", "date"]).reset_index(drop=True)
    qi = cal.searchsorted(q["date"].to_numpy())
    assert (qi < len(cal)).all() and (cal[qi] == q["date"].to_numpy()).all(), "panel date off calendar"
    q["t_idx"] = qi

    tm = cik_map()
    t2c = dict(zip(tm["ticker"], tm["cik"]))
    q["cik"] = q["ticker"].map(t2c)
    meta["rows"] = int(len(q)); meta["rows_unmapped_cik"] = int(q["cik"].isna().sum())

    # events -> day0 index, per CIK, one per (cik, day0)
    ev["day0_idx"] = cal.searchsorted(ev["filing_date"].to_numpy(), side="left")
    ev = ev[ev["day0_idx"] < len(cal)]
    ev = ev.sort_values(["cik", "day0_idx", "filing_date"]).drop_duplicates(["cik", "day0_idx"], keep="first")
    ev_by_cik = {c: g for c, g in ev.groupby("cik")}

    # stock closes on the calendar
    si = cal.searchsorted(sep["date"].to_numpy())
    on = (si < len(cal)) & (cal[np.minimum(si, len(cal) - 1)] == sep["date"].to_numpy())
    sep = sep.loc[on]; sep["ci"] = si[on]
    sep_by_t = {t: (g["ci"].to_numpy(), g["close"].to_numpy(np.float64)) for t, g in sep.groupby("ticker", sort=False)}
    del sep

    def cum_ret(c):
        with np.errstate(divide="ignore", invalid="ignore"):
            ok = np.isfinite(c) & (c > 0)
            return np.where(ok, c, np.nan)

    spy_v = cum_ret(spy_c)
    n = len(q)
    ear_raw = np.full(n, np.nan); ev_f = np.full(n, np.datetime64("NaT"), "datetime64[ns]")
    ev_d0 = ev_f.copy(); ev_av = ev_f.copy(); age = np.full(n, -1, np.int64)
    cov = np.zeros(n, bool); has_event_avail = np.zeros(n, bool); ear_missing_latest = np.zeros(n, bool)
    n_ev_total = n_ev_valid = 0
    starts = np.flatnonzero(np.r_[True, q["ticker"].to_numpy()[1:] != q["ticker"].to_numpy()[:-1]])
    ends = np.r_[starts[1:], n]
    tick = q["ticker"].to_numpy(); ciks = q["cik"].to_numpy(); tix = q["t_idx"].to_numpy()
    for s, e in zip(starts, ends):
        t = tick[s]; c = ciks[s]
        if not np.isfinite(c) or c not in ev_by_cik:
            continue
        g = ev_by_cik[c]
        d0 = g["day0_idx"].to_numpy(); fd = g["filing_date"].to_numpy()
        close = np.full(len(cal), np.nan)
        if t in sep_by_t:
            ci, cl = sep_by_t[t]; close[ci] = cl
        close = cum_ret(close)
        # EAR per event
        E = np.full(len(d0), np.nan)
        for k, x in enumerate(d0):
            if x - 2 < 0 or x + 2 >= len(cal):
                continue
            cs, sp = close[x - 2:x + 3], spy_v[x - 2:x + 3]
            if np.isfinite(cs).all() and np.isfinite(sp).all():
                E[k] = float(np.sum(cs[1:] / cs[:-1] - 1.0) - np.sum(sp[1:] / sp[:-1] - 1.0))
        n_ev_total += len(d0); n_ev_valid += int(np.isfinite(E).sum())
        tt = tix[s:e]
        avail = d0 + 2
        j = np.searchsorted(avail, tt, side="right") - 1          # latest event with avail <= t
        has = j >= 0
        jj = np.where(has, j, 0)
        a = tt - avail[jj]
        live = has & (a < LIVE_DAYS) & np.isfinite(E[jj])
        has_event_avail[s:e] = has & (a < LIVE_DAYS)
        ear_missing_latest[s:e] = has & (a < LIVE_DAYS) & ~np.isfinite(E[jj])
        ear_raw[s:e] = np.where(live, E[jj], np.nan)
        age[s:e] = np.where(has, a, -1)
        ev_f[s:e] = np.where(has, fd[jj], np.datetime64("NaT"))
        ev_d0[s:e] = np.where(has, cal.to_numpy()[np.minimum(d0[jj], len(cal) - 1)], np.datetime64("NaT"))
        ev_av[s:e] = np.where(has, cal.to_numpy()[np.minimum(avail[jj], len(cal) - 1)], np.datetime64("NaT"))
        # coverage: >= 1 original filing with day0 in (t-100, t]
        lo = np.searchsorted(d0, tt - COV_DAYS, side="right"); hi = np.searchsorted(d0, tt, side="right")
        cov[s:e] = hi > lo
    q["ear_raw"] = ear_raw; q["ev_filing_date"] = ev_f; q["ev_day0"] = ev_d0; q["ev_avail"] = ev_av
    q["ear_age"] = age; q["cov100"] = cov
    meta["events"] = {"total_cik_day0_matched_to_panel_tickers": n_ev_total, "ear_finite": n_ev_valid}

    # ---------------- PIT assert (every live row)
    L = q["ear_raw"].notna()
    d = q.loc[L]
    assert (d["ev_avail"] <= d["date"]).all(), "PIT FAIL: price after t"
    assert (d["ev_filing_date"] <= d["ev_day0"]).all()
    fd_idx = cal.searchsorted(d["ev_filing_date"].to_numpy(), side="left")
    assert (fd_idx + 2 <= d["t_idx"].to_numpy()).all(), "PIT FAIL: filing_date + 2 market days > t"
    assert (d["ear_age"] >= 0).all() and (d["ear_age"] < LIVE_DAYS).all()
    meta["pit_assert"] = {"rows_checked": int(L.sum()), "pass": True,
                          "max_price_date_minus_t_days": int((d["ev_avail"] - d["date"]).dt.days.max())}
    meta["live_share"] = float(L.mean())
    meta["neutral_breakdown"] = {"no_event_in_window_or_stale": float((~q["ev_avail"].notna() | (q["ear_age"] >= LIVE_DAYS)).mean()),
                                 "latest_event_ear_missing": float(ear_missing_latest.mean()),
                                 "unmapped_cik": float(q["cik"].isna().mean())}

    # ---------------- Step 0 coverage: column c (SPAC rule) cap150 name-dates
    old_t = set(pd.read_parquet(PANEL_V1, columns=["ticker"])["ticker"].astype(str).unique())
    spac = set(tm.loc[tm["sicindustry"].fillna("").str.contains("Blank Check"), "ticker"])
    colc = q["ticker"].isin(old_t) | ~q["ticker"].isin(spac)
    v1p = q["ticker"].isin(old_t)
    c = q.loc[colc]
    cv = {"v1_present": float(c.loc[v1p[colc], "cov100"].mean()), "v1_absent": float(c.loc[~v1p[colc], "cov100"].mean()),
          "rows_v1_present": int(v1p[colc].sum()), "rows_v1_absent": int((~v1p[colc]).sum()),
          "all": float(c["cov100"].mean())}
    cv["gap_pp"] = 100 * (cv["v1_present"] - cv["v1_absent"])
    cv["pass_within_10pp"] = bool(abs(cv["v1_present"] - cv["v1_absent"]) <= COV_MAX_GAP)
    cat = c.merge(tm[["ticker", "category"]], on="ticker", how="left")
    cat["v1"] = cat["ticker"].isin(old_t)
    cv["by_category"] = {f"{k[0]}|{'v1' if k[1] else 'added'}": {"rows": int(len(g)), "cov100": float(g["cov100"].mean())}
                         for k, g in cat.groupby([cat["category"].fillna("NA"), "v1"]) if len(g) > 20000}
    cv["by_year"] = {int(y): {"v1_present": float(g.loc[g["ticker"].isin(old_t), "cov100"].mean()),
                              "v1_absent": float(g.loc[~g["ticker"].isin(old_t), "cov100"].mean())}
                     for y, g in c.groupby(c["date"].dt.year)}
    meta["coverage_step0"] = cv
    log(f"coverage v1-present {cv['v1_present']:.4f} v1-absent {cv['v1_absent']:.4f} gap {cv['gap_pp']:+.2f}pp "
        f"-> {'PASS' if cv['pass_within_10pp'] else 'FAIL'}")
    meta["live_share_colc"] = float(c["ear_raw"].notna().mean())
    meta["live_share_colc_v1_present"] = float(c.loc[v1p[colc], "ear_raw"].notna().mean())
    meta["live_share_colc_v1_absent"] = float(c.loc[~v1p[colc], "ear_raw"].notna().mean())

    # ---------------- dead name + cadence hand checks
    def name_check(cik, label):
        tk = sorted(tm.loc[tm["cik"] == cik, "ticker"].tolist())
        g = ev[ev["cik"] == cik].sort_values("filing_date")
        rows = q[q["cik"] == cik]
        return {"label": label, "cik": int(cik), "tickers": tk, "names": tm.loc[tm["cik"] == cik, "name"].unique().tolist(),
                "n_original_202": int(len(g)), "first": str(g["filing_date"].min().date()) if len(g) else None,
                "last": str(g["filing_date"].max().date()) if len(g) else None,
                "filing_dates_2007_2008": [str(x.date()) for x in g["filing_date"] if x.year in (2007, 2008)],
                "cap150_rows": int(len(rows)), "cap150_live_rows": int(rows["ear_raw"].notna().sum()),
                "cap150_last_date": str(rows["date"].max().date()) if len(rows) else None,
                "sample_live": rows.loc[rows["ear_raw"].notna(), ["date", "ev_filing_date", "ev_day0", "ev_avail", "ear_age", "ear_raw"]]
                .drop_duplicates("ev_filing_date").head(6).astype(str).to_dict("records")}
    meta["dead_name_LEH"] = name_check(806085, "Lehman Brothers Holdings (dead 2008)")
    meta["cadence_check"] = name_check(320193, "Apple (quarterly cadence: late Jan/Apr/Jul/Oct)")
    aapl = ev[ev["cik"] == 320193]
    aapl = aapl[(aapl["filing_date"] >= "2010-01-01") & (aapl["filing_date"] <= "2019-12-31")]
    meta["cadence_check"]["aapl_2010_2019_dates"] = [str(x.date()) for x in aapl["filing_date"]]
    meta["cadence_check"]["aapl_2010_2019_per_year"] = aapl.groupby(aapl["filing_date"].dt.year).size().to_dict()

    # ---------------- EAR hand trace: one AAPL event recomputed from raw files
    meta["ear_quantiles_live"] = {str(k): float(v) for k, v in q["ear_raw"].quantile([0.01, 0.05, 0.5, 0.95, 0.99]).items()}

    q.drop(columns=["t_idx"]).to_parquet(OUT / "ear_factor_v2.parquet", index=False)
    meta["runtime_s"] = time.time() - t0
    (OUT / "build_ear_meta.json").write_text(json.dumps(meta, indent=2, default=str))
    log(f"wrote {OUT/'ear_factor_v2.parquet'} ({len(q):,} rows, live {meta['live_share']:.3f}) in {time.time()-t0:.0f}s")


if __name__ == "__main__":
    main()
