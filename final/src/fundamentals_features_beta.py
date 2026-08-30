"""
BETA -- point-in-time fundamentals features, built on top of the SEC EDGAR
pull in scripts/fundamentals_raw/ (see scripts/local_fundamentals_pull.py).
Does NOT touch features.py, backtest.py, or any production file -- this is
a standalone experiment to test whether fundamentals improve the buy/no-buy
models before anything gets promoted out of beta, per Gabe's instruction.

Point-in-time discipline: every fundamentals value used for a given price
date is joined via merge_asof on the fact's actual SEC FILING date (not the
fiscal period it covers), requiring filed_date <= price date. This is
stricter and more honest than the FORWARD_WINDOW-based embargo the price
features use, because it's not an assumption about reporting lag -- it's
the literal date the 10-K/10-Q became public. A quarter's numbers simply
don't exist in this feature set until the filing that reported them did.

Two families of concepts, joined differently:
  - "Stock" (balance-sheet) concepts -- total_assets, total_liabilities,
    stockholders_equity, cash, long_term_debt, shares_outstanding: these are
    point-in-time snapshots, so the most recently FILED value (10-K or
    10-Q, whichever is newer) is used as-of each price date.
  - "Flow" (income-statement/cash-flow) concepts -- revenue, net_income,
    gross_profit, operating_income, operating_cash_flow, capex,
    rnd_expense: only ANNUAL (10-K, fiscal_period=FY) values are used, to
    sidestep a real XBRL ambiguity -- some filers report quarterly figures
    as discrete-quarter amounts, others as cumulative year-to-date amounts,
    inconsistently enough across companies that building a reliable
    rolling-TTM from quarterly data isn't safe for a first pass. This means
    these features update once a year (at the 10-K filing), not quarterly,
    and lag a full fiscal year behind -- a known simplification, not a
    bug, worth revisiting if fundamentals prove useful enough to invest
    more in.

Derived ratios: market_cap, pe_ratio, pb_ratio, ps_ratio, debt_to_equity,
roe, roa, gross_margin, operating_margin, fcf_margin, revenue_growth_yoy,
earnings_growth_yoy, rnd_intensity, fundamentals_age_days.

Implementation note (rewritten after the first version OOM-killed at ~6GB):
does ONE pass per ticker (not one pass per concept), building only the
lean [ticker, date] + fundamentals-derived columns per ticker, and only
merges that lean panel onto the full price features.parquet once at the
end -- avoids repeatedly reconstructing the whole ~6.3M-row panel 21 times.

Usage:
    python3 fundamentals_features_beta.py

Output: out/features_with_fundamentals_beta.parquet -- features.parquet
with these new columns merged in (left join on ticker+date; rows for
tickers/dates before any filing, or for the 14 tickers the SEC pull
couldn't match, are NaN in the new columns).
"""
import glob
import gc
import os

import numpy as np
import pandas as pd

from features import OUT_DIR, PROJECT_ROOT, atomic_to_parquet

FUNDAMENTALS_RAW_DIR = PROJECT_ROOT / "scripts" / "fundamentals_raw"

STOCK_CONCEPTS = ["total_assets", "total_liabilities", "stockholders_equity",
                   "cash", "long_term_debt", "shares_outstanding", "shares_outstanding_dei"]
FLOW_CONCEPTS = ["revenue", "net_income", "gross_profit", "operating_income",
                  "operating_cash_flow", "capex", "rnd_expense"]

FUNDAMENTAL_FEATURE_COLS = [
    "market_cap", "pe_ratio", "pb_ratio", "ps_ratio", "debt_to_equity",
    "roe", "roa", "gross_margin", "operating_margin", "fcf_margin",
    "revenue_growth_yoy", "earnings_growth_yoy", "rnd_intensity",
    "fundamentals_age_days",
]


def load_fundamentals_raw():
    files = [f for f in glob.glob(str(FUNDAMENTALS_RAW_DIR / "*.csv"))
             if not os.path.basename(f).startswith("_")]
    frames = []
    for f in files:
        df = pd.read_csv(f, parse_dates=["filed_date"],
                          usecols=["ticker", "concept", "form", "fiscal_period", "filed_date", "value"])
        frames.append(df)
    combined = pd.concat(frames, ignore_index=True)
    return combined


def asof_lookup(price_dates, fact_df, value_col):
    """fact_df: sorted [filed_date, value_col] for ONE ticker. Returns an
    array aligned to price_dates: most recent value_col with filed_date <=
    date, plus the filed_date used (for staleness)."""
    if fact_df is None or fact_df.empty:
        nan_arr = np.full(len(price_dates), np.nan)
        return nan_arr, np.full(len(price_dates), np.datetime64("NaT"))
    tmp = pd.DataFrame({"date": price_dates})
    merged = pd.merge_asof(tmp, fact_df, left_on="date", right_on="filed_date", direction="backward")
    return merged[value_col].values, merged["filed_date"].values


