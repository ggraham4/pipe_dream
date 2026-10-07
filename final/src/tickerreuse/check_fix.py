"""WO-47 A4a/A4b/A4c checks on the scratch rebuilds. Writes final/out/tickerreuse/fix_checks.json."""
import json

import numpy as np
import pandas as pd
import pyarrow.parquet as pq

from common import OUT, SCRATCH, FROZEN
import build_features_sharadar as BF
from features import FEATURE_COLS, LABEL_COL, TRADABLE_LABEL_COL

CUR = FROZEN / "features_sharadar_pit.parquet"
UNF = SCRATCH / "features_sharadar_pit_unfixed.parquet"
FIX = SCRATCH / "features_sharadar_pit_fixed.parquet"
REUSE = {"ADRX", "ADRX__post20260925"}


def load(p):
    t = pq.read_table(p)
    df = t.to_pandas()
    df["ticker"] = df["ticker"].astype(str)
    return df


def compare(a, b, label):
    """Join on (ticker, date); return dict of counts. Byte identity on float64 bit patterns,
    plus NaN-equals-NaN equality as the pre-registered definition."""
    a = a.set_index(["ticker", "date"]).sort_index()
    b = b.set_index(["ticker", "date"]).sort_index()
    out = {"label": label, "rows_a": len(a), "rows_b": len(b),
           "only_a": int((~a.index.isin(b.index)).sum()), "only_b": int((~b.index.isin(a.index)).sum())}
    idx = a.index.intersection(b.index)
    a, b = a.loc[idx], b.loc[idx]
    cols = [c for c in a.columns if c in b.columns]
    bad_bytes = np.zeros(len(idx), bool)
    bad_val = np.zeros(len(idx), bool)
    per = {}
    for c in cols:
        x = a[c].to_numpy(np.float64)
        y = b[c].to_numpy(np.float64)
        bb = x.view(np.uint64) != y.view(np.uint64)
        vv = ~((x == y) | (np.isnan(x) & np.isnan(y)))
        bad_bytes |= bb
        bad_val |= vv
        if vv.any():
            per[c] = int(vv.sum())
    out.update({"rows_compared": int(len(idx)), "columns": len(cols),
                "rows_not_byte_identical": int(bad_bytes.sum()),
                "rows_not_equal_nan_eq": int(bad_val.sum()), "differing_by_column": per})
    return out


def main():
    cur, unf, fix = load(CUR), load(UNF), load(FIX)
    res = {}
    # A4c: unfixed scratch rebuild == pinned current panel (whole panel, positional AND keyed)
    res["A4c_positional_order_equal"] = bool((cur[["ticker", "date"]].to_numpy() == unf[["ticker", "date"]].to_numpy()).all())
    res["A4c"] = compare(cur, unf, "current vs unfixed rebuild")
    # A4b: fixed vs current on every non-reuse ticker
    keep_c = ~cur.ticker.isin(REUSE)
    keep_f = ~fix.ticker.isin(REUSE)
    res["A4b"] = compare(cur[keep_c], fix[keep_f], "current vs fixed rebuild, non-reuse tickers")
    res["A4b"]["tickers_compared"] = int(cur[keep_c].ticker.nunique())
    # A4a: reuse block. Each segment's features must equal features_for() run on that segment alone.
    spy = BF.load_spy() if BF.SPY_CSV.exists() else None
    import importlib
    BF.SPY_CSV = FROZEN / "SPY.csv"
    spy = BF.load_spy()
    raw = cur[cur.ticker == "ADRX"][["ticker", "date"] + BF.PRICE_COLS].sort_values("date")
    old = raw[raw.date <= "2006-11-03"]
    new = raw[raw.date >= "2026-09-25"].assign(ticker="ADRX__post20260925")
    a4a = {}
    for name, g in (("ADRX", old), ("ADRX__post20260925", new)):
        ref = BF.features_for(g, spy)
        got = fix[fix.ticker == name].sort_values("date").reset_index(drop=True)
        cols = FEATURE_COLS + [LABEL_COL, TRADABLE_LABEL_COL]
        x, y = ref[cols].to_numpy(np.float64), got[cols].to_numpy(np.float64)
        a4a[name] = {"rows": len(got), "equal_to_segment_alone": bool(((x == y) | (np.isnan(x) & np.isnan(y))).all())}
    f_old = fix[fix.ticker == "ADRX"].sort_values("date")
    c_old = cur[cur.ticker == "ADRX"].sort_values("date")
    sep_rows = f_old[(f_old.date >= "2006-09-11") & (f_old.date <= "2006-09-19")]
    a4a["ADRX_2006_09_11_19_tradable_label_nan_fixed"] = bool(sep_rows[TRADABLE_LABEL_COL].isna().all())
    a4a["ADRX_2006_09_11_19_rows"] = int(len(sep_rows))
    a4a["ADRX_2006_09_11_19_label_before_fix"] = [round(v, 4) for v in
        c_old[(c_old.date >= "2006-09-11") & (c_old.date <= "2006-09-19")][TRADABLE_LABEL_COL].tolist()]
    nw = fix[fix.ticker == "ADRX__post20260925"]
    a4a["new_listing_momentum_120_all_nan"] = bool(nw.momentum_120.isna().all())
    a4a["new_listing_pct_from_high_252_all_nan"] = bool(nw.pct_from_high_252.isna().all())
    cn = cur[(cur.ticker == "ADRX") & (cur.date >= "2026-09-25")]
    a4a["new_listing_momentum_120_before_fix"] = [round(v, 4) for v in cn.momentum_120.tolist()]
    # old-entity rows that are NOT near the end are unchanged
    a4a["old_entity_rows_changed"] = compare(c_old[c_old.date <= "2006-11-03"], f_old, "ADRX old entity")
    res["A4a"] = a4a
    (OUT / "fix_checks.json").write_text(json.dumps(res, indent=2, default=str))
    print(json.dumps(res, indent=2, default=str))


if __name__ == "__main__":
    main()
