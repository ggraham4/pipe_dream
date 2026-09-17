# New data sourcing research (2026-09-17)

Gabe asked for new data — constructions from what's already on hand, free/public
sources, and paid vendors worth a hard look — ranked by whether they'd add real,
non-redundant, idiosyncratic signal to the stock buy/no-buy model (XGBoost depth 3,
point-in-time, 40-day hold, no stop-loss) and/or the options premium model (Tweedie
GLM, calls deployed, puts researched-only). This is a candidates list for the
existing IC-screen/walk-forward vetting pipeline, not a backtest — nothing here was
tested.

**Why this matters more than usual right now.** Two findings already on record
should set the bar. First, `DATA-PIPELINE-HANDOFF.md` (Round 11, the last commit on
this branch): once the stock universe was rebuilt honestly point-in-time — fixing a
survivorship-determined eligibility pool, 41 wrong-issuer gap tickers, a look-ahead
price floor, and pre-existing corporate-action contamination — the augmented model's
edge over SPY on 124 walk-forward windows (2007-2026) is **-0.11%/window, t = -0.09**.
Statistically nothing. Second, even before that rebuild, `final/app/README.md`
attributes essentially all of the *previously reported* edge to a low-vol tilt and a
sector bet, both purchasable as ETFs. Read together: the current feature set
(momentum, vol, volume, relative strength, price-level, fundamentals ratios) has not
yet been shown to contain a real idiosyncratic signal on honest data. That raises,
not lowers, the bar for anything new — but it also means this is the right moment to
widen the search rather than keep re-tuning the same eleven features.

Two axes, kept separate per the ask:
- **Likelihood** — how confident should we be that this variable carries signal
  distinct from what the model already implicitly has (momentum/vol/size/sector),
  based on the strength and recency of outside evidence and fit to this universe.
- **Magnitude** — if it works, how big a move in excess return / IC should we
  expect, given known effect sizes elsewhere and this project's small-sample,
  cost-inclusive backtest discipline.

A candidate that's "High/High" isn't automatically first — testability and cost
matter too, which is why the shortlist at the end reorders for that.

---

## Ranked candidates

### 1. Sector/industry-neutralized (cross-sectionally demeaned) features
**Model(s): stock.** Likelihood: **High** · Magnitude: **Medium**

**What it is.** The Sharadar `sector`/`famaindustry`/`sic2`/`industry`/`sic3`/
`sicindustry` classification is already pulled and used for post-hoc attribution,
not as a model input. Construct new features by demeaning the existing
momentum/volatility/relative-strength columns within each ticker's sector or
industry bucket on each date (e.g. `momentum_20_ind_rel = momentum_20 -
median(momentum_20 | sic2, date)`), and optionally add sector/industry as a
one-hot or target-encoded categorical.

**Case for it.** This directly targets the project's own documented confound: the
score-vs-volatility correlation (-0.134) and the Healthcare/Energy/Biotech
overweight are a *sector-level* bet the model backed into implicitly, via features
that happen to correlate with sector membership, not a stock-picking skill. Forcing
the model to rank names *within* their sector/industry bucket is the standard way
factor research separates "which sector to be in" (beta, buy the ETF) from "which
stock within the sector" (the only thing worth paying an ML model for). If nothing
survives sector-neutralization, that's itself a valuable, cheap negative result —
directly answers whether there's any idiosyncratic signal left at all, which is
exactly the open question after Round 11.

**Cost/access.** Zero — Sharadar sector/industry data is already pulled and on
disk (`final/src/fundamentals_features_pit.py`/`build_features_fundamentals_sharadar.py`
lineage). Pure feature-engineering exercise.

**Point-in-time feasibility.** Clean. Sector/industry classification is
slow-moving and known as of the data date; no restatement risk. Use `sic2`/`sic3`
rather than the coarser `sector` for enough buckets to be meaningful without
over-fragmenting the ~1,600-name universe.

**Verdict.** Do this first. It's the cheapest, most direct test of whether the
model has *any* real edge left post-Round-11, and it costs nothing.

---

