"""
Build the point-in-time candidate universe from the Sharadar panel.

WHAT THIS REPLACES
------------------
The old universe was "tickers worth >$2B TODAY" plus a partial patch of
S&P 500 leavers. Membership was knowable only in hindsight, so a model
trained on it could separate survivors from non-survivors without learning
anything about selection -- which is what the three-way ablation showed
(gaps exempt IC +0.1350 / screened +0.1262 / removed -0.0013).

Measured against this panel, that universe was missing a third of the
eligible domestic names in the early era, and 89% of what was missing had
since died:

    2008-06-30   981 domestic >=$2B   666 present   315 missing (281 dead)
    2014-06-30  1418                  923           495 missing (396 dead)
    2020-06-30  1344                 1050           294 missing (177 dead)
    2026-06-30  1701                 1576           125 missing ( 11 dead)

This builds the universe from what was true on the day instead.

THE SCREEN
----------
1. Domestic common stock only. ADRs and Canadian listings are excluded as
   a SCOPE decision, matching what the pipeline has always screened. This
   also removes the entire class of false positives in rule 3: an ADR's
   price is per-depositary-share while `sharesbas` counts ordinary shares,
   so the two disagree by the ADR ratio for perfectly healthy data
   (TSM 0.2 = 5:1, TM 0.1 = 10:1, PTRCY 0.01 = 100:1). 93% of an earlier
   ratio-based quarantine was ADRs behaving correctly.

2. marketcap >= $2B and closeunadj > $10, as of that date.

   THE PRICE FLOOR USES THE UNADJUSTED PRICE, AND THIS MATTERS ENORMOUSLY.
   `close` is split-adjusted, so a company that later splits has its whole
   history divided retroactively. Apple's 7:1 (2014) and 4:1 (2020) splits
   put its 2008-06-30 "close" at $5.98 -- against an actual traded price of
   $167.44. Screening on `close` therefore makes eligibility in 2008 depend
   on corporate actions announced in 2014 and 2020, which is look-ahead in
   the eligibility rule itself.

   The bias runs exactly the wrong way. Companies split BECAUSE the stock
   went up a lot, so a floor on split-adjusted price systematically removes
   the biggest future winners from the early universe. On 2008-06-30 it
   excluded 44 names worth $708B combined:

       AAPL   $147.6B   adj $5.98   actual $167.44
       AMZN   $ 30.6B   adj $3.67   actual $ 73.33
       CMCSA  $ 56.2B   adj $9.48   actual $ 18.97
       NVDA   $ 10.4B   adj $0.47   actual $ 18.72
       CSX    $ 25.4B   adj $6.98   actual $ 62.81
       TJX    $ 13.4B   adj $7.87   actual $ 31.47

   A $10 floor exists to keep penny stocks out, and "was this a penny stock"
   is a fact about the price people actually paid that day. `closeunadj` is
   that price.

   NOTE: this bug is inherited, not introduced. The old pipeline screened
   `test_rows["close"] > MIN_PRICE` on the same split-adjusted basis, so
   every prior backtest excluded Apple, Amazon and NVIDIA from its early
   windows.

3. AGREEMENT, not a blocklist. Two independently populated columns give
   market cap: `daily.marketcap`, and `close x sharesbas` from the filed
   share count. Where BOTH exist and `daily` exceeds `close x sharesbas`
   by more than 10x, the row is dropped. No threshold on plausibility, no
   curated exclusions -- the vendor contradicting itself is the whole
   signal.

   THE TEST IS ONE-SIDED, AND THE DIRECTION MATTERS. A first run used a
   symmetric band and dropped exactly 10 tickers, which split perfectly by
   the sign of the disagreement:

     daily >> close x shares -- daily is the wrong one, every time
       DIGA   120,902,938,553 vs        403     ratio 3e8
       RAMR           466,531 vs        467     ratio 1,000
       FDNHQ            9,401 vs         21     ratio 438
       AXPWQ            5,110 vs         13     ratio 400
       CERPQ           14,762 vs        295     ratio 50
       MERR             3,872 vs        129     ratio 30
       NBRVF            2,628 vs        263     ratio 10

     close x shares >> daily -- `daily` is CORRECT and the computed value
     is the wrong one, every time
       ONC     42,837 vs   557,046   BeOne Medicines, really ~$40B
       GWPH     6,917 vs    83,005   GW Pharma, acquired by Jazz for $7.2B
       MTBLY    7,070 vs   318,129   Moatable/Renren, really ~$7B at peak

   There is a mechanism behind that split, not just a pattern. `sharesbas`
   counts ORDINARY shares while the price is per depositary share, so for
   any depositary structure `close x sharesbas` overstates by the ADS ratio
   -- BeOne 13:1, GW 12:1. The computed value being too big has a benign
   explanation that recurs. `daily` being too big does not: it means the
   vendor's own market cap exceeds what its own price and its own filed
   share count can support.

   So the symmetric band was throwing away three real companies -- one of
   them a $40B name -- to catch nothing extra. Dropping only on
   `daily > 10x computed` separates the ten perfectly: all seven corrupt
   rows go, all three real companies stay.

   The one thing this gives up is catching a `daily.marketcap` that is far
   too SMALL. That is the harmless direction here: too small only excludes
   a name from the universe, and a name excluded for being under $2B never
   reaches this rule to begin with.

   Across the full history that is 7 tickers and 3,915 rows -- 0.06% of the
   panel. On 2008-06-30 it is 5 names, every one a known bad row:

       DIGA   daily 27,063,879,072   close x shares         90
       COR3   daily        125,155   close x shares         39
       RAMR   daily         27,251   close x shares         27
       CERPQ  daily          4,973   close x shares         99
       ICLD   daily         29,474   close x shares         18   (2014)

   RAM Holdings is the one that matters most, because no magnitude rule
   would ever have caught it: at $27B it sits comfortably inside the real
   megacap range, and only its own filed share count -- 27.3 MILLION, not
   27.3 billion -- exposes it.

4. A MISSING filing is NOT a disagreement. Requiring both values to clear
   $2B would drop real companies that simply have no SF1 row at that date:

       LO     Lorillard          $12,029M   no filing
       FMCC   Freddie Mac        $10,611M   no filing
       INFO1  IHS Markit          $4,783M   no filing

   Excluding those would reintroduce exactly the hole this exists to close.
   So rule 3 applies only where a filed count exists; otherwise
   `daily.marketcap` stands alone. Coverage is 98.9-100% of domestic names,
   so this fallback is rare and never load-bearing.

MEMORY
------
Streams month by month AND streams the output. An earlier version kept
every month's frame in a list and concatenated at the end -- that holds the
whole 8M-row result twice at the moment of the concat, and the OOM killer
takes it on a modest machine. Rows are now written to the parquet file as
each month finishes, so peak memory is one month, roughly 150k rows,
regardless of how long the history is.

Streaming out has one requirement worth stating: every batch must share ONE
schema, pinned up front. Inferring it per month does not work -- `sharesbas`
arrives as float64 in a month where some row had no filing and as int64 in a
month where every row had one, and the writer rejects the second batch. The
schema below is therefore explicit and every column is cast to it before
writing, rather than trusting whatever pandas inferred that month.

    python3 build_pit_universe.py
    python3 build_pit_universe.py --min-marketcap 2000 --min-price 10

OUTPUT
    final/data/sharadar/pit_universe.parquet
        date, ticker, marketcap, close, closeunadj, sharesbas, cxs_marketcap
        one row per (date, eligible ticker)
    final/data/sharadar/pit_universe_dropped.csv
        every row dropped by rule 3, with both values, for audit
    final/data/sharadar/pit_universe_report.txt
"""
import argparse
from pathlib import Path

