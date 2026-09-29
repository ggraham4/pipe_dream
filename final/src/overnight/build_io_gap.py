"""
Overnight vs intraday return decomposition factor `io_gap` on the v2 grid.
Frozen definition: models/2026-09-29-overnight-intraday-screen.md.

Prices: Sharadar SEP data/sharadar/panel/stocks/2005-01..2019-12 (files after
2019-12 are never opened; any row dated >= 2020-01-01 is an error). SEP
open/high/low/close are split-adjusted; closeadj is split AND dividend adjusted.

Per ticker i, trading day d (prev = i's previous SEP row):
  r_id(d) = log(close_d / open_d)                          intraday
  r_tot(d) = log(closeadj_d / closeadj_prev)               close-to-close total
  r_on(d) = r_tot(d) - r_id(d)                             overnight, net of
                                                           dividends and splits
Day d is VALID iff open, close, closeadj, closeadj_prev finite and > 0;
  volume > 0; low*(1-1e-6) <= open <= high*(1+1e-6); prev row is at most
  7 calendar days before d; |r_id| <= 0.7 and |r_on| <= 0.7.
io_gap(i, t) = 252 * [ mean over VALID days in W of (r_id - r_on) ], where W is
  the 252 market trading days ending at t inclusive (market calendar = SEP
  dates with >= 1000 tickers). NaN when fewer than 200 VALID days in W. Sign +1.
PIT: every price feeding io_gap(i, t) is dated <= t (close_t is known before the
  label's entry at open[t+1]); asserted row by row.

Outputs (worktree final/out/overnight/): io_gap_factor_v2.parquet (gitignored),
build_io_gap_meta.json. Reads the v2 panel and SEP read-only.
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
OUT = Path(__file__).resolve().parents[2] / "out" / "overnight"
START, END = pd.Timestamp("2007-01-02"), pd.Timestamp("2019-12-31")
HOLDOUT = pd.Timestamp("2020-01-01")
FIRST_YM, LAST_YM = "2005-01", "2019-12"
WINDOW, MIN_VALID = 252, 200
MAX_ABS_LOG = 0.7
MAX_GAP_DAYS = 7
CAL_MIN_TICKERS = 1000
COL = "io_gap"


def log(m):
    print(f"[{time.strftime('%H:%M:%S')}] {m}", flush=True)


def sha256(path, chunk=1 << 24):
    h = hashlib.sha256()
    with open(path, "rb") as f:
        while b := f.read(chunk):
            h.update(b)
    return h.hexdigest()


def sep_files():
    files = [f for f in sorted(SEP_MAIN.glob("*.parquet")) if FIRST_YM <= f.stem <= LAST_YM]
    want = pd.period_range(FIRST_YM, LAST_YM, freq="M").strftime("%Y-%m").tolist()
    assert [f.stem for f in files] == want, "SEP month files incomplete"
    return files


def files_digest(files):
    h = hashlib.sha256()
    for f in files:
        h.update(f"{f.parent.name}/{f.name}:{sha256(f)}\n".encode())
    return h.hexdigest()


def load_sep(files):
    cols = ["ticker", "date", "open", "high", "low", "close", "volume", "closeadj"]
    frames = []
    for f in files:
        d = pd.read_parquet(f, columns=cols)
        d["date"] = pd.to_datetime(d["date"])
        assert d["date"].max() < HOLDOUT, f"HOLD-OUT BREACH in {f}"
        assert (d["date"].dt.strftime("%Y-%m") == f.stem).all(), f"{f} has rows outside its month"
        frames.append(d)
    s = pd.concat(frames, ignore_index=True)
    s["ticker"] = s["ticker"].astype(str)
    s = s.sort_values(["ticker", "date"]).drop_duplicates(["ticker", "date"], keep="last").reset_index(drop=True)
    return s


def daily_components(s):
    """Adds r_id, r_on, valid and the per-reason flags used by validation."""
    first = s["ticker"].ne(s["ticker"].shift())
    prev_adj = s["closeadj"].shift().where(~first)
    prev_date = s["date"].shift().where(~first)
    o, h, l, c, a = (s[k].to_numpy(np.float64) for k in ("open", "high", "low", "close", "closeadj"))
    pa = prev_adj.to_numpy(np.float64)
    pos = lambda x: np.isfinite(x) & (x > 0)
    with np.errstate(divide="ignore", invalid="ignore"):
        r_id = np.log(c / o)
        r_on = np.log(a / pa) - r_id
    f = pd.DataFrame(index=s.index)
    f["bad_open"] = ~pos(o)
    f["bad_close"] = ~(pos(c) & pos(a))
    f["no_prev"] = ~pos(pa) | ((s["date"] - prev_date).dt.days > MAX_GAP_DAYS).fillna(True).to_numpy()
    f["zero_volume"] = ~(s["volume"].to_numpy(np.float64) > 0)
    f["open_outside_range"] = pos(o) & np.isfinite(h) & np.isfinite(l) & (
        (o < l * (1 - 1e-6)) | (o > h * (1 + 1e-6)))
    f["extreme"] = (np.abs(r_id) > MAX_ABS_LOG) | (np.abs(r_on) > MAX_ABS_LOG)
    valid = ~f.any(axis=1).to_numpy()
    f["valid"] = valid
    # descriptive only, not a filter: open printed exactly at the prior split-adjusted close
    prev_close = s["close"].shift().where(~first).to_numpy(np.float64)
    f["open_eq_prev_close"] = pos(o) & (o == prev_close)
    s["r_id"] = np.where(valid, r_id, 0.0)
    s["r_on"] = np.where(valid, r_on, 0.0)
    s["valid"] = valid
    return s, f


def market_calendar(s):
    n = s.groupby("date")["ticker"].size()
    return pd.DatetimeIndex(n.index[n >= CAL_MIN_TICKERS])


def io_gap_for(s, cal, q):
    """q: frame (ticker, date) of panel rows. Returns io_gap, n_valid, first/last price date used."""
    ci = cal.searchsorted(s["date"].to_numpy(), side="left")
    on_cal = (ci < len(cal)) & (cal[np.minimum(ci, len(cal) - 1)] == s["date"].to_numpy())
    s = s.loc[on_cal].copy()          # off-calendar SEP rows (holiday prints) never enter W
    s["di"] = ci[on_cal]
    s["g"] = s["r_id"] - s["r_on"]
    s["cg"] = s.groupby("ticker")["g"].cumsum()
    s["cid"] = s.groupby("ticker")["r_id"].cumsum()
    s["cn"] = s.groupby("ticker")["valid"].cumsum()
    out = np.full(len(q), np.nan); nv = np.zeros(len(q), np.int64); out_id = np.full(len(q), np.nan)
    first_used = np.full(len(q), np.datetime64("NaT"), "datetime64[ns]")
    last_used = first_used.copy()
    qi = cal.searchsorted(q["date"].to_numpy(), side="left")
    q_on = (qi < len(cal)) & (cal[np.minimum(qi, len(cal) - 1)] == q["date"].to_numpy())
    assert q_on.all(), "panel date not on the market calendar"
    grp = {t: g for t, g in s.groupby("ticker", sort=False)}
    for t, idx in q.groupby("ticker", sort=False).indices.items():
        g = grp.get(t)
        if g is None:
            continue
        di, cg, cn, cid = g["di"].to_numpy(), g["cg"].to_numpy(), g["cn"].to_numpy(), g["cid"].to_numpy()
        dates = g["date"].to_numpy()
        hi_d = qi[idx]; lo_d = hi_d - WINDOW          # W = (lo_d, hi_d]
        hi = np.searchsorted(di, hi_d, side="right") - 1
        lo = np.searchsorted(di, lo_d, side="right") - 1
        ok = hi >= 0
        cg_hi = np.where(ok, cg[np.maximum(hi, 0)], 0.0); cn_hi = np.where(ok, cn[np.maximum(hi, 0)], 0)
        cg_lo = np.where(lo >= 0, cg[np.maximum(lo, 0)], 0.0); cn_lo = np.where(lo >= 0, cn[np.maximum(lo, 0)], 0)
        n = cn_hi - cn_lo
        with np.errstate(invalid="ignore", divide="ignore"):
            v = WINDOW * (cg_hi - cg_lo) / n
            vid = WINDOW * (np.where(ok, cid[np.maximum(hi, 0)], 0.0) - np.where(lo >= 0, cid[np.maximum(lo, 0)], 0.0)) / n
        v[n < MIN_VALID] = np.nan; vid[n < MIN_VALID] = np.nan
        out[idx] = v; nv[idx] = n; out_id[idx] = vid
        last_used[idx] = np.where(ok, dates[np.maximum(hi, 0)], np.datetime64("NaT"))
        # the day before the first in-window day supplies closeadj_prev
        first_used[idx] = np.where(lo >= 0, dates[np.maximum(lo, 0)], dates[0])
    return out, nv, first_used, last_used, out_id


def main():
    t0 = time.time()
    OUT.mkdir(parents=True, exist_ok=True)
    files = sep_files()
    meta = {"spec": "models/2026-09-29-overnight-intraday-screen.md", "window": WINDOW,
            "min_valid": MIN_VALID, "max_abs_log": MAX_ABS_LOG, "max_gap_days": MAX_GAP_DAYS,
            "composite_panel_v2_sha256": sha256(PANEL_V2), "sep_files": f"{files[0].stem}..{files[-1].stem}",
            "sep_digest": files_digest(files)}
    log(f"panel {meta['composite_panel_v2_sha256'][:16]}  sep {meta['sep_digest'][:16]}")
    s = load_sep(files)
    log(f"SEP rows {len(s):,} tickers {s['ticker'].nunique():,}")
    s, flags = daily_components(s)
    cal = market_calendar(s)
    meta["market_calendar_days"] = int(len(cal))

    q = pd.read_parquet(PANEL_V2, columns=["ticker", "date"],
                        filters=[("date", ">=", str(START.date())), ("date", "<=", str(END.date()))])
    q["date"] = pd.to_datetime(q["date"]); q["ticker"] = q["ticker"].astype(str)
    assert q["date"].max() < HOLDOUT
    q = q.drop_duplicates(["ticker", "date"]).reset_index(drop=True)
    v, nv, first_used, last_used, vid = io_gap_for(s[["ticker", "date", "r_id", "r_on", "valid"]], cal, q)
    q[COL] = v; q["io_nvalid"] = nv
    # DESCRIPTIVE companions (never gated, never a trial): the two legs, annualized
    # (io_gap = io_intraday - io_overnight), and io_gap with open == prior close days dropped
    q["io_intraday"] = vid; q["io_overnight"] = vid - v
    s2 = s[["ticker", "date", "r_id", "r_on", "valid"]].copy()
    s2["valid"] = s2["valid"] & ~flags["open_eq_prev_close"].to_numpy()
    s2.loc[~s2["valid"], ["r_id", "r_on"]] = 0.0
    q["io_gap_noeq"] = io_gap_for(s2, cal, q)[0]
    q["in_sep"] = q["ticker"].isin(set(s["ticker"]))
    fin = np.isfinite(v)
    assert (last_used[fin] <= q["date"].to_numpy()[fin]).all(), "PIT FAIL: price after t"
    meta["pit_rows_checked"] = int(fin.sum())
    meta["window_first_price_min"] = str(pd.Timestamp(first_used[fin].min()).date())

    # validation tables (descriptive; flags counted on SEP ticker-days 2006-01..2019-12)
    yr = s["date"].dt.year
    keep = yr >= 2006
    added_t = set(q["ticker"]) - set(pd.read_parquet(MAIN / "out" / "reset2026" / "composite_panel.parquet",
                                                      columns=["ticker"])["ticker"].astype(str))
    panel_t = set(q["ticker"])
    grp = np.where(s["ticker"].isin(added_t), "added", np.where(s["ticker"].isin(panel_t), "old", "not_in_panel"))
    fl = flags.loc[keep].assign(year=yr[keep].to_numpy(), grp=grp[keep])
    fcols = ["bad_open", "bad_close", "no_prev", "zero_volume", "open_outside_range", "extreme",
             "open_eq_prev_close", "valid"]
    meta["flag_share_by_year"] = {int(y): {c: float(g[c].mean()) for c in fcols}
                                  for y, g in fl[fl["grp"] != "not_in_panel"].groupby("year")}
    meta["flag_share_by_group"] = {k: {c: float(g[c].mean()) for c in fcols} for k, g in fl.groupby("grp")}
    meta["factor_rows"] = int(len(q)); meta["factor_finite"] = int(fin.sum())
    meta["runtime_s"] = time.time() - t0
    q.to_parquet(OUT / "io_gap_factor_v2.parquet", index=False)
    (OUT / "build_io_gap_meta.json").write_text(json.dumps(meta, indent=2, default=float))
    log(f"wrote io_gap_factor_v2.parquet ({len(q):,} rows, finite {fin.mean():.1%}) in {time.time()-t0:.0f}s")


if __name__ == "__main__":
    main()
