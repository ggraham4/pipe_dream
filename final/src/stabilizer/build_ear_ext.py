"""
WO-42 S3: the frozen WO-29 EAR factor extended to 2026-07-30.
Pre-registration: final/models/2026-10-01-stabilizer-rule-ear.md (3c6a321).

This is final/src/ear/build_ear.py's factor logic copied with ONLY the bounds
changed (build_ear.main() hard-codes the 2019 literals, so it cannot be
re-pointed; the module is imported for its constants and helpers and is not
edited). Changes vs the frozen builder:
  SEP months   2005-01..2026-07          (was ..2019-12)
  panel rows   2007-01-02..2026-07-30    (was ..2019-12-31)
  8-K pool     filing_date <= 2026-07-30 (was < 2020-01-01), plus the WO-42
               top-up file for CIKs first seen in 2020+
  SPY.csv      rows <= 2026-07-31
The definition is unchanged: original 8-K Item 2.02; day 0 = first market day
>= filing_date; EAR = sum_{d=-1..+2}(r_i,d - r_SPY,d); available at close of
day +2; live while 0 <= t_idx - (day0_idx + 2) < 60; latest available event,
no fallback.

IDENTITY (hard assert): every row dated <= 2019-12-31 must equal WO-29's
frozen ear_factor_v2.parquet. No label is read here; no outcome statistic.

Outputs (final/out/stabilizer/): ear_factor_ext.parquet (gitignored),
build_ear_ext_meta.json.
Usage: python build_ear_ext.py
"""
import json
import sys
import time
from pathlib import Path

import numpy as np
import pandas as pd

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE.parent / "ear"))
import build_ear as B                  # noqa: E402  (constants + helpers only; main() never called)

OUT = HERE.parents[1] / "out" / "stabilizer"
EXT = OUT / "ear_factor_ext.parquet"
META = OUT / "build_ear_ext_meta.json"
FROZEN = Path("/Users/ggraham/pipe_dream/.claude/worktrees/agent-ad838240373d22717/final/out/ear/ear_factor_v2.parquet")
TOPUP = OUT / "8k_item202_2020topup.parquet"
POOL = list(B.POOL) + [TOPUP]
FROZEN_HI = pd.Timestamp("2019-12-31")
FIRST_YM, LAST_YM = "2005-01", "2026-07"
START, HI = pd.Timestamp("2007-01-02"), pd.Timestamp("2026-07-30")
log = B.log


def load_pool():
    frames = []
    for p in POOL:
        d = pd.read_parquet(p, columns=["cik", "form", "filing_date", "accession", "items"])
        d["filing_date"] = pd.to_datetime(d["filing_date"])
        d = d[d["filing_date"] <= HI].copy()
        d["src"] = p.name
        frames.append(d)
    d = pd.concat(frames, ignore_index=True)
    n_all = len(d)
    d = d.drop_duplicates(["cik", "accession"])
    assert d["items"].str.split(",").apply(lambda x: "2.02" in x).all()
    orig = d[d["form"] == "8-K"].copy()
    return orig, {"rows_all_forms": int(n_all), "rows_dedup": int(len(d)), "rows_8k_original": int(len(orig)),
                  "rows_8ka_excluded": int((d["form"] == "8-K/A").sum()), "ciks": int(orig["cik"].nunique()),
                  "by_source": orig["src"].value_counts().to_dict(),
                  "original_by_year_2019plus": {int(k): int(v) for k, v in
                                                orig[orig["filing_date"] >= "2019-01-01"].groupby(orig["filing_date"].dt.year).size().items()}}


def load_sep():
    files = [f for f in sorted(B.SEP_MAIN.glob("*.parquet")) if FIRST_YM <= f.stem <= LAST_YM]
    want = pd.period_range(FIRST_YM, LAST_YM, freq="M").strftime("%Y-%m").tolist()
    assert [f.stem for f in files] == want, "SEP month files incomplete"
    frames = []
    for f in files:
        d = pd.read_parquet(f, columns=["ticker", "date", "close"])
        d["date"] = pd.to_datetime(d["date"])
        frames.append(d)
    s = pd.concat(frames, ignore_index=True)
    s["ticker"] = s["ticker"].astype(str)
    return s.sort_values(["ticker", "date"]).drop_duplicates(["ticker", "date"], keep="last").reset_index(drop=True)


