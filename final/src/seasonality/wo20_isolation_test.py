"""WO-20 isolation test of the two side ledgers (seas, blend_seas) inside
record_weekly.py, on a SCRATCH copy of the store (never main). Pattern of
final/src/sue/wo15_isolation_test.py.

usage: python wo20_isolation_test.py <mode> <scratch_dir>
modes:
  happy        no forcing: v3/ext/hedge + seas + blend_seas all record
  plan_fail    seas_forward.side_ledgers raises -> both side ledgers skipped at plan
  seas_build   build_seas_rows raises          -> seas skipped, blend_seas records
  blend_build  blend_scores_at raises          -> blend_seas skipped, seas records
  seas_record  record_seas raises (before append) -> seas skipped, blend_seas records
  blend_half   record_blend appends THEN raises -> reported half-written (rc 1) AFTER
               v3/ext/hedge/seas recorded
  guard_fail   seas_build forced AND log_guard raises -> still v3/ext/hedge/blend record
Every write path is patched to <scratch_dir>. v3/ext/hedge are truncated (byte
prefix) to drop the 2026-09-18 and 2026-09-24 records so there is a week to
record; START_AFTER of the side ledgers is set to 2026-09-08 (test only) so
they have 2026-09-18 to record. The main store (every file under
out/reset2026, data/sharadar top level and out/ top level) is fingerprinted
(size + mtime + sha1 of the ledgers) before and after."""
import hashlib
import shutil
import sys
from pathlib import Path

import pandas as pd

WT = Path(__file__).resolve().parents[1]           # this worktree's final/src
sys.path.insert(0, str(WT / "reset2026")); sys.path.insert(0, str(WT / "sue")); sys.path.insert(0, str(WT / "seasonality"))
MAINF = Path("/Users/ggraham/pipe_dream/final")
MAIN = MAINF / "out" / "reset2026"
mode, S = sys.argv[1], Path(sys.argv[2])
assert "pipe_dream/final" not in str(S.resolve()), "scratch dir must be outside the main checkout"


def fingerprint():
    fp = {}
    for d in (MAIN, MAINF / "data" / "sharadar", MAINF / "out"):
        for p in d.iterdir():
            if p.is_file():
                st = p.stat()
                fp[str(p)] = (st.st_size, st.st_mtime)
    for n in ("prediction_ledger_v3.csv", "prediction_ledger_ext.csv", "prediction_ledger_hedge.csv"):
        fp["sha1:" + n] = hashlib.sha1((MAIN / n).read_bytes()).hexdigest()
    return fp


main_before = fingerprint()
if S.exists():
    shutil.rmtree(S)
S.mkdir(parents=True)
for n in ("prediction_ledger.csv", "prediction_ledger_v2.csv", "ledger_record_log.csv",
          "ledger_record_annotations.csv", "ledger_panel_manifest.json"):
    shutil.copy2(MAIN / n, S / n)
for n in ("prediction_ledger_v3.csv", "prediction_ledger_ext.csv", "prediction_ledger_hedge.csv"):
    lines = (MAIN / n).read_bytes().split(b"\n")
    d = pd.read_csv(MAIN / n, usecols=["panel_date"])["panel_date"].astype(str)
    k = int((d < "2026-09-18").sum())
    assert (d.iloc[:k] < "2026-09-18").all() and (d.iloc[k:] >= "2026-09-18").all()
    (S / n).write_bytes(b"\n".join(lines[:k + 1]) + b"\n")
    assert pd.read_csv(S / n).equals(pd.read_csv(MAIN / n).iloc[:k].reset_index(drop=True)), n

import working_panel as W, prediction_ledger as PL, forward_hedge as FH   # noqa: E401,E402
import record_weekly as RW, sue_forward as SF, seas_forward as SS         # noqa: E401,E402
W.MANIFEST = S / "ledger_panel_manifest.json"
PL.OUT_DIR = S; PL.LEDGER_CSV = S / "prediction_ledger_v3.csv"; PL.EXT_CSV = S / "prediction_ledger_ext.csv"
PL.SCORES_CSV = S / "x_scores.csv"; PL.EXT_SCORES_CSV = S / "x_ext_scores.csv"
FH.R26 = S; FH.HEDGE_CSV = S / "prediction_ledger_hedge.csv"; FH.HEDGE_SCORES_CSV = S / "x_hedge_scores.csv"
for k, n in dict(LOG_CSV="ledger_record_log.csv", V3="prediction_ledger_v3.csv", EXT="prediction_ledger_ext.csv",
                 HEDGE="prediction_ledger_hedge.csv", SUE="prediction_ledger_sue.csv",
                 ANN_CSV="ledger_record_annotations.csv", SUE_GUARD_CSV="ledger_sue_guard_log.csv",
                 SEAS="prediction_ledger_seas.csv", BLEND_SEAS="prediction_ledger_blend_seas.csv",
                 SEAS_GUARD_CSV="ledger_seas_guard_log.csv").items():
    setattr(RW, k, S / n)
