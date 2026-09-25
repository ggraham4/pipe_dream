"""
Three backtest variants + one factor screen, testing specific findings from
`2026-09-22-composite-model-physics.md` -- see PREREGISTRATION.md's
"Correction-round pre-registration (2026-09-22, part 2)" section for the
full spec, written before this ran. `FACTOR_SIGNS` is not touched; every
variant is reported BESIDE the confirmed `cap150_raw`/`decile_volq` baseline
(already in `REPORT_nominate.md`, not rerun here), never in place of it.

Variants:
  decile1_volq          -- same construction, decile 1 instead of decile 9
  exclude_bottom_decile -- same construction, hold everything but decile 0
  asset_growth_dropped  -- confirmed composite minus asset_growth, decile_volq

Trial count: 3 backtest variants + 1 IC-only factor screen (book_to_market,
never backtested). cap150, raw, nomination era only (2007-2019), 15bp cost,
40 grid offsets, 50 matched nulls/cell (halved from the package's usual 100
as a runtime concession -- the null is a sanity floor here, not a formal
significance claim, per the pre-registration).

Usage: python3 correction_variants.py
Output: out/reset2026/correction_variants_report.json
"""
import json
import sys
import time
from pathlib import Path

import numpy as np
import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parent))
import composite as C          # noqa: E402
import run_backtest as RB       # noqa: E402

MAIN_ROOT = Path("/Users/ggraham/pipe_dream/final")
OUT_DIR = MAIN_ROOT / "out" / "reset2026"
SF1 = MAIN_ROOT / "data" / "sharadar" / "sf1_fundamentals.parquet"
COMPOSITE_PANEL = OUT_DIR / "composite_panel.parquet"
OUT_JSON = OUT_DIR / "correction_variants_report.json"

TIER = "cap150"
NULL_DRAWS = 50
COST_BPS = 15.0
NW_LAG = 39
NOMINATE_START = pd.Timestamp("2007-01-02")
NOMINATE_END = pd.Timestamp("2019-12-31")


def log(msg):
    print(f"[{time.strftime('%H:%M:%S')}] {msg}", flush=True)


# ---------------------------------------------------------------------------
# Custom composite (ablation) and pick functions -- composite.py untouched
# ---------------------------------------------------------------------------
def compute_composite_ablated(df_date, factor_signs, neutral=False):
    """Same logic as composite.compute_composite, parameterized on a custom
    factor_signs dict instead of the module-level FACTOR_SIGNS -- kept here,
    not added to composite.py, so the confirmed artifact stays untouched."""
    factor_cols = list(factor_signs)
    work = C.neutralize_on_sector(df_date, factor_cols) if neutral else df_date
    scores = pd.DataFrame(index=df_date.index)
    for c in factor_cols:
        scores[c] = C.rank_z(work[c]) * factor_signs[c]
    out = pd.DataFrame(index=df_date.index)
    out["ticker"] = df_date["ticker"].values
    out["coverage"] = scores.notna().sum(axis=1).values
    out["composite"] = scores.mean(axis=1, skipna=True).values
    out.loc[out["coverage"] == 0, "composite"] = np.nan
    return out


ASSET_GROWTH_DROPPED_SIGNS = {k: v for k, v in C.FACTOR_SIGNS.items() if k != "asset_growth"}


def pick_decile1_volq(df_date, scored, book_frac=0.10):
    """Same construction as composite.pick_decile_volq (5 vol quintiles,
    inverse-vol weighted) but selects the SECOND-FROM-BOTTOM decile by
    composite score (ascending rank position [k:2k]) instead of the top
    ([-k:]). Tests physics-doc section 6: decile 1's pooled mean forward
    return was measured above decile 9's on the same scores."""
    vol = df_date["volatility_60"].to_numpy(np.float64)
    valid = np.isfinite(vol) & np.isfinite(scored["composite"].to_numpy(np.float64))
    if valid.sum() < C.N_VOL_QUINTILES * 4:
        return []
    idx = np.flatnonzero(valid)
    vol_v = vol[idx]
    q = pd.qcut(vol_v, C.N_VOL_QUINTILES, labels=False, duplicates="drop")
    comp_v = scored["composite"].to_numpy(np.float64)[idx]
    tick_v = scored["ticker"].to_numpy()[idx]
    picks = []
    for bucket in np.unique(q):
        bmask = q == bucket
        n_bucket = int(bmask.sum())
        k = max(1, int(round(n_bucket * book_frac)))
        b_idx = np.flatnonzero(bmask)
        order_asc = b_idx[np.argsort(comp_v[b_idx])]  # ascending: worst score first
        chosen = order_asc[k:2 * k] if len(order_asc) >= 2 * k else order_asc[-k:]
        for i in chosen:
            picks.append((tick_v[i], vol_v[i]))
    if not picks:
        return []
    inv_vol = np.array([1.0 / max(v, 1e-4) for _, v in picks])
    w = inv_vol / inv_vol.sum()
    return [(t, float(wi)) for (t, _), wi in zip(picks, w)]