import numpy as np
import pandas as pd
import pyarrow as pa
import pyarrow.parquet as pq

ROOT = Path(__file__).resolve().parent.parent
PANEL = ROOT / "data" / "sharadar" / "panel"
SHARADAR = ROOT / "data" / "sharadar"
OUT = SHARADAR / "pit_universe.parquet"
DROPPED = SHARADAR / "pit_universe_dropped.csv"
REPORT = SHARADAR / "pit_universe_report.txt"

DOMESTIC = {
    "Domestic Common Stock",
    "Domestic Common Stock Primary Class",
    "Domestic Common Stock Secondary Class",
}
MIN_MARKETCAP = 2000.0    # $2B, in millions -- daily.marketcap is millions
MIN_PRICE = 10.0          # applied to closeunadj -- see the header
DISAGREE_FACTOR = 10.0    # drop when daily.marketcap exceeds close x sharesbas
                          # by more than this. One-sided on purpose.


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--min-marketcap", type=float, default=MIN_MARKETCAP)
    ap.add_argument("--min-price", type=float, default=MIN_PRICE)
    ap.add_argument("--disagree-factor", type=float, default=DISAGREE_FACTOR)
    a = ap.parse_args()

    lines = []

    def say(s=""):
        print(s)
        lines.append(s)

    master = pd.read_csv(SHARADAR / "tickers_master.csv", dtype=str)
    dom = set(master.loc[master["category"].isin(DOMESTIC), "ticker"])
    say(f"domestic common stock in master: {len(dom):,} of {len(master):,}")

    sh = pd.read_csv(SHARADAR / "sf1_shares.csv", dtype={"ticker": str})
    sh["date"] = pd.to_datetime(sh["date"], errors="coerce")
    sh["sharesbas"] = pd.to_numeric(sh["sharesbas"], errors="coerce")
    sh = sh[sh["date"].notna() & sh["sharesbas"].notna() & (sh["sharesbas"] > 0)]
    sh = sh.sort_values("date")[["ticker", "date", "sharesbas"]].reset_index(drop=True)
    say(f"filed share counts: {len(sh):,} rows, {sh['ticker'].nunique():,} tickers")

    months = sorted(f.stem for f in (PANEL / "daily").glob("*.parquet"))
    say(f"{len(months)} months, {months[0]} .. {months[-1]}\n")

    # Pinned schema. Streaming batches must all match it -- see the memory
    # note above for why inferring per month fails.
    SCHEMA = pa.schema([
        ("date", pa.string()),
        ("ticker", pa.string()),
        ("marketcap", pa.float64()),
        ("close", pa.float64()),
        ("closeunadj", pa.float64()),
        ("sharesbas", pa.float64()),
        ("cxs_marketcap", pa.float64()),
    ])
    writer = None
    dropped = []
    n_screen = n_nofiling = n_kept = 0
    day_counts = {}
    tickers_seen = set()
    COLS = ["date", "ticker", "marketcap", "close", "closeunadj",
            "sharesbas", "cxs_marketcap"]
    for i, ym in enumerate(months, 1):
        d = pd.read_parquet(PANEL / "daily" / f"{ym}.parquet",
                            columns=["ticker", "date", "marketcap"])
        s = pd.read_parquet(PANEL / "stocks" / f"{ym}.parquet",
                            columns=["ticker", "date", "close", "closeunadj"])
        j = d[d["ticker"].isin(dom)].merge(s, on=["ticker", "date"], how="inner")
        j = j[j["marketcap"].notna() & j["close"].notna()]
        # price floor on the UNADJUSTED price -- the price people actually
        # paid that day. See the header: screening on split-adjusted `close`
        # removes future winners retroactively. Fall back to `close` only
        # where closeunadj is missing.
        px_floor = j["closeunadj"].fillna(j["close"])
        j = j[(j["marketcap"] >= a.min_marketcap) & (px_floor > a.min_price)]
        if j.empty:
            continue
        n_screen += len(j)

        j["date"] = pd.to_datetime(j["date"])
        j = j.sort_values("date")
        j["ticker"] = j["ticker"].astype(str)
        j = pd.merge_asof(j, sh, on="date", by="ticker", direction="backward")
        j["cxs_marketcap"] = j["close"] * j["sharesbas"] / 1e6

        has = j["sharesbas"].notna() & (j["cxs_marketcap"] > 0)
        n_nofiling += int((~has).sum())
        ratio = j["marketcap"] / j["cxs_marketcap"]
        # one-sided -- see the header. `close x sharesbas` running high is a
        # depositary-ratio artefact, not corruption.
        bad = has & (ratio > a.disagree_factor)

        if bad.any():
            b = j[bad].copy()
            b["ratio"] = ratio[bad]
            dropped.append(b)
        k = j[~bad].copy()
        k["date"] = k["date"].dt.strftime("%Y-%m-%d")
        k = k[COLS]
        k["date"] = k["date"].astype(str)
        k["ticker"] = k["ticker"].astype(str)
        for c in ("marketcap", "close", "closeunadj", "sharesbas",
                  "cxs_marketcap"):
            k[c] = pd.to_numeric(k[c], errors="coerce").astype("float64")
        n_kept += len(k)
        tickers_seen.update(k["ticker"].unique())
        for dt, c in k["date"].value_counts().items():
            day_counts[dt] = day_counts.get(dt, 0) + int(c)

        tbl = pa.Table.from_pandas(k, schema=SCHEMA, preserve_index=False)
        if writer is None:
            OUT.parent.mkdir(parents=True, exist_ok=True)
            writer = pq.ParquetWriter(OUT, SCHEMA)
        writer.write_table(tbl)

        if i % 60 == 0 or i == len(months):
            say(f"  {i:>3}/{len(months)} {ym}  kept {n_kept:,}"
                f"  dropped {sum(len(x) for x in dropped):,}")

    if writer is not None:
        writer.close()

    drp = (pd.concat(dropped, ignore_index=True) if dropped
           else pd.DataFrame(columns=["ticker", "date", "marketcap",
                                      "close", "sharesbas", "cxs_marketcap", "ratio"]))
    if len(drp):
        drp["date"] = pd.to_datetime(drp["date"]).dt.strftime("%Y-%m-%d")
        drp.to_csv(DROPPED, index=False)

    say(f"\npassed the screen        : {n_screen:,}")
    say(f"no filed share count     : {n_nofiling:,} "
        f"({100 * n_nofiling / max(n_screen, 1):.2f}%) -- daily.marketcap stands alone")
    say(f"dropped, daily > {a.disagree_factor:g}x computed: {len(drp):,} rows, "
        f"{drp['ticker'].nunique() if len(drp) else 0} tickers")
    say(f"universe rows            : {n_kept:,}")
    say(f"trading days             : {len(day_counts):,}")
    say(f"distinct tickers ever    : {len(tickers_seen):,}")
    say(f"\n-> {OUT}")

    if len(drp):
        say("\nevery ticker dropped by the agreement rule:")
        g = (drp.groupby("ticker")
                .agg(rows=("ratio", "size"), ratio=("ratio", "median"),
                     peak=("marketcap", "max"), cxs=("cxs_marketcap", "max"),
                     first=("date", "min"), last=("date", "max"))
                .sort_values("peak", ascending=False))
        nm = dict(zip(master["ticker"], master["name"]))
        say(f"  {'ticker':<9} {'rows':>6} {'daily peak':>18} {'cxs peak':>12} "
            f"{'ratio':>12}  name")
        for t, r in g.iterrows():
            say(f"  {t:<9} {int(r['rows']):>6} {r['peak']:>18,.0f} "
                f"{r['cxs']:>12,.0f} {r['ratio']:>12,.1f}  {str(nm.get(t, '?'))[:34]}")

    say("\nuniverse size at a few dates:")
    for dt in ("2008-06-30", "2011-06-30", "2014-06-30", "2017-06-30",
               "2020-06-30", "2023-06-30", "2026-06-30"):
        n = day_counts.get(dt, 0)
        if n:
            say(f"  {dt}  {n:,}")

    REPORT.write_text("\n".join(lines))
    say(f"\nreport -> {REPORT}")


if __name__ == "__main__":
    main()
