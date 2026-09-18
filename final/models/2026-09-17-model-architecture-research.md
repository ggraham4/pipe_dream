# Model architecture research (2026-09-17)

Gabe asked for a survey of the cross-sectional equity/derivatives return prediction
landscape, gold-standard to cutting-edge, ranked by whether swapping or extending
the current architecture is worth doing versus continuing the data-sourcing
workstream already in flight. This is a candidates list for eventual submission to
the existing IC-screen/walk-forward sweep pipeline (`final/src/sweep/`), not a
backtest — nothing here was run, tuned, or fit.

**Why this matters more than usual right now.** The honest state of the two
deployed/researched models sets a high bar for any architecture change to clear.
After the Round 11 point-in-time universe rebuild, the stock model's augmented cell
shows an edge over SPY across 124 walk-forward windows (2007-2026) of **-0.11% per
window, t = -0.09** — statistically indistinguishable from zero. A pre-registered
sweep of 1,152 configurations (Round 12) failed its own acceptance bar (Deflated
Sharpe 0.746, Reality Check p = 0.61). Round 13 traced most of what edge had been
reported before that to a sector bet, not stock-picking skill. Rounds 15/15b closed
off breadth and horizon as tunable levers. Split importance today is dominated by
one feature — `volatility_60` alone carries 60.3% of the augmented XGBoost's
importance — a shape Gabe explicitly wants to move away from, toward many small
+/- weights, closer to how institutional multi-factor risk models spread exposure
across many weak, ideally-uncorrelated signals. And across 64 scored cells in this
project's own sweep history, the rank correlation between a cell's IC and what it
actually earned is only +0.019 — meaning "better IC" or "better held-out loss" is
not a validated proxy for "better deployed risk-adjusted return" *in this project*,
and every verdict below tries to say so honestly rather than defaulting to IC talk.
The project's own working hypothesis, on the record, is that **breadth — the number
of names the portfolio can hold at once — not model sophistication, is what caps
achievable Sharpe here**, which is the single most important prior any architecture
recommendation has to engage with rather than talk past.

The other hard constraint is the calendar. The 2020-2026 hold-out has already been
spent twice (Round 13's breadth confirmation, Round 18's xrank test) and is being
treated as untouchable going forward. Every architecture below is evaluated on
whether it can be developed and vetted entirely within 2007-2020 using nested/
purged/embargoed walk-forward cross-validation (à la López de Prado, *Advances in
Financial Machine Learning*) — because a "promising" result that can only be
confirmed against 2020-2026 isn't confirmable at all right now.

Two axes, kept separate:

- **Likelihood of real uplift** — given the breadth-ceiling finding, the sector-bet
  finding, and the fact that "architecture is the bottleneck" may itself be a red
  herring, how plausible is it that *this specific change* moves deployed
  risk-adjusted return, as opposed to just re-describing the same ~11-24 features
  through a different function class.
- **Fit to constraints** — data-hunger vs. a ~1,600-name universe (small by deep-
  learning standards, not small by classical-ML standards), point-in-time/no-
  lookahead compatibility, purgeability/embargoability under walk-forward CV,
  engineering cost for a solo project, and interpretability/auditability (this
  project has already burned real time chasing a spurious sector bet it didn't
  initially recognize — a black-box upgrade makes that failure mode harder to catch
  next time, not easier).

A "High/High" candidate isn't automatically first — cost and how fast it can be
falsified matter too, which is why the shortlist at the end reorders for that.

---

## Ranked candidates

### 1. Hold the current architecture; redirect engineering effort to data/features
**Likelihood of real uplift: Low (as a standalone move)** · **Fit to constraints: N/A (no new architecture)**

**What it is.** Not a new architecture — the explicit alternative to everything
below. Keep depth-3 XGBoost (both the augmented classifier and the xrank
regressor), keep the 40-day hold, keep the current ~11 price/volume features plus
the ~13 Sharadar fundamentals ratios, and put the next block of effort into the
already-ranked data-sourcing queue (sector-neutral features, net issuance, insider
buys, options liquidity bucketing, earnings revisions — see
`final/models/2026-09-17-new-data-sourcing-research.md`) instead of a new model
class.

**Case for it.** Every diagnostic this project has run points at the feature set
and the universe, not the function class, as the binding constraint. Round 13 found
the previously-reported edge was a sector bet a linear model would have found just
as easily as a tree — no model swap fixes a sector bet, only better-constructed
features (sector neutralization) or an explicit neutralization step do. Rounds
15/15b already showed breadth and horizon are exhausted levers; nothing about model
class relaxes the breadth ceiling, which is a portfolio-construction constraint
(how many uncorrelated bets the universe can support), not a modeling one. And the
IC-vs-earned-return correlation of +0.019 across 64 cells is itself a warning
against chasing marginal fit-quality gains from a fancier estimator — this
project's own history says a better validation-loss number has not reliably
translated into better deployed return. Swapping architectures is also the
*highest-switching-cost* way to find out the data just isn't there yet: a new model
class adds new surface area (new hyperparameters, new failure modes, new ways to
accidentally leak the future) on top of a feature set that hasn't yet been shown to
carry a real idiosyncratic signal post-Round-11.

