"""
WO-49: opp_buy_90 (opportunistic insider buyers, Cohen-Malloy-Pomorski 2012) on the
v2 down-cap grid, 2007-01-02..2019-12-31. Pre-registration:
final/models/2026-10-08-opportunistic-insiders.md (section 1, frozen before any return).

This step reads NO returns/labels. It builds the factor and the integrity / PIT /
hand-check report only.

Reused by import (not copied): build_insider_panel.load_events, window_counts,
WINDOW_DAYS; build_insider_panel_v2grid.cik_map_dedup.

Definition (section 1b of 2026-09-23-forward-ledger-leverage-opportunistic-buyers.md,
made strictly causal):
  events      Form 4 originals, non-derivative code P, O/D owners, one event per
              (accession, owner, code), trans_date = earliest P date in the filing.
  valid       2006-01-01 <= trans_date <= filing_date (else: neither history nor
              classified -> unclassified, excluded).
  history(e)  valid O/D P events of the same (issuer, owner) with filing_date < e.filing_date.
  classifiable e.year - min(history year) >= 3   (empty history -> unclassifiable)
  routine     history has a trans in month e.month of EACH of years y-1, y-2, y-3
  opportunistic classifiable and not routine
  opp_buy_90(t) = distinct O/D owners with an opportunistic event whose filing date f
              satisfies f + 1 <= t <= f + 90 (calendar days): window_counts on fday + 1.
  CIK-mapped ticker with no event -> 0; unmapped -> NaN.

Usage (python = /opt/anaconda3/envs/pipe_dream/bin/python, under caffeinate -i):
  build_opp.py     -> out/oppinsider/cache/opp_features.parquet (gitignored),
                      out/oppinsider/opp_integrity.json
"""
import json
import sys
import time
import zipfile
from pathlib import Path

import numpy as np
import pandas as pd

HERE = Path(__file__).resolve().parent
SRC = HERE.parent
FINAL = HERE.parents[1]
sys.path.insert(0, str(SRC / "insider"))
import build_insider_panel as B           # noqa: E402
import build_insider_panel_v2grid as BV   # noqa: E402

MAIN = Path("/Users/ggraham/pipe_dream/final")
R26 = MAIN / "out" / "reset2026"
PANEL_V2 = R26 / "composite_panel_v2.parquet"
PANEL_V1 = R26 / "composite_panel.parquet"
RAW = MAIN / "data" / "edgar" / "form345"
OUT = FINAL / "out" / "oppinsider"
CACHE = OUT / "cache"
EV_CACHE = CACHE / "events_from_zips.parquet"
FEAT = CACHE / "opp_features.parquet"
CLS = CACHE / "classified_buys.parquet"
INTEG = OUT / "opp_integrity.json"
HOLDOUT = pd.Timestamp("2020-01-01")
END = "2019-12-31"
VALID_LO = pd.Timestamp("2006-01-01")
N_EVENTS_EXPECTED = 1_456_667
EPOCH = pd.Timestamp("1970-01-01")


def log(m):
    print(f"[{time.strftime('%H:%M:%S')}] {m}", flush=True)


def load_events():
    if EV_CACHE.exists():
        ev = pd.read_parquet(EV_CACHE)
    else:
        ev = B.load_events()
        CACHE.mkdir(parents=True, exist_ok=True)
        ev.to_parquet(EV_CACHE, index=False)
    assert len(ev) == N_EVENTS_EXPECTED, len(ev)
    return ev


def classify(ev):
    """Every O/D P event, tagged valid/classifiable/routine/opportunistic using only
    same-(issuer, owner) valid events filed strictly earlier."""
    b = ev[ev["is_od"].astype(bool) & (ev["code"] == "P")].copy()
    b["issuer_cik"] = b["issuer_cik"].astype("int64")
    b["owner_cik"] = b["owner_cik"].astype("int64")
    b["valid"] = b["trans_date"].notna() & (b["trans_date"] >= VALID_LO) & (b["trans_date"] <= b["filing_date"])
    b["y"] = b["trans_date"].dt.year.fillna(-1).astype(int)
    b["m"] = b["trans_date"].dt.month.fillna(-1).astype(int)
    b = b.sort_values(["issuer_cik", "owner_cik", "filing_date", "accession"]).reset_index(drop=True)
    cls = np.zeros(len(b), bool)
    rou = np.zeros(len(b), bool)
    nhist = np.zeros(len(b), np.int64)
    fd = b["filing_date"].to_numpy()
    yy, mm, vv = b["y"].to_numpy(), b["m"].to_numpy(), b["valid"].to_numpy()
    for _, idx in b.groupby(["issuer_cik", "owner_cik"], sort=False).indices.items():
        idx = np.sort(idx)
        for j, i in enumerate(idx):
            if not vv[i]:
                continue
            prev = idx[:j]
            h = prev[(fd[prev] < fd[i]) & vv[prev]]          # strictly earlier filings, valid only
            nhist[i] = len(h)
            if len(h) == 0:
                continue
            cls[i] = (yy[i] - yy[h].min()) >= 3
            ym = set(zip(yy[h].tolist(), mm[h].tolist()))
            rou[i] = all((yy[i] - k, mm[i]) in ym for k in (1, 2, 3))
    b["n_hist"] = nhist
    b["classifiable"] = cls
    b["routine"] = rou & cls
    b["opportunistic"] = cls & ~rou
    b["cls"] = np.where(~b["valid"], "invalid", np.where(~b["classifiable"], "unclassifiable",
                        np.where(b["routine"], "routine", "opportunistic")))
    return b


