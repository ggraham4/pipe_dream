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

HOW COMPARABILITY IS PRESERVED (2026-09-22 REWRITE -- read this before the
formulas below, not just the concept mapping)
----------------------------------------------------------------------------
Every ratio, every guard against division by zero, the annual-only filter on
flow concepts, the shares_outstanding_dei fallback and the
fundamentals_age_days calculation below are transcribed line-for-line from
`fundamentals_features_beta.process_ticker` -- NOT redefined. What changed is
HOW they're computed, not WHAT: the original calls `process_ticker` once per
ticker (4,011 calls), and each call does up to 14 separate `pd.merge_asof`
calls internally (one per STOCK/FLOW concept) -- 56,000+ merge_asof calls
total, almost entirely per-call overhead against a fact table (SF1) that's
tiny. This file replaces that with ONE global `pd.merge_asof(..., by=
"ticker")` per concept (14 calls total), exactly the pattern already used
elsewhere in this project for the identical point-in-time join shape
(`sweep/issuance.py`, `reset2026/quality_factors.py`). Measured: 2:42 -> see
the log this rewrite's own run prints.

VALIDATED, not assumed: `--verify-against <old_panel_path>` recomputes
nothing -- it loads both panels and asserts every FUNDAMENTAL_FEATURE_COLS
value agrees on every shared (ticker, date) row, NaN-position included. Run
this once against a copy of the panel the OLD (process_ticker-based) version
of this file produced before trusting the speed-up; see this rewrite's git
commit message for the actual comparison run and result.

`fundamentals_features_beta.py` itself is UNTOUCHED -- 23 other files import
`process_ticker`/`asof_lookup`/`STOCK_CONCEPTS`/`FLOW_CONCEPTS` from it, and
none of them needed this speedup. Changing shared code all of them depend on
to fix one caller's runtime would have been a much larger blast radius than
the actual problem.

What this file does, translation-wise, is unchanged: SF1's wide schema into
the tidy long format the (still identical) formulas consume.

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
emitted -- its fact table is always empty, so its asof lookup is always NaN
and the code below always falls back to shares_outstanding, exactly as
`process_ticker` did.

TWO POINT-IN-TIME DECISIONS, BOTH LOAD-BEARING (unchanged from the original)
------------------------------------------------------------------------
1. `filed_date` is SF1's `date`, NOT `calendardate`. `calendardate` is the
   period end and precedes the filing by roughly 4-6 weeks; using it would
   put about a month of look-ahead into every fundamental feature, since the
   merge_asof join is what makes this point-in-time at all.

2. Only ARQ and ARY -- as-reported, never restated. MR* dimensions carry
   figures revised after the fact, which would leak a later correction into
   a value the model is supposed to have seen at the time.

   ARY rows are emitted as form="10-K", fiscal_period="FY"; ARQ rows as
   form="10-Q" with the quarter code. FLOW_CONCEPTS are filtered to
   annual-only (form 10-K/10-K/A + fiscal_period FY), which only ARY rows
   ever carry, avoiding the quarterly cumulative-vs-discrete ambiguity.

    python3 build_features_fundamentals_sharadar.py
    python3 build_features_fundamentals_sharadar.py --verify-against /path/to/old_panel.parquet

OUTPUT
    final/out/features_with_fundamentals_sharadar_pit.parquet
