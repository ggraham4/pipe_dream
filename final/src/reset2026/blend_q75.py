"""
Zero-fit blend of the composite and the deployed q75 model -- Gabe's
requested first step of the "meta model" roadmap (2026-09-19 discussion,
see PREREGISTRATION.md's "Future avenues" section). Rank-average the two
scores, 50/50, no fitted weight -- same "no model to refit" philosophy as
the composite itself.

WHY THIS IS A SINGLE-GRID RESULT, NOT A 40-OFFSET-AVERAGED ONE
----------------------------------------------------------------
Every other result in this package is averaged across all 40 non-
overlapping-window grid offsets (PREREGISTRATION.md section 5), because a
single offset is known to be fragile for weak signals. That isn't possible
here: q75's score cache
(out/sweep/scores/price_fund_h40_q75_trd_xgb_d3e01r100_expanding_cap500k_pit_s40.parquet)
was produced by ONE walk-forward run of the sweep harness, at ONE fixed
cadence (verified: 124 timepoints, 2007-01-03 to 2026-07-27, ~57-63
calendar days apart -- confirmed to be the same grid as this package's own
offset 0). Scoring q75 at the other 39 offsets would mean retraining
XGBoost 39 more times, which reintroduces the exact cost problem the
composite was built to avoid, just to test a blend. This result is
reported as what it is: ONE grid, not an offset-robust estimate. Treat any
edge found here as a lead to confirm at more offsets (by rescoring q75
elsewhere, a real but expensive follow-up), not as evidence at the same
strength as the rest of this package.

CONSTRUCTION
    Universe: cap2000 (q75's own universe -- the composite's strongest
        result, at cap150, has no q75 counterpart to blend against).
    blend_score = mean( rank_z(composite_raw), rank_z(q75_score) ), per date.
    Portfolio: decile_volq (same construction throughout this package),
        applied identically to all three of: q75 alone, composite alone,
        and the blend, so any difference is attributable to the blend
        itself, not a construction mismatch against the deployed model's
        own reported numbers (which use single-best-per-quintile, not
        decile_volq).

OUTPUT
    <MAIN_ROOT>/out/reset2026/blend_q75_report.json
"""
import json
import sys
from pathlib import Path

import numpy as np
import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parent))
import composite as C  # noqa: E402

MAIN_ROOT = Path("/Users/ggraham/pipe_dream/final")
Q75_SCORES = MAIN_ROOT / "out" / "sweep" / "scores" / "price_fund_h40_q75_trd_xgb_d3e01r100_expanding_cap500k_pit_s40.parquet"
PANEL = MAIN_ROOT / "out" / "reset2026" / "composite_panel.parquet"
OUTCOME = MAIN_ROOT / "out" / "reset2026" / "outcome_cache.parquet"
OUT = MAIN_ROOT / "out" / "reset2026" / "blend_q75_report.json"

TIER = "cap2000"
COST_BPS = 15.0
NULL_DRAWS = 100
NOMINATE_END = pd.Timestamp("2019-12-31")


def turnover_net(gross_seq, f_new_seq, cost_bps):
    h = (cost_bps / 1e4) / 2.0
    out = []
    for g, f in zip(gross_seq, f_new_seq):
        f = f if np.isfinite(f) else 1.0
        out.append((1.0 + g) * (1.0 - h * f) / (1.0 + h * f) - 1.0)
    return np.array(out)


