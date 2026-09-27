"""
WO-18 verification (COO request, 2026-09-26; NOT a definition change).
Gabe's Retrain ALL swapped composite_panel_v2.parquet at 22:44:48, and
outcome_cache_v2.parquet at 22:44:53, while the screen was starting: the hash
was logged at 22:44:41 and column c was loaded at 22:44:50. This checks that
the in-era slice (2007-01-01..2019-12-31) of every column the screen reads is
identical in the pre-refresh backup and the current file.

  panel: ticker, date, forward_return_tradable_40, the 8 factors, sector,
         eligible_cap150/500/2000
  outcome cache: ticker, date, gross_return_40
  plus: the old-grid ticker set (composite_panel.parquet, rewritten 22:46:51)
  and the tickers_master SPAC set, vs what the pre-reg validation used.

Output: out/seasonality/panel_swap_check.json
"""
import hashlib
import json
import sys
from pathlib import Path

import pandas as pd

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE.parent / "reset2026"))
import composite as C  # noqa: E402

R26 = Path("/Users/ggraham/pipe_dream/final/out/reset2026")
SH = Path("/Users/ggraham/pipe_dream/final/data/sharadar")
OUT = Path(__file__).resolve().parents[2] / "out" / "seasonality"
FILT = [("date", ">=", "2007-01-01"), ("date", "<=", "2019-12-31")]
PANEL_COLS = ["ticker", "date", "forward_return_tradable_40"] + C.FACTOR_COLS + \
             ["sector", "eligible_cap150", "eligible_cap500", "eligible_cap2000"]


def file_sha(p):
    h = hashlib.sha256()
    with open(p, "rb") as f:
        while b := f.read(1 << 24):
            h.update(b)
    return h.hexdigest()


def slice_sha(path, cols):
    try:
        d = pd.read_parquet(path, columns=cols, filters=FILT)
    except Exception:   # timestamp-typed date column
        d = pd.read_parquet(path, columns=cols, filters=[("date", ">=", pd.Timestamp(FILT[0][2])),
                                                         ("date", "<=", pd.Timestamp(FILT[1][2]))])
    d["date"] = pd.to_datetime(d["date"]).dt.strftime("%Y-%m-%d")
    d["ticker"] = d["ticker"].astype(str)
    d = d.sort_values(["ticker", "date"]).reset_index(drop=True)[cols]
    h = hashlib.sha256(pd.util.hash_pandas_object(d, index=False).to_numpy().tobytes()).hexdigest()
    return {"rows": int(len(d)), "sha256": h, "max_date": d["date"].max()}


def main():
    r = {}
    pairs = {"composite_panel_v2": (R26 / "composite_panel_v2_through_2026-09-24.parquet",
                                    R26 / "composite_panel_v2.parquet", PANEL_COLS),
             "outcome_cache_v2": (R26 / "outcome_cache_v2_through_2026-09-24.parquet",
                                  R26 / "outcome_cache_v2.parquet", ["ticker", "date", "gross_return_40"])}
    for name, (old, new, cols) in pairs.items():
        a, b = slice_sha(old, cols), slice_sha(new, cols)
        r[name] = {"backup": str(old), "backup_file_sha256": file_sha(old), "backup_slice": a,
                   "current": str(new), "current_file_sha256": file_sha(new), "current_slice": b,
                   "in_era_slice_identical": a == b}
    old_t = set(pd.read_parquet(R26 / "composite_panel.parquet", columns=["ticker"])["ticker"].astype(str))
    ref = set((R26.parent.parent / "src" / "reset2026" / "old_grid_tickers_4011.txt").read_text().split()) \
        if (Path(__file__).resolve().parents[1] / "reset2026" / "old_grid_tickers_4011.txt").exists() else None
    if ref is None:
        ref = set((Path(__file__).resolve().parents[1] / "reset2026" / "old_grid_tickers_4011.txt").read_text().split())
    r["old_grid_ticker_set"] = {"n_current": len(old_t), "n_reference_4011": len(ref), "identical": old_t == ref}
    tm = pd.read_csv(SH / "tickers_master.csv", dtype=str, usecols=["ticker", "sicindustry"]).drop_duplicates("ticker")
    r["tickers_master_mtime"] = pd.Timestamp((SH / "tickers_master.csv").stat().st_mtime, unit="s").isoformat()
    r["spac_count_current"] = int(tm["sicindustry"].fillna("").str.contains("Blank Check").sum())
    r["all_identical"] = all(r[k]["in_era_slice_identical"] for k in pairs) and r["old_grid_ticker_set"]["identical"]
    (OUT / "panel_swap_check.json").write_text(json.dumps(r, indent=2))
    print(json.dumps(r, indent=2))


if __name__ == "__main__":
    main()
