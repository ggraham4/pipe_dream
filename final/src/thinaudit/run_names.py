"""
WO-61 Part 1, checks 3 (name checks) and 4 (label basis) on the WO-58 Stage-1 base book (133 dates).
Plan: final/models/2026-10-10-thinbook-audit.md.   caffeinate -i $PY run_names.py
Per-row CRSP values go only to final/data/wrds/crsp/derived/ (parquet, never committed).
Research code only; never trades.
"""
from __future__ import annotations

import numpy as np
import pandas as pd

import ta_common as A
import ta_frame as F
import common as K

B, log = A.B, A.log
DERIVED = K.DERIVED


def validate_crsp_impl(n=20000, seed=20261061):
    """My crsp_labels == WO-51's stored r_C on a random sample of its icw8 cap150 pick rows (2008-2018)."""
    w = pd.read_parquet(DERIVED / "phase3_pickrows.parquet",
                        columns=["date", "ticker", "wn", "r_S", "permno", "r_C", "r_C_ret", "fallback"])
    w["date"] = pd.to_datetime(w.date).astype("datetime64[ns]")
    w = w[(w.date >= A.ERA[0]) & (w.date <= A.ERA[1])]
    s = w.sample(n=n, random_state=seed).sort_values(["date", "ticker"]).reset_index(drop=True)
    perms = sorted({int(x) for x in s.permno.dropna()})
    cal, dsf, dl = F.crsp_inputs(perms)
    mine = F.crsp_labels(s[["date", "ticker", "wn", "r_S", "permno"]], cal, dsf, dl)
    d = np.abs(mine.r_C.to_numpy() - s.r_C.to_numpy())
    dt = np.abs(mine.r_C_ret.to_numpy() - s.r_C_ret.to_numpy())
    res = {"n": n, "fallback_flags_equal": bool((mine.fallback.to_numpy() == s.fallback.to_numpy()).all()),
           "max_abs_diff_r_C": float(np.nanmax(d)), "max_abs_diff_r_C_ret": float(np.nanmax(dt)),
           "nan_mismatch": int((np.isnan(mine.r_C.to_numpy()) != np.isnan(s.r_C.to_numpy())).sum())}
    res["pass"] = bool(res["fallback_flags_equal"] and res["max_abs_diff_r_C"] <= 1e-9 and res["nan_mismatch"] == 0)
    return res


