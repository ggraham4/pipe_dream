# WO-55 amendment 1: blank-check companies are left out of the dead-vs-listed presence check

Date: 2026-10-09. Gabe chose option (b) of
`final/models/2026-10-09-cwspread-outofera-results.md` (his words: "b").

This amendment is written **before any 2019+ outcome is computed**. It changes one thing in
`final/models/2026-10-09-cwspread-outofera-prereg.md` (sha256 72b06653…c7cc, commit 728740d).
Everything else in the pre-reg stands unchanged.

## The change

The **dead-vs-listed chain-share presence check** (pre-reg §3) is computed with blank-check
companies left out.
- A blank-check company is a Sharadar ticker whose `siccode` in `tickers_master*.csv` is
  **6770**.
- The row used is the same one the check already uses: the ticker's row with the latest
  `lastpricedate`.
- Thin name-dates of such tickers are dropped from both sides, later-delisted and still-listed,
  of this check only.

The check **stays binding at the same bar**: later-delisted share ≥ still-listed share − 5
points. If it fails, the order reports BLOCKED and stops.

## What does not change

All of these stay as in the pre-reg:
- the thin slice and cap2000 (blank checks stay in the pool);
- the signal, decile, metric, NW39 t, shuffle null, offsets and label;
- the 80 dates;
- the L1/L2 link repair;
- the coverage gate (≥ 99% terminal on ≥ 72 of 80 dates);
- the other presence checks (BBBYQ, RADCQ, TXG, pool integrity);
- the WO-55 bars (PASS: M ≥ +0.5%/40d AND t ≥ 3.0 AND both offsets > 0; KILL: M ≤ 0 OR the
  offsets have opposite signs; else MIDDLE);
- the descriptive extras, the trial tally (+1, so 23 / 29), and one run.

The read is still **hold-out read #22, unfitted**. The effect of the SIC 6770 exclusion on the
gap had not been computed when this was frozen.

## Implementation

`run_oos.py` wraps `tl_common.arrival_gate`. It recomputes `dead_vs_listed_chain_share` with
the exclusion above, using the same formula and bar, and then recomputes `phase2_allowed`. No
other part of the gate is touched. The `read` guard requires both this amendment's sha256 and
the pre-reg's sha256 to match their frozen values.
