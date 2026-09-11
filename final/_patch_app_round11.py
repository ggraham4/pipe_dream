"""Round 11d: rewire the app onto the point-in-time dataset.

WHY REWIRE RATHER THAN REBUILD
------------------------------
The app is ~110KB across app.py and seven lib modules, and none of it is
broken. It handles detached background jobs with pid tracking and log
tailing, atomic reads against files a running job is writing, an options
model, a regime-gate model and a stock model. What is wrong is four
pointers and two command lists. Rebuilding would risk all of the working
machinery to fix that, so this is a targeted patch.

WHAT WAS ACTUALLY BROKEN
------------------------
1. THE PIT RETRAIN BUTTON REBUILT THE WRONG ARTIFACTS AND SAID NOTHING.
   pit_model.retrain_commands() ran:

       features.py -> features_pit.py -> fundamentals_features_pit.py
       -> current_signal_pit.py

   The first three rebuild the OLD panels from td_data_local. The fourth,
   after the Round 11 patch, reads the NEW panel -- which those steps never
   touch. So the button spent ~20 minutes regenerating files nothing reads,
   left the Sharadar panel at whatever date it already held, and then
   emitted a signal against stale prices WITHOUT ERRORING: the freshness
   check sees the unrefreshed panel's last date as fully covered and passes.
   Confidently wrong is the worst failure shape available here.

2. THE APP READ THE OLD PANEL FOR EVERYTHING IT DISPLAYED.
   pit_model.FUND_PIT_PARQUET pointed at features_with_fundamentals_pit.parquet,
   so the picks came from clean data while the momentum, market cap and
   context shown BESIDE each pick came from the contaminated panel.

3. "Retrain ALL models" had the same wrong PIT sequence inline in app.py.

THE NEW PIT SEQUENCE
--------------------
    sharadar_pull_pit_panel.py            top up daily+stocks (skips months
                                          already on disk, so a same-day
                                          rerun is fast)
    build_pit_universe.py                 re-screen as of every date
    build_features_sharadar.py            11 price features + 2 labels
    build_features_fundamentals_sharadar.py  + 14 fundamental features
    export_sharadar_ohlc.py               per-ticker CSVs for execution
    current_signal_pit.py                 retrain + today's picks

run_step_sequence writes `set -e`, so if the first step exits for a missing
SHARADAR_API_KEY the whole job aborts and the log names the step. That is
deliberate: failing loudly beats the silent-stale behaviour above. The key
must therefore be in the environment Streamlit was launched from --
`export SHARADAR_API_KEY=...` before `streamlit run`.

NOT CHANGED, ON PURPOSE
-----------------------
stock_model.py and regime_gate_model.py drive current_signal.py,
lstm_current_signal.py and current_signal_gated.py. Those are DIFFERENT
models on their own (still old-universe) panels. Rewiring them is a
separate piece of work, and quietly repointing them would mix two changes
in one step. They remain on the old data and their outputs should be read
with that in mind.

    python3 patch_app_round11.py
"""
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent
FINAL = ROOT if (ROOT / "app").is_dir() else ROOT / "final"
PIT = FINAL / "app" / "lib" / "pit_model.py"
APP = FINAL / "app" / "app.py"

NEW_STEPS = '''        [py, str(paths.SRC_DIR / "sharadar_pull_pit_panel.py")],
        [py, str(paths.SRC_DIR / "build_pit_universe.py")],
        [py, str(paths.SRC_DIR / "build_features_sharadar.py")],
        [py, str(paths.SRC_DIR / "build_features_fundamentals_sharadar.py")],
        [py, str(paths.SRC_DIR / "export_sharadar_ohlc.py")],
        [py, str(paths.SRC_DIR / "current_signal_pit.py")],'''

LABELS = '''PIT_STEP_LABELS = [
    "Top up the Sharadar price/marketcap panel (needs SHARADAR_API_KEY)",
    "Rebuild the point-in-time universe",
    "Rebuild price features",
    "Rebuild fundamental features",
    "Export per-ticker OHLCV for execution",
    "Retrain primary model + compute today's picks",
]'''


