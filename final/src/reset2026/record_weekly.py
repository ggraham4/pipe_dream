"""
WO-14: WEEKLY forward-ledger records (Gabe ruling 2026-09-25, recorded in
COO.md: "Forward-ledger record cadence = WEEKLY for all forward ledgers").

    python final/src/reset2026/record_weekly.py            # record every missing week
    python final/src/reset2026/record_weekly.py --plan     # print the plan, write nothing

Normally run by `refresh_working_panel.py --through latest --record-weekly`,
which does: insider refresh -> panel refresh -> this. Exit 0 = done or
nothing to do; 1 = failed (message on stderr).

RULES (frozen; COO implementation of Gabe's ruling)
 1. Weekly record date = the latest working-panel date in each ISO week.
    Every COMPLETE ISO week after 2026-09-08 with no record yet in a ledger
    gets one (a week counts as complete once the panel has a date in a later
    week; fix of 2026-09-25, after the first run recorded W39 at 09-24). One record per ISO week per ledger; a week that already holds any
    record (e.g. week 37 holds 2026-09-08) is skipped.
 2. Ledgers: v3 + ext (prediction_ledger.record(date), which appends both)
    and hedge (forward_hedge.record_hedge(date)). The existing duplicate-date
    and blindness guards apply unchanged.
 3. recorded_late = recorded_at is more than 7 calendar days after
    panel_date. Late records are DESCRIPTIVE ONLY, never counted dates.
 4. WO-10's counted-date rule is unchanged (greedy from 2026-09-08, >= 40
    trading days apart); only on-time records are eligible
    (forward_hedge.status reads the late flags from the sidecar below).
 5. Schema: no existing CSV is rewritten. The flag lives in a sidecar,
    out/reset2026/ledger_record_log.csv (ledger, panel_date, iso_week,
    recorded_at, recorded_late, rows).
 6. Checks after each run: every ledger's pre-existing bytes are unchanged
    (sha256 of the prefix), one record per ISO week per ledger.
 7. WO-15 (2026-09-26, doc final/models/2026-09-26-sue-forward-ledger.md):
    prediction_ledger_sue.csv, written right after v3 on v3's rows. Its dates
    are v3's dates after 2026-09-08 with no SUE record (so it follows v3,
    incl. v3's incomplete_week 2026-09-24, which gets an incomplete_week
    annotation for the sue ledger too). Preflight covers every SUE date:
    SF1-live freshness (runs final/src/sue/sf1_eps_live_pull.py once when the
    live file does not postdate the latest SUE date), basis validation,
    blindness, v3 pairing (tickers + icw8 to 1e-12), backfill gate. The
    annotations sidecar joins the prefix-hash set; the panel manifest is
    checked entry by entry (record_manifest rewrites the JSON).
    Addendum A (COO 2026-09-26, before any record): basis check vs the
    previous ACCEPTED live pull (uniform-ratio exemption; non-uniform names
    get sue NaN; > 1% non-uniform of a date's v3 tickers skips that date).
    ISOLATION: any SUE failure skips only the SUE record (logged to
    ledger_sue_guard_log.csv) and never stops v3/ext/hedge.
 8. WO-20 (2026-09-27, doc final/models/2026-09-27-wo20-seas-live.md): two
    side ledgers from final/src/seasonality/seas_forward.py, written after SUE:
      prediction_ledger_seas.csv        Theoretical model icw9_seas vs icw8,
                                        on v3's rows (paired with v3)
      prediction_ledger_blend_seas.csv  Today's Picks blend with seas (10 ew
                                        factors) vs the previous 9-factor blend
    Their dates are v3's dates after 2026-09-24 with no record in that ledger.
    Same isolation as WO-15 Addendum A, PER LEDGER: any failure (plan,
    preflight, record, sidecar) skips only that ledger's record, is logged to
    ledger_seas_guard_log.csv, and never stops v3/ext/hedge/sue or the other
    side ledger. A record half-written by a raising record step is reported
    at the end, after hedge has recorded.
 9. WO-27-io-fwd (2026-09-29, doc final/models/2026-09-29-wo27-io-forward-ledger.md):
    side ledger prediction_ledger_io.csv from final/src/overnight/io_forward.py
    (icw10_io = icw9_seas + io_gap, frozen weights, vs icw9_seas on v3's rows),
    written after the seas ledger; its record step requires the seas record
    for the same date (icw9_seas identical). Its dates are v3's dates after
    2026-09-24 with no io record. Imported in its OWN try (separate from
    seas); any io failure skips only the io record, is logged to
    ledger_io_guard_log.csv (written here, without importing io_forward), and
    never stops v3/ext/hedge/sue/seas/blend_seas.
10. WO-34 (2026-09-30, doc final/models/2026-09-30-r252-forward.md): side
    ledger prediction_ledger_r252.csv from final/src/rollweights/r252_forward.py
    (icw9_r252 = icw9_seas factors with WO-33's R252 rolling weights, refit
    every 21 trading days, append-only path r252_weight_path.csv; vs icw9_seas
    on v3's rows), written after io; its record step requires the seas record
    for the same date. Dates = v3's dates after 2026-09-24 with no r252
    record. Imported in its OWN try; any r252 failure skips only the r252
    record, is logged to ledger_r252_guard_log.csv (written here, without
    importing r252_forward), and never stops v3/ext/hedge/sue/seas/blend_seas/io.
"""
import argparse
import hashlib
import json
import sys
import time
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE.parent))
sys.path.insert(0, str(HERE))

