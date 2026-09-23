"""
Options overlay: instead of buying the stock, buy a 40-trading-day call,
strike = entry close rounded to the nearest $5, on the top-5 IC-weighted
picks each rebalance. Per Gabe's direct request.

IMPORTANT CAVEAT, stated before any number below is trusted: this project
has NO real historical option-chain data loaded in this environment (that
lives in the separate options-premium-model workstream, a 26GB DoltHub
export not available here). This uses Black-Scholes FAIR VALUE as the
entry premium, with trailing 60-day REALIZED volatility as the implied-vol
proxy. Real market premiums are typically priced ABOVE realized-vol fair
value (the variance risk premium is a well-documented, persistent effect,
Bondarenko 2003 and others) -- so this is a THEORETICAL CEILING on what a
real options strategy could achieve, not a tradable estimate. Real-world
numbers would be worse: real IV usually exceeds trailing realized vol,
which raises the true entry cost above what's computed here.

Pricing: Black-Scholes call, S=close on the rebalance date, K=round(S/5)*5,
T=40/252 years, r=the 3-month Treasury yield on/near that date
(data/rates/treasury_yields.csv, a real point-in-time rate, not an
assumption), sigma=volatility_60 (already annualized in this panel).
Payoff at expiry = max(S_T - K, 0), S_T = close 40 trading days later
(same-ticker shift, matching every other "forward" quantity in this
pipeline).

Usage: python3 options_overlay_backtest.py
"""
import sys
import time
from pathlib import Path

import numpy as np
import pandas as pd
from scipy.stats import norm

sys.path.insert(0, str(Path(__file__).resolve().parent))
import composite as C            # noqa: E402
import run_backtest as RB         # noqa: E402
import ic_weighted_composite as ICW  # noqa: E402

MAIN_ROOT = Path("/Users/ggraham/pipe_dream/final")
PANEL_PATH = MAIN_ROOT / "out" / "reset2026" / "composite_panel.parquet"
RATES_CSV = MAIN_ROOT / "data" / "rates" / "treasury_yields.csv"
TOP_N = 5
HORIZON = 40


def log(msg):
    print(f"[{time.strftime('%H:%M:%S')}] {msg}", flush=True)


def bs_call(S, K, T, r, sigma):
    if sigma <= 0 or T <= 0 or S <= 0 or K <= 0:
        return np.nan
    d1 = (np.log(S / K) + (r + 0.5 * sigma ** 2) * T) / (sigma * np.sqrt(T))
    d2 = d1 - sigma * np.sqrt(T)
    return S * norm.cdf(d1) - K * np.exp(-r * T) * norm.cdf(d2)


