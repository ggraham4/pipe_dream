"""
WO-16 (2026-09-26): append-only incremental top-up of the Sharadar SF1 files
the working panel reads.

    python final/src/reset2026/sf1_topup.py              # top up the main-checkout files
    python final/src/reset2026/sf1_topup.py --dry-run    # pull + validate, write nothing
    python final/src/reset2026/sf1_topup.py --data-dir /tmp/x   # test on a copy

FILES (main checkout, final/data/sharadar/)
    sf1_fundamentals.parquet   key (ticker, dimension, date); ARQ + ARY
    sf1_shares.csv             key (ticker, dimension, date); ARQ + ARY, sharesbas as the API string
  `date` is SF1's datekey (the filing date), the point-in-time key every reader
  joins on (merge_asof, date <= row date).

WHAT IT PULLS (same endpoint, dimensions and columns as sharadar_pull_fundamentals.py /
sharadar_pull_shares.py; those scripts' defaults are unchanged)
    (a) date        >= max(date on disk) - DATE_BACK_DAYS
    (b) lastupdated >= min(max date on disk, last top-up run) - LASTUPD_BACK_DAYS
        (late-added keys and vendor revisions of old keys)
  for ARQ and ARY: ~4-6 calls. More than MAX_PAGES pages -> stop (a bulk pull is
  out of scope; use the full pull scripts deliberately).

RULES
  * Append-only. Every row already on disk stays byte-identical. New keys are
    inserted and the file is stable-sorted by (ticker, date, dimension), the
    order both files already have (readers' drop_duplicates(keep="last") on
    (ticker, filed_date) relies on ARQ preceding ARY).
  * A pulled row for an EXISTING key with different values is NOT applied; it
    is logged to sf1_topup_restatements.csv (deduplicated: a rerun adds nothing).
  * Every appended key is logged to sf1_topup_appended.csv. refresh_working_panel.py
    uses it to tell an explained fundamentals change from a bug.
  * Atomic: temp -> validate -> os.replace. Before the first replace of a file,
    a hard-linked dated backup <stem>_through_<old max date><suffix> is kept.
  * Idempotent: nothing new -> nothing is written (sha256 unchanged).

EXIT 0 ok (incl. nothing new), 1 failure (nothing replaced).
"""
import argparse
import csv
import hashlib
import io
import json
import os
import re
import sys
import time
from pathlib import Path

import numpy as np
import pandas as pd
import pyarrow as pa
import pyarrow.compute as pc
import pyarrow.parquet as pq
import requests

MAIN_SH = Path("/Users/ggraham/pipe_dream/final/data/sharadar")
BASE_URL = "https://api.sharadar.com/v1.0/data/fundamentals"
PAGE = 10000
DELAY = 0.2
MAX_PAGES = 20
MAX_NEW_KEYS = 50000
DATE_BACK_DAYS = 5
LASTUPD_BACK_DAYS = 2
DIMS = ("ARQ", "ARY")
KEY = ["ticker", "dimension", "date"]
SORT = ["ticker", "date", "dimension"]

# identical to sharadar_pull_fundamentals.py
KEEP = [
    "ticker", "dimension", "date", "calendardate", "reportperiod",
    "assets", "liabilities", "equity", "cashneq", "debtnc", "sharesbas",
    "revenue", "netinc", "gp", "opinc", "ncfo", "capex", "rnd",
    "eps", "epsdil", "marketcap", "price", "shareswa",
]
STRCOLS = ["ticker", "dimension", "date", "calendardate", "reportperiod"]
NUMERIC = [c for c in KEEP if c not in STRCOLS]
SHARES_FIELDS = ["ticker", "date", "sharesbas", "dimension"]

RESTATE_FIELDS = ["file", "ticker", "dimension", "date", "column", "old", "new", "lastupdated", "seen_at"]
APPEND_FIELDS = ["file", "ticker", "dimension", "date", "lastupdated", "appended_at"]


class TopupError(Exception):
    pass