"""
import argparse
import gc
import time
from pathlib import Path

import numpy as np
import pandas as pd
import pyarrow as pa
import pyarrow.parquet as pq

from features import (FEATURE_COLS, LABEL_COL, TRADABLE_LABEL_COL,
                      OUT_DIR, PROJECT_ROOT)
from fundamentals_features_beta import FUNDAMENTAL_FEATURE_COLS

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

# Transcribed from fundamentals_features_beta.py -- not imported, so this
# file has no runtime dependency on it, but the LISTS must match exactly.
# Covered by --verify-against, which would fail loudly if they drifted.
STOCK_CONCEPTS = ["total_assets", "total_liabilities", "stockholders_equity",
                   "cash", "long_term_debt", "shares_outstanding", "shares_outstanding_dei"]
FLOW_CONCEPTS = ["revenue", "net_income", "gross_profit", "operating_income",
                  "operating_cash_flow", "capex", "rnd_expense"]


def tidy_sf1():
    """SF1 wide -> the long schema the asof joins below consume. Unchanged
    from the original -- already a handful of vectorized pandas ops, not a
    per-ticker loop, so it was never the slow part."""
    df = pd.read_parquet(SF1)
    df = df[df["dimension"].isin(["ARQ", "ARY"])].copy()
    df["filed_date"] = (pd.to_datetime(df["date"], errors="coerce")
                        .astype("datetime64[ns]"))
    df = df[df["filed_date"].notna()]

    is_ary = df["dimension"].eq("ARY")
    df["form"] = np.where(is_ary, "10-K", "10-Q")
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


def _fact_table(raw, concept, annual_only):
    """One concept's (ticker, filed_date, value) fact table, globally --
    the vectorized equivalent of fundamentals_features_beta.
    build_ticker_fact_series, minus the per-ticker slicing. Same filter,
    same dedup rule (last value wins on a same-day double-filing)."""
    sub = raw[raw["concept"] == concept]
    if annual_only:
        sub = sub[(sub["form"].isin(["10-K", "10-K/A"])) & (sub["fiscal_period"] == "FY")]
    if sub.empty:
        return None
    sub = (sub.sort_values(["ticker", "filed_date"])
              .drop_duplicates(subset=["ticker", "filed_date"], keep="last"))
    return sub[["ticker", "filed_date", "value"]].reset_index(drop=True)


def _global_asof(price, fact, want_filed_date=False):
    """price: DataFrame with ticker, date, _row (original row position).
    fact: DataFrame with ticker, filed_date, value (or None/empty).
    Returns (values, filed_dates_or_None), aligned to price's ORIGINAL row
    order -- the exact contract fundamentals_features_beta.asof_lookup had
    per-ticker, just computed for every ticker in one merge_asof(by=
    "ticker") call instead of one call per ticker.

    Round-16 discipline: merge_asof resets the index, so a plain
    .sort_index() afterward is a no-op. _row is carried explicitly and the
    result is asserted to have lost or reordered nothing."""
    n = len(price)
    if fact is None or fact.empty:
        vals = np.full(n, np.nan)
        filed = np.full(n, np.datetime64("NaT")) if want_filed_date else None
        return vals, filed

    left = price[["ticker", "date", "_row"]].sort_values(["date", "ticker"])
    fa = fact.sort_values(["filed_date", "ticker"])
    m = pd.merge_asof(left, fa, left_on="date", right_on="filed_date",
                      by="ticker", direction="backward")
    m = m.sort_values("_row").reset_index(drop=True)
    assert len(m) == n and (m["_row"].to_numpy() == np.arange(n)).all(), \
        "fundamentals asof merge lost or reordered rows"
    vals = m["value"].to_numpy()
    filed = m["filed_date"].to_numpy() if want_filed_date else None
    return vals, filed


def compute_fundamentals(price: pd.DataFrame, raw: pd.DataFrame) -> pd.DataFrame:
    """price: ticker, date, close (one row per panel row, ANY order).
    Returns a DataFrame of the 14 FUNDAMENTAL_FEATURE_COLS, one row per
    input row, in price's ORIGINAL order -- ready to attach as new columns.
    Formulas transcribed from fundamentals_features_beta.process_ticker;
    see that function for the one-ticker-at-a-time reference version."""
    price = price.reset_index(drop=True).copy()
    price["_row"] = np.arange(len(price))
    price["date"] = pd.to_datetime(price["date"]).astype("datetime64[ns]")
    price["ticker"] = price["ticker"].astype(str)
    n = len(price)

    stock_vals = {}
    for concept in STOCK_CONCEPTS:
        fact = _fact_table(raw, concept, annual_only=False)
        vals, _ = _global_asof(price, fact)
        stock_vals[concept] = vals
        print(f"    stock concept {concept}: {np.isfinite(vals).sum():,} non-null")

    flow_vals, flow_filed, flow_prior = {}, {}, {}
    for concept in FLOW_CONCEPTS:
        fact = _fact_table(raw, concept, annual_only=True)
        vals, filed = _global_asof(price, fact, want_filed_date=(concept == "revenue"))
        flow_vals[concept] = vals
        if concept == "revenue":
            flow_filed[concept] = filed

        if fact is not None and not fact.empty:
            fact_sorted = fact.sort_values(["ticker", "filed_date"]).reset_index(drop=True)
            fact_sorted["value"] = fact_sorted.groupby("ticker")["value"].shift(1)
            prior_vals, _ = _global_asof(price, fact_sorted)
        else:
            prior_vals = np.full(n, np.nan)
        flow_prior[concept] = prior_vals
        print(f"    flow concept {concept}: {np.isfinite(vals).sum():,} non-null "
              f"({np.isfinite(prior_vals).sum():,} with a prior filing)")

    shares = stock_vals["shares_outstanding_dei"]
    shares = np.where(np.isnan(shares), stock_vals["shares_outstanding"], shares)

    close = price["close"].to_numpy(np.float64)
    with np.errstate(divide="ignore", invalid="ignore"):
        market_cap = close * shares
        net_income = flow_vals["net_income"]
        equity = stock_vals["stockholders_equity"]
        assets = stock_vals["total_assets"]
        revenue = flow_vals["revenue"]

        pe = np.where(net_income > 0, market_cap / net_income, np.nan)
        pb = np.where(equity > 0, market_cap / equity, np.nan)
        ps = np.where(revenue > 0, market_cap / revenue, np.nan)
        dte = np.where(equity > 0, stock_vals["long_term_debt"] / equity, np.nan)
        roe = np.where(equity > 0, net_income / equity, np.nan)
        roa = np.where(assets > 0, net_income / assets, np.nan)
        gm = np.where(revenue > 0, flow_vals["gross_profit"] / revenue, np.nan)
        om = np.where(revenue > 0, flow_vals["operating_income"] / revenue, np.nan)
        fcf_margin = np.where(revenue > 0,
                              (flow_vals["operating_cash_flow"] - flow_vals["capex"]) / revenue, np.nan)
        rev_prior = flow_prior["revenue"]
        rev_growth = np.where(rev_prior > 0, revenue / rev_prior - 1, np.nan)
        ni_prior = flow_prior["net_income"]
        ni_growth = np.where(np.abs(ni_prior) > 0, net_income / np.abs(ni_prior) - 1, np.nan)
        rnd_intensity = np.where(revenue > 0, flow_vals["rnd_expense"] / revenue, np.nan)

        rev_filed = flow_filed["revenue"]
        age_days = (price["date"].to_numpy() - rev_filed) / np.timedelta64(1, "D")

    return pd.DataFrame({
        "market_cap": market_cap, "pe_ratio": pe, "pb_ratio": pb, "ps_ratio": ps,
        "debt_to_equity": dte, "roe": roe, "roa": roa, "gross_margin": gm,
        "operating_margin": om, "fcf_margin": fcf_margin,
        "revenue_growth_yoy": rev_growth, "earnings_growth_yoy": ni_growth,
        "rnd_intensity": rnd_intensity, "fundamentals_age_days": age_days,
    })


def build():
    t0 = time.time()
    print("SF1 -> tidy long format...")
    raw = tidy_sf1()
    print(f"  {len(raw):,} fact rows, {raw['ticker'].nunique():,} tickers, "
          f"filed {raw['filed_date'].min().date()} .. "
          f"{raw['filed_date'].max().date()} ({time.time()-t0:.0f}s)")

    print("\nloading price panel...")
    price = pd.read_parquet(PRICE_PANEL)
    price["date"] = pd.to_datetime(price["date"]).astype("datetime64[ns]")
    price["ticker"] = price["ticker"].astype(str)
    print(f"  {len(price):,} rows, {price['ticker'].nunique():,} tickers ({time.time()-t0:.0f}s)")

    print("\ncomputing fundamentals (14 global asof joins, not one per ticker)...")
    fnd = compute_fundamentals(price[["ticker", "date", "close"]], raw)
    del raw
    gc.collect()
    print(f"  done ({time.time()-t0:.0f}s)")

    keep = (["ticker", "date"] + PRICE_COLS + FEATURE_COLS
            + [LABEL_COL, TRADABLE_LABEL_COL] + FUNDAMENTAL_FEATURE_COLS)
    out = pd.concat([price.reset_index(drop=True), fnd.reset_index(drop=True)], axis=1)
    # float64, NOT float32 (integrator, 2026-09-26, at the reset landing):
    # eligibility (cap150/cap500/cap2000) thresholds read market_cap, and
    # composite ranks read the ratios. float32 rounding touched ~99% of
    # market_cap rows (WO-6) and could flip flags at the thresholds, so the
    # output dtype stays what the per-ticker builder wrote. The speedup
    # (global asof joins) is unaffected.
    for c in FUNDAMENTAL_FEATURE_COLS:
        out[c] = (pd.to_numeric(out[c], errors="coerce")
                  .replace([np.inf, -np.inf], np.nan).astype("float64"))
    out = out[keep]
    out["ticker"] = out["ticker"].astype(str)

    schema = pa.schema(
        [("ticker", pa.string()), ("date", pa.timestamp("ns"))]
        + [(c, pa.float64()) for c in keep if c not in ("ticker", "date")])
    OUT.parent.mkdir(parents=True, exist_ok=True)
    pq.write_table(pa.Table.from_pandas(out, schema=schema, preserve_index=False), OUT)
    print(f"\n{len(out):,} rows -> {OUT} ({time.time()-t0:.0f}s total)")

    print("\ncoverage of each derived ratio (non-null share of all rows):")
    for c in FUNDAMENTAL_FEATURE_COLS:
        print(f"  {c:<24} {out[c].notna().mean():.1%}")
    print("\nCompare these against models/fundamentals-beta-results.md. A large")
    print("drop would mean the SF1 translation is losing facts the old CSV")
    print("pipeline captured; a large rise is expected, since the old panel")
    print("simply had no fundamentals for half the universe.")


def verify_against(old_path):
    print(f"verifying {OUT} against {old_path} ...")
    new = pd.read_parquet(OUT)
    old = pd.read_parquet(old_path)
    new["date"] = pd.to_datetime(new["date"])
    old["date"] = pd.to_datetime(old["date"])
    m = new.merge(old, on=["ticker", "date"], suffixes=("_new", "_old"), how="inner")
    print(f"  {len(m):,} shared (ticker, date) rows "
          f"(new has {len(new):,}, old has {len(old):,})")
    all_ok = True
    for c in FUNDAMENTAL_FEATURE_COLS:
        a, b = m[f"{c}_new"].to_numpy(np.float64), m[f"{c}_old"].to_numpy(np.float64)
        both_nan = np.isnan(a) & np.isnan(b)
        close = np.isclose(a, b, rtol=1e-4, atol=1e-6, equal_nan=False)
        ok = (both_nan | close)
        n_bad = int((~ok).sum())
        status = "OK" if n_bad == 0 else f"MISMATCH ({n_bad:,} rows, "
        if n_bad:
            bad_idx = np.flatnonzero(~ok)[:5]
            examples = [(m.iloc[i]["ticker"], m.iloc[i]["date"], a[i], b[i]) for i in bad_idx]
            status += f"e.g. {examples})"
            all_ok = False
        print(f"  {c:<24} {status}")
    print("\nVERIFY PASS" if all_ok else "\nVERIFY FAIL")
    return all_ok


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--verify-against", type=str, default=None,
                    help="Path to an OLD (process_ticker-based) panel to numerically "
                        "compare the freshly-built OUT against, column by column.")
    args = ap.parse_args()
    if args.verify_against:
        ok = verify_against(Path(args.verify_against))
        raise SystemExit(0 if ok else 1)
    build()
