"""
General-purpose point-in-time S&P 500 membership lookup for ANY date, not
just the 8 hardcoded Jan-anchored timepoints pit_universe.py's
pit_universe_membership.json covers.

Built 2026-09-01 in response to two related asks from Gabe: (1) run a
CONTINUOUS rolling backtest (many closely-spaced windows, not 8 sparse
points) with survivorship-bias-correct candidate eligibility at every
single step, not just the 8 points that happen to have a pre-baked
membership.json entry; (2) extend the backtest's reach back to 2008,
which also isn't one of the 8 existing timepoints.

Source data: scripts/pit_universe/sp500_updated.csv -- a DAILY point-in-
time S&P 500 constituent list, 1996-01-02 through 2026-06-30 (2,718 rows).
This is the same underlying source pit_universe_membership.json was
originally built from (github.com/fja05680/sp500), just not previously
shipped in its raw daily form -- pit_universe.py's membership.json only
baked in the 8 specific dates needed at the time. This file makes that
same lookup work for any date.

Usage:
    from pit_universe_continuous import gap_tickers_asof
    gap = gap_tickers_asof("2008-09-15", current_universe_tickers)
    # -> set of tickers that were real S&P 500 members on (the nearest
    #    snapshot at-or-before) 2008-09-15 but are NOT in today's universe

Does NOT replace pit_universe.py / pit_universe_membership.json -- both
are kept, since backtest_pit.py's existing 8-timepoint logic depends on
the validated, hand-reviewed membership.json (gap-ticker coverage has
been spot-checked at those 8 points specifically -- see
backtest/survivorship-bias-correction-results.md Round 1-4). This module
is for the NEW continuous/2008 use case, where checking each step
individually isn't practical -- the trailing-history validation in
features_pit.py's validate_gap_coverage() (MIN_TRAILING_DAYS=380,
recycled-ticker quarantine) is what catches bad data here instead, same
as it always has.
"""
import csv
from pathlib import Path

_SNAPSHOT_PATH = Path(__file__).parent.parent / "scripts" / "pit_universe" / "sp500_updated.csv"

_SNAPSHOTS = None  # lazy-loaded, sorted list of (date_str, frozenset(tickers))


def _load_snapshots():
    global _SNAPSHOTS
    if _SNAPSHOTS is not None:
        return _SNAPSHOTS
    if not _SNAPSHOT_PATH.exists():
        raise FileNotFoundError(
            f"{_SNAPSHOT_PATH} not found -- this file needs to ship alongside "
            f"pit_universe_continuous.py (it's the raw daily S&P 500 membership "
            f"history). Check it was copied to scripts/pit_universe/ on this machine."
        )
    rows = []
    with open(_SNAPSHOT_PATH) as f:
        reader = csv.reader(f)
        next(reader)  # header
        for date_str, tickers_str in reader:
            rows.append((date_str, frozenset(tickers_str.split(","))))
    rows.sort(key=lambda r: r[0])
    _SNAPSHOTS = rows
    return rows


def nearest_snapshot_at_or_before(date_str: str):
    """Returns (snapshot_date_str, frozenset(tickers)) for the latest
    available snapshot at or before date_str, or None if date_str is
    before the earliest available snapshot (1996-01-02)."""
    rows = _load_snapshots()
    best = None
    # rows are sorted ascending; linear scan is fine (2,718 rows, called
    # rarely -- once per rolling-backtest step, not once per price row)
    for d, tickers in rows:
        if d <= date_str:
            best = (d, tickers)
        else:
            break
    return best


def members_asof(date_str: str) -> set[str]:
    """The full set of real S&P 500 constituents as of the nearest snapshot
    at-or-before date_str -- every member, not just the ones missing from
    today's universe. Added 2026-09-01 for a "PIT S&P 500 only" candidate
    pool (Gabe's suggestion, in response to the price-discontinuity bug
    found in continuous_walkforward_pit.py's first run): restricting picks
    to real index members at each point in time should be a much smaller,
    much more vetted pool than the full ~1,650-ticker expanded universe
    (market cap > $2B, no other screen) -- S&P 500 inclusion itself
    requires sustained profitability and liquidity, which should make
    freak micro-cap-style data artifacts (like the CHRD/Chord-Energy
    bankruptcy-reorg discontinuity) much less likely to ever be a
    candidate in the first place, on top of (not instead of) the
    discontinuity fix in price_discontinuity.py."""
    snap = nearest_snapshot_at_or_before(date_str)
    if snap is None:
        return set()
    return set(snap[1])


def gap_tickers_asof(date_str: str, current_universe_tickers) -> set[str]:
    """The set of tickers that were real S&P 500 constituents as of the
    nearest snapshot at-or-before date_str, but are NOT in today's
    current_universe_tickers -- i.e. this date's survivorship-bias gap
    tickers, computed on the fly instead of looked up from a pre-baked
    8-timepoint table."""
    snap = nearest_snapshot_at_or_before(date_str)
    if snap is None:
        return set()
    _, tickers = snap
    return set(tickers) - set(current_universe_tickers)


if __name__ == "__main__":
    # quick self-check when run directly
    import sys
    current = set()  # not meaningful standalone; just exercises the loader
    rows = _load_snapshots()
    print(f"Loaded {len(rows)} snapshots, {rows[0][0]} to {rows[-1][0]}")
    test_date = sys.argv[1] if len(sys.argv) > 1 else "2008-09-15"
    snap = nearest_snapshot_at_or_before(test_date)
    print(f"Nearest snapshot at-or-before {test_date}: {snap[0]}, {len(snap[1])} members")
