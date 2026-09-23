"""
Down-cap point-in-time universe, three tiers, with a dollar-volume liquidity
floor replacing the naive price floor at the two lower tiers.

See PREREGISTRATION.md §1. Mirrors `build_pit_universe.py`'s domestic-common-
stock screen and cxs_marketcap disagreement check exactly (same source data,
same construction), but:

  1. computes ALL THREE tiers in one streaming pass instead of one parquet
     per floor choice, tagging each row with which tier(s) it clears, and
  2. replaces the two lower tiers' price floor with a trailing 20-trading-day
     median DOLLAR VOLUME floor computed on `closeunadj * volume` -- actual
     dollars traded that day, immune to the split-adjusted-close look-ahead
     bug documented in build_pit_universe.py's header and confirmed in Round
     11 (a $10 floor on split-adjusted close excluded Apple from the 2008
     universe because it split *after* 2008, not before).

RUNS FROM THE MAIN CHECKOUT'S DATA, NOT THIS WORKTREE. This package lives in
a git worktree (`.claude/worktrees/...`); git worktrees only check out
TRACKED files, and every data file this reads/writes is gitignored, so it
does not exist under the worktree path at all. MAIN_ROOT below is the one
place that matters -- change it if the worktree is ever merged and re-run
from the primary checkout.

OUTPUT
    <MAIN_ROOT>/data/sharadar/downcap_universe.parquet
        date, ticker, marketcap, close, closeunadj, sharesbas, cxs_marketcap,
        dollar_vol_20d (all in $ millions, matching Sharadar's marketcap
        convention), eligible_cap2000, eligible_cap500, eligible_cap150 (bool)
    <MAIN_ROOT>/data/sharadar/downcap_universe_report.txt
"""
import sys
import time
from pathlib import Path

import numpy as np
import pandas as pd
import pyarrow as pa
import pyarrow.parquet as pq

MAIN_ROOT = Path("/Users/ggraham/pipe_dream/final")
SHARADAR = MAIN_ROOT / "data" / "sharadar"
PANEL = SHARADAR / "panel"
OUT = SHARADAR / "downcap_universe.parquet"
REPORT = SHARADAR / "downcap_universe_report.txt"

DOMESTIC = {
    "Domestic Common Stock",
    "Domestic Common Stock Primary Class",
    "Domestic Common Stock Secondary Class",
}

# Tier definitions -- market cap in $M (Sharadar convention), liquidity floor
# in $M of trailing-20-day median dollar volume. cap2000 keeps the ORIGINAL
# price floor for a clean apples-to-apples reproduction of the deployed
# universe; the two down-cap tiers use the liquidity floor instead.
TIERS = {
    "cap2000": dict(min_marketcap=2000.0, min_price=10.0, min_dollar_vol=None),
    "cap500":  dict(min_marketcap=500.0,  min_price=None,  min_dollar_vol=0.5),
    "cap150":  dict(min_marketcap=150.0,  min_price=None,  min_dollar_vol=0.25),
}
LOOSEST_MARKETCAP = min(t["min_marketcap"] for t in TIERS.values())
DISAGREE_FACTOR = 10.0
DOLLAR_VOL_WINDOW = 20


def log(lines, s=""):
    print(s, flush=True)
    lines.append(s)


