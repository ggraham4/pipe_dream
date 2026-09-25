"""
WO-13 independent hand-check of SUE for three named filings. Does NOT import
build_sue; recomputes from raw SF1 ARQ rows with plain loops and compares to
final/out/sue/sue_filings.parquet.
  AAPL  reportperiod 2015-12-26 (large cap)
  AAME  reportperiod 2013-06-30 (Atlantic American, micro cap, v2-added ticker)
  RSHCQ reportperiod 2013-09-30 (RadioShack, delisted 2015)
"""
import json
import statistics
from datetime import timedelta
from pathlib import Path

import pandas as pd

SF1 = "/Users/ggraham/pipe_dream/final/data/sharadar/sf1_fundamentals.parquet"
OUT = Path(__file__).resolve().parents[2] / "out" / "sue"
CASES = [("AAPL", "2015-12-26"), ("AAME", "2013-06-30"), ("RSHCQ", "2013-09-30")]


def rows_for(t):
    d = pd.read_parquet(SF1, columns=["ticker", "dimension", "date", "reportperiod", "eps"],
                        filters=[("ticker", "==", t)])
    d = d[d["dimension"] == "ARQ"]
    first = {}
    for _, r in d.sort_values("date").iterrows():          # first-reported row per reportperiod
        first.setdefault(r["reportperiod"], (pd.Timestamp(r["date"]), r["eps"]))
    return {pd.Timestamp(k): v for k, v in first.items()}


def find(q, target):
    best = None
    for rp in q:
        gap = abs((rp - target).days)
        if gap <= 15 and (best is None or gap < abs((best - target).days)):
            best = rp
    return best


def one(t, rp_s):
    q = rows_for(t)
    rp = pd.Timestamp(rp_s)
    fdate, eps = q[rp]
    lines = [f"{t} q={rp.date()} filed {fdate.date()} eps={eps}"]
    r4 = find(q, rp - pd.DateOffset(months=12))
    num = eps - q[r4][1]
    lines.append(f"  q-4={r4.date()} eps={q[r4][1]}  numerator={num:+.4f}")
    diffs = []
    for k in range(1, 9):
        rj = find(q, rp - pd.DateOffset(months=3 * k))
        if rj is None:
            lines.append(f"  j=q-{k}: missing"); continue
        rj4 = find(q, rj - pd.DateOffset(months=12))
        if rj4 is None or pd.isna(q[rj][1]) or pd.isna(q[rj4][1]):
            lines.append(f"  j=q-{k} {rj.date()}: no q-4 leg"); continue
        if max(q[rj][0], q[rj4][0]) > fdate:
            lines.append(f"  j=q-{k} {rj.date()}: filed after q"); continue
        dj = q[rj][1] - q[rj4][1]
        diffs.append(dj)
        lines.append(f"  j=q-{k} {rj.date()} eps={q[rj][1]} minus {rj4.date()} eps={q[rj4][1]} -> D={dj:+.4f}")
    sd = statistics.stdev(diffs) if len(diffs) >= 2 else float("nan")
    sue = num / sd if len(diffs) >= 6 and sd > 0 else float("nan")
    sue_w = max(-10.0, min(10.0, sue))
    lines.append(f"  n={len(diffs)} sd={sd:.5f} SUE_raw={sue:+.5f} SUE={sue_w:+.5f}")
    return {"ticker": t, "reportperiod": rp_s, "filed": str(fdate.date()), "sue_hand": sue_w, "lines": lines}


def main():
    fil = pd.read_parquet(OUT / "sue_filings.parquet", columns=["ticker", "rp", "sue"])
    res = []
    for t, rp in CASES:
        r = one(t, rp)
        got = fil.loc[(fil["ticker"] == t) & (fil["rp"] == rp), "sue"].iloc[0]
        r["sue_pipeline"] = float(got)
        r["match"] = bool(abs(got - r["sue_hand"]) < 1e-9)
        print("\n".join(r["lines"]), f"\n  pipeline {got:+.5f}  match={r['match']}\n")
        res.append(r)
    (OUT / "hand_check_sue.json").write_text(json.dumps(res, indent=2))
    assert all(r["match"] for r in res)


if __name__ == "__main__":
    main()