import pandas as pd  # noqa: E402
import pyarrow.parquet as pq  # noqa: E402

import working_panel as W  # noqa: E402

START_AFTER = pd.Timestamp("2026-09-08")
R26 = W.R26
LOG_CSV = R26 / "ledger_record_log.csv"
V3 = R26 / "prediction_ledger_v3.csv"
EXT = R26 / "prediction_ledger_ext.csv"
HEDGE = R26 / "prediction_ledger_hedge.csv"
# WO-15 (2026-09-26): icw9-with-SUE side ledger, paired with v3 (doc
# final/models/2026-09-26-sue-forward-ledger.md). Its dates are v3's dates
# after 2026-09-08 with no SUE record yet (final/src/sue/sue_forward.py).
SUE = R26 / "prediction_ledger_sue.csv"
ANN_CSV = R26 / "ledger_record_annotations.csv"
SUE_GUARD_CSV = R26 / "ledger_sue_guard_log.csv"                      # WO-15 Addendum A
SUE_REF_LOG = W.SH / "sf1_arq_eps_live_accepted.csv"                 # WO-15 Addendum A (d)
# WO-20 (2026-09-27): side ledgers (final/src/seasonality/seas_forward.py)
SEAS = R26 / "prediction_ledger_seas.csv"
BLEND_SEAS = R26 / "prediction_ledger_blend_seas.csv"
SEAS_GUARD_CSV = R26 / "ledger_seas_guard_log.csv"
# WO-27-io-fwd (2026-09-29): io side ledger (final/src/overnight/io_forward.py)
IO = R26 / "prediction_ledger_io.csv"
IO_GUARD_CSV = R26 / "ledger_io_guard_log.csv"
# WO-34 (2026-09-30): r252 side ledger (final/src/rollweights/r252_forward.py)
R252 = R26 / "prediction_ledger_r252.csv"
R252_PATH = R26 / "r252_weight_path.csv"
R252_GUARD_CSV = R26 / "ledger_r252_guard_log.csv"
ALL_LEDGERS = [R26 / n for n in ("prediction_ledger.csv", "prediction_ledger_v2.csv",
                                 "prediction_ledger_v3.csv", "prediction_ledger_ext.csv",
                                 "prediction_ledger_hedge.csv", "prediction_ledger_sue.csv",
                                 "prediction_ledger_seas.csv", "prediction_ledger_blend_seas.csv",
                                 "prediction_ledger_io.csv", "prediction_ledger_r252.csv")]
LATE_DAYS = 7
SUE_INCOMPLETE_NOTE = ("incomplete_week: paired with the v3 record for this date, which is annotated "
                       "incomplete_week; descriptive only, never a counted date; WO-15 2026-09-26")
