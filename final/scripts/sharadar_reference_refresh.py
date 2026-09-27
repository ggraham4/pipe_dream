"""
WO-17 (2026-09-26): refresh the Sharadar reference tables in the MAIN checkout
    final/data/sharadar/tickers_master.csv   (TICKERS table=stocks, full)
    final/data/sharadar/actions.csv          (ACTIONS date.gte=2026-09-01, merged)
with a LABEL HOLD-BACK for tickers already in the 2026-09-08 master.
Pre-registration: final/models/2026-09-26-wo17-reference-refresh.md

    python final/scripts/sharadar_reference_refresh.py --dry-run   # pull + build + validate, no live write
    python final/scripts/sharadar_reference_refresh.py             # ... then atomic replace
    python final/scripts/sharadar_reference_refresh.py --reuse-pull   # rebuild from the staged pull

Pull code is the existing one: get / get_all from final/src/sharadar_build_identity_map.py
(the script that built both files). Its main() is never called. The key comes only
from env SHARADAR_API_KEY; request errors are re-raised with the key scrubbed.

Idempotent: the outputs are built from the dated backups
(tickers_master_through_2026-09-08.csv, actions_through_2026-09-10.csv), which are
created once from the live files and never overwritten. If the live file already
equals the rebuilt output, nothing is written.

Exit 0 = written or already current; 1 = a gate failed (nothing written).
"""
import argparse
import csv
import hashlib
import io
import json
import os
import re
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE.parent / "src"))
import sharadar_build_identity_map as SB  # noqa: E402  (existing pull code)

MAIN = Path("/Users/ggraham/pipe_dream/final")
SH = MAIN / "data" / "sharadar"
MASTER = SH / "tickers_master.csv"
ACTIONS = SH / "actions.csv"
MASTER_BK = SH / "tickers_master_through_2026-09-08.csv"
ACTIONS_BK = SH / "actions_through_2026-09-10.csv"
BRANCH_OUT = HERE.parent / "out" / "wo17"
STAGE = HERE.parent.parent / ".wo17_staging"          # raw pulls, not committed

ACTIONS_FROM = "2026-09-01"
LABEL_COLS = ["category", "siccode", "sicsector", "sicindustry", "famaindustry", "sector", "industry"]
# Addendum A (2026-09-26, iteration 2): the 09-26 pull floors firstpricedate at 1997-12-31
# for 7,860 tickers (AAPL 1986-01-01 -> 1997-12-31), failing G6. Held back too, so the
# master keeps the pre-1998 first-price information.
HOLD_COLS = LABEL_COLS + ["firstpricedate"]
TIME_COLS = {"lastupdated", "lastpricedate", "lastquarter", "firstquarter", "scalemarketcap", "scalerevenue"}
MEGA = ["AAPL", "MSFT", "NVDA"]
BASE_MASTER_ROWS = 20965


class GateError(Exception):
    pass


def scrub(s):
    s = str(s)
    k = os.environ.get("SHARADAR_API_KEY") or ""
    if k:
        s = s.replace(k, "***")
    return re.sub(r"api_key=[^&\s'\"]+", "api_key=***", s)


def pull(table, params):
    try:
        return SB.get_all(table, params)
    except Exception as e:  # never let the URL (with the key) reach stdout
        raise RuntimeError(f"{table} pull failed: {scrub(e)}") from None


def read_csv(path):
    with open(path, newline="") as fh:
        r = csv.DictReader(fh)
        return r.fieldnames, list(r)


def to_bytes(header, rows):
    buf = io.StringIO(newline="")
    w = csv.DictWriter(buf, fieldnames=header)   # default \r\n, same as the original writer
    w.writeheader()
    w.writerows(rows)
    return buf.getvalue().encode()


def sha1(p):
    return hashlib.sha1(Path(p).read_bytes()).hexdigest()


def dedupe(rows, header):
    seen, out = set(), []
    for r in rows:
        k = tuple(r.get(c, "") for c in header)
        if k not in seen:
            seen.add(k)
            out.append(r)
    return out


def ensure_backup(live, bk):
    if bk.exists():
        return "exists"
    data = live.read_bytes()
    tmp = bk.with_suffix(bk.suffix + ".tmp")
    tmp.write_bytes(data)
    os.replace(tmp, bk)
    assert sha1(bk) == hashlib.sha1(data).hexdigest()
    return "created"


