# WO-11: v2 is the working panel (2026-09-25)

Gabe, 2026-09-25: "Lets make the v2 panel the working panel going forward,
all models should use it." Decided; this doc records how, not whether.
Worker branch `worktree-agent-ab25d6868c8fadc1a` (based on integration e11d37e).
The forward hedged bet that starts on v2 is in
`2026-09-25-forward-hedged-icw8.md` (WO-10).

## 1. What "the working panel" is now

`final/src/reset2026/working_panel.py` is the one place that says it:

| constant | file |
|---|---|
| `WORKING_PANEL` | `out/reset2026/composite_panel_v2.parquet` (22.5M rows, 9,266 tickers, 2005-01-03..2026-09-08) |
| `WORKING_BETA` / `WORKING_OUTCOME` | `beta_feature_v2.parquet` / `outcome_cache_v2.parquet` |
| `V1_PANEL` | `out/reset2026/composite_panel.parquet` (4,011 tickers). Kept, never deleted |

**The universe rule that comes with v2.** v2 was built with SPACs included.
Every measurement on it (WO-6 column c, WO-7, WO-9) drops them at analysis
time: keep a ticker if it is in the old 4,011-ticker grid OR its SIC industry
is not "Blank Check". The raw v2 `eligible_cap*` flags do not do this. The
rule has to run BEFORE scoring, because `rank_z` ranks the whole
cross-section; a SPAC trading at trust value has `volatility_60` near 0 and
would top an inverse-vol book. `working_cross_section()` applies it; on
2026-09-08 it removes 19 cap150-eligible SPAC rows (0 at cap500 and cap2000).
The old-grid list is frozen in `old_grid_tickers_4011.txt` (sha256-checked),
not read from `composite_panel.parquet`, because the app's Retrain chain
rewrites that file (it did so at 14:31 today). The frozen list equals both
the v1 panel's tickers and `pit_universe.parquet`'s (checked).

**Frozen, not re-derived on v2:** ICW8 `PRODUCTION_WEIGHTS`, ICW9
`ICW9_WEIGHTS`, and the v3 ledger's Fama-MacBeth slope (now the constant
`FM_SLOPE_FROZEN = 0.016276464738787338`, the value the 2026-09-08 v3 record
used; `record()` used to re-fit it on every run). v2 scores use the same
weights and the same `rank_z` standardisation over a different cross-section.

**Dtypes.** `market_cap` is float64 (double) in both v1 and v2; so are
open/close/volatility_60/pct_from_high_252 and both labels. The seven
fundamental/event factors are float32 in both, unchanged from v1. The
float32 builder issue in COO.md (the main checkout's
`build_features_fundamentals_sharadar.py` rewrite) is about value precision,
so the values were checked too: on 2026-09-08 only 48 of 3,901 v2
`market_cap` values (and 6 of 2,289 in the v1 panel as rebuilt at 14:31
today) survive a float32 round-trip unchanged, so both carry full float64
precision. Not re-checked on other dates.

## 2. Every reader of `composite_panel*` and what was done

Switched (live and forward paths):

| file | change |
|---|---|
| `final/src/current_signal_composite.py` | reads `W.working_cross_section` (latest date, rule applied); meta gains `panel_source`, `universe_rule` |
| `final/src/current_signal_blend.py` | composite leg reads the working panel with the rule; q75 leg and cap2000 eligibility (`load_pit_universe`) unchanged; meta gains `composite_panel_source`, `universe_rule` |
| `final/src/reset2026/prediction_ledger.py` | `record`/`score` read the working panel (rule applied in `record`); beta/outcome follow; FM slope frozen; `record` and `record_ext` write the manifest. `selftest` pinned to `V1_PANEL` (it reproduces v1-grid files `new_factors.parquet` and `insider_features.parquet`) |
| `final/scripts/edgar_form4_refresh.py` | issuer set = working panel's recent cap150 names (rule applied): the forward ext records are scored on that cross-section |
| `final/src/reset2026/forward_hedge.py` (new) | on v2 from its first record |

Left on v1, and why:

| file(s) | why |
|---|---|
| `reset2026/build_panel.py`, `downcap_universe.py`, `quality_factors.py` | the v1 builders. The app's Retrain chain still runs them (see §4) |
| `reset2026/run_backtest.py`, `ic_weighted_composite.py`, `build_backtest_equity_curve.py` | reproduce published results: the nomination/hold-out reports, the frozen ICW fit, and the app's published equity curve |
| `reset2026/model_audit.py`, `correction_variants.py`, `cross_model_accuracy.py`, `amihud_and_regime_diagnostic.py`, `beta_diagnostic.py`, `screen_new_factors_and_exponent.py`, `options_overlay_backtest.py`, `investigate_2020.py`, `era_transfer.py`, `price_adjustment_scanner.py` (docstring only) | research that reproduces published numbers |
| `reset2026/build_beta_feature.py`, `build_ewma_beta_feature.py`, `build_new_factors.py` | v1-grid feature builders; v2 equivalents come from `build_downcap_grid_v2.py` |
| `reset2026/downcap_v2_readout.py`, `downcap_grid_acceptance.py`, `downcap_grid_prechecks.py`, `build_downcap_grid_v2.py` | compare v1 and v2 by design, or build v2 |
| `insider/build_insider_panel.py`, `screen_insider.py`, `posthoc_insider.py`; `insider/*_v2grid.py`, `check_mapping_v2grid.py` | insider research (v1 grid, reproduced by the ext selftest) and v1-vs-v2 comparisons |
| `eap/build_eap_signal.py`, `eap/screen_eap.py`, `scripts/edgar_8k_item202_pull.py` | EAP, certified DEAD |
| `final/app/**` | no direct panel read. `blend_model.retrain_commands()` runs `downcap_universe.py` → `quality_factors.py` → `build_panel.py` → `current_signal_blend.py`; `composite_model.retrain_commands()` runs `current_signal_composite.py` → `build_backtest_equity_curve.py`. Not edited (app-manager owns it) |

