"""
Independent recompute of io_gap for two names, straight from the raw SEP month
files (does not import build_io_gap). Must match io_gap_factor_v2.parquet to 1e-9.
  MU    t = 2015-06-15  (live name, the motivating example)
  RSHCQ t = 2012-06-15  (RadioShack, delisted 2015)
-> out/overnight/hand_check_io_gap.json
"""
import json
from pathlib import Path

import numpy as np
import pandas as pd

MAIN = Path("/Users/ggraham/pipe_dream/final")
SEP = MAIN / "data" / "sharadar" / "panel" / "stocks"
OUT = Path(__file__).resolve().parents[2] / "out" / "overnight"
CASES = [("MU", "2015-06-15"), ("RSHCQ", "2012-06-15")]


def months_before(t, n):
    return [str(p) for p in pd.period_range(pd.Period(t, "M") - n, pd.Period(t, "M"), freq="M")]


def one(ticker, t):
    t = pd.Timestamp(t)
    ms = months_before(t, 14)
    raw = [pd.read_parquet(SEP / f"{m}.parquet") for m in ms]
    cal_counts = pd.concat([r[["date"]] for r in raw])["date"].value_counts()
    cal = sorted(pd.to_datetime(cal_counts.index[cal_counts.values >= 1000]))
    cal = [d for d in cal if d <= t]
    window = set(cal[-252:])
    d = pd.concat([r[r["ticker"] == ticker] for r in raw])
    d["date"] = pd.to_datetime(d["date"])
    d = d.sort_values("date").reset_index(drop=True)
    tot, n = 0.0, 0
    for k in range(1, len(d)):
        row, prev = d.iloc[k], d.iloc[k - 1]
        if row["date"] not in window:
            continue
        o, c, a, pa = row["open"], row["close"], row["closeadj"], prev["closeadj"]
        if not all(np.isfinite(x) and x > 0 for x in (o, c, a, pa)):
            continue
        if not row["volume"] > 0 or (row["date"] - prev["date"]).days > 7:
            continue
        if o < row["low"] * (1 - 1e-6) or o > row["high"] * (1 + 1e-6):
            continue
        rid = np.log(c / o)
        ron = np.log(a / pa) - rid
        if abs(rid) > 0.7 or abs(ron) > 0.7:
            continue
        tot += rid - ron
        n += 1
    return (252 * tot / n if n >= 200 else np.nan), n


def main():
    f = pd.read_parquet(OUT / "io_gap_factor_v2.parquet")
    res = {}
    for tk, t in CASES:
        v, n = one(tk, t)
        got = f[(f["ticker"] == tk) & (f["date"] == pd.Timestamp(t))]
        assert len(got) == 1, (tk, t, len(got))
        g, gn = float(got["io_gap"].iloc[0]), int(got["io_nvalid"].iloc[0])
        res[tk] = {"t": t, "hand": v, "build": g, "n_hand": n, "n_build": gn, "match": bool(abs(v - g) < 1e-9 and n == gn)}
        print(tk, res[tk])
        assert res[tk]["match"], f"HAND CHECK FAIL {tk}"
    (OUT / "hand_check_io_gap.json").write_text(json.dumps(res, indent=2))


if __name__ == "__main__":
    main()
