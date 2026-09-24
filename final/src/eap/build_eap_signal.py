"""
Build `days_to_next_announce_8k_seasonal` (WO-5, earnings-timing trial 6) on
the composite panel's (ticker, date) grid, and run Gate A.
Definition is fixed in models/2026-09-23-earnings-announcement-premium-8k.md
Part 1 -- read it first. Reads NO return column.

For each ticker/CIK with original-8-K Item 2.02 filing dates F:
  candidate c = f + 364d for each f in F; c is active on t in [f, min(c, g_c))
  where g_c = earliest g in F with g >= c - 45d (that quarter already
  announced this year). E(t) = min active c. Value = trading days t -> E(t)
  on the panel's own date calendar. NaN if nothing is active.
Only filings with filing_date <= t ever touch row t (interval starts at f).

Outputs (MAIN checkout, gitignored parquet):
  out/eap/eap_signal.parquet        ticker, date, days_to_next_announce_8k_seasonal
  out/eap/eap_gateA.json            Gate A numbers

Usage: python3.11 build_eap_signal.py
"""
import json
import time
from pathlib import Path

import numpy as np
import pandas as pd

MAIN_ROOT = Path("/Users/ggraham/pipe_dream/final")
PANEL = MAIN_ROOT / "out" / "reset2026" / "composite_panel.parquet"
TICKERS_MASTER = MAIN_ROOT / "data" / "sharadar" / "tickers_master.csv"
RAW = MAIN_ROOT / "data" / "edgar" / "8k_item202.parquet"
OUT_DIR = MAIN_ROOT / "out" / "eap"
OUT = OUT_DIR / "eap_signal.parquet"
GATE = OUT_DIR / "eap_gateA.json"
COL = "days_to_next_announce_8k_seasonal"
ANNIV = 364
USED_TOL = 45
NOMINATE_START = pd.Timestamp("2007-01-02")
NOMINATE_END = pd.Timestamp("2019-12-31")
DEAD = ["LEHMQ", "WAMUQ", "MER", "CFC"]


def log(msg):
    print(f"[{time.strftime('%H:%M:%S')}] {msg}", flush=True)


def load_filings():
    raw = pd.read_parquet(RAW)
    k = raw[raw["form"] == "8-K"].copy()
    k["filing_date"] = pd.to_datetime(k["filing_date"])
    return raw, k


def cik_map():
    tm = pd.read_csv(TICKERS_MASTER, usecols=["ticker", "secfilings"])
    tm["cik"] = pd.to_numeric(tm["secfilings"].str.extract(r"CIK=0*(\d+)")[0], errors="coerce")
    return tm.dropna(subset=["cik"]).astype({"cik": "int64"})[["ticker", "cik"]].drop_duplicates("ticker")


def expected_dates(fdays, tdays):
    """fdays: sorted unique filing days (int, days since epoch). tdays: sorted
    panel days for one ticker. Returns E(t) in days (float, NaN if none)."""
    E = np.full(len(tdays), np.inf)
    for f in fdays:
        c = f + ANNIV
        j = np.searchsorted(fdays, c - USED_TOL, side="left")
        end = min(c, fdays[j]) if j < len(fdays) else c
        i0 = np.searchsorted(tdays, f, side="left")
        i1 = np.searchsorted(tdays, end, side="left")
        if i1 > i0:
            np.minimum(E[i0:i1], c, out=E[i0:i1])
    E[~np.isfinite(E)] = np.nan
    return E


