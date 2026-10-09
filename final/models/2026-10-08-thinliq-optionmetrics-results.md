# WO-52 results: thin-liquidity probe on OptionMetrics (WO-37 arms, real labels)

When these outcomes were computed, the pre-registration and the amendment were frozen by sha256. Neither had been committed. The WO-37 pre-registration is `final/models/2026-10-01-thin-liquidity-prereg.md` on origin/integration, sha256 ce6caf89…acd7. The amendment is `final/models/2026-10-08-thinliq-optionmetrics-amendment.md`, sha256 a9a1c8c1…98cf, frozen at 2026-10-08T20:51:42Z. LEDGER.md and COO.md log both hashes. Commits are queued in PUSH-PLAN-wrds-2026-10-08.md.

Code fix (not a rule change): the runner's `--phase2` guard used to require both docs to be tracked in `git ls-files`. It now requires each doc's sha256 to match the frozen value. The cross-check-pass requirement and the original WO-37 guard still apply. The WO-37 harness itself (`final/src/thinliq/`) runs unchanged from a read-only `git archive` of origin/integration.

Window: 2008-01-02 to 2018-12-19, 133 monthly dates. No date from 2019 onward is read, and nothing is fitted. Fix cycles used: 0 of 3.

## Arm 1 (primary; it sets the verdict): exclude the bottom decile of `opt_cw_spread`, thin slice

| # | Criterion | Value | Bar | Pass |
|---|---|---|---|---|
| S1 | M vs signal-shuffle null p80 | **+2.739%/40d** vs p80 +0.122 (null median +0.003) | M > p80 and M > 0 | yes |
| S2 | NW lag-39 t | **12.17** (lag-2 t 7.23 is descriptive) | ≥ 3.75 | yes |
| S3 | Economic floor | +2.739% | ≥ +1.0% | yes |
| S4 | Sector-neutral | M +1.918, t 10.01 | M > 0 and t ≥ 3.0 | yes |
| S5 | Halves (odd / even / first / second) | +2.81 / +2.68 / +2.63 / +2.84 | all > 0 | yes |
| S6 | LOYO minimum; largest year's share | min +2.49 (drop 2015); max share 17.4% (2015) | min > 0; share ≤ 45% | yes |
| S7 | Offsets (even dates / odd dates) | +2.81 / +2.67 | both > 0 | yes |
| S8 | Size and vol removed | M +2.571, t 10.94 | M > 0 and t ≥ 3.0 | yes |

None of the kill triggers K1 to K6 fired. **Verdict under the WO-37 rules: PASS.** WO-37 §3 treats a PASS as a nomination, not an admission. The next step it names is a pre-registered test of the screen on the live composite's own long book.

Calibration of the rule on shuffled labels (100 seeds, thin slice): PASS 0%, KILL 94%, MIDDLE 6%. Under shuffled labels, M has sd 0.158% and the lag-39 t has sd 1.44. The real t of 12.2 is about 8 null sd out.

Descriptive results, not judged:
- Cap2000 on the same dates: M +1.151, t 6.08. The effect is larger in the thin slice, as WO-37 hypothesised.
- **Open-interest terciles inside the thin slice: thinnest +1.18, middle +1.76, thickest +4.41.** Inside the slice the effect grows with option liquidity. This is the opposite of the "fewer arbitrageurs" story. The best reading is that the CW-spread effect is real and stronger in smaller names, not that it is a thin-quote effect.
- COO post-hoc checks on the exact Arm 1 pool (`coo_reversal_check.py` → `coo_reversal_check_DESCRIPTIVE.json`, built via `run_arm1.load_frame`):
  - **Independent re-derivation: M = +2.7394%**, which matches arm1_results.json.
  - Dropping truncated (delisting-path) labels gives M = +2.695%. Truncated labels are 0.58% of the bottom decile and 0.42% of the rest, so the result is not driven by delisting labels (the WO-51 terminal-treatment gap).
  - Residualising on the 21-day return gives +2.701. Residualising on the 5-day and 21-day returns gives +2.482. The median Spearman correlation between the signal and the 21-day return is −0.08. **So the result is not a short-term-reversal or stale-quote artefact.**

## Arm 2 (secondary; it cannot create a pass): cash-secured 0.30-delta puts, thin slice

| Set | Excess / yr | Odd / even | LOYO min | Positions | Assigned |
|---|---|---|---|---|---|
| quoted | **−8.76%** | −12.4 / −5.8 | −11.2 | 59,800 | 28.5% |
| fillable (OI ≥ 50, bid size ≥ 5) | **−6.99%** | −10.7 / −3.9 | −9.5 | 33,218 | 29.6% |

The strict fillable set has 0 cycles, because sizes are not populated. **Verdict: DEAD.** Hand checks pass, including the split and delisting settlement. The named checks pass: ATPAQ and WAMUQ.

Capacity and stale quotes, both descriptive: a median of 136 entries per month fit within volume, about $11.5M of collateral per month. 71% of positions had zero volume on the entry date, and 13% had never traded.

## Trial tally

The options family goes 20 → 22, or 26 → 28 if WO-36 is counted. Arm 1's t of 12.2 survives any multiple-testing correction at this family size.

## COO verdict

**Arm 1: ITERATE, as a nomination.** Gate A passes: the thin pool includes dead names, the named dead names are present, entry is at the next open, and the placebo fails as required. The arm passes all 8 pre-registered criteria by a wide margin. Two cautions:
1. "Thin" is not the mechanism; see the terciles above.
2. `opt_cw_spread` inside the cap150 long book is a certified dead end (WO-36). So this edge lives in smaller names that the current cap150 book doesn't hold.

The cheapest decisive next test is a fixed-rule, unfitted read of the same Arm 1 screen on OptionMetrics for 2019-01 to 2025-08. Every rule would be frozen, so this counts as an unfitted hold-out read, which is allowed and logged. After that comes a pre-registered down-cap long-book test.

**Arm 2: DEAD.** Selling puts in thin names loses 7 to 9%/yr after honest fills.
