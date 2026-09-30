"""WO-27-io-fwd isolation test of the io side ledger inside record_weekly.py,
on a SCRATCH copy of the store (never main). Pattern of
final/src/seasonality/wo20_isolation_test.py (itself from WO-15).

usage:
  python wo27_isolation_test.py all <scratch_root> <baseline_record_weekly.py>
      runs every mode below in its own subprocess + scratch dir, compares, and
      writes final/out/overnight/wo27_isolation_test.json
  python wo27_isolation_test.py <mode> <scratch_dir> [<baseline_record_weekly.py>]

modes:
  baseline      integration's PRE-WO-27 record_weekly.py (no io at all)
  happy         no forcing: v3/ext/hedge + seas + blend_seas + io all record
  io_import     record_weekly's io import raises       -> io skipped, rest identical
  io_plan       io_forward.side_ledgers raises          -> io skipped
  io_build      build_io_rows raises                     -> io skipped
  io_missing    a SEP month file the date needs is missing (real code path) -> io skipped
  io_lowcov     io_gap coverage forced to ~50% (real 70% floor)           -> io skipped
  io_record     record_io raises before appending        -> io skipped
  io_half       record_io appends THEN raises            -> reported at the end, rc 1,
                AFTER v3/ext/hedge/seas/blend recorded
  io_guardfail  io_build forced AND the io guard log cannot be written -> still rc 0
  seas_skip     build_seas_rows raises -> seas skipped, so io MUST skip (mandatory seas pairing)
  second_run    run 1 with io_build forced (seas records, io skipped), then run 2 with
                no forcing: io records the date against the seas CSV; nothing else new
Every write path is patched to <scratch_dir>. v3/ext/hedge are truncated
(byte prefix) to drop the 2026-09-18 and 2026-09-24 records so there is a
week to record; START_AFTER of the side ledgers is set to 2026-09-08 (test
only) so they have 2026-09-18 to record. The main store (every file under
out/reset2026, data/sharadar top level, out/ top level, the SEP month dir) is
fingerprinted (size + mtime, + sha1 of the ledgers) before and after."""
import hashlib
import importlib.util
import json
import shutil
import subprocess
import sys
from pathlib import Path

import pandas as pd

WT = Path(__file__).resolve().parents[1]           # this worktree's final/src
for sub in ("reset2026", "sue", "seasonality", "overnight"):
    sys.path.insert(0, str(WT / sub))
MAINF = Path("/Users/ggraham/pipe_dream/final")
MAIN = MAINF / "out" / "reset2026"
SEPD = MAINF / "data" / "sharadar" / "panel" / "stocks"
OTHER = ("prediction_ledger_v3.csv", "prediction_ledger_ext.csv", "prediction_ledger_hedge.csv",
         "prediction_ledger_sue.csv", "prediction_ledger_seas.csv", "prediction_ledger_blend_seas.csv")
IO_NAME = "prediction_ledger_io.csv"
MODES = ["baseline", "happy", "io_import", "io_plan", "io_build", "io_missing", "io_lowcov", "io_record",
         "io_half", "io_guardfail", "seas_skip", "second_run"]


def fingerprint():
    fp = {}
    for d in (MAIN, MAINF / "data" / "sharadar", MAINF / "out", SEPD):
        for p in d.iterdir():
            if p.is_file():
                st = p.stat()
                fp[str(p)] = (st.st_size, st.st_mtime)
    for n in ("prediction_ledger_v3.csv", "prediction_ledger_ext.csv", "prediction_ledger_hedge.csv"):
        fp["sha1:" + n] = hashlib.sha1((MAIN / n).read_bytes()).hexdigest()
    return fp


def content_hash(p):
    """sha256 of the CSV content with recorded_at removed (timestamps differ per run)."""
    if not p.exists():
        return None
    df = pd.read_csv(p, float_precision="round_trip")
    df = df.drop(columns=[c for c in ("recorded_at",) if c in df.columns])
    return hashlib.sha256(df.to_csv(index=False).encode()).hexdigest()


def log_hash(p, ledgers):
    if not p.exists():
        return None
    df = pd.read_csv(p)
    df = df[df["ledger"].isin(ledgers)].drop(columns=[c for c in ("recorded_at", "annotated_at") if c in df.columns])
    return hashlib.sha256(df.to_csv(index=False).encode()).hexdigest()