### 2. Net share issuance / buyback yield from Sharadar SF1 (already paid, unused)
**Model(s): stock.** Likelihood: **High** · Magnitude: **Medium**

**What it is.** `sf1_shares.csv` (already pulled, ARQ+ARY as-reported share counts)
supports a trailing change-in-shares-outstanding feature — net issuance (dilution)
vs. net buyback — that isn't in `FUNDAMENTAL_FEATURE_COLS` today (which has
market_cap/pe/pb/ps/debt-to-equity/roe/roa/margins/growth/rnd_intensity but no
issuance measure).

**Case for it.** Net stock issuance is one of the most replicated anomalies in the
cross-sectional return literature (Fama-French, Pontiff-Woodgate, and follow-ups)
— firms that issue shares underperform, firms that buy back outperform, and the
effect is generally *stronger*, not weaker, in smaller/less-followed names, which
matches this universe (mkt-cap floor ~$500k). It's also mechanically distinct from
price/volume momentum and from the valuation ratios already in the model, so it's a
genuine new axis rather than a repackaged one.

**Cost/access.** Zero — data already licensed and on disk. Needs `shares_outstanding`
(already a `STOCK_CONCEPT`) turned into a trailing % change, point-in-time asof-joined
the same way every other fundamentals feature already is.

**Point-in-time feasibility.** Clean — same `asof_lookup` machinery already used for
every other fundamentals ratio, filed-date keyed (ARQ/ARY, not restated MR*), per
the project's own established discipline (`DATA-PIPELINE-HANDOFF.md` §6.4-ish
concept reuse).

**Verdict.** Strong, cheap, well-evidenced. Build it.

---

### 3. Insider transactions (Form 4) — cluster-buy feature
**Model(s): stock.** Likelihood: **High** (for this universe specifically) ·
Magnitude: **Medium**

**What it is.** Alpha Vantage `INSIDER_TRANSACTIONS` (already connected, zero
incremental cost). Construct a rolling feature: count of distinct insiders buying
in the trailing N days, $ value of net insider buying, and specifically a
cluster-buy flag (≥2 unrelated insiders buying within a short window).