def main():
    t0 = time.time()
    lines = []

    master = pd.read_csv(SHARADAR / "tickers_master.csv", dtype=str)
    dom = set(master.loc[master["category"].isin(DOMESTIC), "ticker"])
    log(lines, f"domestic common stock in master: {len(dom):,} of {len(master):,}")

    sh = pd.read_csv(SHARADAR / "sf1_shares.csv", dtype={"ticker": str})
    sh["date"] = pd.to_datetime(sh["date"], errors="coerce")
    sh["sharesbas"] = pd.to_numeric(sh["sharesbas"], errors="coerce")
    sh = sh[sh["date"].notna() & sh["sharesbas"].notna() & (sh["sharesbas"] > 0)]
    sh = sh.sort_values("date")[["ticker", "date", "sharesbas"]].reset_index(drop=True)
    log(lines, f"filed share counts: {len(sh):,} rows, {sh['ticker'].nunique():,} tickers")

    months = sorted(f.stem for f in (PANEL / "daily").glob("*.parquet"))
    log(lines, f"{len(months)} months, {months[0]} .. {months[-1]}\n")

    frames = []
    for i, ym in enumerate(months, 1):
        d = pd.read_parquet(PANEL / "daily" / f"{ym}.parquet",
                             columns=["ticker", "date", "marketcap"])
        s = pd.read_parquet(PANEL / "stocks" / f"{ym}.parquet",
                             columns=["ticker", "date", "close", "closeunadj", "volume"])
        j = d[d["ticker"].isin(dom)].merge(s, on=["ticker", "date"], how="inner")
        j = j[j["marketcap"].notna() & j["close"].notna()]
        # Loosest pool up front -- every tier is a subset of this.
        j = j[j["marketcap"] >= LOOSEST_MARKETCAP]
        if j.empty:
            continue
        frames.append(j)
        if i % 60 == 0 or i == len(months):
            log(lines, f"  loaded {i:>3}/{len(months)} {ym}  "
                       f"rows so far {sum(len(f) for f in frames):,}  "
                       f"({time.time()-t0:.0f}s)")

    panel = pd.concat(frames, ignore_index=True)
    del frames
    log(lines, f"\nloosest-pool rows: {len(panel):,}, "
               f"{panel['ticker'].nunique():,} tickers ({time.time()-t0:.0f}s)")

    panel["date"] = pd.to_datetime(panel["date"])
    panel["ticker"] = panel["ticker"].astype(str)

    # cxs_marketcap disagreement check -- identical rule to
    # build_pit_universe.py, same reasoning (depositary-ratio artefacts are
    # one-sided: daily.marketcap running LOW vs close*shares is fine, running
    # HIGH by >10x is the corrupted case seen with RAMR).
    # merge_asof requires the LEFT frame sorted by the "on" key (date) first --
    # sorting by ["ticker", "date"] and relying on "by" alone raises "left
    # keys must be sorted". Carry an explicit row id and restore ticker/date
    # order afterward (same discipline as sweep/issuance.py's _asof_shares,
    # written after Round 16's merge_asof/sort_index bug).
    panel["_row"] = np.arange(len(panel), dtype=np.int64)
    panel = panel.sort_values(["date", "ticker"])
    panel = pd.merge_asof(panel, sh, on="date", by="ticker", direction="backward")
    panel = panel.sort_values("_row").reset_index(drop=True)
    panel.drop(columns=["_row"], inplace=True)
    panel["cxs_marketcap"] = panel["close"] * panel["sharesbas"] / 1e6
    has = panel["sharesbas"].notna() & (panel["cxs_marketcap"] > 0)
    ratio = panel["marketcap"] / panel["cxs_marketcap"]
    bad = has & (ratio > DISAGREE_FACTOR)
    n_bad = int(bad.sum())
    panel = panel[~bad].reset_index(drop=True)
    log(lines, f"dropped {n_bad:,} rows on the cxs_marketcap disagreement rule "
               f"({time.time()-t0:.0f}s)")

    # The rolling window below depends on within-group chronological order,
    # which the concat/merge_asof round trip above does not guarantee.
    panel = panel.sort_values(["ticker", "date"]).reset_index(drop=True)

    # Trailing 20-trading-day MEDIAN dollar volume, in $M. Sharadar SEP
    # `volume` is SPLIT-ADJUSTED, so actual dollars traded = close (also
    # split-adjusted) * volume. The original closeunadj * volume mixed bases:
    # for any name that split LATER it overstated past dollar volume by the
    # split ratio (AAPL 2008: 28x), letting future splitters -- future winners
    # -- clear the cap500/cap150 liquidity floor early (look-ahead; 4,990
    # cap500 / 26,518 cap150 rows, fixed 2026-09-22). Per-ticker rolling,
    # computed on the full history so day 1 of a name's eligibility window
    # already reflects real trailing liquidity, not a partial window.
    px = panel["close"].fillna(panel["closeunadj"])
    panel["_dollar_vol_raw"] = px * panel["volume"].astype(np.float64) / 1e6
    panel["dollar_vol_20d"] = (
        panel.groupby("ticker")["_dollar_vol_raw"]
             .transform(lambda s: s.rolling(DOLLAR_VOL_WINDOW, min_periods=DOLLAR_VOL_WINDOW // 2).median())
    )
    panel.drop(columns=["_dollar_vol_raw"], inplace=True)
    log(lines, f"computed trailing {DOLLAR_VOL_WINDOW}d median dollar volume "
               f"({time.time()-t0:.0f}s)")

    price_floor = panel["closeunadj"].fillna(panel["close"])
    for tier, spec in TIERS.items():
        ok = panel["marketcap"] >= spec["min_marketcap"]
        if spec["min_price"] is not None:
            ok = ok & (price_floor > spec["min_price"])
        if spec["min_dollar_vol"] is not None:
            ok = ok & (panel["dollar_vol_20d"] >= spec["min_dollar_vol"])
        panel[f"eligible_{tier}"] = ok.fillna(False)
        n = int(panel[f"eligible_{tier}"].sum())
        log(lines, f"  {tier}: marketcap>=${spec['min_marketcap']:.0f}M"
                   + (f", closeunadj>${spec['min_price']:.0f}" if spec["min_price"] else "")
                   + (f", 20d-median-$vol>=${spec['min_dollar_vol']:.2f}M" if spec["min_dollar_vol"] else "")
                   + f"  -> {n:,} rows")

    keep_any = panel[[f"eligible_{t}" for t in TIERS]].any(axis=1)
    panel = panel[keep_any].reset_index(drop=True)

    out_cols = ["date", "ticker", "marketcap", "close", "closeunadj",
                "sharesbas", "cxs_marketcap", "dollar_vol_20d"] + [f"eligible_{t}" for t in TIERS]
    panel = panel[out_cols].copy()
    panel["date"] = panel["date"].dt.strftime("%Y-%m-%d")

    OUT.parent.mkdir(parents=True, exist_ok=True)
    table = pa.Table.from_pandas(panel, preserve_index=False)
    pq.write_table(table, OUT)
    log(lines, f"\nfinal rows: {len(panel):,}, {panel['ticker'].nunique():,} distinct tickers")
    log(lines, f"-> {OUT}")

    log(lines, "\nuniverse size at a few dates:")
    dts = pd.to_datetime(panel["date"])
    for probe in ("2008-06-30", "2011-06-30", "2014-06-30", "2017-06-30",
                  "2020-06-30", "2023-06-30", "2026-06-30"):
        near = panel[dts == pd.Timestamp(probe)]
        if not near.empty:
            counts = {t: int(near[f"eligible_{t}"].sum()) for t in TIERS}
            log(lines, f"  {probe}  " + "  ".join(f"{t}={c}" for t, c in counts.items()))

    log(lines, f"\ntotal wall time: {time.time()-t0:.0f}s")
    REPORT.write_text("\n".join(lines))


if __name__ == "__main__":
    sys.exit(main())
