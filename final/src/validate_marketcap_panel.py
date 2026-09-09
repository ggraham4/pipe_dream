"""
Find the marketcap rows that are wrong but look right.

THE PROBLEM THIS EXISTS FOR
---------------------------
`daily.marketcap` is in millions throughout 2005-2026 -- settled, 21/21
anchors against SF1 land at ~1e6, and no per-date median breaks. But the
column contains corrupt rows, and they come in two very different classes.

CLASS 1 -- astronomical. Trivially caught by any threshold.
    DIGA  Applied Digital Solutions   80,658,330,055  (2005)  $80.6 quadrillion
    BNBX  BNB Plus Corp                5,248,412      (2006)  $5.2T, in 2006

CLASS 2 -- plausible magnitude, and therefore dangerous.
    COR3  Cortex Pharmaceuticals     246,920 (2005)   320,418 (2006)
    RAMR  RAM Holdings               342,340 (2006)    27,251 (2008)
    Cortex was a micro-cap biotech. At 246,920 it is a $247B company --
    on 2005-01-31 the 6th largest in America, ahead of Walmart. RAM
    Holdings was a small Bermuda reinsurer; at $27B on 2008-06-30 it clears
    a $2B screen comfortably. Both sit inside the real megacap range, so NO
    magnitude threshold separates them from Citigroup.

WHY A THRESHOLD ON IMPLIED SHARES IS NOT ENOUGH EITHER
------------------------------------------------------
Check 1 flags implied share counts (marketcap x 1e6 / close) above 30bn.
That number was chosen by hand, and the data shows it landing arbitrarily:

    RAMR  27,251,400,000   just UNDER  -> missed
    CHIO  32,000,000,000   just OVER   -> caught

RAMR's filings say 27,282,579 shares -- 27.3 MILLION. The vendor's figure
is out by almost exactly 1000x. A threshold on a derived quantity is still
a magnitude rule; it cannot separate a wrong value from a large one. Check
1 is kept only as a coarse net for rows check 2 cannot reach.

CHECK 2 IS THE REAL TEST
------------------------
SF1's `sharesbas` is what the company actually filed, recorded separately
from marketcap. Joined point-in-time (most recent filing at or before the
date), implied/filed should sit near 1. Where it does not, two columns the
vendor populated independently contradict each other, and no threshold has
to be invented:

    RAMR  implied 27,251,400,000 / filed 27,282,579   = ~999
    COR3  implied 154,675,333,333 / filed 68,412,618  = ~2261
    AAPL  filed 14,594,180,000                          agrees

MEMORY
------
An earlier version loaded both panels whole -- 30.0M + 32.5M rows -- and
merged them in one go. That runs on a workstation and is killed by the OOM
killer anywhere smaller. There is no reason for it: the join is exact on
(ticker, date) and every month is independent, so this streams month by
month and keeps only flagged rows plus one array of implied share counts.
Peak memory is one month, about 150k rows.

Rows are QUARANTINED to a file, never deleted from the panel. The universe
builder reads the quarantine and excludes it, so every exclusion stays
visible and auditable instead of being baked into the data.

    python3 validate_marketcap_panel.py
    python3 validate_marketcap_panel.py --max-implied-shares 25e9

OUTPUT
    final/data/sharadar/marketcap_quarantine.csv
    final/data/sharadar/marketcap_validation_report.txt
"""
import argparse
from pathlib import Path

import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parent.parent
PANEL = ROOT / "data" / "sharadar" / "panel"
SHARADAR = ROOT / "data" / "sharadar"
QUAR = SHARADAR / "marketcap_quarantine.csv"
REPORT = SHARADAR / "marketcap_validation_report.txt"

