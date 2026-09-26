"""
WO-14 (2026-09-25): incremental refresh of the v2 WORKING PANEL and its
companions past their last date.

    python final/src/reset2026/refresh_working_panel.py --through latest
    python final/src/reset2026/refresh_working_panel.py --through 2026-09-24
    python final/src/reset2026/refresh_working_panel.py --check      # report only, writes nothing

EXIT CODES
    0  refreshed, or already up to date (no-op: nothing is written)
    1  failed. Nothing was replaced: every output is written to a temp file,
       validated, and only then swapped in (message on stderr)

WHAT IT EXTENDS (same point-in-time rules as build_downcap_grid_v2.py,
because it calls the SAME builder code, with paths repointed to temp files)
    out/reset2026/composite_panel_v2.parquet       (working_panel.WORKING_PANEL)
    out/reset2026/beta_feature_v2.parquet          (WORKING_BETA)
    out/reset2026/outcome_cache_v2.parquet         (WORKING_OUTCOME)
    scripts/td_data_sharadar_downcap_v2/*.csv      (OHLC for tickers not in td_data_sharadar/;
                                                    replaced CSVs kept in _backup_through_<old_end>/)
    out/reset2026/downcap_v2/refresh_report_<new_end>.json
Before each swap the previous file is kept as a hard-linked dated backup,
e.g. composite_panel_v2_through_2026-09-08.parquet (refuses if it exists).
It never touches v1 files (composite_panel.parquet, downcap_universe*.parquet,
features_*_sharadar_pit.parquet, td_data_sharadar/) or any prediction ledger.

INPUTS (read-only): data/sharadar/panel/{stocks,daily} (SEP/DAILY, topped up
by sharadar_pull_pit_panel.py), sf1_fundamentals.parquet, sf1_shares.csv,
tickers_master.csv, data/finra/short_interest_raw.csv, SPY.csv, USMV.csv.

HOW (per step, the builder that produced the v2 grid)
    universe   reset2026/downcap_universe.main()      -> temp (full rebuild, ~35s)
    prices     build_features_sharadar.features_for() on each ticker's FULL
               SEP history (rolling std is not bit-stable on a truncated
               buffer: measured 30,661/35,900 last-bit diffs on volatility_60)
    fundamentals build_features_fundamentals_sharadar.main() on the rows kept
               (as-of joins on SF1 `date` <= row date: exact on a buffer)
    issuance / short interest / events: sweep.* library functions (as-of joins)
    quality    reset2026/quality_factors.main() on full close history
    panel      reset2026/build_panel.main(); eligible_cap*_v1 on NEW dates =
               the v1 builder's (downcap_universe.py) flags, which since the
               2026-09-22 split-basis fix are byte-identical to the v2 flags
    beta       reset2026/build_beta_feature.main() on full close history
    outcome    build_outcome_cache.vectorized_outcomes() on full SEP OHLC

ROWS KEPT
    * new dates (old_end, through] for every grid ticker (and any NEW ticker
      the universe now contains) that has SEP rows there
    * label backfill: forward_return_40 / forward_return_tradable_40 NaN -> value
      on old rows whose 40-day window has now matured. Nothing else on an old
      row changes. A recomputed old value that disagrees with the stored one
      is a FAILURE (reported per column), except eligible_* flags, which can
      move with vendor volume/marketcap revisions and are kept as stored.
    * outcome cache: old rows with truncated=True are replaced; others kept.

CORPORATE ACTIONS / VENDOR REVISIONS (compared over the last COMPARE_MONTHS
months <= old_end, stored panel open/close vs SEP on disk)
    split-like  (a close ratio outside [0.8, 1.25]): the months before the
                re-pulled one are still on the OLD split basis on disk, so a
                full recompute would splice two bases. Such tickers are NOT
                extended and are listed as BLOCKED: they need their SEP
                history re-pulled (see the WO-14 doc).
    revised     (any other open/close change, or a row added/removed): the
                ticker's full history is recomputed and replaces its stored rows,
                exactly as a full v2 rebuild would.
    stale       (changed, but no SEP rows after old_end): left as stored.
All three lists are printed and written to downcap_v2/refresh_report_<through>.json.
"""
import argparse
import json
import os
import shutil
import sys
import time
from pathlib import Path

HERE = Path(__file__).resolve().parent
SRC = HERE.parent
sys.path.insert(0, str(SRC))
sys.path.insert(0, str(HERE))

