# Session handoff — 2026-09-22

**For a human colleague or a future AI assistant picking this up cold.** Read
`final/models/2026-09-19-factor-composite-reset.md` first for the full
methodology (the 9-factor composite, the survivorship-bias audit, the
reproduction sequence) — this document covers everything that happened
**after** that one was written, brings the picture current, and lists what's
actually open. It does not re-explain the composite's construction; go there
for that.

Branch: `worktree-factor-composite-reset` (all work below is committed and
pushed there). **Not merged to `main`** — see "What's not done" below, this
is the single most important thing for whoever picks this up next.

---

## 1. The blend replaced the composite as the app's primary signal

Same day as the reset doc, later: Gabe explicitly asked for the composite +
q75 blend to be promoted to "front and center" and for the prior q75/xrank
comparison UI to be retired — given twice, after the caveats were laid out in
full and he confirmed he wanted to proceed anyway. That's documented inline
in `current_signal_blend.py`'s module docstring and in the app itself (a
warning banner on the Today's Picks tab), not just here.

**Construction**: `blend_score = mean(rank_z(composite_9factor), rank_z(q75_score))`,
50/50, zero fitted parameters, on the cap2000 (q75's own) universe,
`decile_volq` portfolio. Backtest (`blend_q75.py`,
`out/reset2026/blend_q75_report.json`): **+1.54%/yr excess vs SPY**, beats
both components individually (q75 alone +0.35%, composite alone +0.54% on
this same universe/construction), beats its matched null 100/100 draws, and
— the genuinely interesting part — **survives dropping 2020 from LOYO
without flipping negative** (+0.24%/window → +0.06%/window), unlike the
standalone composite's cap150 result, which flips to -2.05%/yr on that same
test.

**The caveats that go with it, restated because they matter for anyone
reading the app**: this is a SINGLE-GRID backtest (q75's score cache has
only one cadence, not the 40-offset average every other number in this
project gets), it still shows **negative excess vs SPY in absolute terms**
on the 2020-2026 hold-out (-0.36%, least-bad of three constructions tested,
not a winner), and the construction tested isn't what either component model
actually ran before this promotion (q75's real deployed book is 5
concentrated picks, not the ~160-name `decile_volq` book used here). None of
that changed — it was promoted anyway, on explicit instruction, with the
context preserved rather than smoothed over.

**App changes** (`final/app/app.py`, `final/app/lib/blend_model.py`,
`final/src/current_signal_blend.py`):
- Stock section collapsed from 7 tabs to 3: Today's Picks, Query a Ticker,
  Universe. Removed: the q75/xrank two-column comparison, Sector Bets, Model
  Weights, Backtest & History, and the standalone composite-only candidate
  tab (~900 lines net removed from `app.py`).
- Overview tab's stock section now shows the blend, not q75.
- `current_signal_blend.py` scores q75's **existing cached checkpoint**
  fresh (no retrain) and blends it with the composite — this is why it's
  fast (~15s) and why it depends on `out/models/xgb_pit_augmented_model.json`
  already existing.
- **Not touched, on purpose**: the Data & Updates tab still lists q75/xrank
  checkpoint freshness — the blend's live scoring still loads q75's cached
  model as an ingredient, so that pipeline still needs to run.

## 2. Query answers were uninformative — fixed

Gabe's report: "not a current pick, could be either eligible-but-unranked or
ineligible" was useless without knowing which. `current_signal_blend.py` now
writes a third output, `current_signal_blend_full.csv` — **every** name
scanned that day (2,289, not just the 165 picks), each tagged with an exact
`status`: `PICK`, `ELIGIBLE_NOT_PICKED` (with its real blend score and exact
rank within its own volatility quintile, e.g. "143 of 331, needed top 33"),
`ELIGIBLE_NOT_SCORED`, or `INELIGIBLE_TODAY`. `blend_model.query_tickers`
was rewritten around this file. Verified live: AAPL and TSLA both resolve to
`ELIGIBLE_NOT_PICKED` with real ranks; a nonexistent ticker resolves to
`NOT SCANNED`, not silently blank.

## 3. "Retrain ALL models" was slow — found the real bottleneck, fixed it

Timed every step of the one-click refresh individually:

| step | before |
|---|---|
| `build_pit_universe.py` | 25s |
| `build_features_sharadar.py` | 56s |
| **`build_features_fundamentals_sharadar.py`** | **2:42** |
| `current_signal_pit.py` (both signals) | 26s |

Root cause: that one step called `fundamentals_features_beta.process_ticker`
once per ticker (4,011 calls), and each call did up to 14 separate
`pd.merge_asof` calls internally (one per SF1 concept) — 56,000+ individual
merge_asof calls, almost entirely per-call overhead against a fact table
that's tiny in actual data volume.

**Fix**: rewrote `build_features_fundamentals_sharadar.py` as 14 GLOBAL
`merge_asof(..., by="ticker")` calls — one per concept, across all tickers
at once — instead of one call per ticker per concept. Same pattern already
used elsewhere in this project for the identical PIT-join shape
(`sweep/issuance.py`, `reset2026/quality_factors.py`). Formulas are
transcribed line-for-line from `process_ticker`, not redefined, and
`fundamentals_features_beta.py` itself — imported by 23 other files — was
**not touched**.

**Validated, not assumed**: saved the old script's freshly-built output as
ground truth, ran the new version, and added a `--verify-against` mode that
merges old and new on (ticker, date) and asserts every one of the 14
`FUNDAMENTAL_FEATURE_COLS` agrees (NaN positions included) on all
12,270,047 shared rows. Result: **VERIFY PASS, zero mismatches.** Measured:
**2:42 → 59s**.

Also wired `blend_model.retrain_commands()` into the "Retrain ALL models"
button — before this fix, a full retrain didn't refresh the blend at all
(it only reran the q75/xrank pipeline), so Today's Picks could go stale even
right after a full retrain. Must run after `pm.retrain_commands()`: the
blend scores q75's freshly-retrained checkpoint and reads the
freshly-rebuilt fundamentals panel.

## 4. Meta-model roadmap — a 3-tier plan, tier 1 done

Gabe's framing: the composite/blend should be one input into a higher-level
model eventually, not necessarily the final answer, but the sequencing
should go cheapest-and-least-fit first so this doesn't reproduce the
overfitting trap the whole 2026-09-18 reset was built to escape.

1. **Zero-fit blend of composite + q75 — DONE**, this is section 1 above.
2. **Low-dimensional pre-specified regime gate** (bull/bear, vol threshold)
   — NOT STARTED. **Flagged, not vetoed**: this project already ran a
   similar idea (the 2-state HMM on SPY returns blending two models,
   `regime_signals_beta.py`) and it was retired on Gabe's explicit
   instruction ("we are no longer using the HMM"). The specific reason
   beyond that one line isn't recorded anywhere accessible to this session —
   **ask Gabe why it was dropped before building a new version of the same
   idea.**
3. **Sparse, heterogeneous-effect events** (Fed surprises, geopolitical
   shocks, market-moving news) — NOT STARTED. Needs pooling across stocks
   reacting to each event (not across events) to avoid the same
   data-scarcity trap — one Fed decision is ~2,000 stock-level reactions
   with their own characteristics as inputs, not one data point. Alpha
   Vantage's `NEWS_SENTIMENT` endpoint is available and is the concrete
   starting point.

Full detail and the actual blend backtest numbers: `PREREGISTRATION.md`'s
"Future avenues" section, `final/src/reset2026/blend_q75.py`. Also saved to
memory: `project_meta_model_roadmap.md`.

## 5. Data-sourcing decision, 2026-09-22 — insider data and options liquidity

Resolves the two items marked "source TBD" / blocked in
`project-data-sourcing-priorities` (the 2026-09-17 approved data-sourcing
list, items #3 and #4).

**Insider cluster-buy feature (#3): use SEC EDGAR Form 4, NOT Alpha
Vantage.** Gabe's pitch, and it's correct — checked this earlier in the
project (see `project_thin_liquidity_options_edge_idea.md`'s sibling
finding): AV's `INSIDER_TRANSACTIONS` has **no filing-date field**, which
breaks point-in-time discipline outright (this project's single most
load-bearing methodological rule), and it's **current-universe-only**,
reintroducing the exact survivorship bias this project spent Rounds 1-11
fixing. EDGAR Form 4 filings are free, have real filing dates, and cover
delisted/historical companies. **Not started** — next concrete step if this
gets picked up: a `sharadar`-style pull script
(`final/scripts/edgar_form4_pull.py` or similar, run directly by Gabe per
this project's standing network-access convention) that lands
`(ticker, filed_date, insider_role, transaction_type, shares, price)`
rows, joined point-in-time the same way `sweep/issuance.py` joins
`sf1_shares.csv`.

**Liquidity-bucketed options feature (#4): buy Alpha Vantage's $49.99/month
plan for ONE month, after a free check.** The free check was run this
session and **passed**:
- `HISTORICAL_VOLUME_OPEN_INTEREST_RATIO` for `TXG` — the exact ticker
  already confirmed **absent** from the project's own DoltHub options data
  (`project-thin-liquidity-options-edge-idea` memory) — returned real,
  contract-level data for every strike/expiration on 2026-09-08, with
  genuine thin-liquidity signatures (`0.00000000` ratios, `null` where a
  contract had zero volume that day, small nonzero values elsewhere — not a
  data outage, an actually-thin market).
- `HISTORICAL_PUT_CALL_RATIO` for `TXG` on 2021-06-15 (real historical
  depth, not just current data) returned clean, sensible values varying by
  expiration (0.0 to 1.0).
- **One open question, not yet resolved**: this endpoint returns a
  volume/OI **ratio**, not raw volume and open interest as separate
  numbers. Fine for ratio-based liquidity bucketing; worth checking whether
  AV exposes the raw counts separately if the eventual construction wants
  them.
- **One caveat on the check itself**: run through Claude's own connected AV
  MCP integration, not Gabe's personal account — strong evidence the data
  exists and is queryable at whatever tier that connector uses, not a
  100%-certain guarantee his own key behaves identically once purchased.

**Not started**: the actual purchase (Gabe's decision/action, not something
this session can do), and the pull script once purchased.

---

## What's not done — read this before assuming anything below is live

**The branch is not merged to `main`.** Every commit referenced in this
document is on `worktree-factor-composite-reset`, pushed to the remote.
Direct pushes to `main` were attempted twice this session
(`git push origin worktree-factor-composite-reset:main`) and both were
blocked by **Claude Code's own safety classifier** ("Merge Without Review")
— not a project permission setting, a harness-level guardrail that doesn't
respond to in-conversation confirmation. Gabe needs to either merge it
himself (`git push origin worktree-factor-composite-reset:main` from his own
terminal, or the PR link from the push output) or explicitly adjust his
Claude Code permission settings if he wants an assistant to do it directly
in the future.

**Also worth knowing**: committing the app changes required syncing this
branch up to the actual current working-tree state of `app.py`/`pit_model.py`
the first time, which pulled in ~460 lines of **pre-existing, previously
uncommitted work** (sector-enrichment views, current Sector Bets/Model
Weights implementations) that predates this session and was never reviewed
line-by-line by any assistant — see the commit `24e3b23` message for the
exact diff breakdown. Separately, this branch also brought the entire
`sweep/` research package (Rounds 12-20, ~70 files) into git **for the first
time** — it had never been committed to any branch before, only sitting in
the working directory — because the new `sector_view.py` depends on it. Both
are flagged prominently in their own commit messages; worth a look before
merging, given the scope.

**Open work items, roughly in the order they'd make sense to pick up:**
1. Merge `worktree-factor-composite-reset` → `main` (Gabe's action).
2. EDGAR Form 4 insider pull (free, approved, not started — section 5).
3. Options volume/OI pull, pending the AV purchase (section 5).
4. Meta-model tier 2 (regime gate) — ask Gabe about the old HMM retirement
   reason first (section 4).
5. Meta-model tier 3 (sparse events via news sentiment) — needs the
   event×stock pooling reframe described in section 4, and real data
   (NEWS_SENTIMENT) before it's buildable.
6. The raw-volume/open-interest question for AV options data (section 5).

## File manifest (new/changed since the 2026-09-19 write-up)

```
final/app/app.py                          Stock tab overhauled, blend primary
final/app/lib/blend_model.py              blend loader, query, retrain wiring
final/src/current_signal_blend.py         live blend scoring + full-universe dump
final/src/reset2026/blend_q75.py          the q75+composite blend backtest
final/src/build_features_fundamentals_sharadar.py   vectorized rewrite, 2:42->59s
final/out/current_signal_blend.csv                  today's ~165 picks
final/out/current_signal_blend_full.csv             every name scanned, with status
final/out/current_signal_blend_meta.json            construction + backtest caveats
final/out/reset2026/blend_q75_report.json           the blend backtest numbers
final/src/reset2026/PREREGISTRATION.md              + "Future avenues" section
```