# Arbitrary, and known to be insufficient -- see RAMR above. Kept as a
# coarse net for rows with no filed share count to compare against.
MAX_IMPLIED_SHARES = 30e9
# implied/filed outside this band means two independently populated vendor
# columns disagree. Wide on purpose: buybacks, issuance and filing lag all
# move the ratio legitimately, and the errors being hunted are 1000x.
MAX_SHARE_RATIO = 5.0
MIN_SHARE_RATIO = 0.2
# below this, a name cannot reach a $2B universe and checking it only adds
# noise from penny prices
MIN_MARKETCAP = 100.0     # $100M, in millions
UNIVERSE_MIN = 2000.0     # $2B, in millions


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--max-implied-shares", type=float, default=MAX_IMPLIED_SHARES)
    a = ap.parse_args()

    lines = []

    def say(s=""):
        print(s)
        lines.append(s)

    dd, sd = PANEL / "daily", PANEL / "stocks"
    if not dd.is_dir() or not sd.is_dir():
        raise SystemExit(f"no panel under {PANEL}. Run sharadar_pull_pit_panel.py first.")
    months = sorted(f.stem for f in dd.glob("*.parquet"))
    say(f"{len(months)} months, {months[0]} .. {months[-1]}")

    shares = None
    sf1 = SHARADAR / "sf1_shares.csv"
    if sf1.exists():
        shares = pd.read_csv(sf1, dtype={"ticker": str})
        shares["date"] = pd.to_datetime(shares["date"], errors="coerce")
        shares["sharesbas"] = pd.to_numeric(shares["sharesbas"], errors="coerce")
        shares = shares[shares["date"].notna() & shares["sharesbas"].notna()
                        & (shares["sharesbas"] > 0)]
        shares = (shares.sort_values("date")[["ticker", "date", "sharesbas"]]
                  .reset_index(drop=True))
        say(f"filed share counts: {len(shares):,} rows, "
            f"{shares['ticker'].nunique():,} tickers")
    else:
        say(f"{sf1.name} NOT PRESENT -- check 2 skipped. Run "
            f"sharadar_pull_shares.py; check 1 alone misses RAMR.")

    n_daily = n_join = n_noprice = n_ratio_rows = 0
    impl_pool, flagged = [], []

    for i, ym in enumerate(months, 1):
        d = pd.read_parquet(dd / f"{ym}.parquet", columns=["ticker", "date", "marketcap"])
        s = pd.read_parquet(sd / f"{ym}.parquet", columns=["ticker", "date", "close"])
        n_daily += len(d)
        d = d[d["marketcap"].notna() & (d["marketcap"] > 0)]
        j = d.merge(s, on=["ticker", "date"], how="left")
        n_join += len(j)
        n_noprice += int(j["close"].isna().sum())

        ok = j["close"].notna() & (j["close"] > 0)
        j = j[ok].copy()
        j["implied_shares"] = j["marketcap"] * 1e6 / j["close"]
        j = j[j["marketcap"] >= MIN_MARKETCAP]

        impl_pool.append(
            j.loc[j["marketcap"] >= UNIVERSE_MIN, "implied_shares"]
             .to_numpy(dtype="float64"))

        b1 = j[j["implied_shares"] > a.max_implied_shares].copy()
        if len(b1):
            b1["reason"] = "implied_shares"
            b1["sharesbas"] = np.nan
            b1["share_ratio"] = np.nan
            flagged.append(b1)

        if shares is not None:
            k = j.copy()
            k["date"] = pd.to_datetime(k["date"], errors="coerce")
            k = k[k["date"].notna()].sort_values("date")
            k["ticker"] = k["ticker"].astype(str)
            k = pd.merge_asof(k, shares, on="date", by="ticker",
                              direction="backward")
            k["share_ratio"] = k["implied_shares"] / k["sharesbas"]
            m = k["share_ratio"].notna()
            n_ratio_rows += int(m.sum())
            b2 = k[m & ((k["share_ratio"] > MAX_SHARE_RATIO)
                        | (k["share_ratio"] < MIN_SHARE_RATIO))].copy()
            if len(b2):
                b2["reason"] = "share_ratio"
                b2["date"] = b2["date"].dt.strftime("%Y-%m-%d")
                flagged.append(b2)

        if i % 60 == 0 or i == len(months):
            say(f"  {i:>3}/{len(months)} {ym}  flagged so far "
                f"{sum(len(x) for x in flagged):,}")

    say(f"\ndaily rows            : {n_daily:,}")
    say(f"joined with a price   : {n_join - n_noprice:,}")
    say(f"no matching price bar : {n_noprice:,} "
        f"({100 * n_noprice / max(n_join, 1):.2f}%)")

    pool = np.concatenate([p for p in impl_pool if len(p)]) if impl_pool else np.array([])
    if len(pool):
        say(f"\nimplied-share distribution among rows clearing $2B (n={len(pool):,}):")
        for p in (50, 90, 99, 99.9, 99.99, 100):
            say(f"    p{p:<8g} {np.percentile(pool, p):>22,.0f}")
        say("  the jump between p99.9 and p99.99 is where plausible ends and")
        say("  corruption begins -- and it is far too abrupt to be a real tail.")

    say(f"\nCHECK 1 -- implied shares > {a.max_implied_shares:,.0f}"
        f"   (arbitrary; misses RAMR at 27.25bn)")
    c1 = [x for x in flagged if (x["reason"] == "implied_shares").all()]
    n1 = sum(len(x) for x in c1)
    say(f"  flagged rows: {n1:,}")

    if shares is not None:
        say(f"\nCHECK 2 -- implied vs filed sharesbas")
        say(f"  rows with a filed count: {n_ratio_rows:,}")
        c2 = [x for x in flagged if (x["reason"] == "share_ratio").all()]
        say(f"  flagged rows (ratio outside {MIN_SHARE_RATIO}-{MAX_SHARE_RATIO}): "
            f"{sum(len(x) for x in c2):,}")

    if flagged:
        q = pd.concat(flagged, ignore_index=True)
        q["date"] = q["date"].astype(str)
        q = (q[["ticker", "date", "marketcap", "close", "implied_shares",
                "sharesbas", "share_ratio", "reason"]]
             .sort_values(["ticker", "date"])
             .drop_duplicates(subset=["ticker", "date"], keep="first"))
    else:
        q = pd.DataFrame(columns=["ticker", "date", "marketcap", "close",
                                  "implied_shares", "sharesbas",
                                  "share_ratio", "reason"])

    QUAR.parent.mkdir(parents=True, exist_ok=True)
    q.to_csv(QUAR, index=False)
    say(f"\nquarantined {len(q):,} rows / {q['ticker'].nunique() if len(q) else 0} "
        f"tickers -> {QUAR}")

    if len(q):
        say("\nworst offenders by peak marketcap:")
        top = (q.groupby("ticker")
                 .agg(peak=("marketcap", "max"), rows=("marketcap", "size"),
                      ratio=("share_ratio", "max"), first=("date", "min"),
                      last=("date", "max"))
                 .sort_values("peak", ascending=False).head(30))
        say(f"  {'ticker':<9} {'peak ($M)':>18} {'rows':>7} {'max ratio':>13}  span")
        for t, r in top.iterrows():
            rt = f"{r['ratio']:,.1f}" if pd.notna(r["ratio"]) else "-"
            say(f"  {t:<9} {r['peak']:>18,.1f} {r['rows']:>7,} {rt:>13}  "
                f"{r['first']}..{r['last']}")

        inuni = q[q["marketcap"] >= UNIVERSE_MIN]
        say(f"\nIMPACT -- rows that would have entered a >$2B screen:")
        say(f"  {len(inuni):,} rows, {inuni['ticker'].nunique():,} tickers")
        if len(inuni):
            say(f"  {sorted(inuni['ticker'].unique())[:40]}")

    REPORT.write_text("\n".join(lines))
    say(f"\nreport -> {REPORT}")


if __name__ == "__main__":
    main()