def identity(q):
    ref = pd.read_parquet(FROZEN)
    ref["date"] = pd.to_datetime(ref["date"]); ref["ticker"] = ref["ticker"].astype(str)
    assert ref["date"].max() <= FROZEN_HI
    pre = q[q["date"] <= FROZEN_HI]
    assert len(pre) == len(ref), f"IDENTITY FAIL row count {len(pre)} vs {len(ref)}"
    a = ref.merge(pre, on=["ticker", "date"], how="left", suffixes=("_ref", "_got"), indicator=True)
    assert (a["_merge"] == "both").all() and len(a) == len(ref), "IDENTITY FAIL frozen rows missing"
    x, y = a["ear_raw_got"].to_numpy(np.float64), a["ear_raw_ref"].to_numpy(np.float64)
    assert (np.isnan(x) == np.isnan(y)).all(), f"IDENTITY FAIL NaN pattern on {int((np.isnan(x) != np.isnan(y)).sum())} rows"
    d = np.abs(x - y)[~np.isnan(y)]
    mx = float(d.max())
    assert mx <= 1e-12, f"IDENTITY FAIL ear_raw max abs diff {mx}"
    out = {"rows": int(len(a)), "ear_raw_finite": int((~np.isnan(y)).sum()), "ear_raw_max_abs_diff": mx}
    for c in ("ear_age", "cov100"):
        assert (a[f"{c}_got"].to_numpy() == a[f"{c}_ref"].to_numpy()).all(), f"IDENTITY FAIL {c}"
        out[f"{c}_exact"] = True
    for c in ("ev_filing_date", "ev_day0", "ev_avail"):
        g, r = pd.to_datetime(a[f"{c}_got"]), pd.to_datetime(a[f"{c}_ref"])
        assert ((g == r) | (g.isna() & r.isna())).all(), f"IDENTITY FAIL {c}"
        out[f"{c}_exact"] = True
    assert (a["cik_got"].fillna(-1).to_numpy() == a["cik_ref"].fillna(-1).to_numpy()).all(), "IDENTITY FAIL cik"
    out["pass"] = True
    return out


