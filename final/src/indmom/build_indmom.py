"""
WO-50: build ind_mom_12_1 (Moskowitz-Grinblatt 1999 industry momentum), pre-reg section 1.4.
Pre-registration: final/models/2026-10-08-industry-momentum.md (sha256 asserted at import).

Population: all eligible_cap2000 rows of the v2 grid (model_audit_wo23.load_theo("A", "cap2000"),
which applies the SPAC filter), finite momentum_12_1. Group key = Sharadar `industry`
(tickers_master.csv, table == stocks); if the (date, industry) group has < 5 finite members,
the key becomes the full (date, sector) cap2000 group (tickers_master `sector`); if that has
< 5 members, NaN. Value = equal-weighted mean of members' momentum_12_1, including stock i.
Rows whose own momentum_12_1 is NaN are not members and get NaN (literal reading, recorded
in the results doc header before outcomes).

Era 2007-01-02..2019-12-31 ONLY (hard asserts).
Usage: python build_indmom.py   -> final/out/indmom/cache/indmom_factor.parquet + parts/build.json
"""
import hashlib
import json
import sys
import time
from pathlib import Path

import numpy as np
import pandas as pd

HERE = Path(__file__).resolve().parent
SRC = HERE.parent
FINAL = HERE.parents[1]
PREREG = FINAL / "models" / "2026-10-08-industry-momentum.md"
PREREG_SHA = "c686ad7e9f29b1d26491de2ef6d9865c25ca5804c3412085c79100fb3f28cc16"
assert hashlib.sha256(PREREG.read_bytes()).hexdigest() == PREREG_SHA, "PRE-REG CHANGED SINCE FREEZE: STOP"

HOLDOUT = pd.Timestamp("2020-01-01")
MIN_N = 5
COL = "ind_mom_12_1"
SH = Path("/Users/ggraham/pipe_dream/final/data/sharadar")
TM = SH / "tickers_master.csv"
TM_OLD = SH / "tickers_master_through_2026-09-08.csv"
OUT = FINAL / "out" / "indmom"
PARTS = OUT / "parts"
CACHE = OUT / "cache" / "indmom_factor.parquet"


def log(m):
    print(f"[{time.strftime('%H:%M:%S')}] {m}", flush=True)


def sha(p):
    return hashlib.sha256(Path(p).read_bytes()).hexdigest()


def load_labels(path=TM, strict=True):
    tm = pd.read_csv(path, dtype=str, usecols=["table", "ticker", "industry", "sector"])
    tm = tm[tm["table"] == "stocks"].drop(columns=["table"])
    if not strict:                                   # descriptive snapshot comparison only
        tm = tm.drop_duplicates("ticker", keep="last")
    assert tm["ticker"].is_unique, "tickers_master stocks rows not unique per ticker"
    return tm.set_index("ticker")


def build_factor(P, labels):
    """P: DataFrame ticker, date, momentum_12_1 (the cap2000 population rows on the grid).
    Returns DataFrame aligned with P: ind_mom_12_1, level (0 industry, 1 sector, 2 NaN), group_n."""
    ind = P["ticker"].map(labels["industry"])
    sec = P["ticker"].map(labels["sector"])
    m = P["momentum_12_1"].astype(np.float64)
    fin = np.isfinite(m.to_numpy())
    mm = m.where(fin)
    # industry groups (members = finite momentum, non-missing industry)
    ind_ok = fin & ind.notna().to_numpy()
    ki = pd.Series(np.where(ind_ok, ind.fillna(""), None), index=P.index)
    gi = mm.where(ind_ok).groupby([P["date"], ki])
    ind_n = gi.transform("count")
    ind_mean = gi.transform("mean")
    # sector groups (full cap2000 sector population, finite momentum)
    sec_ok = fin & sec.notna().to_numpy()
    ks = pd.Series(np.where(sec_ok, sec.fillna(""), None), index=P.index)
    gs = mm.where(sec_ok).groupby([P["date"], ks])
    sec_n = gs.transform("count")
    sec_mean = gs.transform("mean")
    use_i = ind_ok & (ind_n.fillna(0).to_numpy() >= MIN_N)
    use_s = ~use_i & sec_ok & (sec_n.fillna(0).to_numpy() >= MIN_N)
    val = np.where(use_i, ind_mean.to_numpy(np.float64), np.where(use_s, sec_mean.to_numpy(np.float64), np.nan))
    val[~fin] = np.nan                                         # non-members get no value
    lvl = np.where(use_i, 0, np.where(use_s, 1, 2)).astype(np.int8)
    lvl[~fin] = 2
    gn = np.where(use_i, ind_n.to_numpy(np.float64), np.where(use_s, sec_n.to_numpy(np.float64), np.nan))
    return pd.DataFrame({COL: val, "level": lvl, "group_n": gn}, index=P.index)


