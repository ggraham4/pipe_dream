"""
Add the 14 fundamental features to the rebuilt price panel.

WHY THIS IS SEPARATE FROM build_features_sharadar.py
-----------------------------------------------------
Gate B4 was measured on the augmented 25-column model. Re-running it on the
11 price features alone would not be a like-for-like comparison, so the
fundamentals have to be on the new universe before any gate number means
anything. The old fundamentals cover 1,837 of the 4,030 universe tickers
(45.6%), and the missing half is disproportionately the dead companies the
universe rebuild just recovered -- so re-running on what was already on disk
would have measured the old survivor pool wearing a new label.

HOW COMPARABILITY IS PRESERVED
------------------------------
`process_ticker` is IMPORTED from fundamentals_features_beta, not
reimplemented. Every ratio, every guard against division by zero, the
annual-only filter on flow concepts, the shares_outstanding_dei fallback and
the fundamentals_age_days calculation are the same code that produced the
existing panel. A difference in a downstream number can therefore come from
the data or the universe, but not from two copies of a formula drifting.

What this file does is only the translation: SF1's wide schema into the
tidy long format that loader expects.

    ticker, concept, form, fiscal_period, filed_date, value

CONCEPT MAPPING -- verified against real rows in an earlier round, see
sharadar_data_pull.py's header for how each was checked:

    total_assets        -> assets        revenue             -> revenue
    total_liabilities   -> liabilities   net_income          -> netinc
    stockholders_equity -> equity        gross_profit        -> gp
    cash                -> cashneq       operating_income    -> opinc
    long_term_debt      -> debtnc        operating_cash_flow -> ncfo
    shares_outstanding  -> sharesbas     capex               -> capex
                                         rnd_expense         -> rnd

`shares_outstanding_dei` has no Sharadar equivalent and is deliberately not
emitted; process_ticker already falls back to shares_outstanding when it is
absent, which is why that fallback exists.

TWO POINT-IN-TIME DECISIONS, BOTH LOAD-BEARING
----------------------------------------------
1. `filed_date` is SF1's `date`, NOT `calendardate`. `calendardate` is the
   period end and precedes the filing by roughly 4-6 weeks; using it would
   put about a month of look-ahead into every fundamental feature, since the
   merge_asof join is what makes this point-in-time at all.

2. Only ARQ and ARY -- as-reported, never restated. MR* dimensions carry
   figures revised after the fact, which would leak a later correction into
   a value the model is supposed to have seen at the time.

   ARY rows are emitted as form="10-K", fiscal_period="FY"; ARQ rows as
   form="10-Q" with the quarter code. That matters because FLOW_CONCEPTS are
   filtered to annual-only inside build_ticker_fact_series, so only ARY rows
   ever feed revenue, net income and the other flows -- which is how the
   quarterly cumulative-vs-discrete ambiguity is avoided.

    python3 build_features_fundamentals_sharadar.py

OUTPUT
    final/out/features_with_fundamentals_sharadar_pit.parquet
"""
import gc
from pathlib import Path

import numpy as np
import pandas as pd
import pyarrow as pa
import pyarrow.parquet as pq

from features import (FEATURE_COLS, LABEL_COL, TRADABLE_LABEL_COL,
                      OUT_DIR, PROJECT_ROOT)
from fundamentals_features_beta import (FUNDAMENTAL_FEATURE_COLS,
                                        process_ticker)

PRICE_PANEL = OUT_DIR / "features_sharadar_pit.parquet"
SF1 = PROJECT_ROOT / "data" / "sharadar" / "sf1_fundamentals.parquet"
OUT = OUT_DIR / "features_with_fundamentals_sharadar_pit.parquet"

CONCEPT_TO_SF1 = {
    "total_assets": "assets",
    "total_liabilities": "liabilities",
    "stockholders_equity": "equity",
    "cash": "cashneq",
    "long_term_debt": "debtnc",
    "shares_outstanding": "sharesbas",
    "revenue": "revenue",
    "net_income": "netinc",
    "gross_profit": "gp",
    "operating_income": "opinc",
    "operating_cash_flow": "ncfo",
    "capex": "capex",
    "rnd_expense": "rnd",
}
PRICE_COLS = ["open", "high", "low", "close", "volume"]


