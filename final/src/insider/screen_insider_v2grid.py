"""
WO-4 pre-registered screen: `ins_buyers_90` on the survivorship-safe v2
down-cap grid. Spec (frozen before this ran):
models/2026-09-24-insider-buyers-v2-grid.md. k = 4, bar |t| >= 2.50, sign +1.

Universes (nomination era 2007-01-02..2019-12-31, v2 eligible_cap150):
  primary   = column c (downcap_v2_readout.load_column("c"))
  secondary = column c rows whose ticker is NOT in the old 4,011-ticker grid
Gates (ALL must hold):
  1 pooled NW(39) Spearman IC t >= +2.50
  2 odd-year and even-year mean IC both > 0
  3 both-sides sector-demeaned IC t >= +1.0 (factor-only reported, not gated)
  4 0/40 grid-offset sign flips of the daily IC series
  5 max single-year share of sum(daily IC) <= 0.45
  6 icw9 (split-half OOS IC-shrinkage weights) decile_volq net 15bp, mean of
    40 offsets, > 80th pct of 20 within-date shuffles of ins_buyers_90
    (seeds 0..19, full refit per draw)

Harness reconciliation (hard assert, before any insider number): icw8 with
frozen PRODUCTION_WEIGHTS and the split-half OOS IC on column c cap150 must
reproduce out/reset2026/downcap_v2/readout.json to 1e-6.

Shared modules are imported, never edited. Output:
out/insider/insider_v2grid_screen_report.json
Usage: python3 screen_insider_v2grid.py [--null-draws 20]
"""
import argparse
import json
import sys
import time
from pathlib import Path

import numpy as np
import pandas as pd

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
sys.path.insert(0, str(HERE.parent / "reset2026"))
import composite as C              # noqa: E402
import downcap_v2_readout as DR    # noqa: E402
import ic_weighted_composite as ICW  # noqa: E402
import screen_insider as SI        # noqa: E402

MAIN = Path("/Users/ggraham/pipe_dream/final")
FEAT = MAIN / "out" / "insider" / "insider_features_v2grid.parquet"
READOUT = MAIN / "out" / "reset2026" / "downcap_v2" / "readout.json"
OUT_JSON = MAIN / "out" / "insider" / "insider_v2grid_screen_report.json"
LABEL = "forward_return_tradable_40"
COL = "ins_buyers_90"
SIGN = +1
T_BAR = 2.50
SECTOR_T_BAR = 1.0
YEAR_SHARE_MAX = 0.45
HOLDOUT = pd.Timestamp("2020-01-01")
FC8 = list(ICW.PRODUCTION_WEIGHTS)
SIGNS8 = {c: C.FACTOR_SIGNS[c] for c in FC8}
SIGNS9 = {**SIGNS8, COL: SIGN}


def log(m):
    print(f"[{time.strftime('%H:%M:%S')}] {m}", flush=True)


def nw(x):
    return SI.newey_west_mean_t(np.asarray(x))


# ---------------------------------------------------------------- IC gates 1-5
def ic_gates(U, xcol=COL):
    s = SI.daily_corr(U, xcol, LABEL)
    yrs = s.index.year
    r = {"pooled": {**nw(s.to_numpy()), "n_dates": int(len(s))},
         "odd": nw(s[yrs % 2 == 1].to_numpy()), "even": nw(s[yrs % 2 == 0].to_numpy())}
    # gate 3: sector demeaning
    sec = U["sector"].fillna("Unknown")
    key = [U["date"], sec]
    V = U[["date"]].copy()
    V["x_sn"] = U[xcol] - U.groupby(key)[xcol].transform("mean")
    lab = U[LABEL].where(U[xcol].notna())      # demean the label on rows the IC uses
    V["y_sn"] = lab - lab.groupby(key).transform("mean")
    V[LABEL] = U[LABEL]
    r["sector_both_sides"] = nw(SI.daily_corr(V, "x_sn", "y_sn").to_numpy())
    r["sector_factor_only"] = nw(SI.daily_corr(V, "x_sn", LABEL).to_numpy())
    r["unknown_sector_share"] = float((sec == "Unknown").mean())
    # gate 4: 40 grid offsets on the sorted daily IC series
    pooled_sign = np.sign(r["pooled"]["mean"])
    offs = [float(s.iloc[o::SI.HORIZON].mean()) for o in range(SI.HORIZON)]
    r["offsets"] = {"means": offs, "min": min(offs), "max": max(offs),
                    "sign_flips": int(sum(np.sign(m) != pooled_sign for m in offs))}
    # gate 5: year shares and leave-one-year-out
    tot = float(s.sum())
    by_year = s.groupby(yrs).sum()
    shares = {int(y): float(v / tot) for y, v in by_year.items()} if tot != 0 else {}
    r["year_share"] = {"total_sum_ic": tot, "shares": shares,
                       "max_share": max(shares.values()) if shares else np.nan,
                       "max_year": max(shares, key=shares.get) if shares else None}
    r["loyo_t"] = {int(y): nw(s[yrs != y].to_numpy())["t"] for y in sorted(set(yrs))}
    g = {
        "g1_pooled_t": bool(r["pooled"]["t"] >= T_BAR),
        "g2_both_halves_positive": bool(r["odd"]["mean"] > 0 and r["even"]["mean"] > 0),
        "g3_sector_both_sides_t": bool(r["sector_both_sides"]["t"] >= SECTOR_T_BAR),
        "g4_zero_offset_flips": bool(r["offsets"]["sign_flips"] == 0),
        "g5_year_share": bool(tot > 0 and r["year_share"]["max_share"] <= YEAR_SHARE_MAX),
    }
    return r, g


