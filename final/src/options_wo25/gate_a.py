"""
WO-25 Gate A: rebuild the unified AV chain + option features into WO-25's own
out dir and run the named, return-free checks A1..A10.
Spec: final/models/2026-09-29-options-readiness-wo25.md section 2.

    /opt/anaconda3/envs/pipe_dream/bin/python final/src/options_wo25/gate_a.py [--dates 2008-01-02,...]

Imports build_option_chain_unified.py / build_av_options_features.py (never
edits them) and never writes under final/data/. Outputs (final/out/options_wo25/):
  chain/source=av_monthly/date=*.parquet    unified-chain rows (gitignored)
  features_cache/date=*.parquet             per-date features (gitignored)
  av_options_features_wo25.parquet          concatenated features (gitignored)
  gate_a_report.json                        A1..A10, pass/fail with numbers

No statistic here relates an option quantity to a forward return. A10 checks the
label FORMULA and reports a match rate only; no label value is printed or saved.
"""
from __future__ import annotations

import argparse
import json
import os
import sqlite3
import sys
import time
from pathlib import Path

import numpy as np
import pandas as pd

HERE = Path(__file__).resolve().parent
SRC = HERE.parent
sys.path.insert(0, str(SRC))
import build_option_chain_unified as U   # noqa: E402
import build_av_options_features as F    # noqa: E402
sys.path.insert(0, str(HERE))
from wo25_io import read_on_dates             # noqa: E402

MAIN = Path("/Users/ggraham/pipe_dream/final")
DATA = MAIN / "data"
AV = DATA / "alphavantage"
OUT = HERE.parents[1] / "out" / "options_wo25"
CHAIN = OUT / "chain" / "source=av_monthly"
FCACHE = OUT / "features_cache"
FEATS = OUT / "av_options_features_wo25.parquet"
REPORT = OUT / "gate_a_report.json"
UNIVERSE = DATA / "sharadar" / "downcap_universe_v2.parquet"
PANEL_V2 = MAIN / "out" / "reset2026" / "composite_panel_v2.parquet"
SEP = DATA / "sharadar" / "panel" / "stocks"
H = 40


def log(m):
    print(f"[{time.strftime('%H:%M:%S')}] {m}", flush=True)


# ------------------------------------------------------------------ build
def read_log():
    return pd.read_sql("SELECT pass, date, ticker, status, symbol, identity, spot_parity, closeunadj FROM calls",
                       sqlite3.connect(f"file:{AV / 'pull_log.sqlite'}?mode=ro", uri=True))


def build_chain(dates, plog):
    rates = U.load_rates(DATA)
    for d in dates:
        src = AV / "options" / "monthly" / f"date={d.date()}.parquet"
        dst = CHAIN / f"date={d.date()}.parquet"
        if not U.newer(src, dst):
            continue
        keep = U.av_keep(plog[(plog["pass"] == "monthly") & (plog.date == str(d.date()))])
        df = U.convert_av(src, d, U.rate_on(rates, d), keep)
        U.write_atomic(df, dst)
        log(f"chain {d.date()}: {len(df):,} rows, {df.sharadar_ticker.nunique()} names, IV solved {df.vol.notna().mean():.0%}")


def build_features(dates):
    FCACHE.mkdir(parents=True, exist_ok=True)
    for d in dates:
        src = CHAIN / f"date={d.date()}.parquet"
        dst = FCACHE / src.name
        if dst.exists() and dst.stat().st_mtime >= src.stat().st_mtime:
            continue
        f = F.partition_features(src)
        f["source"] = "av_monthly"
        tmp = dst.with_suffix(".tmp"); f.to_parquet(tmp, index=False); os.replace(tmp, dst)
        log(f"features {d.date()}: {len(f)} names")
    parts = [FCACHE / f"date={d.date()}.parquet" for d in dates]
    X = pd.concat([pd.read_parquet(p) for p in parts], ignore_index=True)
    sv = F.share_volume_20d(SEP, X.date.unique())
    X = X.merge(sv, on=["date", "ticker"], how="left")
    X["opt_os_ratio"] = 100 * X._opt_volume / X.shares_vol_20d
    X = X.drop(columns=["_opt_volume", "shares_vol_20d"])
    X.to_parquet(FEATS, index=False)
    log(f"features: {len(X):,} name-dates, {X.date.nunique()} dates -> {FEATS}")
    return X


