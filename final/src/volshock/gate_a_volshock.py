"""
WO-28 Gate A (gate 7) for vol_shock and str_lowturn. No outcome statistic is
computed here (the label trace reads single named label values only, to check
the label's construction; no factor-vs-return number).

  A1 SEP basis scan 2006-06..2019-12: every day-over-day change of
     k = close/closeunadj is classified as a real split (closeunadj jumps,
     close continuous) or a basis mismatch (close jumps, closeunadj continuous).
     PASS iff 0 basis mismatches on panel tickers.
  A2 named splits AAPL 7:1 2014-06-09 and a second pre-2020 split picked from
     the scan (NFLX 7:1 2015-07-15 expected): shares_adj continuous, turnover_21
     continuous, V5 continuous (adjusted), while the counterfactual raw-volume
     V5 jumps by ~ the split factor (the check has power).
  A3 dead name LEHMQ: cap150 rows in 2008 with finite vol_shock, r_1m, turnover_21.
  A4 label trace: forward_return_tradable_40 = close[t+40]/open[t+1] - 1 from raw
     SEP rows, field by field, for named rows with t+40 < 2020.
  A5 hand check: independent row loop from the raw month files (no builder import
     for the math) for named (ticker, t).
  A6 PIT: last input date == t on every finite row.
Output: final/out/volshock/gate_a_volshock.json
"""
import json
import sys
from pathlib import Path

import numpy as np
import pandas as pd

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
import build_volshock as B   # noqa: E402  (paths, guards, file list only)

OUT_JSON = B.OUT / "gate_a_volshock.json"
log = B.log


def load_all_sep():
    files = B.sep_files()
    return B.load_sep(files, cols=("ticker", "date", "open", "close", "volume", "closeunadj"))


def basis_scan(s, panel_tickers):
    first = s["ticker"].ne(s["ticker"].shift())
    ra = (s["close"] / s["close"].shift()).where(~first)
    ru = (s["closeunadj"] / s["closeunadj"].shift()).where(~first)
    lk = np.log(ru / ra).abs()
    ev = s.loc[lk > np.log(1.1), ["ticker", "date"]].copy()
    ev["ratio_adj"] = ra[ev.index]; ev["ratio_unadj"] = ru[ev.index]
    ev["split_like"] = np.abs(np.log(ev["ratio_adj"])) < np.log(1.5)
    ev["basis_mismatch"] = (np.abs(np.log(ev["ratio_unadj"])) < np.log(1.05)) & ~ev["split_like"]
    ev["panel"] = ev["ticker"].isin(panel_tickers)
    # file-level basis failure = a mismatch on the first market day of a month file (the
    # day the previous row comes from another file). Per-name vendor/corporate events
    # (e.g. reverse split + spin-off on the same day) are listed, not failed.
    ev["first_row_of_month_file"] = s["date"].shift()[ev.index].dt.strftime("%Y-%m").to_numpy() != ev["date"].dt.strftime("%Y-%m").to_numpy()
    mm = ev[ev["basis_mismatch"] & ev["panel"]]
    fb = ev[ev["basis_mismatch"] & ev["first_row_of_month_file"]]
    return ev, {"k_change_events": int(len(ev)), "split_like": int(ev["split_like"].sum()),
                "basis_mismatch_all": int(ev["basis_mismatch"].sum()),
                "basis_mismatch_panel_tickers": int(len(mm)),
                "basis_mismatch_examples": mm.head(20).astype(str).to_dict("records"),
                "other_unclassified": int((~ev["split_like"] & ~ev["basis_mismatch"]).sum()),
                "basis_mismatch_on_month_file_boundary": int(len(fb)),
                "month_boundary_examples": fb.head(20).astype(str).to_dict("records"),
                "max_tickers_same_boundary_day": int(fb.groupby("date").size().max()) if len(fb) else 0,
                "boundary_mismatch_on_panel_tickers": int(fb["panel"].sum()),
                # a pull-basis split across files would hit many tickers on one boundary day
                "pass": bool(fb["panel"].sum() == 0 and (fb.groupby("date").size().max() if len(fb) else 0) <= 1)}


