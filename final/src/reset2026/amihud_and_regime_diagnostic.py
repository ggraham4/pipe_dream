"""
Two pre-registered diagnostics (see PREREGISTRATION.md's "Two more
pre-registrations (2026-09-22)" section, written before this ran):

1. Amihud illiquidity IC screen -- one trial, no promotion decision made
   here, matches the discipline used for log_market_cap / book_to_market.
2. Regime-conditioning diagnostic -- causal expanding-median split of
   trailing 60-day SPY realized vol; screens momentum_12_1 and
   volatility_60's own IC in each half. Staged: only proceeds to an
   actual conditional-composite backtest if BOTH pre-specified hypotheses
   hold in their predicted direction.

Usage: python3 amihud_and_regime_diagnostic.py
"""
import json
import sys
import time
from pathlib import Path

import numpy as np
import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parent))
import composite as C  # noqa: E402

MAIN_ROOT = Path("/Users/ggraham/pipe_dream/final")
PANEL_PATH = MAIN_ROOT / "out" / "reset2026" / "composite_panel.parquet"
AMIHUD_PATH = MAIN_ROOT / "out" / "reset2026" / "amihud_feature.parquet"
SPY_CSV = MAIN_ROOT / "scripts" / "td_data_local" / "SPY.csv"
OUT_JSON = MAIN_ROOT / "out" / "reset2026" / "regime_diagnostic_report.json"

NOMINATE_START = pd.Timestamp("2007-01-02")
NOMINATE_END = pd.Timestamp("2019-12-31")
LABEL = "forward_return_tradable_40"
NW_LAG = 39
MARKET_VOL_WINDOW = 60


def log(msg):
    print(f"[{time.strftime('%H:%M:%S')}] {msg}", flush=True)


def newey_west_mean_t(x, lag=NW_LAG):
    x = np.asarray(x, dtype=np.float64)
    x = x[np.isfinite(x)]
    n = len(x)
    if n < 10:
        return {"mean": np.nan, "t": np.nan, "n": n}
    xc = x - x.mean()
    L = min(lag, n - 1)
    var = np.dot(xc, xc) / n
    for l in range(1, L + 1):
        w = 1.0 - l / (L + 1.0)
        var += 2.0 * w * (np.dot(xc[l:], xc[:-l]) / n)
    var = max(var, 1e-12)
    t = x.mean() / np.sqrt(var / n) if var > 0 else np.nan
    return {"mean": float(x.mean()), "t": float(t), "n": int(n)}


def pooled_ic(df, xcol, ycol, date_col="date"):
    g = df[[date_col, xcol, ycol]].dropna()
    out = {}
    for d, gd in g.groupby(date_col):
        if len(gd) < 20:
            continue
        c = gd[xcol].corr(gd[ycol], method="spearman")
        if pd.notna(c):
            out[d] = float(c)
    s = pd.Series(out)
    stats = newey_west_mean_t(s.to_numpy())
    stats["n_dates"] = int(len(s))
    return stats


