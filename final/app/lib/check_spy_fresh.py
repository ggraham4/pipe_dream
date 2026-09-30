"""Retrain pre-check: SPY.csv must have a close for the newest Sharadar day.

Run by the retrain sequences (pit_model.retrain_commands()) right after the
Sharadar top-up. Exit 0 = SPY covers the panel's newest trading day, exit 1 =
it doesn't, with the reason printed.

Why (2026-09-29): build_features_sharadar.py computes relative_strength_20
from scripts/td_data_local/SPY.csv, a yfinance cache that the Sharadar top-up
does not refresh. When SPY lagged the Sharadar panel, every row on the newest
days had a NaN relative_strength_20. current_signal_pit.py's complete-feature
filter dropped them all, and the run died four steps later with a misleading
"no tickers cleared eligibility ... market_cap" error. yfinance also writes
today's bar with a blank close until Yahoo finalizes it, so the check looks
for a non-blank close, not just the date.
"""
from __future__ import annotations

import os
import sys
from pathlib import Path

import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parent))
import paths  # noqa: E402  (plain module, no streamlit import)


def newest_sharadar_day() -> pd.Timestamp | None:
    env = os.environ.get("SHARADAR_PANEL_DIR")
    daily = (Path(env) if env else paths.SHARADAR_DIR / "panel") / "daily"
    months = sorted(daily.glob("[0-9][0-9][0-9][0-9]-[0-9][0-9].parquet"))
    if not months:
        return None
    return pd.read_parquet(months[-1], columns=["date"])["date"].max()


def newest_spy_close(spy_csv: Path) -> pd.Timestamp | None:
    if not spy_csv.exists():
        return None
    spy = pd.read_csv(spy_csv, usecols=["date", "close"], parse_dates=["date"])
    spy = spy[spy["close"].notna()]
    return spy["date"].max() if len(spy) else None


def main() -> int:
    spy_csv = paths.STOCK_DATA_DIR / "SPY.csv"
    sh = newest_sharadar_day()
    spy = newest_spy_close(spy_csv)
    if sh is None:
        print("No Sharadar daily panel months on disk; nothing to check SPY against.")
        return 0
    sh = pd.Timestamp(sh).normalize()
    print(f"Newest Sharadar day: {sh.date()}   newest SPY close: "
          f"{spy.date() if spy is not None else 'none'}")
    if spy is not None and pd.Timestamp(spy).normalize() >= sh:
        print("SPY covers the panel. OK.")
        return 0
    print(
        f"SPY.csv has no close for {sh.date()}. relative_strength_20 would be blank "
        f"for every stock on that day and the signal retrain would drop them all. "
        f"If the SPY top-up step says it refreshed, Yahoo hasn't published the "
        f"close yet (it writes a blank close until then). Retry later, usually by "
        f"the next morning. Stopping here, before the universe, features or signals are rebuilt."
    )
    return 1


if __name__ == "__main__":
    sys.exit(main())
