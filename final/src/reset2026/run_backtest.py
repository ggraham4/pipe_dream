"""
The orchestrator. For each of 6 (universe tier x raw/neutral) cells, for
each of the 40 non-overlapping-window grid offsets (PREREGISTRATION.md
section 5 -- "all 40 grid offsets are used, not offset 0"), walks every
40-trading-day rebalance date in the chosen era, builds BOTH portfolio
constructions (decile_volq, topN_ew) from the same composite score, realizes
each pick's return from the pre-verified `outcome_cache.parquet` (no
per-window model retrain, no per-pick execution-engine call -- this is the
"cheap half" the whole reset.py package's speed depends on: compute the
composite once per date, look up every position's already-cached, already-
survivorship-correct return), and draws NULL_DRAWS matched nulls (composite
scores permuted within date, same construction) from the SAME cached
composite so a null draw costs a reshuffle + a pick, not a rebuild.

Resumable: one checkpoint file per (tier, neutral, offset) cell under
out/reset2026/checkpoints/. Safe to kill and re-run the same command.

Usage
    python3 run_backtest.py --era nominate
    python3 run_backtest.py --era holdout --only cap500_neutral_decile_volq --i-am-confirming
"""
import argparse
import json
import sys
import time
from pathlib import Path

import numpy as np
import pandas as pd
import pyarrow.parquet as pq

sys.path.insert(0, str(Path(__file__).resolve().parent))
import composite as C  # noqa: E402

MAIN_ROOT = Path("/Users/ggraham/pipe_dream/final")
OUT_DIR = MAIN_ROOT / "out" / "reset2026"
PANEL_PATH = OUT_DIR / "composite_panel.parquet"
OUTCOME_PATH = OUT_DIR / "outcome_cache.parquet"
CKPT_DIR = OUT_DIR / "checkpoints"

TIERS = ("cap2000", "cap500", "cap150")
NEUTRAL_VARIANTS = (False, True)
N_OFFSETS = 40
HORIZON = C.HORIZON
NULL_DRAWS = 100
BOOTSTRAP_ITERS = 2000
COST_LEVELS = (15.0, 50.0)

# 2007-01-02 matches continuous_walkforward_pit.py's DEFAULT_START_DATE.
# SPY's own benchmark CSV only starts 2006-01-03 -- starting here avoids
# manufacturing a NaN-excess year from a benchmark gap rather than reporting
# one honestly with a note (USMV starts later still, 2011-10-20, and IS
# handled as an honest per-window NaN below -- it is excluded from
# vs-USMV means/years rather than poisoning them).
NOMINATE_START = pd.Timestamp("2007-01-02")
NOMINATE_END = pd.Timestamp("2019-12-31")
HOLDOUT_START = pd.Timestamp("2020-01-01")

NEEDED_COLS = list(dict.fromkeys(
    ["ticker", "date", "sector", "volatility_60", "market_cap"]
    + C.FACTOR_COLS
    + [f"eligible_{t}" for t in TIERS]
))


def cell_name(tier, neutral, offset):
    return f"{tier}_{'neutral' if neutral else 'raw'}_off{offset:02d}"


def load_data(era):
    print("loading composite_panel + outcome_cache ...", flush=True)
    panel = pd.read_parquet(PANEL_PATH, columns=NEEDED_COLS)
    panel["date"] = pd.to_datetime(panel["date"])
    panel["ticker"] = panel["ticker"].astype(str)

    outcomes = pd.read_parquet(OUTCOME_PATH)
    outcomes["date"] = pd.to_datetime(outcomes["date"])
    bench = outcomes[outcomes["ticker"].isin(["SPY", "USMV"])].copy()
    stock_outcomes = outcomes[~outcomes["ticker"].isin(["SPY", "USMV"])]

    before = len(panel)
    panel = panel.merge(stock_outcomes[["ticker", "date", "gross_return_40", "truncated"]],
                        on=["ticker", "date"], how="left")
    assert len(panel) == before, "outcome merge changed row count"
    print(f"  panel: {len(panel):,} rows, outcome coverage "
          f"{panel['gross_return_40'].notna().mean():.1%}", flush=True)

    if era == "nominate":
        panel = panel[(panel["date"] >= NOMINATE_START) & (panel["date"] <= NOMINATE_END)]
        bench = bench[(bench["date"] >= NOMINATE_START) & (bench["date"] <= NOMINATE_END)]
    else:
        panel = panel[panel["date"] >= HOLDOUT_START]
        bench = bench[bench["date"] >= HOLDOUT_START]

    spy = bench[bench["ticker"] == "SPY"].set_index("date")["gross_return_40"]
    usmv = bench[bench["ticker"] == "USMV"].set_index("date")["gross_return_40"]

    by_date = {d: g for d, g in panel.groupby("date", sort=True)}
    all_dates = sorted(by_date.keys())
    print(f"  era={era}: {len(all_dates):,} trading days, "
          f"{all_dates[0].date()} to {all_dates[-1].date()}", flush=True)
    return by_date, all_dates, spy, usmv