def pick_exclude_bottom_decile_volq(df_date, scored, book_frac=0.10):
    """Within each vol quintile, hold every name EXCEPT the bottom
    composite-score decile, inverse-vol weighted across the rest (~90% of
    the universe). NOT apples-to-apples on book size/turnover vs.
    decile_volq -- see pre-registration for the disclosed caveat."""
    vol = df_date["volatility_60"].to_numpy(np.float64)
    valid = np.isfinite(vol) & np.isfinite(scored["composite"].to_numpy(np.float64))
    if valid.sum() < C.N_VOL_QUINTILES * 4:
        return []
    idx = np.flatnonzero(valid)
    vol_v = vol[idx]
    q = pd.qcut(vol_v, C.N_VOL_QUINTILES, labels=False, duplicates="drop")
    comp_v = scored["composite"].to_numpy(np.float64)[idx]
    tick_v = scored["ticker"].to_numpy()[idx]
    picks = []
    for bucket in np.unique(q):
        bmask = q == bucket
        n_bucket = int(bmask.sum())
        k = max(1, int(round(n_bucket * book_frac)))
        b_idx = np.flatnonzero(bmask)
        order_asc = b_idx[np.argsort(comp_v[b_idx])]
        kept = order_asc[k:]
        for i in kept:
            picks.append((tick_v[i], vol_v[i]))
    if not picks:
        return []
    inv_vol = np.array([1.0 / max(v, 1e-4) for _, v in picks])
    w = inv_vol / inv_vol.sum()
    return [(t, float(wi)) for (t, _), wi in zip(picks, w)]


VARIANTS = {
    "decile1_volq": {
        "compute": lambda g: C.compute_composite(g, neutral=False),
        "pick": pick_decile1_volq,
    },
    "exclude_bottom_decile": {
        "compute": lambda g: C.compute_composite(g, neutral=False),
        "pick": pick_exclude_bottom_decile_volq,
    },
    "asset_growth_dropped": {
        "compute": lambda g: compute_composite_ablated(g, ASSET_GROWTH_DROPPED_SIGNS, neutral=False),
        "pick": C.pick_decile_volq,
    },
}


# ---------------------------------------------------------------------------
# Backtest loop (mirrors run_backtest.window_returns_for_offset, generalized
# to arbitrary compute/pick pairs instead of the two hardcoded methods)
# ---------------------------------------------------------------------------
def run_offset(by_date, dates, offset, spy, usmv, rng):
    rebal_dates = dates[offset::RB.HORIZON]
    prev_picks = {name: set() for name in VARIANTS}
    records = []
    for tp in rebal_dates:
        df_date = by_date.get(tp)
        if df_date is None:
            continue
        elig = df_date[df_date[f"eligible_{TIER}"]]
        if len(elig) < C.N_VOL_QUINTILES * 4:
            continue
        elig = elig.reset_index(drop=True)
        ret_lookup = dict(zip(elig["ticker"], elig["gross_return_40"]))
        spy_ret = spy.get(tp, np.nan)
        usmv_ret = usmv.get(tp, np.nan)

        for name, spec in VARIANTS.items():
            scored = spec["compute"](elig)
            picks = spec["pick"](elig, scored)
            picks = [(t, w) for t, w in picks if pd.notna(ret_lookup.get(t))]
            if not picks:
                continue
            wsum = sum(w for _, w in picks)
            gross = sum((w / wsum) * (1.0 + ret_lookup[t]) for t, w in picks) - 1.0
            cur_set = {t for t, _ in picks}
            f_new = sum(1 for t in cur_set if t not in prev_picks[name]) / len(cur_set)
            prev_picks[name] = cur_set
            records.append({"date": tp, "method": name, "draw": "real",
                             "gross": gross, "f_new": f_new, "n_picks": len(picks),
                             "spy": spy_ret, "usmv": usmv_ret})

            null_grosses = []
            for d in range(NULL_DRAWS):
                nscored = C.shuffle_composite(scored, rng)
                npicks = spec["pick"](elig, nscored)
                npicks = [(t, w) for t, w in npicks if pd.notna(ret_lookup.get(t))]
                if not npicks:
                    continue
                nwsum = sum(w for _, w in npicks)
                ngross = sum((w / nwsum) * (1.0 + ret_lookup[t]) for t, w in npicks) - 1.0
                null_grosses.append(ngross)
            for d, ng in enumerate(null_grosses):
                records.append({"date": tp, "method": name, "draw": f"null{d}",
                                 "gross": ng, "f_new": np.nan, "n_picks": len(npicks),
                                 "spy": spy_ret, "usmv": usmv_ret})
    return records


