"""
Pull a FRESH live option-chain snapshot for the options-model universe,
using yfinance -- run this ON YOUR OWN MACHINE, same reasoning as
local_data_pull.py: yfinance's live `Ticker.option_chain()` call uses your
own network connection, sidestepping any sandbox network restrictions.

This does NOT replace the DoltHub historical data (see
update_options_history.py for that) -- it produces a same-day snapshot to
score "today's options picks" against, refreshing:
    final/data/live_score/live_calls_chain.parquet
    final/data/live_score/live_volhist.parquet

Why this is needed at all: per models/options-premium-model-design.md,
yfinance only exposes a LIVE option chain, never history -- which is
exactly what we want here (DoltHub is the history source; yfinance is the
"what does the market look like right now" source).

hv_current / iv_current in the real DoltHub volatility_history table are
presumably a realized-vol and an average/ATM implied-vol measure per
ticker per day (field names only, exact methodology not documented in this
repo). This script computes reasonable proxies with the same names and
similar meaning, not a confirmed match to DoltHub's exact definitions:
    hv_current  = annualized realized volatility, trailing 21 trading days
                  (computed from the local price history -- no external
                  data needed)
    iv_current  = implied volatility of the near-the-money call in the
                  freshly-pulled chain (yfinance option chains include
                  impliedVolatility per contract)
A small, clearly-flagged approximation is better than silently reusing a
stale DoltHub snapshot forever -- but if precise parity with the training
data's hv_current/iv_current matters, prefer pulling a fresh DoltHub export
instead (see update_options_history.py) once that data is only a day or two
stale.

Usage:
    pip install yfinance pandas pyarrow
    python3 pull_live_options_chain.py                  # full universe
    python3 pull_live_options_chain.py AAPL MSFT NVDA    # just these tickers (testing)
"""
import sys
import time
from pathlib import Path

try:
    import yfinance as yf
except ImportError:
    print("Missing dependency. Run: pip install yfinance pandas pyarrow")
    sys.exit(1)

import numpy as np
import pandas as pd

PROJECT_ROOT = Path(__file__).resolve().parent.parent  # final/
DATA_DIR = PROJECT_ROOT / "scripts" / "td_data_local"
LIVE_SCORE_DIR = PROJECT_ROOT / "data" / "live_score"
TARGET_DTE_MIN, TARGET_DTE_MAX = 20, 40  # widen around the ~30-day monthly target used in training


def realized_vol_21d(ticker: str) -> float | None:
    p = DATA_DIR / f"{ticker}.csv"
    if not p.exists():
        return None
    df = pd.read_csv(p, parse_dates=["date"]).sort_values("date")
    if len(df) < 25:
        return None
    daily_ret = df["close"].pct_change().tail(21)
    return float(daily_ret.std() * np.sqrt(252))


def pick_expiration(expirations: list[str], today: pd.Timestamp) -> str | None:
    best, best_dist = None, None
    for e in expirations:
        dte = (pd.Timestamp(e) - today).days
        if TARGET_DTE_MIN <= dte <= TARGET_DTE_MAX:
            dist = abs(dte - 30)
            if best_dist is None or dist < best_dist:
                best, best_dist = e, dist
    return best


def main():
    universe = [t.upper() for t in sys.argv[1:]] or sorted(p.stem for p in DATA_DIR.glob("*.csv"))
    if not universe:
        print(f"No tickers found in {DATA_DIR} -- run local_data_pull.py first.")
        return

    today = pd.Timestamp.now().normalize()
    chain_rows, volhist_rows = [], []
    n_ok, n_skip = 0, 0

    for i, t in enumerate(universe):
        yf_ticker = t.replace(".", "-")  # BRK.B -> BRK-B, same convention as local_data_pull.py
        try:
            tk = yf.Ticker(yf_ticker)
            expirations = tk.options
            if not expirations:
                n_skip += 1
                continue
            exp = pick_expiration(list(expirations), today)
            if exp is None:
                n_skip += 1
                continue
            calls = tk.option_chain(exp).calls
            if calls.empty:
                n_skip += 1
                continue
            calls = calls.copy()
            calls["entry_premium"] = (calls["bid"] + calls["ask"]) / 2.0
            calls = calls[calls["entry_premium"] > 0]
            dte = (pd.Timestamp(exp) - today).days
            for _, r in calls.iterrows():
                chain_rows.append({
                    "act_symbol": t,
                    "entry_date": str(today.date()),
                    "expiration_date": exp,
                    "strike": float(r["strike"]),
                    "bid": float(r["bid"]),
                    "ask": float(r["ask"]),
                    "entry_premium": float(r["entry_premium"]),
                    "entry_iv": float(r["impliedVolatility"]) if pd.notna(r["impliedVolatility"]) else None,
                    "days_to_expiration": int(dte),
                })

            hv = realized_vol_21d(t)
            hist = tk.history(period="1d")
            spot = float(hist["Close"].iloc[-1]) if not hist.empty else None
            iv_atm = None
            if spot is not None and not calls.empty:
                atm_row = calls.iloc[(calls["strike"] - spot).abs().argsort()[:1]]
                if not atm_row.empty and pd.notna(atm_row["impliedVolatility"].iloc[0]):
                    iv_atm = float(atm_row["impliedVolatility"].iloc[0])
            volhist_rows.append({
                "date": str(today.date()), "act_symbol": t,
                "hv_current": hv, "iv_current": iv_atm,
            })
            n_ok += 1
        except Exception as e:
            n_skip += 1
            print(f"  [{i+1}/{len(universe)}] {t}: skipped ({e})", flush=True)
            continue

        if (i + 1) % 25 == 0:
            print(f"  [{i+1}/{len(universe)}] pulled so far: {n_ok} ok, {n_skip} skipped", flush=True)
        time.sleep(0.05)  # be polite to Yahoo's endpoint across ~500 tickers

    if not chain_rows:
        print("No contracts pulled -- nothing written. Check network access and ticker list.")
        return

    LIVE_SCORE_DIR.mkdir(parents=True, exist_ok=True)
    chain_df = pd.DataFrame(chain_rows)
    volhist_df = pd.DataFrame(volhist_rows)
    chain_df.to_parquet(LIVE_SCORE_DIR / "live_calls_chain.parquet", index=False)
    volhist_df.to_parquet(LIVE_SCORE_DIR / "live_volhist.parquet", index=False)

    print(f"\nDone: {n_ok} tickers scored, {n_skip} skipped (no options / no near-30-day expiration / error).")
    print(f"Entry date {today.date()}, {chain_df['expiration_date'].mode().iloc[0]} is the most common expiration.")
    print(f"Saved -> {LIVE_SCORE_DIR / 'live_calls_chain.parquet'} ({len(chain_df)} contracts)")
    print(f"Saved -> {LIVE_SCORE_DIR / 'live_volhist.parquet'} ({len(volhist_df)} tickers)")


if __name__ == "__main__":
    main()
