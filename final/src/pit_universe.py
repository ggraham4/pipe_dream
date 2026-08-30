"""
Point-in-time universe membership -- the survivorship-bias fix (2026-08-28,
Gabe's explicit request after questioning the backtest's implausibly good
numbers). See scripts/local_data_pull_delisted.py's docstring for the full
background.

pit_universe_membership.json (checked in alongside this file) holds, for
each of the 8 standard backtest timepoints, the exact date used to look up
S&P 500 membership (the nearest snapshot at-or-before the timepoint, since
membership changes don't happen daily) and the list of tickers that were
real S&P 500 constituents on that date but are NOT in today's current
universe -- i.e. everything that's since been acquired, delisted, renamed,
or gone bankrupt, and would otherwise be invisibly erased from the
backtest. Source data and full derivation: scripts/pit_universe/ (point-in-
time S&P 500 snapshots from https://github.com/fja05680/sp500, diffed
against the current td_data_local/ ticker list).

This module answers exactly one question: "at timepoint T, what's the
correct candidate universe to score and pick from?" It does NOT restrict
training data -- training on the full historical panel (current + gap
tickers) is fine and good, more coverage of what real market regimes
(including failures) looked like. It only restricts which tickers are
ELIGIBLE TO BE PICKED at each specific timepoint, which is where
survivorship bias actually bites.
"""
import json
from pathlib import Path

_MEMBERSHIP_PATH = Path(__file__).parent / "pit_universe_membership.json"

with open(_MEMBERSHIP_PATH) as f:
    _MEMBERSHIP = json.load(f)

# every gap ticker across all 8 timepoints -- also GAP_TICKERS in the two
# local_*_pull_delisted.py scripts (kept in sync by hand; small, stable list)
ALL_GAP_TICKERS = sorted({t for v in _MEMBERSHIP.values() for t in v["gap"]})


def gap_tickers_for(timepoint: str) -> list[str]:
    """Gap tickers relevant to this specific timepoint (S&P 500 members
    back then, missing from today's universe) -- the ones to ADD to the
    current universe as eligible candidates at this timepoint only."""
    entry = _MEMBERSHIP.get(timepoint)
    return list(entry["gap"]) if entry else []


def allowed_universe_for(timepoint: str, current_universe_tickers, validated_gap_tickers=None) -> set[str]:
    """The full point-in-time-correct candidate set for scoring at this
    timepoint: today's universe (data availability -- e.g. an IPO that
    hadn't happened yet -- already excludes anything not really tradeable
    then) UNION this timepoint's gap tickers (restores what today's
    universe silently erased).

    validated_gap_tickers: optional set/list restricting which gap tickers
    to trust for THIS timepoint -- pass in features_pit.py's
    validate_gap_coverage() output (out/pit_gap_ticker_validation.json's
    "valid_by_timepoint"[timepoint]) to exclude gap tickers whose pulled
    data turned out to be a recycled ticker symbol (a different, unrelated
    company currently trading under that old symbol) rather than the real
    historical constituent. If omitted, every listed gap ticker is trusted
    -- fine for exploring the membership data itself, but backtest_pit.py
    should always pass the validated set once it exists."""
    gap = set(gap_tickers_for(timepoint))
    if validated_gap_tickers is not None:
        gap &= set(validated_gap_tickers)
    return set(current_universe_tickers) | gap


def membership_summary() -> dict:
    return _MEMBERSHIP