def main():
    t0 = time.time()
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    raw, k = load_filings()
    log(f"8-K 2.02 rows {len(k):,} (8-K/A excluded: {(raw['form'] == '8-K/A').sum():,}), CIKs {k['cik'].nunique():,}")

    panel = pd.read_parquet(PANEL, columns=["ticker", "date", "eligible_cap150"])
    panel["date"] = pd.to_datetime(panel["date"]); panel["ticker"] = panel["ticker"].astype(str)
    panel["_row"] = np.arange(len(panel), dtype=np.int64)
    cal = np.sort(panel["date"].unique()).astype("datetime64[D]").astype(np.int64)

    cm = cik_map()
    fil_by_cik = {c: np.unique(g["filing_date"].to_numpy().astype("datetime64[D]").astype(np.int64))
                  for c, g in k.groupby("cik")}
    tick_cik = dict(zip(cm["ticker"], cm["cik"]))

    vals = np.full(len(panel), np.nan)
    Eall = np.full(len(panel), np.nan)
    p_sorted = panel.sort_values(["ticker", "date"])
    for tk, g in p_sorted.groupby("ticker", sort=False):
        cik = tick_cik.get(tk)
        if cik is None or cik not in fil_by_cik:
            continue
        td = g["date"].to_numpy().astype("datetime64[D]").astype(np.int64)
        E = expected_dates(fil_by_cik[cik], td)
        ok = np.isfinite(E)
        v = np.full(len(td), np.nan)
        Ei = E[ok].astype(np.int64)
        inside = Ei <= cal[-1]
        idx_ok = np.flatnonzero(ok)
        v[idx_ok[inside]] = (np.searchsorted(cal, Ei[inside], side="left")
                             - np.searchsorted(cal, td[ok][inside], side="left"))
        rows = g["_row"].to_numpy()
        vals[rows] = v
        Eall[rows] = E
    panel[COL] = vals
    panel["_E"] = pd.to_datetime(Eall, unit="D")
    assert (panel["_row"].to_numpy() == np.arange(len(panel))).all(), "row order changed"
    assert (panel[COL].dropna() > 0).all(), "expected date not strictly after t"

    gate = {}
    # --- AAPL named dates
    a = k[k["cik"] == 320193]["filing_date"]
    fy12 = sorted(str(d.date()) for d in a if d.year == 2012)
    need = ["2012-01-24", "2012-04-24", "2012-07-24", "2012-10-25"]
    gate["aapl_2012_202_dates"] = fy12
    assert all(d in fy12 for d in need), f"AAPL 2012 2.02 dates missing: {fy12}"
    ap = panel[panel["ticker"] == "AAPL"].set_index("date")
    e0 = ap.loc[pd.Timestamp("2013-01-02"), "_E"]
    gate["aapl_E_at_2013-01-02"] = str(e0.date())
    assert e0 == pd.Timestamp("2013-01-22"), f"AAPL E at 2013-01-02 is {e0}"
    jan13 = [d for d in a if d.year == 2013 and d.month == 1]
    after = ap.loc[ap.index > jan13[0]].iloc[0]
    gate["aapl_jan2013_202"] = str(jan13[0].date())
    gate["aapl_E_day_after_jan2013_202"] = str(after["_E"].date())
    assert after["_E"] == pd.Timestamp("2013-04-23"), f"AAPL E after Jan-13 is {after['_E']}"
    gate["aapl_value_at_2013-01-02_trading_days"] = float(ap.loc[pd.Timestamp("2013-01-02"), COL])
    log(f"AAPL checks passed: {gate['aapl_E_at_2013-01-02']} -> {gate['aapl_E_day_after_jan2013_202']}")

    # --- dead companies
    dead = {}
    for tk in DEAD:
        cik = tick_cik.get(tk)
        fd = k[k["cik"] == cik]["filing_date"] if cik is not None else pd.Series([], dtype="datetime64[ns]")
        pr = panel[panel["ticker"] == tk]
        dead[tk] = {"cik": None if cik is None else int(cik), "n_202": int(len(fd)),
                    "first": str(fd.min().date()) if len(fd) else None,
                    "last": str(fd.max().date()) if len(fd) else None,
                    "last_panel_date": str(pr["date"].max().date()) if len(pr) else None,
                    "signal_nonnull_rows": int(pr[COL].notna().sum())}
    gate["dead_companies"] = dead
    assert any(v["n_202"] > 0 and v["signal_nonnull_rows"] > 0 for v in dead.values()), "no dead company present"
    log(f"dead companies: {dead}")

    # --- cadence
    kk = k[(k["filing_date"] >= "2007-01-01") & (k["filing_date"] <= "2019-12-31")]
    per = kk.groupby(["cik", kk["filing_date"].dt.year]).size()
    gate["cadence_filings_per_issuer_year"] = {"median": float(per.median()), "mean": float(per.mean()),
                                               "p10": float(per.quantile(.1)), "p90": float(per.quantile(.9)),
                                               "share_eq_4": float((per == 4).mean())}
    # --- after-16:00 ET
    acc = pd.to_datetime(k["acceptance_et"])
    hr = acc.dt.hour + acc.dt.minute / 60
    gate["acceptance"] = {"frac_after_1600_et": float((hr >= 16).mean()),
                          "frac_before_0930_et": float((hr < 9.5).mean()),
                          "frac_0930_1600_et": float(((hr >= 9.5) & (hr < 16)).mean()),
                          "frac_after_1730_et": float((hr >= 17.5).mean()),
                          "frac_filing_date_ne_acceptance_date": float((acc.dt.normalize() != k["filing_date"]).mean())}
    # --- distribution + coverage on cap150 nomination rows
    nom = panel[(panel["date"] >= NOMINATE_START) & (panel["date"] <= NOMINATE_END) & panel["eligible_cap150"]]
    v = nom[COL].dropna()
    gate["distribution_cap150_nominate"] = {"median": float(v.median()), "p10": float(v.quantile(.1)),
                                            "p90": float(v.quantile(.9)), "max": float(v.max()),
                                            "frac_le_40": float((v <= 40).mean()), "frac_gt_70": float((v > 70).mean())}
    gate["coverage_cap150_by_year"] = {int(y): float(s) for y, s in
                                       nom.groupby(nom["date"].dt.year)[COL].apply(lambda s: s.notna().mean()).items()}
    gate["coverage_cap150_nominate"] = float(nom[COL].notna().mean())
    for kx in ("cadence_filings_per_issuer_year", "acceptance", "distribution_cap150_nominate",
               "coverage_cap150_by_year"):
        log(f"{kx}: {gate[kx]}")

    panel[["ticker", "date", COL]].to_parquet(OUT, index=False)
    GATE.write_text(json.dumps(gate, indent=2, default=str))
    log(f"wrote {OUT} and {GATE} ({time.time()-t0:.0f}s)")


if __name__ == "__main__":
    main()