def window_returns_for_offset(by_date, dates, offset, tier, neutral, spy, usmv, rng):
    """Walk one offset's non-overlapping rebalance dates for one (tier,
    neutral) cell. Returns a list of per-window dicts (real + null draws)."""
    rebal_dates = dates[offset::HORIZON]
    prev_picks = {"decile_volq": set(), "topn_ew": set()}
    records = []
    for tp in rebal_dates:
        df_date = by_date.get(tp)
        if df_date is None:
            continue
        elig = df_date[df_date[f"eligible_{tier}"]]
        if len(elig) < C.N_VOL_QUINTILES * 4:
            continue
        elig = elig.reset_index(drop=True)
        scored = C.compute_composite(elig, neutral=neutral)
        ret_lookup = dict(zip(elig["ticker"], elig["gross_return_40"]))

        spy_ret = spy.get(tp, np.nan)
        usmv_ret = usmv.get(tp, np.nan)

        for method, pick_fn in (("decile_volq", C.pick_decile_volq), ("topn_ew", C.pick_topn_ew)):
            picks = pick_fn(elig, scored)
            picks = [(t, w) for t, w in picks if pd.notna(ret_lookup.get(t))]
            if not picks:
                continue
            wsum = sum(w for _, w in picks)
            gross = sum((w / wsum) * (1.0 + ret_lookup[t]) for t, w in picks) - 1.0
            cur_set = {t for t, _ in picks}
            f_new = sum(1 for t in cur_set if t not in prev_picks[method]) / len(cur_set)
            prev_picks[method] = cur_set
            records.append({
                "date": tp, "method": method, "draw": "real",
                "gross": gross, "f_new": f_new, "n_picks": len(picks),
                "spy": spy_ret, "usmv": usmv_ret,
            })

            null_grosses = []
            for d in range(NULL_DRAWS):
                nscored = C.shuffle_composite(scored, rng)
                npicks = pick_fn(elig, nscored)
                npicks = [(t, w) for t, w in npicks if pd.notna(ret_lookup.get(t))]
                if not npicks:
                    continue
                nwsum = sum(w for _, w in npicks)
                ngross = sum((w / nwsum) * (1.0 + ret_lookup[t]) for t, w in npicks) - 1.0
                null_grosses.append(ngross)
            for d, ng in enumerate(null_grosses):
                records.append({
                    "date": tp, "method": method, "draw": f"null{d}",
                    "gross": ng, "f_new": np.nan, "n_picks": len(npicks),
                    "spy": spy_ret, "usmv": usmv_ret,
                })
    return records


def turnover_net_return(recs_for_method, cost_bps):
    """Approximate turnover-aware net return using each window's f_new as
    both the entry- and exit-turnover fraction for the CURRENT window (an
    exact next-window lookup, as execution.apply_turnover_costs does, would
    need the full ordered sequence; f_new alone is a fair single-window
    proxy and is exact when the book's entry and exit turnover are similar,
    which decile_volq/topn_ew's stable, slowly-rotating books satisfy to
    first order). h = half the round-trip cost."""
    h = (cost_bps / 1e4) / 2.0
    out = []
    for r in recs_for_method:
        f = r.get("f_new", np.nan)
        f = f if pd.notna(f) else 1.0
        net = (1.0 + r["gross"]) * (1.0 - h * f) / (1.0 + h * f) - 1.0
        out.append(net)
    return np.array(out)


