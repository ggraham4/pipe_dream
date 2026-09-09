"""
Rebuild options_calls_expanded_with_pit_capcheck.parquet using the WIDER
point-in-time fundamentals panel (options_pit_fundamentals_expanded.parquet,
1,266 tickers -- built from features_with_fundamentals_pit.parquet, which
already covers the full expanded options universe via the existing SEC
EDGAR pull, no new Sharadar API call needed) instead of the old 495-ticker
options_pit_fundamentals_slim.parquet.
"""
from pathlib import Path
import pandas as pd

OUT_DIR = Path(__file__).resolve().parent

calls = pd.read_parquet(OUT_DIR / "options_calls_training_expanded_v2_with_bnb.parquet")
calls["entry_date"] = calls["entry_date"].astype("datetime64[ns]")
calls["expiration_date"] = calls["expiration_date"].astype("datetime64[ns]")
calls = calls.sort_values("entry_date").reset_index(drop=True)

fund = pd.read_parquet(OUT_DIR / "options_pit_fundamentals_expanded.parquet",
                        columns=["date", "ticker", "market_cap"])
fund["date"] = fund["date"].astype("datetime64[ns]")
fund = fund.dropna(subset=["market_cap"]).sort_values("date").reset_index(drop=True)
fund = fund.rename(columns={"ticker": "act_symbol"})

merged = pd.merge_asof(
    calls, fund[["date", "act_symbol", "market_cap"]],
    left_on="entry_date", right_on="date", by="act_symbol",
    direction="nearest", tolerance=pd.Timedelta(days=120),
)
merged = merged.drop(columns=["date"])
n_matched = merged["market_cap"].notna().sum()
print(f"{n_matched}/{len(merged)} rows matched a PIT market_cap ({n_matched/len(merged)*100:.1f}%)")
print(f"{merged.loc[merged['market_cap'].notna(),'act_symbol'].nunique()} tickers with at least one match")

merged.to_parquet(OUT_DIR / "options_calls_expanded_with_pit_capcheck_v3.parquet", index=False)
print("saved options_calls_expanded_with_pit_capcheck_v3.parquet")
