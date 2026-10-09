"""WO-54 Phase 1 (descriptive): spin-off ex-date events and the fixed 40-day labels.

Pre-registration: final/models/2026-10-09-spinoff-label-fix-prereg.md (hash asserted below).
Reads (read only): CRSP dsedist_3xxx / dsf_2007..2019 / crosswalk (main final/data/wrds), Sharadar OHLC CSVs up to
2019-12-31, main final/out/reset2026/outcome_cache_v2.parquet and composite_panel_v2.parquet (2007-2019 rows).
Writes:
  final/data/wrds/crsp/derived/spinfix_events.parquet   per event (CRSP values; never committed)
  final/data/wrds/crsp/derived/spinfix_labels.parquet   per affected (ticker, date): label, label_fix, m
  final/out/spinfix/phase1.json                         aggregates only
Usage: python events.py
"""
from __future__ import annotations

import hashlib
import json
import sys
import time
from pathlib import Path

import numpy as np
import pandas as pd

HERE = Path(__file__).resolve().parent
FINAL = HERE.parents[1]
sys.path.insert(0, str(HERE.parent / "wrds_crsp"))
import common as K  # noqa: E402

PREREG = FINAL / "models" / "2026-10-09-spinoff-label-fix-prereg.md"
PREREG_SHA = "1c1a22ae7f898d85b1cf85db2ca8bed5b14b2ac0dea2037432ca0e15bae29ccd"   # committed 09d829a
assert hashlib.sha256(PREREG.read_bytes()).hexdigest() == PREREG_SHA, "PRE-REG CHANGED SINCE FREEZE: STOP"

CUT = pd.Timestamp("2019-12-31")
THRESH = 0.02
H = 40
OUT = FINAL / "out" / "spinfix"
EVENTS_PQ = K.DERIVED / "spinfix_events.parquet"
LABELS_PQ = K.DERIVED / "spinfix_labels.parquet"
NAMED = [("SSP", "2008-07-01"), ("CY", "2008-09-30"), ("MO", "2008-03-31"), ("ITT", "2011-11-01"),
         ("STRZA", "2013-01-14"), ("PENN", "2013-11-04"), ("NI", "2015-07-02"), ("MTW", "2016-03-04"),
         ("SPXC", "2015-09-28")]


def log(m):
    print(f"[{time.strftime('%H:%M:%S')}] {m}", flush=True)


def grid_tickers():
    p = pd.read_parquet(K.R26 / "composite_panel_v2.parquet", columns=["ticker"],
                        filters=[("date", ">=", "2007-01-02"), ("date", "<=", "2019-12-31")])
    return set(p.ticker.astype(str).unique())


def build_events(grid):
    d = pd.read_parquet(K.CRSP_DIR / "dsedist_3xxx.parquet")
    d["exdt"] = pd.to_datetime(d.exdt).astype("datetime64[ns]")
    rep = {"dsedist_3xxx_rows_2007_2019": int((d.exdt <= CUT).sum())}
    late = d[(d.exdt > CUT) & (d.facpr > 0)]
    d = d[(d.exdt <= CUT) & (d.facpr > 0)]
    rep["candidate_rows_facpr_pos"] = int(len(d))
    rep["candidate_rows_by_distcd"] = {int(k): int(v) for k, v in d.distcd.value_counts().items()}
    ev = (d.groupby(["permno", "exdt"])
            .agg(n_rows=("distcd", "size"), distcds=("distcd", lambda s: ",".join(str(int(x)) for x in sorted(s))),
                 facpr_sum=("facpr", "sum"), divamt_sum=("divamt", "sum"),
                 acperms=("acperm", lambda s: ",".join(str(int(x)) for x in s if x and x > 0)))
            .reset_index())
    rep["events_permno_exdt"] = int(len(ev))
    xw = K.crosswalk()
    xw["valid_from"] = pd.to_datetime(xw.valid_from).astype("datetime64[ns]")
    xw["valid_to"] = pd.to_datetime(xw.valid_to).astype("datetime64[ns]")
    m = ev.merge(xw[["permno", "ticker", "valid_from", "valid_to", "match_quality"]], on="permno", how="left")
    m = m[(m.valid_from <= m.exdt) & (m.exdt <= m.valid_to)]
    ev = ev.merge(m[["permno", "exdt", "ticker", "match_quality"]], on=["permno", "exdt"], how="left")
    assert not ev.duplicated(["permno", "exdt"]).any(), "crosswalk gave two tickers for one permno-date"
    ev["status"] = np.where(ev.ticker.isna(), "unmapped",
                            np.where(~ev.ticker.isin(grid), "not_in_v2_grid", ""))
    # 2020Q1 metadata-only count (late-2019 windows would cross these; excluded, no 2020 return read)
    lm = late.merge(xw[["permno", "ticker", "valid_from", "valid_to"]], on="permno")
    lm = lm[(lm.valid_from <= lm.exdt) & (lm.exdt <= lm.valid_to) & lm.ticker.isin(grid)]
    rep["excluded_2020q1_grid_events"] = int(lm[["permno", "exdt"]].drop_duplicates().shape[0])
    return ev, rep