**Case for it.** This is one of the better-matched ideas on this list to the
project's *specific* universe. The academic literature (Lakonishok & Lee 2001
onward) finds cluster insider buys predict 4-8% abnormal returns over 6-12 months,
and — critically — the effect is concentrated in smaller, less-analyst-covered
names precisely because insiders have a bigger informational edge there. This
project's universe (mkt-cap floor ~$500k, deliberately including small/microcaps)
is exactly the population where this signal is reported strongest, unlike, e.g.,
congressional trading (see #10) which skews toward large, liquid names politicians
actually hold.

**Cost/access.** Free, already connected (Alpha Vantage MCP). Fastest path to test
of anything paid on this list.

**Point-in-time feasibility.** Clean if keyed on Form 4 *filing* date (2-business-day
SEC deadline), not transaction date — use filing date as the availability timestamp,
same discipline as the fundamentals asof-join. Coverage will be uneven across ~1,600+
tickers (many microcaps have thin insider activity, which is itself informative —
treat "no recent insider activity" as a distinct category, not missing-as-zero).

**Verdict.** High-priority, free, directly evidenced for this exact universe. Test
immediately.

---

### 4. Liquidity-bucketed options skew / put-call ratio — direct test of the thin-liquidity hunch
**Model(s): options** (primarily; a liquidity-bucketed IV skew feature could also
feed the stock model as a sentiment proxy on optionable names). Likelihood:
**Medium** (testing a real hypothesis, not a guaranteed hit) · Magnitude:
**Medium-High if the hunch is right**

**What it is.** Bucket the options universe already on hand (DoltHub chains,
`options_calls_training.parquet`) by open-interest/volume decile, and check whether
put-call-ratio and IV-skew based signal strength (IC, decile spread) is
concentrated in the thin-volume buckets vs. the liquid ones. Alpha Vantage's
`HISTORICAL_PUT_CALL_RATIO`, `HISTORICAL_VOLUME_OPEN_INTEREST_RATIO`, and
`HISTORICAL_OPTIONS` give an independent, already-connected way to pull the same
kind of series for cross-validation without touching the DoltHub pipeline.

**Case for it.** This is Gabe's own stated hunch — that edge lives in thin-volume
mid-cap options, not liquid large-caps — and there's real published support for the
mechanism: option-implied skew and put-call ratios are documented cross-sectional
return predictors (steep-smirk names underperform ~10.9%/yr risk-adjusted per Xing
et al.-lineage work), and illiquid-options market-microstructure research finds
wider spreads / less efficient pricing specifically where hedging and inventory
costs are highest — i.e., thin names. The honest caveat: the same literature and
this project's own `AGENTS.md` history (illiquid options = high effective
transaction costs, in `buy_no_buy_options_v2`) cut both ways — thin volume could
mean genuine information not yet arbitraged away, *or* it could mean stale,
unexecutable quotes (exactly the "16-50x theoretical value" garbage the team already
found and cleaned out of the puts pipeline). This needs the same richness-ratio /
data-quality discipline already built (`build_pit_puts_cleaned.py`'s pattern)
before trusting any signal from the thin end.

**Cost/access.** Zero net-new — this is a *construction* from data already
licensed (DoltHub) or already connected (AV), just sliced by a liquidity dimension
not currently used to segment the model at all.

**Point-in-time feasibility.** Clean — OI/volume and IV are same-day observable
quantities, no restatement risk, same asof discipline as everything else in this
pipeline.

**Verdict.** This is the single cheapest way to actually answer the open strategic
question the user raised, rather than continue debating it. Do it before spending
money on any paid options-flow vendor (#12 below) that's built on the same premise.

---

### 5. Earnings estimate revisions / standardized surprise (SUE-style)
**Model(s): both** (stock: post-earnings drift; options: IV term-structure/crush
around earnings dates is currently unmodeled). Likelihood: **High** · Magnitude:
**Medium**

**What it is.** Alpha Vantage `EARNINGS_ESTIMATES` + `EARNINGS_CALENDAR` (already
connected). Construct analyst-estimate-revision features (direction/magnitude of
EPS estimate changes in the trailing N days) and a standardized-surprise feature at
each earnings date (actual vs. consensus, scaled by estimate dispersion).

**Case for it.** Post-earnings-announcement drift (PEAD) and estimate-revision
momentum are among the most-replicated anomalies in the literature, distinct in
mechanism from price momentum (it's driven by analyst under-reaction to new fundamental
information, not price trend persistence) and from the point-in-time fundamentals
already in the model (which are levels/ratios, not surprise-vs-expectation). For the
options model specifically, an upcoming-earnings flag plus estimate dispersion is a
natural, currently-absent input — the model has GARCH vol and IV levels but nothing
that anticipates an earnings-driven IV event.

**Cost/access.** Free, already connected.

**Point-in-time feasibility.** Clean if estimate revisions are keyed on the
revision's own timestamp (consensus-as-of-date) rather than a survivorship-prone
"latest consensus" pull — check what AV actually returns for historical estimate
vintages before trusting this blindly; if AV only exposes current consensus with no
historical vintage, flag that as a real limitation per the point-in-time rule and
fall back to earnings-date-only surprise features (still useful, weaker).

**Verdict.** Strong, free, well-evidenced — but verify AV's estimate data actually
has point-in-time vintages before building on it; that's the one thing to confirm
cheaply before committing engineering time.

---

### 6. Open interest / volume-OI ratio in the options model
**Model(s): options.** Likelihood: **Medium-High** · Magnitude: **Medium**

**What it is.** Open interest isn't in the options model's feature list at all —
grepping `options_common.py`/`live_score.py`/`optimizer_backtest.py` turns up
`volume_20` and `log_volume_20` but no `open_interest` anywhere in the repo. Worth
checking whether DoltHub's `option_chain` table already carries an OI column that's
simply never been joined in (a pure construction, zero new cost) before assuming a
new source is needed; if not, Alpha Vantage's
`HISTORICAL_VOLUME_OPEN_INTEREST_RATIO`/`REALTIME_VOLUME_OPEN_INTEREST_RATIO` cover
it for free.

**Case for it.** OI (distinct from volume) is a standard proxy for how much
capital is already committed to a position and for how "crowded" or "fresh" a
contract's interest is — a dimension the Tweedie GLM currently has zero visibility
into. Combined with #4's liquidity-bucketing, a volume/OI ratio can distinguish
"new interest building" from "stale open positions," which is exactly the kind of
positioning signal option-microstructure research treats as informative,
particularly in less liquid names where one large print moves the ratio visibly.

**Cost/access.** Zero-to-free — check the existing DoltHub schema first.

**Point-in-time feasibility.** Clean, same-day observable, no restatement.

**Verdict.** Cheap, plausible, currently a genuine gap in the feature set. Check
the schema before reaching for AV.

---

### 7. FINRA short interest (free, public, not yet integrated)
**Model(s): stock** (secondarily a risk-avoidance input; short interest is also a
component of squeeze-risk sizing an options model could use for puts). Likelihood:
**Medium-High** · Magnitude: **Medium**

**What it is.** FINRA publishes aggregate short interest per security twice
monthly, free, via finra.org (not currently reachable through the AV/Twelve Data
MCP tool lists — would need its own small downloader script, same
run-on-Gabe's-machine pattern already used for Sharadar/DoltHub pulls).

**Case for it.** Recent work on "surprise in short interest" (SUSIR) finds it
negatively predicts cross-sectional returns, and — notably for this project — the
effect is *stronger* among illiquid, volatile, high-information-uncertainty stocks,
which describes a meaningful chunk of this project's small/micro-cap universe far
better than it describes a large-cap index. This is mechanistically distinct from
anything currently in the model (it's informed-short-seller positioning, not
price/volume history).

**Cost/access.** Free, but not zero-effort — data is published 7-9 business days
after each settlement date (not through the connected MCP tools), so this needs a
small scraper/downloader, run on Gabe's machine per the project's existing
network-access pattern for anything blocked from the sandbox.

**Point-in-time feasibility.** Straightforward as long as the *publication* date
(not the settlement date) is used as the availability timestamp — a ~1.5-2 week
lag exists and must be respected exactly like the SEC-filing-date discipline
already used for fundamentals, or this silently becomes look-ahead.

**Verdict.** Good, free, evidence-matched to this universe. Slightly more setup
than a pure MCP call, so rank it just behind the zero-friction items above.

---

### 8. SEC EDGAR filing-event flags (going-concern, auditor change, exec departure — 8-K items)
**Model(s): stock**, specifically as a tail-risk/avoid-blowup input given the
model's no-stop-loss, 40-day-hold design. Likelihood: **Medium** · Magnitude:
**Medium** (asymmetric — more about avoiding disasters than picking winners)

**What it is.** SEC EDGAR full-text search (free) can flag specific 8-K item
types and filing language (Item 4.02 non-reliance/restatement, Item 5.02 executive
departures, "going concern" language, auditor changes) as binary/count features,
distinct from the numeric fundamentals ratios already pulled.

**Case for it.** This project's own universe design deliberately includes
companies that later go bankrupt or get delisted (the whole point of the PIT
survivorship correction), and the model currently has no dynamic exit or stop-loss
to protect against one of those blowing up mid-hold. A distress-flag feature
wouldn't be trying to find more winners — it would let the ranking model
systematically down-rank or exclude names showing early distress language *before*
they enter the pool of live picks, which is a different and probably more
defensible kind of edge than another momentum-adjacent signal (asymmetric downside
protection vs. incremental upside prediction — worth stating explicitly since it's
not directly comparable to the other ideas here on IC terms alone).

**Cost/access.** Free (SEC EDGAR full-text search API), though the NLP/keyword-flag
engineering is nontrivial — this is a "cheap data, real engineering" item, not a
zero-effort one.

**Point-in-time feasibility.** Clean — filing-date keyed by construction, same
discipline as everything else already pulled from SEC EDGAR for fundamentals.

**Verdict.** Worth building, framed correctly (downside protection, not alpha) —
but it's an engineering project, not a quick API pull, so it belongs after the
cheaper items above.

---

### 9. Institutional holdings (13F) net-flow signal
**Model(s): stock.** Likelihood: **Medium** · Magnitude: **Low-Medium**

**What it is.** Alpha Vantage `INSTITUTIONAL_HOLDINGS` (free, connected).
Quarter-over-quarter change in institutional position count/size, with a
"new-initiation cluster" flag (multiple unrelated funds opening positions the same
quarter) as the strongest documented sub-signal.

**Case for it.** There's a real literature here, and "smart money" flow is a
plausible complement to insider buying (#3) — but two structural mismatches with
this project specifically pull the case down from #3's level: (a) 13F filings have
a ~45-day lag and quarterly cadence, awkward against a 40-trading-day (~2-month)
hold — by the time a Q-over-Q change is knowable point-in-time, a meaningful chunk
of the relevant holding period may already be behind it; (b) 13F coverage is
sparser and noisier at the small/micro-cap end of this universe than at the
large-cap end, the opposite of where #3's insider-buying evidence is strongest.

**Cost/access.** Free, already connected.

**Point-in-time feasibility.** Clean if keyed on filing date, not the quarter-end
"as of" date the position reflects (the report is stale by construction — that's a
real, honest limitation to carry forward, not a PIT violation, as long as the
*filing* date is what's used to decide availability).

**Verdict.** Worth a look given it's free, but rank behind insider transactions —
weaker cadence/coverage fit for this specific universe and horizon.

---

### 10. Congressional trading disclosures
**Model(s): stock.** Likelihood: **Low-Medium** · Magnitude: **Low**

**What it is.** Alpha Vantage `CONGRESS_TRADES` / `POLITICIAN_METADATA` (free,
connected).

**Case for it.** Real public interest and some vendor-reported track records
(Quiver Quantitative's own marketing cites congressional portfolios beating the
market), but this needs more skepticism than most items here: coverage skews
heavily toward large, liquid, widely-held names politicians and their advisors
actually trade (the opposite end of this project's universe from where #3's
insider-cluster evidence concentrates), the STOCK Act's 45-day disclosure window is
long relative to the 40-day hold, and — importantly — no independent, peer-reviewed
academic study surfaced in this research confirming durable alpha net of the
disclosure lag; most of what's out there is vendor self-reporting rather than
published research. Treat as speculative/novelty-adjacent rather than
evidence-backed until shown otherwise.

**Cost/access.** Free, already connected — cheapest possible way to find out it
doesn't work, which is itself the argument for testing it rather than paying a
dedicated vendor (Unusual Whales bundles the same congressional-trading data
starting at $50/mo — not worth paying for something already free here).

**Point-in-time feasibility.** Clean if keyed on disclosure/filing date, not
transaction date.

**Verdict.** Weak case, but free and instant to test — low priority, still worth
a quick look before spending real engineering time elsewhere.

---

### 11. News sentiment / retail attention (news, Google Trends, social)
**Model(s): stock**, marginal fit for options. Likelihood: **Low-Medium** ·
Magnitude: **Low**

**What it is.** Alpha Vantage `NEWS_SENTIMENT` (free, connected) as the
lowest-friction option; Google Trends search-volume and Reddit/StockTwits retail
sentiment (free-to-cheap, third-party) as adjacent variants.

**Case for it — and against.** Coverage is genuinely sparse and noisy at the
small/micro-cap end of this universe (the opposite of where large-cap sentiment
data is richest), which cuts against both the "underfollowed = mispriced" theory
*and* signal quality simultaneously — thin coverage means both more room for an
edge and less reliable measurement of it. More importantly, this is close in kind
to the `xrank` label that looked good in-sample and failed badly out-of-hold-out
(-4.28%/yr, 2020-2026) — noisy, attention-driven, easy to overfit. The team's own
stated skepticism of noise-chasing applies here more than almost anywhere else on
this list.

**Cost/access.** Free (AV) to low-cost (Google Trends API, StockTwits API).

**Point-in-time feasibility.** Reasonable — timestamped at publication/query time
— but be wary of any vendor-side "smoothed" or "current" sentiment score without a
historical vintage.

**Verdict.** Weak case relative to its noise risk given this project's own
documented overfitting lesson. Low priority; if tried, hold to an unusually strict
walk-forward bar before trusting it.

---

### 12. Earnings call transcript tone-gap NLP feature
**Model(s): stock**, secondarily options (pre-earnings IV positioning).
Likelihood: **Medium** · Magnitude: **Medium**

**What it is.** Alpha Vantage `EARNINGS_CALL_TRANSCRIPT` (free, connected) as the
raw data; the feature itself needs an LLM/finance-lexicon sentiment pass (e.g.
FinBERT-style scoring) comparing tone in *scripted* remarks vs. the *spontaneous*
analyst Q&A.

**Case for it.** More specific and better-evidenced than generic news sentiment —
published research finds the tone gap between prepared remarks and the
unscripted Q&A carries incremental explanatory power for PEAD beyond either
section alone, which is a genuinely different mechanism (management confidence
under unscripted questioning) than anything currently in the model.

**Cost/access.** Data is free; the NLP scoring pipeline is a real engineering
lift (LLM calls or a trained sentiment model per transcript, at ~1,600+ tickers ×
quarterly cadence) — flag this as "cheap data, real engineering cost," same
category as #8.

**Point-in-time feasibility.** Clean — transcripts are timestamped at the call
date, filed after the fact with no restatement risk.

**Verdict.** Good idea, real literature support, but the engineering cost means it
belongs after the cheaper items above, not because the case is weak but because
it's slower to test.

---

### 13. OPRA-grade options flow / unusual-activity data (paid — Unusual Whales, Cheddar Flow, FlowAlgo, or Cboe DataShop for institutional-grade OPRA tape)
**Model(s): options.** Likelihood: **Medium** (real mechanism, unproven for this
specific universe) · Magnitude: **Medium-High if real**

**What it is.** Trade-level (not just EOD chain snapshot) options flow — large
block/sweep detection, dark-pool prints, real-time OI changes — the kind of
granular positioning data DoltHub's EOD chain export doesn't carry.

**Case for it.** This is the most direct paid instantiation of Gabe's thin-liquidity
hunch: in an illiquid options name, one large directional print is a much bigger,
rarer tell than the same print would be in SPY options, and there's genuine
market-microstructure literature on informed trading showing up first in options
before the underlying, especially pre-news. The realistic cost: Unusual Whales'
consumer tier starts at $50/mo (real-time flow + dark pool + congressional data
bundled — see #10, no reason to pay separately for that piece); full API access
runs materially more (~$750/mo class of pricing was the figure found, treat as
approximate and confirm current pricing before committing), and Cboe DataShop's raw
OPRA-based historical options data is institutional-tier pricing, likely overkill
before the hypothesis is validated cheaply first.

**What would falsify this cheaply first.** Do #4 before this — bucket the options
data *already on hand* (DoltHub) by liquidity and check whether any measurable skew/
put-call signal already shows a liquidity gradient. If #4 finds nothing, a paid
real-time flow feed is very unlikely to rescue the hypothesis (it adds granularity,
not a different underlying mechanism). If #4 finds something, that's the evidence
needed to justify a $50-250/mo trial subscription before any $750/mo API commitment.

**Cost/access.** $50/mo (consumer, real-time flow) up to ~$750/mo (full API) —
confirm current pricing before buying; this research pass did not verify live
pricing beyond a September 2026 web search snapshot.

**Point-in-time feasibility.** Genuinely clean — real-time trade prints are
inherently point-in-time by nature, no restatement risk, unlike almost any other
paid alt-data category. That's a real point in this idea's favor relative to, e.g.,
vendor "current snapshot only" catalogs.

**Verdict.** Don't buy yet. Real mechanism, plausible fit to the stated hunch, but
do the free version (#4) first — it's the correct falsification test and costs
nothing.

---

### 14. Macro series (CPI, Fed funds, unemployment, GDP, Treasury yields)
**Model(s): neither, as currently structured — see caveat.** Likelihood: **Low**
(for the stock model's actual architecture) · Magnitude: **Low**

**What it is.** Alpha Vantage `CPI`, `FEDERAL_FUNDS_RATE`, `UNEMPLOYMENT`,
`REAL_GDP`, `TREASURY_YIELD` (free, connected).

**Case against, more than for.** A macro series is the same value for every
ticker on a given date. The stock model ranks a cross-section of ~1,600+ names on
a single day using a depth-3 XGBoost tree — a feature that's constant across the
whole cross-section that day cannot help the tree *rank* names against each other,
only shift a global threshold, which a tree can't meaningfully use as a splitting
variable in a cross-sectional-ranking setup. The only place this class of data
naturally fits is a market-wide gating/regime layer sitting outside the ranking
model — which is exactly what the HMM regime gate was, and Gabe explicitly retired
it ("we are no longer using the HMM"). Recommending macro series as stock-model
*features* in their current architecture would be recommending something the
model structurally can't use; recommending them as a *new* regime gate would be
reopening a workstream Gabe closed, not proposing new data.

**Cost/access.** Free, already connected, in case a future regime-layer workstream
is revisited on Gabe's own initiative.

**Point-in-time feasibility.** Clean, standard vintage-safe.

**Verdict.** Skip for the stock model as currently built. Not a data-quality
problem — a fit problem with the model architecture. Worth remembering it's there
(free, connected) only if Gabe reopens a regime-gating workstream on purpose.

---

### 15. Satellite imagery / web-scraped consumer alt-data (Orbital Insight, YipitData, Thinknum-class vendors)
**Model(s): stock**, in principle. Likelihood: **Low** · Magnitude: **Low** for
this universe

**What it is.** Foot-traffic (satellite/parking-lot imagery), credit-card panel
spend, web-scraped job postings/pricing — the classic "alternative data" vendor
catalog.

**Case against.** These datasets are built for and priced around large-cap
consumer-facing names (retailers, restaurants, big-box) with a real physical or
web footprint to observe — this project's universe, deliberately including
micro-caps down to a ~$500k floor, is mostly the wrong shape of company for this
data category to say anything at all. Pricing is also a genuine barrier for a
solo project: coverage here suggests a single institutional dataset commonly runs
tens of thousands to low hundreds of thousands per year, and YipitData's
enterprise pricing reportedly starts in the high six figures — several orders of
magnitude past anything else on this list, for a universe fit that's already weak.

**Cost/access.** Prohibitive relative to this project's scale, independent of the
universe-fit problem.

**Point-in-time feasibility.** Vendor-dependent — many alt-data catalogs sell
"current" access only, no historical vintage, which would fail this project's PIT
requirement outright even before the cost problem.

**Verdict.** Skip. Wrong universe, wrong price point, likely wrong PIT
availability too.

---

## Do these first

Favoring free/already-connected/testable-immediately per the brief, in the order to
actually run them:

1. **Sector/industry-neutralized features (#1).** Zero cost, answers whether any
   idiosyncratic signal survives at all post-Round-11 — the single most important
   open question right now.
2. **Net issuance/buyback feature from Sharadar SF1 (#2).** Zero cost, well-evidenced,
   mechanically distinct from everything in the model today.
3. **Insider transaction cluster-buy feature via Alpha Vantage (#3).** Free,
   already connected, and the literature match to this specific
   small/micro-cap-inclusive universe is unusually good.
4. **Liquidity-bucketed options skew/put-call test (#4).** The cheapest possible
   way to actually resolve Gabe's thin-liquidity-options hunch instead of debating
   it — do this before any paid options-flow vendor (#13).
5. **Earnings estimate revisions/surprise via Alpha Vantage (#5)** — but first
   confirm AV actually exposes historical estimate vintages, not just current
   consensus; that single check determines whether this is buildable point-in-time
   at all before investing engineering time.

Everything else on the list is lower priority either because the evidence is
weaker for this specific universe (congressional trades, generic news/attention),
the cost/engineering lift is real even though the data is free (8-K distress flags,
transcript NLP), or it requires spending money that should wait on a free
falsification test first (options-flow vendors). Macro series and consumer
alt-data are flagged as skip for structural (architecture-fit) and cost/fit
reasons respectively, not because the underlying idea is bad in general.