def main():
    t0 = time.time()
    need = list(dict.fromkeys(["ticker", "date", "eligible_cap150", "close", "volatility_60"]
                               + C.FACTOR_COLS))
    panel = pd.read_parquet(PANEL_PATH, columns=need)
    panel["date"] = pd.to_datetime(panel["date"])
    panel["ticker"] = panel["ticker"].astype(str)
    panel = panel.sort_values(["ticker", "date"]).reset_index(drop=True)
    panel["close_fwd40"] = panel.groupby("ticker")["close"].shift(-HORIZON)

    rates = pd.read_csv(RATES_CSV, parse_dates=["date"]).sort_values("date")
    rates_lookup = rates.set_index("date")["y3m"] / 100.0  # decimal

    NOMINATE_START = pd.Timestamp("2007-01-02")
    NOMINATE_END = pd.Timestamp("2019-12-31")
    nom = panel[(panel["date"] >= NOMINATE_START) & (panel["date"] <= NOMINATE_END)
                & panel["eligible_cap150"]].copy()

    by_date, all_dates, spy, usmv = RB.load_data("nominate")
    rebal_dates = all_dates[0::RB.HORIZON]  # single offset, matching the confirmed cell's offset 0

    stock_window_returns = []
    option_window_returns = []
    n_with_valid_option = 0
    n_total_picks = 0

    for tp in rebal_dates:
        cross = nom[nom["date"] == tp]
        if len(cross) < 20:
            continue
        cross = cross.reset_index(drop=True)
        scored = ICW.compute_composite_ic_weighted(cross)
        valid = scored["composite"].notna()
        top_idx = scored.loc[valid, "composite"].nlargest(TOP_N).index
        picks = cross.loc[top_idx]

        r_free = rates_lookup.asof(tp)
        if pd.isna(r_free):
            r_free = 0.03  # fallback, rare (pre-2004 gap), not expected to bind here

        stock_rets = []
        option_rets = []
        for _, row in picks.iterrows():
            S = row["close"]
            S_T = row["close_fwd40"]
            # volatility_60 in this panel is a RAW daily std dev (median
            # 0.0216 across the panel -- annualized equity vol is normally
            # 15-45%, i.e. 0.15-0.45, confirming this is daily-scale, not
            # annualized). Black-Scholes needs annualized sigma.
            sigma = row["volatility_60"] * np.sqrt(252) if pd.notna(row["volatility_60"]) else np.nan
            if pd.isna(S) or pd.isna(S_T) or pd.isna(sigma) or S <= 0:
                continue
            K = round(S / 5.0) * 5.0
            if K <= 0:
                continue
            premium = bs_call(S, K, HORIZON / 252.0, r_free, sigma)
            n_total_picks += 1
            if not np.isfinite(premium) or premium <= 0.01:
                continue  # degenerate (e.g. sigma=0) -- excluded, not counted as a loss or a win
            payoff = max(S_T - K, 0.0)
            option_ret = (payoff - premium) / premium
            stock_ret = S_T / S - 1.0
            stock_rets.append(stock_ret)
            option_rets.append(option_ret)
            n_with_valid_option += 1

        if stock_rets:
            stock_window_returns.append({"date": tp, "ret": np.mean(stock_rets),
                                          "spy": spy.get(tp, np.nan)})
        if option_rets:
            option_window_returns.append({"date": tp, "ret": np.mean(option_rets),
                                           "spy": spy.get(tp, np.nan)})

    log(f"n windows: {len(rebal_dates)}, n picks with valid option pricing: "
        f"{n_with_valid_option}/{n_total_picks}")

    sdf = pd.DataFrame(stock_window_returns)
    odf = pd.DataFrame(option_window_returns)

    for label, df in [("STOCK (top-5, equal-weight)", sdf), ("CALL OPTION overlay (BS fair value)", odf)]:
        ok = df["spy"].notna()
        terminal = float(np.prod(1 + df.loc[ok, "ret"]))
        spy_terminal = float(np.prod(1 + df.loc[ok, "spy"]))
        n_years = ok.sum() * HORIZON / 252.0
        ann_ret = terminal ** (1 / n_years) - 1
        ann_excess = (terminal / spy_terminal) ** (1 / n_years) - 1
        win_rate = float((df.loc[ok, "ret"] > df.loc[ok, "spy"]).mean())
        median_ret = float(df["ret"].median())
        pct_total_loss = float((df["ret"] <= -0.999).mean()) if label.startswith("CALL") else None
        log(f"\n{label}:")
        log(f"  terminal wealth ({n_years:.1f}yr): {terminal:.2f}x   annualized return: {ann_ret*100:+.2f}%")
        log(f"  annualized excess vs SPY: {ann_excess*100:+.2f}%   win-rate vs SPY per window: {win_rate*100:.1f}%")
        log(f"  median per-window return: {median_ret*100:+.1f}%   std per-window: {df['ret'].std()*100:.1f}%")
        if pct_total_loss is not None:
            log(f"  fraction of windows with a TOTAL loss on the option (expired worthless): {pct_total_loss*100:.1f}%")

    log(f"\ndone ({time.time()-t0:.0f}s total)")


if __name__ == "__main__":
    main()
