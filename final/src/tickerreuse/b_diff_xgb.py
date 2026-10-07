"""WO-47 B-XGB step 1: diff the Sep-11 build (features_with_rates_sharadar_pit, cache input) against the
current XGB panel (features_with_fundamentals_sharadar_pit, frozen 2026-10-06 copy) on pre-2020 rows.

Writes ~/.cache/wo47/b_xgb_rowdiff.parquet (one row per differing (ticker, date): side + one bool per
column) and final/out/tickerreuse/b_xgb_diff_summary.json.
"""
import json

import numpy as np
import pandas as pd
import pyarrow.parquet as pq

from common import OUT, SCRATCH, FROZEN, MAIN

SEP11 = MAIN / "out" / "features_with_rates_sharadar_pit.parquet"
CUR = FROZEN / "features_with_fundamentals_sharadar_pit.parquet"
CUT = pd.Timestamp("2020-01-01")


def load(p, cols):
    t = pq.read_table(p, columns=["ticker", "date"] + cols, filters=[("date", "<", CUT)])
    df = t.to_pandas()
    df["ticker"] = df["ticker"].astype(str)
    df["date"] = pd.to_datetime(df["date"]).astype("datetime64[ns]")
    return df


def main():
    a_cols = pq.ParquetFile(SEP11).schema_arrow.names
    b_cols = pq.ParquetFile(CUR).schema_arrow.names
    cols = [c for c in b_cols if c in a_cols and c not in ("ticker", "date")]
    print(f"{len(cols)} common columns")
    a = load(SEP11, cols)
    b = load(CUR, cols)
    print(f"Sep-11 pre-2020 {len(a):,} rows {a.ticker.nunique():,} tickers; current {len(b):,} rows {b.ticker.nunique():,}")
    m = a.merge(b, on=["ticker", "date"], how="outer", suffixes=("_a", "_b"), indicator=True)
    del a, b
    side = m["_merge"].astype(str).map({"left_only": "sep11_only", "right_only": "current_only", "both": "both"})
    flags = {}
    both = (side == "both").to_numpy()
    for c in cols:
        x = m[f"{c}_a"].to_numpy(np.float64)
        y = m[f"{c}_b"].to_numpy(np.float64)
        flags[c] = both & ~((x == y) | (np.isnan(x) & np.isnan(y)))
    anydiff = np.zeros(len(m), bool)
    for c in cols:
        anydiff |= flags[c]
    differing = (~both) | anydiff
    D = pd.DataFrame({"ticker": m["ticker"].to_numpy()[differing], "date": m["date"].to_numpy()[differing],
                      "side": side.to_numpy()[differing]})
    for c in cols:
        D[f"d_{c}"] = flags[c][differing]
    D.to_parquet(SCRATCH / "b_xgb_rowdiff.parquet", index=False)
    summ = {"common_columns": cols, "rows_union": int(len(m)), "rows_both": int(both.sum()),
            "sep11_only_rows": int((side == "sep11_only").sum()),
            "current_only_rows": int((side == "current_only").sum()),
            "sep11_only_tickers": int(m.loc[side == "sep11_only", "ticker"].nunique()),
            "current_only_tickers": int(m.loc[side == "current_only", "ticker"].nunique()),
            "both_rows_differing": int(anydiff.sum()),
            "differing_rows_total": int(differing.sum()),
            "differing_by_column": {c: int(flags[c].sum()) for c in cols if flags[c].any()}}
    (OUT / "b_xgb_diff_summary.json").write_text(json.dumps(summ, indent=2))
    print(json.dumps({k: v for k, v in summ.items() if k != "common_columns"}, indent=2))


if __name__ == "__main__":
    main()