def tidy_sf1():
    """SF1 wide -> the long schema fundamentals_features_beta consumes."""
    df = pd.read_parquet(SF1)
    df = df[df["dimension"].isin(["ARQ", "ARY"])].copy()
    # Force nanosecond resolution. pandas 2 preserves whatever unit the
    # parquet file stored -- SF1 comes back as datetime64[us] -- and
    # merge_asof requires the two join keys to match EXACTLY, not merely to
    # be comparable. The price panel is [ns], so [us] here fails with
    # "incompatible merge keys" deep inside process_ticker.
    df["filed_date"] = (pd.to_datetime(df["date"], errors="coerce")
                        .astype("datetime64[ns]"))
    df = df[df["filed_date"].notna()]

    # ARY -> annual (10-K/FY); ARQ -> quarterly. Only ARY feeds flow
    # concepts, via the annual_only filter inside build_ticker_fact_series.
    is_ary = df["dimension"].eq("ARY")
    df["form"] = np.where(is_ary, "10-K", "10-Q")
    # Quarter code from the report period's month end. Companies on a
    # non-calendar fiscal year fall outside this map and are marked "Q?"
    # rather than silently defaulted to Q1 -- the label is INERT either way
    # (flow concepts filter to form 10-K + FY, which only ARY rows carry,
    # and stock concepts ignore fiscal_period entirely), but a field that
    # is wrong and looks right is exactly the kind of thing that gets
    # believed later.
    qtr = (df["reportperiod"].astype(str).str[5:7]
           .map({"03": "Q1", "06": "Q2", "09": "Q3", "12": "Q4"}))
    df["fiscal_period"] = np.where(is_ary, "FY", qtr.fillna("Q?"))

    frames = []
    for concept, col in CONCEPT_TO_SF1.items():
        if col not in df.columns:
            print(f"  WARNING: SF1 has no column '{col}' for {concept}")
            continue
        sub = df.loc[df[col].notna(),
                     ["ticker", "form", "fiscal_period", "filed_date", col]].copy()
        sub = sub.rename(columns={col: "value"})
        sub["concept"] = concept
        frames.append(sub[["ticker", "concept", "form", "fiscal_period",
                           "filed_date", "value"]])
    out = pd.concat(frames, ignore_index=True)
    out["ticker"] = out["ticker"].astype(str)
    return out


def main():
    print("SF1 -> tidy long format...")
    raw = tidy_sf1()
    print(f"  {len(raw):,} fact rows, {raw['ticker'].nunique():,} tickers, "
          f"filed {raw['filed_date'].min().date()} .. "
          f"{raw['filed_date'].max().date()}")
    print(f"  per concept: "
          f"{raw['concept'].value_counts().reindex(CONCEPT_TO_SF1).to_dict()}")
    raw_by_ticker = {t: g for t, g in raw.groupby("ticker", sort=False)}
    del raw
    gc.collect()

    print("\nloading price panel...")
    price = pd.read_parquet(PRICE_PANEL)
    price["date"] = pd.to_datetime(price["date"]).astype("datetime64[ns]")
    price["ticker"] = price["ticker"].astype(str)
    price = price.sort_values(["ticker", "date"]).reset_index(drop=True)
    print(f"  {len(price):,} rows, {price['ticker'].nunique():,} tickers")

    keep = (["ticker", "date"] + PRICE_COLS + FEATURE_COLS
            + [LABEL_COL, TRADABLE_LABEL_COL] + FUNDAMENTAL_FEATURE_COLS)
    schema = pa.schema(
        [("ticker", pa.string()), ("date", pa.timestamp("ns"))]
        + [(c, pa.float64()) for c in keep if c not in ("ticker", "date")])

    OUT.parent.mkdir(parents=True, exist_ok=True)
    writer = pq.ParquetWriter(OUT, schema)
    groups = price.groupby("ticker", sort=False)
    n = 0
    covered = 0
    for i, (tk, g) in enumerate(groups, 1):
        raw_g = raw_by_ticker.get(tk)
        if raw_g is not None:
            covered += 1
        fnd = process_ticker(tk, g[["ticker", "date", "close"]], raw_g)
        fnd["date"] = pd.to_datetime(fnd["date"]).astype("datetime64[ns]")
        m = g.merge(fnd.drop(columns=["ticker"]), on="date", how="left")
        for c in FUNDAMENTAL_FEATURE_COLS:
            m[c] = (pd.to_numeric(m[c], errors="coerce")
                    .replace([np.inf, -np.inf], np.nan))
        m = m[keep]
        m["ticker"] = m["ticker"].astype(str)
        for c in keep:
            if c not in ("ticker", "date"):
                m[c] = pd.to_numeric(m[c], errors="coerce").astype("float64")
        writer.write_table(pa.Table.from_pandas(m, schema=schema,
                                                preserve_index=False))
        n += len(m)
        if i % 500 == 0 or i == len(groups):
            print(f"  {i:,}/{len(groups):,} tickers, {n:,} rows")
    writer.close()

    print(f"\n{n:,} rows -> {OUT}")
    print(f"tickers with any fundamentals: {covered:,} of {len(groups):,} "
          f"({100 * covered / len(groups):.1f}%)")

    print("\ncoverage of each derived ratio (non-null share of all rows):")
    chk = pd.read_parquet(OUT, columns=FUNDAMENTAL_FEATURE_COLS)
    for c in FUNDAMENTAL_FEATURE_COLS:
        print(f"  {c:<24} {chk[c].notna().mean():.1%}")
    print("\nCompare these against models/fundamentals-beta-results.md. A large")
    print("drop would mean the SF1 translation is losing facts the old CSV")
    print("pipeline captured; a large rise is expected, since the old panel")
    print("simply had no fundamentals for half the universe.")


if __name__ == "__main__":
    main()