# ---------------------------------------------------------------- books
def add_ranks(U, cols):
    for c in cols:
        U[f"rz_{c}"] = SI.rank_z(U, c)


def fit_t(U, cols, mask):
    sub = U.loc[mask, ["date", LABEL] + list(cols)]
    return {c: nw(SI.daily_corr(sub, c, LABEL).to_numpy())["t"] for c in cols}


def oos_score(U, weights_by_half, odd_mask):
    """weights_by_half = (w fit on odd -> scores even rows, w fit on even -> scores odd rows)."""
    w_odd, w_even = weights_by_half
    s_even = SI.composite_score(U, w_odd)
    s_odd = SI.composite_score(U, w_even)
    return s_even.where(~odd_mask, s_odd)


class Book:
    """Per-date slices of a universe for pick_decile_volq + readout backtest."""

    def __init__(self, U, all_dates, spy):
        self.all_dates, self.spy = all_dates, spy
        d = U["date"].to_numpy()
        starts = np.flatnonzero(np.r_[True, d[1:] != d[:-1]])
        ends = np.r_[starts[1:], len(d)]
        self.sl = [(pd.Timestamp(d[s]), s, e) for s, e in zip(starts, ends)]
        self.vol = U["volatility_60"].to_numpy(np.float64)
        self.tick = U["ticker"].to_numpy()
        self.ret = U["gross_return_40"].to_numpy(np.float64)

    def picks(self, score):
        score = np.asarray(score, dtype=np.float64)
        out = {}
        for d, s, e in self.sl:
            if e - s < C.N_VOL_QUINTILES * 4:
                continue
            g = pd.DataFrame({"volatility_60": self.vol[s:e]})
            sc = pd.DataFrame({"ticker": self.tick[s:e], "composite": score[s:e]})
            pk = C.pick_decile_volq(g, sc)
            ret = dict(zip(self.tick[s:e], self.ret[s:e]))
            pk = [(t, w) for t, w in pk if pd.notna(ret.get(t))]
            if not pk:
                continue
            ws = sum(w for _, w in pk)
            gross = sum((w / ws) * (1.0 + ret[t]) for t, w in pk) - 1.0
            out[d] = (gross, {t for t, _ in pk})
        return out

    def run(self, score):
        return DR.backtest(self.picks(score), self.all_dates, self.spy)


def shuffle_within_date(U, col, seed):
    """Uniform within-date permutation of the finite values of `col` (U is
    sorted by date, ticker), seeded numpy default_rng(seed)."""
    rng = np.random.default_rng(seed)
    v = U[col].to_numpy(np.float64)
    idx = np.flatnonzero(np.isfinite(v))
    dcode = pd.factorize(U["date"])[0][idx]
    order = np.lexsort((rng.random(len(idx)), dcode))
    assert np.all(np.diff(dcode[order]) >= 0)
    out = v.copy()
    out[idx] = v[idx][order]
    return out