## 3. Ledger switch point

Records are never rewritten. sha256 of every ledger CSV was taken before
any change and re-checked after the hedge record (all unchanged):

| file | sha256 |
|---|---|
| `prediction_ledger.csv` | 4dc52bba... |
| `prediction_ledger_v2.csv` | 3201639a... |
| `prediction_ledger_v3.csv` | 4cc7660b... |
| `prediction_ledger_ext.csv` | a827154b... |

`out/reset2026/ledger_panel_manifest.json` maps {ledger: {panel_date: panel
file}}. It is keyed by ledger because on 2026-09-08 the v1/v2/v3/ext records
are on `composite_panel.parquet` while the hedge record is on
`composite_panel_v2.parquet`. Seeded for the four existing ledgers; every
`record()` now writes its entry and refuses to change an existing one. New
v3/ext records from the next record date on use v2. No new v3/ext record
was written; the record cadence is pending with Gabe.

Scoring the 2026-09-08 v1 records off the working panel is safe: on four
pre-2020 dates, v1 and v2 agree exactly on `forward_return_tradable_40` and
`beta_252` for every common (ticker, date) (8,793 pairs, max |diff| 0), and
`outcome_cache` SPY agrees exactly before 2020; the two SPY rows differ only
from 2026-07-13 on, where v1's cache truncated the 40-day window at its own
series end.

## 4. Open issue for the COO: v2 has no refresh path

`build_downcap_grid_v2.py` refuses to overwrite any output, and the app's
Retrain chain rebuilds v1 only. Once a retrain moves the base panel past
2026-09-08, `current_signal_blend.py` takes `as_of` from the base panel,
finds no v2 rows for that date, and stops ("no eligible rows ... the working
panel (v2) has no refresh path yet"). That stops the primary Today's Picks.
`current_signal_composite.py` keeps showing 2026-09-08. A v2 refresh builder
(and then an app-manager change to `retrain_commands`) is needed. Not built
here: out of scope.

## 5. Live scorers rerun on v2 for 2026-09-08

Outputs were backed up first as `out/current_signal_{composite,composite_meta,
blend,blend_meta,blend_full}_v1panel_2026-09-08.{csv,json}`. The CSV
schemas are unchanged (identical headers). The meta JSONs gain two keys
each and lose none, so the app contract is unchanged.

| | v1 | v2 |
|---|---|---|
| composite (cap150): eligible / picks | 2,214 / 220 | 3,065 / 305 |
| blend (cap2000): scored / picks | 1,665 / 165 | 1,665 / 165 |

## 6. Overlap report, 2026-09-08

`final/src/reset2026/wo11_overlap_report.py` →
`out/reset2026/downcap_v2/wo11_overlap.json`. The composite book is icw8
decile_volq. v1 uses the raw flags; v2 uses the working rule. The cap150 books
equal the live scorer CSVs exactly (v1 backup and v2 rerun).

| tier | v1 eligible / book | v2 eligible / book | common | Jaccard | weight overlap Σmin(w) |
|---|---|---|---|---|---|
| cap150 | 2,214 / 220 | 3,065 / 305 | 215 | 0.694 | 0.734 |
| cap500 | 2,091 / 210 | 2,503 / 250 | 208 | 0.825 | 0.842 |
| cap2000 | 1,665 / 165 | 1,665 / 165 | 165 | 1.000 | 1.000 |
| blend picks | 165 | 165 | 165 | 1.000 | 1.000 (max \|Δw\| 0) |

Top 5 by weight in one book and not the other (weight, market cap):

| tier | v1 only | v2 only |
|---|---|---|
| cap150 | HTLD 0.43% $0.95B; DT 0.36% $14.5B; AEO 0.35% $2.9B; UAA 0.33% $2.2B; CORT 0.24% $12.3B | NATH 1.01% $0.40B; WLKP 0.97% $0.77B; EBF 0.58% $0.54B; VLGEA 0.56% $0.64B; ACEL 0.54% $0.95B |
| cap500 | HTLD 0.43% $0.95B; AEO 0.36% $2.9B (only 2) | WLKP 1.12% $0.77B; EBF 0.67% $0.54B; VLGEA 0.65% $0.64B; ACEL 0.63% $0.95B; GIC 0.60% $1.5B |
| cap2000 | none | none |

At cap2000 the v2 flags and universe equal v1 on this date, so the blend's
composite leg, and its picks, did not move. The v1-only names at cap150
(DT, CORT and others) did not drop out of the universe; the larger v2
cross-section shifted the within-bucket ranks. The v2-only names are mostly
sub-$1B companies that v1's survivorship-selected grid never held.
