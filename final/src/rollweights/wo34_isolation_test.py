"""WO-34 isolation test of the r252 side ledger inside record_weekly.py, on a
SCRATCH copy of the store (never main). Built on WO-27's harness
(final/src/overnight/wo27_isolation_test.py: setup / fingerprint / hashes).

usage:
  python wo34_isolation_test.py all <scratch_root> <baseline_record_weekly.py>
  python wo34_isolation_test.py <mode> <scratch_dir> [<baseline_record_weekly.py>]

modes:
  baseline         the PRE-WO-34 record_weekly.py (no r252 at all)
  happy            no forcing: everything records, r252 included
  r252_import      record_weekly's r252 import raises            -> r252 skipped
  r252_plan        r252_forward.side_ledgers raises               -> r252 skipped
  r252_pinmissing  pinned IC file missing (real code path)        -> r252 skipped
  r252_build       build_r252_rows raises                          -> r252 skipped
  r252_lowlabel    matured-label coverage floor not met (real raise in live_ic) -> r252 skipped
  r252_record      record_r252 raises before appending             -> r252 skipped
  r252_half        record_r252 appends THEN raises -> reported at the end, rc 1,
                   AFTER every other ledger recorded
  r252_guardfail   r252_build forced AND the r252 guard log cannot be written -> still rc 0
  seas_skip        build_seas_rows raises -> seas skipped, so io and r252 MUST skip
  second_run       run 1 with r252_build forced, run 2 clean: r252 records, nothing else new
"Identical" = WO-27's content hash: the CSV content with recorded_at removed
(timestamps differ per run), for v3/ext/hedge/sue/seas/blend_seas/io, plus the
record-log rows of those ledgers. The main store is fingerprinted before/after."""
import json
import subprocess
import sys
import time
from pathlib import Path

import pandas as pd

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE.parent / "overnight"))
sys.path.insert(0, str(HERE))
import wo27_isolation_test as T                     # noqa: E402  (also sets sys.path for reset2026/sue/seasonality/overnight)

OTHER = T.OTHER + (T.IO_NAME,)                      # v3/ext/hedge/sue/seas/blend_seas/io
R_NAME = "prediction_ledger_r252.csv"
P_NAME = "r252_weight_path.csv"
G_NAME = "ledger_r252_guard_log.csv"
MODES = ["baseline", "happy", "r252_import", "r252_plan", "r252_pinmissing", "r252_build", "r252_lowlabel",
         "r252_record", "r252_half", "r252_guardfail", "seas_skip", "second_run"]
SKIP_LOGGED = ("r252_import", "r252_plan", "r252_pinmissing", "r252_build", "r252_lowlabel", "r252_record",
               "seas_skip", "second_run")


def patch(S, base_rw=None):
    RW, SS, IOF, IL = T.patch(S, base_rw)
    import r252_forward as RF
    RF.OUT_DIR = S; RF.R252_CSV = S / R_NAME; RF.R252_SCORES_CSV = S / "x_r252_scores.csv"
    RF.PATH_CSV = S / P_NAME; RF.LOG_CSV = S / "ledger_record_log.csv"
    RF.ANN_CSV = S / "ledger_record_annotations.csv"; RF.GUARD_CSV = S / G_NAME
    RF.START_AFTER = pd.Timestamp("2026-09-08")      # test only
    if hasattr(RW, "_r252_forward"):
        RW.R252 = S / R_NAME; RW.R252_PATH = S / P_NAME; RW.R252_GUARD_CSV = S / G_NAME
        RW.ALL_LEDGERS = list(RW.ALL_LEDGERS) + [S / R_NAME]
        RW._r252_forward = lambda: RF
    return RW, SS, RF