**Case against.** This isn't costless either — if the feature set genuinely
contains structure a depth-3 tree can't reach (e.g., real conditional interactions
across 3+ features, or nonlinearities monotone-constrained trees would suppress),
staying put forgoes it indefinitely. But nothing in this project's diagnostics
(feature-importance concentration, sector-bet finding) points toward "the model
class is underfitting a complex signal" — if anything, the concentration in one
feature and the failure at 1,152 configurations point toward "there may not be much
signal to underfit."

**Cost/complexity.** Zero net-new engineering.

**PIT / walk-forward CV feasibility.** N/A — no new fit risk introduced.

**Verdict.** The honest top pick given the evidence on record. Not "never touch the
model again" — several cheap, low-risk architecture tweaks below (interaction
constraints, monotonic constraints, an Elastic Net side-model) are worth doing in
parallel because they're nearly free and double as diagnostics — but a full
architecture swap should wait until the data-sourcing queue has been run and either
does or doesn't turn up a real signal to model.

---

### 2. Interaction-constrained / feature-grouped XGBoost
**Likelihood of real uplift: Medium** · **Fit to constraints: High**

**What it is.** XGBoost's `interaction_constraints` parameter — already available
in the exact library this project uses, no new dependency — restricts which
features may co-occur in a tree's split path. Grouping momentum/vol/volume/RS/
price-level into one bucket and fundamentals ratios into another (or finer groups)
mechanically prevents any single feature from dominating every tree, because the
search space per split is narrowed to its own group.

**Case for it.** This is the most direct, cheapest available lever on the exact
problem Gabe named — `volatility_60` at 60.3% of split importance is a single-
feature-dominance failure mode, and interaction constraints are a structural (not
just a regularization-strength) fix: they force the ensemble to keep building
capacity in the other feature groups rather than always deepening around whichever
feature the greedy split search likes best early. It's also a genuine diagnostic,
not just a workaround — if performance is materially unchanged once `volatility_60`
can no longer dominate every tree, that's independent evidence the "signal" was
mostly one feature wearing many disguises, consistent with the sector-bet finding
(volatility and sector membership are correlated in this project's own attribution
work).

**Case against.** It doesn't add information, only redistributes how existing
information is used — if `volatility_60` really is carrying most of the genuine
signal, this could make held-out performance *worse*, which would itself be a
useful (if deflating) result.

**Cost/complexity.** Very low — a parameter change to the existing training script,
no new library, no new data. A day or two including a proper walk-forward
comparison against the current unconstrained model.

**PIT / walk-forward CV feasibility.** Fully compatible — this changes nothing
about how features are computed or dated, only how the existing PIT-safe feature
matrix is consumed by the tree-builder. Purge/embargo exactly as today; tunable
entirely within 2007-2020.

