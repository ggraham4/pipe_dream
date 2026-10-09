"""WO-52: three named link checks + link rate by slice (presence only). Writes final/out/thinliq_om/link_report.json."""
import json
import sys
from pathlib import Path

import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parent))
import om_paths as P  # noqa: E402

L = pd.read_parquet(P.CALLS)
sec = pd.read_parquet(P.ROOT / "securd.parquet").set_index("secid")
CASES = [("ATPAQ", "2012-06-20", "dead name: ATP Oil & Gas, bankrupt 2012"),
         ("CB1", "2008-01-02", "reused ticker: Chubb Corp (Sharadar CB1) vs today's CB"),
         ("CB", "2008-01-02", "reused ticker: Sharadar CB traded as ACE in 2008"),
         ("AAPL", "2015-06-17", "large cap")]
out = {}
for tk, d, note in CASES:
    r = L[(L.ticker == tk) & (L.date == d)]
    if r.empty:
        out[f"{tk}@{d}"] = {"note": note, "status": "not in thin/cap2000 slice on date"}
        continue
    r = r.iloc[0]
    s = sec.loc[r.secid] if pd.notna(r.secid) and r.secid in sec.index else None
    out[f"{tk}@{d}"] = {"note": note, "status": r.status, "permno": None if pd.isna(r.permno) else int(r.permno),
                        "secid": None if pd.isna(r.secid) else int(r.secid),
                        "om_ticker_today": None if s is None else s.ticker, "om_cusip": None if s is None else s.cusip,
                        "om_close": r.spot_parity, "sharadar_closeunadj": r.closeunadj}
u = pd.read_parquet(P.UNIVERSE, columns=["date", "ticker", "eligible_cap2000", "eligible_cap150"])
u = u[u.date.astype(str).isin(set(L.date))]
u["thin"] = u.eligible_cap150 & ~u.eligible_cap2000
u["date"] = u.date.astype(str); u["ticker"] = u.ticker.astype(str)
m = L.merge(u[["date", "ticker", "thin"]], on=["date", "ticker"], how="left")
rate = {("thin" if k else "cap2000"): {"name_dates": int(len(g)), "linked_to_permno": float((g.status != "unlinked").mean()),
                                       "ok": float((g.status == "ok").mean()), "no_data": float((g.status == "no_data").mean())}
        for k, g in m.groupby("thin")}
rep = {"crosswalk": str(P.XWALK), "link_rate": rate, "named": out}
(P.OUT / "link_report.json").write_text(json.dumps(rep, indent=1, default=str))
print(json.dumps(rep, indent=1, default=str))