SEAS_INCOMPLETE_NOTE = ("incomplete_week: paired with the v3 record for this date, which is annotated "
                        "incomplete_week; descriptive only, never a counted date; WO-20 2026-09-27")


def log(m):
    print(f"[{time.strftime('%H:%M:%S')}] {m}", flush=True)


def iso_week(d):
    c = pd.Timestamp(d).isocalendar()
    return f"{c[0]}-W{c[1]:02d}"


def panel_dates():
    t = pq.read_table(W.WORKING_PANEL, columns=["date"],
                      filters=[("date", ">", START_AFTER.date().isoformat())])
    return sorted(pd.Timestamp(x) for x in t.column("date").unique().to_pylist())


def weekly_targets():
    """{iso_week: latest panel date in it}, COMPLETE weeks only: the ISO week
    holding the panel's max date is excluded until a later week's date
    exists, so a mid-week refresh never locks in a non-final date (the
    one-per-week guard would otherwise block the week's real last date)."""
    by_week = {}
    ds = panel_dates()
    for d in ds:
        by_week[iso_week(d)] = max(d, by_week.get(iso_week(d), d))
    if ds:
        by_week.pop(iso_week(max(ds)), None)
    return by_week


def recorded_weeks(csv):
    if not csv.exists():
        return {}
    ds = pd.read_csv(csv, usecols=["panel_date"])["panel_date"].astype(str).unique()
    out = {}
    for d in ds:
        out.setdefault(iso_week(d), set()).add(d)
    return out


def prefix_hashes():
    h = {}
    for p in ALL_LEDGERS + [LOG_CSV, ANN_CSV, SUE_GUARD_CSV, SUE_REF_LOG, SEAS_GUARD_CSV, IO_GUARD_CSV,
                                R252_GUARD_CSV, R252_PATH]:
        if p.is_file():     # is_file, not exists: a non-file path (WO-27 harness) must not crash the run
            b = p.read_bytes()
            h[p] = (len(b), hashlib.sha256(b).hexdigest())   # keyed by full path (sidecars live in 2 dirs)
    return h


def check_prefixes(before):
    for path, (n, sha) in before.items():
        b = Path(path).read_bytes()
        if len(b) < n or hashlib.sha256(b[:n]).hexdigest() != sha:
            raise SystemExit(f"PREFIX CHANGED: {Path(path).name} -- existing rows were modified")


def plan():
    targets = weekly_targets()
    p = {}
    for led in (V3, EXT, HEDGE):
        have = recorded_weeks(led)
        p[led.name] = [(w, d) for w, d in sorted(targets.items()) if w not in have]
    # WO-15: SUE dates = v3 dates after 2026-09-08 (existing + this run's) without a SUE record
    try:        # isolation: a SUE failure here never blocks v3/ext/hedge
        SF = _sue_forward()
        p[SUE.name] = [(iso_week(d), d) for d in SF.todo_dates([d for _w, d in p[V3.name]])]
    except (Exception, SystemExit) as e:   # noqa: BLE001
        log(f"SUE plan FAILED (SUE skipped this run; v3/ext/hedge unaffected): {type(e).__name__}: {e}")
        p[SUE.name] = []
    # WO-20: side-ledger dates = v3 dates after 2026-09-24 (existing + this run's) without a record
    for key in _side_keys().values():
        p[key] = []
    sides = []
    try:        # isolation: a side-ledger failure here never blocks v3/ext/hedge/sue
        sides += _seas_forward().side_ledgers()
    except (Exception, SystemExit) as e:   # noqa: BLE001
        log(f"SEAS plan FAILED (seas side ledgers skipped this run; v3/ext/hedge/sue unaffected): {type(e).__name__}: {e}")
    global _IO_PLAN_ERROR
    _IO_PLAN_ERROR = None
    try:        # WO-27: io in its OWN try -- an io failure never blocks seas either
        sides += _io_forward().side_ledgers()
    except (Exception, SystemExit) as e:   # noqa: BLE001
        _IO_PLAN_ERROR = f"plan: {type(e).__name__}: {e}"
        log(f"IO plan FAILED (io side ledger skipped this run; others unaffected): {type(e).__name__}: {e}")
    global _R252_PLAN_ERROR
    _R252_PLAN_ERROR = None
    try:        # WO-34: r252 in its OWN try -- an r252 failure never blocks seas/io
        sides += _r252_forward().side_ledgers()
    except (Exception, SystemExit) as e:   # noqa: BLE001
        _R252_PLAN_ERROR = f"plan: {type(e).__name__}: {e}"
        log(f"R252 plan FAILED (r252 side ledger skipped this run; others unaffected): {type(e).__name__}: {e}")
    for L in sides:
        try:
            p[_side_keys()[L.name]] = [(iso_week(d), d) for d in L.todo([d for _w, d in p[V3.name]])]
        except (Exception, SystemExit) as e:   # noqa: BLE001
            log(f"{L.name} plan FAILED (skipped this run; others unaffected): {type(e).__name__}: {e}")
    return targets, p