def main():
    A.guard_inputs()
    val = validate_crsp_impl()
    log(f"CRSP label re-implementation vs WO-51: {val}")
    assert val["pass"], "CRSP label re-implementation does not match WO-51"

    b, D, uniq, dates, base, var, info = F.wo58_frame()
    ev_b, _ = B.evaluate(D, base)
    lvl_S = B.level(ev_b)
    assert abs(lvl_S - A.WO58_BASE) < 1e-12, lvl_S
    pr = F.pick_rows(D, uniq, base, b)
    o = pd.read_parquet(A.OUTCOME_V2, columns=["ticker", "date", "truncated"],
                        filters=[("date", "in", [d.to_pydatetime() for d in dates])])
    o["ticker"] = o.ticker.astype(str); o["date"] = pd.to_datetime(o.date).astype("datetime64[ns]")
    pr = pr.merge(o, on=["ticker", "date"], how="left")
    pr = F.attach_permno(pr)
    cal, dsf, dl = F.crsp_inputs(sorted({int(x) for x in pr.permno.dropna()}))
    pr = F.crsp_labels(pr, cal, dsf, dl)
    assert pr.x.max() <= np.datetime64(A.READ_CAP)

    # offset weights: row contribution to the annualised gross level
    kd = sorted(pr.date.unique())
    off_of = {d: k % 2 for k, d in enumerate(kd)}
    n_off = [sum(1 for d in kd if off_of[d] == o_) for o_ in (0, 1)]
    pr["off"] = pr.date.map(off_of)
    pr["scale"] = A.ANN / pr.off.map(lambda o_: n_off[o_]) / 2.0
    ndates = len(kd)

    # ---------------- check 4
    nf = ~pr.fallback
    agree = (np.abs(pr.r_S - pr.r_C) <= 0.001)[nf]
    S_net, S_g, _ = F.evaluate_with(D, base, pr, "r_S")
    C_net, C_g, _ = F.evaluate_with(D, base, pr, "r_C")
    Ct_net, _, _ = F.evaluate_with(D, base, pr, "r_C_ret")
    assert abs(S_net - lvl_S) < 1e-12
    fbw = pr.groupby("fb_reason").wn.sum() / ndates
    c4 = {"label_definition": "outcome_cache_v2.gross_return_40 = close[t+40]/open[t+1] - 1 with the delisting floor "
                              "(cb_core.attach_labels reads exactly this column)",
          "crsp_impl_validation": val,
          "pick_rows": int(len(pr)), "mapped_share_count": float(pr.permno.notna().mean()),
          "mapped_share_weight": float(pr.wn[pr.permno.notna()].sum() / ndates),
          "fallback_share_count": float(pr.fallback.mean()),
          "fallback_weight_share_by_reason": {k: float(v) for k, v in fbw.items() if k},
          "within_10bp_share_nonfallback": float(agree.mean()),
          "book_S_net": S_net, "book_C_retx_net": C_net, "book_C_ret_net_not_judged": Ct_net,
          "delta_S_minus_C_retx": S_net - C_net, "delta_S_minus_C_ret_not_judged": S_net - Ct_net,
          "gross_S": S_g, "gross_C": C_g}
    c4["pass"] = bool(c4["within_10bp_share_nonfallback"] >= 0.98 and abs(c4["delta_S_minus_C_retx"]) <= 0.005)
    log(f"check4: within10bp {c4['within_10bp_share_nonfallback']:.4f} S-C {100 * c4['delta_S_minus_C_retx']:+.3f}pp "
        f"-> {'PASS' if c4['pass'] else 'FAIL'}")
    A.dump("check4_labels.json", c4)

    # ---------------- check 3
    pr["cS"] = pr.wn * pr.r_S * pr.scale
    pr["cC"] = pr.wn * pr.r_C * pr.scale
    sp = pd.read_parquet(A.SPINFIX, columns=["ticker", "date", "label_fix"])
    sp["ticker"] = sp.ticker.astype(str); sp["date"] = pd.to_datetime(sp.date).astype("datetime64[ns]")
    pr = pr.merge(sp, on=["ticker", "date"], how="left")
    xw = K.crosswalk()
    nperm = xw.groupby(xw.ticker.astype(str)).permno.nunique()
    tm = pd.read_csv(A.MAIN / "data" / "sharadar" / "tickers_master.csv", dtype=str,
                     usecols=["ticker", "isdelisted", "name"]).drop_duplicates("ticker").set_index("ticker")
    agg = pr.groupby("ticker").agg(n_rows=("wn", "size"), contrib_S=("cS", "sum"), contrib_C=("cC", "sum"),
                                   n_fallback=("fallback", "sum"), n_spin=("label_fix", lambda s: int(s.notna().sum())),
                                   max_abs_gap=("r_S", lambda s: 0.0))
    gap = (pr.r_S - pr.r_C).abs().groupby(pr.ticker).max()
    agg["max_abs_gap"] = gap
    top = agg.sort_values("contrib_S", ascending=False).head(10)
    names = []
    for t, r in top.iterrows():
        rows = pr[pr.ticker == t]
        perms = sorted({int(x) for x in rows.permno.dropna()})
        ratio = r.contrib_C / r.contrib_S if r.contrib_S else np.nan
        spin_bad = bool(((rows.label_fix.notna()) & ((rows.r_S - rows.r_C).abs() > 0.02)).any())
        real = bool(np.isfinite(ratio) and abs(ratio - 1) <= 0.25 and not spin_bad and r.n_fallback < r.n_rows)
        best = rows.sort_values("cS", ascending=False).head(3)
        names.append({"ticker": t, "name": tm.name.get(t), "isdelisted": tm.isdelisted.get(t),
                      "n_pick_rows": int(r.n_rows), "contrib_S_pp": 100 * r.contrib_S, "contrib_C_pp": 100 * r.contrib_C,
                      "ratio_C_over_S": ratio, "n_fallback_rows": int(r.n_fallback), "n_spinfix_rows": int(r.n_spin),
                      "permnos_used": perms, "crosswalk_permnos_for_ticker": int(nperm.get(t, 0)),
                      "ticker_reuse_suffix": bool(t[-1].isdigit()),
                      "max_abs_label_gap_S_C": float(r.max_abs_gap),
                      "entry_price_min_max": [float(rows.closeunadj.min()), float(rows.closeunadj.max())],
                      "top_rows": [{"date": str(pd.Timestamp(x.date).date()), "wn": float(x.wn), "r_S": float(x.r_S),
                                    "r_C": float(x.r_C), "fallback": bool(x.fallback)} for x in best.itertuples()],
                      "real": real})
    tot_S = float(pr.cS.sum())
    trunc = pr[pr.truncated.fillna(False).astype(bool)]
    tnf = trunc[~trunc.fallback]
    later = pr.ticker.map(tm.isdelisted).eq("Y")
    pr["r_fix"] = pr.label_fix.where(pr.label_fix.notna(), pr.r_S)
    fix_net, _, _ = F.evaluate_with(D, base, pr, "r_fix")
    c3 = {"gross_level_sum_of_contribs": tot_S, "top10": names,
          "top10_share_of_gross": float(sum(n["contrib_S_pp"] for n in names) / 100 / tot_S),
          "delisting_path": {"n_rows": int(len(trunc)), "weight_share": float(trunc.wn.sum() / ndates),
                             "mean_r_S": float(trunc.r_S.mean()), "mean_r_C_nonfallback": float(tnf.r_C.mean()),
                             "mean_r_S_nonfallback": float(tnf.r_S.mean()), "n_nonfallback": int(len(tnf)),
                             "abs_gap_nonfallback": float(abs(tnf.r_S.mean() - tnf.r_C.mean())),
                             "delist_applied_rows": int(pr.delist_applied.sum())},
          "later_delisted_names_DESCRIPTIVE": {"share_rows": float(later.mean()),
                                                "weight_share": float(pr.wn[later].sum() / ndates),
                                                "mean_r_S": float(pr.r_S[later].mean()),
                                                "mean_r_S_others": float(pr.r_S[~later].mean())},
          "price_lt_5_at_entry": {"share_rows": float((pr.closeunadj < 5).mean()),
                                  "weight_share": float(pr.wn[pr.closeunadj < 5].sum() / ndates),
                                  "mean_r_S": float(pr.r_S[pr.closeunadj < 5].mean())},
          "spinfix": {"rows_hit": int(pr.label_fix.notna().sum()), "book_fixed_net": fix_net,
                      "delta_fixed_minus_S": fix_net - S_net},
          "seas_nan_pick_share": float(pr.seas_nan.mean())}
    c3["pass"] = bool(all(n["real"] for n in names) and
                      (len(tnf) == 0 or c3["delisting_path"]["abs_gap_nonfallback"] <= 0.02) and
                      c3["spinfix"]["delta_fixed_minus_S"] >= -0.0025)
    log(f"check3: top10 real {[n['real'] for n in names]} delist gap {c3['delisting_path']['abs_gap_nonfallback']:.4f} "
        f"spin delta {100 * c3['spinfix']['delta_fixed_minus_S']:+.3f}pp -> {'PASS' if c3['pass'] else 'FAIL'}")
    A.dump("check3_names.json", c3)
    keep = ["date", "ticker", "permno", "wn", "r_S", "r_C", "r_C_ret", "fallback", "fb_reason", "truncated",
            "closeunadj", "e", "x", "label_fix", "cS", "cC"]
    pr[keep].to_parquet(DERIVED / "thinaudit_wo61_base_pickrows.parquet", index=False)


if __name__ == "__main__":
    main()