def summarize(records, label):
    df = pd.DataFrame(records).sort_values("date")
    net = turnover_net(df["gross"].to_numpy(), df["f_new"].to_numpy(), COST_BPS)
    spy = df["spy"].to_numpy(np.float64)
    ok = np.isfinite(spy)
    excess = net[ok] - spy[ok]
    ann = 252.0 / C.HORIZON
    years = pd.to_datetime(df["date"]).dt.year.to_numpy()
    yearly = {}
    for y in np.unique(years):
        m = (years == y) & ok
        if not m.any():
            continue
        py = float(np.prod(1 + net[m]) - 1)
        sy = float(np.prod(1 + spy[m]) - 1)
        yearly[int(y)] = {"port": py, "spy": sy, "excess": py - sy}
    nominate_mask = pd.to_datetime(df["date"]) <= NOMINATE_END
    return {
        "label": label,
        "n_windows": int(len(df)),
        "excess_cagr_vs_spy": float(np.mean(excess) * ann),
        "years_won": sum(1 for v in yearly.values() if v["excess"] > 0),
        "n_years": len(yearly),
        "yearly": yearly,
        "nominate_only_excess_cagr": float(np.mean((net - spy)[ok & nominate_mask.to_numpy()]) * ann)
                                      if (ok & nominate_mask.to_numpy()).any() else None,
        "holdout_only_excess_cagr": float(np.mean((net - spy)[ok & ~nominate_mask.to_numpy()]) * ann)
                                     if (ok & ~nominate_mask.to_numpy()).any() else None,
    }


def loyo(records, label):
    df = pd.DataFrame(records).sort_values("date")
    net = turnover_net(df["gross"].to_numpy(), df["f_new"].to_numpy(), COST_BPS)
    spy = df["spy"].to_numpy(np.float64)
    ok = np.isfinite(spy)
    excess = (net - spy)[ok]
    years = pd.to_datetime(df["date"]).dt.year.to_numpy()[ok]
    out = {"all": float(np.mean(excess))}
    for y in np.unique(years):
        rest = excess[years != y]
        out[f"drop_{y}"] = float(np.mean(rest)) if len(rest) else None
    return out