MAIN = Path("/Users/ggraham/pipe_dream/final")
# Repoint features' roots at the main checkout BEFORE any builder (or sweep
# module, which reads these at import) is imported -- same as build_downcap_grid_v2.
import features as _features  # noqa: E402
_features.PROJECT_ROOT = MAIN
_features.DATA_DIR = MAIN / "scripts" / "td_data_local"
_features.OUT_DIR = MAIN / "out"
_features.MODELS_DIR = MAIN / "out" / "models"

import numpy as np  # noqa: E402
import pandas as pd  # noqa: E402
import pyarrow as pa  # noqa: E402
import pyarrow.compute as pc  # noqa: E402
import pyarrow.parquet as pq  # noqa: E402

import working_panel as W  # noqa: E402

R26 = MAIN / "out" / "reset2026"
V2DIR = R26 / "downcap_v2"
SH = MAIN / "data" / "sharadar"
SEP = SH / "panel" / "stocks"
DAILY = SH / "panel" / "daily"
GRID_TICKERS = V2DIR / "grid_tickers_v2.parquet"
PANEL_V2 = W.WORKING_PANEL
BETA_V2 = W.WORKING_BETA
OUTCOME_V2 = W.WORKING_OUTCOME
OHLC_OLD = MAIN / "scripts" / "td_data_sharadar"
OHLC_NEW = MAIN / "scripts" / "td_data_sharadar_downcap_v2"
SPY_CSV = MAIN / "scripts" / "td_data_local" / "SPY.csv"
USMV_CSV = MAIN / "data" / "benchmarks" / "USMV.csv"

LABELS = ["forward_return_40", "forward_return_tradable_40"]
BUFFER_DATES = 60          # old trading dates re-derived for label backfill + overlap check
COMPARE_MONTHS = 3
SPLIT_BAND = (0.8, 1.25)
ROWS_PER_DATE_REF = 3901   # 2026-09-08
OHLC_COLS = ["date", "open", "high", "low", "close", "volume"]


class RefreshError(Exception):
    pass


def log(msg):
    print(f"[{time.strftime('%H:%M:%S')}] {msg}", flush=True)


def _max_date(path, col="date"):
    return pd.Timestamp(pc.max(pq.read_table(path, columns=[col]).column(col)).as_py())


def raw_end():
    last_s = sorted(SEP.glob("*.parquet"))[-1]
    last_d = sorted(DAILY.glob("*.parquet"))[-1]
    return min(_max_date(last_s), _max_date(last_d))


def read_sep(tickers, start=None, end=None, cols=("ticker", "date", "open", "high", "low", "close", "volume")):
    frames = []
    for f in sorted(SEP.glob("*.parquet")):
        if start is not None and f.stem < start.strftime("%Y-%m"):
            continue
        if end is not None and f.stem > end.strftime("%Y-%m"):
            continue
        d = pd.read_parquet(f, columns=list(cols))
        if tickers is not None:
            d = d[d["ticker"].isin(tickers)]
        frames.append(d)
    d = pd.concat(frames, ignore_index=True)
    d["date"] = pd.to_datetime(d["date"])
    if end is not None:
        d = d[d["date"] <= end]
    if start is not None:
        d = d[d["date"] >= start]
    return d


# --------------------------------------------------------------------------- steps
def step_universe(work):
    import downcap_universe as U
    U.OUT, U.REPORT = work / "universe.parquet", work / "universe_report.txt"
    U.main()
    return U.OUT


