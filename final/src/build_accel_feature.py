"""
Materialise accel_20 onto the point-in-time panel, without rebuilding it.

    python3 build_accel_feature.py --check      verify only, write nothing
    python3 build_accel_feature.py              add the column to the panel

Promoted 2026-09-16 on the strength of the path-order screen
(models/2026-09-16-order-information-in-20-day-paths.md). accel_20 is the only
order-aware statistic that survived it, and it survived WEAKLY -- paired against
its own matched shuffles, -1.74 on IC and -1.97 at the traded tail, one sign in
17 of 20 years, empirical p ~0.18 against an exact permutation null.

SO THIS SCRIPT DOES NOT PUT IT IN THE MODEL. It adds a CANDIDATE column
(features.CANDIDATE_FEATURE_COLS) that the screens can see and that
FEATURE_COLS does not contain. Promotion to a traded feature requires clearing
the feature_ic screen and then a pre-registered sweep cell, at
promotion_trial_count = 6.

WHY NOT REBUILD THE PANEL
-------------------------
features.py now computes accel_20, so any future rebuild gets it for free. But
rebuilding today costs a full price pull plus the Sharadar fundamentals merge,
and would change dozens of other cells' inputs for a reason unrelated to this
feature -- which would silently invalidate the score caches every current result
rests on. Adding one derived column, computed from `close` already in the panel,
changes nothing else.

DEFINITION FIDELITY IS THE POINT
--------------------------------
The screened column and the promoted column must be the same column. If they
drift, the screen's evidence stops applying to the thing being traded, and that
is a failure mode this project has paid for before. `--check` asserts
features.accel_20() agrees with screen_path_order's sliding-window
implementation to 1e-12 on real panel data, including the NaN mask, before
anything is written.
"""
import argparse
import sys
import time
from pathlib import Path

import numpy as np
import pandas as pd
import pyarrow as pa
import pyarrow.parquet as pq

sys.path.insert(0, str(Path(__file__).resolve().parent))
from features import (CANDIDATE_FEATURE_COLS, FEATURE_COLS,   # noqa: E402
                      OUT_DIR, accel_20)

PANEL = OUT_DIR / "features_with_fundamentals_sharadar_pit.parquet"
COL = "accel_20"
CHUNK_ROWS = 400_000


def compute(panel_cols: pd.DataFrame) -> np.ndarray:
    """ticker/date/close -> accel_20 in the SAME ROW ORDER as the input.

    Returned positionally rather than as a (ticker, date) lookup on purpose. A
    12M-row MultiIndex reindex per write chunk costs more memory than the panel
    itself; a float64 array of the same length is 98MB and can be sliced
    sequentially while the file streams. The write step verifies the row order
    it assumes rather than trusting it -- see _assert_same_order.
    """
    order = np.argsort(
        np.lexsort((panel_cols["date"].to_numpy(),
                    panel_cols["ticker"].to_numpy())), kind="stable")
    d = panel_cols.iloc[np.lexsort((panel_cols["date"].to_numpy(),
                                    panel_cols["ticker"].to_numpy()))]
    vals = d.groupby("ticker", sort=False)["close"].transform(
        accel_20).to_numpy(np.float64)
    return vals[order]


def _assert_same_order(tbl, exp_t, exp_d, offset):
    if tbl.num_rows != len(exp_t):
        raise SystemExit(f"batch at row {offset:,}: length {tbl.num_rows} vs "
                         f"{len(exp_t)} -- refusing to write")
    t = tbl.column("ticker").to_numpy(zero_copy_only=False)
    d = tbl.column("date").to_numpy(zero_copy_only=False)
    if not np.array_equal(t, exp_t) or not np.array_equal(d, exp_d):
        raise SystemExit(
            f"batch at row {offset:,}: streamed row order differs from the "
            f"order the columns were read in. The positional join is unsafe on "
            f"this pyarrow version -- refusing to write.")


def verify(df: pd.DataFrame, n_tickers: int = 25, seed: int = 0) -> None:
    """The promoted column must equal the screened one, NaN mask included."""
    import screen_path_order as S
    assert S.WIN == 20, f"screen window is {S.WIN}, accel_20 assumes 20"
    rng = np.random.default_rng(seed)
    tick = df["ticker"].unique()
    pick = rng.choice(tick, size=min(n_tickers, len(tick)), replace=False)
    checked = 0
    for t in pick:
        g = df[df["ticker"] == t].sort_values("date")
        if len(g) < 60:
            continue
        close = g["close"].to_numpy(np.float64)
        lp = np.log(np.where(close > 0, close, np.nan))
        lr = np.diff(lp, prepend=np.nan)
        lr[0] = np.nan
        ref = S._path_features(lr, np.random.default_rng(0))["accel_20"]
        got = accel_20(g["close"].reset_index(drop=True)).to_numpy(np.float64)
        assert np.array_equal(np.isfinite(got), np.isfinite(ref)), \
            f"{t}: NaN masks differ ({np.isfinite(got).sum()} vs {np.isfinite(ref).sum()})"
        k = np.isfinite(got)
        if k.any():
            m = float(np.max(np.abs(got[k] - ref[k])))
            assert m < 1e-12, f"{t}: max abs diff {m:.3g}"
        checked += 1
    print(f"  fidelity: {checked} tickers agree with screen_path_order "
          f"to <1e-12, NaN masks identical")


