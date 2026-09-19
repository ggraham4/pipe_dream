"""
Option-implied features for the stock model.

    python3 build_options_features.py

Writes out/options_features.parquet, keyed (date, ticker), then merges onto the
point-in-time panel as out/features_with_options_sharadar_pit.parquet.

--------------------------------------------------------------------------
WHY NOT A FULL RISK-NEUTRAL DENSITY
--------------------------------------------------------------------------
The ask was the option-implied risk-neutral distribution. Breeden-Litzenberger
recovers it as the second derivative of call price with respect to strike --
and a second derivative needs a dense strike grid. This chain does not reliably
have one: name-dates with three strikes on the only listed expiry are common,
and numerically differentiating those twice produces a density-shaped object
with no information in it.

So the SHAPE is estimated in delta space instead, which is what the
practitioner measures and what survives a sparse grid:

    25-delta risk reversal  IV(-25d put) - IV(+25d call)   ~ RND skewness
    25-delta butterfly      mean(wings) - IV(ATM)          ~ RND excess kurtosis
    ATM IV                                                  ~ RND width

Same three moments, estimated robustly.

--------------------------------------------------------------------------
AND A WARNING ABOUT THE MEAN
--------------------------------------------------------------------------
There is deliberately NO feature for "where the options think the price is
going". The mean of the risk-neutral density is the forward price, by
no-arbitrage: F = S * exp((r - q) * T). It is arithmetic, not a forecast, and a
regression onto it would return a confident answer that is pure algebra. Every
feature here is shape or premium -- the parts that are not pinned by
no-arbitrage and can therefore carry information.

--------------------------------------------------------------------------
TWO CONSTRAINTS THAT GOVERN HOW ANY RESULT MAY BE READ
--------------------------------------------------------------------------
 1. HISTORY. The chain begins 2019-02-09. The project's nomination era is
    2007-2019, so these features have essentially no overlap with it. They can
    only be studied on 2019-2026, which is the twice-spent hold-out. Per Gabe's
    2026-09-16 decision the options era is treated as its OWN split --
    nominate 2019-2023, confirm 2024-2026 -- with the contamination stated:
    the top-5 / volq / invvol construction was itself confirmed on 2020-2026 in
    Round 13, so the construction is not independent of this span even though
    the features are.
 2. COVERAGE. 497 tickers, ~30% of the point-in-time universe, and it is the
    large-cap 30%. Every feature is NaN for the rest. XGBoost handles that
    natively, but a feature present only on large caps can act as a size proxy,
    and the screen must check that before crediting it with anything.

ACCEPTANCE CHECKS -- each is a number derivable before the run, per Gate A7c:
  * VRP (iv - hv) is positive on average. The variance risk premium is one of
    the most replicated facts in the literature; a negative mean means the two
    columns are swapped or misaligned.
  * 25-delta risk reversal is positive for the large majority of equity
    name-dates. Index and single-stock puts trade above calls; a symmetric or
    negative skew means the put/call assignment is inverted.
  * ATM IV sits in 0.05 .. 2.0. Outside that is a units error.
  * Coverage is ~30% of the universe and concentrated in large caps -- printed,
    with the size correlation, so it cannot be discovered later as a surprise.
"""
import sys
import time
from pathlib import Path

import numpy as np
import pandas as pd
import pyarrow.parquet as pq

sys.path.insert(0, str(Path(__file__).resolve().parent))
from features import OUT_DIR                                   # noqa: E402

DATA = Path(__file__).resolve().parents[1] / "data" / "options_raw"
CHAIN = DATA / "option_chain_sp500.parquet"
VOLHIST = DATA / "volatility_history_sp500.parquet"
PANEL = OUT_DIR / "features_with_fundamentals_sharadar_pit.parquet"
DST = OUT_DIR / "options_features.parquet"
DST_PANEL = OUT_DIR / "features_with_options_sharadar_pit.parquet"

# The model's horizon is 40 trading days ~ 56 calendar days. Expiries are
# matched to that rather than to a fixed 30 days, so the implied move and the
# skew describe the window the position is actually held over.
TARGET_DTE = 56
DTE_LO, DTE_HI = 20, 100

OPTION_FEATURE_COLS = [
    "opt_vrp", "opt_iv_pctile", "opt_iv_mom_1m", "opt_vrp_mom_1m",
    "opt_atm_iv", "opt_rr25", "opt_bfly25", "opt_term_slope",
    "opt_implied_move_40",
]


