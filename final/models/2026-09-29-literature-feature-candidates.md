# Literature search: candidate features for the Theoretical model (icw9_seas)

Date: 2026-09-29. Branch `worktree-lit-feature-candidates`. Requested by Gabe.

**This is a literature review, not a trial.** No IC was computed, no screen was
run and no hold-out data was read. Every number in the table comes from a
published paper or a published replication. Each candidate still needs its own
pre-registered nomination-era screen (the usual 7 gates, 2007-2019, cap150, v2
grid) before it can go near the weights.

## 1. Method

1. **Model context.** The live model is `icw9_seas`
   (`ic_weighted_composite.PRODUCTION_WEIGHTS_V9_SEAS`). Its 9 factors are:
   - gross_profitability (weight .48),
   - seas (.19),
   - accruals (-.13),
   - net_issuance (-.11),
   - momentum_12_1,
   - pct_from_high_252,
   - volatility_60,
   - days_to_next_filing_seasonal,
   - short_interest_days_to_cover.

   The composite ranks each factor, gives it a fixed sign and averages with
   weights, so it can only use **cross-sectional**, stock-level variables.
2. **Already tried, not re-proposed:**
   - SUE (forward ledger),
   - io_gap (nominated),
   - asset_growth and book-to-market (wrong-signed),
   - leverage,
   - fcf_yield (null),
   - profitability_trend (wrong-signed),
   - Amihud (null),
   - insider counts (dead),
   - earnings-announcement timing (dead family),
   - industry momentum (no point-in-time industry labels).
3. **Evidence base: post-publication survival.** I screened about 200
   published predictors in the Chen & Zimmermann Open Source Asset Pricing
   replication (`PredictorSummary2024.xlsx`, sheet `full`, long-short
   portfolios).
   - The key column is the **post-publication t-stat**: the same signal traded
     only after its paper came out.
   - This is the best available evidence that a sign does not flip by era.
     McLean & Pontiff (2016) find returns fall by about half after
     publication on average.
   - Many well-known signals fall below t = 1.5 after publication:
     - NOA (0.09),
     - residual momentum (1.37),
     - MAX (0.64),
     - trend factor (0.47),
     - R&D/ME (0.82),
     - cash-based operating profitability (0.92),
     - Piotroski F (1.33),
     - share turnover (0.34).

     None of these is proposed.
4. **Hard filters.** Each candidate must pass all of these:
   - **Buildable from point-in-time data on disk for 2007-2019.** That means:
     - SEP daily OHLCV from 2005,
     - slim SF1,
     - EDGAR 8-K and Form 4,
     - AV options from 2008.
   - **Predicts over roughly 1-3 months**, to match the 40-day hold.
   - **Low overlap** with gross profitability and momentum.
   - **Not a variant** of a factor already in the model or of a dead end.
5. **Confidence calibration.**
   - Base rate: of about 11 new-factor screens this project has run, 3 passed
     nomination (SUE, seas, io_gap).
   - Each of those 3 added only about +0.1 to +0.2 pp/yr out of sample.
   - seas then read t +0.23 on 2020-26.
   - So "confidence" below is my probability that the feature passes the
     project's nomination gates **and** adds positively to icw9_seas. Nothing
     is above 30%.

## 2. Candidates

Ordered by confidence, then by the literature t-stat.