def build_master(base_h, base, new_h, new):
    if new_h != base_h:
        raise GateError(f"G3 master header changed: {new_h} vs {base_h}")
    n_raw = len(new)
    new = dedupe(new, base_h)
    if n_raw < BASE_MASTER_ROWS:
        raise GateError(f"G1 pulled master has {n_raw} rows < {BASE_MASTER_ROWS}")
    pcount = {}
    for r in base:
        pcount[r["permaticker"]] = pcount.get(r["permaticker"], 0) + 1
    base_dup = {p for p, n in pcount.items() if n > 1}
    ncount = {}
    for r in new:
        ncount[r["permaticker"]] = ncount.get(r["permaticker"], 0) + 1
    new_dup = {p for p, n in ncount.items() if n > 1} - base_dup
    if new_dup:
        raise GateError(f"G1 pulled master repeats permatickers {sorted(new_dup)[:20]}")

    base_first = {}
    for r in base:
        base_first.setdefault(r["ticker"], r)
    new_tickers = {r["ticker"] for r in new}
    new_perma = {r["permaticker"] for r in new}
    kept_verbatim = [r for r in base if r["ticker"] not in new_tickers]
    missing_perma = sorted({r["permaticker"] for r in base} - new_perma
                           - {r["permaticker"] for r in kept_verbatim})
    if missing_perma:
        raise GateError(f"G2 base permatickers lost: {missing_perma[:20]}")

    pending, out = [], []
    for r in new:
        b = base_first.get(r["ticker"])
        r = dict(r)
        if b is not None:
            for c in HOLD_COLS:
                if r[c] != b[c]:
                    pending.append({"ticker": r["ticker"], "permaticker_new": r["permaticker"],
                                    "permaticker_base": b["permaticker"], "column": c,
                                    "base": b[c], "new": r[c]})
                    r[c] = b[c]
        out.append(r)
    out.extend(kept_verbatim)
    # G5
    of = {}
    for r in out:
        of.setdefault(r["ticker"], r)
    for t, b in base_first.items():
        o = of.get(t)
        if o is None or any(o[c] != b[c] for c in HOLD_COLS):
            raise GateError(f"G5 label hold-back broken for {t}")
    # G6
    mega = []
    for t in MEGA:
        b, o = base_first[t], of[t]
        diff = {c: (b[c], o[c]) for c in base_h if c not in TIME_COLS and b[c] != o[c]}
        mega.append({"ticker": t, "diff_non_time_cols": diff,
                     "time_cols": {c: (b[c], o[c]) for c in TIME_COLS if b[c] != o[c]}})
        if diff:
            raise GateError(f"G6 {t} changed: {diff}")
    if len(out) < len(base) - 1:
        raise GateError(f"G7 master rows {len(out)} < base {len(base)} - 1")
    info = {"pulled_rows": n_raw, "pulled_rows_dedup": len(new), "output_rows": len(out),
            "base_rows": len(base), "base_tickers_kept_verbatim": [r["ticker"] for r in kept_verbatim],
            "new_tickers_vs_base": sorted(new_tickers - set(base_first)),
            "label_diffs_held_back": len(pending),
            "held_back_by_column": {c: sum(1 for p in pending if p["column"] == c) for c in HOLD_COLS},
            "tickers_with_held_back_diffs": len({p["ticker"] for p in pending}), "mega": mega}
    return out, pending, info


def build_actions(base_h, base, new_h, new):
    if new_h != base_h:
        raise GateError(f"G3 actions header changed: {new_h} vs {base_h}")
    if not new:
        raise GateError("G4 actions pull empty")
    dmin, dmax = min(r["date"] for r in new), max(r["date"] for r in new)
    if dmin < ACTIONS_FROM or dmax <= "2026-09-10":
        raise GateError(f"G4 pulled actions span {dmin}..{dmax}")
    new = dedupe(new, base_h)
    old = [r for r in base if r["date"] < ACTIONS_FROM]
    out = dedupe(new + old, base_h)
    if len(out) < len(old):
        raise GateError("G7 actions shrank")
    key = lambda r: tuple(r[c] for c in base_h)  # noqa: E731
    ov_base = {key(r) for r in base if r["date"] >= ACTIONS_FROM}
    ov_new = {key(r) for r in new if r["date"] <= "2026-09-10"}
    diff = [dict(zip(base_h, k), side="base_only") for k in sorted(ov_base - ov_new)] + \
           [dict(zip(base_h, k), side="pull_only") for k in sorted(ov_new - ov_base)]
    info = {"pulled_rows": len(new), "pulled_span": [dmin, dmax], "base_rows_kept_pre_0901": len(old),
            "output_rows": len(out), "overlap_0901_0910_base_only": len(ov_base - ov_new),
            "overlap_0901_0910_pull_only": len(ov_new - ov_base)}
    return out, diff, info


