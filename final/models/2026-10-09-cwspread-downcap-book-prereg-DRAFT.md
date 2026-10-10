# DRAFT (not frozen, not launched): opt_cw_spread avoid-screen in a down-cap long book

Status: **draft for the COO and Gabe.** Nothing has been computed for it. Written 2026-10-10
after WO-55 passed: the thin-slice avoid screen gave M +2.36% per 40 days, t 5.9, out of era. If
launched, it becomes its own trial (options family +1) with its own frozen pre-reg.

## Question

The avoid screen works on equal-weight pools of non-cap2000 names. Does it improve an actual
long book that holds such names?

WO-36 already showed it does **not** help the cap150 live book. The open question is a book
built where the edge lives.

## Proposed design (for discussion, every item open)

**Base book.** The current composite (`icw5_seas`, frozen weights, v2 col c, h = 40) ranked
inside a down-cap universe.
- Candidates: (i) the thin slice itself, or (ii) cap500.
- The selection, top-N and rebalance follow the live book's construction, unchanged.

**Variant.** The same book, after first removing names in the bottom decile of `opt_cw_spread`
within that date's eligible pool.
- The decile, the signal build and the OptionMetrics store are exactly as in WO-52/WO-55.
- Names with no chain are not removed. The screen only acts where a signal exists.

**Eras.**
- Primary in-era: 2008-2018, on the WO-52 store.
- Then one unfitted read of 2019-01 to 2025-08 on the WO-55 store, as a new hold-out read
  number.

**Metric.** Variant book minus base book, in %/yr net of the same costs.
- Paired null: random 10% removal with the same counts, p80, per the small-weight bar
  (2026-10-07).
- Also: the 40 time splits, LOYO, and both offsets.

**Proposed bars (to be set by the COO):**
- PASS: book delta > paired-null p80 AND > 0 in at least 30 of 40 splits AND LOYO min > 0.
- KILL: delta ≤ 0.

## Known caveats to settle before freezing

- **Survivorship.** The reset2026 cap500/cap150 grid is survivorship-selected (2026-09-22 caveat).
  Use `downcap_universe_v2` flags, which include delisted names.
- **Capacity and costs** in thin names. The book's trading costs need a down-cap cost model.
  This test is about the stock side only.
- **Chain coverage.** About 80% of thin names have a kept chain. The screen can't act on the
  other 20%.
- **WO-36 overlap.** This must be framed as a down-cap book test, not a re-test of cw_spread in
  the cap150 book (a certified dead end).
