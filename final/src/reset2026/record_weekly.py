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
ALL_LEDGERS = [R26 / n for n in ("prediction_ledger.csv", "prediction_ledger_v2.csv",
                                 "prediction_ledger_v3.csv", "prediction_ledger_ext.csv",
                                 "prediction_ledger_hedge.csv", "prediction_ledger_sue.csv")]
LATE_DAYS = 7
SUE_INCOMPLETE_NOTE = ("incomplete_week: paired with the v3 record for this date, which is annotated "
                       "incomplete_week; descriptive only, never a counted date; WO-15 2026-09-26")


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
    for p in ALL_LEDGERS + [LOG_CSV, ANN_CSV]:
        if p.exists():
            b = p.read_bytes()
            h[p.name] = (len(b), hashlib.sha256(b).hexdigest())
    return h


def check_prefixes(before):
    for name, (n, sha) in before.items():
        b = (R26 / name).read_bytes()
        if len(b) < n or hashlib.sha256(b[:n]).hexdigest() != sha:
            raise SystemExit(f"PREFIX CHANGED: {name} -- existing rows were modified")


def plan():
    targets = weekly_targets()
    p = {}
    for led in (V3, EXT, HEDGE):
        have = recorded_weeks(led)
        p[led.name] = [(w, d) for w, d in sorted(targets.items()) if w not in have]
    # WO-15: SUE dates = v3 dates after 2026-09-08 (existing + this run's) without a SUE record
    SF = _sue_forward()
    p[SUE.name] = [(iso_week(d), d) for d in SF.todo_dates([d for _w, d in p[V3.name]])]
    return targets, p


def _sue_forward():
    sys.path.insert(0, str(HERE.parent / "sue"))
    import sue_forward as SF
    return SF


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
    # WO-15 SUE preflight: SF1-live freshness (pulls once if needed), basis
    # validation, blindness, backfill gate, and the full rows, for EVERY SUE
    # date of this run (existing and new v3 dates) before anything is written.
    SF = _sue_forward()
    sue_dates = [d for _w, d in todo[SUE.name]]
    sue_rows = {}
    if sue_dates:
        cal = SF.panel_calendar()
        live, pulled_at = SF.ensure_live(sue_dates, cal)
        basis = SF.basis_validation(live)
        log(f"SUE basis validation: {basis['overlap_keys']:,} overlapping keys, {basis['mismatch_rows']} eps "
            f"mismatches on split names {basis['mismatch_tickers']}, 0 unexplained")
        v3_have = set(pd.read_csv(V3, usecols=["panel_date"])["panel_date"].astype(str)) if V3.exists() else set()
        for d in sue_dates:
            iso = d.date().isoformat()
            rows, info = SF.build_sue_rows(d, live, pulled_at, cal)
            if iso in v3_have:
                SF.check_pairing(rows, d)
            if iso in SF.BACKFILL_DATES:
                info["backfill_gate"] = SF.backfill_gate(rows, info, d, basis_ok=True)
            sue_rows[iso] = rows
            log(f"SUE preflight {iso}: {info}")
    log("preflight passed (blind, guards, insider freshness, SUE)")
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
    # SUE, right after v3 (record_sue re-checks blindness, duplicates, pairing)
    for d in sue_dates:
        iso = d.date().isoformat()
        out = SF.record_sue(d, sue_rows[iso])
        ra = str(out["recorded_at"].iloc[0])
        logrows.append([SUE.name, iso, iso_week(d), ra, _late(iso, ra), int(len(out))])
        if v3_incomplete(iso):
            append_annotation(SUE.name, iso, SUE_INCOMPLETE_NOTE, "WO-15")
    for _w, d in todo[HEDGE.name]:
        iso = d.date().isoformat()
        FH.record_hedge(date=iso)
        ra = _recorded_at(HEDGE, iso)
        logrows.append([HEDGE.name, iso, iso_week(d), ra, _late(iso, ra), _rows_for(HEDGE, iso)])
    if logrows:
        append_log(logrows)
    check_prefixes(before)
    check_manifest(man_before)
    # one record per ISO week per ledger (weeks after START_AFTER)
    for led in (V3, EXT, HEDGE, SUE):
        for w, ds in recorded_weeks(led).items():
            if len(ds) > 1:
                raise SystemExit(f"{led.name}: more than one record in {w}: {sorted(ds)}")
    for r in logrows:
        log(f"recorded {r[0]} {r[1]} ({r[2]}): {r[5]} rows, late={r[4]}")
    if not logrows:
        log("nothing to record (every week already has a record)")
    _, left = plan()
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