def detect_changes(grid, old_end, through):
    """Stored panel open/close vs SEP on disk over the last COMPARE_MONTHS months."""
    start = (old_end - pd.DateOffset(months=COMPARE_MONTHS)).replace(day=1)
    st = pd.read_parquet(PANEL_V2, columns=["ticker", "date", "open", "close"],
                         filters=[("date", ">=", start.date().isoformat())])
    st["date"] = pd.to_datetime(st["date"])
    st["ticker"] = st["ticker"].astype(str)
    raw = read_sep(grid, start=start, end=old_end, cols=("ticker", "date", "open", "close"))
    m = st.merge(raw, on=["ticker", "date"], how="outer", suffixes=("", "_raw"), indicator=True)
    both = m["_merge"] == "both"
    diff = ~both | ~(((m["open"] == m["open_raw"]) | (m["open"].isna() & m["open_raw"].isna()))
                     & ((m["close"] == m["close_raw"]) | (m["close"].isna() & m["close_raw"].isna())))
    changed = m[diff]
    ratio = (m["close_raw"] / m["close"]).where(both)
    after = set(read_sep(None, start=old_end + pd.Timedelta(days=1), end=through,
                         cols=("ticker", "date"))["ticker"])
    split, revised, stale, detail = [], [], [], {}
    for t, g in changed.groupby("ticker"):
        r = ratio.loc[g.index].dropna()
        is_split = bool(((r < SPLIT_BAND[0]) | (r > SPLIT_BAND[1])).any())
        detail[t] = {"rows_changed": int(len(g)),
                     "rows_one_sided": int((g["_merge"] != "both").sum()),
                     "close_ratio_min": float(r.min()) if len(r) else None,
                     "close_ratio_max": float(r.max()) if len(r) else None}
        if is_split:
            split.append(t)
        elif t not in after:
            stale.append(t)
        else:
            revised.append(t)
    log(f"overlap compare {start.date()}..{old_end.date()}: {len(changed):,} rows differ; "
        f"split-like {len(split)}, revised {len(revised)}, stale {len(stale)}")
    return sorted(split), sorted(revised), sorted(stale), detail, after


def step_prices(work, tickers, full_tickers, buf_start, through):
    import build_features_sharadar as BF
    from features import FEATURE_COLS, LABEL_COL, TRADABLE_LABEL_COL
    px = read_sep(set(tickers), end=through)
    px = px.sort_values(["ticker", "date"]).reset_index(drop=True)
    for c in BF.PRICE_COLS:
        px[c] = pd.to_numeric(px[c], errors="coerce")
    spy = BF.load_spy()
    keep = ["ticker", "date"] + BF.PRICE_COLS + FEATURE_COLS + [LABEL_COL, TRADABLE_LABEL_COL]
    schema = pa.schema([("ticker", pa.string()), ("date", pa.timestamp("ns"))]
                       + [(c, pa.float64()) for c in keep[2:]])
    w = pq.ParquetWriter(work / "prices.parquet", schema)
    closes = []
    n = 0
    for i, (tk, g) in enumerate(px.groupby("ticker", sort=False), 1):
        f = BF.features_for(g[["ticker", "date"] + BF.PRICE_COLS], spy)[keep]
        f["ticker"] = f["ticker"].astype(str)
        for c in keep[2:]:
            f[c] = pd.to_numeric(f[c], errors="coerce").astype("float64")
        closes.append(f[["ticker", "date", "close"]])
        if tk not in full_tickers:
            f = f[f["date"] >= buf_start]
        w.write_table(pa.Table.from_pandas(f, schema=schema, preserve_index=False))
        n += len(f)
        if i % 1000 == 0:
            log(f"  prices {i:,} tickers")
    w.close()
    cl = pd.concat(closes, ignore_index=True)
    cl["date"] = cl["date"].astype("datetime64[ns]")     # same [ns] schema the v2 price panel carries
    pq.write_table(pa.Table.from_pandas(cl, schema=pa.schema([("ticker", pa.string()), ("date", pa.timestamp("ns")),
                                                               ("close", pa.float64())]), preserve_index=False),
                   work / "closes_full.parquet")
    log(f"prices: {px['ticker'].nunique():,} tickers full history ({len(cl):,} rows); kept {n:,} rows")
    return px


def step_fundamentals(work):
    import build_features_fundamentals_sharadar as FF
    FF.PRICE_PANEL, FF.OUT = work / "prices.parquet", work / "fund.parquet"
    FF.main()


def step_addons(work):
    from sweep.issuance import build_issuance_features, NET_ISSUANCE_COL
    from sweep.short_interest import build_short_interest_features
    from sweep import events as E
    fund = pd.read_parquet(work / "fund.parquet")
    fund["ticker"] = fund["ticker"].astype(str)
    iss = build_issuance_features(fund.copy())
    pq.write_table(pa.Table.from_pandas(iss[["ticker", "date", NET_ISSUANCE_COL]], preserve_index=False),
                   work / "iss.parquet")
    si = build_short_interest_features(fund.copy())
    pq.write_table(pa.Table.from_pandas(si[["ticker", "date", "short_interest_days_to_cover"]],
                                        preserve_index=False), work / "si.parquet")
    ev = E.build_event_features(fund.copy(), horizon=40, verbose=False)
    pq.write_table(pa.Table.from_pandas(ev[["ticker", "date", "days_to_next_filing_seasonal"]],
                                        preserve_index=False), work / "ev.parquet")
    log("issuance / short interest / events done")