RW.SUE_REF_LOG = S / "sf1_arq_eps_live_accepted.csv"
RW.ALL_LEDGERS = [S / n for n in ("prediction_ledger.csv", "prediction_ledger_v2.csv", "prediction_ledger_v3.csv",
                  "prediction_ledger_ext.csv", "prediction_ledger_hedge.csv", "prediction_ledger_sue.csv",
                  "prediction_ledger_seas.csv", "prediction_ledger_blend_seas.csv")]
SF.OUT_DIR = S; SF.SUE_CSV = S / "prediction_ledger_sue.csv"; SF.SUE_SCORES_CSV = S / "x_sue_scores.csv"
SF.LOG_CSV = S / "ledger_record_log.csv"; SF.ANN_CSV = S / "ledger_record_annotations.csv"
SF.GUARD_CSV = S / "ledger_sue_guard_log.csv"; SF.REF_LOG = S / "sf1_arq_eps_live_accepted.csv"
RW._sue_forward = lambda: SF
SS.OUT_DIR = S; SS.SEAS_CSV = S / "prediction_ledger_seas.csv"; SS.BLEND_CSV = S / "prediction_ledger_blend_seas.csv"
SS.SEAS_SCORES_CSV = S / "x_seas_scores.csv"; SS.BLEND_SCORES_CSV = S / "x_blend_seas_scores.csv"
SS.LOG_CSV = S / "ledger_record_log.csv"; SS.ANN_CSV = S / "ledger_record_annotations.csv"
SS.GUARD_CSV = S / "ledger_seas_guard_log.csv"
SS.START_AFTER = pd.Timestamp("2026-09-08")          # test only
RW._seas_forward = lambda: SS


def _boom(msg):
    def f(*a, **k):
        raise RuntimeError(f"FORCED {msg} (isolation test)")
    return f


if mode == "plan_fail":
    SS.side_ledgers = _boom("side_ledgers failure")
elif mode in ("seas_build", "guard_fail"):
    SS.build_seas_rows = _boom("build_seas_rows failure")
    if mode == "guard_fail":
        SS.log_guard = _boom("log_guard failure")
elif mode == "blend_build":
    SS.csb().blend_scores_at = _boom("blend_scores_at failure")
elif mode == "seas_record":
    SS.record_seas = _boom("record_seas failure")
elif mode == "blend_half":
    _orig = SS.record_blend
    def _half(t, rows):                                   # noqa: E306
        _orig(t, rows)
        raise RuntimeError("FORCED failure AFTER the blend_seas append (isolation test)")
    SS.record_blend = _half
elif mode != "happy":
    raise SystemExit(f"unknown mode {mode}")

before = {p.name: (p.stat().st_size, hashlib.sha256(p.read_bytes()).hexdigest()) for p in S.iterdir()}
sys.argv = [sys.argv[0]]
rc = RW.main()
after = {p.name: p.read_bytes() for p in S.iterdir()}
print(f"=== mode {mode}: record_weekly rc={rc}")
for n, (sz, h) in sorted(before.items()):
    if n.endswith(".json"):
        continue
    b = after[n]
    print(f"  {n}: {sz} -> {len(b)} bytes, prefix hash {'HOLDS' if hashlib.sha256(b[:sz]).hexdigest() == h else 'BROKEN'}")
for n in sorted(set(after) - set(before)):
    print(f"  NEW {n}: {len(after[n])} bytes")
recorded = {}
for n in ("prediction_ledger_v3.csv", "prediction_ledger_ext.csv", "prediction_ledger_hedge.csv",
          "prediction_ledger_sue.csv", "prediction_ledger_seas.csv", "prediction_ledger_blend_seas.csv"):
    p = S / n
    recorded[n] = (sorted(pd.read_csv(p, usecols=["panel_date"])["panel_date"].astype(str).unique())
                   if p.exists() else [])
    print(f"  {n} dates: {recorded[n]}")
if (S / "ledger_seas_guard_log.csv").exists():
    print("--- ledger_seas_guard_log.csv\n" + (S / "ledger_seas_guard_log.csv").read_text())
print("  log tail:\n" + "\n".join((S / "ledger_record_log.csv").read_text().splitlines()[-5:]))
main_after = fingerprint()
changed = sorted(k for k in set(main_before) | set(main_after) if main_before.get(k) != main_after.get(k))
print("MAIN STORE UNCHANGED:", not changed, changed[:10])
core_ok = all("2026-09-18" in recorded[n] for n in ("prediction_ledger_v3.csv", "prediction_ledger_ext.csv",
                                                    "prediction_ledger_hedge.csv"))
print("V3/EXT/HEDGE RECORDED 2026-09-18:", core_ok)
