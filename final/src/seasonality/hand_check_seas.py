"""
WO-18 name check: hand-compute `seas` for AAPL and a dead name on one date
each, independently of build_seas.py (no import of it), straight from the raw
SEP month files, and compare with out/seasonality/seas_factor_v2.parquet to 1e-9.

  AAPL   2008-03-14  target 2008-04-11 -> April, years 1998..2007 (spans the 2005 splice)
  RSHCQ  2012-06-15  target 2012-07-13 -> July,  years 2002..2011 (RadioShack, delisted 2015)

Output: out/seasonality/hand_check_seas.json
"""
import datetime as dt
import json
from pathlib import Path

import pandas as pd

MAIN = Path("/Users/ggraham/pipe_dream/final")
PRE = MAIN / "data" / "sharadar" / "sep_pre2005" / "stocks"
NEW = MAIN / "data" / "sharadar" / "panel" / "stocks"
OUT = Path(__file__).resolve().parents[2] / "out" / "seasonality"
CASES = [("AAPL", "2008-03-14"), ("RSHCQ", "2012-06-15")]


def month_file(y, m, overlap=False):
    ym = f"{y:04d}-{m:02d}"
    if overlap:
        return PRE / f"{ym}.parquet"
    return (PRE if ym < "2005-01" else NEW) / f"{ym}.parquet"


def last_close(ticker, y, m, overlap=False):
    f = month_file(y, m, overlap)
    d = pd.read_parquet(f, columns=["ticker", "date", "closeadj"])
    d = d[(d["ticker"] == ticker) & (d["closeadj"] > 0)].sort_values("date")
    if d.empty:
        return None, None
    return d["date"].iloc[-1], float(d["closeadj"].iloc[-1])


def main():
    fac = pd.read_parquet(OUT / "seas_factor_v2.parquet")
    out = []
    for tk, day in CASES:
        t = dt.date.fromisoformat(day)
        T = t + dt.timedelta(days=28)
        m = T.month
        # splice factor for this ticker (2005-01 overlap)
        dn, cn = last_close(tk, 2005, 1, overlap=True)
        do, co = last_close(tk, 2005, 1)
        g = cn / co if (cn is not None and co is not None and dn == do) else 1.0
        rets = []
        for y in range(T.year - 10, T.year):
            py, pm = (y, m - 1) if m > 1 else (y - 1, 12)
            d1, c1 = last_close(tk, y, m)
            d0, c0 = last_close(tk, py, pm)
            if c1 is None or c0 is None:
                rets.append({"year": y, "ret": None}); continue
            if f"{y:04d}-{m:02d}" < "2005-01":
                c1 /= g
            if f"{py:04d}-{pm:02d}" < "2005-01":
                c0 /= g
            assert d1 < str(t)
            rets.append({"year": y, "prev_close_date": d0, "close_date": d1, "ret": c1 / c0 - 1.0})
        fin = [r["ret"] for r in rets if r["ret"] is not None]
        hand = sum(fin) / len(fin) if len(fin) >= 5 else float("nan")
        row = fac[(fac["ticker"] == tk) & (fac["date"] == pd.Timestamp(day))]
        built = float(row["seas"].iloc[0]) if len(row) else float("nan")
        out.append({"ticker": tk, "date": day, "target_month": m, "g_splice": g, "years": rets,
                     "n_years": len(fin), "seas_hand": hand, "seas_built": built,
                     "abs_diff": abs(hand - built), "match_1e-9": bool(abs(hand - built) < 1e-9)})
        print(f"{tk} {day}: hand {hand:+.10f} built {built:+.10f} n={len(fin)} g={g:.6f}")
    (OUT / "hand_check_seas.json").write_text(json.dumps(out, indent=2, default=str))
    assert all(o["match_1e-9"] for o in out), "HAND CHECK FAILED"


if __name__ == "__main__":
    main()
