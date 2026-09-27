"""WO-15 Addendum A isolation test on a SCRATCH copy of the store (never main).
usage: python wo15_isolation_test.py <mode> <scratch_dir> [reuse]
modes: force_stop (pull raises) | cap_stop (1% cap forced to 0) | plan_fail (SF.todo_dates raises)
       | guard_fail (SF.log_guard raises after a SUE record) | happy (no forcing)
Every write path is patched to <scratch_dir>; the main store's sha1s are compared before/after."""
import hashlib, shutil, sys, io, contextlib
from pathlib import Path
import pandas as pd
WT = Path("/Users/ggraham/pipe_dream/.claude/worktrees/agent-a505179eca9ed9bf2/final/src")
sys.path.insert(0, str(WT / "reset2026")); sys.path.insert(0, str(WT / "sue"))
MAIN = Path("/Users/ggraham/pipe_dream/final/out/reset2026")
SH = Path("/Users/ggraham/pipe_dream/final/data/sharadar")
mode, S = sys.argv[1], Path(sys.argv[2])
fresh = len(sys.argv) < 4 or sys.argv[3] != "reuse"

def sha(p): return hashlib.sha1(p.read_bytes()).hexdigest() if p.exists() else None
MAIN_FILES = [MAIN / n for n in ("prediction_ledger.csv", "prediction_ledger_v2.csv", "prediction_ledger_v3.csv",
              "prediction_ledger_ext.csv", "prediction_ledger_hedge.csv", "prediction_ledger_sue.csv",
              "ledger_record_log.csv", "ledger_record_annotations.csv", "ledger_panel_manifest.json",
              "ledger_sue_guard_log.csv")] + [SH / "sf1_arq_eps_live_accepted.csv", SH / "sf1_arq_eps_live.parquet"]
main_before = {p: sha(p) for p in MAIN_FILES}

if fresh:
    if S.exists(): shutil.rmtree(S)
    S.mkdir(parents=True)
    for n in ("prediction_ledger.csv", "prediction_ledger_v2.csv", "ledger_record_log.csv",
              "ledger_record_annotations.csv", "ledger_panel_manifest.json"):
        shutil.copy2(MAIN / n, S / n)
    # v3/ext/hedge: byte-prefix truncation dropping the 09-18 and 09-24 records (tail-contiguous)
    for n in ("prediction_ledger_v3.csv", "prediction_ledger_ext.csv", "prediction_ledger_hedge.csv"):
        lines = (MAIN / n).read_bytes().split(b"\n")
        d = pd.read_csv(MAIN / n, usecols=["panel_date"])["panel_date"].astype(str)
        k = int((d < "2026-09-18").sum())
        assert (d.iloc[:k] < "2026-09-18").all() and (d.iloc[k:] >= "2026-09-18").all()
        (S / n).write_bytes(b"\n".join(lines[:k + 1]) + b"\n")
        assert pd.read_csv(S / n).equals(pd.read_csv(MAIN / n).iloc[:k].reset_index(drop=True)), n

import working_panel as W, prediction_ledger as PL, forward_hedge as FH
import record_weekly as RW, sue_forward as SF
# patch every WRITE path to the scratch dir
W.MANIFEST = S / "ledger_panel_manifest.json"
PL.OUT_DIR = S; PL.LEDGER_CSV = S / "prediction_ledger_v3.csv"; PL.EXT_CSV = S / "prediction_ledger_ext.csv"
PL.SCORES_CSV = S / "x_scores.csv"; PL.EXT_SCORES_CSV = S / "x_ext_scores.csv"
FH.R26 = S; FH.HEDGE_CSV = S / "prediction_ledger_hedge.csv"; FH.HEDGE_SCORES_CSV = S / "x_hedge_scores.csv"
for k, n in dict(LOG_CSV="ledger_record_log.csv", V3="prediction_ledger_v3.csv", EXT="prediction_ledger_ext.csv",
                 HEDGE="prediction_ledger_hedge.csv", SUE="prediction_ledger_sue.csv",
                 ANN_CSV="ledger_record_annotations.csv", SUE_GUARD_CSV="ledger_sue_guard_log.csv").items():
    setattr(RW, k, S / n)
RW.SUE_REF_LOG = S / "sf1_arq_eps_live_accepted.csv"
RW.ALL_LEDGERS = [S / n for n in ("prediction_ledger.csv", "prediction_ledger_v2.csv", "prediction_ledger_v3.csv",
                  "prediction_ledger_ext.csv", "prediction_ledger_hedge.csv", "prediction_ledger_sue.csv")]
SF.OUT_DIR = S; SF.SUE_CSV = S / "prediction_ledger_sue.csv"; SF.SUE_SCORES_CSV = S / "x_sue_scores.csv"
SF.LOG_CSV = S / "ledger_record_log.csv"; SF.ANN_CSV = S / "ledger_record_annotations.csv"
SF.GUARD_CSV = S / "ledger_sue_guard_log.csv"; SF.REF_LOG = S / "sf1_arq_eps_live_accepted.csv"
SF.BACKFILL_DECISION = "attempt"          # test only: make 2026-09-18 a SUE date
RW._sue_forward = lambda: SF
if mode == "force_stop":
    def _boom(*a, **k): raise SystemExit("FORCED SUE STOP (isolation test)")
    SF.ensure_live = _boom
elif mode == "cap_stop":
    SF.NONUNIFORM_CAP = 0.0
elif mode == "plan_fail":
    def _boom(*a, **k): raise RuntimeError("FORCED todo_dates failure (isolation test)")
    SF.todo_dates = _boom
elif mode == "guard_fail":
    def _boom(*a, **k): raise RuntimeError("FORCED log_guard failure (isolation test)")
    SF.log_guard = _boom
before = {p.name: (p.stat().st_size, hashlib.sha256(p.read_bytes()).hexdigest()) for p in S.iterdir()}
sys.argv = [sys.argv[0]]
rc = RW.main()
after = {p.name: p.read_bytes() for p in S.iterdir()}
print(f"=== mode {mode}: record_weekly rc={rc}")
for n, (sz, h) in sorted(before.items()):
    if n.endswith(".json"): continue
    b = after[n]
    ok = hashlib.sha256(b[:sz]).hexdigest() == h
    print(f"  {n}: {sz} -> {len(b)} bytes, prefix hash {'HOLDS' if ok else 'BROKEN'}")
for n in sorted(set(after) - set(before)):
    print(f"  NEW {n}: {len(after[n])} bytes")
for n in ("prediction_ledger_v3.csv", "prediction_ledger_ext.csv", "prediction_ledger_hedge.csv", "prediction_ledger_sue.csv"):
    p = S / n
    if p.exists():
        print(f"  {n} dates: {pd.read_csv(p, usecols=['panel_date'])['panel_date'].astype(str).value_counts().sort_index().tail(2).to_dict()}")
for n in ("ledger_sue_guard_log.csv", "sf1_arq_eps_live_accepted.csv"):
    if (S / n).exists(): print(f"--- {n}\n{(S / n).read_text()}")
print("  log tail:\n" + "\n".join((S / "ledger_record_log.csv").read_text().splitlines()[-4:]))
main_after = {p: sha(p) for p in MAIN_FILES}
print("MAIN STORE UNCHANGED:", main_before == main_after)