def crsp_side(ev):
    dsf = K.load_dsf(years=range(2007, 2020), cols=("permno", "date", "ret", "retx", "prc"),
                     permnos=ev.permno.unique(), cutoff=CUT)
    out = []
    for perm, g in dsf.groupby("permno", sort=False):
        g = g.reset_index(drop=True)
        dates = g.date.values
        for exdt in ev.loc[ev.permno == perm, "exdt"].values:
            k = np.searchsorted(dates, exdt)
            rec = {"permno": perm, "exdt": exdt}
            if k >= len(dates) or dates[k] != exdt:
                rec["crsp_status"] = "no_crsp_row_on_exdt"
            elif k == 0:
                rec["crsp_status"] = "no_crsp_prior_row"
            else:
                r, p0 = g.iloc[k], g.iloc[k - 1]
                rec.update(r_C=float(r.ret), r_Cx=float(r.retx), prc=float(r.prc), prc_prev=float(p0.prc),
                           crsp_prev_date=p0.date.to_datetime64(), crsp_after=bool(k + 1 < len(dates)))
                if not np.isfinite(r.ret):
                    rec["crsp_status"] = "ret_nan"
                elif not (r.prc > 0):
                    rec["crsp_status"] = "prc_bidask_or_missing_on_exdt"
                elif not (p0.prc > 0):
                    rec["crsp_status"] = "prc_bidask_or_missing_prev"
                elif not rec["crsp_after"]:
                    rec["crsp_status"] = "no_crsp_row_after_exdt_in_era"
                else:
                    rec["crsp_status"] = ""
                # +-3 day window of CRSP rets for the off-by-one report
                lo, hi = max(1, k - 3), min(len(dates) - 1, k + 3)
                rec["win"] = {pd.Timestamp(dates[j]): float(g.ret.iloc[j]) for j in range(lo, hi + 1)}
            out.append(rec)
    return pd.DataFrame(out), dsf