**Verdict.** Do this early. It's nearly free, directly tests Gabe's stated shape
concern, and the result (does performance hold up once one feature can't dominate)
is informative either way.

---

### 3. Monotonic-constraint XGBoost
**Likelihood of real uplift: Low-Medium** · **Fit to constraints: High**

**What it is.** Constrain specific feature-to-prediction relationships to be
non-decreasing or non-increasing where domain knowledge says they should be (e.g.,
lower P/E should not *increase* predicted probability of a buy, all else equal;
higher debt-to-equity should not help). Supported natively by XGBoost, LightGBM,
and CatBoost — a config change, not an architecture change.

**Case for it.** A 2025 multi-dataset credit-PD benchmark found the accuracy cost
of monotonicity is close to zero on larger datasets and only ~2-3% even on small,
heavily-constrained ones — a cheap trade for a real gain: a monotone model is
harder to overfit to a spurious wiggle in one fundamentals ratio, and it's more
auditable, which matters directly for a solo project that has already once
mistaken a sector bet for stock-picking skill and needs to be able to explain *why*
the model likes a name, not just that it does.

**Case against.** This project has 24-ish features and no confirmed, contested
disagreements about sign (unlike credit scoring, where "does higher leverage hurt
you" is genuinely debated) — so the accuracy delta from constraining is likely to
be close to zero either way, meaning the main benefit is auditability, not lift.
Also low-value on `volatility_60` and momentum features specifically, where the
true relationship plausibly isn't monotone (moderate momentum/vol may predict
differently than extreme values) — constraining those the wrong way could hurt.

**Cost/complexity.** Very low — same training pipeline, added constraints
dictionary, a sign per feature to think through and defend.

**PIT / walk-forward CV feasibility.** Fully compatible, same reasoning as #2.

**Verdict.** Worth a cheap trial alongside #2, mainly for the auditability
benefit rather than expected uplift. Don't expect this to move the needle on its
own; treat a large change (either direction) in held-out performance as a signal
something else is off (e.g., mis-signed constraint) rather than a real effect.

---

### 4. Random Forest
**Likelihood of real uplift: Low-Medium** · **Fit to constraints: High**

**What it is.** Bagged ensemble of deep(ish) decorrelated trees, each grown on a
bootstrap sample with random feature subsampling per split — the other academic
gold-standard tree method alongside gradient boosting, and one of the strongest
performers in Gu/Kelly/Xiu's own comparison of linear, dimension-reduction, tree,
and neural methods for cross-sectional return prediction.

**Case for it.** Random feature subsampling at each split is a *mechanical* route
to Gabe's "many small weights" target shape — a single dominant feature can't
appear in every split of every tree the way it can in greedy boosting, so
aggregate feature importance naturally spreads wider without any manual
constraint-setting. It's also a materially different learning algorithm from
gradient boosting (variance reduction via averaging vs. bias reduction via
sequential residual-fitting), so a Random Forest run alongside the existing
XGBoost cells is a genuine second opinion, not a repackaging — useful given how
thin the evidence for any signal in this feature set currently is.

**Case against.** GKX and the broader literature generally find gradient boosting
edges out random forests on this exact task family, so this is unlikely to beat
what's deployed on raw accuracy; the case here is about weight *shape* and
independent confirmation, not expected lift. If Random Forest ranks the same names
highly that XGBoost does, that is at least reassuring; if it disagrees sharply,
that's a flag that the XGBoost picks are an artifact of its specific greedy
sequential-fitting bias rather than a robust cross-sectional signal.

**Cost/complexity.** Low — scikit-learn `RandomForestClassifier`/`Regressor`,
same feature matrix, no new data pipeline. A few days including a fair walk-forward
comparison.

**PIT / walk-forward CV feasibility.** Fully compatible — same PIT feature matrix,
standard purge/embargo, tunable entirely pre-2020.

**Verdict.** Cheap, well-evidenced as a baseline, and a good independent-shape
check. Worth running as a comparison arm, not as a replacement for the deployed
model unless it clearly beats XGBoost on a walk-forward basis (unlikely per the
literature, but the "many small weights" property alone makes it worth the day of
engineering to find out).

---

### 5. CatBoost
**Likelihood of real uplift: Low-Medium** · **Fit to constraints: Medium-High**

**What it is.** Gradient boosting with ordered boosting — each row's prediction
during training is built only from trees fit on a random permutation prefix that
precedes it, which structurally prevents the target-leakage/overfitting failure
mode plain gradient boosting is prone to on small-to-medium data.

**Case for it.** Recent head-to-head benchmarks (late 2025) show CatBoost leading
XGBoost on log-loss/Brier/AUC on a majority of tested datasets, and its specific
mechanism — ordered boosting's resistance to overfitting below roughly 40K rows —
is aimed exactly at this project's regime: a cross-sectional panel with ~1,600
names per date is not "big data" in the sense gradient boosting was originally
tuned for, and the project's own history of overfitting surprises (the in-sample-
promising xrank label that lost -4.28%/yr out of 2020-2026 hold-out) suggests
overfitting resistance is worth more here than raw accuracy on a clean benchmark.

**Case against.** CatBoost's biggest documented edge is with categorical features;
this feature set is entirely numeric, so the category-handling advantage doesn't
apply, and the overfitting-resistance benefit is speculative for this specific
panel size until actually tested. It's also a genuinely different library with its
own serialization format, its own quirks in the `app/lib/pit_model.py`-style
load/predict wrapper, and its own hyperparameter surface — a real (if modest)
integration cost, not a one-line swap the way `interaction_constraints` is.

**Cost/complexity.** Low-Medium — new dependency, new model-loading code path in
the dashboard, a comparable training script. Maybe a week including integration
and a walk-forward comparison.

**PIT / walk-forward CV feasibility.** Compatible — same PIT feature matrix,
standard purge/embargo. Worth noting ordered boosting's own internal row-ordering
requirement doesn't conflict with time-based purge/embargo as long as training
folds are still constructed the same way (features/labels dated and embargoed
before CatBoost ever sees them) — the ordered-boosting mechanism operates *within*
an already-PIT-safe training fold, not across the purge boundary.

