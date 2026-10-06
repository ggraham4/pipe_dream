"""
WO-43 Step 2 data store (label-free preparation; no fit, no outcome statistic).

Base panel: final/out/features_with_rates_sharadar_pit.parquet (2026-09-11), the
cache-era build that reproduces the cached q75 bit-exactly (Step 1b), loaded
with continuous_walkforward_pit.load_panel_prepared exactly as
sweep/scorecache.PanelContext does (filter = the 11 price FEATURE_COLS, h=40,
tradable label). Row order is load_panel_prepared's (date-sorted, stable).

Hold-out: rows dated >= 2020-01-01 are dropped right after the load, and any
remaining label whose 40-row exit date is >= 2020-01-01 (or missing) is set to
NaN, so the stored label array carries no 2020+ price. (Those labels could
never be used anyway: a training row's exit must be <= its score date <= 2019-12-31.)

New columns (v2 grid, 2007-01-02..2019-12-31; NaN on 2005-2006 rows and on
rows the v2 grid lacks), attached by (base ticker, date) key lookup that
keeps the base row order:
  io_gap       overnight/build_io_gap.py output          io_gap
  seas         seasonality/build_seas.py output          seas
  sue          sue/build_sue.py output                   sue
  ear          ear/build_ear.py output                   ear_raw (NaN unless live)
  str_lowturn  volshock/screen_volshock.str_lowturn_rank on the screen's
               universe (v2 column c, eligible_cap150) from volshock inputs
               r_1m, turnover_21; NaN outside that universe (frozen definition).

Outputs
  ~/.cache/wo43_xgbretrain/*.npy        memmaps (outside the repo; not committed)
  final/out/xgbretrain/inputs/*.parquet copies of every factor input (gitignored)
  final/out/xgbretrain/store_meta.json  hashes, row counts, coverage (label-free)
"""
import hashlib
import json
import shutil
import sys
import time
from pathlib import Path

import numpy as np
import pandas as pd
import pyarrow.parquet as pq

HERE = Path(__file__).resolve().parent
SRC = HERE.parent
sys.path.insert(0, str(SRC))
sys.path.insert(0, str(SRC / "volshock"))
MAIN = Path("/Users/ggraham/pipe_dream/final")
import features as F                      # noqa: E402
import continuous_walkforward_pit as W    # noqa: E402
W.OUT_DIR = MAIN / "out"
W.PIT_UNIVERSE_PATH = MAIN / "data" / "sharadar" / "pit_universe.parquet"
from sweep import scorecache as SC       # noqa: E402
import step1_audit as A                   # noqa: E402

WT = Path("/Users/ggraham/pipe_dream/.claude/worktrees")
BASE_PANEL = MAIN / "out" / "features_with_rates_sharadar_pit.parquet"
BASE_SHA = "18fa37b9a876fab050b1823421e77650e2f4cff3df45c66d86896f5934eb56c6"
SOURCES = {
    "io_gap": (WT / "overnight-intraday/final/out/overnight/io_gap_factor_v2.parquet", "io_gap"),
    "seas": (WT / "agent-a790eb27c4530aa0a/final/out/seasonality/seas_factor_v2.parquet", "seas"),
    "sue": (WT / "agent-a505179eca9ed9bf2/final/out/sue/sue_factor_v2.parquet", "sue"),
    "ear": (WT / "agent-ad838240373d22717/final/out/ear/ear_factor_v2.parquet", "ear_raw"),
    "volshock_inputs": (WT / "agent-a79a9999a5df053aa/final/out/volshock/volshock_inputs_v2.parquet", None),
}
DUP_COPIES = {"seas": WT / "agent-ad57ef9f38454d99d/final/out/seasonality/seas_factor_v2.parquet",
              "sue": WT / "agent-a82cc71ecb09661f5/final/out/sue/sue_factor_v2.parquet"}
V2 = MAIN / "out" / "reset2026" / "composite_panel_v2.parquet"
NEW_COLS = ["io_gap", "seas", "sue", "ear", "str_lowturn"]
HOLDOUT = pd.Timestamp("2020-01-01")
STORE = Path.home() / ".cache" / "wo43_xgbretrain"
OUTD = HERE.parents[1] / "out" / "xgbretrain"
INPUTS = OUTD / "inputs"


def log(m):
    print(f"[{time.strftime('%H:%M:%S')}] {m}", flush=True)


def sha256(path, chunk=1 << 24):
    h = hashlib.sha256()
    with open(path, "rb") as f:
        while b := f.read(chunk):
            h.update(b)
    return h.hexdigest()