def log(msg):
    print(f"[{time.strftime('%H:%M:%S')}] sf1_topup: {msg}", flush=True)


def sha256(path):
    h = hashlib.sha256()
    with open(path, "rb") as fh:
        for b in iter(lambda: fh.read(1 << 20), b""):
            h.update(b)
    return h.hexdigest()


def api_key():
    k = os.environ.get("SHARADAR_API_KEY")
    if k:
        return k
    p = Path.home() / ".config" / "pipe_dream" / "secrets.env"
    if p.exists():
        for line in p.read_text().splitlines():
            m = re.match(r"\s*(?:export\s+)?SHARADAR_API_KEY\s*=\s*['\"]?([^'\"\s]+)", line)
            if m:
                return m.group(1)
    raise TopupError("SHARADAR_API_KEY not set (env or ~/.config/pipe_dream/secrets.env)")


class Puller:
    def __init__(self, key):
        self.key, self.calls = key, 0

    def get(self, params, timeout=180, tries=4):
        last = None
        for attempt in range(tries):
            try:
                p = {"api_key": self.key, "format": "csv"}
                p.update(params)
                self.calls += 1
                r = requests.get(BASE_URL, params=p, timeout=timeout)
                if r.status_code == 200:
                    return list(csv.DictReader(io.StringIO(r.text))) if r.text.strip() else []
                last = f"HTTP {r.status_code}: {r.text[:150]}"
            except requests.RequestException as e:
                last = type(e).__name__
            time.sleep(2 ** attempt)
        raise TopupError(f"Sharadar request failed after {tries} tries: {last}")

    def pull(self, dim, flt):
        rows, off = [], 0
        while True:
            if self.calls >= MAX_PAGES:
                raise TopupError(f"more than {MAX_PAGES} pages: not an incremental range; "
                                 "a bulk pull is out of scope (BLOCKED)")
            chunk = self.get({"dimension": dim, **flt, "limit": PAGE, "offset": off})
            rows.extend(chunk)
            if len(chunk) < PAGE:
                return rows
            off += PAGE
            time.sleep(DELAY)


def _num(v):
    x = pd.to_numeric(pd.Series([v], dtype=object), errors="coerce").iloc[0]
    return float(x) if pd.notna(x) else np.nan


def _same_num(a, b):
    return (np.isnan(a) and np.isnan(b)) or a == b


def _append_csv(path, fields, rows, dedupe_on):
    """Append rows not already present (by dedupe_on). Returns number added."""
    have = set()
    if path.exists():
        with open(path, newline="") as fh:
            for r in csv.DictReader(fh):
                have.add(tuple(r[c] for c in dedupe_on))
    new = []
    for r in rows:
        k = tuple(str(r[c]) for c in dedupe_on)
        if k not in have:
            have.add(k)
            new.append(r)
    if new:
        exists = path.exists()
        with open(path, "a", newline="") as fh:
            w = csv.DictWriter(fh, fieldnames=fields)
            if not exists:
                w.writeheader()
            w.writerows(new)
    return len(new)


def _backup(path, old_max):
    bk = path.with_name(f"{path.stem}_through_{old_max}{path.suffix}")
    if bk.exists():
        bk = path.with_name(f"{path.stem}_through_{old_max}_{time.strftime('%Y%m%dT%H%M%S')}{path.suffix}")
    os.link(path, bk)
    return bk