def gate6(U, book, null_draws, tag):
    yrs = U["date"].dt.year.to_numpy()
    odd = pd.Series(yrs % 2 == 1, index=U.index)
    t8 = {"odd": fit_t(U, FC8, odd), "even": fit_t(U, FC8, ~odd)}
    w8 = (ICW.fit_weights({k: {"t": v} for k, v in t8["odd"].items()}, FC8),
          ICW.fit_weights({k: {"t": v} for k, v in t8["even"].items()}, FC8))
    for h, w in zip(("odd", "even"), w8):   # screen_insider rule == ICW rule, 8 factors
        w_si = SI.fit_weights(t8[h], SIGNS8)
        assert all(abs(w_si[k] - w[k]) < 1e-12 for k in FC8)
    s8 = oos_score(U, w8, odd)
    common = s8.notna()
    r = {"rows": int(len(U)), "rows_dropped_icw8_nan": int((~common).sum()),
         "weights8_fit_odd": w8[0], "weights8_fit_even": w8[1]}

    def icw9(col_values):
        U["_ins"] = col_values
        U[f"rz_{COL}"] = SI.rank_z(U, "_ins")
        slim = pd.DataFrame({"date": U["date"], "_ins": U["_ins"], LABEL: U[LABEL]})
        tin = {"odd": nw(SI.daily_corr(slim[odd], "_ins", LABEL).to_numpy())["t"],
               "even": nw(SI.daily_corr(slim[~odd], "_ins", LABEL).to_numpy())["t"]}
        w9 = (SI.fit_weights({**t8["odd"], COL: tin["odd"]}, SIGNS9),
              SI.fit_weights({**t8["even"], COL: tin["even"]}, SIGNS9))
        s9 = oos_score(U, w9, odd).where(common)
        return s9, tin, w9

    r["icw8"] = book.run(s8.to_numpy())
    s9, tin, w9 = icw9(U[COL].to_numpy(np.float64))
    r["icw9"] = book.run(s9.to_numpy())
    r["ins_t_fit_odd"], r["ins_t_fit_even"] = tin["odd"], tin["even"]
    r["ins_weight_fit_odd"], r["ins_weight_fit_even"] = w9[0][COL], w9[1][COL]
    for k, sc in (("icw9_oos_ic", s9), ("icw8_oos_ic", s8)):
        r[k] = nw(SI.daily_corr(pd.DataFrame({"date": U["date"], "_s": sc, LABEL: U[LABEL]}), "_s", LABEL).to_numpy())
    log(f"[{tag}] icw8 {r['icw8']['excess_cagr_vs_spy_mean40']:+.5f}  icw9 {r['icw9']['excess_cagr_vs_spy_mean40']:+.5f}  "
        f"ins t fit-odd {tin['odd']:+.2f} fit-even {tin['even']:+.2f}  w {w9[0][COL]:+.4f}/{w9[1][COL]:+.4f}")
    nulls, null_w = [], []
    for seed in range(null_draws):
        s9n, tn, wn = icw9(shuffle_within_date(U, COL, seed))
        nulls.append(book.run(s9n.to_numpy())["excess_cagr_vs_spy_mean40"])
        null_w.append([wn[0][COL], wn[1][COL]])
        log(f"[{tag}] null {seed}: {nulls[-1]:+.5f} (ins t {tn['odd']:+.2f}/{tn['even']:+.2f})")
    nulls = np.array(nulls)
    real = r["icw9"]["excess_cagr_vs_spy_mean40"]
    base = r["icw8"]["excess_cagr_vs_spy_mean40"]
    r["null"] = {"draws": nulls.tolist(), "ins_weights": null_w, "p50": float(np.percentile(nulls, 50)),
                 "p80": float(np.percentile(nulls, 80)), "mean": float(nulls.mean()), "sd": float(nulls.std()),
                 "percentile_of_real": float((nulls < real).mean())}
    r["icw9_minus_icw8"] = real - base
    r["null_minus_icw8_p50"] = r["null"]["p50"] - base
    r["null_minus_icw8_p80"] = r["null"]["p80"] - base
    r["g6_beats_null_p80"] = bool(real > r["null"]["p80"])
    U.drop(columns=["_ins"], inplace=True)
    return r