def rd(path, cols):
    is_ts = str(pq.read_schema(path).field("date").type).startswith("timestamp")
    f = ([("date", ">=", pd.Timestamp("2007-01-02")), ("date", "<=", pd.Timestamp("2019-12-31"))] if is_ts
         else [("date", ">=", "2007-01-02"), ("date", "<=", "2019-12-31")])
    d = pd.read_parquet(path, columns=cols, filters=f)
    d["date"] = pd.to_datetime(d["date"]).astype("datetime64[ns]")
    d["ticker"] = d["ticker"].astype(str)
    assert d["date"].max() < HOLDOUT, f"HOLD-OUT BREACH {path.name}"
    return d


def main():
    t0 = time.time()
    STORE.mkdir(parents=True, exist_ok=True)
    INPUTS.mkdir(parents=True, exist_ok=True)
    meta = {"base_panel": str(BASE_PANEL), "inputs": {}}
    log("hashing base panel ...")
    assert sha256(BASE_PANEL) == BASE_SHA, "base panel changed since Step 1"
    meta["base_panel_sha256"] = BASE_SHA

    # ---- factor inputs: copy into the worktree, hash, check duplicate copies
    for k, (src, _) in SOURCES.items():
        h = sha256(src)
        dst = INPUTS / f"{k}.parquet"
        if not dst.exists() or sha256(dst) != h:
            shutil.copy2(src, dst)
        assert sha256(dst) == h
        meta["inputs"][k] = {"source": str(src), "sha256": h, "copy": str(dst)}
        if k in DUP_COPIES:
            assert sha256(DUP_COPIES[k]) == h, f"duplicate copy of {k} differs"
            meta["inputs"][k]["duplicate_copy_identical"] = str(DUP_COPIES[k])
        log(f"  input {k} sha {h[:12]}")

    # ---- base panel, exactly as the cached cell loaded it
    fcols = list(SC.FEATURE_SETS["price_fund"])
    A.PANEL = BASE_PANEL
    R = A.raw_pass()
    raw_idx = np.flatnonzero(R["keep"])
    raw_idx = raw_idx[np.argsort(R["dates"][raw_idx], kind="stable")]
    f_exit = R["exit_date"][raw_idx]
    tick_order = R["order"]
    del R
    df, _ = W.load_panel_prepared(BASE_PANEL, ["close", "open", "market_cap"] + fcols, list(F.FEATURE_COLS), 40)
    assert (df["date"].to_numpy() == np.sort(df["date"].to_numpy())).all()
    assert list(df["ticker"].cat.categories) == tick_order
    keep = df["date"].to_numpy() < np.datetime64(HOLDOUT)
    n = int(keep.sum())
    assert keep[:n].all() and not keep[n:].any()          # date-sorted -> prefix
    df = df.iloc[:n]
    f_exit = f_exit[:n]
    y = df[F.TRADABLE_LABEL_COL].to_numpy(np.float32).copy()
    bad = np.isnat(f_exit) | (f_exit >= np.datetime64(HOLDOUT))
    meta["labels_nulled_exit_2020plus_or_missing"] = int((bad & np.isfinite(y)).sum())
    y[bad] = np.nan
    dates = df["date"].to_numpy()
    codes = df["ticker"].cat.codes.to_numpy().astype(np.int32)
    tick = df["ticker"].astype(str).to_numpy()
    base = np.array([t.split("__post")[0] for t in tick])
    meta["rows"] = n
    meta["post_segment_rows"] = int((base != tick).sum())
    meta["date_range"] = [str(pd.Timestamp(dates[0]).date()), str(pd.Timestamp(dates[-1]).date())]
    log(f"base rows < 2020: {n:,}")

    # ---- new columns by key lookup (no merge reordering)
    key = pd.MultiIndex.from_arrays([base, dates])
    newX = np.full((n, len(NEW_COLS)), np.nan, dtype=np.float32)
    for j, c in enumerate(NEW_COLS[:4]):
        src_col = SOURCES[c][1]
        d = rd(INPUTS / f"{c}.parquet", ["ticker", "date", src_col])
        assert not d.duplicated(["ticker", "date"]).any()
        ix = pd.MultiIndex.from_arrays([d["ticker"].to_numpy(), d["date"].to_numpy()]).get_indexer(key)
        ok = ix >= 0
        newX[ok, j] = d[src_col].to_numpy(np.float64)[ix[ok]].astype(np.float32)
        meta.setdefault("key_match_rows", {})[c] = int(ok.sum())
        log(f"  {c}: matched {ok.sum():,}, finite {np.isfinite(newX[:, j]).sum():,}")

    # str_lowturn on the screen's own universe (v2 column c, eligible_cap150, 2007-2019)
    import screen_volshock as SV                                          # read-only import
    v2 = rd(V2, ["ticker", "date", "eligible_cap150"])
    tm = pd.read_csv(MAIN / "data" / "sharadar" / "tickers_master.csv", dtype=str,
                     usecols=["ticker", "sicindustry"]).drop_duplicates("ticker")
    spac = set(tm.loc[tm["sicindustry"].fillna("").str.contains("Blank Check"), "ticker"])
    old_t = set(pd.read_parquet(MAIN / "out" / "reset2026" / "composite_panel.parquet", columns=["ticker"])["ticker"].astype(str).unique())
    v2 = v2[v2["eligible_cap150"].astype(bool) & (v2["ticker"].isin(old_t) | ~v2["ticker"].isin(spac))]
    vs = rd(INPUTS / "volshock_inputs.parquet", ["ticker", "date", "r_1m", "turnover_21"])
    U = v2.merge(vs, on=["ticker", "date"], how="left")
    assert len(U) == len(v2)
    U = U.sort_values(["date", "ticker"]).reset_index(drop=True)
    U["str_lowturn"], _ = SV.str_lowturn_rank(U)
    ix = pd.MultiIndex.from_arrays([U["ticker"].to_numpy(), U["date"].to_numpy()]).get_indexer(key)
    ok = ix >= 0
    newX[ok, 4] = U["str_lowturn"].to_numpy(np.float64)[ix[ok]].astype(np.float32)
    meta.setdefault("key_match_rows", {})["str_lowturn"] = int(ok.sum())
    meta["str_lowturn_universe_rows"] = int(len(U))
    log(f"  str_lowturn: matched {ok.sum():,}, finite {np.isfinite(newX[:, 4]).sum():,}")

    # ---- PIT-universe flag (the cached cell's scored set)
    pit_map = W.load_pit_universe()
    in_pit = np.zeros(n, bool)
    ds = pd.Series(dates)
    bounds = np.flatnonzero(np.r_[True, dates[1:] != dates[:-1], True])
    for a, b in zip(bounds[:-1], bounds[1:]):
        s = pit_map.get(str(pd.Timestamp(dates[a]).date()), frozenset())
        in_pit[a:b] = np.isin(base[a:b], list(s))

    # ---- coverage (label-free)
    cov = {}
    era = dates >= np.datetime64("2007-01-02")
    for j, c in enumerate(NEW_COLS):
        fin = np.isfinite(newX[:, j])
        cov[c] = {"all_rows": float(fin.mean()), "rows_2007_2019": float(fin[era].mean()),
                  "pit_rows_2007_2019": float(fin[era & in_pit].mean())}
    meta["coverage"] = cov
    meta["any_new_finite_rows_2007_2019"] = float(np.isfinite(newX[era]).any(axis=1).mean())
    meta["in_pit_rows"] = int(in_pit.sum())

    # ---- write memmaps
    X24 = df[fcols].to_numpy(np.float32)
    np.save(STORE / "X24.npy", np.ascontiguousarray(X24))
    np.save(STORE / "X29.npy", np.ascontiguousarray(np.hstack([X24, newX])))
    np.save(STORE / "y.npy", y)
    np.save(STORE / "dates.npy", dates.astype("datetime64[ns]").astype(np.int64))
    np.save(STORE / "exit.npy", f_exit.astype("datetime64[ns]").astype(np.int64))
    np.save(STORE / "codes.npy", codes)
    np.save(STORE / "in_pit.npy", in_pit)
    np.save(STORE / "newfinite.npy", np.isfinite(newX))
    (STORE / "tickers.json").write_text(json.dumps(tick_order))
    meta["feature_cols_24"] = fcols
    meta["new_cols"] = NEW_COLS
    meta["store"] = str(STORE)
    meta["store_sha256"] = {p.name: sha256(p) for p in sorted(STORE.glob("*.npy"))}
    meta["elapsed_sec"] = round(time.time() - t0, 1)
    (OUTD / "store_meta.json").write_text(json.dumps(meta, indent=1, default=str))
    log(f"done -> {OUTD / 'store_meta.json'}")


if __name__ == "__main__":
    main()