def main():
    print("loading panel + outcomes + q75 scores ...")
    needed = list(dict.fromkeys(
        ["ticker", "date", "sector", "volatility_60", f"eligible_{TIER}"] + C.FACTOR_COLS))
    panel = pd.read_parquet(PANEL, columns=needed)
    panel["date"] = pd.to_datetime(panel["date"])
    panel["ticker"] = panel["ticker"].astype(str)

    outcomes = pd.read_parquet(OUTCOME, columns=["ticker", "date", "gross_return_40"])
    outcomes["date"] = pd.to_datetime(outcomes["date"])
    spy_series = outcomes[outcomes["ticker"] == "SPY"].set_index("date")["gross_return_40"]
    stock_outcomes = outcomes[~outcomes["ticker"].isin(["SPY", "USMV"])]
    panel = panel.merge(stock_outcomes, on=["ticker", "date"], how="left")

    q75 = pd.read_parquet(Q75_SCORES, columns=["timepoint", "ticker", "score"])
    q75["timepoint"] = pd.to_datetime(q75["timepoint"])
    q75["ticker"] = q75["ticker"].astype(str)
    dates = sorted(q75["timepoint"].unique())
    q75_by_date = {d: g.set_index("ticker")["score"] for d, g in q75.groupby("timepoint")}

    by_date = {d: g for d, g in panel.groupby("date") if d in set(dates)}
    spy_lookup = spy_series.to_dict()

    print("scoring: q75 alone, composite alone, blend ...")
    q75_records, comp_records, blend_records = [], [], []
    q75_null_draws, blend_null_draws = [], []
    rng = np.random.default_rng(2026)

    prev = {"q75": set(), "comp": set(), "blend": set()}
    for tp in dates:
        df_date = by_date.get(tp)
        if df_date is None:
            continue
        elig = df_date[df_date[f"eligible_{TIER}"]].reset_index(drop=True)
        if len(elig) < 20:
            continue
        ret_lookup = dict(zip(elig["ticker"], elig["gross_return_40"]))
        comp_scored = C.compute_composite(elig, neutral=False)
        q75_scores_today = q75_by_date.get(tp)
        if q75_scores_today is None:
            continue
        q75_vals = elig["ticker"].map(q75_scores_today).to_numpy(dtype=np.float64)

        comp_rank = C.rank_z(comp_scored["composite"])
        q75_rank = C.rank_z(pd.Series(q75_vals, index=comp_scored.index))
        blend_score = pd.concat([comp_rank, q75_rank], axis=1).mean(axis=1, skipna=True)
        blend_score[comp_rank.isna() & q75_rank.isna()] = np.nan

        def do_one(score_series, key, null=False):
            frame = pd.DataFrame({"ticker": elig["ticker"].to_numpy(), "composite": score_series.to_numpy()})
            if null:
                vals = frame["composite"].to_numpy(copy=True)
                finite = np.isfinite(vals)
                perm = rng.permutation(np.flatnonzero(finite))
                shuffled = vals.copy()
                shuffled[finite] = vals[perm]
                frame["composite"] = shuffled
            picks = C.pick_decile_volq(elig, frame)
            picks = [(t, w) for t, w in picks if pd.notna(ret_lookup.get(t))]
            if not picks:
                return None
            wsum = sum(w for _, w in picks)
            gross = sum((w / wsum) * (1.0 + ret_lookup[t]) for t, w in picks) - 1.0
            cur = {t for t, _ in picks}
            f_new = len(cur - prev[key]) / len(cur) if not null else 1.0
            if not null:
                prev[key] = cur
            return {"date": tp, "gross": gross, "f_new": f_new, "spy": spy_lookup.get(tp, np.nan)}

        r = do_one(pd.Series(q75_vals, index=comp_scored.index), "q75")
        if r:
            q75_records.append(r)
        r = do_one(comp_scored["composite"], "comp")
        if r:
            comp_records.append(r)
        r = do_one(blend_score, "blend")
        if r:
            blend_records.append(r)

        for d in range(NULL_DRAWS):
            r = do_one(pd.Series(q75_vals, index=comp_scored.index), "q75", null=True)
            if r:
                q75_null_draws.append((tp, r["gross"]))
            r = do_one(blend_score, "blend", null=True)
            if r:
                blend_null_draws.append((tp, r["gross"]))

    print(f"windows: q75={len(q75_records)}, composite={len(comp_records)}, blend={len(blend_records)}")

    report = {
        "q75_alone": summarize(q75_records, "q75_alone_decile_volq"),
        "composite_alone": summarize(comp_records, "composite_alone_cap2000_decile_volq"),
        "blend": summarize(blend_records, "blend_50_50_decile_volq"),
        "blend_loyo": loyo(blend_records, "blend"),
        "q75_loyo": loyo(q75_records, "q75"),
        "note": "SINGLE GRID (q75's own cadence, confirmed == this package's offset 0), "
                "not 40-offset-averaged. See module docstring.",
    }

    def null_pctile(records, null_draws):
        df = pd.DataFrame(records).sort_values("date")
        net = turnover_net(df["gross"].to_numpy(), df["f_new"].to_numpy(), COST_BPS)
        spy = df["spy"].to_numpy(np.float64)
        ok = np.isfinite(spy)
        real_mean = float(np.mean((net - spy)[ok]))
        by_draw = {}
        for tp, g in null_draws:
            by_draw.setdefault(tp, []).append(g)
        # approximate: null mean excess using same spy lookup, avg gross per draw index
        n_per_date = NULL_DRAWS
        draw_means = []
        dates_sorted = df["date"].tolist()
        for d in range(n_per_date):
            vals = []
            for tp in dates_sorted:
                pool = by_draw.get(tp)
                if pool and d < len(pool):
                    s = spy_lookup.get(tp, np.nan)
                    if np.isfinite(s):
                        vals.append(pool[d] - s)
            if vals:
                draw_means.append(np.mean(vals))
        draw_means = np.array(draw_means)
        pctile = float((draw_means < real_mean).mean()) if len(draw_means) else None
        return {"real_mean_excess_per_window": real_mean,
                "null_mean": float(draw_means.mean()) if len(draw_means) else None,
                "null_std": float(draw_means.std()) if len(draw_means) else None,
                "percentile_of_real": pctile}

    report["blend_null"] = null_pctile(blend_records, blend_null_draws)
    report["q75_null"] = null_pctile(q75_records, q75_null_draws)

    OUT.write_text(json.dumps(report, indent=2, default=str))
    print(json.dumps({k: v for k, v in report.items() if k not in
                      ("blend_loyo", "q75_loyo")}, indent=2, default=str))
    print(f"\n-> {OUT}")


if __name__ == "__main__":
    sys.exit(main())
