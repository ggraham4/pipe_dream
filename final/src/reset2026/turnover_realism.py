"""
Two turnover-realism constructions, tested separately -- per
PREREGISTRATION.md's "Turnover realism + third hold-out spend
(2026-09-22)" section, written before this ran. Both use the IC-weighted
composite, cap150, nomination era.

1. Laddered/staggered: 5 cohorts at offsets 0/8/16/24/32, 20% capital
   each, blended by summing independently-compounding terminal wealth.
   Prediction stated in advance: smooths timing luck, does NOT reduce
   total annual turnover.
2. Buffer/hysteresis band: hold unless a name falls out of the top 20%
   (vs. strict top-decile re-picking every window). 20%/10% fixed,
   declared, not swept. Sequential (state-carrying), single offset.

Usage: python3 turnover_realism.py
"""
import json
import sys
import time
from pathlib import Path

import numpy as np
import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parent))
import composite as C            # noqa: E402
import run_backtest as RB         # noqa: E402
import ic_weighted_composite as ICW  # noqa: E402

MAIN_ROOT = Path("/Users/ggraham/pipe_dream/final")
OUT_JSON = MAIN_ROOT / "out" / "reset2026" / "turnover_realism_report.json"
COST_BPS = 15.0
LADDER_OFFSETS = [0, 8, 16, 24, 32]
HOLD_FRAC = 0.20
ENTRY_FRAC = 0.10


def log(msg):
    print(f"[{time.strftime('%H:%M:%S')}] {msg}", flush=True)


# ---------------------------------------------------------------------------
# Part 1: single-offset baseline + 5-cohort ladder (reuses per-offset chains)
# ---------------------------------------------------------------------------
def run_single_offset(by_date, all_dates, offset, spy):
    rebal_dates = all_dates[offset::RB.HORIZON]
    prev_picks = set()
    records = []
    for tp in rebal_dates:
        df_date = by_date.get(tp)
        if df_date is None:
            continue
        elig = df_date[df_date["eligible_cap150"]]
        if len(elig) < C.N_VOL_QUINTILES * 4:
            continue
        elig = elig.reset_index(drop=True)
        scored = ICW.compute_composite_ic_weighted(elig)
        picks = C.pick_decile_volq(elig, scored)
        ret_lookup = dict(zip(elig["ticker"], elig["gross_return_40"]))
        picks = [(t, w) for t, w in picks if pd.notna(ret_lookup.get(t))]
        if not picks:
            continue
        wsum = sum(w for _, w in picks)
        gross = sum((w / wsum) * (1.0 + ret_lookup[t]) for t, w in picks) - 1.0
        cur_set = {t for t, _ in picks}
        f_new = sum(1 for t in cur_set if t not in prev_picks) / len(cur_set)
        prev_picks = cur_set
        records.append({"date": tp, "gross": gross, "f_new": f_new,
                         "spy": spy.get(tp, np.nan)})
    return records


def terminal_wealth_and_excess(records, cost_bps=COST_BPS):
    df = pd.DataFrame(records).sort_values("date")
    net = RB.turnover_net_return(df.to_dict("records"), cost_bps)
    spy_arr = df["spy"].to_numpy(np.float64)
    ok = np.isfinite(spy_arr)
    terminal_wealth = float(np.prod(1 + net[ok]))
    spy_terminal = float(np.prod(1 + spy_arr[ok]))
    n_years = len(df[ok]) * RB.HORIZON / 252.0
    ann_excess = (terminal_wealth / spy_terminal) ** (1.0 / n_years) - 1.0 if n_years > 0 else np.nan
    mean_f_new = float(df["f_new"].mean())
    return {"terminal_wealth_multiple": terminal_wealth, "spy_terminal_multiple": spy_terminal,
            "annualized_excess_vs_spy": float(ann_excess), "mean_f_new_per_window": mean_f_new,
            "n_windows": int(ok.sum())}


