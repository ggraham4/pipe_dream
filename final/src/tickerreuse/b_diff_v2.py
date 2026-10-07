"""WO-47 B-v2 (factor half): composite_panel_v2_through_2026-09-08 vs current composite_panel_v2
(frozen 2026-10-06 copy) on pre-2020 rows, all common columns (eligibility flags, market_cap, price,
the composite factors). Writes ~/.cache/wo47/b_v2_rowdiff.parquet and
final/out/tickerreuse/b_v2_diff_summary.json."""
import json

import numpy as np
import pandas as pd
import pyarrow.parquet as pq

from common import OUT, SCRATCH, FROZEN, MAIN

SEPV2 = MAIN / "out" / "reset2026" / "composite_panel_v2_through_2026-09-08.parquet"
CURV2 = FROZEN / "composite_panel_v2.parquet"
CUT = pd.Timestamp("2020-01-01")


def load(p, cols):
    typ = pq.ParquetFile(p).schema_arrow.field("date").type
    cut = CUT.date().isoformat() if "string" in str(typ) else CUT
    df = pq.read_table(p, columns=["ticker", "date"] + cols, filters=[("date", "<", cut)]).to_pandas()
    df["ticker"] = df["ticker"].astype(str)
    df["date"] = pd.to_datetime(df["date"]).astype("datetime64[ns]")
    return df


def eq(x, y):
    if x.dtype.kind in "fiub" and y.dtype.kind in "fiub":
        x = x.astype(np.float64); y = y.astype(np.float64)
        return (x == y) | (np.isnan(x) & np.isnan(y))
    xs, ys = pd.Series(x, dtype=object), pd.Series(y, dtype=object)
    return ((xs == ys) | (xs.isna() & ys.isna())).to_numpy()


def main():
    a_cols = pq.ParquetFile(SEPV2).schema_arrow.names
    b_cols = pq.ParquetFile(CURV2).schema_arrow.names
    cols = [c for c in b_cols if c in a_cols and c not in ("ticker", "date")]
    a, b = load(SEPV2, cols), load(CURV2, cols)
    print(f"sep v2 pre-2020 {len(a):,} rows {a.ticker.nunique():,} tickers; current {len(b):,} rows {b.ticker.nunique():,}")
    m = a.merge(b, on=["ticker", "date"], how="outer", suffixes=("_a", "_b"), indicator=True)
    side = m["_merge"].astype(str).map({"left_only": "sep_only", "right_only": "current_only", "both": "both"}).to_numpy()
    both = side == "both"
    flags = {c: both & ~eq(m[f"{c}_a"].to_numpy(), m[f"{c}_b"].to_numpy()) for c in cols}
    anyd = np.zeros(len(m), bool)
    for c in cols:
        anyd |= flags[c]
    dif = (~both) | anyd
    D = pd.DataFrame({"ticker": m["ticker"].to_numpy()[dif], "date": m["date"].to_numpy()[dif], "side": side[dif]})
    for c in cols:
        D[f"d_{c}"] = flags[c][dif]
    D.to_parquet(SCRATCH / "b_v2_rowdiff.parquet", index=False)
    summ = {"columns_only_sep": [c for c in a_cols if c not in b_cols], "columns_only_current": [c for c in b_cols if c not in a_cols],
            "common_columns": cols, "rows_union": int(len(m)), "rows_both": int(both.sum()),
            "sep_only_rows": int((side == "sep_only").sum()), "current_only_rows": int((side == "current_only").sum()),
            "sep_only_tickers": sorted(set(m.loc[side == "sep_only", "ticker"])),
            "current_only_tickers": sorted(set(m.loc[side == "current_only", "ticker"])),
            "both_rows_differing": int(anyd.sum()), "differing_rows_total": int(dif.sum()),
            "differing_by_column": {c: int(flags[c].sum()) for c in cols if flags[c].any()},
            "differing_both_tickers": int(D.loc[D.side == "both", "ticker"].nunique())}
    (OUT / "b_v2_diff_summary.json").write_text(json.dumps(summ, indent=2))
    print(json.dumps({k: v for k, v in summ.items() if k != "common_columns"}, indent=2)[:4000])


if __name__ == "__main__":
    main()
