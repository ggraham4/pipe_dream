"""
PIT market-cap join for the puts (selling-premium) training table, mirroring
build_pit_capcheck_v3.py's exact pattern for calls.
"""
from pathlib import Path
import pandas as pd

OUT_DIR = Path(__file__).resolve().parent

puts = pd.read_parquet(OUT_DIR / "options_puts_training_expanded_properrescale.parquet")
puts["entry_date"] = puts["entry_date"].astype("datetime64[ns]")
puts["expiration_date"] = puts["expiration_date"].astype("datetime64[ns]")
puts = puts.sort_values("entry_date").reset_index(drop=True)

fund = pd.read_parquet(OUT_DIR / "options_pit_fundamentals_expanded.parquet",
                        columns=["date", "ticker", "market_cap"])
fund["date"] = fund["date"].astype("datetime64[ns]")
fund = fund.dropna(subset=["market_cap"]).sort_values("date").reset_index(drop=True)
fund = fund.rename(columns={"ticker": "act_symbol"})

merged = pd.merge_asof(
    puts, fund[["date", "act_symbol", "market_cap"]],
    left_on="entry_date", right_on="date", by="act_symbol",
    direction="nearest", tolerance=pd.Timedelta(days=120),
)
merged = merged.drop(columns=["date"])
n_matched = merged["market_cap"].notna().sum()
print(f"{n_matched}/{len(merged)} rows matched a PIT market_cap ({n_matched/len(merged)*100:.1f}%)")
print(f"{merged.loc[merged['market_cap'].notna(),'act_symbol'].nunique()} tickers with at least one match")

merged.to_parquet(OUT_DIR / "options_puts_expanded_pit_properrescale.parquet", index=False)
print("saved options_puts_expanded_pit_properrescale.parquet")