def _sue_forward():
    sys.path.insert(0, str(HERE.parent / "sue"))
    import sue_forward as SF
    return SF


def _seas_forward():
    sys.path.insert(0, str(HERE.parent / "seasonality"))
    import seas_forward as SS
    return SS


def _io_forward():
    sys.path.insert(0, str(HERE.parent / "overnight"))
    import io_forward as IOF
    return IOF


def _r252_forward():
    sys.path.insert(0, str(HERE.parent / "rollweights"))
    import r252_forward as RF
    return RF


def _side_keys():
    """side-ledger name -> todo key (the ledger file name)."""
    return {"seas": SEAS.name, "blend_seas": BLEND_SEAS.name, "io": IO.name, "r252": R252.name}


SEAS_SIDES = ("seas", "blend_seas")
_IO_PLAN_ERROR = None       # set by plan() when io import/plan fails; logged by run() (not by --plan)
_R252_PLAN_ERROR = None     # WO-34: same, for r252


def _io_guard(iso, event, detail):
    """WO-27: io skips go to ledger_io_guard_log.csv, written HERE (no io_forward
    import needed, so an io import failure is still logged). Never raises."""
    try:
        if IO_GUARD_CSV.exists() and not IO_GUARD_CSV.read_bytes().endswith(b"\n"):
            raise SystemExit(f"{IO_GUARD_CSV.name} does not end in a newline; refusing to append")
        row = pd.DataFrame([[pd.Timestamp.now().isoformat(), "io", iso, iso_week(iso) if iso else "",
                             event, str(detail)[:500]]],
                           columns=["logged_at", "ledger", "panel_date", "iso_week", "event", "detail"])
        row.to_csv(IO_GUARD_CSV, mode="a", header=not IO_GUARD_CSV.exists(), index=False)
    except (Exception, SystemExit) as e:   # noqa: BLE001
        log(f"could not write io guard log for {iso}: {type(e).__name__}: {e}")


def _r252_guard(iso, event, detail):
    """WO-34: r252 skips go to ledger_r252_guard_log.csv, written HERE (no
    r252_forward import needed). Never raises."""
    try:
        if R252_GUARD_CSV.exists() and not R252_GUARD_CSV.read_bytes().endswith(b"\n"):
            raise SystemExit(f"{R252_GUARD_CSV.name} does not end in a newline; refusing to append")
        row = pd.DataFrame([[pd.Timestamp.now().isoformat(), "r252", iso, iso_week(iso) if iso else "",
                             event, str(detail)[:500]]],
                           columns=["logged_at", "ledger", "panel_date", "iso_week", "event", "detail"])
        row.to_csv(R252_GUARD_CSV, mode="a", header=not R252_GUARD_CSV.exists(), index=False)
    except (Exception, SystemExit) as e:   # noqa: BLE001
        log(f"could not write r252 guard log for {iso}: {type(e).__name__}: {e}")


def _seas_guard(SS, iso, event, detail, ledger):
    try:
        SS.log_guard(iso, event, detail, ledger=ledger)
    except (Exception, SystemExit) as e:   # noqa: BLE001
        log(f"could not write seas guard log for {ledger} {iso}: {type(e).__name__}: {e}")


def manifest_snapshot():
    return json.loads(W.MANIFEST.read_text()) if W.MANIFEST.exists() else {"ledgers": {}}


