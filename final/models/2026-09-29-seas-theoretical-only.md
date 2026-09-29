# 2026-09-29: seas goes live in the Theoretical model only (WO-20-seas-final)

**Decision (Gabe, 2026-09-29, in the moment, in the COO session): "Theoretical only".**

- **Theoretical composite:** live on `icw9_seas` (`current_signal_composite.py`,
  model_version `ic_weighted_seas_2026-09-27`). Unchanged from WO-20
  (`final/models/2026-09-27-wo20-seas-live.md`).
- **Today's Picks blend:** back on its ORIGINAL frozen 9-factor composite leg
  (`_ORIGINAL_FACTOR_SIGNS` / `_compute_composite_frozen`), model_version
  `blend_q75_ew9_2026-09-19`. This is the pre-WO-20 scoring. `main()` no longer
  computes seas at all, so a missing SEP month file can't stop the live blend.
- **10-factor seas blend:** recorded ONLY in its forward side ledger
  (`prediction_ledger_blend_seas.csv`, via `seas_forward.py` ->
  `current_signal_blend.blend_scores_at`). That path and the v10 functions
  (`_BLEND_FACTOR_SIGNS_V10_SEAS`, `_compute_composite_frozen_v10_seas`) are unchanged.

Why: seas was tested in the blend, not deployed (WO-23: blend10 −0.12 pre-2020,
−0.78 2020-26 vs blend9).

## Change (`final/src/current_signal_blend.py` only)

- `BLEND_MODEL_VERSION = "blend_q75_ew9_2026-09-19"`. The 10-factor label is kept
  as `BLEND_MODEL_VERSION_SEAS10_TESTED` (side ledger only).
- `main()` scores the composite leg with `_compute_composite_frozen`. The meta's
  `factors` has the 9 original signs, and `construction` says `composite_9factor_frozen`.
  The WO-20 meta keys `seas` and `picks_overlap_vs_previous_9factor_blend` are gone.
- The `backtest_summary.note_wo20` and meta `note` now say the numbers (incl. the
  −0.36% hold-out) belong to the live 9-factor blend. They also say seas was tested in the blend, not
  deployed. `wo20_seas_pre2020` is kept as the record of that test.
- Module docstring: a WO-20-seas-final note. The WO-20 paragraph is marked superseded for the live path.
- `current_signal_composite.py`, `seas_forward.py`, `seas_live.py`, `record_weekly.py`
  and the app are unchanged.

## Checks (worktree, 2026-09-29)

| Check | Result |
|---|---|
| py_compile (blend, composite, seas_forward, seas_live, build_seas, record_weekly, ic_weighted_composite, isolation test) | OK |
| Blend `--out-dir` vs the pre-WO-20 file (27cc6ce) on the same date (2026-09-25), outputs redirected | picks 160/160 and full 2288/2288 rows identical, max abs diff **0.0**, same NaN pattern |
| Blend meta | `blend_q75_ew9_2026-09-19`, 9 factors, no `seas` |
| Composite `--out-dir` meta | `ic_weighted_seas_2026-09-27`, 9 weights incl. seas |
| `seas_forward.py selftest` | PASS (blend_seas 2026-09-25, 1615 rows, blend10 == blend_scores_at) |
| `wo20_isolation_test.py` all 8 modes | rc 0, MAIN STORE UNCHANGED True, v3/ext/hedge recorded in scratch |
| `record_weekly.py --plan` | rc 0, no missing weeks |
| App AppTest (integration 254ea01 app, blend9 + icw9_seas metas) | 0 exceptions. Blend: "9 composite factors", "The blend shows **-0.36%** excess", no "PREVIOUS 9-factor blend's". Theoretical: 9 factors, `ic_weighted_seas_2026-09-27`, "live icw9_seas version has **no hold-out result**". No app change needed. |
| Live ledgers v3 / ext / hedge sha1 | 963d5e3b / 1eba78b3 / 1c0738be (unchanged) |
