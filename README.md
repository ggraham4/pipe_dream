# pipe_dream: current state of the project

**Consolidated 2026-09-23 by `pipe-dream-readme-manager`** (first full sweep),
last refreshed **2026-09-29** (run 12, at the end of this paragraph); run 5 (2026-09-26) followed WO-9, WO-10/WO-11, WO-13 and WO-14 landing,
the 10bfb19 app layout became official, and the ext ledger was committed
(integration `079fa26`); run 6 (same day) folds in the reset-branch landing
(`d7d257d`), the WO-8 addendum (`ddb2773`), the live-checkout sync (`6a1823d`)
and Gabe's 2026-09-26 decisions (integration `d7d257d`); run 7 (same day)
folds in WO-16, the SF1 top-up (landed `defcc23`, deployed to the live
checkout as `500a4a5`); run 8 (same day) folds in WO-15, the SUE forward
ledger with its Addendum A (landed `6ac64e6`, deployed live as `562dab9`),
the `final/scripts` deploy (`db13243`) and the launch of WO-17 and WO-18;
run 9 (same day) folds in WO-17, the Sharadar reference-table refresh
(landed `a9344ef`), and the app's SHARADAR_API_KEY guard (landed `c50e0e4`,
not deployed); run 10 (**2026-09-27**) folds in WO-20, the AV options pull
retry fix (landed `f380817`, pull still stopped), the app deploy of the key
guard and the most-volatile-first sort (`c8dec17`, live `4ab4363`), Gabe's
clean live Retrain ALL of 2026-09-26, and the COO's WO-18 seasonality
PASS-nomination (branch `74e6e03`, not landed); run 11 (**2026-09-28**)
folds in WO-19, the Sharadar key redaction (landed `9e169ce`, not deployed),
**WO-20-seas** (seasonality goes into both live models by Gabe's decision,
narrowed on 2026-09-29, see run 12;
landed `0032ee3` together with WO-18, app text landed `254ea01`, **not
deployed**), WO-21, the
construction-drag decomposition (landed `e05faea`, COO verdict UNIVERSE BET,
descriptive), Gabe's standing OK for unfitted hold-out reads, and the AV pull
now running on Gabe's Windows machine; run 12 (**2026-09-29**) folds in
**WO-20-seas-final**: Gabe's "Theoretical only" call puts `seas` in the
Theoretical model only and returns Today's Picks to its original 9-factor
blend (landed `22f2c69`, **deploy pending**). It also lists the new in-flight
branches (WO-23 results, WO-24, the two WO-25s, overnight-intraday). "WO-20" alone means the AV retry fix
(`f380817`); the seasonality deploy is always "WO-20-seas" (COO.md naming
note).
This is the one current-state document. It merges every branch's docs, the
coordination ledger, handoffs and project memory, and the newest source wins
where two disagree. Everything that lost is listed in [Superseded](#superseded)
at the bottom.

How to read the tags:

- **landed** means the claim is on `integration` (22f2c69). Landed is not
  the same as **live**: the live app runs from Gabe's main checkout
  (`round18-app-two-models` @ 4ab4363), which gets code only through an
  explicit deploy with his OK (§5 live-checkout row).
- **in flight** means it comes from an unlanded branch or from uncommitted files
  in a worktree. In-flight claims never describe current state. They live in
  [In flight](#5-in-flight).
- Paths written as `branch:path` exist only on that branch or worktree.
- "Project doc" means a markdown doc in the Claude Project, not in this repo.

`AGENTS.md` is now only the standing constraints and a pointer to this file.
Coordination rules for parallel sessions are in `~/.claude/CLAUDE.md` and
`~/.claude/pipe_dream-coordination/LEDGER.md`, both outside git.

---

## 1. What this project is

This is Gabe's personal, from-scratch quantitative trading research project.
The core question: can a model identify stocks likely to outperform over a
multi-week (40-trading-day) horizon, backtested honestly with point-in-time
discipline? That means no look-ahead, a survivorship-correct universe,
walk-forward evaluation, next-open execution and costs. There is also an
options workstream, plus a local Streamlit dashboard (`final/app/`) that shows
current picks.

**Owner: Gabe.** Every modeling decision, scope call and verdict is his. The
`pipe-dream-coo` agent recommends research direction, and Gabe decides. This
file records decisions and doesn't make them.

## 2. Standing constraints

These are Gabe's rules, copied byte-for-byte into [`AGENTS.md`](AGENTS.md). Read
them there. They are not repeated here, so the two copies can't drift apart.

Two newer rules live outside the repo and interact with them. See
[Open conflicts](#6-open-conflicts-and-decisions-for-gabe), item 1.

- **Rule 0 (`~/.claude/CLAUDE.md`, 2026-09-23).** Only `pipe-dream-integrator`
  runs git write operations (commit, push, merge, branch, stash, worktree). No
  other agent or session does.
- **Ownership (ledger, 2026-09-23).** `final/app/**` belongs to
  `pipe-dream-app-manager`. `README.md` and `AGENTS.md` belong to
  `pipe-dream-readme-manager`. `.gitignore`, `final/models/2026-09-19-factor-composite-reset.md`
  and `final/src/reset2026/PREREGISTRATION.md` are integrator-owned protected
  files.

---

## 3. Current state (as of 2026-09-29)

### 3.1 The one-paragraph version

Rounds 10-19 (2026-09-09 to 2026-09-16) established that the original
24-feature XGBoost stock model (`q75`) has **no detectable stock-selection
edge**. What it has is a low-volatility tilt plus a sector bet. On 2026-09-18
Gabe restarted the stock model as a **sign-constrained linear factor composite**
built from published anomalies, and moved down-cap. That composite shows a real
nomination-era signal (2007-2019). On the 2020-2026 hold-out (read on the old
v1 grid), **every version fails leave-one-year-out on 2020**. The old down-cap
grid (v1) was survivorship-selected. A survivorship-safe **v2 grid** was built on
2026-09-24 (WO-6), and on it the production `icw8` book earns **+2.85%/yr** vs SPY
at cap150 (nomination era, net 15bp, 40 offsets, late-2019 labels unmasked per
Gabe), down from +5.25% on v1. The result is now flat across cap tiers. WO-7
(2026-09-24) shows that on v2 all of that excess comes from the **ranking**, not
from holding the universe. The caveat: from 2011-10-20 to 2019, icw8 only
**ties SPY (+0.00)**. The IWM-hedged version (WO-9, 2026-09-25) came out
**MIDDLE**. Gabe had it recorded as a **forward bet, not promoted** (WO-10). On
2026-09-25 Gabe made **v2 the working panel** for every live and forward model
(WO-11). WO-14 added its refresh path (panel now through 2026-09-25 live) and the
**weekly** forward records Gabe chose. The SUE/post-earnings-drift screen (WO-13,
2026-09-25) is a **PASS-nomination**, but its portfolio contribution is noise-sized,
so the COO recommends confirming it forward only. Gabe approved the item on
2026-09-26, and per the COO that approval means forward confirmation via
WO-15, **not live weights** (§6 #15). **WO-15 is now a live forward bet:** its
SUE column landed as integration 6ac64e6 and was deployed live as 562dab9 on
2026-09-26 (Gabe: "Wo-15 cam go live"). The first countable record is W40,
and the verdict is read once, at 6 counted dates (§4.1). On rank accuracy the
IC-weighted composite beats q75 by a margin that is **not detectable** at 82
dates (§19, MIDDLE), and its rank signal is essentially one factor,
`gross_profitability`. **The app now runs the 10bfb19 layout** (Gabe,
2026-09-25): the composite+q75 blend is Today's Picks, and the composite alone
is the Theoretical Model tab. **Live checkout:** on 2026-09-26, with Gabe's
OK, the main checkout's `final/src` and `final/app` were synced to integration
d7d257d (commit 6a1823d, not pushed). That deploys the v2 working panel, the
WO-14 refresh and the Retrain ALL hook. Streamlit was not restarted, so the
change takes effect on the next app restart or rerun (LEDGER landing log).
**Scripts gap closed (2026-09-26):** `final/scripts/edgar_form4_refresh.py`,
which the weekly-record step calls first, was missing live. It was deployed
as db13243 on Gabe's OK. A static trace of Retrain ALL found 0 missing
scripts. **Gabe then ran a live Retrain ALL (2026-09-26 22:36-22:47), and the
COO verified it CLEAN** from the run log: insider refresh, SF1 top-up, panel
09-24 → 09-25, weekly-record preflight, both signals (COO.md; §4.7).
**WO-16 landed and deployed (2026-09-26):**
the append-only SF1 top-up, the 7-day fundamentals window and the
`FF.main()` → `build()` crash fix landed as integration defcc23 and were
deployed to the live checkout as 500a4a5 (not pushed). The worker already
topped up the live SF1 files once (max datekey 2026-09-08 → 2026-09-25).
Retrain ALL runs the insider step *before* the top-up; with db13243 deployed
it can now reach the top-up (§4.7; [WO-16 doc](final/models/2026-09-26-wo16-sf1-topup.md)).
**WO-17 landed (2026-09-26, a9344ef):** the live `tickers_master.csv` and
`actions.csv`, stale since 2026-09-08/09-10, were refreshed once by hand
(labels of existing tickers held back; §4.5). Nothing refreshes them
automatically. Insider buy/sell counts are a certified dead end (2026-09-23), and the
down-cap reopen was used by WO-4 (DEAD, 2026-09-24), so the family is spent
in-era. Congress is forward-only. The earnings-timing family is closed (8-K
test DEAD, 2026-09-23). The Alpha Vantage options pull on the Mac **crashed**
on 2026-09-23 (last date logged 18:03, traceback by 18:09), and its crash
cause is fixed on integration (WO-20, f380817, 2026-09-27). **The pull now
runs on Gabe's Windows machine** (Gabe, 2026-09-27: "AV pull is running on the
windows machine"). His 2026-09-28 ETA is cap2000 monthly around 09-30,
small-cap monthly 10-04..08, and the weekly pass around 10-25..29, after the
~10-22 renewal. Whether the Windows copy has the retry fix is not recorded
(§4.4, §6 #21).
**Seasonality goes into the Theoretical model only (Gabe, 2026-09-29:
"Theoretical only"); landed, deploy pending.** WO-18 (Heston-Sadka return
seasonality, `seas`) was a COO-verified PASS-nomination (+0.181pp/yr out of
sample, noise-sized). On 2026-09-27 Gabe promoted it into both models, and
WO-20-seas (0032ee3, with WO-18; app text 254ea01) implemented that. Before it
was deployed, WO-23 showed that seas lowered the blend in both periods
("WO-23: blend10 −0.12 pre-2020, −0.78 2020-26 vs blend9", hold-out read #5,
unfitted), and Gabe then chose "Theoretical only". **WO-20-seas-final**
(integration 22f2c69) keeps the Theoretical composite on `icw9_seas`
(`ic_weighted_seas_2026-09-27`) and returns Today's Picks to its original
frozen 9-factor leg (`blend_q75_ew9_2026-09-19`). Its picks equal the
pre-WO-20 scorer's (max diff 0.0). The 10-factor seas blend is recorded only
in the forward side ledger `prediction_ledger_blend_seas.csv`. COO.md records
the call as his in-the-moment deploy OK. **The deploy has not happened yet:** the integrator's
landing run was worktree-isolated and could not reach the main checkout,
which is still at 4ab4363, so the live app still shows icw8 and the 9-factor
blend (§4.1, §6 #24;
[seas Theoretical-only doc](final/models/2026-09-29-seas-theoretical-only.md)).
**WO-21 (2026-09-27, landed e05faea, descriptive): the post-2011 drag is a
universe bet.** Over 2011-10..2019 (nomination era, v2 cap150, net 15bp), a
random same-construction book trails SPY by −2.76%/yr. Of that, 72% (−1.99) is the no-score cap150 universe losing to
large caps, and the rest is the random null's own turnover cost. The icw8
ranking still adds +2.78 net over that null after 2011 (gross +2.10). The
realised post-2011 icw8 book was +0.01 vs SPY. The COO verdict is UNIVERSE BET,
no model change; the benchmark/hedge question goes to Gabe (§3.3, §6 #25).
**Hold-out policy changed (Gabe, 2026-09-27):** checks that fit nothing may
read 2020-2026 without asking each time (§3.4). Gabe has recorded that he has
**more faith in the blend** (Today's Picks) than in the Theoretical model
(2026-09-26, §3.2).

### 3.2 What the app shows: the 10bfb19 layout, official since 2026-09-25 (landed `e1f8f6f`, deployed `ccddf1a`)

On 2026-09-25 Gabe made the **10bfb19 layout** (what his live checkout was
running) the official app baseline. The integrator landed `app` @ 80f9f57 as
integration e1f8f6f ("10bfb19 layout is the official app baseline (Gabe,
2026-09-25)") and deployed `final/app` to the live checkout as ccddf1a (LEDGER,
"APP LAYOUT BASELINE"). This replaces the bca3f7c baseline Gabe set on
2026-09-23 (see Superseded). The bca3f7c-only items are gone from the app:
the q75/xrank display, the Sector Bets, Model Weights and Backtest & History
stock tabs, the knob-family band and the two Candidate tabs.

`final/app/app.py` on `integration` has four top-level tabs (Overview, Stock
Buy/No-Buy, Options Premium, Data & Updates). Stock has **four sub-tabs**:

| sub-tab | what it shows | role |
|---|---|---|
| Today's Picks | the composite+q75 blend, cap2000 (`final/src/current_signal_blend.py`). Its composite half is the **frozen original 9-factor equal-weight** version (`blend_q75_ew9_2026-09-19`), now read from the v2 panel. It stays that way after WO-20-seas-final: no `seas` in the blend | `"role": "primary"` in its meta. Not a validated edge |
| Theoretical Model | the icw8 composite alone, cap150, v2 panel + SPAC rule (`final/src/current_signal_composite.py`). On integration it is `icw9_seas`, not yet deployed | `"role": "candidate"`, note "TRACKED, NOT ACTED ON AS A VALIDATED EDGE" |
| Query a Ticker | per-ticker answers from both models plus a "Both models pick it" column (2026-09-24) | — |
| Universe | the eligible universe | — |

The numbers each tab's meta carries (landed):

- **Blend** (`final/out/current_signal_blend_meta.json`): a single-grid
  backtest, excess vs SPY 1.54%/yr (q75 alone 0.35, composite alone 0.54),
  hold-out -0.36%. As of 2026-09-08: 1,665 eligible, 165 picks. Its cap2000
  picks were identical on v1 and v2 that day (WO-11 §6).
- **Theoretical** (`final/out/current_signal_composite_meta.json`, landed
  27cc6ce): as of 2026-09-08 on v2, 3,065 eligible, 305 picks (220 on v1). It
  still quotes hold-out excess 2.44%/yr, 40/40 offsets, and **fails LOYO**
  (dropping 2020 flips it to -3.95%/yr). **Those hold-out numbers were measured
  on v1.** No landed hold-out read on v2 yet. Since Gabe's
  2026-09-27 standing OK, an unfitted read needs no per-read approval (§3.4).
  WO-23's read #5 (2026-09-28, committed, not landed) is the first on v2
  (§3.4, §5).
- **After WO-14 (uncommitted outputs in the main checkout, 2026-09-25):** the
  composite is as of 2026-09-24, with a cap150 book of 300 of 3,048 eligible.
  The blend stays as of 2026-09-08, because its `as_of` comes from the v1 base
  panel, which WO-14 was not allowed to rebuild
  ([WO-14 doc](final/models/2026-09-25-wo14-v2-incremental-refresh.md) "Live
  scorers").
- **After Gabe's live Retrain ALL (uncommitted outputs in the main checkout,
  mtime 2026-09-26 22:47):** both signals are as of **2026-09-25**. The blend
  has 160 picks of 1,615 eligible, and the composite has 300 of 3,048 (both
  metas read; COO.md "Live Retrain ALL"). The Retrain's v1 steps rewrote the
  v1 base panel (22:46:51, per the WO-18 doc's panel-swap check), so the blend
  is no longer stuck at 2026-09-08.

**Today's Picks sort (landed c8dec17, live 4ab4363, 2026-09-26):** a "Sort
picks by" control defaults to "Most volatile first" (`volatility_60`), with
"Blend score" and "Portfolio weight" (the old order) as options, plus a ticker
filter. It is display only: rows and weights are unchanged (Gabe, "aggressive
trading mode"; HANDOFF-app; COO.md decision #12). The same deploy made the
SHARADAR_API_KEY guard live (§4.7).

**Landed on integration, deploy pending: seasonality in the Theoretical tab
only (WO-20-seas 0032ee3, 2026-09-28; WO-20-seas-final 22f2c69,
2026-09-29).** On integration, `current_signal_composite.py` scores
`icw9_seas` (meta `model_version` `ic_weighted_seas_2026-09-27`, 9 factor
weights incl. `seas`). On 2026-09-25 data the new Theoretical book shares
203/300 picks with icw8 (HANDOFF-worktree-agent-a790eb27c4530aa0a).
`current_signal_blend.py`'s `main()` is back on the original frozen 9-factor
leg (`blend_q75_ew9_2026-09-19`, 9 factors in the meta, no `seas` or
pick-overlap keys), and on 2026-09-25 its picks were 160/160 identical to the
pre-WO-20 scorer (max abs diff **0.0**). The −0.36% hold-out belongs to the
live 9-factor blend again. The app text **landed as integration 254ea01 (app
a74a9dd, 2026-09-28)**: factor counts from the meta, the "SAME composite"
sentence replaced, hold-out provenance, and the equity curve labelled as icw8.
It is meta-driven, and WO-20-seas-final's AppTest with blend9 + icw9_seas metas
showed 0 exceptions and correct text ("9 composite factors", "The blend shows
**-0.36%** excess", no "PREVIOUS 9-factor blend's"), so no app change was
needed. The same landing carries a `_sue_guard_report` getattr fix (02b72e2).
Src and app deploy together as a 10-path list (HANDOFF-wo20-seas-final),
**without** running Retrain ALL; Gabe runs that himself after restarting
Streamlit from a shell with `secrets.env` sourced. None of this is in the live
checkout (4ab4363) yet (§6 #24). The tracked metas on integration were last
committed at 27cc6ce, so the composite meta there still shows icw8 until the
next scorer run.

**Gabe's recorded preference (2026-09-26):** "for the record I have more faith
in the blend than the theoretical because theoretical rejects TXG" (project
memory; COO.md decisions log). Recorded, not argued. The COO adds one fact: in
the blend's cap2000 universe the composite ranks TXG 29/323 in its vol
quintile (cutoff 32), so it would pick it there. The Theoretical tab most
likely misses it because of the cap150 universe (inferred, not recomputed),
not the factors.

App-owned inaccuracies are for `pipe-dream-app-manager` and are not fixed here
(Open conflicts #5). `final/app/README.md` still opens with a 2026-09-16
"q75 PRIMARY / xrank CANDIDATE, six tabs" header. The Theoretical Model tab
says it is "the SAME composite that feeds the blend", but the blend uses the
frozen 9-factor equal-weight composite and Theoretical uses icw8. That
sentence is fixed on integration (254ea01) and stays live until the deploy.

### 3.3 Headline verdicts

| verdict | status | date | source |
|---|---|---|---|
| The rebuilt point-in-time data erased the old edge: augmented model **−0.11% per window, t = −0.09**, compounded **1.00x vs SPY 5.23x** | landed | 2026-09-09 | [`DATA-PIPELINE-HANDOFF.md`](DATA-PIPELINE-HANDOFF.md) §0 |
| Old XGBoost stock selection: no edge. Round 12 Deflated Sharpe 0.746, Reality Check p=0.61. 100% of the apparent performance is factor loading | landed (code), certified dead end | 2026-09-11/12 | [`final/src/sweep/RUNBOOK.md`](final/src/sweep/RUNBOOK.md) §5; `round18-app-two-models:AGENTS.md` "Rounds 10–17" |
| IC is retired as a *feature-admission* gate. The gate is now a within-date shuffle null at the 80th percentile | landed | 2026-09-16 | [`final/src/sweep/RUNBOOK.md`](final/src/sweep/RUNBOOK.md) §9 |
| Factor composite, nomination era, cap150: **+3.75%/yr** excess vs SPY, 40/40 offsets (9(8)-factor original) | landed. **Superseded** by the v2-grid row below (v1 survivorship-selected grid) | 2026-09-19 | [`final/out/reset2026/REPORT_nominate.md`](final/out/reset2026/REPORT_nominate.md), [reset doc](final/models/2026-09-19-factor-composite-reset.md) §3.1 |
| `asset_growth` dropped (Gabe's call): nomination **+4.32%/yr**, sd 0.55%. `FACTOR_SIGNS` is now 8 factors | landed. The factor set stands; the +4.32% (v1 grid) is **superseded** by ew8 +1.80% on v2 (row below) | 2026-09-22 | [`PREREGISTRATION.md`](final/src/reset2026/PREREGISTRATION.md) "Factor-set decision"; [corrections](final/models/2026-09-22-composite-model-corrections.md) §3 |
| Composite hold-out (2020-2026): every version is positive in aggregate and **fails LOYO on 2020**. Original +1.85%/yr (drop 2020 → -2.05%/yr); asset_growth_dropped +2.62%/yr (→ -1.97%/yr); IC-weighted +2.44%/yr (→ -3.95%/yr) | landed | 2026-09-19/22 | [reset doc](final/models/2026-09-19-factor-composite-reset.md) §3.2; [corrections](final/models/2026-09-22-composite-model-corrections.md) §6b, §16 |
| **Survivorship-safe down-cap grid v2 built (WO-6), BUILD SUCCESS.** 22,535,814 rows, 9,266 tickers; the old 4,011 tickers reproduce `composite_panel.parquet` exactly on 20 dates. Re-measured (nomination era 2007-2019, `decile_volq` net 15bp, mean of 40 offsets, column c = v2 grid): cap150 icw8 **+2.85%** (v1: +5.25%), ew8 **+1.80%** (v1: +4.32%); cap500 icw8 +2.66%; cap2000 icw8 +2.84%. 40/40 offsets positive in every cell; LOYO min cap150 icw8 +1.71%. The survivorship fix alone is −1.8 to −2.6pp; the liquidity-flag fix is about 0. **No longer monotonic in cap.** Split-half OOS IC at cap150 *rises*, +0.0400 → +0.0479 | landed; COO-verified. "Monotonic in cap" is a certified dead end | 2026-09-24 | [down-cap grid rebuild](final/models/2026-09-24-downcap-grid-rebuild.md) "Phase 2 read-out" |
| **No-score control on v2 (WO-7): SELECTION MATERIAL.** cap150, column c, 2007-2019, net 15bp, 40 offsets, vs SPY: icw8 **+2.85**, random same-size book (icw8 score permuted within date, 20 draws) median **−1.09** (p95 −0.93), whole eligible universe with no score **−0.25** (6/40 offsets > 0; the old grid gave +2.40). Selection (icw8 − null median) **+3.95pp/yr**, 40/40 offsets, LOYO min +3.32 (2018). So on the honest grid all of the composite's excess is the ranking, not universe beta. Of the +3.95, about 0.65pp is lower turnover than a random book: the gross (0bp) selection is **+3.28**. **Caveat: on the common window 2011-10-20 to 2019-12-31, icw8 is +0.00 vs SPY (19/40 offsets) and +0.59 vs USMV (37/40).** All full-era excess over SPY comes from before 2011-10-20; the universe lagged SPY by about 2pp/yr afterwards and the ranking made that up. Descriptive, not a trial | landed; COO verdict SELECTION MATERIAL | 2026-09-24 | [no-score control v2](final/models/2026-09-24-noscore-control-v2.md) |
| **IWM-hedged composite (WO-9): MIDDLE**, recorded as a forward bet and **not promoted** (Gabe, 2026-09-25). Composite-family trial 14, v2 column c, cap150, 2007-2019, hedged = icw8 `decile_volq` net 15bp − IWM 40-day return − 10bp short leg, ETF borrow ≈ 0. **Price-only IWM (primary):** full **+2.28** pp/yr (40/40, LOYO min +1.61), 2011-10-20..2019 **+0.92** (misses the +1.0 gate), beta to SPY −0.164 (t −5.01). **Tradable** (ITERATE #1, adds book dividends − IWM dividends; book out-yields IWM by +0.27 full / +0.16 2011-19): full **+2.56** (LOYO +1.88), 2011-19 **+1.08** (40/40), but the 2011-19 LOYO is −0.26 without 2018. Clearing every gate on the tradable basis is "for information only": it follows a post-hoc basis fix and the 2011-19 margin is 0.08pp. Six of 13 years are negative (2016 −12.5). WO-9's figures are on IWM-available dates (last 40 era dates masked), so the like-for-like unhedged icw8 is +3.10, not the +2.85 standard. COO ruled after the results that LOYO is read on the full window only | landed e11d37e; COO verdict MIDDLE; Gabe: forward bet (WO-10) | 2026-09-25 | [hedged composite](final/models/2026-09-25-hedged-composite.md) §3-4; COO.md "Gabe decisions log" |
| **SUE / post-earnings-announcement drift (WO-13): PASS-nomination**, new family "earnings surprise / PEAD", k=1, v2 column c cap150, h=40, 2007-2019. All 6 gates pass: pooled NW IC **t +2.17** (bar 1.96), halves +1.82 / +1.22, both-sides sector-demeaned t +2.09, 0/40 offset flips, max single-year share 0.335. Gate 6: icw9 +2.4412%/yr vs a shuffle-null p80 of +2.3504%, so **icw9 − icw8 is +0.073pp/yr** against a null median of −0.025pp. That is noise against the book's offset sd (~0.47pp per COO.md; the doc gives 0.54 / 0.48). LOYO t falls to 1.52 without 2015; 2009 is −41% of the sum. Nearly new information (median Spearman with icw8 +0.062, with momentum +0.262). The COO recommended forward confirmation only. **Gabe approved the item 2026-09-26** (COO.md decisions log). Per the COO (2026-09-26) that means forward confirmation via WO-15, not live weights (§6 #15). WO-15's forward column landed 6ac64e6 and is live (562dab9); its verdict is read at 6 counted dates (§4.1) | landed 026e3b7; COO verdict PASS-nomination; WO-15 forward bet live 2026-09-26 | 2026-09-25 | [SUE screen](final/models/2026-09-25-sue-drift-screen.md) "Results"; COO.md WO-13, WO-15 |
| **Return seasonality `seas` (WO-18): PASS-nomination.** Heston-Sadka 2008 same-calendar-month returns, sign +1, new family, **trial 1, k=1**, v2 column c, cap150, h=40, 2007-2019. All 7 gates pass: NW t +2.84 (bar 1.96); halves t +1.61 / +2.67; both-sides sector t +2.87; 0/40 flips; max year share 0.271 (2008); icw9 +2.5496%/yr vs icw8 +2.3683% and shuffle-null p80 +2.3617% (**+0.181pp/yr**, split-half OOS weights, beats 20/20 draws). Caveats: 2017-2019 all negative; the COO puts 2007-2012 at ≈ 79% of the summed IC (decay plausible, the paper is from 2008); OOS IC does not improve (icw9 0.04831 vs icw8 0.04848, the gain is in the top-decile tail). The panel-swap race with Gabe's Retrain ALL was cleared (in-era slices sha-identical). The COO recommended a forward column only; Gabe promoted it instead (next row) | landed 0032ee3 (with WO-20-seas); COO verdict PASS-nomination | 2026-09-26/27 | [seasonality screen](final/models/2026-09-26-seasonality-screen.md) Results; COO.md "WO-18 VERDICT" |
| **`seas` promoted into both live models by Gabe (WO-20-seas); narrowed to the Theoretical model only on 2026-09-29 (next row)**: "Seasonality looks very good so you should add it to the model"; "Yes the blend should get the seasonality" (2026-09-27; overrides the pre-registered forward-column-only route; his call, not relitigated). Theoretical `icw9_seas` (frozen-rule weights: `seas` +0.1928, `gross_profitability` .4808): in-era +3.4871%/yr vs icw8 +2.8542%, worst offset +2.95 vs +1.93, LOYO min +2.46 vs +1.71, post-2011-10 +0.51 vs +0.01. **These use in-sample weights and are not evidence**; the out-of-sample figure is WO-18's +0.181pp/yr. Blend, pre-2020 **single grid**: previous 9-factor +2.52%/yr → 10-factor with seas **+2.40** (LOYO min +2.07 → +1.87, post-2011 +0.60 → +0.20), so **seas made the blend slightly worse on this grid**, inside single-grid noise; Gabe was shown this before deciding. Two forward side ledgers **monitor** the promotion (not a gate): mean paired rank-IC gain ≤ 0 at the 6th counted date is a demotion question to Gabe, never automatic | landed 0032ee3; the blend half superseded by 22f2c69 (next row) | 2026-09-27 | [WO-20-seas doc](final/models/2026-09-27-wo20-seas-live.md) §2-4; HANDOFF-worktree-agent-a790eb27c4530aa0a; COO.md decisions log |
| **`seas` in the Theoretical model only (Gabe, 2026-09-29, in the moment: "Theoretical only"; WO-20-seas-final).** Theoretical stays `icw9_seas` (`ic_weighted_seas_2026-09-27`). Today's Picks is back on its original frozen 9-factor leg (`blend_q75_ew9_2026-09-19`); the 10-factor seas blend is recorded only in `prediction_ledger_blend_seas.csv`. Why, per the doc: "seas was tested in the blend, not deployed (WO-23: blend10 −0.12 pre-2020, −0.78 2020-26 vs blend9)". Those WO-23 figures are the blend's single grid, frozen weights; 2020-26 is hold-out read #5 (unfitted), and WO-23 itself is not landed (§5). Checks: blend picks 160/160 and full 2288/2288 rows identical to the pre-WO-20 file on 2026-09-25 (max abs diff **0.0**); `seas_forward.py selftest` PASS; `wo20_isolation_test.py` all 8 modes rc 0; live ledger sha1s unchanged | landed 22f2c69 (161db4b); **deploy pending** (Gabe's OK given; the isolated integrator run could not reach the main checkout) | 2026-09-29 | [seas Theoretical-only](final/models/2026-09-29-seas-theoretical-only.md); COO.md decisions log; HANDOFF-wo20-seas-final |
| **Post-2011 drag decomposition (WO-21): UNIVERSE BET.** Descriptive, no trial. icw8 frozen, v2 column c, cap150, h=40, 2007-2019, 40 offsets, net 15bp, random book = 5-draw mean of the icw8 score shuffled within date. Post (≥ 2011-10), %/yr vs SPY: random book **−2.76** = (a) universe (no-score cap150 book) **−1.99** (72%) + (b) construction **−0.77** (28%); (c) costs −0.87 (31.5%, overlapping). Gross construction is +0.05, so (b) is entirely the random null's own turnover (f_new 0.905); the live book's cost is −0.20. Pre-2011 the universe helped (+2.74). icw8 selection over that null, post: **+2.78** net (sd40 0.40, 40/40 offsets, LOYO min +1.59 dropping 2018), +2.10 gross; the ≈ 0.67 gap is the null's extra cost. Realised post-2011 icw8 book: **+0.01** vs SPY. The universe book is ≈ 0.8 × IWM (R² 0.97); its SPY slope is t 0.85, so the drag is not beta. The doc's literal "selection − universe drag" is +0.79 and explicitly does not choose a forward formula. Not comparable one-to-one with WO-7's 20-draw median null (+3.95 selection) | landed e05faea; COO verdict UNIVERSE BET (COO-verified from drag_decomp.json, 20/20 reconciles), no model change, benchmark/hedge question to Gabe | 2026-09-27/28 | [construction drag](final/models/2026-09-27-construction-drag.md) §2; COO.md "WO-21 VERDICT" |
| **Up-market capture / upside beta: shelved by Gabe** before any run ("If the metric already exists then may not be worth the effort to include"). No trial spent, not a dead end. Reopen only if Gabe asks | recorded (no files) | 2026-09-25 | COO.md "Gabe decisions log" |
| The composite is a strong low-beta bet: corr(score, beta_252) -0.2933. Beta-adjusted IC is sharper (t 2.53 → 4.25) | landed. v1 cap150 grid, not re-measured on v2 | 2026-09-22 | [corrections](final/models/2026-09-22-composite-model-corrections.md) §9b |
| **IC-shrinkage weights** (each factor weighted by sign × max(0.1, abs(t) − 1) of its own pooled-IC t, pre-registered, one run) beat equal weight out of sample on raw-return IC in both split-halves: fit-odd→test-even, weighted +0.0304 vs equal +0.0183; fit-even→test-odd, weighted +0.0496 vs equal +0.0434. On beta-adjusted IC the second split favours equal weight on the point estimate. No portfolio CAGR was computed for this step | landed. v1 cap150 grid, nomination era (v2 split-half IC in the WO-6 row) | 2026-09-22 | [corrections](final/models/2026-09-22-composite-model-corrections.md) §12 (OOS figures as reproduced in §19's sanity gate) |
| **Cross-model rank accuracy (§19): MIDDLE.** Paired rho(icw8 split-half) − rho(q75) mean **+0.0449**, t **+1.89** (bar t ≥ 2), same sign in both halves. icw8 alone +0.0475 (t +4.19); q75 +0.0026 (t +0.12); `gross_profitability` alone +0.0458, so the composite's rank accuracy is **essentially one factor, not eight**. FM-R² ranks the other way because it is unsigned. Required labels: q75's large-cap-leaning (cap500k+) intersection, single s40 grid, pre-2020 only, descriptive (no trial spent) | landed; COO verdict: MIDDLE, no detectable difference | 2026-09-23 | [corrections](final/models/2026-09-22-composite-model-corrections.md) §19; `final/out/reset2026/cross_model_accuracy_report.json` |
| Composite extensions screened on the nomination era, none adopted: Amihud IC +0.0009 (t = +0.10); regime conditioning stopped (momentum flips in high-vol, the low-vol hypothesis fails); exponent p=2 no better; `fcf_yield` null; `profitability_trend` wrong-signed; EWMA beta marginal (IC +0.0462 vs +0.0450). `leverage` IC -0.0161, t -2.44, right sign, **not in the weights** (see §4.1 for its status) | landed. v1 cap150 grid, not re-measured on v2 | 2026-09-22 | [corrections](final/models/2026-09-22-composite-model-corrections.md) §10, §11, §13, §17 |
| Turnover: a buffer band (hold unless out of the top 20%) cuts turnover 19.3% → 6.3% at +5.43% vs +5.09% excess. Laddering smooths offset dispersion but does not cut turnover. Buffer is a tested refinement, **not the confirmed default** | landed. v1 cap150 grid, nomination era, not re-measured on v2 | 2026-09-22 | [corrections](final/models/2026-09-22-composite-model-corrections.md) §15; [full spec](final/models/2026-09-22-composite-model-full-specification.md) §2.3 |
| Options overlay (top-5 picks, 40-day ATM calls at Black-Scholes fair value, no real chain data): 47.1% of contracts expire worthless, all 5 worthless in 13 of 82 windows, full reinvestment compounds to ruin. A theoretical ceiling, not a recommendation | landed. v1 cap150 grid, nomination era | 2026-09-22 | [corrections](final/models/2026-09-22-composite-model-corrections.md) §18 |
| **Insider buy/sell counts are a certified dead end** as composite factors (cap150, h=40). Registered k=2: `ins_buyers_90` raw IC −0.0006 (t −0.16), halves disagree in sign; `ins_sellers_90` wrong-signed. The book gain is **gross, costs not applied**: ew9+buyers +4.94% vs the ew8 baseline +4.82%, against a shuffle-null p80 of +4.86%. The sector-neutral t of +3.10 is an artefact; with factor and return both sector-demeaned, IC +0.0018, **t 0.65**. Do not re-screen 30/180-day windows | landed; COO certified dead end | 2026-09-23 | [insider results](final/models/2026-09-23-insider-congress-results.md) §2-3, §7; [prereg](final/models/2026-09-23-insider-congress-preregistration.md) |
| **Insider plain buyer counts on the v2 grid (WO-4): DEAD.** This used the dead end's stated reopen condition (a survivorship-safe down-cap grid). Insider family k=4, bar t ≥ 2.50. Primary, cap150 column c, 2007-2019: pooled IC −0.0017, **NW t −0.50**; halves disagree in sign; 6/40 offset flips. Registered secondary, added (never-cap2000) tickers only: t **+2.36**, but **+0.60** once both factor and return are sector-demeaned, so it is a sector effect. icw9 − icw8 book gap +0.063pp/yr. **The insider family is spent in-era**; plain counts reopen only on forward data | landed; COO verdict DEAD | 2026-09-24 | [insider buyers v2 grid](final/models/2026-09-24-insider-buyers-v2-grid.md) |
| **Lead, not a result:** *opportunistic* insider purchases (Cohen, Malloy & Pomorski 2012), **+0.71% sector-demeaned 40-day return (Newey-West t 1.92, n = 10,419 events)**; routine purchases −0.70%. Post-hoc and below t = 2. Its "small-cap" tercile is mostly fallen large-caps. Measured on the **pre-fix TRANS_DATE** (see the WO-8 row): with the fixed dates, 1,185 of 327,456 officer/director purchases reclassify; not re-run. Continues forward-only | landed. v1 cap150 grid | 2026-09-23 | [insider results](final/models/2026-09-23-insider-congress-results.md) §6 |
| **TRANS_DATE fix (WO-8).** `build_insider_panel.load_events` took a lexicographic min of `DD-MON-YYYY` strings. Fixed: 25,081 event rows (1.72%) get a new, always earlier trans_date; that is 17,620 of 217,778 multi-date (accession, code) groups (8.09%). **0 classification flips on the 2026-09-08 blind record** (its in-window events all come from the live refresh, which was already correct). Bulk-vs-live agreement 94.69% → 100.00%. Historic reclassification: 1,185 of 327,456 officer/director purchases. `insider_features.parquet` (filing-date keyed) is unchanged. Implementation fix, not a trial | landed; COO-verified | 2026-09-24 | [forward ledger doc](final/models/2026-09-23-forward-ledger-leverage-opportunistic-buyers.md) "Implementation fix 2026-09-24: TRANS_DATE min" |
| **Congress trades are untestable in-era.** AV House coverage starts mid-2018 and 2020+ is spent. Forward-only. The premise that insider and congress data only record the execution date was wrong: SEC Form 345 has `FILING_DATE` (median lag 2 days) and AV congress has `filed_date` (median 28 days) | landed; COO: forward-only | 2026-09-23 | [insider results](final/models/2026-09-23-insider-congress-results.md) §1, §7 |
| **The reset2026 cap500/cap150 grid (v1) is survivorship-selected.** 52% of cap150-only rows are future winners, and 4,598 real tickers are missing. Rebuilt as v2 on 2026-09-24 (WO-6 row); v1 numbers not re-measured on v2 stay caveated | landed | 2026-09-22 | [AV spin doc](final/models/2026-09-22-alpha-vantage-spin.md) §A |
| `downcap_universe.py` split-basis bug is fixed; corrected universe written as `downcap_universe_v2.parquet` (v1 kept because `blend_model.py` reads it) | landed | 2026-09-22 | [AV spin doc](final/models/2026-09-22-alpha-vantage-spin.md) §B |
| AV `HISTORICAL_OPTIONS` is the only survivorship-safe AV endpoint (dead names, 2008+, raw volume/OI, PIT-safe OI). EARNINGS/ESTIMATES/INSIDER/NEWS are live-only | landed | 2026-09-22 | [AV spin doc](final/models/2026-09-22-alpha-vantage-spin.md) §1-2 |
| The one positive result from the XGBoost era: `days_to_next_filing` (the earnings announcement premium), h=20 IC -0.0153, t -4.17, and it gains strength under sector neutralisation. `_seasonal` is the tradeable, provably causal version (t -2.18). `_actual`/`_known` are **excluded from every training feature set** | landed (code); in the composite as `days_to_next_filing_seasonal`. The family is now closed (see the 8-K row) | 2026-09-12 | `round18-app-two-models:AGENTS.md` "Round 16" |
| **Earnings announcement premium via 8-K Item 2.02 is DEAD** under its pre-registered rule (trial 6 of 6): pooled raw IC −0.0065, **NW t −1.71 vs a 2.64 bar**, and **2015 = 48.5%** of the effect (limit 45%). Passed: both halves negative, both-sides sector-neutral t −1.82, 0/40 grid flips. **The earnings-timing family (6 trials) is a COO-certified dead end.** Reopen only with a point-in-time source of *announced* dates, tested forward. COO ruling: the doc's Part 2 sentence on moving a portfolio is struck, because the icw9−icw8 book gap is +0.10%/yr on in-sample weights | landed; COO certified dead end | 2026-09-23 | [EAP 8-K doc](final/models/2026-09-23-earnings-announcement-premium-8k.md) Part 2; COO.md dead-end table |
| **Two forward-only bets pre-registered and recording** (WO-2+3): `icw9` (the frozen icw8 rule plus `leverage`, sign −1, weight −0.1582) vs icw8, and CMP-2012 opportunistic insider buyers (`opp_buyers_90`, with the plain count as control). First blind record: panel date **2026-09-08**, 2,214 rows. Decision after **6 non-overlapping matured dates**; the first matures around **2026-11-03**. No backtest was run. Cadence is now **weekly** (WO-14 row). The side-ledger CSV `prediction_ledger_ext.csv` itself was committed only on 2026-09-26 (079fa26); before that it existed only untracked in the main checkout | code and doc landed 2026-09-24 (f3233bd); ext CSV landed 2026-09-26 (079fa26) | 2026-09-23/24 | [forward ledger doc](final/models/2026-09-23-forward-ledger-leverage-opportunistic-buyers.md) §1-5; COO.md report log 2026-09-26 |
| **Forward IWM-hedged icw8 bet (WO-10) recording** on the v2 panel: long the icw8 `decile_volq` book, cap150 (registered; cap2000 descriptive), short IWM at equal notional, tradable basis (dividends on both legs), full 15bp round trip on every record (heavier than WO-9's backtest) plus 10bp for the short. First blind record 2026-09-08: 472 rows (cap150 305 long + IWM, cap2000 165 + IWM). Kill if the mean hedged return over counted dates is ≤ 0 after ≥ 6 matured counted dates; > 0 goes to Gabe as a PROMOTE-CANDIDATE question. No verdict before about mid-2027. The top 3 names (SLAB, RAMP, PEN, 7.4% of the book) look like pending-acquisition targets, a known `decile_volq` property | landed 8f47808 | 2026-09-25 | [forward hedged icw8](final/models/2026-09-25-forward-hedged-icw8.md) |
| **v2 is the working panel** (Gabe, 2026-09-25: "Lets make the v2 panel the working panel going forward, all models should use it."). `final/src/reset2026/working_panel.py` holds the constants and the SPAC rule. The live scorers, `prediction_ledger.py`, `edgar_form4_refresh.py` and `forward_hedge.py` read v2. Research that reproduces published numbers stays on v1. ICW8/ICW9 weights and the v3 ledger's FM slope are frozen, not re-derived. Existing 2026-09-08 v1/v2/v3/ext records stay as recorded on v1 (`ledger_panel_manifest.json`) | landed 8f47808 (WO-11); deployed to the live checkout 2026-09-26 (6a1823d) | 2026-09-25 | [v2 working panel](final/models/2026-09-25-v2-working-panel-switch.md); COO.md "Gabe decisions log" |
| **v2 refresh path + weekly forward records (WO-14)**: `refresh_working_panel.py --through latest --record-weekly` extended v2 from 2026-09-08 to **2026-09-24** (12 new dates, 22,535,814 → 22,584,099 rows), with acceptance checks 1-6 all passing. Weekly records written for W38 (2026-09-18) and W39 (2026-09-24) in v3, ext and hedge. W39 was recorded before the week closed, so it is annotated `incomplete_week`: descriptive only, never a counted date. The WO-10 kill rule is unchanged: counted dates are greedy, each ≥ 40 trading days after the last, and on-time records only | landed f0e750a; engineering, no trial | 2026-09-25 | [WO-14 doc](final/models/2026-09-25-wo14-v2-incremental-refresh.md) |
| LCID was **not** a data bug. It was a real 1-for-10 reverse split on 2025-09-02 | landed | 2026-09-22 | [corrections](final/models/2026-09-22-composite-model-corrections.md) §6d |

Two down-cap grids exist, and every number names one. **v1** (`composite_panel.parquet`,
2026-09-18) holds only the 4,011 tickers that were cap2000 at some point, so it is
survivorship-selected and its cap150/cap500 rows are not a true small-cap result.
**v2** (`composite_panel_v2.parquet`, 2026-09-24) adds the 4,598 missing non-SPAC
names; "column c" in the WO-6/WO-7/WO-4 docs is v2 without SPACs. A "v1 grid"
status means the number was not re-measured on v2. cap2000 numbers are the same
on both grids. Since 2026-09-25, v2 is the working panel (WO-11 row).

**Era-end labels (Gabe, 2026-09-25; closed, don't relitigate).** Late-2019
rebalance dates whose 40-day labels exit in January-February 2020 stay in
nomination-era readouts, unmasked. Gabe: "let the model do its final gamble
and show the results." The standard is cap150 icw8 **+2.85%/yr** vs SPY; +3.10
masked is for reference only (COO.md "Open correctness items").

The certified dead ends list is owned by the COO (`~/.claude/pipe_dream-coordination/COO.md`,
2026-09-23) and is reproduced in §8.3.

### 3.4 Hold-out accounting

- The **old** 2020-2026 hold-out was spent on the XGBoost track: Round 13
  (top-5 breadth) and Round 18 (xrank).
- On 2026-09-18 Gabe **refreshed** it for the reset, and said not to re-argue
  that ([memory](#9-doc-index): `feedback_dont_relitigate_methodology_calls`).
- Since then it has been read for the composite **three times**:
  1. 2026-09-19: `cap150_raw`/`decile_volq`, the one pre-registered shot.
  2. 2026-09-22: `asset_growth_dropped`, the "Second hold-out spend" in
     PREREGISTRATION.md.
  3. 2026-09-22: IC-weighted, +2.44%/yr, drop 2020 → -3.95%/yr
     (corrections §16, landed 2026-09-23).

  The composite+q75 blend was also read once (-0.36%; its `blend_q75.py`
  and report landed with the reset branch, d7d257d). COO.md
  counts all four as hold-out reads; the full-spec doc §5 counts the three
  composite versions only. Both are right about what they count.
- **Policy since 2026-09-27 (Gabe, standing OK; do not relitigate):** "Since
  this is not fitted data, I do not think it is so bad to retest the same time
  point multiple times." Checks that fit nothing (fixed weights, no parameter
  chosen on 2020+) may read 2020-2026 whenever useful, without a per-read OK.
  The COO's rules: log every read in COO.md "Hold-out status", show the
  2020-2026 number next to the 2007-2019 one, and treat anything whose weights
  or selection were chosen after seeing a 2020+ number as in-sample for 2020+
  from then on. **Fitting on 2020+ still needs Gabe** (project memory
  `feedback_holdout_unfitted_reads_ok.md`; COO.md decisions log).
  - **Read #5 done, not landed:** WO-23's model audit (per-factor IC and
    leave-one-out for icw9_seas and the 10-factor blend, 2020-01 to the last
    matured label, frozen weights; pre-registered 8a58c88 before any 2020+
    number; results c9ba394/9106bef, COO-verified 2026-09-28; §5). Its
    blend10-vs-blend9 figures informed Gabe's "Theoretical only" (§3.3).
  - **Reads #6 and #7 are in flight (2026-09-29):** WO-24 (WO-21's
    decomposition on 2020+, descriptive) is #6. #7 is claimed twice in
    COO.md: the ICW v2 reweight, whose short-interest weight is **fit on
    2020-26** (Gabe-approved), and the options-readiness WO-25's exp B confirm
    (§5, §6 #28). Per COO.md, once the reweight fits on 2020-26 "only forward
    ledgers can confirm the Theoretical model".
- **The forward ledgers remain the only fully clean test surface.** Before
  the policy change, any further hold-out look needed Gabe's explicit OK
  (COO.md). There are three live ledgers,
  all first recorded on panel date 2026-09-08. Records are never rewritten, and
  `ledger_panel_manifest.json` maps each record to its panel (the 2026-09-08
  v3/ext records are on v1; the hedge ledger, including its 2026-09-08
  record, and everything later are on v2):
  - `prediction_ledger_v3.csv`: icw and ew columns (`prediction_ledger.py`,
    started 2026-09-22, landed 2026-09-23).
  - `prediction_ledger_ext.csv`: icw9 leverage + opportunistic buyers. Code
    landed 2026-09-24, and the CSV was committed 2026-09-26 (079fa26).
  - `prediction_ledger_hedge.csv`: the WO-10 hedged bet (landed 2026-09-25).
  - `prediction_ledger_sue.csv`: the WO-15 icw9_sue column (landed 6ac64e6,
    deployed live 562dab9, 2026-09-26). No record yet: W38/W39 were declined,
    and W40 is the first countable record (§4.1).
  - **Landed, not yet live (WO-20-seas 0032ee3; unchanged by 22f2c69):**
    `prediction_ledger_seas.csv` (icw9_seas vs icw8 on v3's rows; monitors
    the live Theoretical promotion) and `prediction_ledger_blend_seas.csv`
    (10-factor vs 9-factor blend, cap2000; since 2026-09-29 the only place
    the seas blend is recorded, since it is not deployed). They start at the first v3 date
    after 2026-09-24 (W40) once deployed. Neither is a gate (§4.1).

  **Cadence: weekly** (Gabe, 2026-09-25, "maximum data for future analyses").
  Records so far are 2026-09-08, 2026-09-18 (W38) and 2026-09-24 (W39,
  `incomplete_week`, descriptive). Counted dates are greedy, each ≥ 40 trading
  days after the last, and on-time only. Weekly records in between are
  descriptive, because their windows overlap. The first maturity is about
  2026-11-03, and every bet needs at least 6 counted dates before a verdict
  (COO.md WO-1; WO-10 §1). The weekly-record step reached the live checkout
  on 2026-09-26 (6a1823d). With `edgar_form4_refresh.py` deployed (db13243) it
  can now run end to end there (checked by static trace only so far).
- All three hold-out reads above were on the **v1** grid. The v2-grid work
  (WO-6, WO-7, WO-4, 2026-09-24; WO-9, WO-13, 2026-09-25) is nomination-era
  only and asserts `max(date) < 2020-01-01`, so it spent nothing. So do
  WO-18 and WO-21 (2026-09-26/27). WO-23 (read #5, 2026-09-28) is the first
  v2 hold-out read.

---

## 4. Workstreams

### 4.1 Factor composite (reset2026): active, landed through WO-21 (2026-09-28); live still icw8

**Start with the [full specification](final/models/2026-09-22-composite-model-full-specification.md)**
(2026-09-22, landed): the equation, factor table, weights, universe, eras and
reproduction in one place. Its §6 points to "AGENTS.md's reproduction table",
which now lives in §7 below.


- **Model:** a rank-transform of each factor, a fixed sign, then an average.
  Top decile within 5 trailing-vol quintiles, inverse-vol weighted, 40-day hold,
  next-open entry, 15bp costs, averaged over all 40 grid offsets, matched
  shuffle null. `final/src/reset2026/composite.py`.
- **Factors (landed `FACTOR_SIGNS`, 8):** `momentum_12_1` +, `pct_from_high_252`
  +, `volatility_60` −, `gross_profitability` +, `accruals` −,
  `net_issuance_pct` −, `days_to_next_filing_seasonal` −,
  `short_interest_days_to_cover` −. The last one has **zero coverage before
  2020-04-27**, so every nomination number is effectively from 7 factors.
- **Weights:** equal-weight in `composite.py`. The live candidate uses
  IC-shrinkage `PRODUCTION_WEIGHTS` from `ic_weighted_composite.py` (landed
  2026-09-23): `gross_profitability` 0.5956, `accruals` -0.1627,
  `net_issuance_pct` -0.1399, `momentum_12_1` 0.0497, the rest ±0.013 (per
  the landed composite meta). Frozen, fit once on the nomination era.
  **On integration since 0032ee3 (2026-09-28, not deployed):** the Theoretical
  scorer uses `PRODUCTION_WEIGHTS_V9_SEAS` (9 factors: `gross_profitability`
  .4808, `seas` +.1928, `accruals` −.1314, `net_issuance_pct` −.1129,
  `momentum_12_1` .0402, the rest ±.0105; same frozen ICW rule, full-era t).
  `PRODUCTION_WEIGHTS` (icw8) is unchanged and still what the live app and the
  v3 ledger use.
- **Physics audit (landed 2026-09-22).** Signs mostly right. Equal weights sit
  at cosine similarity 0.47 from the IC-optimal weights. Most of the edge is
  unlikely to be stock selection.
  [`2026-09-22-composite-model-physics.md`](final/models/2026-09-22-composite-model-physics.md).
- **Corrections round (landed §0-9).** `decile1_volq` refuted (−0.83%/yr).
  Book-to-market wrong-signed (IC -0.0240). `asset_growth` dropped. Beta term
  added. `price_adjustment_scanner.py` and `concentration_monitor.py` built.
  [`2026-09-22-composite-model-corrections.md`](final/models/2026-09-22-composite-model-corrections.md).
- **Corrections §10-19 (landed 2026-09-23):** IC-shrinkage weighting, the
  extension screens, regime buckets, turnover, the third hold-out spend, EWMA
  beta, the options overlay and the §19 cross-model comparison. Verdicts are
  in §3.3.
- **`leverage`:** corrections §13 (2026-09-22) called it a ready candidate for
  a promotion decision. The newer COO position (COO.md WO-2, 2026-09-23) is
  that its t −2.44 was already measured in-era, so an in-era test can only
  nominate. Confirmation is forward-only, as an icw9 column in the prediction
  ledger. **Recording since panel date 2026-09-08** (landed 2026-09-24; frozen
  weights and the kill/success rule in the
  [forward ledger doc](final/models/2026-09-23-forward-ledger-leverage-opportunistic-buyers.md) §1a, §4).
- **v2 grid (landed 2026-09-24).** WO-6 rebuilt the grid survivorship-safe
  without a new pull (SEP and SF1 for the missing names were already on disk;
  the 14-ticker SF1 top-up added nothing). On v2 the down-cap premium over
  cap2000 is gone, and the ranking holds (§3.3). WO-7 shows the excess is
  selection, but only in 2007-2011 vs SPY.
  [grid rebuild](final/models/2026-09-24-downcap-grid-rebuild.md),
  [no-score control](final/models/2026-09-24-noscore-control-v2.md).
- **Hedged (WO-9, landed 2026-09-25): MIDDLE.** Hedging with IWM removes the
  universe's 2011-19 drag against SPY almost entirely, but the 2011-19 spread
  is about +1pp/yr and depends on 2018. Gabe had it recorded forward (WO-10), not
  promoted (§3.3).
  [hedged composite](final/models/2026-09-25-hedged-composite.md),
  [forward hedged icw8](final/models/2026-09-25-forward-hedged-icw8.md).
- **SUE (WO-13, landed 2026-09-25): PASS-nomination** as a 9th factor
  candidate. Its in-era book gain is noise-sized. Gabe approved the item on
  2026-09-26. Per the COO (2026-09-26), that approval means forward
  confirmation via WO-15, **not live weights** (§6 #15). WO-15's
  pre-registration says "No promotion ever rests on the 2007-2019 result".
  [SUE screen](final/models/2026-09-25-sue-drift-screen.md).
- **WO-15, SUE forward confirmation: a live forward bet** (landed integration
  6ac64e6, deployed live 562dab9, 2026-09-26; Gabe: "Wo-15 cam go live").
  [SUE forward ledger](final/models/2026-09-26-sue-forward-ledger.md).
  - **What it records.** The weekly Retrain hook (`record_weekly.py`) writes an
    `icw9_sue` score next to v3's icw8 score into the side ledger
    `final/out/reset2026/prediction_ledger_sue.csv`, on live data only. `sue`
    comes from a separate SUE-only ARQ EPS pull
    (`final/src/sue/sf1_eps_live_pull.py` → `sf1_arq_eps_live.parquet`, hard
    cap 15 API calls). The frozen ICW rule with sue t +2.169917640299337 gives
    sue a weight of **+0.1321**. The doc discloses that this is **2.2× to
    5.1×** the WO-13 split-half weights behind the in-era +0.073pp/yr, so the
    forward test is of a larger SUE tilt than the one measured in-era.
  - **Clock.** W38 (2026-09-18) and W39 (2026-09-24) were declined and are
    descriptive either way. The first countable record is **W40**: panel date
    ~2026-10-02, recordable once the panel has a W41 date (~10-05) (doc §7),
    and it must be recorded by ~10-09 to count on time (COO.md decision #9).
    The anchor is the first on-time, complete-week record with ≥ 70% `sue`
    coverage. After it, counted dates are greedy, each ≥ 40 trading days after
    the last.
  - **Verdict, read once, at 6 counted dates** (about 1 year out, COO.md). The
    statistic is the mean paired gain, Spearman(icw9_sue, r) − Spearman(icw8,
    r), with r the raw `forward_return_tradable_40`. **Mean gain > 0: it goes
    to Gabe as a promotion candidate. ≤ 0: DEAD** (SUE family closed). Fewer
    than 6 matured counted dates: INSUFFICIENT. The beta-adjusted and
    sector-demeaned versions are descriptive only.
  - **Addendum A** (COO ITERATE 1/3, committed c69b942 before any record,
    hardened 7c3e066). The first live pull (2026-09-26: 91,310 ARQ rows, 7,305
    tickers) stopped at the pre-registered basis validation, with 176 eps
    mismatches on 15 tickers outside the split lists. The ruling:
    - **Isolation (A0):** any SUE failure skips SUE only. It is logged to
      `out/reset2026/ledger_sue_guard_log.csv` and never blocks the v3, ext or
      hedge records (isolation harness `final/src/sue/wo15_isolation_test.py`,
      6/6 modes pass on a scratch store).
    - **Uniform-ratio basis check (A1a):** a ticker whose live/reference eps is
      one constant ratio (within 1e-9) across all its common keys passes. This
      is detected in code; no ticker is hand-listed. Non-uniform tickers (per-key
      edits, value↔NaN edits, rounding-varied ratios) get `sue` = NaN and are
      logged (A1b). The old split lists no longer exempt anyone (the worker's
      reading, COO-confirmed).
    - **1% cap (A1c):** if non-uniform tickers exceed 1% of a date's v3
      tickers, SUE is skipped for that date only.
    - **Rolling reference (A1d):** each run validates against the last
      accepted pull. The first reference is
      `sf1_fundamentals_through_2026-09-08.parquet` (631,185 rows). Accepted
      pulls are logged in `data/sharadar/sf1_arq_eps_live_accepted.csv` and
      survive as dated `sf1_arq_eps_live_<pulled_at>.parquet` backups.
    - **W38/W39 declined (A1e).**
    - Dry run on W38/W39: 2 of 3,053 v3 tickers non-uniform (BNC, BNTC), 0.066%,
      under the cap; `sue` coverage 90.17% / 90.32%.
  - **After deploy** (LEDGER, 2026-09-26): live `record_weekly.py --plan`
    exits 0 with nothing missing, ledger sha1s are unchanged, and
    `prediction_ledger_sue.csv` does not exist yet.
- **Next (COO.md, 2026-09-26):** score the forward ledgers from about
  2026-11-03 (WO-1; needs Gabe's machine for the price pull). Get WO-15's first
  countable record (W40) written by ~10-09. The
  WO-16 SF1 top-up landed (defcc23) and was deployed live (500a4a5) on
  2026-09-26 (§4.7). Laddered rebalancing was **not launched**: it only changes
  variance and can't fix the 2020 concentration (COO.md; corrections §15). The
  open composite questions for Gabe are COO decision #7.
- **Book construction check (COO, 2026-09-27; descriptive, run read-only, no
  trial counted; script in `/tmp/coo_ew/`, not in the repo; source COO.md).**
  Gabe asked "out of curiosity". WO-18 harness, icw8 frozen, v2 column c
  cap150, 2007-2019, 40 offsets, net 15bp (nomination era). Inverse-vol
  +2.85%/yr (LOYO min +1.71, post-2011-10 +0.01, 5-draw shuffle null −1.01);
  equal weight +2.73 (LOYO min +0.85, post-2011 −0.41, null −1.14);
  vol-weighted +2.25 (LOYO min −0.42, post-2011 −1.17, null −1.79). Selection
  over the matched null is ~+3.9 to +4.0 in all three arms, so **the weighting
  does not create the edge**; more vol tilt adds noise and 2009 dependence.
- **Why TDUP/MYGN are picked (COO, 2026-09-27, Gabe's question):** their
  drawdowns came before the decision date and are in the model's view
  (momentum 5th/8th pct), but gross_profitability (weight 0.596, 97th/96th
  pct) and accruals (weight −0.163) dominate while momentum carries 0.05. An
  unverified hypothesis: an impairment-driven loss (MYGN accruals −0.58)
  scores as "high quality"; a possible work order would test it (COO.md).
- **Seasonality (WO-18, landed 0032ee3 via WO-20-seas): PASS-nomination**
  (§3.3). The factor is built from SEP prices only (`final/src/seasonality/`
  `build_seas.py`), so it is point-in-time and v2-survivorship-safe. A 10-year
  lookback needed SEP from 1998, so the worker pulled
  `final/data/sharadar/sep_pre2005/` (85 monthly files, gitignored; §7).
  Coverage 79%.
  [seasonality screen](final/models/2026-09-26-seasonality-screen.md).
- **WO-20-seas → WO-20-seas-final: `seas` goes live in the Theoretical model
  only (landed 0032ee3 on 2026-09-28, narrowed by 22f2c69 on 2026-09-29;
  deploy pending).** Gabe decided "both" on 2026-09-27 and "Theoretical only"
  on 2026-09-29, after WO-23 (§3.3). The forward ledgers monitor it rather
  than gate it.
  [seas Theoretical-only doc](final/models/2026-09-29-seas-theoretical-only.md);
  [WO-20-seas doc](final/models/2026-09-27-wo20-seas-live.md) (its own title
  says "WO-20").
  - **Code:** `ic_weighted_composite.py` adds the V9_SEAS weights; new
    `seasonality/seas_live.py` computes `seas` at score time from
    `data/sharadar/panel/stocks/` (selftest vs the WO-18 parquet: max diff
    0.0); `current_signal_composite.py` scores icw9_seas.
    `current_signal_blend.py`'s `main()` uses `_compute_composite_frozen` (9
    factors, `BLEND_MODEL_VERSION = "blend_q75_ew9_2026-09-19"`) and no longer
    computes `seas`; the 10-factor code (`_BLEND_FACTOR_SIGNS_V10_SEAS`,
    `_compute_composite_frozen_v10_seas`, `blend_scores_at`, label
    `BLEND_MODEL_VERSION_SEAS10_TESTED`) is kept for the side ledger only
    (22f2c69). `seasonality/seas_forward.py` writes the two side ledgers,
    driven by `record_weekly.py` after SUE, isolated per ledger (8/8 isolation
    modes pass, including Addendum A's `MIN_ROWS` 100 row-count guard).
  - **Forward read, per ledger, once at the 6th counted date** (WO-15
    counting rules; seas coverage ≥ 0.70): mean `gain_raw` = Spearman(new,
    r) − Spearman(previous, r) > 0 → CONSISTENT, reported to Gabe; ≤ 0 → a
    **demotion question to Gabe**, nothing automatic (doc §4).
  - **Deploy** is an additive 10-path list in HANDOFF-wo20-seas-final (7
    `final/src` files, `final/app/`, and both seas docs), approved by Gabe's
    2026-09-29 call and still pending (§6 #24). Do not run Retrain ALL as part
    of it. Post-deploy checks: `seas_forward.py selftest`,
    `record_weekly.py --plan`, and both metas' `model_version`.
  - **Blocked on Gabe:** the Theoretical tab's 2007-2026 equity curve stays
    **icw8** and is to be labelled so. The doc says an icw9_seas curve would
    read the spent hold-out; whether Gabe's newer unfitted-read OK changes
    that is open (§6 #26).
- **Post-2011 drag decomposition (WO-21, landed e05faea, 2026-09-28): UNIVERSE
  BET** (§3.3). Pre-registered decision map, 1 run + 1 fix, 20/20 reconciles
  to the COO's and WO-7's numbers. The drag concentrates in 2014, 2015, 2017
  and 2019, and its construction and cost parts are flat at about −0.8%/yr
  every year. The COO's reading: the model's stock picking kept working after
  2011, and the unhedged book vs SPY rides the small/mid-cap vs large-cap
  cycle. The COO recommends keeping SPY as the headline and adding
  score-over-universe as a standing diagnostic (§6 #25). No construction trial
  and no turnover work order were triggered.
  [construction drag](final/models/2026-09-27-construction-drag.md); code
  `final/src/construction/drag_decomp.py`, outputs `final/out/construction/`.
- **Next (COO.md, 2026-09-28/29):** WO-23's audit is done and awaits landing:
  S1 was not triggered, so S2 (the forward ledgers at 6 counted dates) applies
  to seas in the Theoretical model (§5). Its other findings (weights derived
  from v1 t's, short interest, accruals wrong-signed on 2020+) led to the ICW
  v2 reweight and WO-24, both in flight (§5). WO-22 (a next factor) has no
  strong candidate and is not launched.

### 4.2 Old XGBoost stock model (q75 / xrank): half of the blend, no validated edge

- Since the 10bfb19 layout became official (2026-09-25), q75 is no longer
  displayed on its own. It is half of the Today's Picks blend. xrank is not
  shown. The COO notes that keeping q75 is Gabe's decision, and the "certified
  dead end" is **not** grounds to remove it.
- Its demonstrated content: a low-vol tilt (score-vol correlation -0.134) plus a
  tech/healthcare sector bet. Sector-neutralised IC is −0.0038.
- Live script: `final/src/current_signal_pit.py`. It trains both variants from
  one panel load, and the tradable label `_trd_` was fixed in Round 18.
- Full history: `round18-app-two-models:AGENTS.md` (Rounds 9-19). The
  integrator held those sections back from `integration` pending a decision,
  and this README carries their current-state content. Also
  [`final/src/sweep/RUNBOOK.md`](final/src/sweep/RUNBOOK.md).

### 4.3 Composite+q75 blend (meta-model tier 1): Today's Picks (primary)

- `blend_score = mean(rank_z(composite_9factor_frozen), rank_z(q75))`, cap2000,
  zero fit. Single-grid backtest: 1.54%/yr vs SPY (q75 alone 0.35, composite
  alone 0.54), hold-out -0.36%. **Bases, all in the same landed meta:** 1.54 is
  the overall `excess_cagr_vs_spy_pct`; the nomination era alone
  (`nominate_only_excess_cagr_pct`) is **2.52**, and the hold-out alone is
  -0.36. The seas comparison below (2.52 → 2.40) is on the
  nomination-era basis, pre-2020 only. cap2000 is unaffected by the survivorship-grid
  issue. It has been the app's Today's Picks since the 10bfb19 layout became
  official (2026-09-25). Since WO-11 its composite leg reads the v2 panel with
  the SPAC rule, and its picks didn't change (cap2000 is identical on v1 and v2).
- The composite half is **frozen** to the original 9-factor equal-weight
  definition on purpose. Don't let it import the current `composite.py`,
  because that would invalidate its own backtest (APP.md).
- **Seas was tested in the blend and not deployed (Gabe, 2026-09-29,
  "Theoretical only"; integration 22f2c69).** The live leg stays the original
  frozen 9 factors (`blend_q75_ew9_2026-09-19`), so the -0.36% hold-out and
  the 1.54%/yr are this blend's own numbers. The 10-factor variant
  (`_BLEND_FACTOR_SIGNS_V10_SEAS`) scored +2.40 vs +2.52 on the pre-2020
  single grid (§3.3), and WO-23 put it at "blend10 −0.12 pre-2020, −0.78
  2020-26 vs blend9". It is recorded only in the forward side ledger
  `prediction_ledger_blend_seas.csv`. q75 is untouched. Because `main()` no
  longer computes `seas`, a missing SEP month file can't stop Today's Picks.
- Tier 2 (regime gate) is not started. Ask Gabe why the old HMM was retired
  first (COO decision #1). Tier 3 (sparse events) needs a survivorship-safe news
  source, since AV NEWS fails on dead names.

### 4.4 Options

- **AV options bulk pull: running on Gabe's Windows machine (Gabe,
  2026-09-27).** The Mac run crashed 2026-09-23, and its cause was fixed on
  integration 2026-09-27 (WO-20, f380817). Gabe's ETA (via his Windows
  session, COO.md D-AV-2, 2026-09-28): cap2000 monthly done ~09-30, small-cap
  (cap150-not-cap2000) monthly ~10-04..08, and the weekly pass (non-cap2000
  names only, the thin-liquidity slice) ~10-25..29. The parquet lands on
  Windows, so Gabe must copy `options/monthly/` and `pull_log.sqlite` to the
  Mac before any worker can use it. **Whether the Windows script has the
  WO-20 retry fix is not recorded** (COO asks Gabe to confirm).
  The Mac crash, for the record: the run died on
  `http.client.IncompleteRead`, which subclasses `http.client.HTTPException`,
  not `OSError`, so it escaped the retry tuple. It had logged monthly
  2010-08-18 (last line 18:03:02): 33 of 225 monthly dates, 0 of 750 weekly
  (`final/data/alphavantage/pull.out`, 33 unique dates, traceback, mtime 18:09).
  The fix in `final/scripts/av_options_pull.py` retries every
  `http.client.HTTPException` (and a non-dict JSON body) with the unchanged
  backoff; after 5 failed tries the name is logged `error` and the loop moves
  on, and the next run re-tries `error` rows. Offline monkeypatched test only
  (`/tmp/wo20/test_retry.py`, not committed): ALL PASS; no AV calls made
  ([WO-20 doc](final/models/2026-09-27-av-pull-retry-fix.md)).
  - **Where the fix is and isn't:** the live checkout has no
    `final/scripts/av_options_pull.py` or `av_options_run_pull.sh`, and the
    copy the crashed run used (`final/data/alphavantage/bin/av_options_pull.py`)
    is unfixed. Resuming needs the launcher run from a checkout that has the
    fix, or the two scripts deployed live first (integrator + Gabe's OK). The
    launcher copies its sibling script over `bin/` and writes to the live
    `final/data/alphavantage/`; a resume skips every ok/no_data row in
    `pull_log.sqlite` (WO-20 doc "Resuming";
    [`AV_PULL_WINDOWS.md`](final/scripts/AV_PULL_WINDOWS.md) 2026-09-27 line).
  - **Where it runs:** Gabe moved it to his Windows machine (2026-09-24
    call; confirmed running 2026-09-27). The WO-20 runbook line describes a
    Mac resume; that is a how-to, not a decision.
  - Data in `final/data/alphavantage/`. An updated Windows runbook, a
    merge-back tool and a *different* retry fix are unlanded on the AV-spin
    branch (§5, §6 #23).
  A unified AV+DoltHub chain and option features are built
  (`build_option_chain_unified.py`, `build_av_options_features.py`).
- **Pre-registered, not run.** Exp B (option factors, cap2000) needs ≥120
  nominate-era monthly dates landed. Exp A (train-old/test-new weights) needs
  the 1998 Sharadar backfill (blocked: `SHARADAR_API_KEY` not set). WO-18's
  `sep_pre2005/` pull (2026-09-26) covers the SEP part of it; SF1 for
  1998-2006 is still missing (COO.md WO-18 note).
  `final/src/reset2026/era_transfer.py`. **Do not** run `--exp B --stage confirm`
  or any cap500/cap150 tier before the grid rebuild.
- **AV subscription:** $49.99/mo, renews around 2026-10-22 (COO decision #3).
  **COO decision D-AV-2 (2026-09-28, for Gabe): renewal vs the weekly pass.**
  The weekly pass serves only the thin-liquidity bet, the lowest-prior options
  bet; exp B and WO-O1 need only cap2000 monthly. The COO's plan: ~10-01
  launch exp B + WO-O1 on cap2000 monthly; ~10-08 a pre-registered
  thin-liquidity probe on small-cap monthly; renew one more month by ~10-20
  only if that probe survives its kill or WO-O1 passes and needs the WO-O2
  daily pull, else cancel. Gabe asked (2026-09-28) whether to cancel and test
  on cap2000 first; the COO said yes: turn off auto-renew now **if** AV keeps
  access through the paid period (check the account page), and don't stop the
  running pull (COO.md; §6 #21).
- **Options program written, all BLOCKED on the AV data (COO.md, 2026-09-27;
  options dead-end trial count so far = 7):** WO-O1 sell cash-secured puts on
  honest AV data at cap2000 with the stock score as a filter; WO-O2 an
  exit-rule family (needs daily quotes per held contract); WO-O3 behavior
  cloning of Gabe's own trades (step 1: is his record profitable after costs
  vs a matched null; needs his broker export). None is launched.
- **Earlier options model (2026-08/09):** long calls ≈ flat (Kelly −0.16%/mo,
  n=74). Long puts have no working model. Selling cash-secured puts is a
  **lead**: +3.32%/cohort, 70/85 months, a −33.5% COVID month, ad-hoc cleaning,
  and a DoltHub universe that isn't survivorship-safe. Details are in
  `final/models/buy_no_buy_options_v2/`, `final/models/pit_integration/README.md`
  and `final/models/hyperparameter_retune/README.md`. The live options tab still
  scores the S&P 500 chain.

### 4.5 Data layer

- The Round 11 point-in-time Sharadar rebuild is the ground everything stands
  on: `pit_universe.parquet` 6,888,686 rows, 4,011 tickers. Reproduction and
  acceptance tests: [`DATA-PIPELINE-HANDOFF.md`](DATA-PIPELINE-HANDOFF.md).
- **Down-cap grid v2** (2026-09-24, landed): `final/src/reset2026/build_downcap_grid_v2.py`
  runs the existing builders unchanged into new `*_downcap_v2*` files and
  `composite_panel_v2.parquet` / `outcome_cache_v2.parquet`. Added tickers' OHLC
  go to `final/scripts/td_data_sharadar_downcap_v2/` (gitignored). Nothing
  existing is overwritten.
- **v2 is the working panel** (2026-09-25, WO-11; `working_panel.py`), and
  **`refresh_working_panel.py`** (WO-14) extends it incrementally. It is now
  through 2026-09-25 in the live checkout (Gabe's Retrain ALL, 2026-09-26:
  +3,999 rows, 3,855 label fills; COO.md). Known gaps: 8 reverse-split
  micro-caps (CTSO, GOSS, GTBP, JAGX, NFE, NXXT, OPTT, VWAV) are not extended,
  and **the BLOCKED list is now 9: KITT joined them** in that Retrain (COO.md).
  The refresh exits 1 if a blocked name becomes eligible. `sf1_fundamentals.parquet` and `sf1_shares.csv`
  get the WO-16 append-only top-up (landed defcc23, 2026-09-26; live copy
  through 2026-09-25). The v1 panel is kept only to reproduce past results.
- **Reference tables refreshed once (WO-17, landed a9344ef, 2026-09-26;
  [WO-17 doc](final/models/2026-09-26-wo17-reference-refresh.md)).** The live
  `tickers_master.csv` (a live reader: domestic-common filter, sector, SPAC
  rule) and `actions.csv` had ended at 2026-09-08 / 2026-09-10. The worker
  rewrote both in the main checkout with the new operator script
  `final/scripts/sharadar_reference_refresh.py` (two pulls; dry run, live
  write, idempotent rerun). Verdict: **SUCCESS**.
  - tickers_master 20,965 → 21,014 rows; actions 48,558 → 51,625 rows,
    now covering through 2026-09-29 (12 rows dated after the run: announced
    dividends and splits). Backups `tickers_master_through_2026-09-08.csv`
    and `actions_through_2026-09-10.csv` (byte copies of the old files).
  - **Label hold-back:** for every ticker already in the base, `category,
    siccode, sicsector, sicindustry, famaindustry, sector, industry,
    firstpricedate` keep the base value (Addendum A added `firstpricedate`,
    which the vendor now clamps at 1997-12-31). 7,936 differences on 7,889
    tickers were held back (7,876 of them `firstpricedate`) and listed in
    `final/out/wo17/master_label_changes_pending.csv`, not applied.
  - Acceptance (a): 12/12 panel and ledger hashes unchanged. (b): 0 of the
    3,130 tickers eligible after 09-08 change labels, SPAC flag or DOMESTIC
    membership; 0 mismatches over all 9,272 panel (ticker, sector) pairs, so
    the next refresh won't hit a sector RefreshError. (c): named IPO,
    delisting and split checks PASS against SEC filings/exchange notices
    (checked, per the doc, through web-search summaries of the linked pages).
  - **Not fixed:** the 8 split-blocked micro-caps above. All 8 splits are now
    in `actions.csv`, but `refresh_working_panel.py` never reads it; its block
    is price-based. Unblocking is WO-14's 8-call re-pull plus a missing fold
    step, a new pull (COO recommends NO, all ineligible).
  - **Not automatic:** the script is a one-off tool, not wired into Retrain
    ALL and not in the live checkout. The tables will go stale again.
- Approved data-sourcing order (Gabe, 2026-09-17): sector-neutral features →
  net issuance (done, Round 20) → insider buys (**done 2026-09-23**, SEC Form
  345, plain counts a dead end, see §4.6) → options liquidity bucketing (AV
  pull running on Windows, see §4.4) → earnings revisions.
  [`2026-09-17-new-data-sourcing-research.md`](final/models/2026-09-17-new-data-sourcing-research.md).
- Architecture research (2026-09-17): hold the architecture and put effort
  into data. The reset then chose a linear composite.
  [`2026-09-17-model-architecture-research.md`](final/models/2026-09-17-model-architecture-research.md).

### 4.6 Insider and congressional trading: done 2026-09-23, reopen spent 2026-09-24 (landed)

- **Data:** SEC Insider Transactions Data Sets (structured Form 3/4/5,
  2006Q1-2026Q1, 868 MB, gitignored in `final/data/edgar/form345/`),
  keyed on `FILING_DATE` and joined by issuer CIK, officers and directors
  only. AV `INSIDER_TRANSACTIONS` is unusable (no filing date, no P/S code,
  today's issuer only).
- **Result:** plain buyer/seller counts are a certified dead end. Nearly all
  the cross-sectional structure is a sector bet: insiders buy most in
  Financials, Energy and Real Estate, which then underperform. The
  down-cap reopen (WO-4, v2 grid, 2026-09-24) was also DEAD, and the family
  (k=4) is spent in-era. Verdicts in §3.3.
- **Lead:** opportunistic buyers. Now a pre-registered forward-only bet,
  recording since panel date 2026-09-08 (landed 2026-09-24,
  [forward ledger doc](final/models/2026-09-23-forward-ledger-leverage-opportunistic-buyers.md)).
  A live Form 4 refresh (`final/scripts/edgar_form4_refresh.py`) covers
  2026-04-01 to 2026-09-23. No 2007-2019 reruns.
- **TRANS_DATE bug fixed** (WO-8, landed d9be19b, 2026-09-24). The bulk
  events were regenerated; the old file is kept as
  `out/insider/insider_events_prefix_2026-09-24.parquet`. 0 flips on the
  2026-09-08 blind record; the fix applies from the next record date. The
  in-era opportunistic lead was measured on the old dates and was not re-run.
- **Congress:** forward-only. `final/scripts/av_congress_pull.py` needs the
  premium AV key and is **untested** against the REST response.
- Code: `final/src/insider/` (`build_insider_panel.py`, `screen_insider.py`,
  `posthoc_insider.py`; v2 grid: `build_insider_panel_v2grid.py`,
  `check_mapping_v2grid.py`, `screen_insider_v2grid.py`). Small reports are committed in `final/out/insider/`.
  [Results](final/models/2026-09-23-insider-congress-results.md),
  [pre-registration](final/models/2026-09-23-insider-congress-preregistration.md).

### 4.7 Live pipeline and forward ledgers: landed (9dd0852, WO-16 defcc23) and deployed to the live checkout (6a1823d, WO-16 500a4a5, app 4ab4363), 2026-09-26; WO-19 landed, not deployed; WO-20-seas(-final) landed, deploy pending

- **The Retrain ALL chain that should run** (WO-14 doc): the v1 data steps
  (`sharadar_pull_pit_panel.py` … `export_sharadar_ohlc.py`), then
  `refresh_working_panel.py --through latest --record-weekly`, then
  `current_signal_blend.py` and `current_signal_composite.py`. The app hook
  landed as 783cc12 → integration 9dd0852, and it was deployed together with
  the `final/src` sync as 6a1823d on 2026-09-26, on Gabe's OK (APP.md; LEDGER).
  Streamlit was not restarted then. **Scripts gap closed 2026-09-26:**
  `refresh_working_panel.py --record-weekly` first calls
  `final/scripts/edgar_form4_refresh.py`, which was missing live, so a live
  Retrain ALL would have stopped at "insider refresh failed; panel and ledgers
  untouched" (APP.md). The integrator deployed that one script as db13243 on
  Gabe's OK. A static trace of all 15 Retrain ALL steps found 41 files, 0
  missing scripts and 0 unresolved imports. The other
  integration-only `final/scripts` paths are still absent live, and Retrain
  ALL doesn't call them: **10 as of e05faea** (checked with `git ls-tree`
  integration vs the live HEAD 4ab4363, 2026-09-28 run 11), the 9 from run 10
  plus WO-19's `test_wo19_key_redaction.py`. Two of them are the WO-20-fixed
  `av_options_pull.py` and its launcher `av_options_run_pull.sh` (§4.4).
- **Live `final/src` no longer equals integration (2026-09-29).** Landed but
  not deployed: WO-20-seas as narrowed by WO-20-seas-final (the scorer/ledger
  files plus the new `final/src/seasonality/` tree and the app text; Gabe's OK
  given 2026-09-29, deploy pending a non-isolated integrator run, §6 #24),
  WO-19's key redaction in 11 Sharadar scripts plus `sf1_topup.py` (needs
  Gabe's OK, §6 #27), and WO-21's research-only `final/src/construction/`.
- **First real live Retrain ALL: CLEAN (Gabe, 2026-09-26 22:36-22:47;
  COO-verified from `final/app/logs/retrain_all_models/run.log`, COO.md).**
  Insider refresh ran (filings through 09-25). SF1 top-up: +0 rows, 21
  restated keys NOT applied, 4 calls. Panel 09-24 → 09-25 (+3,999 rows, 3,855
  label fills). BLOCKED list now 9 (KITT joined the 8 split names).
  `record_weekly` preflight passed ("SUE isolated") and there was nothing to
  record (W39 was not a complete week). Ledger shas unchanged. Signals as of
  2026-09-25 (§3.2). The panel rewrite (22:44:48) raced WO-18's screen start;
  the in-era slices are sha-identical before and after (WO-18 doc, panel swap
  verification), so no result changed.
- **Retrain speedup** (reset branch, landed d7d257d): the merged
  `build_features_fundamentals_sharadar.py` keeps the global-asof speedup
  (2:42 → 59s on that step) but writes all 14 fundamental columns, including
  `market_cap`, as float64. On 80 sampled in-universe tickers (218,698 rows)
  it is bit-identical to `process_ticker`. The live panel
  `features_with_fundamentals_sharadar_pit.parquet` (built 2026-09-25) came
  from the float32 builder, and the next Retrain ALL rewrites it as float64
  (LEDGER landing log, 2026-09-26).
- **SF1 top-up (WO-16): landed defcc23, deployed to the live checkout 500a4a5,
  2026-09-26** ([WO-16 doc](final/models/2026-09-26-wo16-sf1-topup.md); LEDGER
  landing log). New `final/src/reset2026/sf1_topup.py` appends new ARQ/ARY
  keys to `sf1_fundamentals.parquet` and `sf1_shares.csv` (4 Sharadar calls a
  run). Rows already on disk stay byte-identical, restatements are logged to
  `sf1_topup_restatements.csv` and never applied, and each run keeps dated
  backups and is idempotent. `refresh_working_panel.py` runs it by default
  (`--no-sf1-topup` skips it; never under `--check`/`--no-swap`).
  - **Acceptance exception** (Gabe, 2026-09-26: "fundamentals may change on
    rows < 7 days old"): the 6 fundamental-derived columns may take recomputed
    values on panel rows dated ≥ run date − 7 days (logged to
    `sf1_window_changes.csv`). On older rows an explained difference keeps the
    stored value (logged to `sf1_kept_stored.csv`), and an unexplained one is
    still a hard failure.
  - **Bug fix:** the reset landing (d7d257d) renamed
    `build_features_fundamentals_sharadar.main()` to `build()`, but the WO-14
    refresh still called `FF.main()`. The first real refresh with a new SEP
    day would have crashed. The refresh now calls `main()` if it exists, else
    `build()` (verified at `refresh_working_panel.py:293` on the live checkout).
  - **Live data, 2026-09-26:** the worker topped up the live SF1 once:
    +475 rows (sf1_fundamentals), +471 (sf1_shares), max datekey
    2026-09-08 → **2026-09-25**. No real panel refresh ran (SEP ends
    2026-09-24 = panel end), so the panel and every ledger are unchanged
    (sha256). A full-grid `--no-swap` rehearsal (9,250 tickers) showed
    0 unexplained mismatches.
  - **Reachable through Retrain ALL since db13243:** with `--record-weekly`,
    the refresh runs `final/scripts/edgar_form4_refresh.py` *before* the
    top-up. That script is now deployed live, so both run (static trace only
    so far).
  - **Coupling:** the live SF1 is already topped up, so the pre-WO-16 refresh
    code fails on it ("recomputed old rows disagree"). Rolling back means
    restoring `sf1_fundamentals_through_2026-09-08.parquet` and
    `sf1_shares_through_2026-09-08.csv` *before* any refresh.
  - **v1 side effect:** the v1 steps are full rebuilds. The next Retrain
    absorbs every appended key into v1 history (no window), one run behind
    v2. No ledger is affected.
- **SUE forward hook (WO-15): landed 6ac64e6, deployed live 562dab9,
  2026-09-26** (§4.1). `record_weekly.py` runs `sf1_eps_live_pull.py` as a
  subprocess (`sys.executable`) only when a SUE date is due and the live file
  is stale, at most once per run. Any SUE failure skips SUE only. New
  append-only files: `prediction_ledger_sue.csv` and `ledger_sue_guard_log.csv`
  (`out/reset2026`), and `sf1_arq_eps_live_accepted.csv` (`data/sharadar`).
  The SUE pull needs `SHARADAR_API_KEY` in the Retrain shell (§8.2).
- **App key guard: landed c50e0e4, deployed live 4ab4363 (2026-09-26, with
  the Today's Picks sort, integration c8dec17)** on Gabe's "just deploy it
  now" (COO.md decision #12; LEDGER landing log). A startup banner when
  `SHARADAR_API_KEY` is missing (presence only, the value is never shown), a
  Retrain ALL key preflight, and after Retrain a report of SUE guard-log rows
  and refresh exit codes. Verified headless (AppTest, 0 exceptions).
  **Streamlit was not restarted:** the new lib modules aren't hot-reloaded, so
  Gabe must fully restart it from a shell that sourced
  `~/.config/pipe_dream/secrets.env`, in the pipe_dream env (COO.md #12;
  HANDOFF-app).
- **Pull-script gap:** `sharadar_pull_pit_panel.py` skips any month already on
  disk, so the current month is never re-pulled, and every Retrain was a no-op
  for September. WO-14 used `--start 2026-09 --end 2026-09 --force` (21
  calls). The deployed app change also forces the current-month re-pull.
- **Sharadar key out of logs (WO-19): landed 9e169ce, 2026-09-27, NOT
  deployed** ([WO-19 doc](final/models/2026-09-27-wo19-key-redaction.md)). No
  script built a key-bearing URL string. The leak was `requests` exception
  text (which carries the full URL, key included) reaching stdout, a
  RuntimeError or a traceback, and so the app job logs. An inline `_scrub()`
  now redacts it in `sharadar_pull_pit_panel.py` (the one the app runs),
  `sharadar_pull_fundamentals.py`, `sharadar_pull_shares.py`,
  `diagnose_marketcap_units.py`, `sharadar_build_identity_map.py`, the three
  universe probes, and `final/scripts/` `sharadar_splits_pull.py`,
  `sharadar_data_pull.py`, `sharadar_downcap_pull.py`; `sf1_topup.py` gets
  defence in depth. `sf1_eps_live_pull.py` and `sf1_topup.py` were already
  safe. Offline test (fake key, no network): 10 of 13 pre-fix copies leak, 13
  of 13 fixed copies are clean, and mocked-success output is byte-identical. A
  read-only scan of the live `final/app/logs` found no key-shaped string. The
  live checkout still has the pre-fix scripts (§8.2).
- **Forward ledgers** (§3.4): v3, ext, hedge and (from W40) sue, weekly, with sidecars
  `ledger_record_log.csv` (`recorded_late`) and `ledger_record_annotations.csv`
  (`incomplete_week`). `forward_hedge.py status` drops both kinds before
  applying the counted-date rule. To score the hedge ledger at maturity, pull
  IWM into `final/data/benchmarks/IWM_live.csv`, refresh SEP past the exit date,
  then run `forward_hedge.py score` and `status`.

---

## 5. In flight

Nothing below is current state until it lands.

| branch / worktree | what it will change | state | source |
|---|---|---|---|
| `worktree-wo23-model-audit` (COO WO-23, model audit) @ 9106bef | Descriptive audit, **no fitting, no weight changes**, of Theoretical icw9_seas (40 offsets) and the blend's 10-factor leg + q75 (cap2000, single grid), periods A = 2007-2019 and B = 2020-01 to the last matured label (**hold-out read #5**, unfitted). COO verdict (COO.md "WO-23 VERDICT", 2026-09-28): no F1/F2 flags; S1 not triggered (seas B IC t +0.23, LOO −0.03), so S2 (forward) applies to Theoretical. Period B %/yr vs SPY, frozen weights: icw9_seas −2.02, icw8 −1.99, blend10 −1.41, blend9 −0.63 (q75's 2020+ training-window leakage unchecked). Its "seas lowered the blend" finding drove Gabe's "Theoretical only" (§3.3) | pre-reg 8a58c88; results c9ba394 + doc follow-up 9106bef (2026-09-28); **not landed** (COO.md: "Landing requested after Gabe sees it."). The LEDGER row still says "awaiting COO verdict" | `worktree-wo23-model-audit:final/models/2026-09-27-model-audit.md`; COO.md; LEDGER |
| `worktree-wo24-construction-drag` (COO WO-24) @ 06a76c2 | WO-21's universe/construction/cost decomposition on period B (2020-01-02..2026-07-30) for icw8 and icw9_seas: **hold-out read #6**, unfitted, descriptive. New files only (`drag_decomp_b.py`, `drag_decomp_b.json`, `final/models/2026-09-28-construction-drag-2020s.md`) | pre-reg b63582d; results committed 06a76c2 (2026-09-29; commit message: "decision map: universe bet"); no COO verdict recorded yet; not landed. Carries WO-23 as an input merge | `worktree-wo24-construction-drag:final/models/2026-09-28-construction-drag-2020s.md`; LEDGER |
| `worktree-agent-aa9609e4d8a64a036` (ICW v2 reweight; the ledger calls it "WO-25") @ 0aa87b4 | Gabe, 2026-09-29: "re derive on v2, fit on 2020-26". Re-derives the icw9 weights with the same rule from v2 column c 2007-2019 t's for 8 factors, with the short-interest weight **fit on 2020-26** (hold-out read #7, Gabe-approved). New files only (`final/src/reweight/`, `final/out/reweight/`, `final/models/2026-09-29-icw-v2-reweight.md`). No `PRODUCTION_WEIGHTS` change and no deploy; results go to Gabe | method pin 0aa87b4 committed before any backtest (2026-09-29); carries WO-23 (land WO-23 first or together) | LEDGER; COO.md decisions log |
| `wo25-options-readiness` (COO WO-25, options Phase 1) in `agent-a8b6bd6512a6407cf` | Gate A on the 33 Mac AV dates, exp B runner + a portfolio shuffle-p80 companion, the WO-O1 put-selling backtester, a data-arrival checker; **no outcome stats on real labels**. Pre-reg `final/models/2026-09-29-options-readiness-wo25.md`; hold-out reads pre-assigned #7 and #8 (§6 #28). Phase 2 runs on the Windows data once copied (~10-01), before the ~10-20 AV renewal call | in progress, no commits recorded (2026-09-29) | COO.md "WO-25 LAUNCHED"; LEDGER |
| `worktree-overnight-intraday` | Overnight vs intraday return decomposition screen (Lou-Polk-Skouras 2019), Gabe-approved 2026-09-29. New files only (`final/src/overnight/`, `final/out/overnight/`, `final/models/2026-09-29-overnight-intraday-screen.md`); pre-reg before any outcome read | in progress, no commits recorded | LEDGER |
| main checkout `round18-app-two-models` (live) @ 4ab4363 | **Not yet deployed there (2026-09-29):** WO-20-seas src as narrowed by WO-20-seas-final (22f2c69) with its app text (254ea01): **Gabe's OK given 2026-09-29, deploy pending** because the landing integrator run was worktree-isolated (LEDGER). Also WO-19 (9e169ce, needs Gabe's OK) and WO-21 (e05faea, research only). Today `final/src` + `final/app` equal integration d7d257d plus the 3 WO-16 paths from defcc23 (500a4a5), `final/scripts/edgar_form4_refresh.py` (db13243), the 6 WO-15 paths from 6ac64e6 (562dab9) and `final/app` from c8dec17 (4ab4363: key guard + picks sort), all 2026-09-26, except `final/src/fly/*` (9 files kept). The other integration-only `final/scripts` are not synced (10 at e05faea, incl. WO-17's two operator tools and WO-20's fixed AV pull script and launcher, which only run by hand). WO-17's data write went straight into the live `final/data/sharadar/` (no commit). **Not pushed**: 10bfb19 in its history carries 4.3 GB of FUSE temp files and >100MB blobs. A clean mirror is on origin as `round18-app-two-models-clean` @ 78f8c34, and it lacks 02be838 and everything from 6a1823d on | Repointing the local branch onto the clean line is a history rewrite: Gabe's call (§6 #12). Not to be merged into integration | LEDGER landing log 2026-09-26; LEDGER round18 row |
| `worktree-alpha-vantage-spin` @ 6ca32f3 | Updated Windows runbook, `av_pull_windows_prep.py`, `av_merge_pull_roots.py`, a pull retry fix in `av_options_pull.py` (a bare `except Exception`, not WO-20's `FETCH_ERRORS`; also `--only-tier downcap`), a `downcap_universe.py` path override | committed and pushed, **not landed**: excluded from the 2026-09-26 merge (Gabe: "merge everything but AV"). Its `av_options_pull.py` now conflicts with WO-20's landed version (f380817) on the same lines (§6 #23) | LEDGER landing log; COO.md decisions log 2026-09-26 |
| `worktree-papermoney-order-sheet` | paper-broker order sheet | **not to land** (Gabe, 2026-09-23; reaffirmed 2026-09-26) | LEDGER; COO.md decisions log |

---

## 6. Open conflicts and decisions for Gabe

1. **Standing constraints vs newer out-of-repo rules.** AGENTS.md #5 (dated
   2026-09-17) says agents may `git add/commit/push` themselves. Rule 0 in
   `~/.claude/CLAUDE.md` (2026-09-23) says only the integrator may. AGENTS.md #1
   says never push or redeploy the live app, while project memory (2026-09-23)
   records Gabe giving the integrator authority with "the app is for my use
   only". The constraints are copied verbatim and not edited. **Gabe: amend #1
   and #5 in AGENTS.md, or confirm the out-of-repo rules take precedence?**
   `final/src/sweep/RUNBOOK.md` §10 still carries the pre-2026-09-17 "never
   commit" wording.
2. ~~Landed code depends on an uncommitted file (`ic_weighted_composite`).~~
   **Resolved 2026-09-23** by f680f94 (audit landed; the integrator verified
   `import current_signal_composite` on integration).
3. ~~The live composite still reads the v1 grid.~~ **Resolved 2026-09-25 by
   Gabe:** "Lets make the v2 panel the working panel going forward, all models
   should use it." Implemented by WO-11 (landed 8f47808): the scorers and forward
   ledgers read v2, and existing records stay as recorded (manifest). Deployed
   to the live checkout 2026-09-26 (6a1823d, #12).
4. **IC's role (methodology, for the COO).** Round 19 (2026-09-16) retired IC as
   a feature-admission gate (rank correlation with earnings +0.019). Gabe's
   2026-09-22 reframe made pooled IC the composite's *target metric*, and the
   IC-weighting, leverage and §19 cross-model results are judged on IC/rho.
   The insider round (2026-09-23) used both an IC screen and the shuffle
   null, and they disagreed: sellers are wrong-signed on IC but beat the
   shuffle null on the book. The two standards need an explicit
   reconciliation.
5. **App-owned inconsistencies (for `pipe-dream-app-manager`).**
   `final/app/README.md` still opens with a 2026-09-16 header that calls q75
   PRIMARY and xrank CANDIDATE and lists "six tabs". The 10bfb19 layout has
   four stock sub-tabs with the blend primary. The Theoretical Model tab
   (`render_stock_theoretical`) says it is "the SAME composite that feeds the
   blend", but the blend's composite leg is the frozen 9-factor equal-weight
   version, and Theoretical is icw8. (The blend's `"role": "primary"` is
   correct again under the 10bfb19 layout.) The Theoretical sentence is fixed
   on integration by the WO-20-seas app text (254ea01, 2026-09-28, not
   deployed). The app README header is not in that change and is still open.
6. **Stale coordination entries (for their owners).** COO.md "Hold-out
   status" read 2 still says the blend is "a Candidate tab, not app primary:
   Gabe declared bca3f7c the baseline", which the 10bfb19 decision reversed.
   COO.md Leads still lists laddered rebalancing and the 8-K earnings premium
   (not launched; DEAD). The WO-10 doc §2 C10 and COO.md's WO-9 decision bullet
   say the cadence is pending, and it is now weekly. The ledger's AV row says
   new commits after e58dfd5 need landing, but `de4fdb5` is in integration
   (6ca32f3 is the unlanded one). The ledger's round18 row (dated 2026-09-24)
   still gives the local tip as ccddf1a; it is 6a1823d since 2026-09-26.
   COO.md "Active bets" still says the main checkout's `final/src` is 983a154,
   and its "Open correctness items" still lists the float32 builder as open
   (both closed 2026-09-26 per its own decisions log). COO.md's 2026-09-26
   decisions-log line still says "SUE/PEAD promotion approved" without the
   scope the COO has since given (#15). COO.md decision #12 still says "The
   app-manager is building it" after its own DONE line. COO.md "Hold-out
   status" still ends "Any further look needs Gabe's explicit OK", under the
   2026-09-27 policy that replaced it. COO.md D-AV still says the retry fix is
   unfixed on integration; it landed as f380817. The WO-20-seas doc §5 says an
   icw9_seas equity curve is forbidden by the spent hold-out, which doesn't
   account for Gabe's unfitted-read OK (#26).
7. **Earlier decisions still pending** (COO.md): why the HMM regime gate was
   retired; whether to renew AV premium (around 2026-10-22; now D-AV-2, #21);
   whether the integrator may
   fast-forward `main` to `integration` (origin/main is 1f81de2 after the
   2026-09-25 docs push, still far behind); the composite open questions (COO
   decision #7: is 2020 regime or luck, adopt `leverage`, a
   Deflated-Sharpe/Reality-Check gate, EWMA beta). The forward-ledger cadence
   is **resolved: weekly** (Gabe, 2026-09-25).
8. **`neutralize_on_sector` convention (COO decision #6, methodology, for
   Gabe).** It demeans the factor within sector but not the return. The
   insider round showed that this turns a sector-timing effect into a fake
   within-sector t (+3.10 → 0.65 when both sides are demeaned). The same
   function produced the physics doc §7 `*_neutral` rows and the reset's
   neutral cells. The COO recommends reporting the both-sides number next to
   it as standard, without changing past numbers. Not yet decided.
9. ~~COO worker worktrees on origin/main.~~ **Resolved 2026-09-24:** WO-5
   landed at 371f2d0 and WO-2+3 at f3233bd, both via integration.
10. ~~App layout: 10bfb19 vs bca3f7c.~~ **Resolved 2026-09-25 by Gabe:** the
    10bfb19 layout is official. Landed e1f8f6f, deployed ccddf1a (§3.2).
11. ~~What the composite's post-2011 result means for promotion.~~
    **Answered 2026-09-25:** WO-9 (hedged) came out MIDDLE, and Gabe had it
    recorded as a forward bet (WO-10), not promoted.
12. **Live checkout: history rewrite still open (Gabe).** The src/app deploy
    is **done**: on 2026-09-26, with Gabe's OK, the main checkout's `final/src`
    and `final/app` were synced to integration d7d257d as 6a1823d, which
    deploys the WO-14 Retrain hook (LEDGER landing log). ~~(a) sync
    `final/scripts`~~ **done 2026-09-26:** `edgar_form4_refresh.py` deployed as
    db13243 on Gabe's OK ("1 yes do it", "3 make it happen"), so Retrain ALL
    now reaches the weekly records and the SF1 top-up (static trace, then a
    clean live run 2026-09-26; §4.7).
    Still open, Gabe's call: (b) 6a1823d and everything after it (500a4a5,
    db13243, 562dab9, 4ab4363) is not pushed, because the local round18
    history carries >100MB blobs. Repointing the local branch onto
    `round18-app-two-models-clean` is a history rewrite. COO.md (2026-09-26)
    says it is "NOT treated as approved".
13. ~~SUE promotion (Gabe).~~ **Decided 2026-09-26:** COO.md's decisions log
    records "SUE/PEAD promotion approved" (Gabe OK'd all open items). The only
    implementation is WO-15, a forward-only column, live since 2026-09-26
    (§4.1). See #15 for what "promotion" covers.
14. ~~The WO-8 doc addendum is uncommitted.~~ **Resolved 2026-09-26:**
    committed 547ae48 and landed in integration as ddb2773 (Gabe-requested via
    the COO).
15. ~~What "SUE promotion approved" means.~~ **Resolved 2026-09-26 by the
    COO:** it means forward confirmation via WO-15, not live weights. `sue` is
    not in any live scorer, the blend or the Theoretical Model tab; if the
    WO-15 verdict is > 0 after 6 counted dates, promotion goes to Gabe as a
    separate question (§4.1). (Source: the COO's 2026-09-26 request to the
    README manager, clarifying its own summary line; COO.md line still
    unqualified, #6.) This matches WO-15's ruling: "**No promotion on the
    2007-2019 result.**" Adding SUE to live weights would need its own work
    order.
16. ~~SF1 is frozen at 2026-09-08 for every live reader (COO decision #8).~~
    **Approved by Gabe 2026-09-26** as top priority ("this needs to be fixed
    ASAP, make it happen"), including the WO-14 acceptance exception
    "fundamentals may change on rows < 7 days old". **Resolved 2026-09-26:**
    WO-16 landed (defcc23) and was deployed to the live checkout (500a4a5),
    and the live SF1 now runs through 2026-09-25 (§4.7). Automatic top-ups
    through Retrain ALL became reachable with the db13243 scripts deploy
    (#12). One
    caveat: Gabe answered "3", and the coordinator mapped that to WO-16 rather
    than to the COO's own item 3, the round18 history rewrite (COO.md).
17. **RESOLVED 2026-09-26 (COO: CLOSED, no recheck needed).** WO-17's live
    `actions.csv` write came after WO-15 deployed, but live `sue_forward.py`
    reads `actions.csv` only in `split_names_since_basis()`, and that result
    is reporting-only per Addendum A (`split_sources_reported_only`). The
    rewrite cannot change any SUE value or decision (COO.md "WO-17 LANDED").
18. **Held-back label changes (COO.md decision #11, Gabe).** 11 panel tickers'
    labels changed at the vendor (none eligible after 09-08), including the
    ticker reuse that leaves the new RML and HYAC.U carrying the old
    company's labels. Applying any needs a WO-16-style acceptance exception.
    COO recommends leaving them held back. Data:
    `final/out/wo17/master_label_changes_pending.csv`, `acceptance_b_tickers.csv`.
19. **RESOLVED 2026-09-26: deployed.** Gabe: "just deploy it now" (COO.md
    #12). The key guard and the picks sort landed as c8dec17 and went live as
    4ab4363 (§4.7). Still open for Gabe: a full Streamlit restart from a shell
    that sourced `secrets.env`, or the new modules don't load.
20. **DOMO → HUCK continuity: logged as a low-priority lead (COO,
    2026-09-26).** DOMO (eligible) was renamed HUCK on 2026-09-24 (same
    permaticker 116453; WO-17 doc). The panel is keyed on ticker, so a rename orphans
    history: a general gap, one name now. Candidate fix: key or join on the
    Sharadar permaticker in the refresh (COO.md). The same pattern covers
    WO-14's 8 "stale, kept" tickers (WO-17 doc (b)).
21. **D-AV-2: AV renewal vs the weekly pass (Gabe; COO.md, 2026-09-28,
    decide by ~10-20).** D-AV itself is resolved: Gabe, 2026-09-27, "AV pull
    is running on the windows machine". Its ETA puts the weekly pass after
    the ~10-22 renewal (§4.4). The COO recommends testing exp B and WO-O1 on
    cap2000 monthly first, turning off auto-renew now if AV keeps access
    through the paid period, and renewing only if a result earns the weekly
    or daily data. Open for Gabe: that call; copying the Windows output
    (`options/monthly/`, `pull_log.sqlite`) to the Mac; and confirming the
    Windows script has the WO-20 retry fix.
22. ~~WO-18 `seas` forward column?~~ **Superseded 2026-09-27 by Gabe:** he
    promoted `seas` into both live models instead ("Seasonality looks very
    good so you should add it to the model"; "Yes the blend should get the
    seasonality"). WO-20-seas implements it, and its forward ledgers monitor
    it rather than gate it (§4.1). Not relitigated here. **Narrowed
    2026-09-29 by Gabe to "Theoretical only"** (#24, §3.3).
23. **AV-spin's retry fix vs WO-20's (integrator/Gabe).** The unlanded
    `worktree-alpha-vantage-spin` (6ca32f3) carries its own
    `av_options_pull.py` retry change (`except Exception`, plus
    `--only-tier downcap`) on the same lines WO-20 changed. If AV-spin is
    ever landed, the merge must pick one. Gabe excluded AV-spin from the
    2026-09-26 merge. Which checkout the other machine runs isn't recorded,
    so it is unknown whether that copy has any fix.
24. **WO-20-seas deploy: DECIDED 2026-09-29, deploy pending.** COO.md
    records Gabe's "Theoretical only" (relayed from the peer session
    "seasonality evaluation next steps", COO.md 2026-09-29) as his
    in-the-moment deploy OK for exactly the WO-20-seas-final change: icw9_seas
    in Theoretical, the 9-factor blend in Today's Picks. It landed as 22f2c69.
    The integrator's landing run was worktree-isolated and could not run git in
    the main checkout, so live is still 4ab4363. **Open: a non-isolated
    integrator run to do the additive 10-path deploy** (HANDOFF-wo20-seas-final),
    with no Retrain ALL. Gabe then restarts Streamlit from a shell with
    `secrets.env` sourced and runs Retrain ALL himself.
25. **WO-21's benchmark/hedge question (Gabe; COO.md "WO-21 VERDICT",
    2026-09-28).** The post-2011 drag is a universe bet (§3.3). The COO
    recommends keeping SPY as the headline (the real alternative investment)
    and adding score-over-universe as a standing diagnostic. The IWM-hedged
    forward bet (WO-10) already tests the hedged product. A beta-matched
    (~0.8 × IWM) hedge variant would be a methodology change, so it is Gabe's
    call. Which forward formula to quote (net or gross selection minus the
    universe drag) is also left to the COO and Gabe by the WO-21 doc.
26. **Does the unfitted-read OK unblock an icw9_seas equity curve?
    (methodology, Gabe/COO).** The WO-20-seas doc (§5) keeps the Theoretical
    tab's 2007-2026 curve on icw8 because an icw9_seas curve "would compute on
    2020+ returns, which the spent hold-out forbids", and COO.md says moving it
    "needs a 2020+ read, Gabe". Gabe's 2026-09-27 standing OK allows unfitted
    2020+ reads, and the icw9_seas weights were fit on 2007-2019 only. The two
    sources disagree; this README doesn't decide which applies.
27. **Deploy WO-19 (key redaction) to live? (Gabe).** Landed 9e169ce; the
    live checkout still has the scripts that can print the key into job logs
    on a connection error (§4.7, §8.2). It is scripts only and needs no app
    change. Deploying needs Gabe's in-the-moment OK (still open in COO.md,
    2026-09-29).
28. **Two "WO-25"s and two hold-out read #7s (COO, 2026-09-29).** The LEDGER
    and the reweight branch's commit call the ICW v2 reweight "WO-25", and it
    logs its 2020-26 short-interest fit as hold-out read #7 (COO.md "Hold-out
    status"). COO.md's "WO-25 LAUNCHED" is the options-readiness work order,
    and it pre-assigns reads #7 and #8 to exp B and WO-O1. The COO should
    renumber one of each before either result lands. This README names them
    "ICW v2 reweight" and "WO-25 (options readiness)".
29. **WO-23 findings still open for Gabe (COO.md, 2026-09-29).** Beyond seas
    (settled by #24): short-interest weighting (the reweight fits it on
    2020-26, in flight), and landing WO-23 itself after Gabe sees it.

---

## 7. Repo map and reproduction

```
pipe_dream/
├── AGENTS.md, README.md          constraints / this file (readme-manager owns)
├── DATA-PIPELINE-HANDOFF.md      Round 11 point-in-time data build (2026-09-09)
├── final/                        THE ACTIVE PROJECT
│   ├── app/                      Streamlit dashboard (app-manager owns; see its README)
│   ├── src/                      pipeline
│   │   ├── reset2026/            factor composite (2026-09-18 onward), PREREGISTRATION.md;
│   │   │                         working_panel.py (v2 = working panel), refresh_working_panel.py,
│   │   │                         record_weekly.py, prediction_ledger.py, forward_hedge.py
│   │   ├── sweep/                XGBoost-era sweep harness, Rounds 12-20; RUNBOOK.md
│   │   ├── insider/              insider (SEC Form 345) signals, 2026-09-23
│   │   ├── sue/                  SUE / post-earnings drift screen, 2026-09-25
│   │   ├── seasonality/          seas screen (WO-18), live seas + side ledgers (WO-20-seas), 2026-09-26/27
│   │   ├── construction/         post-2011 drag decomposition (WO-21), 2026-09-27
│   │   ├── current_signal_pit.py        q75 + xrank live signal
│   │   ├── current_signal_composite.py  Theoretical tab (icw8 live; icw9_seas on integration)
│   │   ├── current_signal_blend.py      Today's Picks (frozen 9-factor leg, live and on integration; 10-factor seas code kept for the side ledger)
│   │   ├── execution.py          the one place a position is realized (Round 9)
│   │   └── build_*.py, sharadar_pull_*.py   data builders
│   ├── scripts/                  data acquisition, run on Gabe's machine (network)
│   ├── data/                     sharadar/, alphavantage/, options_unified/, benchmarks/ (mostly gitignored)
│   ├── out/                      panels, score caches, reset2026/ reports, signal CSVs
│   └── models/                   dated round docs (YYYY-MM-DD-*.md) + options workstream folders
├── src/, analysis/, out/         pre-reorg history, not in the active pipeline
└── options_raw/                  dolt clone of post-no-preference/options (8GB, gitignored)
```

**Environment:** conda env `pipe_dream` (`/opt/anaconda3/envs/pipe_dream/bin/python3`).
The base `anaconda3` env has a broken pandas/numpy ABI (APP.md, 2026-09-23).

**Reproduction, newest pipeline first.** Every network pull runs in Gabe's own
terminal. Sharadar, SEC EDGAR, yfinance, DoltHub and Alpha Vantage are
unreachable from agent sandboxes, and keys (`SHARADAR_API_KEY`,
`ALPHAVANTAGE_API_KEY`) never go in the repo.

| layer | how | source |
|---|---|---|
| Point-in-time Sharadar data, universe, feature panels, `td_data_sharadar/` | 9-step sequence (`sharadar_pull_pit_panel.py` … `export_sharadar_ohlc.py`) | [`DATA-PIPELINE-HANDOFF.md`](DATA-PIPELINE-HANDOFF.md) §3 |
| Factor composite: universe, factors, panel, outcome cache, backtest, reports | `downcap_universe.py` → `quality_factors.py` → `build_panel.py` → `build_outcome_cache.py` → `run_backtest.py` → `aggregate_report.py` | [reset doc](final/models/2026-09-19-factor-composite-reset.md) §7 |
| Composite corrections / audit | `model_audit.py`, `correction_variants.py`, `harness_check.py` | [physics](final/models/2026-09-22-composite-model-physics.md) §12, [corrections](final/models/2026-09-22-composite-model-corrections.md) §7 |
| Sweep harness (XGBoost era) | `python3 -m sweep.cli …` | [`final/src/sweep/RUNBOOK.md`](final/src/sweep/RUNBOOK.md) |
| Insider panel, screen, post-hoc (download 81 SEC quarterly zips first) | `build_insider_panel.py` → `screen_insider.py` → `posthoc_insider.py` | [insider results](final/models/2026-09-23-insider-congress-results.md) "Reproduction" |
| Down-cap grid v2 and its read-outs (nomination era only) | `build_downcap_grid_v2.py --all` → `downcap_grid_acceptance.py` → `downcap_v2_readout.py` → `noscore_control_v2.py`; insider re-test `build_insider_panel_v2grid.py` → `screen_insider_v2grid.py`. Optional SF1 top-up: `final/scripts/sharadar_downcap_pull.py` (key needed; added nothing) | [grid rebuild](final/models/2026-09-24-downcap-grid-rebuild.md); [no-score control](final/models/2026-09-24-noscore-control-v2.md); [insider v2](final/models/2026-09-24-insider-buyers-v2-grid.md) |
| v2 working-panel refresh + weekly forward records | `sharadar_pull_pit_panel.py --start <this month> --end <this month> --force` (the default skips the current month), then `refresh_working_panel.py --through latest --record-weekly` (`--check`, `--no-swap`, `record_weekly.py --plan` write nothing). 8 split-blocked tickers: `sharadar_downcap_pull.py --pull-list final/out/reset2026/downcap_v2/wo14_split_pull_list.csv` (8 calls; not run, and folding the CSVs in is a missing step; KITT, blocked since the 2026-09-26 Retrain, is not on that list) | [WO-14 doc](final/models/2026-09-25-wo14-v2-incremental-refresh.md) |
| Sharadar reference tables (`tickers_master.csv`, `actions.csv`), WO-17 | `final/scripts/sharadar_reference_refresh.py` (2 pulls, key from env only; builds from the dated backups, so a rerun just re-pulls; label hold-back for existing tickers), then `final/scripts/wo17_acceptance_report.py` (read-only). Not part of Retrain ALL; run by hand from the main checkout | [WO-17 doc](final/models/2026-09-26-wo17-reference-refresh.md) |
| SF1 incremental top-up (WO-16) | runs inside `refresh_working_panel.py`; standalone `python final/src/reset2026/sf1_topup.py` (key from the environment or `~/.config/pipe_dream/secrets.env`). Rollback: restore `sf1_fundamentals_through_2026-09-08.parquet` / `sf1_shares_through_2026-09-08.csv` before any refresh | [WO-16 doc](final/models/2026-09-26-wo16-sf1-topup.md) |
| IWM-hedged composite (nomination era) | IWM from yfinance (`auto_adjust=False`, plus Adj Close) into `final/data/benchmarks/IWM.csv` (gitignored), then `hedged_composite.py` → `hedged_tradable.py` (dividends from the Sharadar SEP panel's closeadj/close) | [hedged composite](final/models/2026-09-25-hedged-composite.md) §1.2, §3.6 |
| Forward hedged ledger | `forward_hedge.py record` / `selftest` / `score` / `status` (scoring needs `final/data/benchmarks/IWM_live.csv`, pulled after maturity) | [forward hedged icw8](final/models/2026-09-25-forward-hedged-icw8.md) §2, §4 |
| SUE screen | `build_sue.py` (about 1 min) → `validate_sue.py` → `hand_check_sue.py` → `screen_sue.py`; reads `sf1_fundamentals.parquet` (ARQ only) | [SUE screen](final/models/2026-09-25-sue-drift-screen.md) |
| SUE forward ledger (WO-15) | runs inside `record_weekly.py` (Retrain ALL / `refresh_working_panel.py --record-weekly`); standalone pull `python final/src/sue/sf1_eps_live_pull.py` (key from the environment only); `python final/src/sue/sue_forward.py score` / `status`; isolation harness `final/src/sue/wo15_isolation_test.py` (scratch copies only). Use the pipe_dream env | [SUE forward ledger](final/models/2026-09-26-sue-forward-ledger.md) §4-6, Addendum A |
| Composite, current spec (universe → factors → panel → outcomes → beta, then `ic_weighted_composite.py`, `prediction_ledger.py record/score`) | per the spec | [full spec](final/models/2026-09-22-composite-model-full-specification.md) §6 |
| AV options pull + unified chain + features | `av_options_pull.py` (retry-fixed 2026-09-27, WO-20; resume with `ALPHAVANTAGE_API_KEY=... AV_PULL_ARGS="--passes monthly --only-tier cap2000" zsh <checkout>/final/scripts/av_options_run_pull.sh` from a checkout that has the fix; it skips every ok/no_data row already logged), `build_option_chain_unified.py`, `build_option_chain_unified.py`, `build_av_options_features.py` | [AV spin doc](final/models/2026-09-22-alpha-vantage-spin.md) §C-E; [WO-20 doc](final/models/2026-09-27-av-pull-retry-fix.md) "Resuming" |
| Pre-2005 SEP for `seas` (WO-18, landed 0032ee3; data in the main checkout only) | `final/data/sharadar/sep_pre2005/` (SEP 1998-01..2005-01, 85 months, 12.9M rows, plus `_manifest.csv`; gitignored under `final/data/sharadar/`): `python final/src/seasonality/pull_sep_pre2005.py` (~17 min; needs `SHARADAR_API_KEY`) | [seasonality screen](final/models/2026-09-26-seasonality-screen.md); HANDOFF-worktree-agent-ad57ef9f38454d99d |
| `seas` screen (WO-18, nomination era) | `build_seas.py` → `hand_check_seas.py` → `screen_seas.py --validate` (harness reconcile) → `screen_seas.py`; `check_panel_swap.py` (in-era slice hashes) | [seasonality screen](final/models/2026-09-26-seasonality-screen.md) |
| Live `seas` + seas side ledgers (WO-20-seas, narrowed by 22f2c69; not deployed) | scored inside `current_signal_composite.py` via `seas_live.py` (the blend's `main()` no longer computes it; `blend_scores_at` does, for the blend_seas ledger) (`selftest`, `handcheck`); ledgers via `record_weekly.py`, or `seas_forward.py plan` / `score` / `status` / `selftest`; checks `wo20_frozen_backtest.py`, `wo20_blend_seas_backtest.py`, `wo20_isolation_test.py` (scratch store) | [WO-20-seas doc](final/models/2026-09-27-wo20-seas-live.md) §1-4, §6; [seas Theoretical-only](final/models/2026-09-29-seas-theoretical-only.md) "Checks" |
| Post-2011 drag decomposition (WO-21) | `python final/src/construction/drag_decomp.py --validate` (reconcile only), then without the flag (writes `final/out/construction/drag_decomp.json`; it writes to the main checkout) | [construction drag](final/models/2026-09-27-construction-drag.md) |
| Key-redaction test (WO-19) | `python final/scripts/test_wo19_key_redaction.py`, run directly and **not under pytest** (it patches `socket.connect` and `requests.get` at import) | [WO-19 doc](final/models/2026-09-27-wo19-key-redaction.md) |
| Live signals | `current_signal_pit.py`, `current_signal_composite.py`, `current_signal_blend.py` (the app's "Retrain ALL" runs them) | `final/app/README.md` |
| Older gitignored paths (yfinance `td_data_local/`, EDGAR `fundamentals_raw/`, DoltHub options exports, GARCH, pre-Round-11 panels) | per-path commands | `git show integration:AGENTS.md` at 29eb67b, "Reproducing every gitignored path" (historical copy, see §Superseded) |

**Not reproducible (2026-09-26, WO-15/WO-16/WO-17):** these are gitignored vendor
snapshots or append-only logs, and no re-pull recreates them. Don't delete
them. `final/data/sharadar/sf1_fundamentals_through_2026-09-08.parquet` (SUE's
first basis reference and WO-16's rollback file), `sf1_shares_through_2026-09-08.csv`,
every dated `sf1_arq_eps_live_<pulled_at>.parquet` backup (each accepted pull
is the next run's reference), and `sf1_arq_eps_live_accepted.csv`. Also
(WO-17) `tickers_master_through_2026-09-08.csv` and
`actions_through_2026-09-10.csv`: the vendor now clamps `firstpricedate` at
1997-12-31 and re-dates `relation` rows, so a re-pull can't recreate them,
and the refresh builds from them.

**Older known gaps, still open** (from AGENTS.md "Known gaps", 2026-09-02/04,
not superseded by anything newer):

- `final/models/final_model_calls.pkl` / `final_model_puts.pkl` have no direct
  reproduction script. They stay tracked in git on purpose.
  `final/models/pit_integration/` is the validated substitute.
- `build_training_data_expanded.py` and its related expanded-universe options
  scripts were never confirmed present. Check before assuming they exist.
- The app's "Retrain" buttons don't refresh the raw EDGAR/Sharadar
  fundamentals pulls. Those run separately on Gabe's machine.
- Several `.DS_Store` files are tracked (a one-time `git rm --cached` for Gabe
  or the integrator).
- The sweep-era idea backlog, unprioritized since the reset (from AGENTS.md
  "Future plans", 2026-08-30/09-01): stop-limit exits, time-series foundation
  models for the options distribution, per-stock behavioral transition
  matrices, MoSeq-style "syllables", and per-ticker "Wins Above Replacement".
  Confirm priority with Gabe or the COO first.

---

## 8. Lessons and landmines: read before adding a feature

### 8.1 Bugs that passed every automated check (deduplicated)

| bug | how it presented | what caught it | source |
|---|---|---|---|
| Survivorship-determined universe (Round 11) | 2008 pool missing a third of names, 89% of them dead | naming companies that should be there (Apple, Wachovia) | DATA-PIPELINE-HANDOFF §1 |
| $10 floor on split-adjusted close | excluded Apple ($5.98 adjusted) from 2008 | named company | same |
| Reissued symbols (41 of 264 gap files) | wrong-issuer bars | identity map | same |
| `--refresh-recent` splice (Round 9) | fake one-day crash in MNST/PRIM, the *live* signal | adjustment-factor check | integration AGENTS.md Round 9 |
| Delisted OHLC basis mismatch (Round 9) | stops barely fired on gap tickers | `close` outside `[low, high]` | same |
| NaN ranking (R13) | `argsort` put NaN last, so an empty column got top ranks | asking what an empty column should score | sweep RUNBOOK §6 |
| NaN era split (R14) | one NaN made an era "no estimate" | asking why it was missing | same |
| Breadth estimator (R15) | reported 19.1 where the truth was 5.0 | `capture > 1` is impossible | same |
| `merge_asof` alignment (R16) | `.sort_index()` no-op, six columns on the wrong rows | fire rate 0.7% vs 64% expected | same |
| Empty feature list / inf in features (R17) | "no windows", dead cells | noticing *nothing* ≠ *no signal* | same |
| Live label basis `_trd_` (R18) | live trained on close-to-close | field-by-field diff vs the cell id | round18 AGENTS.md R18 |
| "Candidate pool" fix, **retracted** (R18) | admitted NaN-vol names, and `_bucket_idx` filed them in the lowest-vol bucket | Gabe reading the picks | same; APP.md |
| `downcap_universe.py` `closeunadj × split-adjusted volume` | inflated past dollar volume for later splitters | AAPL 2008 $162B/day | AV spin doc §B |
| Survivorship-selected down-cap grid | 52% of cap150-only rows are future winners | pool-integrity check, 62.85% | AV spin doc §A |
| IC-weighted score without renormalising | missing-factor rows compressed | re-run after the fix | corrections §12 |
| Sector-neutral t from demeaning the factor only | insider buyers t +3.10 "within sector"; both sides demeaned gives 0.65 | fire rate vs sector return, corr −0.79 | insider results §3 |
| `build_insider_panel.py` min of `TRANS_DATE` as a string (**fixed 2026-09-24**, WO-8) | "04-MAR-2008" sorted before "11-FEB-2008"; 17 of 320 validation rows mismatched; 25,081 event rows wrong | live-vs-bulk Form 4 validation | forward ledger doc §5c and "Implementation fix 2026-09-24" |
| Main-checkout builder swapped to float32 (a risk, **resolved 2026-09-26**: the landed builder writes float64) | `market_cap` differs from `composite_panel` in 43,250 of 43,743 sampled rows; float32 would have changed 216,864 `market_cap` values | WO-6 naming its reproduction target explicitly; bit-identity check at landing | [grid rebuild](final/models/2026-09-24-downcap-grid-rebuild.md); COO.md; LEDGER landing log d7d257d |
| AV pull `IncompleteRead` not retried (**fixed 2026-09-27**, WO-20, f380817; the live `bin/` copy is still unfixed) | bulk pull died after monthly 2010-08-18 | `pull.out` traceback | [WO-20 doc](final/models/2026-09-27-av-pull-retry-fix.md) "What broke" |
| LCID "bug", **retracted** | adjusted vs raw price compared | split-signature scanner | corrections §6d |
| v2 `eligible_cap*` flags include SPACs | a SPAC at trust value has `volatility_60` near 0 and would top an inverse-vol book; 19 cap150 SPAC rows on 2026-09-08 | WO-11 tracing why every v2 measurement dropped them at analysis time | [v2 working panel](final/models/2026-09-25-v2-working-panel-switch.md) §1 |
| `sharadar_pull_pit_panel.py` skips months already on disk | the current month was never re-pulled, so every Retrain was a no-op for September | WO-14 | [WO-14 doc](final/models/2026-09-25-wo14-v2-incremental-refresh.md) |
| Weekly hook recorded an open ISO week (W39 at 09-24) | a daily Retrain could lock in a mid-week date | WO-14 disclosing its own deviation | same, "Deviation, disclosed" |
| `FF.main()` called after the reset renamed it to `build()` (**fixed 2026-09-26**, WO-16) | the first real v2 refresh with a new SEP day would have crashed with AttributeError; the live checkout carried it from 6a1823d to 500a4a5 | WO-16 reading the refresh code path | [WO-16 doc](final/models/2026-09-26-wo16-sf1-topup.md) §2 |
| SF1 restatements are logged, not applied (WO-16 append-only, by design) | after a reverse split, `market_cap` and `net_issuance_pct` are off by the split ratio until the next filing (e.g. RML 67x, looks like a vendor share-count error); none eligible on 2026-09-24 | WO-16 share-basis screen | same, Addendum; `sf1_topup_restatements.csv` |
| A SUE basis-validation STOP would have halted **all** weekly records (WO-15 §5 as pre-registered: "if SUE cannot be recorded, nothing is written") (**fixed 2026-09-26**, Addendum A0) | the first live pull hit 15 unexplained tickers; every later pull would keep failing against the frozen 09-08 file, wedging v3/ext/hedge from W40 | the WO-15 worker at the first live pull; the isolation harness then found 2 more paths (plan/import, post-record sidecar) | [SUE forward ledger](final/models/2026-09-26-sue-forward-ledger.md) Results, Addendum A |
| Sharadar `requests` exception text carries `api_key` (**fixed on integration 2026-09-27**, WO-19, 9e169ce; not deployed) | a connection error printed the full URL, key included, into job logs, although every script already passed the key via `params=` | the app manager noticing it on screen (2026-09-26); WO-19's offline test (10 of 13 pre-fix copies leak) | [WO-19 doc](final/models/2026-09-27-wo19-key-redaction.md) |
| `actions.csv` covers only 2025-09-09 onward (through 2026-09-29 since WO-17) | no 2007-2019 dividends (and no pre-2025 splits) | WO-9 inspecting it before use | [hedged composite](final/models/2026-09-25-hedged-composite.md) §3.6 |

**Standing rule** (Round 16/17): verify by naming what should be there, with
explicit expected values, not by counting. Distribution checks can't detect a
permuted row.

### 8.2 Rules that bind new work

- **Pre-register before running.** Gates don't move after a result. Composite
  work goes in `final/src/reset2026/PREREGISTRATION.md` (protected, append-only)
  or its own dated pre-registration doc.
- **Grid offset.** Average over all 40 offsets. Offset 0 alone flips weak
  features (`momentum_20` flips on 16/40) (`check_grid_offset.py`).
- **Feature admission (XGBoost track):** beat the 80th percentile of a
  within-date **shuffle** null. A shuffled noise column once produced the best
  backtest in the grid (3.309×). Never quote an improvement without its null.
- **Leave-one-year-out** is never relaxed. A result concentrated in one year has
  a near-zero forward expectation.
- **Run `concentration_monitor.py`** on any new backtest's picks, and
  `price_adjustment_scanner.py` before calling a price series a bug.
- **Live script = backtest cell, field by field.** Trace a backtest's data to
  where it is *loaded*, not where it is used.
- **`current_signal_blend.py` hardcodes `MAIN_ROOT` to the main checkout**
  and puts its `src/` and `reset2026/` on `sys.path` first. Importing it from a
  worktree can silently pick up the main checkout's stale `composite.py`
  (corrections §19 row 3; ledger landing log). Don't import it for analysis.
- **Sector-neutral numbers:** `neutralize_on_sector` demeans only the
  factor. When a factor's sector concentration tracks sector returns, the
  result looks like within-sector skill but isn't (insider round). Whether
  to report both-sides numbers as standard is pending (Open conflicts #8).
- **Name the grid.** Two down-cap grids exist (v1 survivorship-selected, v2
  safe; §3.3 footnote). Every cap150/cap500 number must say which one.
  cap2000 is identical on both.
- **Insider re-runs read the fixed events.** Since WO-8, `posthoc_insider.py`
  and `screen_insider.py` read the regenerated `insider_events.parquet`. To
  reproduce the published 2026-09-23 numbers, use
  `out/insider/insider_events_prefix_2026-09-24.parquet`.
- **Read through `working_panel.py`.** Live and forward code uses
  `W.working_cross_section` (v2 plus the SPAC rule, applied **before** scoring,
  because `rank_z` ranks the whole cross-section). The old-grid ticker list is
  frozen in `old_grid_tickers_4011.txt`, not read from `composite_panel.parquet`,
  which the app's Retrain rewrites. Don't re-derive the frozen ICW weights or the
  FM slope on v2.
- **Forward ledgers are append-only.** Never rewrite a record. Late
  (`recorded_late`) and `incomplete_week` records are descriptive and never
  counted. `record()` refuses to change an existing manifest entry.
- **Price basis.** Books and SPY are split-adjusted, price-only. A benchmark
  must match that basis, with dividends measured separately on both legs (WO-9
  ITERATE #1). A total-return benchmark against a price-only book understated
  WO-9 by about IWM's yield.
- **`decile_volq` pulls in pending-deal names.** Low-vol bucket 0 fills with
  pinned-price acquisition targets (SLAB, RAMP, PEN: 7.4% of the 2026-09-08
  book), so their return is a deal spread. It's a known property, not a data
  error (WO-10 §4).
- **Hedge or benchmark the universe leg.** On v2 the eligible small-cap
  universe lagged SPY by about 2pp/yr after 2011 (WO-7). Report a long-only
  small-cap book against its own no-score universe as well as SPY and USMV.
- **Never admit NaN-feature names to a scored pool.** `_bucket_idx` sends NaN
  vol to the lowest-vol bucket. The fix touches `simulate()`, so it's Gabe's
  call.
- **The decision bar** (Project doc `claude/validation-gates.md`, 2026-09-12)
  replaces Gate B's t > 3 for deployment questions. Deploy when the
  expected excess return is positive after costs and the downside is
  understood. **Gate A (placebo, look-ahead, pool integrity) is unchanged
  and absolute.**
- **`build_app_benchmarks.py`** is the one tool allowed to touch the
  hold-out, and only for its hard-coded list of two already-spent cells.
  Never add a cell "to see how it does".
- **Unpaired decile t-stats:** at `decile_volq_excess`, order-free shuffle
  series reach median |t| 1.66 and max 3.86. A decile screen read against a
  ±2 bar is using a null roughly twice as wide as it looks (Round 19).
- **Calibration:** in a zero-signal grid, 27% of configs beat the market and
  the best reached 2.577×. One config beating SPY is evidence of nothing.

- **WO-15 / live SUE landmines (2026-09-26,** WO-15 handoff; COO.md):
  - Never prune the dated `sf1_arq_eps_live_<pulled_at>.parquet` backups.
    They are the rolling validation reference: a missing reference skips SUE
    every week until it is restored. Never modify
    `sf1_fundamentals_through_2026-09-08.parquet` (the first reference,
    asserted 631,185 rows).
  - The Retrain shell needs `SHARADAR_API_KEY`, or the SUE pull fails and SUE
    is skipped (logged) every week; v3/ext/hedge are unaffected. Streamlit
    must be launched from a shell that has the key (project memory,
    `reference_sharadar_api_key.md`).
  - **Sharadar scripts can write the API key into job logs; fixed on
    integration (WO-19, 9e169ce), NOT in the live checkout.** The route is
    `requests` exception text, which carries the full URL including
    `api_key`, reaching stdout, a RuntimeError or a traceback on a connection
    error. The live copies of `sharadar_pull_pit_panel.py` (run by Retrain
    ALL) and 10 other Sharadar scripts still do this until deployed (§6 #27).
    `sf1_topup.py` and `sf1_eps_live_pull.py` were already safe. The app
    redacts on screen only. A 2026-09-27 scan of the live `final/app/logs`
    found no key. New Sharadar code: never print raw exception text; use a
    scrub like `_scrub()` / `scrub()` and `from None`.
  - Base anaconda's pandas is broken. Use the pipe_dream env
    (`/opt/anaconda3/envs/pipe_dream/bin/python`). The live Retrain uses
    `sys.executable`, so it is unaffected (Streamlit runs in the pipe_dream
    conda env; LEDGER db13243 verify line).
  - The live SUE file `sf1_arq_eps_live.parquet` is separate from
    `sf1_fundamentals.parquet`. One pull is one split basis: never splice or
    union them.
  - A run that returns rc 1 after a failed SUE sidecar step (guard log,
    annotation, accepted-pull log) has still written v3/ext/hedge; read the
    reason before rerunning.
  - `sf1_arq_eps_live_accepted.csv` and `ledger_sue_guard_log.csv` are
    append-only (in the prefix-hash set).
- **Seasonality landmines (WO-20-seas, 2026-09-27; apply once deployed;**
  [WO-20-seas doc](final/models/2026-09-27-wo20-seas-live.md) §1, §5;
  HANDOFF-worktree-agent-a790eb27c4530aa0a):
  - **The Theoretical scorer fails outright, with no fallback,** if `seas`
    coverage is below 60% (`SEAS_MIN_COVERAGE`) or a SEP month file is
    missing. Since 22f2c69 Today's Picks no longer computes `seas`, so this
    can't stop the live primary; the blend_seas side ledger is isolated.
  - **SEP price-basis mix from about 2027-08.** `closeadj` is rebased at each
    pull, and the 2026-09 month file was re-pulled 2026-09-26 on a different
    basis. Live `seas` starts reading that month around 2027-08, and
    `basis_flag` in the composite meta will show it. It must be fixed before then.
  - The seas side ledgers pair against v3 through the record-time panel
    backup: the 09-26 refresh added 5 names to past cross-sections, so v3's
    past records don't pair against the current panel.
  - "WO-20" names two things (the AV retry fix f380817, and the seas deploy).
    Read ledger rows by worktree, not by WO number.
- **Random-book nulls carry their own turnover cost (WO-21).** A within-date
  shuffle null is redrawn every rebalance (name turnover ~0.9 vs the live
  book's ~0.2), so at 15bp it pays about 0.67%/yr more than the live book.
  Net selection over such a null overstates the ranking's gross edge by that
  amount (post-2011: net +2.78, gross +2.10). Quote both.
- **WO-17 / reference-table landmines (2026-09-26,** [WO-17 doc](final/models/2026-09-26-wo17-reference-refresh.md); COO.md):
  - The next `refresh_working_panel.py` (Retrain ALL) adds new DOMESTIC
    tickers as `new_tickers`, and `splice` writes their rows on every date,
    including dates already stored. 26 have SEP rows after 09-08; 14 of those
    have marketcap ≥ $150M; 10 of the 26 are SPACs, dropped at read time.
    Existing rows and the ledger CSVs are untouched.
  - The vendor now clamps `firstpricedate` at 1997-12-31 for 7,860 tickers.
    If the Sharadar plan's history window changed, full-history SEP re-pulls
    may come back truncated. Check before any full-history re-pull.
  - Don't overwrite the dated backups (`tickers_master_through_2026-09-08.csv`,
    `actions_through_2026-09-10.csv`): the refresh builds from them (§7).
  - Held-back labels mean a reused ticker keeps the old company's labels
    (new RML, HYAC.U); see §6 #18.

### 8.3 Certified dead ends (COO.md, 2026-09-26). Reopen only with the stated reason

Old XGBoost stock selection · fundamentals as a selection signal (R13) ·
rate-sensitivity features (R14) · breadth via book size/horizon (R15/15b) ·
path-order / `accel_20` (R19; an 8th trial is not allowed) · IC as a feature
gate · the old HMM gate (until Gabe says why it was dropped) · earnings
proximity as a stage-2 rule · composite `decile1_volq` · options: long calls,
long puts, buy/no-buy gate + ATM, 60-day, ~2-day/0DTE, LEAPS, GAM hurdle · AV
EARNINGS/ESTIMATES/INSIDER/NEWS as backtest features · **insider plain
counts** (`ins_buyers_90`/`ins_sellers_90`, cap150, h=40; no 30/180-day,
value, cluster or size variants; the down-cap reopen condition **was used** by
WO-4 on 2026-09-24, DEAD, so the insider family k=4 is spent and reopens only
on forward data) · **"down-cap breadth improves the composite" / "monotonic
in cap"** (WO-6, 2026-09-24; reopen only for a factor whose premium is
specifically small-cap, tested on v2) · **congress as a backtest factor** (forward-only) · **the
earnings-timing family** (6 trials, closed 2026-09-23 by the 8-K test; reopen
only with point-in-time *announced* dates, tested forward). Screened
negative but not certified by the COO: Amihud illiquidity, book-to-market
(wrong-signed), exponent transform, `fcf_yield`, `profitability_trend`,
regime conditioning (stopped by its own staging rule).

---

## 9. Doc index

Dates come from filenames, else the doc, else the last commit. "Landed" means
the file is on `integration`.

| doc | date | status | one line |
|---|---|---|---|
| [`AGENTS.md`](AGENTS.md) | 2026-09-23 | landed | standing constraints + pointer |
| [`DATA-PIPELINE-HANDOFF.md`](DATA-PIPELINE-HANDOFF.md) | 2026-09-09 | landed | Round 11 point-in-time Sharadar rebuild, reproduction, acceptance tests |
| [`final/src/sweep/RUNBOOK.md`](final/src/sweep/RUNBOOK.md) | 2026-09-18 (commit) | landed | sweep package, Rounds 12-19, shuffle-null gate, bug ledger (§10 git rule stale) |
| [`final/models/2026-09-17-model-architecture-research.md`](final/models/2026-09-17-model-architecture-research.md) | 2026-09-17 | landed | 15 ranked model-architecture options |
| [`final/models/2026-09-17-new-data-sourcing-research.md`](final/models/2026-09-17-new-data-sourcing-research.md) | 2026-09-17 | landed | 15 ranked data sources; Gabe approved the top 5 order |
| [`final/models/2026-09-19-factor-composite-reset.md`](final/models/2026-09-19-factor-composite-reset.md) | 2026-09-19 (+09-22 correction) | landed, protected | the reset: model, results, survivorship audit, reproduction |
| [`final/src/reset2026/PREREGISTRATION.md`](final/src/reset2026/PREREGISTRATION.md) | 2026-09-18 → 09-22 | landed, protected | append-only record of every composite decision and spend; "Future avenues (2026-09-19)" section landed with the reset branch (d7d257d) |
| [`final/out/reset2026/REPORT_nominate.md`](final/out/reset2026/REPORT_nominate.md), [`REPORT_holdout.md`](final/out/reset2026/REPORT_holdout.md) | 2026-09-19 | landed; **stale** (9(8)-factor, pre-`asset_growth` drop, pre-survivorship finding) | offset-averaged headline tables |
| [`final/models/2026-09-22-composite-model-physics.md`](final/models/2026-09-22-composite-model-physics.md) | 2026-09-22 | landed | physics-style audit of the composite (§6 recommendation refuted by corrections §1) |
| [`final/models/2026-09-22-composite-model-corrections.md`](final/models/2026-09-22-composite-model-corrections.md) | 2026-09-22 → 09-23 | landed (§0-19) | corrections, LCID retraction, beta term, safeguards, IC weighting, extensions, turnover, third hold-out spend, options overlay, §19 cross-model MIDDLE |
| [`final/models/2026-09-22-composite-model-full-specification.md`](final/models/2026-09-22-composite-model-full-specification.md) | 2026-09-22 | landed | clean spec of the IC-weighted 8-factor composite: start here (§4 lacks the survivorship caveat; §6 points to the old AGENTS.md table) |
| [`final/models/2026-09-22-alpha-vantage-spin.md`](final/models/2026-09-22-alpha-vantage-spin.md) | 2026-09-22 | landed | AV coverage, options pull, **down-cap survivorship finding** |
| [`final/scripts/AV_PULL_WINDOWS.md`](final/scripts/AV_PULL_WINDOWS.md) | 2026-09-23 (WO-20 line 2026-09-27) | landed | moving the AV pull to Windows; the 2026-09-27 line records the retry fix and a resume command |
| [`final/models/2026-09-22-session-handoff.md`](final/models/2026-09-22-session-handoff.md) | 2026-09-22 | landed (d7d257d) | blend promotion (UI part superseded by 10bfb19), query fix, retrain speedup (its float32 builder not taken) |
| [`final/models/2026-09-23-insider-congress-preregistration.md`](final/models/2026-09-23-insider-congress-preregistration.md) | 2026-09-23 | landed | insider k=2 trials, congress ruled untestable before any return |
| [`final/models/2026-09-23-insider-congress-results.md`](final/models/2026-09-23-insider-congress-results.md) | 2026-09-23 | landed | insider counts fail; sector-neutral artefact; opportunistic-buyer lead; congress forward-only |
| [`final/models/2026-09-23-earnings-announcement-premium-8k.md`](final/models/2026-09-23-earnings-announcement-premium-8k.md) | 2026-09-23 | landed | WO-5: 8-K Item 2.02 EAP, DEAD; closes the earnings-timing family (Part 2 "Reading" first sentence struck by the COO) |
| [`final/models/2026-09-23-forward-ledger-leverage-opportunistic-buyers.md`](final/models/2026-09-23-forward-ledger-leverage-opportunistic-buyers.md) | 2026-09-23/24 (+09-26 addendum, ddb2773) | landed | WO-2+3: forward pre-registration of icw9 leverage and opportunistic buyers; first blind record 2026-09-08; TRANS_DATE bug and its WO-8 fix (2026-09-24 section) |
| [`final/models/2026-09-24-downcap-grid-rebuild.md`](final/models/2026-09-24-downcap-grid-rebuild.md) | 2026-09-24 | landed | WO-6: survivorship-safe v2 grid, BUILD SUCCESS; icw8 cap150 +5.25 → +2.85%/yr; flat across tiers |
| [`final/models/2026-09-24-noscore-control-v2.md`](final/models/2026-09-24-noscore-control-v2.md) | 2026-09-24 | landed | WO-7: SELECTION MATERIAL on v2; universe −0.25 vs SPY; +0.00 vs SPY on 2011-10-20..2019 |
| [`final/models/2026-09-24-insider-buyers-v2-grid.md`](final/models/2026-09-24-insider-buyers-v2-grid.md) | 2026-09-24 | landed | WO-4: plain insider buyers on v2, DEAD; insider family k=4 spent |
| [`final/models/2026-09-25-hedged-composite.md`](final/models/2026-09-25-hedged-composite.md) | 2026-09-25 | landed (e11d37e) | WO-9: IWM-hedged composite, MIDDLE (price-only 2011-19 +0.92; tradable +1.08); COO LOYO ruling; ITERATE #1 dividends |
| [`final/models/2026-09-25-v2-working-panel-switch.md`](final/models/2026-09-25-v2-working-panel-switch.md) | 2026-09-25 | landed (8f47808) | WO-11: v2 is the working panel; SPAC rule; which readers switched; ledger manifest; v1-vs-v2 overlap (its §4 "no refresh path" is superseded by WO-14) |
| [`final/models/2026-09-25-forward-hedged-icw8.md`](final/models/2026-09-25-forward-hedged-icw8.md) | 2026-09-25 | landed (8f47808) | WO-10: forward IWM-hedged icw8 bet, pre-registration pinned by hash, first record 2026-09-08 (its C10 "cadence pending" is superseded: weekly) |
| [`final/models/2026-09-25-forward-hedged-icw8.PREREG-PREIMAGE.md`](final/models/2026-09-25-forward-hedged-icw8.PREREG-PREIMAGE.md) | 2026-09-25 | landed | byte-exact pre-image of WO-10 §1-2 (sha256 29438c7a…) |
| [`final/models/2026-09-25-sue-drift-screen.md`](final/models/2026-09-25-sue-drift-screen.md) | 2026-09-25 | landed (026e3b7) | WO-13: SUE/PEAD pre-registration and results, PASS-nomination |
| [`final/models/2026-09-25-wo14-v2-incremental-refresh.md`](final/models/2026-09-25-wo14-v2-incremental-refresh.md) | 2026-09-25 | landed (f0e750a) | WO-14: v2 refresh builder, acceptance, split-blocked tickers, weekly-record rules and first run, WO-10 addendum |
| [`final/models/2026-09-26-wo16-sf1-topup.md`](final/models/2026-09-26-wo16-sf1-topup.md) | 2026-09-26 | landed (defcc23) | WO-16: SF1 append-only top-up pre-reg + results, 7-day window, `FF.main()` fix, full-grid rehearsal, share-basis screen, deploy coupling and rollback |
| [`final/models/2026-09-26-sue-forward-ledger.md`](final/models/2026-09-26-sue-forward-ledger.md) | 2026-09-26 (pre-reg 9dc2d03; Addendum A c69b942) | landed (6ac64e6) | WO-15: icw9_sue forward ledger pre-registration (frozen weights, kill rule), first live pull (STOP at basis validation), Addendum A (isolation, uniform-ratio check, 1% cap, rolling reference, W38/W39 declined). Its §4 "ends 2026-09-08" for `sf1_fundamentals.parquet` predates WO-16 |
| [`final/models/2026-09-26-wo17-reference-refresh.md`](final/models/2026-09-26-wo17-reference-refresh.md) | 2026-09-26 (pre-reg 7dd8066; Addendum A 134fbf5; results f88ae19) | landed (a9344ef) | WO-17: tickers_master/actions refresh, label hold-back (+`firstpricedate`), SUCCESS; acceptance (a)-(d), named checks, split-blocked 8 stay blocked, WO-15 coupling. Its consumer table's "`sue_forward.py` (WO-15, not landed)" and "Recheck WO-15 before it deploys" predate the 562dab9 deploy (§6 #17). Reports in `final/out/wo17/` |
| [`final/models/2026-09-26-seasonality-screen.md`](final/models/2026-09-26-seasonality-screen.md) | 2026-09-26 (pre-reg 51795c9; results a7aa44e; panel-swap check 74e6e03, 2026-09-27) | landed (0032ee3, via WO-20-seas) | WO-18: Heston-Sadka `seas` pre-registration + Results, PASS-nomination (7 gates), caveats, panel-swap verification |
| [`final/models/2026-09-27-av-pull-retry-fix.md`](final/models/2026-09-27-av-pull-retry-fix.md) | 2026-09-27 (7b16662) | landed (f380817) | WO-20: why the AV pull died (IncompleteRead is an HTTPException), the retry fix, offline test, how to resume |
| [`final/models/2026-09-27-wo19-key-redaction.md`](final/models/2026-09-27-wo19-key-redaction.md) | 2026-09-27 (7b77ba4) | landed (9e169ce), not deployed | WO-19: how the Sharadar key reached job logs (exception text), per-file audit and `_scrub()` fix, offline leak test |
| [`final/models/2026-09-27-wo20-seas-live.md`](final/models/2026-09-27-wo20-seas-live.md) | 2026-09-27 (999db67; Addendum A 56afb05) | landed (0032ee3), not deployed; blend half superseded by 22f2c69 | **WO-20-seas** (the doc's title says "WO-20"): Gabe's two seas decisions, live `seas`, icw9_seas weights and in-sample backtest, the 10-factor blend (2.52 → 2.40), the two pre-registered monitoring ledgers, what is blocked; Results section empty until records exist |
| [`final/models/2026-09-27-construction-drag.md`](final/models/2026-09-27-construction-drag.md) | 2026-09-27 (pre-reg 74c73ca; results fb78673; follow-up e78a139, 2026-09-28) | landed (e05faea) | WO-21: pre-registered decision map, reconcile gates, post-2011 drag = universe −1.99 + construction −0.77 (costs −0.87), UNIVERSE BET, per-year table, OLS on SPY and IWM |
| [`final/models/2026-09-29-seas-theoretical-only.md`](final/models/2026-09-29-seas-theoretical-only.md) | 2026-09-29 (161db4b) | landed (22f2c69), deploy pending | **WO-20-seas-final**: Gabe's "Theoretical only"; blend back on `blend_q75_ew9_2026-09-19`, 10-factor seas blend side-ledger only; the one-file change and its checks (picks identical, max diff 0.0; AppTest) |
| `worktree-wo23-model-audit:final/models/2026-09-27-model-audit.md` | 2026-09-27/28 (pre-reg 8a58c88; results c9ba394; 9106bef) | in flight (committed, not landed) | WO-23: model audit pre-registration and results, periods A/B, flags F1/F2, seas removal plan S1-S3, hold-out read #5 |
| `worktree-wo24-construction-drag:final/models/2026-09-28-construction-drag-2020s.md` | 2026-09-28/29 (pre-reg b63582d; results 06a76c2) | in flight (committed, not landed) | WO-24: WO-21's drag decomposition on 2020-26, hold-out read #6 |
| `worktree-agent-aa9609e4d8a64a036:final/models/2026-09-29-icw-v2-reweight.md` | 2026-09-29 (method pin 0aa87b4) | in flight (committed, not landed) | ICW v2 reweight ("WO-25" in the ledger): method pin, SI weight fit on 2020-26 |
| [`final/app/README.md`](final/app/README.md) | 2026-09-24 (commit) | landed; header stale vs the 10bfb19 app.py (app-manager) | how to run the app, tab guide |
| [`final/models/pit_integration/README.md`](final/models/pit_integration/README.md) | 2026-09-02 | landed | options PIT-integration reproduction |
| [`final/models/hyperparameter_retune/README.md`](final/models/hyperparameter_retune/README.md) | 2026-09-02 | landed | options Tweedie/GAM retune |
| `round18-app-two-models:Claude outputs/RUNBOOK.md` | 2026-09-09 | superseded (self-labelled) | Round 12-only runbook |
| `round18-app-two-models:AGENTS.md` | 2026-09-16 | not landed; absorbed here | Rounds 9-19 narrative |
| `~/.claude/pipe_dream-coordination/` LEDGER.md, COO.md, APP.md, HANDOFF-*.md | 2026-09-23 → 09-28 | outside git | who's doing what; research verdicts; app state |
| `~/.claude/projects/-Users-ggraham-pipe-dream/memory/*.md` | 2026-09-17 → 09-27 | outside git | Gabe's recorded decisions (foundation reset, data priorities, meta-model roadmap, don't-relitigate, blend preference, unfitted hold-out reads OK) |
| Project docs (`claude/validation-gates.md`, `backtest/*`, `models/*`, `universe/*`) | 2026-08 → 09-16 | Claude Project, not in repo | the pre-reset narrative. Gates: the DECISION BAR (2026-09-12) |

---

## Superseded

Old claim, its source and date → what replaced it, with source and date.

- The q75 / PIT "augmented + 15% stop" model is primary at $10k → $214,606 (AGENTS.md workstream 4, 2026-09-02) → corrected execution gives $25,299 vs SPY $55,597 (AGENTS.md Round 9, 2026-09-07), and then the rebuilt data gives 1.00x vs SPY 5.23x (DATA-PIPELINE-HANDOFF, 2026-09-09).
- The v4 XGBoost/LSTM "Secondary Models" tab, XGBoost +21.54%/trial (AGENTS.md workstream 1, 2026-08-27) → tab removed; the pre-Round-11 universe was defective (app README / round18 AGENTS.md Round 18, 2026-09-16).
- The HMM-gated blend is primary (pre-2026-09-02) → retired, "we are no longer using the HMM" (AGENTS.md workstream 2, 2026-09-02). Reason unrecorded (COO decision #1).
- Options calls show a real edge, +11.43%/+7.28% (AGENTS.md workstream 3, 2026-09-02) → calls baseline flat, Kelly −0.16% monthly n=74 (AGENTS.md 2026-09-04 rebuild).
- Options universe built from today's roster (AGENTS.md Known gaps, 2026-09-04) → closed for 2008+ by AV `HISTORICAL_OPTIONS` as-traded symbols (AV spin doc, 2026-09-22). The DoltHub-based puts lead still carries it.
- "Treat Round 12 top-5 breadth as confirmed on the hold-out" (Round 13) → hold-out spent (round18 AGENTS.md, 2026-09-12) → hold-out refreshed for the reset (memory, 2026-09-18) → read three times for the composite (2026-09-19/22).
- IC `|t|` gates feature admission (sweep era) → shuffle null at the 80th percentile (sweep RUNBOOK §9, 2026-09-16).
- The deployed model is the 24-column XGBoost q75 (app README, 2026-09-16) → stock model restarted as a linear factor composite (memory / reset doc, 2026-09-18/19). q75 stays displayed by Gabe's decision.
- 9-factor equal-weight composite incl. `asset_growth` (reset doc, 2026-09-19) → 8 factors, `asset_growth` dropped (PREREGISTRATION "Factor-set decision", 2026-09-22). The candidate tab uses IC-shrinkage weights (composite meta, 2026-09-22).
- "9 factors" in the nomination era (reset doc, 2026-09-19) → 8 active before 2020 (`short_interest_days_to_cover` 0% coverage) (physics doc §2, 2026-09-22).
- Nomination +3.75%/yr "monotonic in cap", "no survivorship bias found" (reset doc §3.1/§4, 2026-09-19) → the down-cap grid is survivorship-selected, and these results are unreadable (AV spin doc §A, 2026-09-22).
- Physics doc §6: buy deciles 1-3 / avoid decile 0 (2026-09-22) → `decile1_volq` −0.83%/yr, refuted (corrections §1, 2026-09-22).
- Physics doc §9.1: value is the strongest omission (2026-09-22) → book-to-market wrong-signed, IC -0.0240 (corrections §4, 2026-09-22).
- Physics doc recommendation #4 (|t|<1 shrinkage) → rejected before running (corrections §0, 2026-09-22).
- LCID price series is a data bug (corrections §6c; AGENTS.md Known gaps, 2026-09-22) → real 1-for-10 reverse split, retracted (corrections §6d; integration AGENTS.md, 2026-09-22).
- Blend promoted to PRIMARY, with q75/xrank, Sector Bets, Model Weights, Backtest & History and the composite tab retired (reset `b37b7db` and session-handoff, 2026-09-19/22) → the app baseline keeps all tabs, blend as Candidate (Gabe, LEDGER landing queue #2, 2026-09-23).
- Composite and blend branch "not merged to main; Gabe merges" (session-handoff, 2026-09-22) → all landing goes through the integrator onto `integration` (LEDGER / Rule 0, 2026-09-23).
- Standing constraint #5 "Never run git add/commit/push yourself" (origin/main AGENTS.md; sweep RUNBOOK §10) → "fine to run yourself" (AGENTS.md #5, 2026-09-17). Further narrowed by Rule 0 (2026-09-23; see Open conflicts #1).
- AV options are blocked, with no volume/OI field (memory, 2026-09-17) → unblocked, AV premium bought, bulk pull running (AV spin doc / memory, 2026-09-22).
- Insider data source "TBD / AV" (data-sourcing research, 2026-09-17) → EDGAR Form 4 (session-handoff, 2026-09-22) → SEC Form 3/4/5 bulk data sets (insider prereg and results, 2026-09-23, landed).
- AV `HISTORICAL_VOLUME_OPEN_INTEREST_RATIO` gives only a ratio (session-handoff §5, 2026-09-22) → `HISTORICAL_OPTIONS` has raw volume and OI (AV spin doc §1, 2026-09-22).
- Stop-loss 15% adopted (AGENTS.md Round 8) → no stop; Round 13 holds to horizon (AGENTS.md note, 2026-09-11; reset doc §5).
- AGENTS.md sections "Current state (as of 2026-09-02)", "Known gaps", "Future plans", "Where the fuller history lives" → history only. Read them at `git show 29eb67b:AGENTS.md`. Their live content (reproduction table, options gaps, dead ends) is carried in §4, §7 and §8 above.
- `Claude outputs/RUNBOOK.md` (Round 12, 2026-09-09) → `final/src/sweep/RUNBOOK.md` (self-labelled superseded).
- `current_signal_composite.py` fails at import on integration (README Open conflicts #2, 2026-09-23 first sweep) → resolved, audit landed with `ic_weighted_composite.py` (LEDGER landing log, f680f94, 2026-09-23).
- Corrections §10-18, the full-spec doc, `ic_weighted_composite.py` and `prediction_ledger_v3.csv` are uncommitted in the audit worktree (README §5, 2026-09-23 first sweep; COO decision #4) → pushed and landed at 736a424 / f680f94 (LEDGER, 2026-09-23).
- Insider/congress pre-registered, no results (README §5, 2026-09-23 12:28 prereg) → results landed, counts a dead end, congress forward-only (insider results doc; COO.md; c8bba77, 2026-09-23).
- Insider and congress data only record the execution date (the premise the insider session started from, 2026-09-23) → SEC Form 345 has `FILING_DATE` and AV congress has `filed_date` (insider results §1, 2026-09-23).
- AV options bulk pull running (AV spin doc / memory, 2026-09-22) → crashed on `IncompleteRead` at 18:09 (COO.md, `pull.out`, 2026-09-23).
- `leverage` is a ready candidate for an explicit promotion decision (corrections §13, 2026-09-22) → contaminated in-era; confirmation only via a forward-ledger icw9 column (COO.md WO-2, 2026-09-23).
- Laddered rebalancing as a next step for the composite (reset doc §6 / COO leads, 2026-09-22) → smooths dispersion but doesn't cut turnover (corrections §15), and the COO did not launch it (COO.md, 2026-09-23).
- Corrections §12 OOS table: fit-odd→test-even IC +0.0302 (corrections §12 table, 2026-09-22) → +0.0304 after the renormalisation fix (same section's text; §19 sanity gate, 2026-09-23).
- WO-2+3 and WO-5 in flight on origin/main worktrees (README §5 / Open conflicts #9, 2026-09-23) → both landed via integration: 371f2d0, f3233bd (LEDGER / COO.md, 2026-09-24).
- Earnings announcement premium via 8-K as an open lead (COO.md leads, 2026-09-23) → DEAD, earnings-timing family closed at 6 trials (EAP 8-K doc; COO.md dead ends, 2026-09-23).
- `leverage` / opportunistic buyers "confirmation being built" (README §4.1/§4.6, 2026-09-23) → recording forward since panel date 2026-09-08 (forward ledger doc §5e, 2026-09-24).
- EAP 8-K doc Part 2 "Reading", first sentence (portfolio-impact claim, 2026-09-23) → struck by the COO: the icw9−icw8 gap is +0.10%/yr on in-sample weights (COO.md, 2026-09-23).
- Composite cap150 +3.75%/yr (9-factor, v1) and +4.32%/yr (ew8, v1) "unreadable until the grid is rebuilt" (README §3.3, 2026-09-22/23) → re-measured on v2: ew8 +1.80%, icw8 +2.85% (v1 +5.25%) (downcap-grid-rebuild doc, 2026-09-24).
- "Breadth is the lever": composite excess rises cap2000 < cap500 < cap150 (+1.09 → +3.03 → +3.75, reset REPORT_nominate 2026-09-19, as quoted in the downcap-grid-rebuild doc) → flat on v2, +2.84 / +2.66 / +2.85 (downcap-grid-rebuild doc, 2026-09-24; COO dead end).
- The composite is mostly universe beta; no-score control +2.40%/yr (corrections §2a, 2026-09-22) → on v2 the no-score universe earns −0.25%/yr and all the excess is selection, +3.95pp/yr (noscore-control-v2 doc, 2026-09-24). §2a's result was survivorship.
- Down-cap grid rebuild needs a Sharadar SF1 pull for ~4,600 names (AV spin doc §A / COO decision #2, 2026-09-22/24) → SEP and SF1 were already on disk; the 14-ticker top-up added nothing (downcap-grid-rebuild doc, 2026-09-24).
- WO-6 in flight, Phase 2 blocked on `SHARADAR_API_KEY` (README §5, 2026-09-24) → landed deb156d + 26f600f (LEDGER, 2026-09-24).
- Insider plain counts reopen "if a survivorship-safe down-cap grid exists" (COO.md dead ends, 2026-09-23) → reopen used by WO-4, DEAD; forward data only (insider-buyers-v2-grid doc, 2026-09-24).
- `build_insider_panel.py` TRANS_DATE string-min "found, not fixed; effect on historical classification unmeasured" (forward ledger doc §5c, 2026-09-23) → fixed; 1,185 of 327,456 reclassify, 0 flips on the blind record (same doc, "Implementation fix 2026-09-24").
- TRANS_DATE bug affects "5.3%" (forward ledger doc §5c, 2026-09-23) → that was 17 of 320 rows in one day's sample; the full count is 25,081 rows (1.72%), 8.09% of multi-date groups (same doc, 2026-09-24 section).
- `app` = bca3f7c, awaiting `git merge integration` (README §5, 2026-09-23) → rebuilt on 10bfb19's layout, 0584436 + 80f9f57, blocked on Gabe (HANDOFF-app.md, 2026-09-24; Open conflicts #10).
- The app baseline is bca3f7c: q75 primary, blend and composite as Candidate tabs, 8 stock sub-tabs (Gabe, LEDGER landing queue #2, 2026-09-23) → the 10bfb19 layout is official: blend = Today's Picks, composite alone = Theoretical Model, 4 stock sub-tabs (Gabe; LEDGER "APP LAYOUT BASELINE"; e1f8f6f, 2026-09-25).
- App prints q75 +8.71%/yr (2.796x SPY) / xrank +6.35% in-sample, +7.33% / -4.28% hold-out, beside a knob-family band of -8.01 to +9.15 %/yr, sd 5.03 (`final/app/README.md`, 2026-09-16/18) → no longer on the app; the bca3f7c-only items were dropped with the 10bfb19 layout (LEDGER, 2026-09-25). The README header still quotes them.
- q75 "kept in the app as the displayed primary" (README §4.2, 2026-09-23) → half of the Today's Picks blend, not shown alone (10bfb19 layout, 2026-09-25).
- `current_signal_blend.py`/meta `"role": "primary"` is stale (README Open conflicts #5, 2026-09-23) → correct again under the 10bfb19 layout (2026-09-25).
- `app` rebuilt on 10bfb19, blocked on Gabe (README §5 / Open conflicts #10, 2026-09-25) → landed e1f8f6f, deployed ccddf1a (LEDGER, 2026-09-25).
- The live composite and forward ledger read the v1 grid; which grid is Gabe's call (README Open conflicts #3, 2026-09-25) → v2 is the working panel (Gabe; WO-11 doc; 8f47808, 2026-09-25). The live checkout still runs v1 `src` (Open conflicts #12).
- `prediction_ledger_ext.csv` "landed 2026-09-24" (README §3.4, 2026-09-24/25) → only the code and doc landed then (f3233bd); the CSV was untracked in the main checkout until it was committed as 079fa26 (COO.md report log, 2026-09-26).
- Forward-ledger record cadence pending with Gabe (forward ledger doc §5f, 2026-09-24; WO-10 doc C10 and COO.md WO-9 bullet, 2026-09-25) → weekly, WO-10 counted-date rule unchanged (Gabe, COO.md decisions log; WO-14 doc addendum, 2026-09-25).
- "v2 has no refresh path" (WO-11 doc §4, 2026-09-25) → `refresh_working_panel.py` (WO-14 doc; f0e750a, 2026-09-25/26).
- WO-9 in flight, "pre-registration committed (60a2247), no result yet" (README §5, 2026-09-25) → MIDDLE, landed e11d37e; recorded as a forward bet, not promoted (hedged-composite doc; COO.md, 2026-09-25).
- WO-9 verdict "MIDDLE or KILL", depending on the LOYO window (hedged-composite doc §3.2, c572df0, 2026-09-25) → COO ruling: LOYO on the full window only, so MIDDLE (same doc §3.6, 2026-09-25).
- What the post-2011 +0.00 vs SPY means for promotion is open (README Open conflicts #11, 2026-09-25) → answered by WO-9 MIDDLE and Gabe's forward-bet decision (COO.md, 2026-09-25).
- Late-2019 labels exiting in 2020: to mask or not (WO-9 finding, 2026-09-25) → keep unmasked; the standard stays +2.85 (Gabe, COO.md "Open correctness items", 2026-09-25).
- SUE/PEAD as a proposed work order (COO.md, 2026-09-25) → screened, PASS-nomination (SUE doc; 026e3b7, 2026-09-25).
- `main` 7898b52 is far behind (README Open conflicts #7, 2026-09-23) → origin/main 1f81de2 after the 2026-09-25 docs push, still far behind integration (LEDGER, 2026-09-25).
- AV pull restart is Gabe's call (README §4.4, 2026-09-23) → Gabe will move it to another machine himself, not restart it on the Mac (COO.md, 2026-09-24).
- Reset branch in flight, "blocked on app-manager reconciliation", with a float32 `market_cap` correctness risk (README §5, 2026-09-25/26) → landed as d7d257d; its app.py reorg was superseded by the 10bfb19 layout, and the builder keeps float64 and is bit-identical on 218,698 sampled rows (LEDGER landing log, 2026-09-26).
- `2026-09-22-session-handoff.md` exists only on the reset branch (README §9, 2026-09-23) → landed (d7d257d, 2026-09-26).
- The live checkout runs 983a154 `src`, so a live Retrain ALL reverts to v1, pending Gabe's OK (README §3.1 and Open conflicts #12, 2026-09-26 run 5) → synced to integration d7d257d as 6a1823d, Retrain hook deployed (Gabe's OK; LEDGER, APP.md, 2026-09-26).
- The WO-14 Retrain ALL hook is "queued with the app manager, not built" (README §4.7/§5, 2026-09-25/26) → landed 783cc12/9dd0852, deployed 6a1823d (APP.md; LEDGER, 2026-09-26).
- The WO-8 doc addendum is uncommitted in its worktree (README §5 and Open conflicts #14, 2026-09-25/26) → committed 547ae48, landed ddb2773 (LEDGER, 2026-09-26).
- WO-15 is "written, held until the src sync" (README §4.1/§5, 2026-09-26 run 5) → Gabe approved it and it launched in `worktree-agent-a505179eca9ed9bf2`; it is still uncommitted (COO.md, LEDGER, 2026-09-26).
- SUE promotion is Gabe's open call (README Open conflicts #13, 2026-09-26 run 5) → approved by Gabe 2026-09-26 (COO.md decisions log); its scope is flagged in Open conflicts #15.
- SF1 frozen at 2026-09-08, proposed WO-16 needs Gabe's OK (COO.md decision #8, 2026-09-26, first entry) → approved as top priority, WO-16 launched in `worktree-agent-a2aadeb16c0d0ca8f` (COO.md decisions log; LEDGER, 2026-09-26).
- Deploy gate cleared by the 6a1823d sync (APP.md, first 2026-09-26 entry) → only partly cleared: `final/scripts/edgar_form4_refresh.py` is missing in the live checkout, so a live Retrain ALL stops at the insider-refresh step (APP.md, later 2026-09-26 entry).
- WO-16 in flight in `worktree-agent-a2aadeb16c0d0ca8f`, no commits (README §5, 2026-09-26 run 6) → landed defcc23, deployed to the live checkout 500a4a5 (LEDGER landing log, 2026-09-26).
- SF1 frozen at 2026-09-08 for every live reader (README §4.5/§4.7 and Open conflicts #16, 2026-09-26) → WO-16 top-up; live SF1 through 2026-09-25 (WO-16 doc, 2026-09-26).
- Live checkout @ 6a1823d (README §5, 2026-09-26 run 6) → 500a4a5 with the WO-16 paths (LEDGER, 2026-09-26).
- WO-15 pre-reg uncommitted, commit denied by the classifier (README §5, 2026-09-26 run 6) → committed 9dc2d03 and pushed; code still uncommitted (LEDGER, 2026-09-26).
- WO-15 in flight, code uncommitted in `worktree-agent-a505179eca9ed9bf2` (README §5, 2026-09-26 run 7) → landed 6ac64e6 and deployed live 562dab9 on Gabe's "Wo-15 cam go live" (LEDGER landing log; COO.md decision #9, 2026-09-26).
- WO-15 §4-5: basis validation against the 09-08 file with split-list exemptions, and a SUE failure writes nothing for any ledger (pre-reg 9dc2d03, 2026-09-26) → Addendum A: isolation, uniform-ratio check, 1% cap, rolling reference (c69b942/7c3e066, 2026-09-26).
- WO-15 §7: W38/W39 backfilled if checks (a)-(c) pass (pre-reg 9dc2d03) → declined, W40 first countable (Results; Addendum A1e, 2026-09-26).
- What "SUE promotion approved" covers is open (README Open conflicts #15, 2026-09-26 runs 6-7) → forward confirmation via WO-15, not live weights (COO clarification, 2026-09-26).
- The `final/scripts` gap: a live Retrain ALL stops at the insider step and skips the WO-16 top-up (README §3.1/§4.7/Open conflicts #12, 2026-09-26 runs 6-7) → `edgar_form4_refresh.py` deployed live as db13243 (LEDGER landing log, 2026-09-26).
- Live checkout @ 500a4a5 (README §5, 2026-09-26 run 7) → 562dab9 via db13243 (LEDGER, 2026-09-26).
- `tickers_master.csv` / `actions.csv` end at 2026-09-08 / 2026-09-10 and nothing refreshes them; no post-09-08 listing can enter the universe (README §4.5, 2026-09-26 runs 7-8) → refreshed once by hand (21,014 rows; actions through 2026-09-29), still no automatic refresh (WO-17 doc, landed a9344ef, 2026-09-26).
- WO-17 in flight, pre-reg 7dd8066 only (README §5/§9, 2026-09-26 run 8) → SUCCESS, landed a9344ef (LEDGER landing log, 2026-09-26).
- WO-17 hold-back set: 7 label columns (pre-reg 7dd8066) → plus `firstpricedate` (Addendum A 134fbf5, 2026-09-26).
- `actions.csv` covers 2025-09-09..2026-09-10 (README §8.1, 2026-09-25) → through 2026-09-29 (WO-17 doc, 2026-09-26).
- "The other 7 integration-only scripts are absent live" (README §4.7, 2026-09-26 run 8, derived) → 9 at a9344ef, incl. WO-17's two tools (git ls-tree check, 2026-09-26 run 9).
- WO-18 pre-reg doc does not exist yet (README §5, 2026-09-26 run 8) → exists uncommitted, mtime 2026-09-26 22:25 (WO-18 worktree).
- AV pull stopped at monthly 2010-08-18 after "32 of 225" monthly dates (README §4.4, from COO.md, 2026-09-23) → 33 of 225 (WO-20 doc and COO.md D-AV, 2026-09-27; 33 unique dates in `pull.out`).
- `IncompleteRead` is not in the retry tuple at `final/scripts/av_options_pull.py:151` (README §4.4/§8.1, 2026-09-23) → fixed: `FETCH_ERRORS` includes `http.client.HTTPException` (WO-20, landed f380817, 2026-09-27).
- A real network run of Retrain ALL has not been exercised (README §3.1/§4.7, 2026-09-26 runs 8-9) → Gabe's live Retrain ALL 2026-09-26 22:36-22:47, COO-verified CLEAN (COO.md, 2026-09-27).
- The working panel is through 2026-09-24 and 8 split names are blocked (README §4.5, 2026-09-25/26) → through 2026-09-25 in the live checkout; BLOCKED list 9 with KITT (COO.md, Retrain ALL 2026-09-26).
- The blend stays as of 2026-09-08 because its `as_of` comes from the unrebuilt v1 base panel (README §3.2, from the WO-14 doc, 2026-09-25) → blend and composite both as of 2026-09-25 after Gabe's Retrain ALL (live metas, mtime 2026-09-26 22:47).
- App key guard landed, not deployed; deploying it is Gabe's call (README §4.7 / Open conflicts #19, 2026-09-26 run 9) → deployed with the picks sort as 4ab4363 (c8dec17) on Gabe's "just deploy it now" (COO.md #12; LEDGER, 2026-09-26).
- Live checkout @ 562dab9 (README §5, 2026-09-26 runs 8-9) → 4ab4363 (LEDGER landing log, 2026-09-26).
- WO-15's split allow-list changed under it; recheck needed (README Open conflicts #17, 2026-09-26 run 9) → CLOSED, the split list is reporting-only (COO.md, 2026-09-26).
- WO-18 in flight, uncommitted, no result (README §5, 2026-09-26 run 9) → committed 51795c9/a7aa44e/74e6e03, PASS-nomination, COO-verified, not landed (COO.md; LEDGER, 2026-09-27).
- AV pull "still STOPPED"; restart it or cancel AV is Gabe's call (README §3.1/§4.4/§6 #21, 2026-09-27 run 10) → running on Gabe's Windows machine (Gabe, "AV pull is running on the windows machine"; COO.md D-AV RESOLVED, 2026-09-27); ETA cap2000 monthly ~09-30 (COO.md, 2026-09-28).
- COO D-AV: restart the pull by ~10-12 or cancel at renewal (COO.md, 2026-09-27) → D-AV-2: test on cap2000 monthly first, renew only if a result earns the weekly/daily data (COO.md, 2026-09-28).
- Project memory "AV bulk pull RUNNING" listed as stale (README §6 #6, 2026-09-23 → 09-27) → accurate again, now on Windows (2026-09-27); dropped from the stale list.
- WO-18 `seas` PASS-nomination on an unlanded branch; a forward column pending Gabe (README §5/§6 #22, 2026-09-27 run 10) → Gabe promoted `seas` into both live models; landed with WO-20-seas as 0032ee3, not deployed (COO.md decisions log; LEDGER, 2026-09-27/28).
- WO-18 pre-registration "Pass = nomination → forward column only" (COO.md WO-18 launch; seasonality-screen doc, 2026-09-26) → promotion by Gabe's decision, monitored by forward ledgers (WO-20-seas doc "Decisions", 2026-09-27). The pre-registration itself stands as a historical record.
- `sf1_topup.py`, `sf1_eps_live_pull.py` and `sharadar_pull_pit_panel.py` put the key in the request URL (COO.md WO-19 candidate, 2026-09-26; README §8.2 run 10) → no script built a key-bearing URL; the leak was `requests` exception text, and those first two were already safe (WO-19 doc, 2026-09-27).
- Any further hold-out look needs Gabe's explicit OK (COO.md; README §3.2/§3.4, 2026-09-19 → 09-27) → standing OK for unfitted 2020-2026 reads, each logged; fitting on 2020+ still needs Gabe (Gabe, 2026-09-27 late; memory `feedback_holdout_unfitted_reads_ok.md`).
- 9 integration-only `final/scripts` absent live (README §4.7/§5, 2026-09-27 run 10) → 10 at e05faea, adding WO-19's test (git ls-tree vs 4ab4363, 2026-09-28 run 11).
- Live `final/src` equals integration d7d257d plus the 2026-09-26 deploys (README §5, 2026-09-26/27) → integration has moved ahead: WO-19, WO-20-seas and WO-21 are landed and not deployed (LEDGER, 2026-09-27/28).
- Post-2011: "a −2.76 same-construction drag (only partly IWM-hedgeable) eats the rest", components unknown (COO.md descriptive check, 2026-09-27) → universe −1.99 (72%) + construction −0.77, which is the null's own churn cost; UNIVERSE BET (WO-21 doc; COO.md, 2026-09-28).
- WO-20-seas app text queued in APP.md; the app manager could not write from an isolated worktree (HANDOFF-worktree-agent-a790eb27c4530aa0a; LEDGER, 2026-09-27) → landed as integration 254ea01 (app a74a9dd), not deployed; src and app deploy together (COO.md report log, 2026-09-28).
- `seas` in both live models: Theoretical `icw9_seas` and a 10-factor equal-weight blend leg `blend_q75_ew10seas_2026-09-27` (Gabe "Both"; WO-20-seas 0032ee3; README run 11, 2026-09-27/28) → Theoretical only; the blend is back on `blend_q75_ew9_2026-09-19` and the 10-factor blend is side-ledger only (Gabe "Theoretical only"; [seas Theoretical-only](final/models/2026-09-29-seas-theoretical-only.md), 22f2c69, 2026-09-29).
- The −0.36% hold-out and 1.54%/yr "belong to the previous 9-factor blend" (README §3.2/§4.3, WO-20-seas doc, 2026-09-27/28) → they belong to the live 9-factor blend again (seas Theoretical-only doc, 2026-09-29).
- New blend shares 136/160 picks with the old one on 2026-09-25 (HANDOFF-worktree-agent-a790eb27c4530aa0a, 2026-09-27) → blend picks 160/160 identical to the pre-WO-20 scorer, max diff 0.0 (seas Theoretical-only doc "Checks", 2026-09-29).
- Landmine: Today's Picks stops outright if `seas` coverage < 60% or a SEP month is missing (README §4.3/§6 #24/§8.2, 2026-09-27/28) → only the Theoretical scorer can stop; the blend's `main()` no longer computes `seas` (seas Theoretical-only doc, 2026-09-29).
- Deploy WO-20-seas awaits Gabe's one-word confirm; the 2.52 → 2.40 blend comparison is a number to see before deciding (README §6 #24, COO.md 2026-09-28) → decided "Theoretical only" 2026-09-29, recorded as his deploy OK; deploy pending an unisolated integrator run (COO.md; LEDGER, 2026-09-29).
- WO-23 hold-out read #5 in flight, no results (README §3.2/§3.4/§5, 2026-09-28 run 11) → results committed c9ba394/9106bef, COO-verified verdict (S1 not triggered), not landed (COO.md; LEDGER, 2026-09-28).
- WO-23 next: apply the seas removal plan S1 (README §4.1, 2026-09-28) → S1 not triggered, S2 (forward) applies to the Theoretical model (COO.md "WO-23 VERDICT", 2026-09-28).
- No v2 hold-out read had been reported as of 2026-09-28 (README §3.4, run 11) → WO-23 read #5 is the first; WO-24 (#6) and the ICW v2 reweight (#7) are in flight (COO.md; LEDGER, 2026-09-29).