def force(mode, S, RW, SS, RF):
    if mode == "r252_import":
        def _imp():
            raise ImportError("FORCED r252_forward import failure (isolation test)")
        RW._r252_forward = _imp
    elif mode == "r252_plan":
        RF.side_ledgers = T._boom("r252 side_ledgers failure")
    elif mode == "r252_pinmissing":
        RF.PINNED_CSV = S / "no_such_pinned.csv"
    elif mode in ("r252_build", "r252_guardfail"):
        RF.build_r252_rows = T._boom("build_r252_rows failure")
        if mode == "r252_guardfail":
            (S / G_NAME).mkdir()
    elif mode == "r252_lowlabel":
        RF.LABEL_MIN_COVERAGE = 1.01
    elif mode == "r252_record":
        RF.record_r252 = T._boom("record_r252 failure")
    elif mode == "r252_half":
        _orig = RF.record_r252
        def _half(t, rows):                                  # noqa: E306
            _orig(t, rows)
            raise RuntimeError("FORCED failure AFTER the r252 append (isolation test)")
        RF.record_r252 = _half
    elif mode == "seas_skip":
        SS.build_seas_rows = T._boom("build_seas_rows failure")
    elif mode not in ("happy", "baseline", "second_run"):
        raise SystemExit(f"unknown mode {mode}")


def dates(S):
    out = {}
    for n in OTHER + (R_NAME,):
        p = S / n
        out[n] = sorted(pd.read_csv(p, usecols=["panel_date"])["panel_date"].astype(str).unique()) if p.is_file() else []
    return out


def one(mode, S, base_rw):
    main_before = T.fingerprint()
    T.setup(S)
    res = {"mode": mode}
    RW, SS, RF = patch(S, base_rw if mode == "baseline" else None)
    sys.argv = [sys.argv[0]]
    if mode == "second_run":
        orig = RF.build_r252_rows
        RF.build_r252_rows = T._boom("build_r252_rows failure (run 1)")
        rc1 = RW.main()
        d1 = dates(S)
        res.update({"run1_rc": rc1, "run1_r252_dates": d1[R_NAME]})
        RF.build_r252_rows = orig
        rc = RW.main()
        d2 = dates(S)
        res["run2_new_other_records"] = sum(len(set(d2[n]) - set(d1[n])) for n in OTHER)
    else:
        force(mode, S, RW, SS, RF)
        rc = RW.main()
    res["rc"] = rc
    res["dates"] = dates(S)
    res["content"] = {n: T.content_hash(S / n) for n in OTHER}
    res["log_other"] = T.log_hash(S / "ledger_record_log.csv", list(OTHER))
    g = S / G_NAME
    res["r252_guard_logged"] = bool(g.is_file() and "r252_skipped" in g.read_text())
    res["r252_guard_rows"] = g.read_text().splitlines()[1:] if g.is_file() else []
    if (S / R_NAME).is_file():
        r = pd.read_csv(S / R_NAME, float_precision="round_trip")
        sea = pd.read_csv(S / "prediction_ledger_seas.csv", float_precision="round_trip")
        m = r.merge(sea[["panel_date", "ticker", "icw9_seas_score"]], on=["panel_date", "ticker"], suffixes=("", "_s"))
        res["r252_rows"] = int(len(r))
        res["r252_vs_seas_icw9_max_abs"] = float((m["icw9_seas_score"] - m["icw9_seas_score_s"]).abs().max())
        res["r252_refits_used"] = sorted(int(x) for x in r["refit_idx"].unique())
    if (S / P_NAME).is_file():
        res["weight_path_refits"] = [int(x) for x in pd.read_csv(S / P_NAME)["refit_idx"]]
    main_after = T.fingerprint()
    changed = sorted(k for k in set(main_before) | set(main_after) if main_before.get(k) != main_after.get(k))
    res["main_store_unchanged"] = not changed
    res["main_store_changed"] = changed[:10]
    (S.parent / f"{mode}.result.json").write_text(json.dumps(res, indent=1, default=str))
    print(json.dumps({k: v for k, v in res.items() if k != "content"}, default=str, indent=1))