def main():
    t0 = time.time()
    need = list(dict.fromkeys(["ticker", "date", "eligible_cap150", LABEL] + C.FACTOR_COLS))
    panel = pd.read_parquet(PANEL_PATH, columns=need)
    panel["date"] = pd.to_datetime(panel["date"])
    panel["ticker"] = panel["ticker"].astype(str)

    amihud = pd.read_parquet(AMIHUD_PATH)
    amihud["date"] = pd.to_datetime(amihud["date"])
    amihud["ticker"] = amihud["ticker"].astype(str)
    panel = panel.merge(amihud, on=["ticker", "date"], how="left")

    nom = panel[(panel["date"] >= NOMINATE_START) & (panel["date"] <= NOMINATE_END)
                & panel["eligible_cap150"]].copy()
    log(f"nomination-era cap150-eligible rows: {len(nom):,}, "
        f"amihud coverage {nom['amihud_20'].notna().mean():.1%}")

    report = {}

    # -------------------------------------------------------------------
    # 1. Amihud illiquidity IC screen
    # -------------------------------------------------------------------
    log("\n=== 1. Amihud illiquidity IC screen ===")
    amihud_ic = pooled_ic(nom, "amihud_20", LABEL)
    print(f"  pooled IC={amihud_ic['mean']:+.4f}  t={amihud_ic['t']:+.2f}  n={amihud_ic['n_dates']} dates "
          f"(hypothesized sign: +1)")
    years = nom["date"].dt.year
    odd_ic = pooled_ic(nom[years % 2 == 1], "amihud_20", LABEL)
    even_ic = pooled_ic(nom[years % 2 == 0], "amihud_20", LABEL)
    print(f"  split-half: odd-years IC={odd_ic['mean']:+.4f} t={odd_ic['t']:+.2f}  "
          f"even-years IC={even_ic['mean']:+.4f} t={even_ic['t']:+.2f}")
    report["amihud_screen"] = {"pooled": amihud_ic, "odd_years": odd_ic, "even_years": even_ic,
                                "hypothesized_sign": 1}

    # -------------------------------------------------------------------
    # 2. Regime-conditioning diagnostic
    # -------------------------------------------------------------------
    log("\n=== 2. Regime split (causal expanding-median of trailing 60d SPY realized vol) ===")
    spy = pd.read_csv(SPY_CSV, usecols=["date", "close"], parse_dates=["date"]).sort_values("date")
    spy["ret"] = spy["close"].pct_change()
    spy["realized_vol_60"] = spy["ret"].rolling(MARKET_VOL_WINDOW, min_periods=30).std() * np.sqrt(252)
    spy["regime_median"] = spy["realized_vol_60"].expanding(min_periods=252).median()
    spy["high_vol_regime"] = spy["realized_vol_60"] > spy["regime_median"]
    regime_map = spy.set_index("date")["high_vol_regime"]

    nom["high_vol_regime"] = nom["date"].map(regime_map)
    n_high = nom.loc[nom["high_vol_regime"] == True, "date"].nunique()
    n_low = nom.loc[nom["high_vol_regime"] == False, "date"].nunique()
    log(f"  {n_high} high-vol-regime dates, {n_low} low-vol-regime dates (nomination era)")

    mom_high = pooled_ic(nom[nom["high_vol_regime"] == True], "momentum_12_1", LABEL)
    mom_low = pooled_ic(nom[nom["high_vol_regime"] == False], "momentum_12_1", LABEL)
    vol_high = pooled_ic(nom[nom["high_vol_regime"] == True], "volatility_60", LABEL)
    vol_low = pooled_ic(nom[nom["high_vol_regime"] == False], "volatility_60", LABEL)

    print(f"\n  momentum_12_1 IC:  high-vol regime={mom_high['mean']:+.4f} (t={mom_high['t']:+.2f})   "
          f"low-vol regime={mom_low['mean']:+.4f} (t={mom_low['t']:+.2f})")
    print(f"  Hypothesis 1 (momentum weaker in high-vol): "
          f"{'HOLDS' if mom_high['mean'] < mom_low['mean'] else 'FAILS'}")

    print(f"\n  volatility_60 IC:  high-vol regime={vol_high['mean']:+.4f} (t={vol_high['t']:+.2f})   "
          f"low-vol regime={vol_low['mean']:+.4f} (t={vol_low['t']:+.2f})")
    print(f"  Hypothesis 2 (low-vol premium stronger, i.e. MORE negative IC, in high-vol regime): "
          f"{'HOLDS' if vol_high['mean'] < vol_low['mean'] else 'FAILS'}")

    h1_holds = mom_high["mean"] < mom_low["mean"]
    h2_holds = vol_high["mean"] < vol_low["mean"]
    report["regime_diagnostic"] = {
        "n_high_vol_dates": int(n_high), "n_low_vol_dates": int(n_low),
        "momentum_ic_high_vol": mom_high, "momentum_ic_low_vol": mom_low,
        "volatility_ic_high_vol": vol_high, "volatility_ic_low_vol": vol_low,
        "hypothesis_1_momentum_weaker_in_high_vol": bool(h1_holds),
        "hypothesis_2_lowvol_stronger_in_high_vol": bool(h2_holds),
        "both_hold": bool(h1_holds and h2_holds),
    }

    print(f"\n{'BOTH HYPOTHESES HOLD -- proceeding to conditional-composite backtest' if (h1_holds and h2_holds) else 'AT LEAST ONE HYPOTHESIS FAILED -- stopping at the diagnostic stage, per pre-registration'}")

    OUT_JSON.parent.mkdir(parents=True, exist_ok=True)
    with open(OUT_JSON, "w") as f:
        json.dump(report, f, indent=2, default=str)
    log(f"\nwrote {OUT_JSON} ({time.time()-t0:.0f}s total)")


if __name__ == "__main__":
    main()
