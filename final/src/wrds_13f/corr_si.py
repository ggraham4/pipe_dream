"""WO-59 descriptive (not gated, no outcome): median per-date Spearman of dbreadth with
short_interest_days_to_cover on cap150 2007-2019 (the harness frame does not carry the SI column).
Writes final/out/wrds_13f/corr_si.json."""
import json
from pathlib import Path

import numpy as np
import pandas as pd

OUT = Path(__file__).resolve().parents[2] / "out" / "wrds_13f"
P = pd.read_parquet("/Users/ggraham/pipe_dream/final/out/reset2026/composite_panel_v2.parquet",
                    columns=["ticker", "date", "short_interest_days_to_cover", "eligible_cap150"],
                    filters=[("date", ">=", "2007-01-02"), ("date", "<=", "2019-12-31")])
P = P[P.eligible_cap150.astype(bool)]
P["date"] = pd.to_datetime(P.date); P["ticker"] = P.ticker.astype(str)
F = pd.read_parquet(OUT / "cache" / "dbreadth_factor.parquet"); F["date"] = pd.to_datetime(F.date)
M = P.merge(F, on=["ticker", "date"], how="inner").dropna(subset=["dbreadth", "short_interest_days_to_cover"])
sp = [d.dbreadth.rank().corr(d.short_interest_days_to_cover.rank()) for _, d in M.groupby("date") if len(d) >= 20]
r = {"median_spearman_dbreadth_si_dtc": float(np.median(sp)) if sp else None, "n_dates": len(sp),
     "si_finite_share_cap150_2007_2019": float(P.short_interest_days_to_cover.notna().mean())}
(OUT / "corr_si.json").write_text(json.dumps(r))
print(r)