def check_manifest(before):
    """record_manifest rewrites the whole JSON, so no byte-prefix check is
    possible: every pre-existing (ledger, panel_date) entry must be unchanged."""
    after = manifest_snapshot()
    for k, v in before.items():
        if k != "ledgers" and after.get(k) != v:
            raise SystemExit(f"MANIFEST CHANGED: top-level key {k}")
    for led, entries in before.get("ledgers", {}).items():
        for d, v in entries.items():
            if after["ledgers"].get(led, {}).get(d) != v:
                raise SystemExit(f"MANIFEST CHANGED: {led} {d}")


def v3_incomplete(d):
    if not ANN_CSV.exists():
        return False
    an = pd.read_csv(ANN_CSV)
    return bool(((an["ledger"] == V3.name) & (an["panel_date"].astype(str) == d)
                 & an["annotation"].astype(str).str.startswith("incomplete_week")).any())


def append_annotation(ledger, d, note, source):
    if ANN_CSV.exists() and not ANN_CSV.read_bytes().endswith(b"\n"):
        raise SystemExit(f"{ANN_CSV.name} does not end in a newline; refusing to append")
    row = pd.DataFrame([[ledger, d, iso_week(d), note, pd.Timestamp.now().date().isoformat(), source]],
                       columns=["ledger", "panel_date", "iso_week", "annotation", "annotated_at", "source"])
    row.to_csv(ANN_CSV, mode="a", header=not ANN_CSV.exists(), index=False)


def append_log(rows):
    df = pd.DataFrame(rows, columns=["ledger", "panel_date", "iso_week", "recorded_at", "recorded_late", "rows"])
    df.to_csv(LOG_CSV, mode="a", header=not LOG_CSV.exists(), index=False)


def _rows_for(csv, d):
    if not csv.exists():
        return 0
    return int((pd.read_csv(csv, usecols=["panel_date"])["panel_date"].astype(str) == d).sum())


def _recorded_at(csv, d):
    s = pd.read_csv(csv, usecols=["panel_date", "recorded_at"])
    s = s[s["panel_date"].astype(str) == d]
    return str(s["recorded_at"].iloc[0])


def _late(panel_date, recorded_at):
    return (pd.Timestamp(recorded_at).normalize() - pd.Timestamp(panel_date).normalize()).days > LATE_DAYS