def run_all(root, base_rw):
    start = time.time()
    root = Path(root)
    root.mkdir(parents=True, exist_ok=True)
    out = {}
    for m in MODES:
        s = root / m
        rp = root / f"{m}.result.json"
        if rp.exists():
            rp.unlink()
        r = subprocess.run([sys.executable, __file__, m, str(s), str(base_rw)], capture_output=True, text=True)
        res = json.loads(rp.read_text()) if rp.exists() else {
            "crashed": True, "rc": None, "dates": {n: None for n in OTHER + (R_NAME,)}, "content": {},
            "log_other": None, "main_store_unchanged": False}
        res["subprocess_rc"] = r.returncode
        res["log_tail"] = (r.stdout + r.stderr).splitlines()[-12:]
        out[m] = res
        print(f"=== {m}: rc={res.get('rc')} r252_dates={res.get('dates', {}).get(R_NAME)} "
              f"main_unchanged={res.get('main_store_unchanged')} ({time.time()-start:.0f}s)", flush=True)
    base = out["baseline"]
    new_v3 = [d for d in base["dates"]["prediction_ledger_v3.csv"] if d > "2026-09-08"]
    expect_r = {m: (new_v3 if m in ("happy", "r252_half", "second_run") else []) for m in MODES}
    verdict = {}
    for m, r in out.items():
        skipset = ("prediction_ledger_seas.csv", T.IO_NAME) if m == "seas_skip" else ()
        others = [n for n in OTHER if n not in skipset]
        same = {n: (r["content"].get(n, "missing") == base["content"][n]) for n in others}
        logs_same = r["log_other"] == base["log_other"] if m != "seas_skip" else True
        r_ok = r["dates"][R_NAME] == expect_r[m]
        core = all(set(new_v3) <= set(r["dates"][n] or []) for n in T.OTHER[:3])
        extra = True
        if m == "seas_skip":
            extra = r["dates"]["prediction_ledger_seas.csv"] == [] and r["dates"][T.IO_NAME] == []
        if m == "second_run":
            extra = r.get("run2_new_other_records") == 0 and r.get("run1_r252_dates") == []
        if m in SKIP_LOGGED:
            extra = extra and r.get("r252_guard_logged", False)
        if m in ("happy", "second_run"):
            extra = extra and r.get("r252_vs_seas_icw9_max_abs") == 0.0 and r.get("weight_path_refits") == [4935, 4956]
        rc_exp = 1 if m == "r252_half" else 0
        ok = (all(same.values()) and logs_same and r_ok and core and extra and r["rc"] == rc_exp
              and r["main_store_unchanged"])
        verdict[m] = {"pass": bool(ok), "others_identical_to_baseline": same, "sidecar_rows_identical": logs_same,
                      "r252_dates": r["dates"][R_NAME], "core_recorded": core, "rc": r["rc"], "extra": extra,
                      "main_store_unchanged": r["main_store_unchanged"]}
        print(f"  {m}: {'PASS' if ok else 'FAIL'} {verdict[m]}", flush=True)
    res = {"baseline_new_v3_dates": new_v3, "modes": out, "verdict": verdict,
           "all_pass": all(v["pass"] for v in verdict.values())}
    dst = HERE.parents[1] / "out" / "rollweights" / "wo34_isolation_test.json"
    dst.write_text(json.dumps(res, indent=1, default=str))
    print(f"ALL PASS: {res['all_pass']} -> {dst}")
    return 0 if res["all_pass"] else 1


if __name__ == "__main__":
    mode, S = sys.argv[1], Path(sys.argv[2])
    assert "pipe_dream/final" not in str(S.resolve()), "scratch dir must be outside the main checkout"
    if mode == "all":
        sys.exit(run_all(S, sys.argv[3]))
    one(mode, S, sys.argv[3] if len(sys.argv) > 3 else None)