def step_quality(work):
    import quality_factors as Q
    Q.PRICE_PANEL, Q.OUT = work / "closes_full.parquet", work / "quality.parquet"
    Q.main()


def step_panel(work):
    import build_panel as BP
    BP.BASE_PANEL, BP.ISSUANCE_PANEL = work / "fund.parquet", work / "iss.parquet"
    BP.SHORT_INT_PANEL, BP.EVENTS_PANEL = work / "si.parquet", work / "ev.parquet"
    BP.QUALITY_PANEL = work / "quality.parquet"
    BP.DOWNCAP_UNIVERSE = work / "universe.parquet"
    BP.OUT = work / "panel_part.parquet"
    BP.main()
    p = pd.read_parquet(BP.OUT)
    u = pd.read_parquet(work / "universe.parquet",
                        columns=["ticker", "date", "eligible_cap2000", "eligible_cap500", "eligible_cap150"])
    u["ticker"] = u["ticker"].astype(str)
    u = u.rename(columns={c: c + "_v1" for c in ("eligible_cap2000", "eligible_cap500", "eligible_cap150")})
    n = len(p)
    p = p.merge(u, on=["ticker", "date"], how="left")
    assert len(p) == n
    for c in ("eligible_cap2000_v1", "eligible_cap500_v1", "eligible_cap150_v1"):
        p[c] = p[c].fillna(False).astype(bool)
    return p


def step_beta(work):
    import build_beta_feature as BB
    BB.PANEL_PATH, BB.OUT = work / "closes_full.parquet", work / "beta.parquet"
    BB.main()
    return pd.read_parquet(BB.OUT)


def step_outcome(px):
    from build_outcome_cache import vectorized_outcomes
    frames = []
    for tk, g in px.groupby("ticker", sort=False):
        g = g.sort_values("date").reset_index(drop=True)
        gross, trunc = vectorized_outcomes(g)
        frames.append(pd.DataFrame({"ticker": tk, "date": g["date"].to_numpy(),
                                    "gross_return_40": gross, "truncated": trunc}))
    for name, path in (("SPY", SPY_CSV), ("USMV", USMV_CSV)):
        g = pd.read_csv(path, usecols=["date", "open", "high", "low", "close"], parse_dates=["date"])
        g = g.sort_values("date").reset_index(drop=True)
        gross, trunc = vectorized_outcomes(g)
        frames.append(pd.DataFrame({"ticker": name, "date": g["date"].to_numpy(),
                                    "gross_return_40": gross, "truncated": trunc}))
    return pd.concat(frames, ignore_index=True)


# --------------------------------------------------------------------------- splice
def _eq(a, b):
    a = np.asarray(a); b = np.asarray(b)
    if a.dtype.kind == "f" or b.dtype.kind == "f":
        a = a.astype(np.float64); b = b.astype(np.float64)
        return (a == b) | (np.isnan(a) & np.isnan(b))
    return a == b


def _to_arrow(df, schema):
    plain = schema.remove_metadata()
    return pa.Table.from_pandas(df[[f.name for f in plain]], schema=plain, preserve_index=False)


