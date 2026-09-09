"""
Step 2: pull all Call rows from the expanded option chain matching the
(entry_date, expiration) pairs computed in step 1 -- one duckdb join
against the 91M-row merged parquet (single scan via a registered small
table, not 91 separate filtered scans).
"""
import time
from pathlib import Path
import pandas as pd
import duckdb

REPO_FINAL = Path(__file__).resolve().parents[2]
OPT_PARQUET = REPO_FINAL / "data" / "options_raw" / "expanded" / "option_chain_expanded_merged.parquet"
OUT_DIR = Path(__file__).resolve().parent

pairs = pd.read_parquet(OUT_DIR / "entry_expiration_pairs_2d.parquet")

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
WHERE o.call_put = 'Call'
"""
calls = con.execute(q).fetchdf()
print(f"Pulled {len(calls)} call rows in {time.time()-t0:.1f}s, "
      f"{calls['act_symbol'].nunique()} tickers", flush=True)
calls.to_parquet(OUT_DIR / "raw_calls_at_entry_2d.parquet")
print("wrote raw_calls_at_entry_2d.parquet", flush=True)