def load_population():
    sys.path.insert(0, str(SRC / "signcheck"))
    import signcheck  # noqa: F401  (sets sys.path for the harness modules, as in dropcheck)
    import model_audit_wo23 as MA
    import trailfilter as TF
    MA.SEAS_EXT = TF.SEAS_EXT_RO
    U, all_dates, spy = MA.load_theo("A", "cap2000")
    assert U["date"].max() < HOLDOUT and max(pd.Timestamp(d) for d in all_dates) < HOLDOUT, "HOLD-OUT BREACH"
    return U[["ticker", "date", "momentum_12_1", "sector"]].copy()


def main():
    T0 = time.time()
    PARTS.mkdir(parents=True, exist_ok=True)
    CACHE.parent.mkdir(parents=True, exist_ok=True)
    P = load_population()
    labels = load_labels()
    F = build_factor(P, labels)
    P = pd.concat([P, F], axis=1)
    ind = P["ticker"].map(labels["industry"]); sec = P["ticker"].map(labels["sector"])
    fin = np.isfinite(P["momentum_12_1"].to_numpy(np.float64))
    # descriptive sanity numbers vs the pre-reg (outcome-free)
    ind_n_all = ind.groupby([P["date"], ind]).transform("size")
    tick = P["ticker"].unique()
    old = load_labels(TM_OLD, strict=False); new = labels
    common = old.index.intersection(new.index)
    chg = (old.loc[common, "industry"].fillna("") != new.loc[common, "industry"].fillna("")).mean()
    desc = {
        "cap2000_rows": int(len(P)), "cap2000_tickers": int(len(tick)),
        "tickers_in_master": int(pd.Index(tick).isin(labels.index).sum()),
        "industry_missing_row_share": float(ind.isna().mean()),
        "sector_missing_row_share": float(sec.isna().mean()),
        "panel_vs_master_sector_agree": float((P["sector"].astype(str) == sec.astype(str))[P["sector"].notna() & sec.notna()].mean()),
        "rows_in_industry_group_lt5_all_rows": float((ind_n_all < MIN_N).fillna(True).mean()),
        "finite_mom_share": float(fin.mean()),
        "level_share_finite_mom": {k: float((P.loc[fin, "level"] == v).mean()) for k, v in (("industry", 0), ("sector", 1), ("nan", 2))},
        "factor_finite_share": float(np.isfinite(P[COL]).mean()),
        "label_change_share_between_snapshots": float(chg), "n_common_tickers_snapshots": int(len(common)),
        "median_group_n_industry": float(P.loc[P["level"] == 0, "group_n"].median()),
        "n_dates": int(P["date"].nunique()), "date_min": str(P["date"].min().date()), "date_max": str(P["date"].max().date()),
    }
    assert P["date"].max() < HOLDOUT
    out = P[["ticker", "date", "momentum_12_1", COL, "level", "group_n"]]
    out.to_parquet(CACHE, index=False)
    rep = {"work_order": "WO-50", "prereg_sha256": PREREG_SHA, "tickers_master_sha256": sha(TM),
           "cache": str(CACHE.relative_to(FINAL)), "cache_sha256": sha(CACHE), "descriptive": desc,
           "runtime_s": time.time() - T0}
    (PARTS / "build.json").write_text(json.dumps(rep, indent=1, default=float))
    log(json.dumps(desc, default=float))


if __name__ == "__main__":
    main()
