"""WO-34b isolation test: WO-34's harness (wo34_isolation_test.py, 12 modes,
scratch copy of the store, never main) re-run on the record_weekly.py that now
also calls r252_forward.score() and write_picks(), plus four modes in which
those two new steps fail.

usage:
  python wo34b_isolation_test.py all <scratch_root> <baseline_record_weekly.py>
  python wo34b_isolation_test.py <mode> <scratch_dir> [<baseline_record_weekly.py>]

new modes (the r252 ledger itself records normally in all four):
  post_score      r252_forward.score raises        -> r252_score_skipped logged, picks written, rc 0
  post_picks      r252_forward.write_picks raises  -> r252_picks_skipped logged, no picks file, rc 0
  post_both       both raise                        -> both logged, rc 0
  post_guardfail  both raise AND the r252 guard log cannot be written -> still rc 0
The picks files and the scores file are patched into the scratch dir. PASS for
every mode needs: v3/ext/hedge/sue/seas/blend_seas/io identical to the
PRE-WO-34 baseline (WO-27 content hash + record-log rows), the expected rc,
the expected r252 dates, and the main store unchanged (T.fingerprint covers
final/out top level, where the real picks files live)."""
import json
import subprocess
import sys
import time
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
import wo34_isolation_test as B                     # noqa: E402
T = B.T

PK, PM = "current_signal_r252.csv", "current_signal_r252_meta.json"
POST = ["post_score", "post_picks", "post_both", "post_guardfail"]
MODES = B.MODES + POST
_patch0, _force0 = B.patch, B.force


def patch(S, base_rw=None):
    RW, SS, RF = _patch0(S, base_rw)
    RF.PICKS_CSV, RF.PICKS_META = S / PK, S / PM     # never the main checkout's final/out
    return RW, SS, RF


def force(mode, S, RW, SS, RF):
    if mode not in POST:
        return _force0(mode, S, RW, SS, RF)
    if mode in ("post_score", "post_both", "post_guardfail"):
        RF.score = T._boom("r252 score failure")
    if mode in ("post_picks", "post_both", "post_guardfail"):
        RF.write_picks = T._boom("r252 write_picks failure")
    if mode == "post_guardfail":
        (S / B.G_NAME).mkdir()


B.patch, B.force = patch, force


def one(mode, S, base_rw):
    B.one(mode, S, base_rw)
    rp = S.parent / f"{mode}.result.json"
    res = json.loads(rp.read_text())
    g = S / B.G_NAME
    txt = g.read_text() if g.is_file() else ""
    res["score_skip_logged"] = "r252_score_skipped" in txt
    res["picks_skip_logged"] = "r252_picks_skipped" in txt
    res["picks_written"] = (S / PK).is_file() and (S / PM).is_file()
    res["picks_tmp_left"] = sorted(p.name for p in S.glob("current_signal_r252*.tmp"))
    if res["picks_written"]:
        m = json.loads((S / PM).read_text())
        res["picks"] = {"as_of_date": m["as_of_date"], "n_picks": m["n_picks"], "refit_idx": m["r252"]["refit_idx"],
                        "refit_in_weight_path": m["r252"]["refit_in_weight_path"],
                        "csv_rows": sum(1 for _ in open(S / PK)) - 1}
    res["scores_file"] = (S / "x_r252_scores.csv").is_file()
    res["r252_content"] = T.content_hash(S / B.R_NAME)
    rp.write_text(json.dumps(res, indent=1, default=str))
    print(json.dumps({k: res[k] for k in ("score_skip_logged", "picks_skip_logged", "picks_written", "picks_tmp_left")}))


