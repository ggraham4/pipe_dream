"""
WO-28 factor inputs on the v2 grid: `vol_shock` (28a) and the raw inputs of
`str_lowturn` (28b). Frozen definition: models/2026-09-29-volshock-strlowturn-screen.md.

Prices/volume: Sharadar SEP data/sharadar/panel/stocks/2006-06..2019-12 (files
after 2019-12 are never opened; the file stem is asserted <= 2019-12 before the
open and every row dated >= 2020-01-01 is an error). SEP `volume` and `close`
are split-adjusted on one common basis (single pull 2026-09-09; basis
consistency is certified by gate_a_volshock.py).

Market calendar = SEP dates with >= 1000 tickers. Rows not on it are dropped.
Positions below are market-calendar positions; a window is "complete" only if
the ticker has a SEP row with finite volume on every market day in it
(zero volume counts as data).

28a  V5(t) = sum of volume over the 5 market days ending t.
     vol_shock(t) = average-ties rank (1..10) of V5(t) among
       {V5(t - 5k), k = 0..9}; NaN unless all 50 market days t-49..t are complete.
28b  r_1m(t)  = close[t] / close[t-21] - 1 (split-adjusted SEP close), needs a row at t-21.
     vol21(t) = mean volume over the 21 market days t-20..t (all 21 complete).
     turnover_21(t) = vol21(t) / shares_adj(t), shares_adj(t) = market_cap(t) / close(t)
       with market_cap from composite_panel_v2 (Sharadar DAILY marketcap, USD) and
       close = SEP close (asserted equal to the panel close). The eligibility split
       and the neutral mid-rank are applied on the screen universe
       (volshock_common.str_lowturn_rank).
Descriptive: r_5d = close[t]/close[t-5]-1, r_21d = r_1m.
PIT: every input is dated <= t; the last SEP date used is t itself (asserted).

Outputs (worktree final/out/volshock/): volshock_inputs_v2.parquet (gitignored),
build_volshock_meta.json.
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
OUT = Path(__file__).resolve().parents[2] / "out" / "volshock"
START, END = pd.Timestamp("2007-01-02"), pd.Timestamp("2019-12-31")
HOLDOUT = pd.Timestamp("2020-01-01")
FIRST_YM, LAST_YM = "2006-06", "2019-12"
CAL_MIN_TICKERS = 1000
NWIN, WLEN = 10, 5
TLEN, RLAG = 21, 21
FACT = OUT / "volshock_inputs_v2.parquet"


def log(m):
    print(f"[{time.strftime('%H:%M:%S')}] {m}", flush=True)


def sha256(path, chunk=1 << 24):
    h = hashlib.sha256()
    with open(path, "rb") as f:
        while b := f.read(chunk):
            h.update(b)
    return h.hexdigest()


def guard(df, what):
    assert pd.to_datetime(df["date"]).max() < HOLDOUT, f"HOLD-OUT BREACH in {what}"
    return df


def sep_files(first=FIRST_YM, last=LAST_YM):
    assert last <= "2019-12"
    files = [f for f in sorted(SEP_MAIN.glob("*.parquet")) if first <= f.stem <= last]
    want = pd.period_range(first, last, freq="M").strftime("%Y-%m").tolist()
    assert [f.stem for f in files] == want, "SEP month files incomplete"
    for f in files:
        assert f.stem <= "2019-12", f"refusing to open {f}"
    return files


def files_digest(files):
    h = hashlib.sha256()
    for f in files:
        h.update(f"{f.parent.name}/{f.name}:{sha256(f)}\n".encode())
    return h.hexdigest()


def load_sep(files, cols=("ticker", "date", "close", "volume", "closeunadj")):
    frames = []
    for f in files:
        assert f.stem <= "2019-12", f"refusing to open {f}"
        d = pd.read_parquet(f, columns=list(cols))
        d["date"] = pd.to_datetime(d["date"])
        guard(d, f)
        assert (d["date"].dt.strftime("%Y-%m") == f.stem).all(), f"{f} has rows outside its month"
        frames.append(d)
    s = pd.concat(frames, ignore_index=True)
    s["ticker"] = s["ticker"].astype(str)
    s = s.sort_values(["ticker", "date"]).drop_duplicates(["ticker", "date"], keep="last").reset_index(drop=True)
    return guard(s, "SEP concat")


def market_calendar(s):
    n = s.groupby("date")["ticker"].size()
    return pd.DatetimeIndex(sorted(n.index[n >= CAL_MIN_TICKERS]))


def shifted(a, k, fill=np.nan):
    out = np.full_like(a, fill, dtype=np.float64) if a.dtype.kind == "f" else np.full(a.shape, -1, dtype=a.dtype)
    if k < len(a):
        out[k:] = a[:-k] if k else a
    return out


def compute(s, cal):
    """s sorted by ticker, date; restricted to calendar dates. Returns frame of inputs."""
    s = s[s["date"].isin(cal)].reset_index(drop=True)
    pos = pd.Index(cal).get_indexer(s["date"]).astype(np.int64)
    assert (pos >= 0).all()
    tc = pd.factorize(s["ticker"])[0].astype(np.int64)
    vol = s["volume"].to_numpy(np.float64)
    close = s["close"].to_numpy(np.float64)
    vfin = np.isfinite(vol) & (vol >= 0)

    def back(arr, k):   # value k rows earlier, same ticker only
        o = shifted(arr, k)
        same = shifted(tc, k) == tc
        return np.where(same, o, np.nan if arr.dtype.kind == "f" else -1)

    def contiguous(n):
        """rows i-n+1..i: same ticker, market positions consecutive, all volume finite."""
        ok = np.ones(len(s), dtype=bool)
        if n > 1:
            p0 = back(pos.astype(np.float64), n - 1)
            ok &= np.isfinite(p0) & (pos - p0 == n - 1)
        # all volumes finite within the n rows
        bad = (~vfin).astype(np.int64)
        cs = np.cumsum(bad)
        cs_prev = shifted(cs.astype(np.float64), n)
        cs_prev = np.where(np.isnan(cs_prev), 0.0, cs_prev)
        ok &= (cs - cs_prev) == 0
        return ok

    # rolling sums by row (valid only where contiguous, which guarantees same ticker)
    v0 = np.where(vfin, vol, 0.0)
    csum = np.cumsum(v0)

    def rsum(n):
        prev = shifted(csum, n)
        prev = np.where(np.isnan(prev), 0.0, prev)
        return csum - prev

    c5 = contiguous(WLEN)
    V5 = np.where(c5, rsum(WLEN), np.nan)
    c50 = contiguous(NWIN * WLEN)
    less = np.zeros(len(s)); eq = np.ones(len(s)); allfin = np.isfinite(V5)   # k=0 is V5 itself
    for k in range(1, NWIN):
        pk = shifted(V5, WLEN * k)
        less += pk < V5
        eq += pk == V5
        allfin &= np.isfinite(pk)
    rank = less + (eq + 1) / 2.0                          # average-ties rank, 1..10
    vol_shock = np.where(c50 & allfin, rank, np.nan)

    c21 = contiguous(TLEN)
    vol21 = np.where(c21, rsum(TLEN) / TLEN, np.nan)
    p21 = back(pos.astype(np.float64), RLAG)
    c_lag = back(close, RLAG)
    r_1m = np.where(np.isfinite(p21) & (pos - p21 == RLAG) & (c_lag > 0) & (close > 0), close / c_lag - 1.0, np.nan)
    p5 = back(pos.astype(np.float64), 5)
    c_l5 = back(close, 5)
    r_5d = np.where(np.isfinite(p5) & (pos - p5 == 5) & (c_l5 > 0) & (close > 0), close / c_l5 - 1.0, np.nan)
    out = pd.DataFrame({"ticker": s["ticker"], "date": s["date"], "sep_close": close, "V5": V5,
                        "vol_shock": vol_shock, "vol21": vol21, "r_1m": r_1m, "r_5d": r_5d})
    # PIT: the latest SEP row used for (ticker, t) is the row at t itself; all windows run backward.
    out["last_input_date"] = s["date"]
    return out


def main():
    t0 = time.time()
    OUT.mkdir(parents=True, exist_ok=True)
    files = sep_files()
    meta = {"sep_first": FIRST_YM, "sep_last": LAST_YM, "sep_digest": files_digest(files),
            "composite_panel_v2_sha256": sha256(PANEL_V2)}
    log(f"panel sha {meta['composite_panel_v2_sha256'][:16]}  sep digest {meta['sep_digest'][:16]}")
    s = load_sep(files)
    cal = market_calendar(s)
    meta["sep_rows"] = int(len(s)); meta["calendar_days"] = int(len(cal))
    meta["rows_off_calendar"] = int((~s["date"].isin(cal)).sum())
    meta["volume_nonfinite_or_negative"] = int((~(np.isfinite(s["volume"]) & (s["volume"] >= 0))).sum())
    meta["volume_zero_share"] = float((s["volume"] == 0).mean())
    f = compute(s, cal)
    del s
    f = f[(f["date"] >= START) & (f["date"] <= END)].reset_index(drop=True)
    guard(f, "inputs")
    assert (f["last_input_date"] <= f["date"]).all(), "PIT FAIL"

    # turnover: shares_adj(t) = market_cap(t) / close(t), panel rows 2007..2019 only
    pan = pd.read_parquet(PANEL_V2, columns=["ticker", "date", "close", "market_cap"],
                          filters=[("date", ">=", "2007-01-02"), ("date", "<=", "2019-12-31")])
    pan["date"] = pd.to_datetime(pan["date"]); pan["ticker"] = pan["ticker"].astype(str)
    guard(pan, "panel")
    n = len(pan)
    pan = pan.merge(f, on=["ticker", "date"], how="left")
    assert len(pan) == n
    both = pan["close"].notna() & pan["sep_close"].notna()
    rel = (pan.loc[both, "close"] / pan.loc[both, "sep_close"] - 1).abs()
    meta["panel_close_vs_sep_close"] = {"rows": int(both.sum()), "max_rel_diff": float(rel.max()),
                                        "share_gt_1e-9": float((rel > 1e-9).mean())}
    assert rel.max() < 1e-9, f"panel close != SEP close (max rel {rel.max()})"
    with np.errstate(divide="ignore", invalid="ignore"):
        shares = pan["market_cap"] / pan["close"]
        pan["turnover_21"] = (pan["vol21"] / shares).where((shares > 0) & np.isfinite(shares))
    pan["r_21d"] = pan["r_1m"]
    keep = ["ticker", "date", "vol_shock", "V5", "r_1m", "turnover_21", "vol21", "r_5d", "r_21d",
            "market_cap", "last_input_date"]
    pan = pan[keep]
    pan.to_parquet(FACT, index=False)
    meta["rows"] = int(len(pan))
    meta["nonnull"] = {c: float(pan[c].notna().mean()) for c in ("vol_shock", "r_1m", "turnover_21", "r_5d")}
    meta["factor_sha256"] = sha256(FACT)
    meta["runtime_s"] = time.time() - t0
    (OUT / "build_volshock_meta.json").write_text(json.dumps(meta, indent=2, default=float))
    log(f"wrote {FACT} ({len(pan):,} rows) {json.dumps(meta['nonnull'])} in {time.time()-t0:.0f}s")


if __name__ == "__main__":
    main()