def summarize_cell(records, tier, neutral, offset):
    df = pd.DataFrame(records)
    out = {"tier": tier, "neutral": neutral, "offset": offset}
    for method in ("decile_volq", "topn_ew"):
        sub = df[(df["method"] == method) & (df["draw"] == "real")].sort_values("date")
        if sub.empty:
            continue
        for cost in COST_LEVELS:
            net = turnover_net_return(sub.to_dict("records"), cost)
            spy_arr = sub["spy"].to_numpy(np.float64)
            usmv_arr = sub["usmv"].to_numpy(np.float64)
            spy_ok = np.isfinite(spy_arr)
            usmv_ok = np.isfinite(usmv_arr)
            excess_spy = net[spy_ok] - spy_arr[spy_ok]
            excess_usmv = net[usmv_ok] - usmv_arr[usmv_ok]
            years = pd.to_datetime(sub["date"]).dt.year.to_numpy()
            yearly = {}
            for y in np.unique(years):
                m = (years == y) & spy_ok
                if not m.any():
                    continue
                port_y = float(np.prod(1 + net[m]) - 1)
                spy_y = float(np.prod(1 + spy_arr[m]) - 1)
                yearly[int(y)] = {"port_cagr_like": port_y, "spy_cagr_like": spy_y,
                                   "excess": port_y - spy_y}
            n_windows = len(net)
            ann_factor = 252.0 / HORIZON
            excess_cagr = float(np.mean(excess_spy) * ann_factor) if len(excess_spy) else float("nan")
            info_ratio = (float(np.mean(excess_spy) / (np.std(excess_spy) + 1e-9) * np.sqrt(ann_factor))
                          if len(excess_spy) else float("nan"))
            out[f"{method}_cost{int(cost)}"] = {
                "n_windows": n_windows,
                "mean_net_return": float(np.mean(net)),
                "excess_cagr_vs_spy": excess_cagr,
                "excess_cagr_vs_usmv": (float(np.mean(excess_usmv) * ann_factor)
                                        if len(excess_usmv) else float("nan")),
                "n_windows_vs_usmv": int(usmv_ok.sum()),
                "info_ratio_vs_spy": info_ratio,
                "years_won_vs_spy": sum(1 for v in yearly.values() if v["excess"] > 0),
                "n_years": len(yearly),
                "yearly": yearly,
            }
        # Null percentile on the primary (15bp) cost level, decile-style.
        null_sub = df[(df["method"] == method) & (df["draw"] != "real")]
        if not null_sub.empty:
            null_by_draw = null_sub.groupby("draw").apply(
                lambda g: np.mean(turnover_net_return(g.sort_values("date").to_dict("records"), 15.0)
                                   - g.sort_values("date")["spy"].to_numpy(np.float64)))
            real_stat = out[f"{method}_cost15"]["excess_cagr_vs_spy"] / ann_factor  # back to per-window mean
            pctile = float((null_by_draw.to_numpy() < real_stat).mean())
            out[f"{method}_null_mean"] = float(null_by_draw.mean())
            out[f"{method}_null_std"] = float(null_by_draw.std())
            out[f"{method}_null_percentile_of_real"] = pctile
    return out


def bootstrap_ci(net, spy, n_iter=BOOTSTRAP_ITERS, seed=0):
    rng = np.random.default_rng(seed)
    excess = net - spy
    n = len(excess)
    if n < 5:
        return None
    ann_factor = 252.0 / HORIZON
    draws = np.empty(n_iter)
    for i in range(n_iter):
        sample = rng.choice(excess, size=n, replace=True)
        draws[i] = np.mean(sample) * ann_factor
    return {"lo95": float(np.percentile(draws, 2.5)), "hi95": float(np.percentile(draws, 97.5)),
            "median": float(np.percentile(draws, 50))}


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--era", choices=["nominate", "holdout"], default="nominate")
    ap.add_argument("--only", default=None, help="tier_neutral, e.g. cap500_neutral (holdout must name one)")
    ap.add_argument("--i-am-confirming", action="store_true")
    ap.add_argument("--seed", type=int, default=1234)
    args = ap.parse_args()

    if args.era == "holdout" and not args.i_am_confirming:
        raise SystemExit("--era holdout requires --i-am-confirming AND --only <the one pre-registered config>. "
                          "See PREREGISTRATION.md section 8 -- this run happens exactly once.")
    if args.era == "holdout" and args.only is None:
        raise SystemExit("--era holdout requires --only naming the ONE nomination-era-selected configuration.")

    CKPT_DIR.mkdir(parents=True, exist_ok=True)
    by_date, dates, spy, usmv = load_data(args.era)

    cells = []
    for tier in TIERS:
        for neutral in NEUTRAL_VARIANTS:
            if args.only and f"{tier}_{'neutral' if neutral else 'raw'}" != args.only:
                continue
            cells.append((tier, neutral))

    t0 = time.time()
    n_total = len(cells) * N_OFFSETS
    n_done = 0
    for tier, neutral in cells:
        for offset in range(N_OFFSETS):
            name = f"{args.era}_{cell_name(tier, neutral, offset)}"
            ckpt = CKPT_DIR / f"{name}.json"
            if ckpt.exists():
                n_done += 1
                continue
            rng = np.random.default_rng(args.seed + hash((tier, neutral, offset)) % (2**31))
            records = window_returns_for_offset(by_date, dates, offset, tier, neutral, spy, usmv, rng)
            summary = summarize_cell(records, tier, neutral, offset)
            ckpt.write_text(json.dumps(summary, default=str))
            n_done += 1
            elapsed = time.time() - t0
            rate = elapsed / max(n_done, 1)
            eta = rate * (n_total - n_done)
            print(f"[{n_done}/{n_total}] {name}  ({elapsed:.0f}s elapsed, "
                  f"~{eta:.0f}s remaining)", flush=True)

    print(f"\nAll cells done ({time.time()-t0:.0f}s). Run aggregate_report.py next.", flush=True)


if __name__ == "__main__":
    sys.exit(main())