# --------------------------------------------------------------------------- fundamentals
def merge_fundamentals(path, pulled, now, report):
    T = pq.read_table(path)
    n_old = T.num_rows
    old = T.select(KEEP).to_pandas()
    for c in STRCOLS:
        old[c] = old[c].astype(object)
    old_idx = {k: i for i, k in enumerate(zip(old["ticker"], old["dimension"], old["date"]))}
    if len(old_idx) != n_old:
        raise TopupError(f"{path.name}: key (ticker, dimension, date) not unique on disk")

    new_rows, restate, seen_new = [], [], {}
    conflicts = 0
    for r in pulled:
        k = (r.get("ticker"), r["_dim"], r.get("date"))
        rec = {c: r.get(c) for c in KEEP}
        rec["dimension"] = r["_dim"]
        if k in old_idx:
            o = old.iloc[old_idx[k]]
            for c in KEEP:
                if c in STRCOLS:
                    if str(o[c]) != (rec[c] or ""):
                        restate.append((k, c, o[c], rec[c], r.get("lastupdated", "")))
                else:
                    a, b = float(o[c]), _num(rec[c])
                    if not _same_num(a, b):
                        restate.append((k, c, a, b, r.get("lastupdated", "")))
            continue
        if k in seen_new:                      # first row seen wins, as in the full pull
            if seen_new[k] != rec:
                conflicts += 1
            continue
        seen_new[k] = rec
        new_rows.append((rec, r.get("lastupdated", "")))

    _u = {}
    for x in restate:
        _u.setdefault((x[0], x[1]), x)
    restate = list(_u.values())
    report["restatement_cells"] = len(restate)
    report["restatement_keys"] = len({x[0] for x in restate})
    report["pull_conflicting_duplicates"] = conflicts
    report["rows_appended"] = len(new_rows)
    rs = [{"file": path.name, "ticker": k[0], "dimension": k[1], "date": k[2], "column": c,
           "old": repr(a) if not isinstance(a, str) else a, "new": repr(b) if not isinstance(b, str) else b,
           "lastupdated": lu, "seen_at": now} for k, c, a, b, lu in restate]
    if not new_rows:
        return None, rs, []
    if len(new_rows) > MAX_NEW_KEYS:
        raise TopupError(f"{len(new_rows):,} new keys: not incremental (BLOCKED)")

    df = pd.DataFrame([x[0] for x in new_rows], columns=KEEP)
    for c in NUMERIC:
        df[c] = pd.to_numeric(df[c], errors="coerce")
    df["ticker"] = df["ticker"].astype(str)
    for c in STRCOLS:
        df[c] = df[c].fillna("").astype(str)
    plain = T.schema.remove_metadata()
    N = pa.Table.from_pandas(df[[f.name for f in plain]], schema=plain, preserve_index=False)
    src = pa.array(np.arange(n_old + N.num_rows, dtype=np.int64))
    both = pa.concat_tables([T.replace_schema_metadata(None), N]).append_column("_src", src)
    idx = pc.sort_indices(both, sort_keys=[(c, "ascending") for c in SORT] + [("_src", "ascending")])
    out = both.take(idx)
    pos = out.column("_src").to_numpy()
    out = out.drop(["_src"]).replace_schema_metadata(T.schema.metadata)

    # validation: old rows identical and in the same relative order, schema equal, key unique
    old_pos = np.flatnonzero(pos < n_old)
    if not (np.array_equal(pos[old_pos], np.arange(n_old))):
        raise TopupError(f"{path.name}: old rows not in their original relative order")
    if not out.take(pa.array(old_pos)).equals(T):
        raise TopupError(f"{path.name}: an old row changed")
    if out.schema != T.schema:
        raise TopupError(f"{path.name}: schema drift")
    kk = pd.DataFrame({c: out.column(c).to_pylist() for c in KEY})
    if kk.duplicated().any():
        raise TopupError(f"{path.name}: duplicate key after merge")
    ap = [{"file": path.name, "ticker": rec["ticker"], "dimension": rec["dimension"], "date": rec["date"],
           "lastupdated": lu, "appended_at": now} for rec, lu in new_rows]
    return out, rs, ap