def summarize_offset(records, method, cost_bps=COST_BPS):
    df = pd.DataFrame(records)
    sub = df[(df["method"] == method) & (df["draw"] == "real")].sort_values("date")
    if sub.empty:
        return None
    net = RB.turnover_net_return(sub.to_dict("records"), cost_bps)
    spy_arr = sub["spy"].to_numpy(np.float64)
    spy_ok = np.isfinite(spy_arr)
    excess = net[spy_ok] - spy_arr[spy_ok]
    years = pd.to_datetime(sub["date"]).dt.year.to_numpy()
    yearly = {}
    for y in np.unique(years):
        m = (years == y) & spy_ok
        if not m.any():
            continue
        yearly[int(y)] = float(np.prod(1 + net[m]) - float(np.prod(1 + spy_arr[m])))
    ann_factor = 252.0 / RB.HORIZON
    excess_cagr = float(np.mean(excess) * ann_factor) if len(excess) else float("nan")

    null_sub = df[(df["method"] == method) & (df["draw"] != "real")]
    null_pct = None
    if not null_sub.empty:
        null_by_draw = null_sub.groupby("draw").apply(
            lambda g: np.mean(RB.turnover_net_return(g.sort_values("date").to_dict("records"), cost_bps)
                               - g.sort_values("date")["spy"].to_numpy(np.float64)))
        real_stat = float(np.mean(excess))
        null_pct = float((null_by_draw.to_numpy() < real_stat).mean())

    return {
        "n_windows": int(len(excess)),
        "excess_cagr_vs_spy": excess_cagr,
        "years_won": int(sum(1 for v in yearly.values() if v > 0)),
        "n_years": len(yearly),
        "null_percentile_of_real": null_pct,
    }


def run_backtest_variants():
    by_date, all_dates, spy, usmv = RB.load_data("nominate")
    per_offset = {name: [] for name in VARIANTS}
    for offset in range(40):
        rng = np.random.default_rng(1234 + offset)
        t0 = time.time()
        records = run_offset(by_date, all_dates, offset, spy, usmv, rng)
        for name in VARIANTS:
            s = summarize_offset(records, name)
            if s is not None:
                per_offset[name].append(s)
        log(f"offset {offset:02d} done ({time.time()-t0:.0f}s)")

    report = {}
    for name, offs in per_offset.items():
        vals = [o["excess_cagr_vs_spy"] for o in offs if np.isfinite(o["excess_cagr_vs_spy"])]
        pcts = [o["null_percentile_of_real"] for o in offs if o["null_percentile_of_real"] is not None]
        report[name] = {
            "n_offsets": len(vals),
            "mean_excess_cagr_vs_spy": float(np.mean(vals)) if vals else None,
            "std_excess_cagr_vs_spy": float(np.std(vals)) if vals else None,
            "min": float(np.min(vals)) if vals else None,
            "max": float(np.max(vals)) if vals else None,
            "n_offsets_positive": int(sum(v > 0 for v in vals)) if vals else None,
            "mean_null_percentile": float(np.mean(pcts)) if pcts else None,
            "mean_years_won": float(np.mean([o["years_won"] for o in offs])) if offs else None,
            "mean_n_years": float(np.mean([o["n_years"] for o in offs])) if offs else None,
        }
    return report


# ---------------------------------------------------------------------------
# Book-to-market: IC screen only, no portfolio, no promotion.
# ---------------------------------------------------------------------------
def newey_west_mean_t(x, lag=NW_LAG):
    x = np.asarray(x, dtype=np.float64)
    x = x[np.isfinite(x)]
    n = len(x)
    if n < 10:
        return {"mean": float(np.nan), "t": float(np.nan), "n": n}
    xc = x - x.mean()
    L = min(lag, n - 1)
    var = np.dot(xc, xc) / n
    for l in range(1, L + 1):
        w = 1.0 - l / (L + 1.0)
        var += 2.0 * w * (np.dot(xc[l:], xc[:-l]) / n)
    var = max(var, 1e-12)
    t = x.mean() / np.sqrt(var / n) if var > 0 else np.nan
    return {"mean": float(x.mean()), "t": float(t), "n": int(n)}


def pooled_ic(df, xcol, ycol, date_col="date"):
    g = df[[date_col, xcol, ycol]].dropna()
    out = {}
    for d, gd in g.groupby(date_col):
        if len(gd) < 20:
            continue
        c = gd[xcol].corr(gd[ycol], method="spearman")
        if pd.notna(c):
            out[d] = float(c)
    s = pd.Series(out)
    stats = newey_west_mean_t(s.to_numpy())
    stats["n_dates"] = int(len(s))
    return stats