def run(dry=False):
    targets, todo = plan()
    log(f"weeks after {START_AFTER.date()} in the working panel: "
        + ", ".join(f"{w}->{d.date()}" for w, d in sorted(targets.items())))
    for led, items in todo.items():
        log(f"{led}: missing weeks {[(w, d.date().isoformat()) for w, d in items]}")
    if dry:
        return 0
    io_plan_error = _IO_PLAN_ERROR
    r252_plan_error = _R252_PLAN_ERROR
    before = prefix_hashes()
    import prediction_ledger as PL
    import forward_hedge as FH
    import opportunistic as OPP

    v3_ext_dates = sorted({d for _w, d in todo[V3.name]} | {d for _w, d in todo[EXT.name]})
    # PREFLIGHT (writes nothing): every target date must pass the blindness
    # and book guards, and the insider data must be fresh for the ext columns.
    for d in sorted(set(v3_ext_dates) | {d for _w, d in todo[HEDGE.name]}):
        cross, _u = W.working_cross_section(["eligible_cap150", PL.LABEL], date=d)
        n = int(cross.loc[cross["eligible_cap150"], PL.LABEL].notna().sum())
        if n:
            raise SystemExit(f"preflight: {d.date()} not blind ({n} matured labels)")
    for _w, d in todo[HEDGE.name]:
        FH.build_record_rows(d.date().isoformat())       # raises on any guard failure
    if v3_ext_dates:
        maxf = OPP.max_filing_date(OPP.load_events())
        worst = max(v3_ext_dates)
        if (worst - maxf).days > PL.INSIDER_MAX_STALE_DAYS:
            raise SystemExit(f"preflight: insider data ends {maxf.date()}, stale for {worst.date()} "
                             f"(> {PL.INSIDER_MAX_STALE_DAYS}d). Run final/scripts/edgar_form4_refresh.py first.")
    # WO-15 SUE preflight (Addendum A, 2026-09-26): SF1-live freshness (pulls
    # once if needed), basis check vs the previous accepted pull, blindness,
    # pairing, backfill gate, 1% non-uniform cap, and the full rows, for every
    # SUE date BEFORE anything is written. ISOLATION: any SUE failure skips only
    # the SUE record (whole run or one date) and is logged to
    # ledger_sue_guard_log.csv; it never stops v3/ext/hedge.
    sue_dates = [d for _w, d in todo[SUE.name]]
    sue_rows, sue_nan, sue_skipped = {}, {}, {}
    sue_deferred = []                      # a half-written SUE record: raised AFTER hedge
    SF = _sue_forward() if sue_dates else None     # plan() already imported it successfully
    live = pulled_at = None
    if sue_dates:
        try:
            cal = SF.panel_calendar()
            live, pulled_at = SF.ensure_live(sue_dates, cal)
            basis = SF.basis_validation(live, pulled_at)
            log(f"SUE basis check vs {basis['reference']}: {basis['overlap_keys']:,} overlapping keys, "
                f"{basis['mismatch_rows']} eps mismatches; uniform {basis['uniform_tickers']}; "
                f"non-uniform {basis['nonuniform_tickers']}")
        except Exception as e:          # noqa: BLE001 (SystemExit is not an Exception; caught below)
            sue_skipped = {d.date().isoformat(): f"preflight: {type(e).__name__}: {e}" for d in sue_dates}
        except SystemExit as e:
            sue_skipped = {d.date().isoformat(): f"preflight: {e}" for d in sue_dates}
        if not sue_skipped:
            v3_have = set(pd.read_csv(V3, usecols=["panel_date"])["panel_date"].astype(str)) if V3.exists() else set()
            for d in sue_dates:
                iso = d.date().isoformat()
                try:
                    rows0, _i0 = SF.build_sue_rows(d, live, pulled_at, cal)
                    hit, share, stop = SF.date_nonuniform(basis, rows0["ticker"])
                    if stop:
                        raise SystemExit(f"non-uniform share {share:.2%} of {len(rows0)} tickers > "
                                         f"{SF.NONUNIFORM_CAP:.0%} cap: {hit[:30]}")
                    rows, info = SF.build_sue_rows(d, live, pulled_at, cal, nan_tickers=hit)
                    if iso in v3_have:
                        SF.check_pairing(rows, d)
                    if iso in SF.BACKFILL_DATES:
                        info["backfill_gate"] = SF.backfill_gate(rows, info, d, basis_ok=True, v3_exists=iso in v3_have)
                    sue_rows[iso], sue_nan[iso] = rows, hit
                    log(f"SUE preflight {iso}: {info}")
                except (Exception, SystemExit) as e:   # noqa: BLE001
                    sue_skipped[iso] = f"date: {type(e).__name__}: {e}"
        for iso, why in sue_skipped.items():
            log(f"SUE SKIPPED for {iso} (v3/ext/hedge unaffected): {why}")
    # WO-20 side-ledger preflight (isolated exactly like SUE, per ledger): rows +
    # coverage guard + pairing where v3 already exists, BEFORE anything is written.
    SS, sides = None, []
    side_rows, side_skipped, side_deferred = {}, {}, []
    v3_have_s = set(pd.read_csv(V3, usecols=["panel_date"])["panel_date"].astype(str)) if V3.exists() else set()
    if any(todo[_side_keys()[k]] for k in SEAS_SIDES):
        try:
            SS = _seas_forward()
            sides = list(SS.side_ledgers())
        except (Exception, SystemExit) as e:   # noqa: BLE001
            for key in SEAS_SIDES:
                side_skipped[key] = {d.date().isoformat(): f"preflight: {type(e).__name__}: {e}"
                                     for _w, d in todo[_side_keys()[key]]}
            sides = []
    if todo[IO.name]:           # WO-27: own try, after seas (its record step needs the seas record)
        try:
            sides += list(_io_forward().side_ledgers())
        except (Exception, SystemExit) as e:   # noqa: BLE001
            side_skipped["io"] = {d.date().isoformat(): f"preflight: {type(e).__name__}: {e}"
                                  for _w, d in todo[IO.name]}
    if todo[R252.name]:         # WO-34: own try, after io (its record step needs the seas record)
        try:
            sides += list(_r252_forward().side_ledgers())
        except (Exception, SystemExit) as e:   # noqa: BLE001
            side_skipped["r252"] = {d.date().isoformat(): f"preflight: {type(e).__name__}: {e}"
                                    for _w, d in todo[R252.name]}
    for L in sides:
        side_rows[L.name], side_skipped[L.name] = {}, {}
        for _w, d in todo[_side_keys()[L.name]]:
            iso = d.date().isoformat()
            try:
                rows, info = L.build(d)
                if L.pair is not None and iso in v3_have_s:
                    L.pair(rows, d)
                side_rows[L.name][iso] = rows
                log(f"{L.name} preflight {iso}: {info}")
            except (Exception, SystemExit) as e:   # noqa: BLE001
                side_skipped[L.name][iso] = f"date: {type(e).__name__}: {e}"
    for name, sk in side_skipped.items():
        for iso, why in sk.items():
            log(f"{name} SKIPPED for {iso} (v3/ext/hedge/sue unaffected): {why}")
    log("preflight passed (blind, guards, insider freshness; SUE and side ledgers isolated)")
    man_before = manifest_snapshot()

    logrows = []
    # v3 + ext: one call records both; v3's and ext's own guards stop duplicates
    for d in v3_ext_dates:
        iso = d.date().isoformat()
        n3, ne = _rows_for(V3, iso), _rows_for(EXT, iso)
        PL.record(date=iso)
        for csv, n0 in ((V3, n3), (EXT, ne)):
            n1 = _rows_for(csv, iso)
            if n0 == 0 and n1 > 0:
                ra = _recorded_at(csv, iso)
                logrows.append([csv.name, iso, iso_week(d), ra, _late(iso, ra), n1])
    # SUE, right after v3 (record_sue re-checks blindness, duplicates, pairing).
    # Isolated: a failure here is logged and skipped; hedge still records.
    for d in sue_dates:
        iso = d.date().isoformat()
        if iso not in sue_rows:
            continue
        size0 = SUE.stat().st_size if SUE.exists() else 0
        try:
            out = SF.record_sue(d, sue_rows[iso])
        except (Exception, SystemExit) as e:   # noqa: BLE001
            sue_skipped[iso] = f"record: {type(e).__name__}: {e}"
            log(f"SUE SKIPPED for {iso} at record (v3/ext/hedge unaffected): {e}")
            if (SUE.stat().st_size if SUE.exists() else 0) != size0:
                sue_deferred.append(f"{SUE.name} {iso}: record_sue raised AFTER appending ({e}); "
                                    f"half-written record, fix by hand")
            continue
        try:
            ra = str(out["recorded_at"].iloc[0])
            logrows.append([SUE.name, iso, iso_week(d), ra, _late(iso, ra), int(len(out))])
            if v3_incomplete(iso):
                append_annotation(SUE.name, iso, SUE_INCOMPLETE_NOTE, "WO-15")
            for tk in sue_nan[iso]:
                SF.log_guard(iso, "nonuniform_sue_nan", tk, "Addendum A (b): eps vs reference not one constant ratio")
            SF.accept_pull(pulled_at, iso)
        except (Exception, SystemExit) as e:   # noqa: BLE001
            sue_deferred.append(f"{SUE.name} {iso}: sidecar step after the record failed: {type(e).__name__}: {e}")
            log(f"SUE sidecar step FAILED for {iso} (hedge still records; run will report it): {e}")
    for iso, why in sorted(sue_skipped.items()):
        try:
            SF.log_guard(iso, "sue_skipped", "", why)
        except (Exception, SystemExit) as e:   # noqa: BLE001
            log(f"could not write SUE guard log for {iso}: {type(e).__name__}: {e}")
    # WO-20 side ledgers, right after SUE (each record step re-checks blindness,
    # duplicates and, for seas, v3 pairing). Isolated per ledger: a failure is
    # logged and skipped; the other side ledger and hedge still record.
    for L in sides:
        for iso, rows in side_rows.get(L.name, {}).items():
            d = pd.Timestamp(iso)
            csv = L.csv
            size0 = csv.stat().st_size if csv.exists() else 0
            try:
                out = L.record(d, rows)
            except (Exception, SystemExit) as e:   # noqa: BLE001
                side_skipped[L.name][iso] = f"record: {type(e).__name__}: {e}"
                log(f"{L.name} SKIPPED for {iso} at record (v3/ext/hedge/sue unaffected): {e}")
                if (csv.stat().st_size if csv.exists() else 0) != size0:
                    side_deferred.append(f"{csv.name} {iso}: record raised AFTER appending ({e}); "
                                         f"half-written record, fix by hand")
                continue
            try:
                ra = str(out["recorded_at"].iloc[0])
                logrows.append([csv.name, iso, iso_week(d), ra, _late(iso, ra), int(len(out))])
                if v3_incomplete(iso):
                    append_annotation(csv.name, iso, getattr(L, "incomplete_note", SEAS_INCOMPLETE_NOTE), L.source)
            except (Exception, SystemExit) as e:   # noqa: BLE001
                side_deferred.append(f"{csv.name} {iso}: sidecar step after the record failed: {type(e).__name__}: {e}")
                log(f"{L.name} sidecar step FAILED for {iso} (hedge still records; run will report it): {e}")
    if io_plan_error:          # WO-27: an io import/plan failure is logged too (no dates are known then)
        _io_guard("", "io_skipped", io_plan_error)
    if r252_plan_error:        # WO-34: likewise for r252
        _r252_guard("", "r252_skipped", r252_plan_error)
    for name, sk in side_skipped.items():
        for iso, why in sorted(sk.items()):
            if name == "io":
                _io_guard(iso, "io_skipped", why)
            elif name == "r252":
                _r252_guard(iso, "r252_skipped", why)
            elif SS is not None:
                _seas_guard(SS, iso, f"{name}_skipped", why, name)
            else:
                log(f"seas guard log unavailable ({name} {iso}): {why}")
    for _w, d in todo[HEDGE.name]:
        iso = d.date().isoformat()
        FH.record_hedge(date=iso)
        ra = _recorded_at(HEDGE, iso)
        logrows.append([HEDGE.name, iso, iso_week(d), ra, _late(iso, ra), _rows_for(HEDGE, iso)])
    if logrows:
        append_log(logrows)
    check_prefixes(before)
    check_manifest(man_before)
    if sue_deferred or side_deferred:
        raise SystemExit("SUE/side-ledger post-record problem (v3/ext/hedge recorded): "
                         + " | ".join(sue_deferred + side_deferred))
    # one record per ISO week per ledger (weeks after START_AFTER)
    for led in (V3, EXT, HEDGE, SUE, SEAS, BLEND_SEAS, IO, R252):
        for w, ds in recorded_weeks(led).items():
            if len(ds) > 1:
                raise SystemExit(f"{led.name}: more than one record in {w}: {sorted(ds)}")
    for r in logrows:
        log(f"recorded {r[0]} {r[1]} ({r[2]}): {r[5]} rows, late={r[4]}")
    if not logrows:
        log("nothing to record (every week already has a record)")
    _, left = plan()
    if sue_skipped:     # a skipped SUE date stays missing by design (isolation); logged above
        left[SUE.name] = [x for x in left[SUE.name] if x[1].date().isoformat() not in sue_skipped]
    for name, sk in side_skipped.items():   # same for the WO-20 / WO-27 side ledgers
        key = _side_keys()[name]
        left[key] = [x for x in left[key] if x[1].date().isoformat() not in sk]
    if any(left.values()):
        raise SystemExit(f"weeks still missing after run: {left}")
    return 0


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--plan", action="store_true")
    a = ap.parse_args()
    try:
        return run(dry=a.plan)
    except SystemExit as e:
        if e.code in (0, None):
            return 0
        print(f"RECORD_WEEKLY FAILED: {e}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    sys.exit(main())