def splice(old_path, part, key_date_str, replace_tickers, new_tickers, buf_start, old_end, label_cols,
           frozen_cols, report, name):
    """part: recomputed rows (ticker, date as in file). Returns the new arrow table."""
    T = pq.read_table(old_path)
    schema = T.schema
    date_is_str = pa.types.is_large_string(schema.field("date").type) or pa.types.is_string(schema.field("date").type)
    tick = T.column("ticker")
    drop_t = pa.array(sorted(replace_tickers | new_tickers), type=pa.large_string())
    keep_mask = pc.invert(pc.is_in(tick, value_set=drop_t))
    bs = buf_start.date().isoformat() if date_is_str else pa.scalar(buf_start, type=schema.field("date").type)
    in_tail = pc.greater_equal(T.column("date"), bs)
    body = T.filter(pc.and_(keep_mask, pc.invert(in_tail)))
    tail = T.filter(pc.and_(keep_mask, in_tail)).to_pandas()
    tail["ticker"] = tail["ticker"].astype(str)
    del T

    part = part.copy()
    part["ticker"] = part["ticker"].astype(str)
    oe = old_end.date().isoformat() if date_is_str else old_end
    # overlap: recomputed vs stored on the tail of unchanged tickers
    m = tail.merge(part, on=["ticker", "date"], how="left", suffixes=("", "__n"), indicator=True)
    assert len(m) == len(tail)
    rep = {"tail_rows": int(len(tail)), "tail_rows_recomputed": int((m["_merge"] == "both").sum()),
           "column_mismatch": {}, "label_fill": {}}
    both = (m["_merge"] == "both").to_numpy()
    for c in [f.name for f in schema if f.name not in ("ticker", "date")]:
        if c + "__n" not in m.columns:
            continue
        eq = _eq(m[c].to_numpy(), m[c + "__n"].to_numpy())
        if c in label_cols:
            old_nan = pd.isna(m[c]).to_numpy()
            bad = both & ~old_nan & ~eq
            fill = both & old_nan & ~pd.isna(m[c + "__n"]).to_numpy()
            rep["label_fill"][c] = int(fill.sum())
            rep["column_mismatch"][c] = int(bad.sum())
            tail.loc[fill, c] = m.loc[fill, c + "__n"].to_numpy()
        else:
            rep["column_mismatch"][c] = int((both & ~eq).sum())
    hard = {c: v for c, v in rep["column_mismatch"].items() if v and c not in frozen_cols}
    if hard:
        raise RefreshError(f"{name}: recomputed old rows disagree with stored values {hard} -- "
                           f"not a pure extension; refusing to write")
    newrows = part[(part["date"] > oe) | part["ticker"].isin(replace_tickers | new_tickers)]
    rep["rows_replaced_tickers"] = int(part["ticker"].isin(replace_tickers).sum())
    rep["rows_new_tickers"] = int(part["ticker"].isin(new_tickers).sum())
    rep["rows_new_dates"] = int((part["date"] > oe).sum())
    out = pa.concat_tables([body.replace_schema_metadata(None), _to_arrow(tail, schema),
                            _to_arrow(newrows, schema)])
    idx = pc.sort_indices(out, sort_keys=[("ticker", "ascending"), ("date", "ascending")])
    out = out.take(idx).replace_schema_metadata(schema.metadata)
    tcol, dcol = out.column("ticker"), out.column("date")
    n = out.num_rows
    dup = pc.and_(pc.equal(tcol.slice(1), tcol.slice(0, n - 1)), pc.equal(dcol.slice(1), dcol.slice(0, n - 1)))
    if pc.any(dup).as_py():
        raise RefreshError(f"{name}: duplicate (ticker, date) after splice")
    report[name] = rep
    return out


def splice_outcome(part, replace_tickers, new_tickers, report):
    T = pq.read_table(OUTCOME_V2)
    schema = T.schema
    affected = set(part["ticker"].unique())
    aff_arr = pa.array(sorted(affected), type=pa.large_string())
    in_aff = pc.is_in(T.column("ticker"), value_set=aff_arr)
    body = T.filter(pc.invert(in_aff))
    old = T.filter(in_aff).to_pandas()
    del T
    old["ticker"] = old["ticker"].astype(str)
    old["date"] = pd.to_datetime(old["date"]).astype("datetime64[ns]")
    part = part.copy()
    part["date"] = pd.to_datetime(part["date"]).astype("datetime64[ns]")
    m = old.merge(part, on=["ticker", "date"], how="outer", suffixes=("", "__n"), indicator=True)
    whole = m["ticker"].isin(replace_tickers | new_tickers)
    oldrow = m["_merge"] != "right_only"
    both = m["_merge"] == "both"
    trunc_old = m["truncated"].fillna(False).astype(bool)
    eq = _eq(m["gross_return_40"].to_numpy(), m["gross_return_40__n"].to_numpy()) & (
        m["truncated"].fillna(False).astype(bool).to_numpy() == m["truncated__n"].fillna(False).astype(bool).to_numpy())
    mism = both & ~trunc_old & ~pd.Series(eq, index=m.index) & ~whole
    use_new = whole | (m["_merge"] == "right_only") | (both & trunc_old)
    res = pd.DataFrame({"ticker": m["ticker"], "date": m["date"],
                        "gross_return_40": np.where(use_new, m["gross_return_40__n"], m["gross_return_40"]),
                        "truncated": np.where(use_new, m["truncated__n"], m["truncated"])})
    res = res[~(whole & (m["_merge"] == "left_only"))]
    res["gross_return_40"] = res["gross_return_40"].astype(np.float32)
    res["truncated"] = res["truncated"].astype(bool)
    report["outcome"] = {
        "affected_tickers": len(affected),
        "rows_truncated_replaced": int((both & trunc_old & ~whole).sum()),
        "rows_new": int(((m["_merge"] == "right_only") & ~whole).sum()),
        "rows_whole_ticker_replaced": int((whole & (m["_merge"] != "left_only")).sum()),
        "old_nontruncated_mismatch_kept_old": int(mism.sum()),
        "old_nontruncated_mismatch_examples": m.loc[mism, ["ticker", "date"]].astype(str).head(10).values.tolist(),
        "old_rows_without_recompute_kept": int(((m["_merge"] == "left_only") & ~whole).sum()),
    }
    out = pa.concat_tables([body.replace_schema_metadata(None), _to_arrow(res, schema)])
    idx = pc.sort_indices(out, sort_keys=[("ticker", "ascending"), ("date", "ascending")])
    return out.take(idx).replace_schema_metadata(schema.metadata)