def _asof_value(panel, fact, date_col):
    """Identical pattern to quality_factors._asof_value: merge_asof with an
    explicit row-position column, asserted preserved -- Round 16's
    sort_index()-after-merge_asof bug, guarded against again here."""
    left = panel[["ticker", date_col]].copy()
    left["_row"] = np.arange(len(panel), dtype=np.int64)
    left = left.rename(columns={date_col: "date"}).sort_values(["date", "ticker"])
    fa = fact.rename(columns={"filed_date": "date"}).sort_values(["date", "ticker"])
    m = (pd.merge_asof(left, fa, on="date", by="ticker", direction="backward")
           .sort_values("_row").reset_index(drop=True))
    assert len(m) == len(panel) and (m["_row"].to_numpy() == np.arange(len(panel))).all(), \
        "book_to_market merge lost or reordered rows"
    return m["value"].to_numpy(np.float64)


def screen_book_to_market():
    log("book_to_market: loading SF1 equity (ARQ+ARY, filed-date keyed) ...")
    sf1 = pd.read_parquet(SF1, columns=["ticker", "dimension", "date", "equity"])
    sf1 = sf1[sf1["dimension"].isin(["ARQ", "ARY"]) & sf1["equity"].notna()].copy()
    sf1["filed_date"] = pd.to_datetime(sf1["date"], errors="coerce")
    sf1 = sf1[sf1["filed_date"].notna()]
    sf1["ticker"] = sf1["ticker"].astype(str)
    equity_fact = (sf1[["ticker", "filed_date", "equity"]]
                   .sort_values(["ticker", "filed_date"])
                   .drop_duplicates(subset=["ticker", "filed_date"], keep="last")
                   .rename(columns={"equity": "value"}).reset_index(drop=True))

    log("loading composite_panel (ticker, date, market_cap, eligible_cap150, label) ...")
    panel = pd.read_parquet(COMPOSITE_PANEL,
                             columns=["ticker", "date", "market_cap", "eligible_cap150",
                                      "forward_return_tradable_40"])
    panel["date"] = pd.to_datetime(panel["date"])
    panel["ticker"] = panel["ticker"].astype(str)
    panel = panel[(panel["date"] >= NOMINATE_START) & (panel["date"] <= NOMINATE_END)
                  & panel["eligible_cap150"]].reset_index(drop=True)

    log(f"as-of join equity onto {len(panel):,} eligible nomination-era rows ...")
    equity = _asof_value(panel, equity_fact, "date")
    with np.errstate(divide="ignore", invalid="ignore"):
        btm = np.where((panel["market_cap"].to_numpy(np.float64) > 0) & np.isfinite(equity),
                       equity / panel["market_cap"].to_numpy(np.float64), np.nan)
    panel["book_to_market"] = btm
    coverage = float(panel["book_to_market"].notna().mean())
    log(f"  coverage {coverage:.1%}")

    panel["__label__"] = panel["forward_return_tradable_40"]
    full = pooled_ic(panel, "book_to_market", "__label__")
    years = panel["date"].dt.year
    odd = pooled_ic(panel[years % 2 == 1], "book_to_market", "__label__")
    even = pooled_ic(panel[years % 2 == 0], "book_to_market", "__label__")
    return {
        "coverage_frac": coverage,
        "pooled_ic": full,
        "odd_years_ic": odd,
        "even_years_ic": even,
        # Classic value premium (Fama-French HML): high book-to-market ->
        # higher forward return, i.e. sign +1. Report the measured sign
        # against that, not a pre-committed FACTOR_SIGNS entry -- this
        # factor is never added to the composite regardless of the result.
        "classical_value_premium_sign": 1,
        "citation": "Fama & French 1992/1993; Novy-Marx 2013 (paired with gross_profitability)",
        "note": "IC screen only -- not added to any composite, not backtested as a portfolio, not promoted.",
    }


def main():
    t0 = time.time()
    report = {"generated": pd.Timestamp.now().isoformat(), "era": "nominate_2007_2019",
              "tier": TIER, "cost_bps": COST_BPS, "null_draws": NULL_DRAWS}
    report["backtest_variants"] = run_backtest_variants()
    report["book_to_market_screen"] = screen_book_to_market()
    OUT_JSON.parent.mkdir(parents=True, exist_ok=True)
    with open(OUT_JSON, "w") as f:
        json.dump(report, f, indent=2, default=str)
    log(f"wrote {OUT_JSON} ({time.time()-t0:.0f}s total)")


if __name__ == "__main__":
    main()