| # | Feature | Type | Coding (as a composite input) | Sign | Hypothesized IC addition (literature statistic as reported; not computed) | Confidence | Citations |
|---|---|---|---|---|---|---|---|
| 1 | **Abnormal volume** (`vol_shock`), high-volume return premium | Price/volume | This is GKM's weekly definition, from SEP:<br>• Take the stock's dollar volume for the last 5 trading days.<br>• Rank it among the stock's last 10 non-overlapping 5-day dollar volumes (1..10).<br>• The raw value is that rank; then signed rank as usual.<br>New family: volume *shocks*. Amihud and turnover measure volume *levels*, which is the opposite construct. | + | These numbers come from the **GKM 1998 working paper**, not the published JF 2001 version: NYSE 1963-96, 20-day hold, size-adjusted long-short.<br>**Weekly formation:**<br>• small caps +0.54%, t 4.80<br>• mid caps +0.47%, t 7.50<br>• large caps +0.38%, t 6.66<br>**Long leg only**, which is what a long-only top-decile book earns:<br>• weekly: +0.40 (t 2.44), +0.27 (t 2.96), +0.21 (t 2.58)<br>• daily: +0.45 (t 2.65), +0.41 (t 4.36), +0.29 (t 3.80)<br>In the weekly sample, most of the premium comes from the low-volume short side.<br>Other properties:<br>• persists to 100 trading days<br>• stronger when the formation-week return is not extreme<br>• not driven by earnings or dividend announcements<br>• found in 41 countries (KOS 2012); a US premium unexplained by factor models (Wang 2021)<br>No post-publication t in the Chen-Zimmermann set. | **30%** | Gervais, Kaniel & Mingelgrin (2001), JF 56:877-919; Kaniel, Ozoguz & Starks (2012), JFE 103:255-279; Wang (2021), JFE 140:325-345 |
| 2 | **Option IV spread / smile slope** | Options | ATM 30-day put IV minus call IV (Yan).<br>**Already coded** as `opt_cw_spread` / `opt_rr25` and **pre-registered in WO-25 Exp B** (cap2000 primary, k=5). It is listed here as the strongest post-publication survivor. It is not a new ask, and it is blocked on the AV data copy. Coverage is optionable names only. | − (put−call) | Chen-Zimmermann long-short:<br>• SmileSlope: in-sample t 8.15; **post-publication t 5.16** (0.85%/mo)<br>• CPVolSpread: post-publication t 3.26<br>• Xing-Zhang-Zhao skew (OTM put): post-publication t 1.2, a weak survivor<br>Cremers-Weinbaum: expensive-call names beat expensive-put names by 50 bp/week. | 30% (blocked) | Yan (2011), JFE; Cremers & Weinbaum (2010), JFQA 45:335-367; Bali & Hovakimian (2009), MS |
| 3 | **Earnings announcement return** (EAR) | Event + price | Sum of (r_i − r_SPY) from day −1 to +2 around the latest 8-K Item 2.02 filing. The filing date is the actual release date, so the feature is point-in-time.<br>Held for 60 trading days after the announcement, then NaN.<br>**Family: SUE/PEAD**, not the dead earnings-timing family, which forecast *future* dates. It is a market-reaction measure; SUE is the accounting-surprise measure. | + | Chen-Zimmermann AnnouncementReturn (equal-weighted): in-sample t 12.75; **post-publication t 7.48** (0.85%/mo).<br>Against it:<br>• Martineau (2022): drift gone for large caps since 2006.<br>• Subrahmanyam (2025, working paper): 2001-24 t 2.18 for all stocks, 1.43 excluding microcaps (the NYSE bottom 20%).<br>For it, here:<br>• cap150 ($150M floor) contains many names below that cutoff.<br>• This project's own SUE passed nomination on 2007-2019 cap150 (t +2.17). | 25% | Chan, Jegadeesh & Lakonishok (1996), JF; Martineau (2022), CFR 11:613-646; Subrahmanyam (2025), SSRN |
| 4 | **Short-term reversal, low-turnover names only** (`str_lowturn`) | Price | r_1m = return over the last 21 trading days.<br>Feature = r_1m for names whose 21-day share turnover is below the cross-sectional median; NaN otherwise.<br>**The median split is my construction.** Medhat & Schmeling double-sort into deciles, finding reversal in low-turnover stocks and short-term *momentum* in high-turnover ones. Restricting to the reversal side keeps one sign. | − (on r_1m) | **The t-stat below is for *unconditional* reversal, not this restricted feature.** Chen-Zimmermann STreversal (equal-weighted long-short): in-sample t 14.21; post-publication t 4.13 (1.63%/mo).<br>Medhat-Schmeling (1963-2018) show the sign depends on turnover.<br>Caveats:<br>• small-cap heavy<br>• most of the effect falls in the first month (about half the 40-day window)<br>• cost-sensitive | 25% | Jegadeesh (1990), JF; Lehmann (1990), QJE; Medhat & Schmeling (2022), RFS |
| 5 | **Revenue surprise** | Financials | Uses SF1 ARQ, point-in-time by filing date.<br>• Revenue per share = revenue / sharesbas.<br>• Take its 4-quarter change, minus the mean 4-quarter change over the prior 8 quarters.<br>• Divide by the sd of those changes.<br>Family: SUE/PEAD. The paper shows it adds to earnings surprise. | + | Chen-Zimmermann RevenueSurprise: in-sample t 5.73; **post-publication t 2.55** (0.36%/mo). The same PEAD-decay caveat as #3 applies. | 15% | Jegadeesh & Livnat (2006), JAE |
| 6 | **Tax-expense surprise** | Financials | (tax_q − tax_{q−4}) / assets_{q−4}.<br>**Needs an SF1 re-pull**: `taxexp` is not in the slim SF1 file. | + | Chen-Zimmermann ChTax: in-sample t 9.10; **post-publication t 2.28** (0.37%/mo), 3-month holding period. | 15% | Thomas & Zhang (2011), JAR |