**Verdict.** A reasonable second-tier trial — real mechanism, plausible fit to
this project's small-panel/overfitting history — but behind the near-free items
above (#2, #3) and #4, since it's the first item on this list with real
integration cost for an uncertain payoff.

---

### 6. LightGBM
**Likelihood of real uplift: Low** · **Fit to constraints: Medium**

**What it is.** Gradient boosting with leaf-wise (best-first) tree growth instead
of XGBoost's level-wise growth — generally faster and, on many benchmarks,
comparably or more accurate than XGBoost.

**Case for it.** It's the closest drop-in engine swap on this list — same
training paradigm, same feature matrix, same monotonic/interaction-constraint
support, well-documented, fast. If Gabe wants a like-for-like architecture
comparison with minimal integration risk, this is the lowest-friction option.

**Case against.** Leaf-wise growth tends to concentrate splits around whatever
feature currently looks most informative even more aggressively than XGBoost's
level-wise growth does — which cuts directly against Gabe's stated "many small
weights" target. Absent interaction constraints (which LightGBM also supports, so
this isn't fatal, just a caveat), a naive LightGBM swap is more likely to make the
`volatility_60`-dominance problem worse, not better. There's also no strong reason
from this project's own diagnostics to expect a different growth strategy to
surface signal XGBoost is missing — the binding constraint (per items #1 and the
opening framing) looks like data, not which gradient-boosting variant computes
splits.

**Cost/complexity.** Low — same category as CatBoost, slightly lower integration
friction since LightGBM's API is closer to XGBoost's.

**PIT / walk-forward CV feasibility.** Fully compatible, same reasoning as #2/#3.

**Verdict.** Lowest priority among the boosting-family swaps. If tried at all, pair
it with interaction constraints from the start rather than testing it naively,
given the leaf-wise-concentration concern above.

---

### 7. Elastic Net / Ridge / Lasso (shrinkage linear factor model)
**Likelihood of real uplift: Low (as a replacement) / Medium (as a diagnostic and ensemble input)** · **Fit to constraints: High**

**What it is.** A penalized linear regression/classification (Elastic Net blends
Ridge's L2 shrinkage with Lasso's L1 sparsity) over the same feature set — the
`Gu/Kelly/Xiu`-style academic baseline every ML-in-asset-pricing paper compares
against, and the natural first rung of "many small weights" since a linear model's
coefficients *are* the weights, with no split-importance concentration mechanism
possible in the first place.

**Case for it.** Two distinct arguments, and they matter for different reasons.
First, as a **diagnostic**: if an Elastic Net trained on the same PIT features
captures most of XGBoost's walk-forward performance, that's strong evidence the
"signal" here is linear/additive (e.g., a sector or vol-tilt effect any linear
model would also find) rather than something requiring tree-based nonlinearity or
interactions — directly testable and directly relevant to the sector-bet finding
from Round 13. Second, as an **ensemble input**: stacking a linear model's
prediction alongside the tree-based cells (see #8) is a cheap way to diversify
away from any one model's idiosyncratic overfitting mode, and Elastic Net's L1
component gives automatic feature selection, which is useful sanity-checking
against the fundamentals ratios that haven't individually been shown to carry
signal post-Round-11.

**Case against.** Purely as a standalone replacement, it's unlikely to beat
XGBoost on raw accuracy (GKX found trees and neural nets ahead of linear/PLS/PCR
methods, with the gains coming specifically from nonlinear interactions linear
models can't capture) — so don't expect this to be the deployed model. Also
doesn't fit the classifier's current probability-calibration setup out of the box
(need `LogisticRegression(penalty="elasticnet")` for the augmented cell, plain
`ElasticNet` for the xrank cell) — a small but real adaptation.

**Cost/complexity.** Very low — scikit-learn, same feature matrix, well-understood
tuning (single `alpha`/`l1_ratio` grid). A few days.

**PIT / walk-forward CV feasibility.** Fully compatible, and easier to purge/
embargo correctly than any tree model since there's no risk of implicit temporal
leakage through complex split structure — the simplest model on this list to audit
for a CV mistake.

**Verdict.** Do this early and cheaply, not because it's likely to become the
deployed model, but because it's the fastest way to answer "is what's left after
Round 11 linear or not" — a genuinely useful piece of information regardless of
which way it comes out, and sets up #8 for later.

---

### 8. Weak-learner stacking / ensemble of few-feature sub-models
**Likelihood of real uplift: Medium** · **Fit to constraints: Medium**

**What it is.** Instead of one model ingesting all ~24 features, train several
small models each on a narrow, economically coherent feature subset (e.g., a
pure-momentum model, a pure-volatility model, a pure-fundamentals-ratio model, a
relative-strength model), then combine their outputs with a simple learned
meta-weighting (linear stacking) or a fixed IC/IR-weighted blend — the mechanism
institutional multi-factor shops (AQR/Barra-style risk models) actually use to
combine many weak, ideally-uncorrelated factors into one score.

**Case for it.** This is the most *mechanically direct* route to Gabe's stated
target shape on this whole list — "many small +/- weights" isn't a side effect
here, it's the literal design: each sub-model contributes one weight in the final
blend, and no single feature can structurally dominate the ensemble the way
`volatility_60` dominates one big tree, because volatility only gets one vote
alongside momentum, fundamentals, and relative strength. It also gives a clean,
auditable per-factor performance breakdown (which sub-model is actually pulling
its weight, which isn't) that a single 24-feature tree doesn't expose without
extra SHAP-style tooling — directly useful for a solo project that needs to be
able to explain what it owns and why. Institutional practice (Barra-style risk
model construction) explicitly warns against indiscriminately adding weak/spurious
factors, which maps onto a real risk here too: this only works if the sub-models
are each independently vetted (via the existing sweep pipeline) before being
blended in, not just thrown in for shape's sake.

**Case against.** More moving parts than any single-model swap on this list:
several models to train, tune, and keep in sync as features evolve, plus a
meta-weighting step that is itself a small model needing its own walk-forward
validation (and its own leakage risk if not purged correctly). There's also a real
chance this simply re-derives what a single tree with interaction constraints (#2)
already gives more cheaply — worth trying #2 first as a cheaper partial test of
the same idea before committing to a full multi-model stack.

**Cost/complexity.** Medium — several small training scripts (largely reusing
existing feature-engineering code, just subsetted), a meta-model, and dashboard
integration to show per-factor contribution. Plausibly 1-2 weeks.

**PIT / walk-forward CV feasibility.** Feasible but needs care: every sub-model
and the meta-weighting layer must each be purged/embargoed against the same
2007-2020 boundary — the meta-model's own training data (the sub-models'
predictions) must come from an out-of-fold, walk-forward-consistent generation
process (never let the meta-model train on a sub-model's in-sample predictions),
which is a well-known stacking pitfall and needs to be built in from day one, not
patched on later.

**Verdict.** The best-fit cutting-edge-adjacent idea on this list for Gabe's
explicitly stated target shape, but it's real engineering, not a quick trial — do
#2 and #7 first (cheap, and they inform how to split the feature groups
sensibly), then decide whether the extra complexity of a full stack is worth it.

---

### 9. Bayesian Model Averaging over candidate feature subsets/models
**Likelihood of real uplift: Low** · **Fit to constraints: Low-Medium**

**What it is.** Instead of one point-estimate model, maintain a posterior over
several candidate models (different feature subsets, or different function
classes) and average their predictions weighted by posterior model probability —
the fully Bayesian generalization of the stacking idea in #8, and the standard
academic alternative to stacking discussed in the ensembling literature. (Stacking
has generally been reported to outperform BMA in practice — a genuine head-to-head
finding worth weighing against BMA's extra complexity.)

**Case for it.** More principled uncertainty quantification than a point-weighted
stack — the posterior itself tells you how confident to be in any given
sub-model's contribution, which could plausibly feed into position sizing
alongside or instead of #11's conformal approach.

**Case against.** Meaningfully more engineering and computational cost than
stacking for, per the literature, generally *worse* out-of-sample performance —
and the literature's own preference for stacking over BMA in practice is a direct
argument to do #8 instead of this. There's also no evidence in this project's
history that model-uncertainty quantification (as opposed to point-prediction
quality, or breadth) is the actual bottleneck — nothing here addresses the
breadth-ceiling hypothesis at all.

**Cost/complexity.** Medium-High — meaningfully more than #8 for a method the
literature itself ranks below it on typical predictive performance.

**PIT / walk-forward CV feasibility.** Same purging discipline as #8 applies, with
the added complexity of validating the posterior weights themselves aren't
leaking future information.

**Verdict.** Skip unless #8 is built first and specifically needs better-calibrated
uncertainty than a point-weighted stack provides — don't reach for this before
trying the simpler, better-evidenced alternative.

---

### 10. Quantile regression forests / distributional forecasting
**Likelihood of real uplift: Low-Medium** · **Fit to constraints: Medium-High**

**What it is.** Instead of (or alongside) a point prediction, forecast the full
conditional distribution of forward return per name — quantile regression forests
are a direct random-forest-based way to do this with no distributional
assumptions, estimating the whole conditional distribution from one model.

**Case for it.** This targets a different, real gap: the deployed stock model has
**no stop-loss in the current config** and the options puts model is
researched-only in part because of unreliable tail behavior in thin markets — a
distributional forecast (not just a point rank) is a more natural fit for
asymmetric downside risk than a single probability-of-buy score, and it composes
naturally with #11's conformal-prediction position sizing. This is a genuinely
different *target*, not just a different function class, which is a meaningfully
different kind of change from most of the rest of this list.

**Case against.** Doesn't help find more signal — it reshapes how a given amount
of signal is used for risk management, which is valuable but a different problem
than what most of this report is about (finding idiosyncratic edge). If the
underlying point-estimate ranking doesn't carry real signal (the open question per
the framing above), a fancier distributional wrapper around it doesn't fix that.

**Cost/complexity.** Medium — `sklearn`/`scikit-garden`-class tooling exists, but
requires rethinking the backtest and portfolio-construction code to consume a
distribution rather than a rank, a real (if bounded) engineering lift.

**PIT / walk-forward CV feasibility.** Compatible — same PIT features, standard
purge/embargo; quantile loss functions don't introduce new lookahead risk beyond
what point regression already has.

**Verdict.** Interesting, but positioned as a risk-management upgrade, not an
edge-finding one — reasonable to revisit once/if a real point-estimate signal is
confirmed post-data-sourcing-workstream, not before.

---

### 11. Conformal prediction for uncertainty-aware position sizing
**Likelihood of real uplift: Low-Medium (risk-adjusted, not raw-return)** · **Fit to constraints: High**

**What it is.** A distribution-free, model-agnostic wrapper that produces
calibrated prediction intervals from any existing model's outputs (no need to
replace XGBoost — this sits on top of it), then scales position size to interval
width (narrower interval → bigger position, à la fractional-Kelly). A 2025-2026
"Conformal Kelly" paper reports meaningfully better risk-adjusted performance
(Sharpe 1.34 vs. an S&P 500 benchmark) using exactly this combination on a
multi-year development window, though that's one paper's backtest, not an
independently replicated result, and should be treated as a plausibility case, not
proof it transfers here.

**Case for it.** This is the cheapest item on the whole list to try, because it
doesn't touch the model at all — it's a post-hoc calibration layer over whatever
score the augmented/xrank cells already output. It also directly addresses a real,
named gap: the deployed model has no stop-loss and a fixed 40-day hold with no
dynamic sizing — a calibrated uncertainty measure is a natural, low-risk way to
size positions (or set a genuinely justified stop) without re-opening the "does
the model have real edge" question at all.

**Case against.** It cannot create signal that isn't there — if the underlying
ranking is noise (the live open question here), calibrated intervals around noise
are still noise, just with better-quantified honesty about it. It's a risk-
management/portfolio-construction improvement, not an edge-finding one, so
ranking it purely on "likelihood of uplift" undersells it (better risk-adjusted
return from the same edge is a real win) while also not addressing the project's
central open question.

**Cost/complexity.** Low — conformal prediction is a post-processing step over an
existing model's residuals from a held-out calibration fold; no retraining of the
underlying model required.

**PIT / walk-forward CV feasibility.** Clean and arguably the easiest item on this
list to keep leakage-free — the calibration set is just another walk-forward-
respecting held-out fold, no different in principle from the diagnostics this
project's `holdout_analysis.py`/`continuous_walkforward_pit.py` already run.

**Verdict.** Do this early, in parallel with #2/#7, precisely because it's cheap,
doesn't require resolving whether the model has real edge first, and directly
targets a documented, unaddressed risk-management gap (no stop-loss on the
deployed config).

---

### 12. Modern tabular deep learning (FT-Transformer, SAINT, NODE, TabNet)
**Likelihood of real uplift: Low** · **Fit to constraints: Low**

**What it is.** Attention-based or neural tree-ensemble architectures purpose-
built for tabular data — FT-Transformer (feature tokenization + transformer
attention), SAINT (adds row-wise/"intersample" attention), NODE (differentiable
oblivious trees), TabNet (sequential attention-based feature selection marketed
for interpretability).

**Case for it.** These are the standard 2023-2025 answer to "can deep learning
finally beat gradient boosting on tabular data," and FT-Transformer in particular
is reported as the most broadly competitive of the family across benchmark tasks.

**Case against.** The dominant, repeatedly-replicated 2022-2025 finding
(Grinsztajn et al. and its 2024-2025 follow-ups) is that tree-based models still
outperform deep learning on typical tabular data at medium dataset sizes, and that
this gap does *not* disappear after hyperparameter tuning — it comes from a real
inductive-bias mismatch (trees handle irregular, non-smooth target functions and
uninformative features better), not just under-tuned baselines. This project's
panel is squarely in the size regime where that finding applies: ~1,600 names,
~24 features, no natural way to manufacture more independent cross-sectional
rows without changing the universe itself. Gu/Kelly/Xiu's own results are
sometimes cited as neural nets beating trees, but their panel is far larger
(thousands of stocks over 60 years monthly) and their strongest configurations use
substantial dropout/regularization/ensembling specifically to fight overfitting at
that scale — machinery this project would also need, adding engineering cost on
top of an approach with a worse prior of working here in the first place. TabNet's
built-in "interpretability" via attention masks is also weaker in practice than
advertised and shouldn't be counted as offsetting the black-box cost relative to
a tree's native feature importances.

**Cost/complexity.** High — new framework (PyTorch/TensorFlow rather than the
existing scikit-learn/XGBoost stack), GPU-friendlier but not GPU-required, real
hyperparameter surface (attention heads, embedding dims, dropout, learning-rate
schedules), and a materially harder-to-audit model for a solo project that has
already been burned once by a signal (the sector bet) it didn't initially
recognize — a black box makes that kind of mistake harder to catch, not easier.

**PIT / walk-forward CV feasibility.** Technically feasible (same PIT feature
matrix, same purge/embargo discipline applies to any model) but the practical risk
is higher: more hyperparameters to tune inside 2007-2020 means more chances to
implicitly overfit the *validation* split itself, which is a documented failure
mode in this exact project (the xrank cell looked good on in-sample validation and
lost badly on 2020-2026 hold-out). Deep nets typically need more, not fewer,
careful validation folds to catch that.

**Verdict.** Interesting in general, poor fit here. Skip unless the data-sourcing
workstream materially grows the effective panel size (e.g., meaningfully more
tickers, higher-frequency snapshots) in a way that changes the data-hunger
calculus — not a near-term priority.

---

### 13. Tabular foundation models (TabPFN-2.5 and successors)
**Likelihood of real uplift: Low-Medium** · **Fit to constraints: Medium**

**What it is.** In-context-learning transformers pretrained on millions of
synthetic tabular tasks, used zero-shot or lightly fine-tuned at inference time —
no gradient-descent training on the target dataset itself. TabPFN-2.5 (2025-2026)
reports a 100% win rate against default (untuned) XGBoost on small classification
datasets (≤10K rows, ≤500 features) and handles up to ~100K rows / ~2K features,
comfortably inside this project's per-date cross-section size.

**Case for it.** This is the one deep-learning-adjacent item on this list that
doesn't fail the data-hunger filter outright — it was built specifically for the
small/medium regime this project sits in, and "zero-shot, no tuning" is a
genuinely different cost profile than the rest of the deep-learning family: a
single day's cross-sectional snapshot (~1,600 rows × ~24 features) is well within
its documented sweet spot, and there's no hyperparameter search to accidentally
overfit against the 2007-2020 validation window the way a from-scratch neural net
risks. Worth a cheap pilot for exactly that reason — low tuning-related leakage
risk, fast to try.

**Case against.** Its evaluation basis is per-snapshot i.i.d. tabular prediction —
the benchmarks it wins on are static classification/regression tasks, not
walk-forward panel forecasting with a moving time axis, so how well "one date's
cross-section treated as an i.i.d. table" reflects a genuinely time-aware model is
untested territory, not a solved problem the vendor's benchmarks answer. Comparing
it against tuned XGBoost (not default XGBoost, which is what its headline win-rate
figure is measured against) is the fair comparison and is far less clearly in
TabPFN's favor. It's also a third-party pretrained model with real replicability
and versioning risk for a production pipeline (the model itself could change
between vendor releases in ways outside this project's control) — a different
kind of operational risk than anything else on this list.

**Cost/complexity.** Low-Medium — a pip-installable library, no training pipeline
needed, but real work to build a proper per-date walk-forward evaluation harness
around a model that wasn't designed with a time axis in mind, and to compare
fairly against a *tuned* XGBoost baseline rather than TabPFN's own marketing
comparison point.

**PIT / walk-forward CV feasibility.** Genuinely fine on the no-lookahead axis
(the pretrained model itself never saw this project's data, so there's no
leakage from *pretraining*), but purging/embargoing has to be handled entirely in
how the per-date "context" table is constructed at inference time — an
under-specified problem this project would have to solve itself, since TabPFN's
own literature doesn't address walk-forward panel use.

**Verdict.** The most interesting cutting-edge item on this list precisely because
it's the one built for this exact data regime — worth a cheap, honest pilot (one
walk-forward window, compared against *tuned* XGBoost, not default) once the
data-sourcing workstream's cheap wins are exhausted, but not ahead of them.

---

### 14. Regime-aware / time-varying-coefficient models
**Likelihood of real uplift: Low** · **Fit to constraints: Low**

**What it is.** Models that let feature-return relationships shift with a latent
or observed market state — particle-filter regime-switching factor models,
regime-switching VAEs (e.g. HireVAE), or simpler time-varying-coefficient
regressions, as opposed to a single fixed mapping trained once over the full
history.

**Case for it.** There's active 2025-2026 research in this space, and the
intuition is real: a feature that predicts returns in a low-vol regime may not in
a high-vol one, and this project's own `regime_signals_beta.py` already
demonstrated the team can build and evaluate a 2-state Markov regime model.

**Case against — the load-bearing point.** This project already tried exactly
this idea, at the whole-market level, and explicitly retired it: "we are no
longer using the HMM," per Gabe's own instruction, with the augmented+stop-loss
model promoted to primary specifically to replace the HMM-gated blend. Any new
regime-aware architecture needs to reckon directly with *why* that was retired
(not documented in this repo's git history, but the decision itself is
unambiguous and recent) before re-proposing essentially the same idea in new
architectural clothing — a per-stock or per-sector regime layer (an idea already
logged as a possible extension in `AGENTS.md`, not yet built) is a genuinely
different granularity than the retired whole-market gate, but it inherits the same
core risk: regime models add real estimation uncertainty (how many states, how to
detect a transition point-in-time without hindsight) on top of a feature set that
hasn't yet been shown to carry a confirmed signal in *any* single regime, let
alone several separately-estimated ones. Adding regime-conditioning multiplies the
effective number of parameters being fit against a modest amount of cross-
sectional history, which is a bad trade against the breadth-ceiling and small-
sample findings already on record.

**Cost/complexity.** Medium-High — genuinely novel modeling work (state
estimation, transition dynamics, point-in-time-safe regime detection), not a
config change.

**PIT / walk-forward CV feasibility.** The hardest item on this list to get right:
regime *detection* itself must be point-in-time (no using the full-sample-fitted
regime label, which is a classic and easy-to-miss lookahead leak in this exact
model family), and the purge/embargo boundary has to account for regime labels
potentially being informed by data spanning the boundary — a real, specific risk
this project has direct institutional memory of, since the retired HMM gate was
built and evaluated by this same team.

**Verdict.** Don't reopen this without Gabe explicitly deciding to, and if he
does, treat it as resuming a workstream he closed, not adopting new architecture —
frame it that way rather than re-pitching the same idea as if it were novel. Not
recommended as a near-term priority given everything else on this list is cheaper
and doesn't carry this same retirement history.

---

### 15. Time-series foundation models (Chronos-2, TimesFM 2.5, MOIRAI-2.0, Kronos) for the stock classifier
**Likelihood of real uplift: Low (for this use)** · **Fit to constraints: Low (for this use)**

**What it is.** Pretrained sequence-forecasting transformers, generic
(Chronos-2/TimesFM/MOIRAI) or finance-specific (Kronos, pretrained on 12B+ K-line
records).

**Case for it — and why it's already been researched, and already redirected.**
This is already covered in `AGENTS.md`: generic TSFMs pretrained on non-financial
data are a weak zero-shot fit for daily equity returns (significant gains over a
random-walk benchmark in only 2 of 10 tested equity/model pairs in a cited 2026
study), while Kronos's finance-specific pretraining does meaningfully better,
meaning domain-matched pretraining data matters more than model architecture
choice. That research already concluded the better fit in this project isn't the
buy/no-buy classifier — a classification task on ~24 hand-engineered features, not
a raw sequence-forecasting problem — but the **options premium model**, which
already needs a predicted *distribution* over the underlying's future price, the
exact native output shape a TSFM like Chronos-2 produces.

**Case against (for the stock classifier specifically).** Nothing has changed
since that research to revisit the conclusion — the classifier's task shape still
doesn't match what a TSFM is built for, and duplicating that analysis here would
just restate it.

**Cost/complexity.** N/A for the stock classifier (not the right tool for the
task, independent of cost).

**PIT / walk-forward CV feasibility.** N/A here — see the same caveat already
logged in `AGENTS.md`: train/test overlap between a TSFM's pretraining corpus and
common evaluation datasets is a documented risk, and any future pilot (options
model, per the existing note) should fine-tune/few-shot-adapt on this project's
own tickers and be benchmarked against the deployed Tweedie GLM, not trusted
zero-shot.

**Verdict.** Out of scope for the stock architecture question this report is
answering. Listed here only to be explicit that it was considered and the right
answer is "already researched, already pointed at the other model" — see
`AGENTS.md`'s existing TSFM section rather than treating this as a fresh
recommendation.

---

## Do these first

Favoring cheap, testable, low-engineering-risk moves first, per the brief:

1. **Hold the current architecture as the deployed model (#1)** and put the next
   real block of effort into the data-sourcing queue already ranked in
   `2026-09-17-new-data-sourcing-research.md` — nothing on this list has a
   stronger case than "the feature set, not the function class, is still the open
   question."
2. **Interaction-constrained XGBoost (#2)** and **Elastic Net (#7)**, run in
   parallel — both are config-level or near-config-level changes, both directly
   probe whether what's left post-Round-11 is linear/additive or genuinely needs
   tree nonlinearity, and both double as evidence for or against the
   `volatility_60`-dominance concern at essentially zero cost.
3. **Conformal prediction for position sizing (#11)** — the cheapest item on the
   whole list, doesn't require resolving the edge question at all, and directly
   targets a real, already-documented gap (no stop-loss on the deployed config).
4. **Monotonic constraints (#3)** and **Random Forest as a comparison arm (#4)** —
   both cheap, both mainly valuable for auditability/independent-confirmation
   rather than expected lift; run once #2/#7 are done so the feature groupings and
   linear-vs-nonlinear read-out can inform how to set them up.
5. **A cheap TabPFN-2.5 pilot (#13)** — the one deep-learning-family item that
   doesn't fail the data-hunger filter, worth a single honest walk-forward-window
   test against *tuned* XGBoost once the above are done, specifically because it's
   fast to try and low-risk to abandon.

**Wait on:** weak-learner stacking (#8) and Bayesian Model Averaging (#9) until
#2/#7 clarify how to split feature groups sensibly; quantile regression forests
(#10) until a real point-estimate signal is confirmed (distributional forecasting
is a risk-management upgrade on top of an edge, not a way to find one); modern
tabular deep learning (#12) unless the universe or snapshot frequency materially
grows; and regime-aware modeling (#14) indefinitely unless Gabe explicitly decides
to reopen a workstream he already closed. Time-series foundation models (#15)
belong to the options model, not this question, and are already logged there.