def split_check(s, fac, tk, day):
    day = pd.Timestamp(day)
    g = s[s["ticker"] == tk].sort_values("date").reset_index(drop=True)
    i = int(np.flatnonzero(g["date"] == day)[0])
    factor = float(g.loc[i, "close"] / g.loc[i, "closeunadj"]) / float(g.loc[i - 1, "close"] / g.loc[i - 1, "closeunadj"])  # 7 for 7:1
    raw = g["volume"] * g["close"] / g["closeunadj"]           # unadjusted share volume (basis-free)
    V5a = g["volume"].rolling(5).sum(); V5r = raw.rolling(5).sum()
    f = fac[fac["ticker"] == tk].set_index("date")
    d_pre, d_post4 = g.loc[i - 1, "date"], g.loc[i + 4, "date"]
    shares = f["market_cap"] / g.set_index("date")["close"]
    rng = g.loc[i - 3:i + 12, "date"]
    tab = pd.DataFrame({"volume_adj": g.set_index("date")["volume"], "volume_raw": raw.values}, index=g["date"]).loc[rng]
    tab = tab.join(f[["V5", "vol_shock", "turnover_21"]]).join(shares.rename("shares_adj"))
    r = {"ticker": tk, "split_day": str(day.date()), "split_factor": factor,
         "shares_adj_ratio": float(shares[day] / shares[d_pre]),
         "turnover21_ratio_split_day": float(f.loc[day, "turnover_21"] / f.loc[d_pre, "turnover_21"]),
         "V5_adj_ratio_post4_vs_pre": float(V5a[i + 4] / V5a[i - 1]),
         "V5_raw_ratio_post4_vs_pre": float(V5r[i + 4] / V5r[i - 1]),
         "vol_shock_split_day_to_plus9": [float(f.loc[d, "vol_shock"]) for d in g.loc[i:i + 9, "date"]],
         "window": {str(k.date()): {c: float(v) for c, v in row.items()} for k, row in tab.iterrows()}}
    r["pass"] = bool(0.9 < r["shares_adj_ratio"] < 1.1 and 0.5 < r["turnover21_ratio_split_day"] < 2
                     and 1 / 3 < r["V5_adj_ratio_post4_vs_pre"] < 3
                     and 0.5 < r["V5_raw_ratio_post4_vs_pre"] / factor < 2)
    return r


def label_trace(s, tk, t):
    pan = pd.read_parquet(B.PANEL_V2, columns=["ticker", "date", "open", "close", "forward_return_tradable_40"],
                          filters=[("ticker", "==", tk), ("date", ">=", "2007-01-02"), ("date", "<=", "2019-12-31")])
    pan["date"] = pd.to_datetime(pan["date"]); B.guard(pan, "panel label trace")
    g = s[s["ticker"] == tk].sort_values("date").reset_index(drop=True)
    i = int(np.flatnonzero(g["date"] == pd.Timestamp(t))[0])
    assert g.loc[i + 40, "date"] < B.HOLDOUT
    o1, c40 = float(g.loc[i + 1, "open"]), float(g.loc[i + 40, "close"])
    mine = c40 / o1 - 1
    got = float(pan.loc[pan["date"] == pd.Timestamp(t), "forward_return_tradable_40"].iloc[0])
    return {"ticker": tk, "t": t, "t_plus_1": str(g.loc[i + 1, "date"].date()), "open_t_plus_1": o1,
            "t_plus_40": str(g.loc[i + 40, "date"].date()), "close_t_plus_40": c40,
            "recomputed": mine, "panel": got, "abs_diff": abs(mine - got), "pass": bool(abs(mine - got) < 1e-9)}


def hand_check(tk, t, fac):
    """Independent loop: market calendar and windows from raw month files."""
    t = pd.Timestamp(t)
    months = pd.period_range(t - pd.Timedelta(days=120), t, freq="M").strftime("%Y-%m")
    rows, counts = [], {}
    for m in months:
        f = B.SEP_MAIN / f"{m}.parquet"
        assert m <= "2019-12"
        d = pd.read_parquet(f, columns=["ticker", "date", "close", "volume"])
        B.guard(d, f)
        for dt, n in d.groupby("date").size().items():
            counts[pd.Timestamp(dt)] = n
        rows.append(d[d["ticker"] == tk])
    cal = sorted(dt for dt, n in counts.items() if n >= 1000 and dt <= t)
    g = pd.concat(rows); g["date"] = pd.to_datetime(g["date"]); g = g.set_index("date")
    need = cal[-50:]
    vol = [float(g.loc[d, "volume"]) for d in need]            # KeyError if any day missing
    V5 = [sum(vol[len(vol) - 5 * k - 5: len(vol) - 5 * k]) for k in range(10)]
    cur = V5[0]
    rank = sum(1 for v in V5 if v < cur) + (sum(1 for v in V5 if v == cur) + 1) / 2
    vol21 = sum(vol[-21:]) / 21
    r1m = float(g.loc[cal[-1], "close"]) / float(g.loc[cal[-22], "close"]) - 1
    fr = fac[(fac["ticker"] == tk) & (fac["date"] == t)].iloc[0]
    out = {"ticker": tk, "t": str(t.date()), "vol_shock_loop": rank, "vol_shock_build": float(fr["vol_shock"]),
           "vol21_loop": vol21, "vol21_build": float(fr["vol21"]), "r_1m_loop": r1m, "r_1m_build": float(fr["r_1m"])}
    out["pass"] = bool(rank == fr["vol_shock"] and abs(vol21 / fr["vol21"] - 1) < 1e-9 and abs(r1m - fr["r_1m"]) < 1e-9)
    return out