def write_csv_rows(path, rows, header):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(to_bytes(header, rows) if rows else (",".join(header) + "\r\n").encode())


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--dry-run", action="store_true")
    ap.add_argument("--reuse-pull", action="store_true")
    a = ap.parse_args()
    if not os.environ.get("SHARADAR_API_KEY") and not a.reuse_pull:
        sys.exit("SHARADAR_API_KEY not set")
    STAGE.mkdir(exist_ok=True)
    pm, pa = STAGE / "tickers_pull.csv", STAGE / "actions_pull.csv"
    if not a.reuse_pull:
        print("pull tickers table=stocks ...", flush=True)
        rows = pull("tickers", {"table": "stocks"})
        pm.write_bytes(to_bytes(list(rows[0].keys()), rows))
        print(f"pull actions date.gte={ACTIONS_FROM} ...", flush=True)
        rows = pull("actions", {"date.gte": ACTIONS_FROM})
        pa.write_bytes(to_bytes(list(rows[0].keys()), rows))
    report = {"dry_run": a.dry_run, "live_sha1_before": {MASTER.name: sha1(MASTER), ACTIONS.name: sha1(ACTIONS)}}

    try:
        mb = MASTER_BK if MASTER_BK.exists() else MASTER
        ab = ACTIONS_BK if ACTIONS_BK.exists() else ACTIONS
        bh, base = read_csv(mb)
        nh, new = read_csv(pm)
        m_out, pending, m_info = build_master(bh, base, nh, new)
        abh, abase = read_csv(ab)
        anh, anew = read_csv(pa)
        a_out, a_diff, a_info = build_actions(abh, abase, anh, anew)
        m_bytes, a_bytes = to_bytes(bh, m_out), to_bytes(abh, a_out)
        # re-read check (G3 on the serialized output)
        for b, h, n in ((m_bytes, bh, len(m_out)), (a_bytes, abh, len(a_out))):
            r = csv.DictReader(io.StringIO(b.decode(), newline=""))
            if r.fieldnames != h or sum(1 for _ in r) != n:
                raise GateError("re-read of serialized output failed")
    except GateError as e:
        print(f"GATE FAILED: {e}", file=sys.stderr)
        return 1

    BRANCH_OUT.mkdir(parents=True, exist_ok=True)
    write_csv_rows(BRANCH_OUT / "master_label_changes_pending.csv", pending,
                   ["ticker", "permaticker_new", "permaticker_base", "column", "base", "new"])
    write_csv_rows(BRANCH_OUT / "actions_overlap_diff.csv", a_diff, abh + ["side"])
    report.update({"master": m_info, "actions": a_info,
                   "output_sha1": {MASTER.name: hashlib.sha1(m_bytes).hexdigest(),
                                   ACTIONS.name: hashlib.sha1(a_bytes).hexdigest()}})
    (STAGE / "tickers_master.built.csv").write_bytes(m_bytes)
    (STAGE / "actions.built.csv").write_bytes(a_bytes)

    if not a.dry_run:
        report["backups"] = {MASTER_BK.name: ensure_backup(MASTER, MASTER_BK),
                             ACTIONS_BK.name: ensure_backup(ACTIONS, ACTIONS_BK)}
        for live, data in ((MASTER, m_bytes), (ACTIONS, a_bytes)):
            if live.read_bytes() == data:
                report.setdefault("already_current", []).append(live.name)
                continue
            tmp = live.with_name(live.name + ".wo17tmp")
            tmp.write_bytes(data)
            if tmp.read_bytes() != data:
                tmp.unlink()
                raise SystemExit(f"temp verify failed for {live.name}")
            os.replace(tmp, live)
        report["live_sha1_after"] = {MASTER.name: sha1(MASTER), ACTIONS.name: sha1(ACTIONS),
                                     MASTER_BK.name: sha1(MASTER_BK), ACTIONS_BK.name: sha1(ACTIONS_BK)}
    (BRANCH_OUT / ("run_report_dry.json" if a.dry_run else "run_report.json")).write_text(
        json.dumps(report, indent=2, default=str))
    print(json.dumps({k: v for k, v in report.items()}, indent=1, default=str)[:4000])
    return 0


if __name__ == "__main__":
    sys.exit(main())