# --------------------------------------------------------------------------- shares csv
def merge_shares(path, pulled, now, report):
    raw = path.read_bytes()
    lines = raw.split(b"\r\n")
    if lines[-1] != b"":
        raise TopupError(f"{path.name}: does not end with CRLF")
    header, body = lines[0], lines[1:-1]
    if header.decode() != ",".join(SHARES_FIELDS):
        raise TopupError(f"{path.name}: unexpected header {header!r}")
    old_keys, old_sb = [], {}
    for ln in body:
        t, d, sb, dim = next(csv.reader([ln.decode()]))
        old_keys.append((t, d, dim))
        old_sb[(t, dim, d)] = sb
    if len(old_sb) != len(body):
        raise TopupError(f"{path.name}: key not unique on disk")
    new, restate, seen = [], [], set()
    for r in pulled:
        sb = r.get("sharesbas")
        if not sb:                                   # as sharadar_pull_shares.py
            continue
        k = (r.get("ticker"), r["_dim"], r.get("date"))
        if k in old_sb:
            if old_sb[k] != sb and not any(x["ticker"] == k[0] and x["dimension"] == k[1]
                                           and x["date"] == k[2] for x in restate):
                restate.append({"file": path.name, "ticker": k[0], "dimension": k[1], "date": k[2],
                                "column": "sharesbas", "old": old_sb[k], "new": sb,
                                "lastupdated": r.get("lastupdated", ""), "seen_at": now})
            continue
        if k in seen:
            continue
        seen.add(k)
        buf = io.StringIO()
        csv.writer(buf, lineterminator="").writerow([k[0], k[2], sb, k[1]])
        new.append(((k[0], k[2], k[1]), buf.getvalue().encode(), r.get("lastupdated", "")))
    report["restatement_cells"] = len(restate)
    report["rows_appended"] = len(new)
    if not new:
        return None, restate, []
    allrows = [(k, 0, i, ln) for i, (k, ln) in enumerate(zip(old_keys, body))] + \
              [(k, 1, i, ln) for i, (k, ln, _lu) in enumerate(new)]
    allrows.sort(key=lambda x: (x[0], x[1], x[2]))
    out_lines = [x[3] for x in allrows]
    # validation: old lines are an in-order subsequence, keys unique, sorted
    olds = [x[3] for x in allrows if x[1] == 0]
    if olds != body:
        raise TopupError(f"{path.name}: old lines changed or reordered")
    ks = [x[0] for x in allrows]
    if len(set(ks)) != len(ks) or ks != sorted(ks):
        raise TopupError(f"{path.name}: duplicate/unsorted keys after merge")
    data = b"\r\n".join([header] + out_lines) + b"\r\n"
    ap = [{"file": path.name, "ticker": k[0], "dimension": k[2], "date": k[1], "lastupdated": lu,
           "appended_at": now} for k, _ln, lu in new]
    return data, restate, ap


