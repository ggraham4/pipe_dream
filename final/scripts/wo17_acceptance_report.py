"""
WO-17 acceptance (b) and (d): read-only report comparing the 09-08 master
(tickers_master_through_2026-09-08.csv, or the live file before the swap) with the
raw 09-26 pull (.wo17_staging/tickers_pull.csv), against composite_panel_v2.

    python final/scripts/wo17_acceptance_report.py

Writes final/out/wo17/acceptance_b.json and acceptance_b_tickers.csv (branch only).
Reads the main checkout; writes nothing there.
"""
import json
import sys
from pathlib import Path

import pandas as pd

HERE = Path(__file__).resolve().parent
MAIN = Path("/Users/ggraham/pipe_dream/final")
SH = MAIN / "data" / "sharadar"
R26 = MAIN / "out" / "reset2026"
OUT = HERE.parent / "out" / "wo17"
STAGE = HERE.parent.parent / ".wo17_staging"
BASE = SH / "tickers_master_through_2026-09-08.csv"
if not BASE.exists():
    BASE = SH / "tickers_master.csv"
LABELS = ["category", "siccode", "sicsector", "sicindustry", "famaindustry", "sector", "industry"]
DOMESTIC = {"Domestic Common Stock", "Domestic Common Stock Primary Class",
            "Domestic Common Stock Secondary Class"}
ELIG = ["eligible_cap2000", "eligible_cap500", "eligible_cap150",
        "eligible_cap2000_v1", "eligible_cap500_v1", "eligible_cap150_v1"]
BLOCKED = ["CTSO", "GOSS", "GTBP", "JAGX", "NFE", "NXXT", "OPTT", "VWAV"]
WO15 = ["BNTC", "BRTX", "BURU", "GAUZ", "HUBC", "IPDN", "KITT", "LRHC", "NRSN", "TNMG", "WHLR", "ASX"]


def spac(v):
    return "Blank Check" in (v or "")


def main():
    OUT.mkdir(parents=True, exist_ok=True)
    b_all = pd.read_csv(BASE, dtype=str, keep_default_na=False)
    b = b_all.drop_duplicates("ticker")
    n = pd.read_csv(STAGE / "tickers_pull.csv", dtype=str, keep_default_na=False)
    p = pd.read_parquet(R26 / "composite_panel_v2.parquet", columns=["ticker", "date"] + ELIG)
    p["ticker"] = p["ticker"].astype(str)
    p["date"] = pd.to_datetime(p["date"])
    panel_t = set(p["ticker"])
    post = p[p["date"] > "2026-09-08"]
    elig_post = set(post.loc[post[ELIG].any(axis=1), "ticker"])

    j = b.merge(n, on="ticker", how="left", suffixes=("_b", "_n"), indicator=True)
    rows = []
    for _, r in j.iterrows():
        t = r["ticker"]
        if r["_merge"] == "left_only":
            kinds = ["missing_from_pull"]
            changed = []
        else:
            changed = [c for c in LABELS if r[c + "_b"] != r[c + "_n"]]
            kinds = []
            if changed:
                kinds.append("label_change")
            if r["permaticker_b"] != r["permaticker_n"]:
                kinds.append("ticker_reused_new_permaticker")
            if spac(r["sicindustry_b"]) != spac(r["sicindustry_n"]):
                kinds.append("spac_flag_change")
            if (r["category_b"] in DOMESTIC) != (r["category_n"] in DOMESTIC):
                kinds.append("domestic_membership_change")
        if not kinds:
            continue
        rows.append({"ticker": t, "kinds": "|".join(kinds), "in_panel_v2": t in panel_t,
                     "eligible_after_0908": t in elig_post, "columns": "|".join(changed),
                     **{f"{c}_base": r[c + "_b"] for c in LABELS + ["permaticker", "name"]},
                     **{f"{c}_new": r.get(c + "_n", "") for c in LABELS + ["permaticker", "name"]}})
    d = pd.DataFrame(rows)
    d.to_csv(OUT / "acceptance_b_tickers.csv", index=False)

    # new tickers the next refresh would pick up (domestic, in the new pull, not in the base,
    # SEP rows after 09-08, and marketcap >= 150 ($M) on some DAILY row after 09-08)
    newt = n[~n["ticker"].isin(set(b["ticker"])) & n["category"].isin(DOMESTIC)]
    sep = pd.read_parquet(SH / "panel" / "stocks" / "2026-09.parquet", columns=["ticker", "date", "close"])
    dly = pd.read_parquet(SH / "panel" / "daily" / "2026-09.parquet", columns=["ticker", "date", "marketcap"])
    sep, dly = sep[sep["date"].astype(str) > "2026-09-08"], dly[dly["date"].astype(str) > "2026-09-08"]
    have = set(sep["ticker"])
    big = set(dly.loc[pd.to_numeric(dly["marketcap"], errors="coerce") >= 150, "ticker"])
    cand = newt[newt["ticker"].isin(have)]
    cand_big = cand[cand["ticker"].isin(big)]

    def sub(k, elig_only):
        x = d[d["kinds"].str.contains(k)] if len(d) else d
        if elig_only:
            x = x[x["eligible_after_0908"]]
        return sorted(x["ticker"])

    rep = {
        "base": BASE.name, "eligible_after_0908_tickers": len(elig_post),
        "label_change_eligible_after_0908": sub("label_change", True),
        "label_change_in_panel": sub("label_change", False) and [t for t in sub("label_change", False) if t in panel_t],
        "label_change_all_count": len(sub("label_change", False)),
        "spac_flag_change_eligible": sub("spac_flag_change", True),
        "spac_flag_change_in_panel": [t for t in sub("spac_flag_change", False) if t in panel_t],
        "domestic_membership_change_eligible": sub("domestic_membership_change", True),
        "domestic_membership_change_in_panel": [t for t in sub("domestic_membership_change", False) if t in panel_t],
        "missing_from_pull_in_panel": [t for t in sub("missing_from_pull", False) if t in panel_t],
        "missing_from_pull_eligible": sub("missing_from_pull", True),
        "ticker_reused_new_permaticker": sub("ticker_reused", False),
        "ticker_reused_in_panel": [t for t in sub("ticker_reused", False) if t in panel_t],
        "new_domestic_tickers_vs_base": int(len(newt)),
        "new_domestic_with_sep_after_0908": sorted(cand["ticker"]),
        "new_domestic_with_sep_and_mcap150_after_0908": sorted(cand_big["ticker"]),
    }
    # (d) blocked tickers vs actions
    act = pd.read_csv(STAGE / "actions_pull.csv", dtype=str, keep_default_na=False)
    rr = json.loads((R26 / "downcap_v2" / "refresh_report_2026-09-24.json").read_text())
    dd = {}
    for t in BLOCKED:
        a = act[(act["ticker"] == t) & act["action"].isin(["split", "adrratiosplit"])]
        cd = rr["change_detail"].get(t, {})
        dd[t] = {"actions": a[["date", "action", "value"]].values.tolist(),
                 "observed_close_ratio": [cd.get("close_ratio_min"), cd.get("close_ratio_max")],
                 "implied_ratio_from_value": [round(1 / float(v), 4) for v in a["value"] if v]}
    rep["blocked_8"] = dd
    rep["wo15_12_in_actions"] = {t: act[(act["ticker"] == t) & act["action"].isin(["split", "adrratiosplit"])]
                                 [["date", "action", "value"]].values.tolist() for t in WO15}
    (OUT / "acceptance_b.json").write_text(json.dumps(rep, indent=2, default=str))
    print(json.dumps(rep, indent=1, default=str))


if __name__ == "__main__":
    sys.exit(main())