The "Literature effect" column is what each paper reports: long-short returns
and t-stats in the paper's own units and sample. Few papers report a rank IC,
and converting between the two would be a calculation, so none was done. Ties in confidence are ordered by the headline t in that column.

## 3. Considered and not proposed

- **Macro, central-bank and world-event variables.** A Fed decision or a GDP
  print is the same number for every stock on a given date, so it cannot
  change a cross-sectional rank. Such variables can only enter as stock-level
  sensitivities (betas), and rate-sensitivity betas are already a COO dead end
  (R14: 45% of the effect came from 2019). They would belong in a timing or
  regime layer, which is a separate question.
- **Dividend-month premium.** Hartzmark & Solomon (2013); Chen-Zimmermann
  DivYieldST post-publication t 9.72.
  - **The 40-day label is a price return that excludes dividends.**
    `build_outcome_cache.py` reads split-adjusted `close` from
    `scripts/td_data_sharadar/`; for example, KO closes at 20.77 on
    2005-01-03, which is split-adjusted only.
  - The ex-dividend price drop therefore counts against dividend payers in the
    label, so the literature's sign does not carry over.
  - See §4.
- **"Lazy prices"** (Cohen, Malloy & Nguyen, JF 2020): year-over-year 10-K
  text similarity. The NBER abstract reports up to 188 bp/mo alpha from
  going long non-changers and short changers. Not proposed, because it fails
  the "confident it is reproducible" bar:
  - it has no Chen-Zimmermann replication;
  - the one independent replication found (S&P 100, 2009-26, GitHub) was null;
  - it needs a full-text EDGAR pull.
- **Pairs-trading momentum** (Chen et al. 2019, MS). The authors show it is
  mostly short-term reversal plus one-month industry momentum. Short-term
  reversal is row 3, and industry momentum has no point-in-time labels here.
- **Analyst-based signals** (revisions, dispersion, earnings streaks), and
  **13F / institutional ownership**. There is no point-in-time analyst data
  for backtests; AV estimates are live-only. 13F was not checked for
  2007-2019 coverage.
- **Low-risk family** (MAX, idiosyncratic volatility, beta). `volatility_60`
  already has an IC near 0 here, and MAX falls to post-publication t 0.64.
- **Iterations of existing factors** (cash-based operating profitability, ROA,
  net payout yield, external financing). These overlap gross profitability
  and net issuance; the task was new information, not re-cuts.

## 4. Note on the label

The 40-day label excludes dividends by design (`DATA-PIPELINE-HANDOFF.md`
§6.3). That is why dividend-timing features are excluded above.

## 5. Suggested next step

If the COO approves, run rows 1 and 4 first. Both are price/volume only, so
each is buildable from SEP in the io_gap pattern.

1. Pre-register each one separately.
2. Run the 7-gate nomination screen: 2007-2019, v2 column c, cap150, h=40.
3. Compare against **icw9_seas**, not icw8.

Rows 3 and 5 belong to the SUE/PEAD family, whose forward ledger has not matured,
so the COO should decide on family trial counts first. Row 2 is already
queued. Row 6 needs an SF1 re-pull.

## Sources

- Chen & Zimmermann, Open Source Asset Pricing: https://github.com/OpenSourceAP/CrossSection (`SignalDoc.csv`, `Signals/pyCode/StataComparison/PredictorSummary2024.xlsx`)
- Gervais, Kaniel & Mingelgrin working paper (Tables 2-4, 7): https://rodneywhitecenter.wharton.upenn.edu/wp-content/uploads/2014/04/9901.pdf
- Kaniel, Ozoguz & Starks (2012): https://ideas.repec.org/a/eee/jfinec/v103y2012i2p255-279.html
- Wang (2021): https://ideas.repec.org/a/eee/jfinec/v140y2021i1p325-345.html
- Medhat & Schmeling (2022): https://openaccess.city.ac.uk/id/eprint/31278/
- Martineau (2022): https://ideas.repec.org/a/now/jnlcfr/104.00000122.html
- Subrahmanyam (2025) summary: https://anderson-review.ucla.edu/is-post-earnings-announcement-drift-a-thing-again/
- Cohen, Malloy & Nguyen, Lazy Prices: https://www.nber.org/papers/w25084
- Lazy Prices S&P 100 replication: https://github.com/iqueipopg/lazy-prices
- Cremers & Weinbaum (2010): https://ideas.repec.org/a/cup/jfinqa/v45y2010i02p335-367_00.html
- Chen, Chen, Chen & Li (2019): https://ideas.repec.org/a/inm/ormnsc/v65y2019i1p370-389.html