def build_ticker_fact_series(raw_ticker, concept, annual_only):
    if raw_ticker is None:
        return None
    sub = raw_ticker[raw_ticker["concept"] == concept]
    if annual_only:
        sub = sub[(sub["form"].isin(["10-K", "10-K/A"])) & (sub["fiscal_period"] == "FY")]
    if sub.empty:
        return None
    sub = sub.sort_values("filed_date").drop_duplicates(subset="filed_date", keep="last")
    return sub[["filed_date", "value"]].rename(columns={"value": concept}).reset_index(drop=True)


def process_ticker(ticker, price_g, raw_g):
    dates = price_g["date"].values
    close = price_g["close"].values
    n = len(dates)
    result = {"ticker": ticker, "date": dates}

    stock_vals = {}
    for concept in STOCK_CONCEPTS:
        series = build_ticker_fact_series(raw_g, concept, annual_only=False)
        vals, _ = asof_lookup(dates, series, concept)
        stock_vals[concept] = vals

    flow_vals = {}
    flow_filed = {}
    flow_prior = {}
    for concept in FLOW_CONCEPTS:
        series = build_ticker_fact_series(raw_g, concept, annual_only=True)
        vals, filed = asof_lookup(dates, series, concept)
        flow_vals[concept] = vals
        flow_filed[concept] = filed
        if series is not None and len(series) > 1:
            series_prior = series.copy()
            series_prior[f"{concept}_prior"] = series_prior[concept].shift(1)
            prior_vals, _ = asof_lookup(dates, series_prior[["filed_date", f"{concept}_prior"]], f"{concept}_prior")
        else:
            prior_vals = np.full(n, np.nan)
        flow_prior[concept] = prior_vals

    shares = stock_vals["shares_outstanding_dei"]
    shares = np.where(np.isnan(shares), stock_vals["shares_outstanding"], shares)

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
        fcf_margin = np.where(revenue > 0, (flow_vals["operating_cash_flow"] - flow_vals["capex"]) / revenue, np.nan)
        rev_prior = flow_prior["revenue"]
        rev_growth = np.where(rev_prior > 0, revenue / rev_prior - 1, np.nan)
        ni_prior = flow_prior["net_income"]
        ni_growth = np.where(np.abs(ni_prior) > 0, net_income / np.abs(ni_prior) - 1, np.nan)
        rnd_intensity = np.where(revenue > 0, flow_vals["rnd_expense"] / revenue, np.nan)

        rev_filed = flow_filed["revenue"]
        age_days = (dates - rev_filed) / np.timedelta64(1, "D")

    result["market_cap"] = market_cap
    result["pe_ratio"] = pe
    result["pb_ratio"] = pb
    result["ps_ratio"] = ps
    result["debt_to_equity"] = dte
    result["roe"] = roe
    result["roa"] = roa
    result["gross_margin"] = gm
    result["operating_margin"] = om
    result["fcf_margin"] = fcf_margin
    result["revenue_growth_yoy"] = rev_growth
    result["earnings_growth_yoy"] = ni_growth
    result["rnd_intensity"] = rnd_intensity
    result["fundamentals_age_days"] = age_days

    return pd.DataFrame(result)


def main():
    print("Loading price feature panel (ticker/date/close only for the merge build)...")
    price_full = pd.read_parquet(OUT_DIR / "features.parquet")
    price_lean = price_full[["ticker", "date", "close"]].sort_values(["ticker", "date"]).reset_index(drop=True)

    print("Loading raw fundamentals pull...")
    raw = load_fundamentals_raw()
    print(f"  {raw['ticker'].nunique()} tickers, {len(raw)} raw fact rows, "
          f"filed {raw['filed_date'].min().date()} to {raw['filed_date'].max().date()}")
    raw_by_ticker = {t: g for t, g in raw.groupby("ticker", sort=False)}
    del raw
    gc.collect()

    print("Grouping price panel by ticker...")
    price_by_ticker = {t: g for t, g in price_lean.groupby("ticker", sort=False)}
    del price_lean
    gc.collect()

    tickers = list(price_by_ticker.keys())
    print(f"Processing {len(tickers)} tickers, one pass each...")

    pieces = []
    for i, ticker in enumerate(tickers, 1):
        price_g = price_by_ticker[ticker]
        raw_g = raw_by_ticker.get(ticker)
        pieces.append(process_ticker(ticker, price_g, raw_g))
        if i % 200 == 0:
            print(f"  {i}/{len(tickers)} tickers done")

    fundamentals_panel = pd.concat(pieces, ignore_index=True)
    del pieces, price_by_ticker, raw_by_ticker
    gc.collect()

    for col in FUNDAMENTAL_FEATURE_COLS:
        fundamentals_panel[col] = fundamentals_panel[col].replace([np.inf, -np.inf], np.nan).astype("float32")

    print("\nCoverage of derived ratios (non-null share of ALL price rows):")
    for col in FUNDAMENTAL_FEATURE_COLS:
        print(f"  {col:<22} {fundamentals_panel[col].notna().mean():.1%}")

    merged = price_full.merge(fundamentals_panel, on=["ticker", "date"], how="left")
    del price_full, fundamentals_panel
    gc.collect()

    out_path = OUT_DIR / "features_with_fundamentals_beta.parquet"
    atomic_to_parquet(merged, out_path)
    print(f"\nSaved -> {out_path}  shape={merged.shape}")


if __name__ == "__main__":
    main()
