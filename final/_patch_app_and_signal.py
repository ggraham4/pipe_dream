"""Round 11c: stop the app quoting a backtest that no longer exists, and
stop current_signal_pit.py claiming a screen it did not run.

TWO FIXES, BOTH THE SAME CLASS OF PROBLEM -- a line of text asserting
something that is not true of the run that produced it.

1. current_signal_pit.py prints:

       Point-in-time mid-cap+ floor (market_cap >= $2,000,000,000,
       close > $10): 1606/2227 tickers eligible today

   On --universe pit that floor DOES NOT RUN. Eligibility comes from
   pit_universe.parquet, which screened `daily.marketcap` and `closeunadj`
   as of the date. The printed line names two different quantities: the
   panel's `market_cap` (= close x sharesbas) and a split-adjusted close.
   Both are the wrong numbers, and the count beside them is real -- which
   is what makes it believable.

2. app/app.py line ~518 hardcodes:

       "Backtested $10k -> $214,606 vs. SPY's $53,306 over 123
        non-overlapping 40-day windows, 2007-2026"

   That result came from the pre-Round-11 universe: the pool missing a
   third of the eligible early names, 89% of them dead, and excluding
   Apple, Amazon and NVIDIA via the split-adjusted price floor. It is not
   a pessimistic or optimistic estimate of the current strategy; it is a
   measurement of a different, defective dataset. Serving clean picks
   beside it is worse than serving either alone.

   This does not hardcode replacement numbers. It READS the current
   walk-forward result and writes the figures that file actually contains,
   so the claim cannot drift from the run again.

    python3 patch_app_and_signal.py
"""
import json
import re
from pathlib import Path

import numpy as np

ROOT = Path(__file__).resolve().parent
FINAL = ROOT if (ROOT / "out").is_dir() else ROOT.parent
RESULTS = FINAL / "out" / "continuous_walkforward_pit_augmented_pit_realistic_tradable.json"
SIGNAL = FINAL / "src" / "current_signal_pit.py"
APP = FINAL / "app" / "app.py"


def figures():
    d = json.load(open(RESULTS))
    r = [w for w in d["results"]
         if w.get("model_return_pct") is not None
         and w.get("spy_return_pct") is not None]
    m = np.array([w["model_return_pct"] for w in r], float)
    s = np.array([w["spy_return_pct"] for w in r], float)
    ex = m - s
    cm, cs = float(np.prod(1 + m / 100)), float(np.prod(1 + s / 100))
    t = ex.mean() / (ex.std(ddof=1) / np.sqrt(len(ex)))
    return {
        "n": len(r), "beat": int((m > s).sum()),
        "model": 10000 * cm, "spy": 10000 * cs,
        "ex": ex.mean(), "t": t,
        "first": r[0]["timepoint"][:4], "last": r[-1]["timepoint"][:4],
    }


def patch_signal():
    s = SIGNAL.read_text()
    old = '''    print(f"Point-in-time mid-cap+ floor (market_cap >= ${MIN_MARKET_CAP:,.0f}, close > ${MIN_PRICE:.0f}): "'''
    if old not in s:
        # find whatever form it takes and report rather than guess
        hits = [l for l in s.splitlines() if "mid-cap+ floor" in l]
        print(f"  SIGNAL: anchor not found. Lines mentioning the floor:\n    "
              + "\n    ".join(hits))
        return False
    i = s.index(old)
    j = s.index("\n", s.index(")", s.index('"', i + len(old))))
    block = s[i:j]
    new = ('    if UNIVERSE != "pit":\n    ' + block.replace("\n", "\n    ")
           + '\n    # On the pit path the floor above does not run; the PIT\n'
             '    # universe line printed earlier is the real screen.')
    s = s[:i] + new + s[j:]
    SIGNAL.write_text(s)
    print("  SIGNAL: floor message now only prints when the floor actually runs")
    return True


def patch_app(f):
    if not APP.exists():
        print(f"  APP: {APP} not found")
        return False
    s = APP.read_text()
    pat = re.compile(r'"Backtested \$10k[^"]*"', re.S)
    m = pat.search(s)
    if not m:
        print("  APP: hardcoded backtest string not found; check manually")
        return False
    print(f"  APP: replacing -> {m.group(0)[:90]}...")
    new = (f'"Backtested $10k -> ${f["model"]:,.0f} vs. SPY\'s ${f["spy"]:,.0f} over '
           f'{f["n"]} non-overlapping 40-day windows, {f["first"]}-{f["last"]}, on the '
           f'Round 11 point-in-time universe. Excess return vs SPY averages '
           f'{f["ex"]:+.2f}% per window (t={f["t"]:+.2f}) -- not distinguishable from '
           f'zero. Earlier figures on this line came from a survivorship-contaminated '
           f'universe and have been withdrawn."')
    s = s[:m.start()] + new + s[m.end():]
    APP.write_text(s)
    print("  APP: replaced with the figures from the current results file")
    return True


if __name__ == "__main__":
    f = figures()
    print(f"current walk-forward: {f['n']} windows {f['first']}-{f['last']}, "
          f"beat SPY {f['beat']}")
    print(f"  $10k -> model ${f['model']:,.0f}   spy ${f['spy']:,.0f}")
    print(f"  excess {f['ex']:+.3f}%/window, t={f['t']:+.3f}\n")
    patch_signal()
    patch_app(f)
    print("\nAlso check app.py's OTHER performance line (~186):")
    print("  it reads df['beat_spy'] from whichever results JSON the app loads.")
    print("  Confirm that is continuous_walkforward_pit_augmented_pit_realistic_")
    print("  tradable.json and not a pre-Round-11 file.")
