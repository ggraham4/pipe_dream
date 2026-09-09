"""
Pull Put rows (instead of Calls) for the same 91 30-day (entry_date,
expiration) pairs -- for the selling-premium strategy (2026-09-04, round
6): sell a cash-secured put on names the model likes, collecting premium,
instead of buying a call. Same pairs table, same DoltHub source.
"""
import time
from pathlib import Path
import pandas as pd
import duckdb

REPO_FINAL = Path(__file__).resolve().parents[2]
OPT_PARQUET = REPO_FINAL / "data" / "options_raw" / "expanded" / "option_chain_expanded_merged.parquet"
OUT_DIR = Path(__file__).resolve().parent

pairs = pd.read_parquet(OUT_DIR / "entry_expiration_pairs.parquet")
con = duckdb.connect()
con.register("pairs", pairs[["entry_date", "expiration"]])
t0 = time.time()
q = f"""
SELECT o.date AS entry_date, o.act_symbol, o.expiration AS expiration_date,
       o.strike, o.bid, o.ask, o.vol AS entry_iv, o.delta AS entry_delta,
       o.gamma AS entry_gamma, o.theta AS entry_theta, o.vega AS entry_vega,
       o.rho AS entry_rho
FROM '{OPT_PARQUET}' o
JOIN pairs p ON o.date = p.entry_date AND o.expiration = p.expiration
WHERE o.call_put = 'Put'
"""
puts = con.execute(q).fetchdf()
print(f"Pulled {len(puts)} put rows in {time.time()-t0:.1f}s, {puts['act_symbol'].nunique()} tickers", flush=True)
puts.to_parquet(OUT_DIR / "raw_puts_at_entry.parquet")
print("wrote raw_puts_at_entry.parquet", flush=True)
