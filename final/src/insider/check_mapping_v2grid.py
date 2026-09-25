"""
WO-4 integrity follow-up: is the lower within-cap-band fire rate on the
added (never-cap2000) tickers a CIK-mapping bug?

Two checks, column c cap150 rows, 2007-2019:
  1 any Form 3/4/5 filed under the mapped CIK inside the ticker's cap150
    date range (the CIK is live), old vs added;
  2 the most common ISSUERTRADINGSYMBOL filed under the mapped CIK in that
    range equals the ticker (trailing digits/Q stripped; "loose" also accepts
    a prefix match), old vs added. Mismatches are mostly renames, where
    Sharadar keys on the latest ticker and the filing carries the old one.
Then the matched-market-cap fire rate, restricted to symbol-matched tickers.

Output: out/insider/insider_v2grid_mapping_check.json
Usage: python3 check_mapping_v2grid.py
"""
import glob
import json
import re
import zipfile
from pathlib import Path

import numpy as np
import pandas as pd

MAIN = Path("/Users/ggraham/pipe_dream/final")
RAW = MAIN / "data" / "edgar" / "form345"
R26 = MAIN / "out" / "reset2026"
OUT = MAIN / "out" / "insider" / "insider_v2grid_mapping_check.json"
CACHE = Path("/tmp/wo4_submissions_2006_2020.parquet")


def submissions():
    if CACHE.exists():
        return pd.read_parquet(CACHE)
    rows = []
    for p in sorted(glob.glob(str(RAW / "*_form345.zip"))):
        if Path(p).name[:4] > "2020":
            continue
        with zipfile.ZipFile(p) as zf, zf.open("SUBMISSION.tsv") as fh:
            rows.append(pd.read_csv(fh, sep="\t", dtype=str, quoting=3, on_bad_lines="skip",
                                    usecols=["ACCESSION_NUMBER", "FILING_DATE", "DOCUMENT_TYPE",
                                             "ISSUERCIK", "ISSUERTRADINGSYMBOL"]))
    s = pd.concat(rows)
    s["cik"] = pd.to_numeric(s["ISSUERCIK"], errors="coerce")
    s["fd"] = pd.to_datetime(s["FILING_DATE"], format="%d-%b-%Y", errors="coerce")
    s["sym"] = s["ISSUERTRADINGSYMBOL"].fillna("").str.upper().str.strip()
    s = s[["cik", "sym", "fd", "DOCUMENT_TYPE", "ACCESSION_NUMBER"]]
    s.to_parquet(CACHE)
    return s


def norm(t):
    return re.sub(r"[^A-Z]", "", re.sub(r"(\d+|Q)$", "", str(t).upper()))


def main():
    s = submissions()
    p = pd.read_parquet(R26 / "composite_panel_v2.parquet",
                        columns=["ticker", "date", "eligible_cap150", "market_cap"],
                        filters=[("date", ">=", "2007-01-02"), ("date", "<=", "2019-12-31")])
    p["date"] = pd.to_datetime(p["date"])
    assert p["date"].max() < pd.Timestamp("2020-01-01")
    p = p[p["eligible_cap150"]]
    old = set(pd.read_parquet(R26 / "composite_panel.parquet", columns=["ticker"])["ticker"].astype(str))
    tm = pd.read_csv(MAIN / "data" / "sharadar" / "tickers_master.csv", dtype=str,
                     usecols=["ticker", "secfilings", "sicindustry"]).drop_duplicates("ticker")
    tm["cik"] = pd.to_numeric(tm["secfilings"].str.extract(r"CIK=0*(\d+)")[0])
    spac = set(tm.loc[tm["sicindustry"].fillna("").str.contains("Blank Check"), "ticker"])
    p = p[p["ticker"].isin(old) | ~p["ticker"].isin(spac)]
    rng = p.groupby("ticker")["date"].agg(["min", "max"]).reset_index().merge(tm[["ticker", "cik"]], on="ticker")
    rng["g"] = np.where(rng["ticker"].isin(old), "old", "added")

    anyf = s.groupby("cik")["fd"].agg(["min", "max"]).rename(columns=lambda c: "f_" + c)
    r = rng.merge(anyf, left_on="cik", right_index=True, how="left")
    rng["any_form345"] = r["f_min"].notna().to_numpy() & (r["f_max"] >= r["min"]).to_numpy() & (r["f_min"] <= r["max"]).to_numpy()

    ss = s[["cik", "sym", "fd"]].merge(rng[["ticker", "cik", "min", "max"]], on="cik")
    ss = ss[(ss["fd"] >= ss["min"]) & (ss["fd"] <= ss["max"] + pd.Timedelta(days=5)) & (ss["sym"] != "")]
    top = ss.groupby("ticker")["sym"].agg(lambda x: x.value_counts().index[0])
    rng["sym"] = rng["ticker"].map(top)
    has = rng["sym"].notna()
    nt, ns = rng["ticker"].map(norm), rng["sym"].fillna("").map(norm)
    rng["match"] = has & (nt == ns)
    rng["match_loose"] = rng["match"] | (has & (ns != "") & np.array([a.startswith(b) or b.startswith(a) for a, b in zip(ns, nt)]))

    f = pd.read_parquet(MAIN / "out" / "insider" / "insider_features_v2grid.parquet")
    f["date"] = pd.to_datetime(f["date"])
    c = p.merge(f, on=["ticker", "date"]).merge(rng[["ticker", "g", "match_loose"]], on="ticker")
    bins = [0, 3e8, 5e8, 1e9, 2e9, 1e13]
    out = {"tickers": rng.groupby("g").size().to_dict(),
           "any_form345_in_range": rng.groupby("g")["any_form345"].mean().to_dict(),
           "has_symbol": has.groupby(rng["g"]).mean().to_dict(),
           "symbol_match_strict": rng[has].groupby("g")["match"].mean().to_dict(),
           "symbol_match_loose": rng[has].groupby("g")["match_loose"].mean().to_dict(),
           "ciks_shared_by_gt1_ticker": int((rng.groupby("cik")["ticker"].nunique() > 1).sum()),
           "added_mismatch_examples": rng[has & ~rng["match_loose"] & (rng["g"] == "added")]
               .head(15)[["ticker", "sym"]].values.tolist()}
    for name, sub in (("all_tickers", c), ("symbol_matched_only", c[c["match_loose"]])):
        mcb = pd.cut(sub["market_cap"], bins)
        t = sub.groupby([mcb, "g"], observed=True)["ins_buyers_90"].agg(lambda x: float((x > 0).mean())).unstack()
        out[f"fire_rate_by_mcap_{name}"] = {str(k): v for k, v in t.to_dict("index").items()}
        print(name, "\n", t)
    OUT.write_text(json.dumps(out, indent=2, default=str))
    print(json.dumps({k: v for k, v in out.items() if not k.startswith("fire")}, indent=1, default=str))


if __name__ == "__main__":
    main()