def part1_ladder(by_date, all_dates, spy):
    log("\n=== Part 1: single-offset baseline vs 5-cohort ladder ===")
    per_offset_stats = {}
    for offset in LADDER_OFFSETS:
        recs = run_single_offset(by_date, all_dates, offset, spy)
        stats = terminal_wealth_and_excess(recs)
        per_offset_stats[offset] = stats
        log(f"  offset {offset:2d}: terminal_wealth={stats['terminal_wealth_multiple']:.3f}x  "
            f"ann_excess={stats['annualized_excess_vs_spy']*100:+.2f}%  "
            f"mean_f_new={stats['mean_f_new_per_window']*100:.1f}%")

    # Ladder: dollar-weighted (20% each) sum of terminal wealth.
    ladder_terminal = np.mean([s["terminal_wealth_multiple"] for s in per_offset_stats.values()])
    spy_terminal = np.mean([s["spy_terminal_multiple"] for s in per_offset_stats.values()])
    n_years = 13.0  # nomination era span
    ladder_ann_excess = (ladder_terminal / spy_terminal) ** (1.0 / n_years) - 1.0
    ladder_mean_f_new = np.mean([s["mean_f_new_per_window"] for s in per_offset_stats.values()])

    dispersion_single_offset = np.std([s["annualized_excess_vs_spy"] for s in per_offset_stats.values()])
    log(f"\n  LADDER (5 cohorts blended): terminal_wealth={ladder_terminal:.3f}x  "
        f"ann_excess={ladder_ann_excess*100:+.2f}%  mean_f_new={ladder_mean_f_new*100:.1f}%")
    log(f"  Dispersion across the 5 single-offset legs (timing-luck proxy): "
        f"sd={dispersion_single_offset*100:.2f}pp")

    return {"per_offset": per_offset_stats, "ladder_blended": {
        "terminal_wealth_multiple": float(ladder_terminal),
        "annualized_excess_vs_spy": float(ladder_ann_excess),
        "mean_f_new_per_window": float(ladder_mean_f_new),
    }, "single_offset_dispersion_sd": float(dispersion_single_offset)}


# ---------------------------------------------------------------------------
# Part 2: buffer/hysteresis band, sequential, single offset
# ---------------------------------------------------------------------------
def pick_buffered(elig, scored, held_previous, entry_frac=ENTRY_FRAC, hold_frac=HOLD_FRAC):
    vol = elig["volatility_60"].to_numpy(np.float64)
    comp = scored["composite"].to_numpy(np.float64)
    ticker = elig["ticker"].to_numpy()
    valid = np.isfinite(vol) & np.isfinite(comp)
    if valid.sum() < C.N_VOL_QUINTILES * 4:
        return {}

    idx = np.flatnonzero(valid)
    vol_v = vol[idx]
    comp_v = comp[idx]
    tick_v = ticker[idx]
    q = pd.qcut(vol_v, C.N_VOL_QUINTILES, labels=False, duplicates="drop")

    final_picks = {}  # ticker -> vol (for inverse-vol weighting)
    for bucket in np.unique(q):
        bmask = q == bucket
        n_bucket = int(bmask.sum())
        k_entry = max(1, int(round(n_bucket * entry_frac)))
        k_hold = max(1, int(round(n_bucket * hold_frac)))
        b_idx = np.flatnonzero(bmask)
        order_desc = b_idx[np.argsort(-comp_v[b_idx])]  # best-to-worst, this quintile, today

        entry_candidates = list(tick_v[order_desc[:k_entry]])
        hold_zone = set(tick_v[order_desc[:k_hold]])
        names_here = set(tick_v[b_idx])

        kept = (held_previous & names_here) & hold_zone
        target_size = k_entry
        new_adds = []
        for t in entry_candidates:
            if len(kept) + len(new_adds) >= target_size:
                break
            if t not in kept:
                new_adds.append(t)

        for t in kept | set(new_adds):
            i = np.flatnonzero(tick_v == t)[0]
            final_picks[t] = vol_v[i]

    if not final_picks:
        return {}
    inv_vol = {t: 1.0 / max(v, 1e-4) for t, v in final_picks.items()}
    total = sum(inv_vol.values())
    return {t: w / total for t, w in inv_vol.items()}