def main():
    t0 = time.time()
    OUT.mkdir(parents=True, exist_ok=True)
    meta = {"prereg": "final/models/2026-10-01-stabilizer-rule-ear.md @ 3c6a321",
            "composite_panel_v2_sha256": B.sha256(B.PANEL_V2), "pool_sha256": {p.name: B.sha256(p) for p in POOL},
            "frozen_factor_sha256": B.sha256(FROZEN), "bounds": {"sep": [FIRST_YM, LAST_YM], "panel": [str(START.date()), str(HI.date())]}}
    ev, meta["pool"] = load_pool()
    log(f"pool {meta['pool']}")

    sep = load_sep()
    ntk = sep.groupby("date")["ticker"].size()
    cal = pd.DatetimeIndex(ntk.index[ntk >= B.CAL_MIN_TICKERS])
    meta["calendar"] = {"n": len(cal), "first": str(cal[0].date()), "last": str(cal[-1].date())}
    spy = pd.read_csv(B.SPY_CSV, usecols=["date", "close"], parse_dates=["date"])
    spy = spy[spy["date"] <= cal[-1]]
    spy_c = spy.set_index("date")["close"].reindex(cal).to_numpy(np.float64)
    miss = cal[np.isnan(spy_c)]
    meta["spy_missing_calendar_days"] = int(len(miss))
    meta["spy_missing_last"] = str(miss.max().date()) if len(miss) else None
    assert len(miss) == 0 or miss.max() < pd.Timestamp("2006-01-03"), "SPY.csv gap inside 2006-2026"

    q = pd.read_parquet(B.PANEL_V2, columns=["ticker", "date", "eligible_cap150"],
                        filters=[("date", ">=", "2007-01-02"), ("date", "<=", str(HI.date()))])
    q["date"] = pd.to_datetime(q["date"]); q["ticker"] = q["ticker"].astype(str)
    assert q["date"].max() <= HI
    q = q[q["eligible_cap150"]].drop(columns="eligible_cap150").sort_values(["ticker", "date"]).reset_index(drop=True)
    qi = cal.searchsorted(q["date"].to_numpy())
    assert (qi < len(cal)).all() and (cal[qi] == q["date"].to_numpy()).all(), "panel date off calendar"
    q["t_idx"] = qi

    tm = B.cik_map()
    t2c = dict(zip(tm["ticker"], tm["cik"]))
    q["cik"] = q["ticker"].map(t2c)
    meta["rows"] = int(len(q)); meta["rows_unmapped_cik"] = int(q["cik"].isna().sum())

    ev["day0_idx"] = cal.searchsorted(ev["filing_date"].to_numpy(), side="left")
    ev = ev[ev["day0_idx"] < len(cal)]
    ev = ev.sort_values(["cik", "day0_idx", "filing_date"]).drop_duplicates(["cik", "day0_idx"], keep="first")
    ev_by_cik = {c: g for c, g in ev.groupby("cik")}

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
    cov = np.zeros(n, bool); ear_missing_latest = np.zeros(n, bool)
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
        j = np.searchsorted(avail, tt, side="right") - 1
        has = j >= 0
        jj = np.where(has, j, 0)
        a = tt - avail[jj]
        live = has & (a < B.LIVE_DAYS) & np.isfinite(E[jj])
        ear_missing_latest[s:e] = has & (a < B.LIVE_DAYS) & ~np.isfinite(E[jj])
        ear_raw[s:e] = np.where(live, E[jj], np.nan)
        age[s:e] = np.where(has, a, -1)
        ev_f[s:e] = np.where(has, fd[jj], np.datetime64("NaT"))
        ev_d0[s:e] = np.where(has, cal.to_numpy()[np.minimum(d0[jj], len(cal) - 1)], np.datetime64("NaT"))
        ev_av[s:e] = np.where(has, cal.to_numpy()[np.minimum(avail[jj], len(cal) - 1)], np.datetime64("NaT"))
        lo = np.searchsorted(d0, tt - B.COV_DAYS, side="right"); hi = np.searchsorted(d0, tt, side="right")
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
    assert (d["ear_age"] >= 0).all() and (d["ear_age"] < B.LIVE_DAYS).all()
    meta["pit_assert"] = {"rows_checked": int(L.sum()), "pass": True,
                          "max_price_date_minus_t_days": int((d["ev_avail"] - d["date"]).dt.days.max())}

    # ---------------- identity vs the frozen WO-29 factor (before anything else is reported)
    meta["identity_pre2020"] = identity(q)
    log(f"IDENTITY OK {meta['identity_pre2020']}")

    # ---------------- coverage (column c = SPAC rule), by year; no outcome involved
    old_t = set(pd.read_parquet(B.PANEL_V1, columns=["ticker"])["ticker"].astype(str).unique())
    spac = set(tm.loc[tm["sicindustry"].fillna("").str.contains("Blank Check"), "ticker"])
    colc = q["ticker"].isin(old_t) | ~q["ticker"].isin(spac)
    c = q.loc[colc]
    yr = c["date"].dt.year
    first_year = c.groupby("ticker")["date"].transform("min").dt.year
    meta["colc_by_year"] = {int(y): {"rows": int(len(g)), "cov100": float(g["cov100"].mean()),
                                     "live_share": float(g["ear_raw"].notna().mean()),
                                     "unmapped_cik_share": float(g["cik"].isna().mean())}
                            for y, g in c.groupby(yr)}
    post = c[c["date"] > FROZEN_HI]
    newn = first_year[c["date"] > FROZEN_HI] >= 2020
    meta["coverage_2020plus"] = {"all_cov100": float(post["cov100"].mean()), "all_live": float(post["ear_raw"].notna().mean()),
                                 "names_first_seen_2020plus_cov100": float(post.loc[newn, "cov100"].mean()),
                                 "names_first_seen_2020plus_live": float(post.loc[newn, "ear_raw"].notna().mean()),
                                 "names_first_seen_2020plus_row_share": float(newn.mean()),
                                 "names_seen_pre2020_cov100": float(post.loc[~newn, "cov100"].mean()),
                                 "names_seen_pre2020_live": float(post.loc[~newn, "ear_raw"].notna().mean())}
    pre = c[c["date"] <= FROZEN_HI]
    meta["coverage_2007_2019"] = {"all_cov100": float(pre["cov100"].mean()), "all_live": float(pre["ear_raw"].notna().mean())}
    log(f"coverage 2020+ {meta['coverage_2020plus']} | 2007-2019 {meta['coverage_2007_2019']}")

    q.drop(columns=["t_idx"]).to_parquet(EXT, index=False)
    meta["ext_sha256"] = B.sha256(EXT)
    meta["rows_2020plus"] = int((q["date"] > FROZEN_HI).sum())
    meta["runtime_s"] = time.time() - t0
    META.write_text(json.dumps(meta, indent=2, default=str))
    log(f"wrote {EXT} ({len(q):,} rows) in {time.time()-t0:.0f}s")


if __name__ == "__main__":
    main()
