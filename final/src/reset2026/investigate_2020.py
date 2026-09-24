"""
One-off diagnostic, not part of any pre-registered result: chases down what
is actually driving the 2020 hold-out year for `asset_growth_dropped`
(+30.72% excess, the single dominant year in the LOYO check). Descriptive
only -- does not change any backtest number, does not touch FACTOR_SIGNS,
does not "fix" anything. Purpose is to answer: is 2020's return concentrated
in a small number of tickers/dates (a red flag, per this project's own
CHRD/MNST/PRIM history of exactly this pattern indicating a data bug), or
is it broadly distributed (consistent with a real, if extreme, market year)?

Usage: python3 investigate_2020.py
"""
import sys
import time
from pathlib import Path

import numpy as np
import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parent))
import composite as C            # noqa: E402
import run_backtest as RB         # noqa: E402
import correction_variants as CV  # noqa: E402


def log(msg):
    print(f"[{time.strftime('%H:%M:%S')}] {msg}", flush=True)


def main():
    t0 = time.time()
    by_date, all_dates, spy, usmv = RB.load_data("holdout")

    # Also need truncated flag and market_cap per pick -- load_data's panel
    # (via NEEDED_COLS) doesn't carry market_cap by default for this era;
    # pull it straight from composite_panel for the 2020 slice only.
    extra = pd.read_parquet(RB.PANEL_PATH, columns=["ticker", "date", "market_cap", "close"])
    extra["date"] = pd.to_datetime(extra["date"])
    extra["ticker"] = extra["ticker"].astype(str)
    extra_lookup = extra.set_index(["ticker", "date"])[["market_cap", "close"]]

    records = []
    for offset in range(40):
        rebal_dates = [d for d in all_dates[offset::RB.HORIZON] if d.year == 2020]
        for tp in rebal_dates:
            df_date = by_date.get(tp)
            if df_date is None:
                continue
            elig = df_date[df_date["eligible_cap150"]]
            if len(elig) < C.N_VOL_QUINTILES * 4:
                continue
            elig = elig.reset_index(drop=True)
            scored = CV.compute_composite_ablated(elig, CV.ASSET_GROWTH_DROPPED_SIGNS, neutral=False)
            picks = C.pick_decile_volq(elig, scored)
            ret_lookup = dict(zip(elig["ticker"], elig["gross_return_40"]))
            trunc_lookup = dict(zip(elig["ticker"], elig["truncated"]))
            for t, w in picks:
                r = ret_lookup.get(t)
                if pd.isna(r):
                    continue
                records.append({
                    "offset": offset, "date": tp, "ticker": t, "weight": w,
                    "gross_return_40": r, "contribution": w * r,
                    "truncated": bool(trunc_lookup.get(t, False)),
                })
    log(f"collected {len(records)} (offset,date,ticker) picks in 2020 windows ({time.time()-t0:.0f}s)")

    df = pd.DataFrame(records)

    log("\n=== Distinct rebalance dates touched in 2020 (across all 40 offsets) ===")
    print(sorted(df["date"].dt.date.unique().tolist()))

    log("\n=== Top 20 single (offset,date,ticker) picks by gross_return_40 ===")
    top = df.sort_values("gross_return_40", ascending=False).head(20)
    for _, r in top.iterrows():
        mc_close = extra_lookup.reindex([(r["ticker"], r["date"])])
        mc = mc_close["market_cap"].iloc[0] if len(mc_close) else np.nan
        cl = mc_close["close"].iloc[0] if len(mc_close) else np.nan
        print(f"  {r['date'].date()} offset={r['offset']:02d} {r['ticker']:8s} "
              f"ret={r['gross_return_40']*100:+8.1f}%  w={r['weight']:.3f}  "
              f"contrib={r['contribution']*100:+.2f}pp  trunc={r['truncated']}  "
              f"mcap=${mc/1e6:.0f}M  close=${cl:.2f}" if pd.notna(mc) else
              f"  {r['date'].date()} offset={r['offset']:02d} {r['ticker']:8s} "
              f"ret={r['gross_return_40']*100:+8.1f}%  w={r['weight']:.3f}  "
              f"contrib={r['contribution']*100:+.2f}pp  trunc={r['truncated']}  mcap=NA")

    log("\n=== Concentration: top-10 tickers by TOTAL contribution across all 2020 picks ===")
    by_ticker = df.groupby("ticker").agg(
        n_picks=("contribution", "size"),
        total_contribution=("contribution", "sum"),
        mean_return=("gross_return_40", "mean"),
        max_return=("gross_return_40", "max"),
    ).sort_values("total_contribution", ascending=False)
    total_contrib_all = df["contribution"].sum()
    print(by_ticker.head(15))
    top10_share = by_ticker.head(10)["total_contribution"].sum() / total_contrib_all
    print(f"\nTotal contribution, all picks: {total_contrib_all:.2f}")
    print(f"Top-10 tickers' share of total contribution: {top10_share*100:.1f}%")

    log("\n=== Truncated (delisting-floor) picks in 2020 ===")
    trunc = df[df["truncated"]]
    print(f"n truncated picks: {len(trunc)} of {len(df)} ({len(trunc)/len(df)*100:.1f}%)")
    if len(trunc):
        print(trunc.sort_values("gross_return_40", ascending=False).head(10)
              [["date", "offset", "ticker", "gross_return_40", "contribution"]])

    log("\n=== Return distribution across ALL 2020 picks ===")
    print(df["gross_return_40"].describe())
    print("skew:", df["gross_return_40"].skew())

    log(f"\ndone ({time.time()-t0:.0f}s total)")


if __name__ == "__main__":
    main()