def main():
    t0 = time.time()
    OUT.mkdir(parents=True, exist_ok=True)
    K.DERIVED.mkdir(parents=True, exist_ok=True)
    grid = grid_tickers()
    ev, rep = build_events(grid)
    log(f"events {len(ev):,}; mapped to v2 grid {(ev.status == '').sum():,}")
    cs, dsf = crsp_side(ev[ev.status == ""])
    ev = ev.merge(cs, on=["permno", "exdt"], how="left")
    ev.loc[(ev.status == "") & ev.crsp_status.isna(), "crsp_status"] = "no_crsp_rows"
    ev.loc[(ev.status == "") & (ev.crsp_status != ""), "status"] = ev.crsp_status
    ohlc = K.load_ohlc(sorted(ev.loc[ev.status == "", "ticker"].unique()), CUT)
    rows = []
    for i in np.flatnonzero((ev.status == "").to_numpy()):
        r = ev.iloc[i]
        g = ohlc.get(r.ticker)
        rec = {"idx": i}
        if g is None:
            rec["status"] = "no_sharadar_ohlc"
            rows.append(rec)
            continue
        dts = g.date.values.astype("datetime64[ns]")
        exd = np.datetime64(pd.Timestamp(r.exdt), "ns")
        k = np.searchsorted(dts, exd)
        if k >= len(dts) or dts[k] != exd or k == 0:
            rec["status"] = "no_sharadar_row_on_exdt"
        elif dts[k - 1] != np.datetime64(pd.Timestamp(r.crsp_prev_date), "ns"):
            rec["status"] = "sharadar_prev_row_not_crsp_prev_day"
        else:
            c = g.close.to_numpy(np.float64)
            rS = c[k] / c[k - 1] - 1
            mm = (1 + rS) / (1 + r.r_C)
            gaps = {}
            for j in range(max(1, k - 3), min(len(dts) - 1, k + 3) + 1):
                rc = r.win.get(pd.Timestamp(dts[j])) if isinstance(r.win, dict) else None
                if rc is not None and np.isfinite(rc) and c[j - 1] > 0:
                    gaps[j - k] = float(np.log((c[j] / c[j - 1]) / (1 + rc)))
            big = max(gaps, key=lambda q: abs(gaps[q])) if gaps else 0
            rec.update(status="", k=int(k), n_rows_to_cut=int(len(dts)), r_S=float(rS), m=float(mm),
                       log_m=float(np.log(mm)), applied=bool(abs(np.log(mm)) >= THRESH),
                       max_gap_offset=int(big), max_gap=float(gaps.get(big, np.nan)))
        rows.append(rec)
    sh = pd.DataFrame(rows).set_index("idx")
    for c in sh.columns:
        if c == "status":
            ev.loc[sh.index, "status"] = sh.status.where(sh.status != "", "")
        else:
            ev.loc[sh.index, c] = sh[c]
    ev["applied"] = ev["applied"].fillna(False).astype(bool)
    ev = ev.drop(columns=["win"])
    log(f"applied events {ev.applied.sum():,} ({time.time()-t0:.0f}s)")

    # ---------------- labels
    app = ev[ev.applied]
    tick = sorted(app.ticker.unique())
    oc = pd.read_parquet(K.R26 / "outcome_cache_v2.parquet", columns=["ticker", "date", "gross_return_40"],
                         filters=[("ticker", "in", tick), ("date", "<=", CUT)])
    oc["date"] = pd.to_datetime(oc.date).astype("datetime64[ns]")
    oc["ticker"] = oc.ticker.astype(str)
    lab = []
    for t, ge in app.groupby("ticker"):
        g = ohlc[t]
        dts = g.date.values
        mult = np.ones(len(dts))
        evid = [[] for _ in range(len(dts))]
        for e in ge.itertuples():
            kk = int(e.k)
            lo, hi = max(0, kk - H), kk - 2          # rows i with i+1 < k <= i+40
            if hi >= lo:
                mult[lo:hi + 1] *= e.m
                for i in range(lo, hi + 1):
                    evid[i].append(str(pd.Timestamp(e.exdt).date()))
        idx = np.flatnonzero(mult != 1.0)
        lab.append(pd.DataFrame({"ticker": t, "date": dts[idx], "m": mult[idx], "pos": idx,
                                 "events": [";".join(evid[i]) for i in idx]}))
    lab = pd.concat(lab, ignore_index=True)
    n0 = len(lab)
    lab = lab.merge(oc, on=["ticker", "date"], how="left")
    assert len(lab) == n0
    lab["label_fix"] = (1 + lab.gross_return_40.astype(np.float64)) / lab.m - 1
    # verify cache label == OHLC recompute (rows whose exit lies in-era), and hand-check fixed labels
    ver, hand = [], []
    rng = np.random.default_rng(54)
    for t, gl in lab.groupby("ticker"):
        g = ohlc[t]
        o, c = g.open.to_numpy(np.float64), g.close.to_numpy(np.float64)
        for r in gl.itertuples():
            je, jx = r.pos + 1, r.pos + H
            if jx < len(c) and np.isfinite(r.gross_return_40):
                ver.append(abs((c[jx] / o[je] - 1) - r.gross_return_40))
    lab_ok = lab[np.isfinite(lab.gross_return_40) & (lab.pos + H < lab.ticker.map(lambda t: len(ohlc[t])))]
    for j in rng.choice(len(lab_ok), size=min(10, len(lab_ok)), replace=False):
        r = lab_ok.iloc[j]
        g = ohlc[r.ticker]
        o, c = g.open.to_numpy(np.float64).copy(), g.close.to_numpy(np.float64).copy()
        for e in app[app.ticker == r.ticker].itertuples():   # pre-exdt prices x m (makes the exdt return = CRSP ret)
            o[:int(e.k)] *= e.m
            c[:int(e.k)] *= e.m
        hv = c[r.pos + H] / o[r.pos + 1] - 1
        hand.append({"ticker": r.ticker, "date": str(pd.Timestamp(r.date).date()), "label": float(r.gross_return_40),
                     "label_fix_vector": float(r.label_fix), "label_fix_hand": float(hv),
                     "eq_1e5": bool(abs(hv - r.label_fix) < 1e-5)})
    ver = np.array(ver)
    rep["cache_vs_ohlc_recompute"] = {"rows": int(len(ver)), "max_abs_diff": float(ver.max()) if len(ver) else None,
                                      "share_lt_1e5": float((ver < 1e-5).mean()) if len(ver) else None}
    rep["hand_check_fixed_labels"] = hand
    log(json.dumps(rep["cache_vs_ohlc_recompute"])); [log(str(h)) for h in hand if not h["eq_1e5"]]
    assert all(h["eq_1e5"] for h in hand), "hand check failed"

    # ---------------- shares among eligible name-dates
    p = pd.read_parquet(K.R26 / "composite_panel_v2.parquet", columns=["ticker", "date", "eligible_cap150", "eligible_cap2000"],
                        filters=[("date", ">=", "2007-01-02"), ("date", "<=", "2019-12-31")])
    p["date"] = pd.to_datetime(p.date).astype("datetime64[ns]")
    p["ticker"] = p.ticker.astype(str)
    p = p.merge(lab[["ticker", "date", "gross_return_40"]].assign(aff=True), on=["ticker", "date"], how="left")
    p["aff"] = p.aff.fillna(False).astype(bool) & np.isfinite(p.gross_return_40.astype(np.float64))
    for tier in ("cap150", "cap2000"):
        e = p[f"eligible_{tier}"].astype(bool)
        hit = lab.merge(p.loc[e & p.aff, ["ticker", "date"]], on=["ticker", "date"])
        evs = hit.assign(ev=hit.events.str.split(";")).explode("ev")[["ticker", "ev"]].drop_duplicates()
        rep[f"affected_{tier}"] = {"eligible_name_dates": int(e.sum()), "affected": int((e & p.aff).sum()),
                                   "share": float((e & p.aff).sum() / e.sum()), "events_touching": int(len(evs))}
    # ---------------- event summary
    st = ev.status.fillna("")
    rep["events_status"] = {(k or "ok"): int(v) for k, v in st.value_counts().items()}
    ok = ev[st == ""]
    rep["events_ok"] = int(len(ok))
    rep["events_applied"] = int(ok.applied.sum())
    rep["events_below_threshold"] = int((~ok.applied).sum())
    rep["events_applied_near_line_0p02_0p04"] = int((ok.applied & (ok.log_m.abs() < 0.04)).sum())
    rep["events_applied_match_quality_not_A"] = int((ok.applied & (ok.match_quality != "A")).sum())
    rep["applied_by_year"] = {int(k): int(v) for k, v in ok[ok.applied].exdt.dt.year.value_counts().sort_index().items()}
    rep["applied_by_distcds"] = {k: int(v) for k, v in ok[ok.applied].distcds.value_counts().head(15).items()}
    rep["ret_minus_retx_nonzero_events"] = int(((ok.r_C - ok.r_Cx).abs() > 1e-6).sum())
    rep["ret_minus_retx_nonzero_applied"] = int((ok.applied & ((ok.r_C - ok.r_Cx).abs() > 1e-6)).sum())
    single = ok[ok.applied & (ok.n_rows == 1)]
    dev = np.abs(np.log(single.m * (1 + single.facpr_sum)))
    rep["m_vs_facpr_single_row_applied"] = {"n": int(len(single)), "median_abs_log": float(dev.median()),
                                            "share_within_5pct": float((dev < 0.05).mean())}
    rep["off_by_one_applied_or_not"] = {"events_ok_largest_gap_not_on_exdt_and_gt_0p02": int(
        ((ok.max_gap_offset != 0) & (ok.max_gap.abs() >= THRESH)).sum())}
    rep["log_m_applied_quantiles"] = {str(q): float(ok[ok.applied].log_m.quantile(q)) for q in (0.05, 0.25, 0.5, 0.75, 0.95)}
    rep["affected_label_rows_all"] = int(len(lab))

    # ---------------- named cases
    cal = K.market_calendar(CUT)
    dsfN = K.load_dsf(years=range(2007, 2020), cols=("permno", "date", "ret", "retx", "prc", "openprc"),
                      permnos=ev[ev.ticker.isin([n[0] for n in NAMED])].permno.dropna().unique(), cutoff=CUT)
    named = []
    for tic, ds in NAMED:
        d0 = np.datetime64(ds, "ns")
        r = ev[(ev.ticker == tic) & (ev.exdt == d0)]
        rec = {"ticker": tic, "exdt": ds, "detected": bool(len(r)), "applied": bool(len(r) and r.applied.iloc[0])}
        if len(r):
            r = r.iloc[0]
            rec.update(permno=int(r.permno), distcds=r.distcds, status=r.status or "ok",
                       r_S=None if pd.isna(r.get("r_S")) else round(float(r.r_S), 5),
                       r_C=None if pd.isna(r.get("r_C")) else round(float(r.r_C), 5),
                       m=None if pd.isna(r.get("m")) else round(float(r.m), 5))
        if rec["applied"]:
            rS_fix = (1 + r.r_S) / r.m - 1
            rec["bar_b_exdate_abs_diff_bp"] = float(abs(rS_fix - r.r_C) * 1e4)
            ci = np.searchsorted(cal, d0) - 20
            t, e, x = cal[ci], cal[ci + 1], cal[ci + H]
            row = lab[(lab.ticker == tic) & (lab.date == t)]
            g = dsfN[dsfN.permno == r.permno]
            w = g[(g.date >= e) & (g.date <= x)]
            hv = abs(w.prc.iloc[0]) / w.openprc.iloc[0] * np.prod(1 + w.retx.iloc[1:].to_numpy()) - 1 \
                if len(w) and w.date.iloc[0] == e and w.date.iloc[-1] == x else np.nan
            rec.update(t=str(pd.Timestamp(t).date()), label_unfixed=None if row.empty else round(float(row.gross_return_40.iloc[0]), 5),
                       label_fixed=None if row.empty else round(float(row.label_fix.iloc[0]), 5),
                       crsp_hand_label_retx=None if not np.isfinite(hv) else round(float(hv), 5))
            rec["bar_c_gap_pp"] = None if (row.empty or not np.isfinite(hv)) else float(abs(row.label_fix.iloc[0] - hv) * 100)
            rec["corrected"] = bool(rec["bar_b_exdate_abs_diff_bp"] <= 1.0 and rec["bar_c_gap_pp"] is not None
                                    and rec["bar_c_gap_pp"] <= 2.0)
        else:
            rec["corrected"] = False
        named.append(rec)
    rep["named_cases"] = named
    rep["named_all_corrected"] = bool(all(n["corrected"] for n in named))
    # WO-51 pick-row cross-check (icw8 picks): rows hit by our fix vs r_C
    pk = pd.read_parquet(K.DERIVED / "phase3_pickrows.parquet", columns=["date", "ticker", "r_S", "r_C", "fallback"])
    pk["date"] = pd.to_datetime(pk.date).astype("datetime64[ns]")
    x = pk.merge(lab[["ticker", "date", "label_fix"]], on=["ticker", "date"])
    x = x[~x.fallback]
    rep["wo51_pickrow_crosscheck"] = {"rows": int(len(x)),
                                      "median_abs_rS_minus_rC_pp": float((x.r_S - x.r_C).abs().median() * 100) if len(x) else None,
                                      "median_abs_fix_minus_rC_pp": float((x.label_fix - x.r_C).abs().median() * 100) if len(x) else None,
                                      "share_fix_within_2pp_of_rC": float(((x.label_fix - x.r_C).abs() < 0.02).mean()) if len(x) else None}
    ev.to_parquet(EVENTS_PQ, index=False)
    lab.to_parquet(LABELS_PQ, index=False)
    (OUT / "phase1.json").write_text(json.dumps(rep, indent=1, default=str))
    log(f"done ({time.time()-t0:.0f}s): applied {rep['events_applied']}, label rows {len(lab):,}, "
        f"named corrected {sum(n['corrected'] for n in named)}/{len(named)}")


if __name__ == "__main__":
    main()