def run_all(root, base_rw):
    start = time.time()
    root = Path(root)
    root.mkdir(parents=True, exist_ok=True)
    out = {}
    for m in MODES:
        rp = root / f"{m}.result.json"
        if rp.exists():
            rp.unlink()
        r = subprocess.run([sys.executable, __file__, m, str(root / m), str(base_rw)], capture_output=True, text=True)
        res = json.loads(rp.read_text()) if rp.exists() else {
            "crashed": True, "rc": None, "dates": {n: None for n in B.OTHER + (B.R_NAME,)}, "content": {},
            "log_other": None, "main_store_unchanged": False}
        res["subprocess_rc"] = r.returncode
        res["log_tail"] = (r.stdout + r.stderr).splitlines()[-14:]
        out[m] = res
        print(f"=== {m}: rc={res.get('rc')} r252_dates={res.get('dates', {}).get(B.R_NAME)} "
              f"picks={res.get('picks_written')} score_skip={res.get('score_skip_logged')} "
              f"picks_skip={res.get('picks_skip_logged')} main_unchanged={res.get('main_store_unchanged')} "
              f"({time.time()-start:.0f}s)", flush=True)
    base, happy = out["baseline"], out["happy"]
    new_v3 = [d for d in base["dates"]["prediction_ledger_v3.csv"] if d > "2026-09-08"]
    records = ["happy", "r252_half", "second_run"] + POST
    # post-step expectation per mode: (score_skip_logged, picks_skip_logged, picks_written)
    # r252_import: the import itself fails, so both steps skip. pinmissing / lowlabel:
    # the picks step needs the R252 weights, which that forced condition makes unavailable.
    post_exp = {m: (False, False, True) for m in MODES}
    post_exp.update({"baseline": (False, False, False), "r252_import": (True, True, False),
                     "r252_pinmissing": (False, True, False), "r252_lowlabel": (False, True, False),
                     "r252_guardfail": (False, False, True),
                     "post_score": (True, False, True), "post_picks": (False, True, False),
                     "post_both": (True, True, False), "post_guardfail": (False, False, False)})
    verdict = {}
    for m, r in out.items():
        skipset = ("prediction_ledger_seas.csv", T.IO_NAME) if m == "seas_skip" else ()
        others = [n for n in B.OTHER if n not in skipset]
        same = {n: (r["content"].get(n, "missing") == base["content"][n]) for n in others}
        logs_same = r["log_other"] == base["log_other"] if m != "seas_skip" else True
        r_ok = r["dates"][B.R_NAME] == (new_v3 if m in records else [])
        core = all(set(new_v3) <= set(r["dates"][n] or []) for n in T.OTHER[:3])
        extra = True
        if m == "seas_skip":
            extra = r["dates"]["prediction_ledger_seas.csv"] == [] and r["dates"][T.IO_NAME] == []
        if m == "second_run":
            extra = r.get("run2_new_other_records") == 0 and r.get("run1_r252_dates") == []
        if m in B.SKIP_LOGGED:
            extra = extra and r.get("r252_guard_logged", False)
        if m in ("happy", "second_run") + tuple(POST):
            extra = extra and r.get("r252_vs_seas_icw9_max_abs") == 0.0 and r.get("weight_path_refits") == [4935, 4956]
        if m in records:        # the r252 ledger itself is the same whatever the post-steps do
            extra = extra and r.get("r252_content") == happy.get("r252_content")
        post_ok = ((r.get("score_skip_logged"), r.get("picks_skip_logged"), r.get("picks_written")) == post_exp[m]
                   and r.get("picks_tmp_left") == [] and r.get("scores_file") is False)
        if r.get("picks_written"):
            post_ok = post_ok and r["picks"]["n_picks"] == r["picks"]["csv_rows"] == happy["picks"]["n_picks"]
        rc_exp = 1 if m == "r252_half" else 0
        ok = (all(same.values()) and logs_same and r_ok and core and extra and post_ok and r["rc"] == rc_exp
              and r["main_store_unchanged"])
        verdict[m] = {"pass": bool(ok), "others_identical_to_baseline": same, "sidecar_rows_identical": logs_same,
                      "r252_dates": r["dates"][B.R_NAME], "core_recorded": core, "rc": r["rc"], "extra": extra,
                      "post_steps_as_expected": post_ok,
                      "post": {"score_skip_logged": r.get("score_skip_logged"),
                               "picks_skip_logged": r.get("picks_skip_logged"),
                               "picks_written": r.get("picks_written"), "picks": r.get("picks")},
                      "main_store_unchanged": r["main_store_unchanged"]}
        print(f"  {m}: {'PASS' if ok else 'FAIL'} {verdict[m]}", flush=True)
    res = {"baseline_new_v3_dates": new_v3, "modes": out, "verdict": verdict,
           "n_modes": len(verdict), "all_pass": all(v["pass"] for v in verdict.values())}
    dst = HERE.parents[1] / "out" / "rollweights" / "wo34b_isolation_test.json"
    dst.write_text(json.dumps(res, indent=1, default=str))
    print(f"ALL PASS: {res['all_pass']} ({sum(v['pass'] for v in verdict.values())}/{len(verdict)}) -> {dst}")
    return 0 if res["all_pass"] else 1


if __name__ == "__main__":
    mode, S = sys.argv[1], Path(sys.argv[2])
    assert "pipe_dream/final" not in str(S.resolve()), "scratch dir must be outside the main checkout"
    if mode == "all":
        sys.exit(run_all(S, sys.argv[3]))
    one(mode, S, sys.argv[3] if len(sys.argv) > 3 else None)