# ---------------------------------------------------------------- reconciliation
def reconcile(U, book, ref):
    yrs = U["date"].dt.year.to_numpy()
    s_frozen = SI.composite_score(U, ICW.PRODUCTION_WEIGHTS)
    dates = [x for x, _, _ in book.sl]
    for d in dates[:: max(1, len(dates) // 12)]:
        g = U[U["date"] == d].reset_index(drop=True)
        ref_s = ICW.compute_weighted_score(g, ICW.PRODUCTION_WEIGHTS, FC8).to_numpy()
        assert np.allclose(ref_s, s_frozen[U["date"] == d].to_numpy(), equal_nan=True, atol=1e-12), d
    bt = book.run(s_frozen.to_numpy())
    got = bt["excess_cagr_vs_spy_mean40"]
    want = ref["icw8"]["excess_cagr_vs_spy_mean40"]
    assert abs(got - want) < 1e-6, f"RECONCILE FAIL decile {got} vs {want}"
    odd = pd.Series(yrs % 2 == 1, index=U.index)
    out = {"decile_icw8_frozen": [got, want]}
    for name, fit, test in (("oos_fit_odd_test_even", odd, ~odd), ("oos_fit_even_test_odd", ~odd, odd)):
        t = fit_t(U, FC8, fit)
        w = ICW.fit_weights({k: {"t": v} for k, v in t.items()}, FC8)
        sub = U[test].copy()
        sub["_s"] = SI.composite_score(sub, w)
        ic = nw(SI.daily_corr(sub, "_s", LABEL).to_numpy())["mean"]
        want = ref["ic"][name]["mean"]
        assert abs(ic - want) < 1e-6, f"RECONCILE FAIL IC {name} {ic} vs {want}"
        out[name] = [ic, want]
    log(f"harness reconcile OK: {out}")
    return out


# ---------------------------------------------------------------- main
def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--null-draws", type=int, default=20)
    args = ap.parse_args()
    t0 = time.time()
    rep = {"spec": "models/2026-09-24-insider-buyers-v2-grid.md", "k": 4, "t_bar": T_BAR, "sign": SIGN,
           "column": COL, "label": LABEL, "null_draws": args.null_draws}

    p, spy = DR.load_column("c")
    all_dates = sorted(p["date"].unique())
    p = p[p["eligible_cap150"]].drop(columns=["eligible_cap500", "eligible_cap2000"])
    sec = pd.read_parquet(DR.R26 / "composite_panel_v2.parquet", columns=["ticker", "date", "sector"],
                          filters=[("date", ">=", "2007-01-02"), ("date", "<=", "2019-12-31")])
    sec["date"] = pd.to_datetime(sec["date"]); sec["ticker"] = sec["ticker"].astype(str)
    ins = pd.read_parquet(FEAT)
    ins["date"] = pd.to_datetime(ins["date"]); ins["ticker"] = ins["ticker"].astype(str)
    n = len(p)
    p = p.merge(sec, on=["ticker", "date"], how="left").merge(ins, on=["ticker", "date"], how="left")
    assert len(p) == n, "merge changed row count"
    assert p["date"].max() < HOLDOUT and spy.index.max() < HOLDOUT, "HOLD-OUT BREACH"
    del sec, ins
    old_t = set(pd.read_parquet(DR.R26 / "composite_panel.parquet", columns=["ticker"])["ticker"].astype(str).unique())
    p["added"] = ~p["ticker"].isin(old_t)
    p = p.sort_values(["date", "ticker"]).reset_index(drop=True)
    log(f"column c cap150: {len(p):,} rows ({p['added'].sum():,} added), {p['ticker'].nunique():,} tickers, "
        f"{COL} non-null {p[COL].notna().mean():.4%}, fire {(p[COL] > 0).mean():.4f}")

    ref = json.loads(READOUT.read_text())["columns"]["c"]["cap150"]
    for name, U in (("primary", p), ("secondary_added", p[p["added"]].reset_index(drop=True))):
        U = U.copy()
        add_ranks(U, FC8)
        book = Book(U, all_dates, spy)
        res = {"rows": int(len(U)), "tickers": int(U["ticker"].nunique()),
               "nonnull": float(U[COL].notna().mean()), "fire_rate": float((U[COL] > 0).mean())}
        if name == "primary":
            res["harness_reconcile"] = reconcile(U, book, ref)
        ic, g = ic_gates(U)
        res["ic"] = ic
        log(f"[{name}] IC {ic['pooled']['mean']:+.5f} t {ic['pooled']['t']:+.2f} | odd {ic['odd']['mean']:+.5f} "
            f"(t {ic['odd']['t']:+.2f}) even {ic['even']['mean']:+.5f} (t {ic['even']['t']:+.2f}) | "
            f"sector both {ic['sector_both_sides']['t']:+.2f} factor-only {ic['sector_factor_only']['t']:+.2f} | "
            f"offset flips {ic['offsets']['sign_flips']}/40 | max year share {ic['year_share']['max_share']} "
            f"({ic['year_share']['max_year']})")
        res["portfolio"] = gate6(U, book, args.null_draws, name)
        g["g6_beats_null_p80"] = res["portfolio"]["g6_beats_null_p80"]
        res["gates"] = g
        res["verdict"] = "PASS" if all(g.values()) else "KILL"
        log(f"[{name}] gates {g} -> {res['verdict']}")
        rep[name] = res
        OUT_JSON.write_text(json.dumps(rep, indent=2, default=float))
        del U, book
    log(f"wrote {OUT_JSON} ({time.time()-t0:.0f}s)")


if __name__ == "__main__":
    main()