def patch_pit_model():
    s = PIT.read_text()
    orig = s

    old_path = ('FUND_PIT_PARQUET = paths.OUT_DIR / '
                '"features_with_fundamentals_pit.parquet"')
    new_path = ('# Round 11: the rebuilt point-in-time panel. The old file is still on\n'
                '# disk and still readable, but it carries the survivorship-contaminated\n'
                '# universe -- reading it here would show contaminated context beside\n'
                '# clean picks.\n'
                'FUND_PIT_PARQUET = paths.OUT_DIR / '
                '"features_with_fundamentals_sharadar_pit.parquet"')
    if old_path not in s:
        print("  pit_model: FUND_PIT_PARQUET anchor not found (already patched?)")
    else:
        s = s.replace(old_path, new_path, 1)
        print("  pit_model: FUND_PIT_PARQUET -> sharadar panel")

    s = s.replace('"features_with_fundamentals_pit.parquet not found -- "',
                  '"features_with_fundamentals_sharadar_pit.parquet not found -- "')

    old_cmds = '''        [py, str(paths.SRC_DIR / "features.py")],
        [py, str(paths.SRC_DIR / "features_pit.py")],
        [py, str(paths.SRC_DIR / "fundamentals_features_pit.py")],
        [py, str(paths.SRC_DIR / "current_signal_pit.py")],
    ]'''
    if old_cmds not in s:
        print("  pit_model: retrain_commands anchor not found (already patched?)")
    else:
        s = s.replace(old_cmds, NEW_STEPS + "\n    ]", 1)
        print("  pit_model: retrain_commands -> Round 11 sequence (6 steps)")

    if "PIT_STEP_LABELS" not in s:
        s = s.replace("paths.ensure_src_on_path()",
                      "paths.ensure_src_on_path()\n\n" + LABELS, 1)
        print("  pit_model: added PIT_STEP_LABELS")

    if s != orig:
        PIT.write_text(s)
        return True
    return False


def patch_app():
    s = APP.read_text()
    orig = s
    old = '''                [py, str(paths.SRC_DIR / "features.py")],
                [py, str(paths.SRC_DIR / "features_pit.py")],
                [py, str(paths.SRC_DIR / "fundamentals_features_pit.py")],
                [py, str(paths.SRC_DIR / "current_signal.py")],
                [py, str(paths.SRC_DIR / "lstm_current_signal.py")],
                [py, str(paths.SRC_DIR / "current_signal_pit.py")],
            ]'''
    new = '''                # secondary models -- still on the OLD universe, see
                # patch_app_round11.py's "NOT CHANGED, ON PURPOSE"
                [py, str(paths.SRC_DIR / "features.py")],
                [py, str(paths.SRC_DIR / "current_signal.py")],
                [py, str(paths.SRC_DIR / "lstm_current_signal.py")],
                # primary PIT model -- Round 11 sequence
                [py, str(paths.SRC_DIR / "sharadar_pull_pit_panel.py")],
                [py, str(paths.SRC_DIR / "build_pit_universe.py")],
                [py, str(paths.SRC_DIR / "build_features_sharadar.py")],
                [py, str(paths.SRC_DIR / "build_features_fundamentals_sharadar.py")],
                [py, str(paths.SRC_DIR / "export_sharadar_ohlc.py")],
                [py, str(paths.SRC_DIR / "current_signal_pit.py")],
            ]'''
    if old not in s:
        print("  app.py: retrain-all command list not found (already patched?)")
    else:
        s = s.replace(old, new, 1)
        print("  app.py: retrain-all -> secondary (old) + PIT (Round 11)")

    old_lab = '''                "Rebuild price features.parquet",
                "Rebuild PIT price panel (features_pit.py)",
                "Rebuild PIT fundamentals panel",
                "Retrain XGBoost (secondary, price-only)",
                "Retrain LSTM (secondary)",
                "Retrain primary model (augmented + stop-loss, PIT) + compute today's picks",
            ]'''
    new_lab = '''                "Rebuild price features.parquet (secondary models, old universe)",
                "Retrain XGBoost (secondary, price-only, old universe)",
                "Retrain LSTM (secondary, old universe)",
                "Top up the Sharadar panel (needs SHARADAR_API_KEY)",
                "Rebuild the point-in-time universe",
                "Rebuild price features (PIT)",
                "Rebuild fundamental features (PIT)",
                "Export per-ticker OHLCV for execution",
                "Retrain primary model (augmented + stop-loss, PIT) + compute today's picks",
            ]'''
    if old_lab in s:
        s = s.replace(old_lab, new_lab, 1)
        print("  app.py: labels updated")

    if s != orig:
        APP.write_text(s)
        return True
    return False


if __name__ == "__main__":
    print(f"patching {FINAL}/app ...")
    a = patch_pit_model()
    b = patch_app()
    print("\nDone." if (a or b) else "\nNothing changed.")
    print("\nIMPORTANT: the refresh now needs the API key in the environment")
    print("Streamlit was launched from:")
    print('    export SHARADAR_API_KEY="..."')
    print("    streamlit run final/app/app.py")
    print("\nWithout it the first step exits and `set -e` aborts the job --")
    print("deliberately. A refresh that cannot fetch prices must fail loudly")
    print("rather than quietly rebuild on top of a stale panel.")