def part2_buffer(by_date, all_dates, spy, offset=0):
    log(f"\n=== Part 2: buffer/hysteresis band (hold_frac={HOLD_FRAC}, entry_frac={ENTRY_FRAC}), offset={offset} ===")
    rebal_dates = all_dates[offset::RB.HORIZON]
    held = set()
    records_buffered = []
    records_baseline = []
    prev_baseline = set()
    for tp in rebal_dates:
        df_date = by_date.get(tp)
        if df_date is None:
            continue
        elig = df_date[df_date["eligible_cap150"]]
        if len(elig) < C.N_VOL_QUINTILES * 4:
            continue
        elig = elig.reset_index(drop=True)
        scored = ICW.compute_composite_ic_weighted(elig)
        ret_lookup = dict(zip(elig["ticker"], elig["gross_return_40"]))

        # Buffered
        picks_w = pick_buffered(elig, scored, held)
        picks_w = {t: w for t, w in picks_w.items() if pd.notna(ret_lookup.get(t))}
        if picks_w:
            wsum = sum(picks_w.values())
            gross = sum((w / wsum) * (1.0 + ret_lookup[t]) for t, w in picks_w.items()) - 1.0
            cur_set = set(picks_w)
            f_new = sum(1 for t in cur_set if t not in held) / len(cur_set)
            held = cur_set
            records_buffered.append({"date": tp, "gross": gross, "f_new": f_new, "spy": spy.get(tp, np.nan)})

        # Baseline (strict top-decile every window), same dates, for a clean comparison
        picks_b = C.pick_decile_volq(elig, scored)
        picks_b = [(t, w) for t, w in picks_b if pd.notna(ret_lookup.get(t))]
        if picks_b:
            wsum_b = sum(w for _, w in picks_b)
            gross_b = sum((w / wsum_b) * (1.0 + ret_lookup[t]) for t, w in picks_b) - 1.0
            cur_b = {t for t, _ in picks_b}
            f_new_b = sum(1 for t in cur_b if t not in prev_baseline) / len(cur_b)
            prev_baseline = cur_b
            records_baseline.append({"date": tp, "gross": gross_b, "f_new": f_new_b, "spy": spy.get(tp, np.nan)})

    stats_buffered = terminal_wealth_and_excess(records_buffered)
    stats_baseline = terminal_wealth_and_excess(records_baseline)
    log(f"  BASELINE (strict top-decile): ann_excess={stats_baseline['annualized_excess_vs_spy']*100:+.2f}%  "
        f"mean_f_new={stats_baseline['mean_f_new_per_window']*100:.1f}%  n={stats_baseline['n_windows']}")
    log(f"  BUFFERED (hold unless <top-{int(HOLD_FRAC*100)}%): "
        f"ann_excess={stats_buffered['annualized_excess_vs_spy']*100:+.2f}%  "
        f"mean_f_new={stats_buffered['mean_f_new_per_window']*100:.1f}%  n={stats_buffered['n_windows']}")
    return {"baseline": stats_baseline, "buffered": stats_buffered}


def main():
    t0 = time.time()
    by_date, all_dates, spy, usmv = RB.load_data("nominate")
    report = {}
    report["ladder"] = part1_ladder(by_date, all_dates, spy)
    report["buffer"] = part2_buffer(by_date, all_dates, spy)

    OUT_JSON.parent.mkdir(parents=True, exist_ok=True)
    with open(OUT_JSON, "w") as f:
        json.dump(report, f, indent=2, default=str)
    log(f"\nwrote {OUT_JSON} ({time.time()-t0:.0f}s total)")


if __name__ == "__main__":
    main()
