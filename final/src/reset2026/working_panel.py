"""
The working panel: ONE place that says which composite panel the live and
forward code reads (WO-11, 2026-09-25).

Gabe, 2026-09-25: "Lets make the v2 panel the working panel going forward,
all models should use it."  Decided; not relitigated here.

    WORKING_PANEL  = out/reset2026/composite_panel_v2.parquet   (9,266 tickers)
    V1_PANEL       = out/reset2026/composite_panel.parquet      (4,011 tickers,
                     survivorship-selected; kept, never deleted, still read by
                     research scripts that reproduce published results)

THE UNIVERSE RULE THAT GOES WITH v2 (read before scoring anything on it)
    v2 was built with SPACs INCLUDED; every measurement on it (WO-6 readout
    column "c", WO-7, WO-9) excludes them at analysis time with one rule:

        keep a ticker if it is in the old 4,011-ticker grid
                      OR its SIC industry is not "Blank Check"

    (downcap_v2_readout.load_column("c")). The raw v2 `eligible_cap*` flags
    still include SPACs. A SPAC trades at trust value with volatility_60
    near 0, so inverse-vol weighting would put it at the TOP of a
    decile_volq book. The rule must be applied BEFORE scoring, because
    rank_z is computed over the whole cross-section. `working_cross_section`
    does exactly that; use it, not a raw read of the flags.

    The old-grid ticker set is FROZEN in old_grid_tickers_4011.txt (sha256
    in OLD_GRID_SHA256), not read from V1_PANEL at runtime: the app's
    Retrain-ALL pipeline rewrites composite_panel.parquet (build_panel.py),
    and a runtime read would silently move the universe the day that
    happens. `selftest()` checks the frozen list against V1_PANEL and
    pit_universe.parquet.

FROZEN THINGS THAT DO NOT MOVE WITH THE PANEL
    ICW8 / ICW9 weights (ic_weighted_composite.PRODUCTION_WEIGHTS,
    prediction_ledger.ICW9_WEIGHTS) and the v3 Fama-MacBeth slope are
    constants. Scores on v2 use the same weights and the same rank_z
    standardisation over a different cross-section.

LEDGER PANEL MANIFEST
    out/reset2026/ledger_panel_manifest.json, {ledger file: {panel_date:
    panel file}}. Every record() writes its entry; the entries for the
    records made before the switch (all on V1_PANEL, panel_date 2026-09-08)
    are seeded by `seed_manifest()`.
"""
import hashlib
import json
from pathlib import Path

import numpy as np
import pandas as pd

MAIN_ROOT = Path("/Users/ggraham/pipe_dream/final")
R26 = MAIN_ROOT / "out" / "reset2026"
SH = MAIN_ROOT / "data" / "sharadar"

V1_PANEL = R26 / "composite_panel.parquet"
WORKING_PANEL = R26 / "composite_panel_v2.parquet"
WORKING_PANEL_SOURCE = "composite_panel_v2"
WORKING_BETA = R26 / "beta_feature_v2.parquet"
WORKING_OUTCOME = R26 / "outcome_cache_v2.parquet"
TICKERS_MASTER = SH / "tickers_master.csv"

OLD_GRID_TXT = Path(__file__).resolve().parent / "old_grid_tickers_4011.txt"
OLD_GRID_SHA256 = "474f0c0b1dd24be906b5dc7592963b972f6931076febda28686a6297ac985830"
OLD_GRID_N = 4011

MANIFEST = R26 / "ledger_panel_manifest.json"
SWITCH_NOTE = ("Working panel switched v1 -> v2 on 2026-09-25 (Gabe; WO-11). Records "
               "dated 2026-09-08 in the v1/v2/v3/ext ledgers were made on "
               "composite_panel.parquet and are never rewritten. New v3/ext records "
               "from the next record date on use composite_panel_v2.parquet. The hedge "
               "ledger (WO-10) is on v2 from its first record. Doc: "
               "final/models/2026-09-25-forward-hedged-icw8.md")


def old_grid_tickers():
    raw = OLD_GRID_TXT.read_bytes()
    got = hashlib.sha256(raw).hexdigest()
    if got != OLD_GRID_SHA256:
        raise SystemExit(f"{OLD_GRID_TXT.name} sha256 {got} != frozen {OLD_GRID_SHA256}")
    t = {x for x in raw.decode().split("\n") if x}
    assert len(t) == OLD_GRID_N, len(t)
    return t