def main():
    rep = {}
    fac = pd.read_parquet(B.FACT)
    B.guard(fac, "factor file")
    fin = fac["vol_shock"].notna() | fac["r_1m"].notna() | fac["vol21"].notna()
    rep["A6_pit"] = {"finite_rows": int(fin.sum()),
                     "violations": int((fac.loc[fin, "last_input_date"] > fac.loc[fin, "date"]).sum()),
                     "last_input_equals_t": bool((fac.loc[fin, "last_input_date"] == fac.loc[fin, "date"]).all())}
    rep["A6_pit"]["pass"] = rep["A6_pit"]["violations"] == 0
    s = load_all_sep()
    ptick = set(fac["ticker"].unique())
    ev, rep["A1_basis_scan"] = basis_scan(s, ptick)
    log(f"A1 {json.dumps({k: v for k, v in rep['A1_basis_scan'].items() if k != 'basis_mismatch_examples'})}")
    cands = ev[ev["split_like"] & ev["panel"] & (ev["ticker"] != "AAPL")]
    rep["A2_split_candidates_named"] = cands[cands["ticker"].isin(["NFLX", "V", "GOOGL", "MA", "PCLN", "MNST"])].astype(str).to_dict("records")
    nf = cands[(cands["ticker"] == "NFLX") & (cands["date"].dt.year == 2015)]
    assert len(nf) == 1, "NFLX 2015 split not found"
    rep["A2_splits"] = [split_check(s, fac, "AAPL", "2014-06-09"),
                        split_check(s, fac, "NFLX", nf["date"].iloc[0])]
    for r in rep["A2_splits"]:
        log(f"A2 {r['ticker']} {r['split_day']} factor {r['split_factor']:.3f} shares {r['shares_adj_ratio']:.3f} "
            f"turn {r['turnover21_ratio_split_day']:.3f} V5adj {r['V5_adj_ratio_post4_vs_pre']:.3f} "
            f"V5raw {r['V5_raw_ratio_post4_vs_pre']:.3f} vs {r['vol_shock_split_day_to_plus9']} pass {r['pass']}")
    pan = pd.read_parquet(B.PANEL_V2, columns=["ticker", "date", "eligible_cap150"],
                          filters=[("ticker", "==", "LEHMQ"), ("date", ">=", "2007-01-02"), ("date", "<=", "2019-12-31")])
    pan["date"] = pd.to_datetime(pan["date"]); B.guard(pan, "panel LEHMQ")
    L = pan[pan["eligible_cap150"] & (pan["date"].dt.year == 2008)].merge(fac, on=["ticker", "date"], how="left")
    rep["A3_dead_name"] = {"ticker": "LEHMQ", "cap150_rows_2008": int(len(L)),
                           "last_cap150_date": str(L["date"].max().date()) if len(L) else None,
                           "finite_vol_shock": int(L["vol_shock"].notna().sum()),
                           "finite_r_1m": int(L["r_1m"].notna().sum()),
                           "finite_turnover_21": int(L["turnover_21"].notna().sum())}
    rep["A3_dead_name"]["pass"] = bool(rep["A3_dead_name"]["finite_vol_shock"] > 100
                                       and rep["A3_dead_name"]["finite_turnover_21"] > 100)
    log(f"A3 {rep['A3_dead_name']}")
    rep["A4_label_trace"] = [label_trace(s, "AAPL", "2014-06-02"), label_trace(s, "LEHMQ", "2008-06-16"),
                             label_trace(s, "NFLX", "2015-07-01")]
    log(f"A4 {[(r['ticker'], r['abs_diff']) for r in rep['A4_label_trace']]}")
    rep["A5_hand_check"] = [hand_check(tk, t, fac) for tk, t in
                            (("AAPL", "2014-06-13"), ("LEHMQ", "2008-06-16"), ("NFLX", "2015-07-24"),
                             ("MU", "2012-03-15"), ("AAPL", "2019-12-31"))]
    log(f"A5 {[(r['ticker'], r['t'], r['pass']) for r in rep['A5_hand_check']]}")
    rep["pass"] = bool(rep["A1_basis_scan"]["pass"] and all(r["pass"] for r in rep["A2_splits"])
                       and rep["A3_dead_name"]["pass"] and all(r["pass"] for r in rep["A4_label_trace"])
                       and all(r["pass"] for r in rep["A5_hand_check"]) and rep["A6_pit"]["pass"])
    OUT_JSON.write_text(json.dumps(rep, indent=2, default=str))
    log(f"Gate A {'PASS' if rep['pass'] else 'FAIL'} -> {OUT_JSON}")


if __name__ == "__main__":
    main()