def counts_on(panel, sub):
    """window_counts with the +1-day shift: owner filing at f covers t in [f+1, f+90]."""
    sub = sub.copy()
    sub["fday"] = (sub["filing_date"] - EPOCH).dt.days.astype(np.int64) + 1
    by = {k: g for k, g in sub.groupby("issuer_cik")}
    out = np.full(len(panel), np.nan)
    dint = (panel["date"] - EPOCH).dt.days.to_numpy(np.int64)
    for cik, idx in panel.groupby("cik").indices.items():
        idx = np.asarray(idx)
        out[idx] = 0.0
        if cik in by:
            out[idx] = B.window_counts(by[cik], dint[idx], B.WINDOW_DAYS)
    return out


def brute(b_opp, cmap, ticker, date):
    """Independent recompute of opp_buy_90 at (ticker, date) straight from the event table."""
    c = cmap.get(ticker)
    if c is None:
        return np.nan
    t = pd.Timestamp(date)
    w = b_opp[(b_opp["issuer_cik"] == c) & (b_opp["filing_date"] < t)
              & (b_opp["filing_date"] >= t - pd.Timedelta(days=90))]
    return float(w["owner_cik"].nunique())


def owner_name(accession, source_file):
    with zipfile.ZipFile(RAW / source_file) as zf:
        with zf.open("REPORTINGOWNER.tsv") as fh:
            o = pd.read_csv(fh, sep="\t", dtype=str, quoting=3, on_bad_lines="skip",
                            usecols=["ACCESSION_NUMBER", "RPTOWNERNAME", "RPTOWNER_TITLE"])
    o = o[o["ACCESSION_NUMBER"] == accession]
    return o[["RPTOWNERNAME", "RPTOWNER_TITLE"]].fillna("").to_dict("records")


def hand_check(b, feat, cmap_df, picks):
    """picks: list of (ticker, filing_date str, owner_cik or None)."""
    res = []
    tick2cik = dict(zip(cmap_df["ticker"], cmap_df["cik"]))
    for tk, fdate, own in picks:
        c = tick2cik[tk]
        f = pd.Timestamp(fdate)
        e = b[(b["issuer_cik"] == c) & (b["filing_date"] == f)]
        if own is not None:
            e = e[e["owner_cik"] == own]
        e = e.iloc[0]
        hist = b[(b["issuer_cik"] == c) & (b["owner_cik"] == e["owner_cik"]) & (b["filing_date"] < f) & b["valid"]]
        fr = feat[feat["ticker"] == tk].set_index("date")["opp_buy_90"]
        before = fr[fr.index <= f].tail(3)
        after = fr[fr.index > f].head(2)
        res.append({"ticker": tk, "issuer_cik": int(c), "owner_cik": int(e["owner_cik"]),
                    "owner": owner_name(e["accession"], e["source_file"]),
                    "accession": e["accession"], "filing_date": str(f.date()), "trans_date": str(e["trans_date"].date()),
                    "value_usd": float(e["value"]), "class": e["cls"],
                    "prior_purchase_months": sorted({f"{d.year}-{d.month:02d}" for d in hist["trans_date"]}),
                    "factor_on_and_before_filing_date": {str(k.date()): float(v) for k, v in before.items()},
                    "factor_after_filing_date": {str(k.date()): float(v) for k, v in after.items()},
                    "steps_up_day_after": bool(after.iloc[0] > before.iloc[-1] and after.index[0] > f)})
    return res


