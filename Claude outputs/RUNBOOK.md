> **SUPERSEDED — do not follow this file.**
>
> This is the Round 12-only runbook, frozen 2026-09-09. The live version is
> `final/src/sweep/RUNBOOK.md`, which covers Rounds 12-19 and carries the
> current module map, feature sets, results table, bug ledger and standing
> rules.
>
> Two things here are now actively wrong:
>
> - The **feature-admission gate** changed in Round 19. IC is retired as an
>   admission criterion (rank correlation with what a cell earns: **+0.019**
>   across 64 cells). The replacement is a shuffled-feature null scored on
>   `decile_volq_excess`. See `final/src/sweep/RUNBOOK.md` §9.
> - The **hold-out is spent.** 2020-2026 was used in Round 13 and again in
>   Round 18. Nothing nominated from here is confirmable on data that exists.
>
> Kept for provenance: the Round 12 numbers quoted elsewhere were produced by
> these exact commands.

---

# Round 12 sweep — runbook

One command per line. A trailing `# comment` parses as an argparse argument and
has silently skipped probes on this project before, so nothing below has one.

All commands run from `~/pipe_dream/final/src` in your own terminal. The device
bridge caps at ~3.9GB RAM and ~45s per command, which is well short of what a
panel load needs.

```
cd ~/pipe_dream/final/src
```

---

## Step 0 — regenerate the frozen grid (seconds)

```
python3 sweep/gridspec.py all
```

Expect: `27 entries -> cells_phase_a.json`, `48 entries -> grid_portfolio.json`,
and `Phase A trial count: 1296`.

---

## Step 1 — timing probe (~20–30 min)

```
python3 -m sweep.cli probe --start 2023-01-03 --caps 0,1500000,500000
```

This runs the last ~8 walk-forward steps at three training-set sizes. Those are
the *most expensive* steps (the expanding window is largest at the end), so the
`sec_per_step` it reports is an upper bound on the run average.

**This is the number that sizes everything.** Phase A is 27 cells run
sequentially so the panel load is shared, so the overnight cost is roughly
`27 × sec_per_step × 124 / 3600` hours plus ~6 panel loads.

- If that lands under ~10 hours at `train_cap=0`, run Phase A uncapped.
- If it doesn't, tell me the numbers and I'll re-freeze the grid with a
  training cap **before** any cell runs. The probe reveals only timing, never a
  performance result, so amending the grid on it is not peeking — but it gets
  its own commit and an explicit note in the pre-registration either way.

---

## Step 2 — the blocking correctness gate (~1 walk-forward run)

```
python3 -m sweep.cli verify
```

Runs the sweep harness at the exact production config and compares its top-5
picks, window by window, against
`out/continuous_walkforward_pit_augmented_pit_realistic_tradable.json`.

**Do not run Step 3 until this prints `VERIFY PASS`.** If the harness does not
reproduce the production picks pick-for-pick, every sweep cell is measuring
something other than what the baseline measured, and nothing in this round means
anything. If it fails, send me the mismatch examples it prints — the likely
causes in order are a different training-row filter, a different label column,
or XGBoost threading (Gate A3).

---

## Step 3 — Phase A, the expensive half (overnight)

```
nohup python3 -m sweep.cli scores --cells sweep/cells_phase_a.json > ../out/sweep_phase_a.log 2>&1 &
```

Watch it with:

```
tail -f ../out/sweep_phase_a.log
```

Fully resumable. Every cell checkpoints per timepoint and finished cells are
skipped on restart, so you can kill it, close the laptop, and re-run the same
command tomorrow. It groups cells by (panel, horizon) so the panel load is paid
6 times, not 27.

---

## Step 4 — realized outcomes (~10–15 min)

```
python3 -m sweep.cli outcomes
```

Builds every (timepoint, ticker) outcome at 4 horizons × 10 stop levels,
vectorized, then verifies a random sample cell-for-cell against
`execution.realize_position()`. It aborts if any comparison disagrees.

---

## Step 5 — the cheap half (~30–45 min with nulls)

```
python3 -m sweep.cli portfolio --grid sweep/grid_portfolio.json --era nominate --null-draws 100
```

Scores all 1,296 cells on **2007–2019 only** and, for each one, runs 100
matched random-selection draws — the same construction with the rankings
shuffled within each date. Writes `out/sweep/results_nominate.csv` and
`out/sweep/verdict_nominate.json`.

For a fast first look without the nulls, use `--null-draws 0`. The nulls are
what make S4 and the grid-consistency test possible, so the real pass needs
them.

---

## Step 6 — the hold-out. Once.

Only after a config has cleared S1–S4 on the nomination era, and only for that
one config:

```
python3 -m sweep.cli portfolio --grid sweep/grid_portfolio.json --era holdout --only <cell_id> --i-am-confirming --null-draws 200
```

The CLI refuses `--era holdout` without both flags, and refuses to run a grid
there at all. If the nominated config fails here, it fails — it does not get
re-run, re-tuned, or replaced with the runner-up.

---

## What I'll want back

After Step 1: the probe table.
After Step 2: pass/fail, and the mismatch examples if it fails.
After Step 5: `out/sweep/results_nominate.csv` and `verdict_nominate.json`.

The verdict file is the one that matters. `consistency.z_vs_binomial` is the
highest-powered number in it — under the global null it sits near 0, and it does
not depend on which single cell happened to top the table.

---

## Files this added

All new, nothing existing was modified:

```
final/src/sweep/__init__.py
final/src/sweep/_num.py          numeric helpers, no scipy/sklearn dependency
final/src/sweep/outcomes.py      vectorized realized outcomes + reference gate
final/src/sweep/scorecache.py    the expensive half
final/src/sweep/portfolio.py     the cheap half
final/src/sweep/stats.py         DSR, Reality Check, matched null, consistency
final/src/sweep/gridspec.py      the frozen grid
final/src/sweep/cli.py           orchestrator
final/src/sweep/cells_phase_a.json
final/src/sweep/grid_portfolio.json
final/src/sweep/grid_sensitivity.json
```

Per the standing rule I haven't run any git command. When you're ready:

```
cd ~/pipe_dream
git checkout -b round12-sweep
git add final/src/sweep
git commit -m "Round 12: pre-registered parameter sweep harness"
```