def spac_tickers():
    tm = pd.read_csv(TICKERS_MASTER, dtype=str, usecols=["ticker", "sicindustry"]).drop_duplicates("ticker")
    return set(tm.loc[tm["sicindustry"].fillna("").str.contains("Blank Check"), "ticker"])


def universe_keep(tickers):
    """Boolean mask: the column-c rule (old grid OR not a SPAC)."""
    old, spac = old_grid_tickers(), spac_tickers()
    t = pd.Series(tickers, dtype=str)
    return (t.isin(old) | ~t.isin(spac)).to_numpy()


def latest_date(path=WORKING_PANEL):
    import pyarrow.parquet as pq
    d = pq.read_table(path, columns=["date"]).column("date")
    import pyarrow.compute as pc
    return pd.Timestamp(pc.max(d).as_py())


def working_cross_section(columns, date=None, path=WORKING_PANEL, apply_universe_rule=True):
    """All rows of ONE date (default: the panel's latest) with `columns`,
    date parsed, ticker str, SPAC rule applied (before any scoring).
    Returns (frame, info) where info counts the rows the rule dropped."""
    date = latest_date(path) if date is None else pd.Timestamp(date)
    cols = list(dict.fromkeys(["ticker", "date"] + list(columns)))
    df = pd.read_parquet(path, columns=cols, filters=[("date", "==", date.date().isoformat())])
    df["date"] = pd.to_datetime(df["date"])
    df["ticker"] = df["ticker"].astype(str)
    info = {"date": date.date().isoformat(), "rows": int(len(df))}
    if apply_universe_rule:
        keep = universe_keep(df["ticker"])
        for c in [c for c in df.columns if c.startswith("eligible_")]:
            info[f"spac_rows_dropped_{c}"] = int((df[c].astype(bool) & ~keep).sum())
        info["rows_dropped_spac_rule"] = int((~keep).sum())
        df = df[keep].reset_index(drop=True)
    return df, info


# ------------------------------------------------------------------ manifest
def _load_manifest():
    if MANIFEST.exists():
        return json.loads(MANIFEST.read_text())
    return {"note": SWITCH_NOTE, "working_panel": WORKING_PANEL.name, "ledgers": {}}


def record_manifest(ledger_csv, panel_date, panel_path):
    """Called by every record(). Refuses to change an existing entry."""
    m = _load_manifest()
    led = m["ledgers"].setdefault(Path(ledger_csv).name, {})
    k = pd.Timestamp(panel_date).date().isoformat()
    v = Path(panel_path).name
    if k in led and led[k] != v:
        raise SystemExit(f"manifest: {Path(ledger_csv).name} {k} already maps to {led[k]}, refusing {v}")
    led[k] = v
    MANIFEST.write_text(json.dumps(m, indent=2, sort_keys=False))
    return m


def seed_manifest():
    """The pre-switch records: every panel_date present in the v1/v2/v3/ext
    ledgers was recorded on V1_PANEL. Reads only the panel_date column."""
    for name in ("prediction_ledger.csv", "prediction_ledger_v2.csv",
                 "prediction_ledger_v3.csv", "prediction_ledger_ext.csv"):
        p = R26 / name
        if not p.exists():
            continue
        for d in sorted(pd.read_csv(p, usecols=["panel_date"])["panel_date"].astype(str).unique()):
            record_manifest(p, d, V1_PANEL)
    return _load_manifest()


def panel_for(ledger_csv, panel_date):
    m = _load_manifest()
    return m["ledgers"].get(Path(ledger_csv).name, {}).get(pd.Timestamp(panel_date).date().isoformat())


def selftest():
    import pyarrow.parquet as pq
    old = old_grid_tickers()
    v1 = set(pq.read_table(V1_PANEL, columns=["ticker"]).column("ticker").unique().to_pylist())
    pu = set(pd.read_parquet(SH / "pit_universe.parquet", columns=["ticker"])["ticker"].astype(str))
    print(f"frozen old grid {len(old)}; == V1_PANEL tickers: {old == v1}; == pit_universe: {old == pu}")
    return old == v1 and old == pu


if __name__ == "__main__":
    import sys
    cmd = sys.argv[1] if len(sys.argv) > 1 else "selftest"
    if cmd == "seed":
        print(json.dumps(seed_manifest(), indent=2))
    else:
        sys.exit(0 if selftest() else 1)
