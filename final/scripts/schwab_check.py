#!/usr/bin/env python3
"""WO-41 acceptance checker for the Schwab collector. Offline: no API calls.

    python final/scripts/schwab_check.py [--data-root DIR] [--panel PATH]

Prints PASS / FAIL / NOT_EVALUABLE for each of the four acceptance tests
(fixed 2026-10-01, see final/models/2026-10-01-schwab-collector.md) and an
informational SPY cross-check against the yfinance cache the live retrain
uses. Exit code: 0 all PASS, 1 any FAIL, 2 otherwise (not enough data yet).
"""
import argparse
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO / "final" / "src"))

from schwab import checks, store                                 # noqa: E402

SPY_CACHE = store.MAIN_ROOT / "scripts" / "td_data_local" / "SPY.csv"


def spy_info(root):
    """Informational: Schwab SPY closes vs the yfinance SPY.csv cache."""
    import pandas as pd
    sc = checks.schwab_closes(root)
    sc = sc[sc["ticker"] == "SPY"]
    if sc.empty or not SPY_CACHE.exists():
        return "SPY cross-check: no data yet"
    y = pd.read_csv(SPY_CACHE)
    dcol = next((c for c in y.columns if c.lower() == "date"), y.columns[0])
    ccol = next((c for c in y.columns if c.lower() == "close"), None)
    if ccol is None:
        return "SPY cross-check: no Close column in SPY.csv"
    y = y.assign(candle_date=y[dcol].astype(str).str[:10],
                 close_yf=pd.to_numeric(y[ccol], errors="coerce"))
    m = sc.merge(y[["candle_date", "close_yf"]], on="candle_date", how="left")
    missing = m[m["close_yf"].isna()]["candle_date"].tolist()
    m = m.dropna(subset=["close_yf"])
    worst = ((m["close"] - m["close_yf"]) / m["close_yf"]).abs().max() if len(m) else float("nan")
    return (f"SPY cross-check (yfinance cache): {len(m)} days compared, worst gap {worst:.4%}; "
            f"days Schwab has and SPY.csv lacks: {missing or 'none'}")


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--data-root", default=None)
    ap.add_argument("--panel", default=str(store.WORKING_PANEL))
    args = ap.parse_args(argv)
    root = store.data_root(args.data_root)
    log = store.PullLog(root / "pull_log.sqlite") if (root / "pull_log.sqlite").exists() else None
    results = checks.run_all(root, args.panel, log)
    for r in results:
        print(f"[{r['status']}] {r['name']}: {r['detail']}")
    print("[INFO] " + spy_info(root))
    statuses = {r["status"] for r in results}
    code = 1 if "FAIL" in statuses else (0 if statuses == {"PASS"} else 2)
    print(f"overall: {'ALL PASS' if code == 0 else 'FAIL' if code == 1 else 'NOT YET EVALUABLE'}")
    return code


if __name__ == "__main__":
    sys.exit(main())