def run_all(root, base_rw):
    import time
    global START
    START = time.time()
    root = Path(root)
    out = {}
    for m in MODES:
        s = root / m
        r = subprocess.run([sys.executable, __file__, m, str(s), str(base_rw)], capture_output=True, text=True)
        tail = (r.stdout + r.stderr).splitlines()
        rp = s.parent / f"{m}.result.json"
        if rp.exists():
            rp.unlink() if rp.stat().st_mtime < START else None
        res = json.loads(rp.read_text()) if rp.exists() else {"crashed": True, "rc": None, "dates": {n: None for n in OTHER + (IO_NAME,)},
                                                             "content": {}, "log_other": None, "main_store_unchanged": False}
        res["subprocess_rc"] = r.returncode
        res["log_tail"] = tail[-12:]
        out[m] = res
        print(f"=== {m}: rc={res.get('rc')} io_dates={res.get('dates', {}).get(IO_NAME)} "
              f"main_unchanged={res.get('main_store_unchanged')}", flush=True)
    base = out["baseline"]
    expect_rc = {m: (1 if m == "io_half" else 0) for m in MODES}
    expect_io = {"baseline": [], "happy": ["2026-09-18"], "io_half": ["2026-09-18"], "second_run": ["2026-09-18"]}
    verdict = {}
    for m, r in out.items():
        others = [n for n in OTHER if not (m == "seas_skip" and n == "prediction_ledger_seas.csv")]
        same = {n: r["content"].get(n, "missing") == base["content"][n] for n in others}
        logs_same = r["log_other"] == base["log_other"] if m != "seas_skip" else True
        io_ok = r["dates"][IO_NAME] == expect_io.get(m, [])
        core = all("2026-09-18" in (r["dates"][n] or []) for n in OTHER[:3])
        extra = True
        if m == "seas_skip":
            extra = r["dates"]["prediction_ledger_seas.csv"] == [] and r["dates"][IO_NAME] == []
        if m == "second_run":
            extra = r.get("run2_new_other_records") == 0 and r.get("run1_io_dates") == []
        if m in ("io_import", "io_plan", "io_build", "io_missing", "io_lowcov", "io_record", "seas_skip", "second_run"):
            extra = extra and r.get("io_guard_logged", False)
        ok = (all(same.values()) and logs_same and io_ok and core and extra and r["rc"] == expect_rc[m]
              and r["main_store_unchanged"])
        verdict[m] = {"pass": bool(ok), "others_identical_to_baseline": same, "sidecar_rows_identical": logs_same,
                      "io_dates": r["dates"][IO_NAME], "core_recorded": core, "rc": r["rc"], "extra": extra,
                      "main_store_unchanged": r["main_store_unchanged"]}
        print(f"  {m}: {'PASS' if ok else 'FAIL'} {verdict[m]}", flush=True)
    res = {"modes": out, "verdict": verdict, "all_pass": all(v["pass"] for v in verdict.values())}
    dst = WT.parent / "out" / "overnight" / "wo27_isolation_test.json"
    dst.write_text(json.dumps(res, indent=1, default=str))
    print(f"ALL PASS: {res['all_pass']} -> {dst}")
    return 0 if res["all_pass"] else 1


def setup(S):
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


def patch(S, base_rw=None):
    import working_panel as W, prediction_ledger as PL, forward_hedge as FH   # noqa: E401
    import sue_forward as SF, seas_forward as SS                              # noqa: E401
    import io_forward as IOF, io_gap_live as IL                               # noqa: E401
    if base_rw:
        spec = importlib.util.spec_from_file_location("record_weekly_base", base_rw)
        RW = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(RW)
    else:
        import record_weekly as RW
    W.MANIFEST = S / "ledger_panel_manifest.json"
    PL.OUT_DIR = S; PL.LEDGER_CSV = S / "prediction_ledger_v3.csv"; PL.EXT_CSV = S / "prediction_ledger_ext.csv"
    PL.SCORES_CSV = S / "x_scores.csv"; PL.EXT_SCORES_CSV = S / "x_ext_scores.csv"
    FH.R26 = S; FH.HEDGE_CSV = S / "prediction_ledger_hedge.csv"; FH.HEDGE_SCORES_CSV = S / "x_hedge_scores.csv"
    for k, n in dict(LOG_CSV="ledger_record_log.csv", V3="prediction_ledger_v3.csv", EXT="prediction_ledger_ext.csv",
                     HEDGE="prediction_ledger_hedge.csv", SUE="prediction_ledger_sue.csv",
                     ANN_CSV="ledger_record_annotations.csv", SUE_GUARD_CSV="ledger_sue_guard_log.csv",
                     SEAS="prediction_ledger_seas.csv", BLEND_SEAS="prediction_ledger_blend_seas.csv",
                     SEAS_GUARD_CSV="ledger_seas_guard_log.csv", IO=IO_NAME,
                     IO_GUARD_CSV="ledger_io_guard_log.csv").items():
        if hasattr(RW, k):
            setattr(RW, k, S / n)
    RW.SUE_REF_LOG = S / "sf1_arq_eps_live_accepted.csv"
    RW.ALL_LEDGERS = [S / n for n in ("prediction_ledger.csv", "prediction_ledger_v2.csv") + OTHER + (IO_NAME,)]
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
    IOF.OUT_DIR = S; IOF.IO_CSV = S / IO_NAME; IOF.IO_SCORES_CSV = S / "x_io_scores.csv"
    IOF.LOG_CSV = S / "ledger_record_log.csv"; IOF.ANN_CSV = S / "ledger_record_annotations.csv"
    IOF.GUARD_CSV = S / "ledger_io_guard_log.csv"
    IOF.START_AFTER = pd.Timestamp("2026-09-08")         # test only
    if hasattr(RW, "_io_forward"):
        RW._io_forward = lambda: IOF
    return RW, SS, IOF, IL