# --------------------------------------------------------------------------- main
def run(data_dir, dry_run=False):
    t0 = time.time()
    data_dir = Path(data_dir)
    fpath, spath = data_dir / "sf1_fundamentals.parquet", data_dir / "sf1_shares.csv"
    restate_path, append_path = data_dir / "sf1_topup_restatements.csv", data_dir / "sf1_topup_appended.csv"
    state_path = data_dir / "sf1_topup_state.json"
    now = time.strftime("%Y-%m-%dT%H:%M:%S")
    report = {"started": now, "data_dir": str(data_dir), "dry_run": dry_run}

    fmax = pc.max(pq.read_table(fpath, columns=["date"]).column("date")).as_py()
    smax = pd.read_csv(spath, usecols=["date"], dtype=str)["date"].max()
    report["sha_before"] = {fpath.name: sha256(fpath), spath.name: sha256(spath)}
    report["max_date_before"] = {fpath.name: fmax, spath.name: smax}
    base = min(fmax, smax)
    state = json.loads(state_path.read_text()) if state_path.exists() else {}
    lu_base = min(base, state.get("last_run_date", base))
    d_from = (pd.Timestamp(base) - pd.Timedelta(days=DATE_BACK_DAYS)).date().isoformat()
    lu_from = (pd.Timestamp(lu_base) - pd.Timedelta(days=LASTUPD_BACK_DAYS)).date().isoformat()
    report["pull"] = {"date_gte": d_from, "lastupdated_gte": lu_from}
    log(f"on disk: fundamentals max date {fmax}, shares max date {smax}; "
        f"pulling date>={d_from} and lastupdated>={lu_from}, ARQ+ARY")

    P = Puller(api_key())
    pulled = []
    for dim in DIMS:
        for flt in ({"date.gte": d_from}, {"lastupdated.gte": lu_from}):
            rows = P.pull(dim, flt)
            for r in rows:
                r["_dim"] = dim
            pulled.extend(rows)
            log(f"  {dim} {flt}: {len(rows):,} rows")
    report["calls"] = P.calls
    report["rows_pulled"] = len(pulled)
    if any(r.get("dimension") and r["dimension"] != r["_dim"] for r in pulled):
        raise TopupError("API returned a row with a dimension other than the one requested")

    rf, rs = {}, {}
    ftab, frest, fapp = merge_fundamentals(fpath, pulled, now, rf)
    sdata, srest, sapp = merge_shares(spath, pulled, now, rs)
    report["fundamentals"], report["shares"] = rf, rs
    log(f"fundamentals: +{rf['rows_appended']:,} rows, {rf['restatement_keys']:,} restated keys "
        f"({rf['restatement_cells']:,} cells, NOT applied); shares: +{rs['rows_appended']:,} rows, "
        f"{rs['restatement_cells']:,} restated (NOT applied)")
    if dry_run:
        log(f"--dry-run: nothing written ({P.calls} calls, {time.time() - t0:.0f}s)")
        report["sha_after"] = report["sha_before"]
        return report

    # temps first (validated above in memory; re-read from disk here), then replace
    staged = []
    if ftab is not None:
        tmp = fpath.with_name(fpath.name + ".wo16tmp")
        pq.write_table(ftab, tmp)
        back = pq.read_table(tmp)
        if not back.equals(ftab) or back.schema != ftab.schema:
            raise TopupError("fundamentals temp does not read back identically")
        staged.append((tmp, fpath))
    if sdata is not None:
        tmp = spath.with_name(spath.name + ".wo16tmp")
        tmp.write_bytes(sdata)
        if tmp.read_bytes() != sdata:
            raise TopupError("shares temp does not read back identically")
        staged.append((tmp, spath))
    report["backups"] = []
    for tmp, dst in staged:
        mx = fmax if dst == fpath else smax
        report["backups"].append(str(_backup(dst, mx)))
        os.replace(tmp, dst)
    report["restatements_logged_new"] = _append_csv(
        restate_path, RESTATE_FIELDS, frest + srest, ["file", "ticker", "dimension", "date", "column", "new"])
    report["appended_logged_new"] = _append_csv(
        append_path, APPEND_FIELDS, fapp + sapp, ["file", "ticker", "dimension", "date"])
    state_path.write_text(json.dumps({"last_run_date": time.strftime("%Y-%m-%d"), "last_run_at": now,
                                      "calls": P.calls}, indent=2))
    report["sha_after"] = {fpath.name: sha256(fpath), spath.name: sha256(spath)}
    report["max_date_after"] = {
        fpath.name: pc.max(pq.read_table(fpath, columns=["date"]).column("date")).as_py(),
        spath.name: pd.read_csv(spath, usecols=["date"], dtype=str)["date"].max()}
    report["runtime_s"] = round(time.time() - t0, 1)
    (data_dir / "sf1_topup_last_report.json").write_text(json.dumps(report, indent=2, default=str))
    log(f"done: max date {report['max_date_before']} -> {report['max_date_after']}; "
        f"{P.calls} calls, {report['runtime_s']}s")
    return report


def main(argv=None):
    ap = argparse.ArgumentParser()
    ap.add_argument("--data-dir", default=str(MAIN_SH))
    ap.add_argument("--dry-run", action="store_true")
    a = ap.parse_args(argv)
    try:
        run(a.data_dir, a.dry_run)
        return 0
    except TopupError as e:
        print(f"SF1 TOP-UP FAILED (nothing replaced): {e}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    sys.exit(main())
