# Insider and congressional trading vs the composite — pre-registration

**Written 2026-09-23, before any return, IC or backtest number for these
columns was computed.** A separately dated pre-registration, as
`final/src/reset2026/PREREGISTRATION.md` §2 requires for any insider
factor (that file is not edited). Results go in
`2026-09-23-insider-congress-results.md`.

## Data (settled before any test)

**Insiders: SEC "Insider Transactions Data Sets"** (structured Form 3/4/5,
quarterly, 2006Q1-2026Q1, `final/data/edgar/form345/`, 868 MB, free).
The dataset carries **both** `TRANS_DATE` (execution) **and** `FILING_DATE`
(public availability), so the "execution date only" limitation applies to
Alpha Vantage's `INSIDER_TRANSACTIONS`, not to this source. AV's endpoint is
not used: it has no filing date, no transaction code (only A/D, so grants,
option exercises and open-market buys are indistinguishable), and it maps to
today's issuer (empty for dead names).

- Availability timestamp: `FILING_DATE`. A filing is usable on panel date
  `t` iff `FILING_DATE <= t`; the harness enters at `open[t+1]`.
- Issuer join: `ISSUERCIK` -> Sharadar `tickers_master.secfilings` CIK.
  Never `ISSUERTRADINGSYMBOL`, because of reused symbols (Round 11).
- Transactions: non-derivative table, `TRANS_CODE == 'P'` (open-market or
  private purchase) and `'S'` (open-market or private sale) only. Grants
  (A), exercises (M), tax withholding (F) and gifts (G) are excluded.
- Insider: a distinct `RPTOWNERCIK` whose relationship includes Officer or
  Director. Pure 10%-owners are excluded from the primary definitions,
  since funds trade for reasons unrelated to private information about the
  firm. Amendments (4/A) are dropped, so an amended filing is counted once,
  at its original filing date.
- No filing = no trade = **0**, not NaN, for every name in the panel whose
  CIK is known.

**Congress: Alpha Vantage `CONGRESS_TRADES`** carries `transaction_date`,
`notification_date` **and** `filed_date` (median filed-minus-trade lag is
28 days on AAPL), so timing is not the blocker either. Two facts measured
before this registration decide its fate:

1. Coverage by chamber on AAPL, the single most-traded name: Senate from
   2014, House only from mid-2018 (0 House rows 2014-2017, 5 in 2018).
   Pelosi (P000197) has 0 rows before 2020. The nomination era therefore
   holds roughly 15-25 Senate trades per year even on the most popular
   stock, dominated by two senators.
2. 2020-2026 is spent (PREREGISTRATION.md, hold-out section).

**Registered verdict for congress, before any return is looked at:** it
cannot be tested under this project's era rules. It is recorded as a
coverage finding and a forward-only candidate. No congressional IC or
backtest number is computed.

## Trials (k = 2)

| # | column | definition | sign |
|---|---|---|---|
| 1 | `ins_buyers_90` | distinct officer/director owners with >= 1 `P` filed in `(t-90d, t]` | **+1** |
| 2 | `ins_sellers_90` | distinct officer/director owners with >= 1 `S` filed in `(t-90d, t]` | **-1** |

Trial 1 is primary (Lakonishok & Lee 2001; Cohen, Malloy & Pomorski 2012:
purchases carry information, sales mostly do not). Trial 2 is registered so
that a sell-side result can't be reported after the fact as though it had
been planned. The 90-day window is fixed: no 30/180-day variants are run.

Descriptive only, not counted as trials: a cluster flag
(`ins_buyers_90 >= 2`), buy dollar value, and the event study below.

## Era, universe, label

Nomination era 2007-01-02 to 2019-12-31, `eligible_cap150`,
`forward_return_tradable_40`. Same as `ic_weighted_composite.py` and
`screen_new_factors_and_exponent.py`.

## Tests

1. **IC screen:** daily cross-sectional Spearman IC, Newey-West t (lag 39),
   pooled plus odd/even years. Every IC is reported on both raw and
   beta-adjusted (`label - beta_252 * SPY_fwd40`) returns, the theoretical
   model's lens (corrections doc §9).
2. **Sector-neutral IC:** factor residualized on sector dummies per date
   (`composite.neutralize_on_sector`).
3. **Incremental IC:** partial IC of the factor against the return after
   both have been residualized, per date, on the existing composite score
   (equal-weight and IC-weighted `PRODUCTION_WEIGHTS`).
4. **Composite ablation:** composite IC with and without the factor as a
   9th term.
   - Equal-weight: sign as registered, weight 1/9.
   - IC-weighted: weight from `fit_weights` rule, fit on odd years and
     tested on even, and vice versa.
5. **Portfolio + shuffle null** (the project's feature gate, AGENTS.md
   2026-09-16): `decile_volq` on the 9-factor equal-weight composite, 40
   non-overlapping offsets, returns from `outcome_cache.parquet`. Compared
   against 20 draws with the factor **permuted within each date**. Gate:
   beat the 80th percentile of the null on mean excess vs SPY.
6. **Event study:** 40-day return, demeaned on the same date's cap150
   cross-section (raw and beta-adjusted), for the first panel date on or
   after each filing that adds a new officer/director buyer. t clustered
   by calendar month.

## Pass rule (fixed now)

A trial is **nominated** only if all of the following hold:

- the pooled NW t on raw returns has the registered sign and
  |t| >= 2.24 (two-sided 0.05, Bonferroni over k = 2);
- both halves have the registered sign;
- the sector-neutral t has the registered sign;
- test 5 beats the null's 80th percentile.

Anything less is reported as a descriptive result, not a nomination. A
nomination is **not** a promotion into `FACTOR_SIGNS`. That is Gabe's call,
and confirmation would need data the project hasn't seen yet (forward
2026+), since the hold-out is spent.

## Acceptance checks on the built column (Gate A7c: name what should be there)

- `P` counts per year taken straight from the raw SEC tables must match the
  panel's fire rate after the join, within the expected CIK-coverage loss.
  2008-Q4 and 2020-Q1 should show the known insider-buying spikes. Only
  2008 is looked at here, as a data check, not a return.
- Named cases:
  - Jamie Dimon's JPM purchase (Jan/Feb 2016, about 500k shares) must appear
    on its filing date.
  - At least one company that later died must carry buyers before its
    death, which shows the join is survivorship-safe.
- Zero mass: report the `rank_z` value that non-trading names receive.