def _boom(msg):
    def f(*a, **k):
        raise RuntimeError(f"FORCED {msg} (isolation test)")
    return f


def force(mode, S, RW, SS, IOF, IL):
    if mode == "io_import":
        def _imp():
            raise ImportError("FORCED io_forward import failure (isolation test)")
        RW._io_forward = _imp
    elif mode == "io_plan":
        IOF.side_ledgers = _boom("io side_ledgers failure")
    elif mode in ("io_build", "io_guardfail"):     # guardfail: the guard log path is a DIRECTORY
        IOF.build_io_rows = _boom("build_io_rows failure")
        if mode == "io_guardfail":
            (S / "ledger_io_guard_log.csv").mkdir()          # a directory: every append raises
    elif mode == "io_missing":
        sep = S / "sep_missing_one"
        sep.mkdir()
        for p in SEPD.glob("*.parquet"):
            if p.stem != "2026-03":                          # a month inside every live window
                (sep / p.name).symlink_to(p)
        _orig = IL.io_gap_asof
        IL.io_gap_asof = lambda tickers, t, *a, **k: _orig(tickers, t, sep_dir=sep, **k)
    elif mode == "io_lowcov":
        import numpy as np
        _orig = IL.io_gap_asof
        def _low(tickers, t, *a, **k):                       # noqa: E306
            out, info = _orig(tickers, t, *a, **k)
            out = out.copy()
            out.loc[np.arange(len(out)) % 2 == 0, "io_gap"] = np.nan
            return out, info
        IL.io_gap_asof = _low
    elif mode == "io_record":
        IOF.record_io = _boom("record_io failure")
    elif mode == "io_half":
        _orig = IOF.record_io
        def _half(t, rows):                                  # noqa: E306
            _orig(t, rows)
            raise RuntimeError("FORCED failure AFTER the io append (isolation test)")
        IOF.record_io = _half
    elif mode == "seas_skip":
        SS.build_seas_rows = _boom("build_seas_rows failure")
    elif mode not in ("happy", "baseline", "second_run"):
        raise SystemExit(f"unknown mode {mode}")


def dates(S):
    out = {}
    for n in OTHER + (IO_NAME,):
        p = S / n
        out[n] = sorted(pd.read_csv(p, usecols=["panel_date"])["panel_date"].astype(str).unique()) if p.exists() else []
    return out


def one(mode, S, base_rw):
    main_before = fingerprint()
    setup(S)
    res = {"mode": mode}
    RW, SS, IOF, IL = patch(S, base_rw if mode == "baseline" else None)
    if mode == "second_run":
        orig_build = IOF.build_io_rows
        IOF.build_io_rows = _boom("build_io_rows failure (run 1)")
        sys.argv = [sys.argv[0]]
        rc1 = RW.main()
        d1 = dates(S)
        res.update({"run1_rc": rc1, "run1_io_dates": d1[IO_NAME]})
        IOF.build_io_rows = orig_build
        rc = RW.main()
        d2 = dates(S)
        res["run2_new_other_records"] = sum(len(set(d2[n]) - set(d1[n])) for n in OTHER)
    else:
        force(mode, S, RW, SS, IOF, IL)
        sys.argv = [sys.argv[0]]
        rc = RW.main()
    res["rc"] = rc
    res["dates"] = dates(S)
    res["content"] = {n: content_hash(S / n) for n in OTHER}
    res["log_other"] = log_hash(S / "ledger_record_log.csv", list(OTHER))
    g = S / "ledger_io_guard_log.csv"
    res["io_guard_logged"] = bool(g.is_file() and "io_skipped" in g.read_text())
    res["io_guard_rows"] = g.read_text().splitlines()[1:] if g.is_file() else []
    if (S / IO_NAME).exists():
        io = pd.read_csv(S / IO_NAME, float_precision="round_trip")
        sea = pd.read_csv(S / "prediction_ledger_seas.csv", float_precision="round_trip")
        m = io.merge(sea[["panel_date", "ticker", "icw9_seas_score"]], on=["panel_date", "ticker"], suffixes=("", "_s"))
        res["io_rows"] = int(len(io))
        res["io_vs_seas_icw9_max_abs"] = float((m["icw9_seas_score"] - m["icw9_seas_score_s"]).abs().max())
        res["io_coverage"] = float(io["io_gap"].notna().mean())
    main_after = fingerprint()
    changed = sorted(k for k in set(main_before) | set(main_after) if main_before.get(k) != main_after.get(k))
    res["main_store_unchanged"] = not changed
    res["main_store_changed"] = changed[:10]
    (S.parent / f"{mode}.result.json").write_text(json.dumps(res, indent=1, default=str))
    print(json.dumps({k: v for k, v in res.items() if k not in ("content",)}, default=str, indent=1))


if __name__ == "__main__":
    mode, S = sys.argv[1], Path(sys.argv[2])
    assert "pipe_dream/final" not in str(S.resolve()), "scratch dir must be outside the main checkout"
    if mode == "all":
        sys.exit(run_all(S, sys.argv[3]))
    one(mode, S, sys.argv[3] if len(sys.argv) > 3 else None)