# --------------------------------------------------------------------------- swap
def backup_name(path, old_end):
    return path.with_name(f"{path.stem}_through_{old_end.date().isoformat()}{path.suffix}")


def swap(tmp, dst, old_end):
    bk = backup_name(dst, old_end)
    if bk.exists():
        raise RefreshError(f"backup {bk} already exists; refusing to overwrite it")
    os.link(dst, bk)           # hard link: the old bytes stay reachable under the dated name
    os.replace(tmp, dst)
    return bk


def write_ohlc(px, tickers, old_end, report):
    """Rewrite v2-dir CSVs (tickers with no CSV in td_data_sharadar/) from SEP."""
    have_old = {p.stem for p in OHLC_OLD.glob("*.csv")}
    # inside OHLC_NEW: gitignored with it, and load_ohlc_panel's non-recursive glob skips it
    bkdir = OHLC_NEW / f"_backup_through_{old_end.date().isoformat()}"
    todo = set(t for t in tickers if t not in have_old)
    staged = []
    for tk, g in px[px["ticker"].isin(todo)].groupby("ticker", sort=True):
        g = g.sort_values("date")
        g = g.assign(date=g["date"].dt.strftime("%Y-%m-%d"))
        tmp = OHLC_NEW / f".{tk}.csv.wo14tmp"
        g[OHLC_COLS].to_csv(tmp, index=False)
        staged.append((tk, tmp))
    return staged, bkdir


def commit_ohlc(staged, bkdir):
    bkdir.mkdir(exist_ok=True)
    n_new = 0
    for tk, tmp in staged:
        dst = OHLC_NEW / f"{tk}.csv"
        if dst.exists():
            b = bkdir / f"{tk}.csv"
            if not b.exists():
                os.link(dst, b)
        else:
            n_new += 1
        os.replace(tmp, dst)
    return n_new


