"""
WO-37: prove the --phase2 guard refuses on each ground independently.

    /opt/anaconda3/envs/pipe_dream/bin/python final/src/thinliq/test_guard.py

1. doc not tracked in git        -> refused (true until the pre-reg doc is committed)
2. doc tracked, arrival gate FAIL -> refused (simulated by pointing the doc check at a file that IS tracked)
3. a results file already exists  -> refused (simulated with the arrival gate stubbed to pass and a temp result file)
No label is read: phase2_guard raises before any loader runs.
"""
import json
import subprocess
import tempfile
from pathlib import Path

import tl_common as T


def refusal(fn):
    try:
        fn()
    except SystemExit as e:
        return str(e)
    return None


def main():
    out = {}
    tracked = subprocess.run(["git", "-C", str(T.REPO), "ls-files", "--error-unmatch", T.PREREG_DOC], capture_output=True).returncode == 0
    out["doc_tracked_now"] = tracked
    real_doc = T.PREREG_DOC
    if not tracked:
        out["1_doc_untracked"] = refusal(lambda: T.phase2_guard(T.OUT / "arm1_results.json"))
    else:
        T.PREREG_DOC = "final/models/__no_such_doc__.md"
        out["1_doc_untracked"] = refusal(lambda: T.phase2_guard(T.OUT / "arm1_results.json"))
    T.PREREG_DOC = "final/src/options_wo25/wo25_io.py"       # any tracked file: isolates the arrival gate
    out["2_arrival_gate"] = refusal(lambda: T.phase2_guard(T.OUT / "arm1_results.json"))
    gate = T.arrival_gate
    rep = gate(write=False)
    on_disk = sorted(p.stem.split("=")[1] for p in T.CHAIN.glob("date=*.parquet"))
    T.arrival_gate = lambda write=True: {**rep, "gate_pass": True, "phase2_allowed": True,
                                         "thin_complete_dates": [d for d in rep["thin_complete_dates"] if d in on_disk]}
    with tempfile.TemporaryDirectory() as td:
        f = Path(td) / "arm1_results.json"
        f.write_text("{}")
        out["3_result_exists"] = refusal(lambda: T.phase2_guard(f))
    T.arrival_gate, T.PREREG_DOC = gate, real_doc
    out["all_refused"] = bool(out["1_doc_untracked"] and "not tracked" in out["1_doc_untracked"]
                              and out["2_arrival_gate"] and "arrival gate FAIL" in out["2_arrival_gate"]
                              and out["3_result_exists"] and "exists" in out["3_result_exists"])
    (T.OUT / "guard_test.json").write_text(json.dumps(out, indent=1))
    print(json.dumps(out, indent=1))
    raise SystemExit(0 if out["all_refused"] else 1)


if __name__ == "__main__":
    main()