# ------------------------------------------------------------------ checks
def label_basis_check(dates, n_sample=400, seed=0):
    """A10: forward_return_tradable_40 == close[t+40]/open[t+1] - 1 on each
    ticker's OWN trading days in SEP. Returns match counts only."""
    p = read_on_dates(PANEL_V2, ["ticker", "date", "forward_return_tradable_40", "eligible_cap2000"], dates)
    p = p[p.eligible_cap2000 & p.forward_return_tradable_40.notna()]
    s = p.sample(min(n_sample, len(p)), random_state=seed)
    tick = set(s.ticker.astype(str))
    months = pd.period_range(min(dates), max(dates) + pd.Timedelta(days=120), freq="M")
    sep = pd.concat([pd.read_parquet(SEP / f"{m}.parquet", columns=["ticker", "date", "open", "close"],
                                     filters=[("ticker", "in", list(tick))])
                     for m in months if (SEP / f"{m}.parquet").exists()])
    sep["date"] = pd.to_datetime(sep.date)
    sep = sep.sort_values(["ticker", "date"])
    by = {t: g.reset_index(drop=True) for t, g in sep.groupby("ticker")}
    match = mism = unres = 0
    for r in s.itertuples():
        g = by.get(str(r.ticker))
        if g is None:
            unres += 1; continue
        i = np.searchsorted(g.date.to_numpy(), np.datetime64(pd.Timestamp(r.date)))
        if i >= len(g) or g.date.iloc[i] != pd.Timestamp(r.date) or i + H >= len(g):
            unres += 1; continue
        v = g.close.iloc[i + H] / g.open.iloc[i + 1] - 1
        alt = g.close.iloc[i + H] / g.close.iloc[i] - 1
        if np.isclose(v, r.forward_return_tradable_40, rtol=1e-4, atol=1e-6):
            match += 1
        else:
            mism += 1
            if np.isclose(alt, r.forward_return_tradable_40, rtol=1e-4, atol=1e-6):
                mism_alt = True  # noqa: F841 (close-to-close would be a basis error)
    n = match + mism
    return {"sampled": int(len(s)), "resolved": int(n), "unresolved": int(unres),
            "match": int(match), "mismatch": int(mism),
            "match_rate": float(match / n) if n else float("nan")}


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--dates", default="", help="comma list; default = every monthly parquet on disk")
    a = ap.parse_args()
    OUT.mkdir(parents=True, exist_ok=True); CHAIN.mkdir(parents=True, exist_ok=True)
    t0 = time.time()
    srcs = sorted((AV / "options" / "monthly").glob("date=*.parquet"))
    dates = [pd.Timestamp(s.stem.split("=")[1]) for s in srcs]
    if a.dates:
        want = {pd.Timestamp(x) for x in a.dates.split(",")}
        dates = [d for d in dates if d in want]
    plog = read_log()
    build_chain(dates, plog)
    X = build_features(dates)
    X["date"] = pd.to_datetime(X.date)

    rep, checks = {"dates": [str(d.date()) for d in dates], "n_dates": len(dates)}, {}

    def put(cid, name, ok, **nums):
        checks[cid] = {"check": name, "pass": bool(ok), **nums}
        log(f"  {'PASS' if ok else 'FAIL'} {cid} {name} {json.dumps(nums, default=str)[:300]}")

    have = set(zip(X.date, X.ticker))
    # A1 AAPL on every 2008 date
    d08 = [d for d in dates if d.year == 2008]
    got = [d for d in d08 if (d, "AAPL") in have]
    put("A1", "AAPL present on every 2008 date", len(d08) > 0 and len(got) == len(d08),
        dates_2008=len(d08), aapl_present=len(got), missing=[str(d.date()) for d in d08 if d not in got])

    # A2 + A3 failed banks, identity via pull_log parity
    L = plog[plog["pass"] == "monthly"].copy()
    L["err"] = (L.spot_parity / L.closeunadj - 1).abs()
    named = [("LEHMQ", "LEH", "2008-08-20"), ("WAMUQ", "WM", "2008-08-20"), ("WB1", "WB", "2008-08-20"),
             ("WAMUQ", "WM", "2008-09-17"), ("WB1", "WB", "2008-09-17")]
    a2, a3 = {}, {}
    uni_named = read_on_dates(UNIVERSE, ["date", "ticker", "marketcap", "closeunadj", "eligible_cap2000", "eligible_cap150"],
                              sorted({pd.Timestamp(ds) for _, _, ds in named}))
    required_ok = True
    for tk, sym, ds in named:
        d = pd.Timestamp(ds)
        ur = uni_named[(uni_named.ticker == tk) & (uni_named.date == d)]
        el = {"eligible_cap2000": bool(ur.eligible_cap2000.iloc[0]) if len(ur) else None,
              "marketcap_musd": float(ur.marketcap.iloc[0]) if len(ur) else None,
              "closeunadj": float(ur.closeunadj.iloc[0]) if len(ur) else None}
        r = L[(L.ticker == tk) & (L.date == ds)]
        v = {"in_features": (d, tk) in have, "log_status": r.status.iloc[0] if len(r) else "not attempted",
             "av_symbol": r.symbol.iloc[0] if len(r) else None, **el}
        # REQUIRED: all three on 2008-08-20 (the pull covered cap150 then). Later dates: the pull
        # was cap2000-only, so a name below the cap2000 $10 price floor was never attempted.
        if ds == "2008-08-20":
            ok = v["in_features"] and v["av_symbol"] == sym
        else:
            ok = (v["in_features"] and v["av_symbol"] == sym) if el["eligible_cap2000"] else True
            if not el["eligible_cap2000"]:
                v["note"] = "not cap2000-eligible on this date (cap2000 = mcap>=$2B AND closeunadj>$10); pull was cap2000-only -> no chain; N/A"
        v["pass"] = bool(ok)
        required_ok &= bool(ok)
        a2[f"{tk}@{ds}"] = v
        if len(r) and r.status.iloc[0] == "ok":
            a3[f"{tk}@{ds}"] = {"av_symbol": r.symbol.iloc[0], "identity": r.identity.iloc[0],
                                "spot_parity": r.spot_parity.iloc[0], "closeunadj": r.closeunadj.iloc[0],
                                "abs_err": r.err.iloc[0]}
    put("A2", "LEH/WM/WB present on 2008-08-20 with expected AV symbols (09-17: only if cap2000-eligible)",
        required_ok, detail=a2)
    ok3 = len(a3) >= 3 and all(v["identity"] == "verified" and v["abs_err"] < U.STRICT_TOL for v in a3.values())
    put("A3", "identity: |parity spot / closeunadj - 1| < 5%", ok3, detail=a3)

    # A4 symbol reuse (WM / WMI), 2008-08..2009-01, and chain-level (date, symbol) uniqueness
    win = L[(L.date >= "2008-08-01") & (L.date <= "2009-01-31") & (L.status == "ok")]
    wm_rows = win[(win.ticker == "WM") | (win.symbol == "WM") | (win.symbol == "WMI")]
    wm_detail = wm_rows[["date", "ticker", "symbol", "spot_parity", "closeunadj"]].to_dict("records")
    bad = wm_rows[((wm_rows.ticker == "WM") & (wm_rows.symbol != "WMI")) |
                  ((wm_rows.symbol == "WM") & (wm_rows.ticker != "WAMUQ"))]
    # after av_keep, a (date, AV symbol) belongs to exactly one Sharadar ticker
    multi = 0
    for d in dates:
        c = pd.read_parquet(CHAIN / f"date={d.date()}.parquet", columns=["act_symbol", "sharadar_ticker"]).drop_duplicates()
        multi += int(c.act_symbol.duplicated().sum())
    # does the WAMUQ chain disappear after the 09-25 seizure while WM (Waste Mgmt) keeps WMI?
    put("A4", "no WM/WMI cross-assignment; one Sharadar ticker per (date, AV symbol) in chain",
        len(bad) == 0 and multi == 0, wm_rows=wm_detail, bad_rows=int(len(bad)), multi_claims=multi)

    # A5-A7 feature sanity (no returns)
    rr = X.opt_rr25.dropna()
    put("A5", "rr25 > 0 on most name-dates", (rr > 0).mean() > 0.5,
        share_pos=float((rr > 0).mean()), n=int(len(rr)),
        by_year={int(y): float((g > 0).mean()) for y, g in X.dropna(subset=["opt_rr25"]).groupby(X.date.dt.year).opt_rr25})
    pc = float(X.opt_pc_vol_ratio.median())
    put("A6", "pc_vol_ratio median in [0.30, 0.45]", 0.30 <= pc <= 0.45, median=pc,
        n=int(X.opt_pc_vol_ratio.notna().sum()))
    cw = float(X.opt_cw_spread.median())
    cw08 = float(X[X.date.dt.year == 2008].opt_cw_spread.median())
    put("A7", "cw_spread median slightly negative (builder: about -0.022 in 2008)", -0.06 < cw < 0,
        median_all=cw, median_2008=cw08, n=int(X.opt_cw_spread.notna().sum()))

    # A8-A9 coverage + spread by tier, only on dates where the tier was attempted
    u = read_on_dates(UNIVERSE, ["date", "ticker", "eligible_cap2000", "eligible_cap500", "eligible_cap150"], dates)
    u["date"] = pd.to_datetime(u.date)
    u["tier"] = np.where(u.eligible_cap2000, "cap2000",
                         np.where(u.eligible_cap500, "cap500_only", np.where(u.eligible_cap150, "cap150_only", None)))
    u = u[u.tier.notna()]
    att = L[L.status.isin(["ok", "no_data", "error"])][["date", "ticker"]].assign(attempted=True)
    att["date"] = pd.to_datetime(att.date)
    u = u.merge(att, on=["date", "ticker"], how="left")
    u["attempted"] = u.attempted.fillna(False).astype(bool)
    tier_att = u.groupby(["date", "tier"]).attempted.mean().unstack()
    u = u.merge(X[["date", "ticker", "opt_spread_atm", "opt_atm_iv"]].assign(chain=True), on=["date", "ticker"], how="left")
    u["chain"] = u.chain.fillna(False).astype(bool)
    cov = {}
    for tier, g in u.groupby("tier"):
        att_dates = [d for d in tier_att.index if tier_att.loc[d, tier] > 0.5]
        gg = g[g.date.isin(att_dates)]
        cov[tier] = {"dates_attempted": len(att_dates), "eligible_name_dates": int(len(gg)),
                     "share_with_chain": float(gg.chain.mean()) if len(gg) else None,
                     "share_with_chain_min_date": float(gg.groupby("date").chain.mean().min()) if len(gg) else None,
                     "median_atm_rel_spread": float(gg.opt_spread_atm.median()) if len(gg) else None,
                     "atm_iv_median": float(gg.opt_atm_iv.median()) if len(gg) else None}
    put("A8", "coverage by tier (tier attempted dates only)", cov["cap2000"]["share_with_chain"] > 0.8, tiers=cov)
    sp = [cov[t]["median_atm_rel_spread"] for t in ["cap2000", "cap500_only", "cap150_only"] if t in cov]
    put("A9", "median ATM relative spread rises as cap falls", all(np.diff([x for x in sp if x is not None]) > 0),
        by_tier={t: cov[t]["median_atm_rel_spread"] for t in cov})

    # A10 label basis
    lb = label_basis_check(dates)
    put("A10", "forward_return_tradable_40 == close[t+40]/open[t+1]-1 (own trading days)",
        lb["match_rate"] >= 0.99, **lb)

    # extra facts: adjusted-deliverable key duplicates, IV solve rate
    kd = {}
    for d in dates:
        c = pd.read_parquet(AV / "options" / "monthly" / f"date={d.date()}.parquet", columns=["sharadar_ticker", "contractID"])
        n = int(c.duplicated(["sharadar_ticker", "contractID"], keep=False).sum())
        if n:
            kd[str(d.date())] = n
    rep["key_duplicate_rows_by_date"] = kd
    rep["checks"] = checks
    rep["all_pass"] = all(c["pass"] for c in checks.values())
    rep["runtime_s"] = time.time() - t0
    REPORT.write_text(json.dumps(rep, indent=2, default=str))
    log(f"Gate A {'ALL PASS' if rep['all_pass'] else 'HAS FAILS'} -> {REPORT}")


if __name__ == "__main__":
    main()