# --------------------------------------------------------------------------- main
def run(args):
    t0 = time.time()
    old_end = W.latest_date(PANEL_V2)
    re = raw_end()
    through = re if args.through == "latest" else min(pd.Timestamp(args.through), re)
    log(f"working panel ends {old_end.date()}; SEP/DAILY on disk end {re.date()}; target {through.date()}")
    for p, col in ((BETA_V2, "date"),):
        if _max_date(p, col) != old_end:
            raise RefreshError(f"{p.name} ends {_max_date(p, col).date()}, panel ends {old_end.date()}: "
                               "companions out of step, refusing")
    if through <= old_end:
        log("up to date: nothing to do (no file written)")
        return 0
    if args.check:
        log("--check: new data available; not writing")
        return 0

    work = V2DIR / f"refresh_tmp_{through.date().isoformat()}"
    if work.exists():
        shutil.rmtree(work)
    work.mkdir(parents=True)
    report = {"old_end": old_end.date().isoformat(), "through": through.date().isoformat(),
              "started": time.strftime("%Y-%m-%d %H:%M:%S")}

    grid = set(pd.read_parquet(GRID_TICKERS)["ticker"].astype(str))
    log("step universe (downcap_universe.py, v1 builder == v2 flags since 2026-09-22) ...")
    step_universe(work)
    uni_t = set(pq.read_table(work / "universe.parquet", columns=["ticker"]).column("ticker").unique().to_pylist())
    new_tickers_all = uni_t - grid

    split, revised, stale, detail, after = detect_changes(grid, old_end, through)
    new_tickers = set(t for t in new_tickers_all if t in after)
    blocked = set(split)
    # COO 2026-09-25: a blocked (split-like, stale-basis) ticker that is now
    # eligible at any tier must stop the refresh, not silently drop out.
    if blocked:
        u = pd.read_parquet(work / "universe.parquet",
                            columns=["ticker", "date", "eligible_cap2000", "eligible_cap500", "eligible_cap150"],
                            filters=[("date", ">", old_end.date().isoformat())])
        u = u[u["ticker"].astype(str).isin(blocked)]
        hit = u[u[["eligible_cap2000", "eligible_cap500", "eligible_cap150"]].any(axis=1)]
        if len(hit):
            raise RefreshError(f"split-like tickers with stale-basis history are ELIGIBLE after "
                               f"{old_end.date()}: {sorted(hit['ticker'].unique())}. Re-pull their SEP "
                               f"history first (see the WO-14 doc); refusing to refresh.")
    affected =((grid | new_tickers) & after) - blocked
    full = (set(revised) | new_tickers) - blocked
    dates = sorted(pq.read_table(PANEL_V2, columns=["date"],
                                 filters=[("date", ">=", (old_end - pd.Timedelta(days=150)).date().isoformat())])
                   .column("date").unique().to_pylist())
    buf_start = pd.Timestamp(dates[-BUFFER_DATES])
    report.update({"split_like_blocked": sorted(blocked), "revised_recomputed": sorted(revised),
                   "stale_kept": sorted(stale), "new_tickers": sorted(new_tickers),
                   "change_detail": detail, "buffer_start": buf_start.date().isoformat(),
                   "tickers_extended": len(affected)})
    log(f"tickers to extend {len(affected):,} (new tickers {len(new_tickers)}, revised {len(revised)}, "
        f"BLOCKED split-like {sorted(blocked)}); buffer from {buf_start.date()}")

    log("step prices ...")
    px = step_prices(work, affected, full, buf_start, through)
    log("step fundamentals ...")
    step_fundamentals(work)
    log("step issuance / short / events ...")
    step_addons(work)
    log("step quality ...")
    step_quality(work)
    log("step panel ...")
    part = step_panel(work)
    log("step beta ...")
    beta = step_beta(work)
    beta["ticker"] = beta["ticker"].astype(str)
    log("step outcome ...")
    oc = step_outcome(px)

    # ---- splice + validate (temps only)
    log("splicing panel ...")
    frozen = {"eligible_cap2000", "eligible_cap500", "eligible_cap150",
              "eligible_cap2000_v1", "eligible_cap500_v1", "eligible_cap150_v1"}
    panel_t = splice(PANEL_V2, part, True, set(revised), new_tickers, buf_start, old_end, LABELS,
                     frozen, report, "panel")
    log("splicing beta ...")
    # beta rows exist exactly where panel rows exist
    keyp = part[["ticker", "date"]]
    beta_part = beta.merge(keyp, on=["ticker", "date"], how="inner")
    beta_t = splice(BETA_V2, beta_part, True, set(revised), new_tickers, buf_start, old_end, [],
                    set(), report, "beta")
    log("splicing outcome cache ...")
    out_t = splice_outcome(oc, set(revised), new_tickers, report)

    # validation
    new_dates = pc.greater(panel_t.column("date"), old_end.date().isoformat())
    nd = panel_t.filter(new_dates).select(["date"]).to_pandas()["date"].value_counts().sort_index()
    report["rows_per_new_date"] = {k: int(v) for k, v in nd.items()}
    lo, hi = ROWS_PER_DATE_REF * 0.95, ROWS_PER_DATE_REF * 1.05
    badd = {k: v for k, v in report["rows_per_new_date"].items() if not lo <= v <= hi}
    if badd:
        raise RefreshError(f"rows per new date outside +-5% of {ROWS_PER_DATE_REF}: {badd}")
    if panel_t.num_rows != beta_t.num_rows:
        raise RefreshError(f"panel {panel_t.num_rows:,} rows vs beta {beta_t.num_rows:,}")
    if panel_t.schema != pq.read_schema(PANEL_V2) or beta_t.schema != pq.read_schema(BETA_V2) \
            or out_t.schema != pq.read_schema(OUTCOME_V2):
        raise RefreshError("schema drift in a spliced table")
    report["rows"] = {"panel_old": pq.ParquetFile(PANEL_V2).metadata.num_rows, "panel_new": panel_t.num_rows,
                      "beta_new": beta_t.num_rows, "outcome_old": pq.ParquetFile(OUTCOME_V2).metadata.num_rows,
                      "outcome_new": out_t.num_rows}
    tmp_p, tmp_b, tmp_o = (p.with_name(p.name + ".wo14tmp") for p in (PANEL_V2, BETA_V2, OUTCOME_V2))
    pq.write_table(panel_t, tmp_p)
    pq.write_table(beta_t, tmp_b)
    pq.write_table(out_t, tmp_o)
    for tmp in (tmp_p, tmp_b, tmp_o):          # re-read what hit disk
        pq.read_table(tmp, columns=["ticker", "date"])
    staged, bkdir = write_ohlc(px, affected | set(revised), old_end, report)
    if args.no_swap:
        for _tk, tmp in staged:
            tmp.unlink()
        report["no_swap"] = True
        report["ohlc_csvs_would_write"] = len(staged)
        (work / "report.json").write_text(json.dumps(report, indent=2, default=str))
        log(f"--no-swap: validated temps left at {tmp_p.name}, {tmp_b.name}, {tmp_o.name}; "
            f"report {work / 'report.json'}; {time.time() - t0:.0f}s")
        return 0

    # ---- swap (panel last, so a failure mid-swap leaves the panel at its old end)
    log("swapping in (dated hard-link backups first) ...")
    report["backups"] = [str(swap(tmp_o, OUTCOME_V2, old_end)), str(swap(tmp_b, BETA_V2, old_end))]
    report["ohlc_csvs_written"] = len(staged)
    report["ohlc_csvs_new"] = commit_ohlc(staged, bkdir)
    report["ohlc_backup_dir"] = str(bkdir)
    report["backups"].append(str(swap(tmp_p, PANEL_V2, old_end)))
    report["new_end"] = W.latest_date(PANEL_V2).date().isoformat()
    report["runtime_s"] = round(time.time() - t0, 1)
    (V2DIR / f"refresh_report_{through.date().isoformat()}.json").write_text(json.dumps(report, indent=2, default=str))
    shutil.rmtree(work)
    log(f"DONE: panel {old_end.date()} -> {report['new_end']}, "
        f"{report['rows']['panel_new'] - report['rows']['panel_old']:+,} rows; "
        f"label fills {report['panel']['label_fill']}; BLOCKED {sorted(blocked)}; {report['runtime_s']}s")
    return 0


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--through", default="latest", help="'latest' or YYYY-MM-DD")
    ap.add_argument("--check", action="store_true", help="report whether new data exists; write nothing")
    ap.add_argument("--no-swap", action="store_true",
                    help="test run: build + validate temps, never replace the live files")
    ap.add_argument("--record-weekly", action="store_true",
                    help="WO-14 weekly cadence: insider refresh -> panel refresh -> record_weekly.py")
    a = ap.parse_args()
    import subprocess
    if a.record_weekly and not (a.check or a.no_swap):
        ins = HERE.parent.parent / "scripts" / "edgar_form4_refresh.py"
        log(f"step insider refresh ({ins.name}) ...")
        if subprocess.run([sys.executable, str(ins)]).returncode != 0:
            print("REFRESH FAILED: insider refresh failed; panel and ledgers untouched", file=sys.stderr)
            return 1
    try:
        rc = run(a)
        if rc == 0 and a.record_weekly and not (a.check or a.no_swap):
            log("step weekly records (record_weekly.py) ...")
            rc = subprocess.run([sys.executable, str(HERE / "record_weekly.py")]).returncode
            if rc != 0:
                print("REFRESH FAILED: weekly record step failed (panel refreshed, no partial record "
                      "written past the preflight)", file=sys.stderr)
                return 1
        return rc
    except (RefreshError, AssertionError, SystemExit) as e:
        if isinstance(e, SystemExit) and e.code in (0, None):
            return 0
        print(f"REFRESH FAILED (nothing replaced): {e}", file=sys.stderr)
        return 1
    except Exception as e:  # noqa: BLE001
        import traceback
        traceback.print_exc()
        print(f"REFRESH FAILED (nothing replaced): {type(e).__name__}: {e}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    sys.exit(main())