def main(check_only: bool = False):
    if COL not in CANDIDATE_FEATURE_COLS:
        raise SystemExit(f"{COL} is not in CANDIDATE_FEATURE_COLS")
    if COL in FEATURE_COLS:
        raise SystemExit(
            f"{COL} is in FEATURE_COLS. This script adds a CANDIDATE column; "
            f"a feature reaching FEATURE_COLS must go through the screen and a "
            f"pre-registered sweep cell first.")
    if not PANEL.exists():
        raise SystemExit(f"{PANEL} not found")

    t0 = time.time()
    existing = set(pq.ParquetFile(PANEL).schema_arrow.names)
    print(f"{PANEL.name}: {len(existing)} columns, "
          f"{PANEL.stat().st_size / 1e9:.2f} GB")
    if COL in existing:
        print(f"  {COL} is already present -- it will be RECOMPUTED and replaced.")

    print("reading ticker/date/close ...", flush=True)
    base = pd.read_parquet(PANEL, columns=["ticker", "date", "close"])
    print(f"  {len(base):,} rows")

    print("verifying the promoted definition against the screened one ...")
    verify(base)

    print("computing ...", flush=True)
    acc = compute(base)
    n_ok = int(np.isfinite(acc).sum())
    print(f"  {n_ok:,} finite of {len(acc):,} "
          f"({n_ok / len(acc):.1%}); mean {np.nanmean(acc):+.5f}, "
          f"sd {np.nanstd(acc):.5f}")
    if n_ok / len(acc) < 0.5:
        raise SystemExit("under half the panel resolved -- refusing to write")

    if check_only:
        print(f"\n--check: nothing written ({time.time() - t0:.0f}s)")
        return

    key_t = base["ticker"].to_numpy()
    key_d = base["date"].to_numpy()
    del base

    tmp = PANEL.with_suffix(".parquet.tmp")
    pf = pq.ParquetFile(PANEL)
    # Append the column ARROW-NATIVELY rather than round-tripping each batch
    # through pandas. to_pandas()/from_pandas() silently re-types columns --
    # the first version of this script turned `ticker` from large_string into
    # string across the whole 2.3GB panel, which nothing downstream would have
    # reported. Appending to the arrow table leaves every existing column's
    # type byte-identical.
    #
    # TICKER_TYPE normalises the one column that already drifted, so this panel
    # matches every sibling panel in the project again.
    src_schema = pf.schema_arrow
    fields = []
    for f in src_schema:
        if f.name == COL:
            continue
        if f.name == "ticker" and pa.types.is_string(f.type):
            f = f.with_type(pa.large_string())
        fields.append(f)
    out_schema = pa.schema(fields + [pa.field(COL, pa.float64())])
    writer = None
    written = 0
    print(f"writing {tmp.name} ...", flush=True)
    try:
        for batch in pf.iter_batches(batch_size=CHUNK_ROWS):
            tbl = pa.Table.from_batches([batch])
            if COL in tbl.column_names:
                tbl = tbl.drop([COL])
            lo, hi = written, written + tbl.num_rows
            # Never assume the streamed order matches the order the columns
            # were read in. If it ever diverged, every accel_20 value would be
            # attached to the wrong row -- a silent, total corruption of the
            # panel that no downstream check would catch.
            _assert_same_order(tbl, key_t[lo:hi], key_d[lo:hi], lo)
            tbl = tbl.append_column(COL, pa.array(acc[lo:hi], type=pa.float64()))
            tbl = tbl.cast(out_schema)
            if writer is None:
                writer = pq.ParquetWriter(tmp, out_schema)
            writer.write_table(tbl)
            written += tbl.num_rows
            if written % (CHUNK_ROWS * 10) == 0:
                print(f"  {written:,} / {len(acc):,}", flush=True)
    finally:
        if writer is not None:
            writer.close()

    got = pq.ParquetFile(tmp)
    if got.metadata.num_rows != pf.metadata.num_rows:
        tmp.unlink()
        raise SystemExit(f"row count changed {pf.metadata.num_rows:,} -> "
                         f"{got.metadata.num_rows:,} -- not replacing the panel")
    if COL not in got.schema_arrow.names:
        tmp.unlink()
        raise SystemExit(f"{COL} missing from the rewrite -- not replacing")
    # atomic: the panel is either the old one or the new one, never a partial
    tmp.replace(PANEL)
    print(f"\nwritten {PANEL} (+{COL}, {written:,} rows, "
          f"{time.time() - t0:.0f}s)")
    print("\nNEXT: the screen, not the model.")
    print("  python3 -m sweep.cli features --era nominate "
          "--features path --horizons 40")
    print(f"  {COL} is a CANDIDATE column; FEATURE_COLS is unchanged, so no "
          f"model input moved.")


if __name__ == "__main__":
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--check", action="store_true",
                    help="verify and report, write nothing")
    a = ap.parse_args()
    main(a.check)
