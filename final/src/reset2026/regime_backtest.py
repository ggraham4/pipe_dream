"""
Portfolio returns vs SPY by market regime, for the confirmed IC-weighted
composite -- per Gabe's request, framed as lower-risk than the equivalent
check on a fitted model since no parameter search over this data occurred
(the weights are a fixed function of an already-measured statistic). See
PREREGISTRATION.md's "Trial-count ledger and next round (2026-09-22)"
section: this does not reopen 2020-2026, and both regime definitions are
external (SPY's own realized return; a causal, pre-built vol split), not
chosen after seeing the composite's results.

Construction: pick_decile_volq (the confirmed construction), IC-weighted
composite score, cap150, 15bp cost, all 40 grid offsets -- identical
methodology to every other backtest number in this package.

Regime A: each nomination-era calendar year classified by SPY's OWN
realized return that year (up >+10%, down <-10%, flat between).
Regime B: high/low realized-vol regime, same causal expanding-median
split of trailing 60-day SPY vol already built for the regime diagnostic
(reused, not a new threshold).

Usage: python3 regime_backtest.py
"""
import json
import sys
import time
from pathlib import Path

import numpy as np
import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parent))
import composite as C            # noqa: E402
import run_backtest as RB         # noqa: E402
import ic_weighted_composite as ICW  # noqa: E402

MAIN_ROOT = Path("/Users/ggraham/pipe_dream/final")
SPY_CSV = MAIN_ROOT / "scripts" / "td_data_local" / "SPY.csv"
OUT_JSON = MAIN_ROOT / "out" / "reset2026" / "regime_backtest_report.json"
MARKET_VOL_WINDOW = 60
COST_BPS = 15.0


def log(msg):
    print(f"[{time.strftime('%H:%M:%S')}] {msg}", flush=True)


def build_vol_regime_map():
    spy = pd.read_csv(SPY_CSV, usecols=["date", "close"], parse_dates=["date"]).sort_values("date")
    spy["ret"] = spy["close"].pct_change()
    spy["realized_vol_60"] = spy["ret"].rolling(MARKET_VOL_WINDOW, min_periods=30).std() * np.sqrt(252)
    spy["regime_median"] = spy["realized_vol_60"].expanding(min_periods=252).median()
    spy["high_vol_regime"] = spy["realized_vol_60"] > spy["regime_median"]
    return spy.set_index("date")["high_vol_regime"]


def build_year_regime_map(spy_yearly_returns):
    out = {}
    for y, r in spy_yearly_returns.items():
        if r > 0.10:
            out[y] = "up"
        elif r < -0.10:
            out[y] = "down"
        else:
            out[y] = "flat"
    return out


def spy_calendar_year_returns():
    """SPY's actual close-to-close return for each calendar year -- direct
    and unambiguous, not an approximation via overlapping 40-day windows."""
    spy = pd.read_csv(SPY_CSV, usecols=["date", "close"], parse_dates=["date"]).sort_values("date")
    spy["year"] = spy["date"].dt.year
    out = {}
    for y, g in spy.groupby("year"):
        if len(g) < 2:
            continue
        out[y] = float(g["close"].iloc[-1] / g["close"].iloc[0] - 1.0)
    return out


def main():
    t0 = time.time()
    by_date, all_dates, spy, usmv = RB.load_data("nominate")
    vol_regime = build_vol_regime_map()

    # SPY's own realized calendar-year return (regime A) -- direct
    # close-to-close, not an approximation via overlapping 40-day windows.
    yearly_spy = spy_calendar_year_returns()
    year_regime = build_year_regime_map(yearly_spy)
    log(f"SPY yearly-return regime classification: {year_regime}")

    records = []
    for offset in range(40):
        rebal_dates = all_dates[offset::RB.HORIZON]
        prev_picks = set()
        for tp in rebal_dates:
            df_date = by_date.get(tp)
            if df_date is None:
                continue
            elig = df_date[df_date["eligible_cap150"]]
            if len(elig) < C.N_VOL_QUINTILES * 4:
                continue
            elig = elig.reset_index(drop=True)
            scored = ICW.compute_composite_ic_weighted(elig)
            picks = C.pick_decile_volq(elig, scored)
            ret_lookup = dict(zip(elig["ticker"], elig["gross_return_40"]))
            picks = [(t, w) for t, w in picks if pd.notna(ret_lookup.get(t))]
            if not picks:
                continue
            wsum = sum(w for _, w in picks)
            gross = sum((w / wsum) * (1.0 + ret_lookup[t]) for t, w in picks) - 1.0
            cur_set = {t for t, _ in picks}
            f_new = sum(1 for t in cur_set if t not in prev_picks) / len(cur_set)
            prev_picks = cur_set
            records.append({
                "date": tp, "offset": offset, "gross": gross, "f_new": f_new,
                "spy": spy.get(tp, np.nan),
                "year": tp.year, "year_regime": year_regime.get(tp.year, "unknown"),
                "vol_regime": "high" if vol_regime.get(tp, False) else "low",
            })
        if offset % 10 == 0:
            log(f"offset {offset:02d} done ({time.time()-t0:.0f}s)")

    df = pd.DataFrame(records)
    net = RB.turnover_net_return(df.to_dict("records"), COST_BPS)
    df["net"] = net
    df["excess"] = df["net"] - df["spy"]

    ann_factor = 252.0 / RB.HORIZON
    report = {"overall": {
        "mean_excess_annualized": float(df["excess"].mean() * ann_factor),
        "n_windows": int(len(df)),
    }}

    log("\n=== Regime A: SPY's own realized calendar-year return ===")
    for regime, g in df.groupby("year_regime"):
        mean_exc = g["excess"].mean() * ann_factor
        sd_exc = g["excess"].std() * np.sqrt(ann_factor)
        n_pos = int((g.groupby("offset")["excess"].mean() > 0).sum())
        log(f"  {regime:6s} n_windows={len(g):5d}  mean_excess/yr={mean_exc*100:+.2f}%  "
            f"sd={sd_exc*100:.2f}%  offsets_positive={n_pos}/40  years={sorted(set(y for y,r in year_regime.items() if r==regime))}")
        report[f"year_regime_{regime}"] = {
            "n_windows": int(len(g)), "mean_excess_annualized": float(mean_exc),
            "sd_annualized": float(sd_exc), "offsets_positive": n_pos,
            "years": sorted(set(y for y, r in year_regime.items() if r == regime)),
        }

    log("\n=== Regime B: high/low realized-vol regime (causal SPY median split) ===")
    for regime, g in df.groupby("vol_regime"):
        mean_exc = g["excess"].mean() * ann_factor
        sd_exc = g["excess"].std() * np.sqrt(ann_factor)
        n_pos = int((g.groupby("offset")["excess"].mean() > 0).sum())
        log(f"  {regime:6s} n_windows={len(g):5d}  mean_excess/yr={mean_exc*100:+.2f}%  sd={sd_exc*100:.2f}%")
        report[f"vol_regime_{regime}"] = {
            "n_windows": int(len(g)), "mean_excess_annualized": float(mean_exc),
            "sd_annualized": float(sd_exc),
        }

    log(f"\n=== Overall (all regimes pooled) ===")
    log(f"  mean excess/yr = {report['overall']['mean_excess_annualized']*100:+.2f}%  n_windows={report['overall']['n_windows']}")

    OUT_JSON.parent.mkdir(parents=True, exist_ok=True)
    with open(OUT_JSON, "w") as f:
        json.dump(report, f, indent=2, default=str)
    log(f"\nwrote {OUT_JSON} ({time.time()-t0:.0f}s total)")


if __name__ == "__main__":
    main()