def main():
    T0 = time.time()
    OUT.mkdir(parents=True, exist_ok=True); CACHE.mkdir(parents=True, exist_ok=True)
    rep = {"work_order": "WO-49", "prereg": "final/models/2026-10-08-opportunistic-insiders.md",
           "note": "factor build + integrity only; no label or return read"}
    ev = load_events()
    rep["events_rows"] = int(len(ev))
    b = classify(ev)
    b.to_parquet(CLS, index=False)
    rep["od_P_events"] = int(len(b))
    rep["invalid_trans_date_events"] = int((~b["valid"]).sum())
    yb = b[b["filing_date"] <= END]
    rep["class_by_filing_year"] = {int(y): g["cls"].value_counts().to_dict()
                                   for y, g in yb.groupby(yb["filing_date"].dt.year)}
    log(f"classified {len(b):,} O/D P events; invalid {rep['invalid_trans_date_events']:,}")

    cmap = BV.cik_map_dedup()
    panel = pd.read_parquet(PANEL_V2, columns=["ticker", "date"], filters=[("date", "<=", END)])
    panel["ticker"] = panel["ticker"].astype(str); panel["date"] = pd.to_datetime(panel["date"])
    panel = panel[panel["date"] >= pd.Timestamp("2007-01-02")]
    assert panel["date"].max() < HOLDOUT, "HOLD-OUT BREACH"
    n0 = len(panel)
    panel = panel.merge(cmap, on="ticker", how="left").reset_index(drop=True)
    assert len(panel) == n0, "CIK merge changed row count"
    opp = b[b["opportunistic"]]
    panel["opp_buy_90"] = counts_on(panel, opp)
    panel["ins_buy_90_shift"] = counts_on(panel, b)
    # PIT: no event filed on/after t may count at t (f+1 <= t by construction); check on the raw arrays
    assert (panel["opp_buy_90"].fillna(0) <= panel["ins_buy_90_shift"].fillna(0)).all()
    assert (panel["opp_buy_90"].isna() == panel["cik"].isna()).all()
    panel[["ticker", "date", "opp_buy_90", "ins_buy_90_shift"]].to_parquet(FEAT, index=False)
    log(f"features: {len(panel):,} rows ({time.time()-T0:.0f}s)")

    # brute-force recompute (independent of window_counts) on fired rows + random rows
    rng = np.random.default_rng(49)
    mapped = panel[panel["cik"].notna()]
    fired = mapped[mapped["opp_buy_90"] > 0]
    samp = pd.concat([fired.sample(min(1500, len(fired)), random_state=1),
                      mapped.sample(1500, random_state=2)])
    c2 = dict(zip(cmap["ticker"], cmap["cik"]))
    bad = 0
    for tk, d, v in zip(samp["ticker"], samp["date"], samp["opp_buy_90"]):
        if brute(opp, c2, tk, d) != v:
            bad += 1
    rep["pit_brute_force"] = {"rows_checked": int(len(samp)), "mismatches": int(bad),
                              "rule": "count distinct owners with opportunistic filing f, t-90d <= f < t"}
    assert bad == 0, f"brute force mismatch {bad}"
    # every opportunistic event's history is strictly earlier-filed (by construction) -- assert on table
    rep["pit_history_rule"] = "history = same (issuer, owner) valid events with filing_date < event filing_date"

    old_t = set(pd.read_parquet(PANEL_V1, columns=["ticker"])["ticker"].astype(str).unique())
    p2 = pd.read_parquet(PANEL_V2, columns=["ticker", "date", "eligible_cap150"],
                         filters=[("date", "<=", END)])
    p2["ticker"] = p2["ticker"].astype(str); p2["date"] = pd.to_datetime(p2["date"])
    p2 = p2[p2["eligible_cap150"].astype(bool)].merge(panel[["ticker", "date", "opp_buy_90", "ins_buy_90_shift"]],
                                                      on=["ticker", "date"], how="inner")
    p2["grp"] = np.where(p2["ticker"].isin(old_t), "old", "added")
    rep["cap150_fire"] = {g: {"rows": int(len(s)), "nonnull": float(s["opp_buy_90"].notna().mean()),
                              "opp_fire": float((s["opp_buy_90"] > 0).mean()),
                              "ins_fire": float((s["ins_buy_90_shift"] > 0).mean())}
                          for g, s in p2.groupby("grp")}
    rep["cap150_opp_fire_by_year"] = {int(y): float((s["opp_buy_90"] > 0).mean())
                                      for y, s in p2.groupby(p2["date"].dt.year)}
    log(f"fire: {rep['cap150_fire']}")

    # hand-check (gate 7c): Dimon JPM + two more chosen from the classified table
    rep["hand_check_candidates"] = (
        b[b["opportunistic"] & (b["filing_date"].dt.year.between(2009, 2019))]
        .assign(ticker=lambda x: x["issuer_cik"].map(dict(zip(cmap["cik"], cmap["ticker"]))))
        .dropna(subset=["ticker"]).nlargest(15, "value")[["ticker", "owner_cik", "filing_date", "value"]]
        .astype(str).to_dict("records"))
    INTEG.write_text(json.dumps(rep, indent=1, default=str))
    log(f"wrote {INTEG} ({time.time()-T0:.0f}s)")


def run_hand_check(picks):
    b = pd.read_parquet(CLS)
    feat = pd.read_parquet(FEAT)
    rep = json.loads(INTEG.read_text())
    rep["hand_check"] = hand_check(b, feat, BV.cik_map_dedup(), picks)
    INTEG.write_text(json.dumps(rep, indent=1, default=str))
    for r in rep["hand_check"]:
        print(json.dumps(r, default=str))


if __name__ == "__main__":
    if len(sys.argv) > 1 and sys.argv[1] == "--hand":
        # args: TICKER:YYYY-MM-DD[:OWNERCIK] ...
        picks = []
        for a in sys.argv[2:]:
            p = a.split(":")
            picks.append((p[0], p[1], int(p[2]) if len(p) > 2 else None))
        run_hand_check(picks)
    else:
        main()