def _interp_iv_at_delta(g, target, is_call):
    """IV at a target delta, linearly interpolated along the smile.

    Delta is monotone in strike within a side, so interpolating in delta space
    rather than strike space gives a moneyness-standardised quote: comparable
    across names with different spot prices and volatilities, which raw strikes
    are not."""
    d = g["delta"].to_numpy(np.float64)
    v = g["vol"].to_numpy(np.float64)
    ok = np.isfinite(d) & np.isfinite(v) & (v > 1e-4) & (v < 5.0)
    if ok.sum() < 2:
        return np.nan
    d, v = d[ok], v[ok]
    o = np.argsort(d)
    d, v = d[o], v[o]
    if target < d[0] or target > d[-1]:
        return np.nan                    # do not extrapolate off the smile
    return float(np.interp(target, d, v))


def chain_features(verbose=True):
    """One streaming pass over the 55M-row chain."""
    pf = pq.ParquetFile(CHAIN)
    cols = ["date", "act_symbol", "expiration", "call_put", "vol", "delta"]
    out, carry = [], None
    t0 = time.time()
    for i in range(pf.num_row_groups):
        t = pf.read_row_group(i, columns=cols).to_pandas()
        if carry is not None:
            t = pd.concat([carry, t], ignore_index=True)
        # The file is date-ordered; hold back the final date so a name-date
        # split across a row-group boundary is never computed from half its
        # contracts. Without this the boundary dates get a silently truncated
        # smile, which is exactly the kind of defect that produces plausible
        # numbers and no error.
        last = t["date"].iloc[-1]
        carry = t[t["date"] == last]
        t = t[t["date"] != last]
        if len(t):
            out.append(_one_batch(t))
        if verbose and (i % 50 == 0 or i == pf.num_row_groups - 1):
            print(f"  [{i+1}/{pf.num_row_groups}] {time.time()-t0:.0f}s", flush=True)
    if carry is not None and len(carry):
        out.append(_one_batch(carry))
    return pd.concat(out, ignore_index=True)


def _one_batch(t):
    t = t.copy()
    t["date"] = pd.to_datetime(t["date"])
    t["expiration"] = pd.to_datetime(t["expiration"])
    t["dte"] = (t["expiration"] - t["date"]).dt.days
    t = t[(t["dte"] >= DTE_LO) & (t["dte"] <= DTE_HI)]
    if not len(t):
        return pd.DataFrame(columns=["date", "act_symbol"])

    rows = []
    for (dt, sym), g in t.groupby(["date", "act_symbol"], sort=False):
        exps = g["expiration"].unique()
        if not len(exps):
            continue
        dtes = np.array([(pd.Timestamp(e) - dt).days for e in exps])
        near = exps[np.argmin(np.abs(dtes - TARGET_DTE))]
        gg = g[g["expiration"] == near]
        calls = gg[gg["call_put"] == "Call"]
        puts = gg[gg["call_put"] == "Put"]
        atm = _interp_iv_at_delta(calls, 0.50, True)
        c25 = _interp_iv_at_delta(calls, 0.25, True)
        p25 = _interp_iv_at_delta(puts, -0.25, False)
        # term slope: shortest vs longest available expiry in the band
        slope = np.nan
        if len(exps) > 1:
            lo_e, hi_e = exps[np.argmin(dtes)], exps[np.argmax(dtes)]
            a = _interp_iv_at_delta(g[(g.expiration == hi_e) & (g.call_put == "Call")], 0.50, True)
            b = _interp_iv_at_delta(g[(g.expiration == lo_e) & (g.call_put == "Call")], 0.50, True)
            if np.isfinite(a) and np.isfinite(b):
                slope = a - b
        rr = p25 - c25 if np.isfinite(p25) and np.isfinite(c25) else np.nan
        bf = ((p25 + c25) / 2.0 - atm
              if np.isfinite(p25) and np.isfinite(c25) and np.isfinite(atm) else np.nan)
        rows.append({"date": dt, "act_symbol": sym, "opt_atm_iv": atm,
                     "opt_rr25": rr, "opt_bfly25": bf, "opt_term_slope": slope,
                     "opt_implied_move_40": (atm * np.sqrt(40.0 / 252.0)
                                             if np.isfinite(atm) else np.nan)})
    return pd.DataFrame(rows)


def volhist_features():
    v = pd.read_parquet(VOLHIST)
    v["date"] = pd.to_datetime(v["date"])
    out = pd.DataFrame({"date": v["date"], "act_symbol": v["act_symbol"]})
    out["opt_vrp"] = v["iv_current"] - v["hv_current"]
    rng = (v["iv_year_high"] - v["iv_year_low"])
    out["opt_iv_pctile"] = np.where(rng > 1e-6,
                                    (v["iv_current"] - v["iv_year_low"]) / rng, np.nan)
    out["opt_iv_mom_1m"] = v["iv_current"] - v["iv_month_ago"]
    out["opt_vrp_mom_1m"] = ((v["iv_current"] - v["hv_current"])
                             - (v["iv_month_ago"] - v["hv_month_ago"]))
    return out


def main():
    t0 = time.time()
    print("volatility history ...")
    vh = volhist_features()
    print(f"  {len(vh):,} name-dates")

    print(f"streaming {CHAIN.name} ({CHAIN.stat().st_size/1e6:.0f}MB) ...")
    ch = chain_features()
    print(f"  {len(ch):,} name-dates with a usable smile")

    feat = vh.merge(ch, on=["date", "act_symbol"], how="outer")
    feat = feat.rename(columns={"act_symbol": "ticker"})

    print("\n--- acceptance checks ---")
    ok = True
    vrp = feat["opt_vrp"].dropna()
    print(f"  VRP (iv-hv): mean {vrp.mean():+.4f}, {100*(vrp>0).mean():.1f}% positive")
    if not (vrp.mean() > 0 and (vrp > 0).mean() > 0.5):
        ok = False
        print("    FAIL -- the variance risk premium is positive in every published "
              "study of equity options. A negative mean means iv/hv are swapped "
              "or the join is misaligned.")
    rr = feat["opt_rr25"].dropna()
    print(f"  25d risk reversal: mean {rr.mean():+.4f}, "
          f"{100*(rr>0).mean():.1f}% positive")
    if not (rr.mean() > 0 and (rr > 0).mean() > 0.6):
        ok = False
        print("    FAIL -- equity puts trade above calls. A symmetric or negative "
              "skew means the put/call assignment or the delta sign is inverted.")
    iv = feat["opt_atm_iv"].dropna()
    print(f"  ATM IV: median {iv.median():.3f}, "
          f"{100*((iv>0.05)&(iv<2.0)).mean():.1f}% in 0.05..2.0")
    if ((iv > 0.05) & (iv < 2.0)).mean() < 0.95:
        ok = False
        print("    FAIL -- ATM implied vol outside a plausible band; units error")
    bf = feat["opt_bfly25"].dropna()
    print(f"  25d butterfly: mean {bf.mean():+.4f} "
          f"(positive = fat tails vs lognormal, expected)")

    for c in OPTION_FEATURE_COLS:
        print(f"  {c:<22} {100*feat[c].notna().mean():>5.1f}% populated")

    print(f"\n{'ALL CHECKS PASSED' if ok else 'CHECKS FAILED -- do not use'}")
    if not ok:
        sys.exit(1)
    feat.to_parquet(DST, index=False)
    print(f"written {DST} ({len(feat):,} rows)")

    print(f"\nmerging onto {PANEL.name} ...")
    panel = pd.read_parquet(PANEL)
    n0 = len(panel)
    panel = panel.merge(feat, on=["date", "ticker"], how="left")
    assert len(panel) == n0, f"merge changed row count {n0} -> {len(panel)}"
    sub = panel[panel["date"] >= "2019-02-09"]
    cov = sub["opt_atm_iv"].notna().mean()
    print(f"  coverage after 2019-02-09: {cov:.1%} of panel rows")
    if "market_cap" in sub.columns:
        has = sub["opt_atm_iv"].notna()
        print(f"  median market cap WITH options ${sub.loc[has,'market_cap'].median()/1e9:.1f}B "
              f"vs WITHOUT ${sub.loc[~has,'market_cap'].median()/1e9:.1f}B")
        print("  ^ if these differ a lot the feature is partly a size proxy, and any")
        print("    screen must neutralise on size before crediting it.")
    panel.to_parquet(DST_PANEL, index=False)
    print(f"written {DST_PANEL} ({time.time()-t0:.0f}s total)")


if __name__ == "__main__":
    main()
