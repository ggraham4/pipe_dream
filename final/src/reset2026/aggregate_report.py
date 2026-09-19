"""
Reads every per-(tier, neutral, offset) checkpoint run_backtest.py wrote and
produces the headline report: PREREGISTRATION.md section 6's metrics,
offset-averaged (not offset-0), with the full 40-offset distribution shown
alongside the mean so a fragile result is visible as one (the exact
`check_grid_offset.py` lesson this package's design note in PREREGISTRATION.md
section 5 exists to apply).

The "bootstrap CI" here resamples WHICH OF THE 40 OFFSETS to include (with
replacement, 2000 draws) rather than individual windows within one offset.
This is a between-offset dispersion estimate, not a formal iid-block
bootstrap -- the 40 offsets all describe the SAME underlying 3,272 trading
days from different partitions, so they are not independent draws either way,
and this file does not claim otherwise. It is reported alongside the full
offset distribution (mean/std/min/max/n_offsets_positive) as a second,
complementary read on dispersion, not a replacement for it.

Usage
    python3 aggregate_report.py --era nominate
"""
import argparse
import json
import sys
from pathlib import Path

import numpy as np

MAIN_ROOT = Path("/Users/ggraham/pipe_dream/final")
CKPT_DIR = MAIN_ROOT / "out" / "reset2026" / "checkpoints"
OUT_MD = MAIN_ROOT / "out" / "reset2026" / "REPORT_{era}.md"

TIERS = ("cap2000", "cap500", "cap150")
NEUTRAL_VARIANTS = (False, True)
N_OFFSETS = 40
BOOTSTRAP_ITERS = 2000


def load_cells(era):
    cells = {}
    for tier in TIERS:
        for neutral in NEUTRAL_VARIANTS:
            key = f"{tier}_{'neutral' if neutral else 'raw'}"
            offs = []
            for offset in range(N_OFFSETS):
                p = CKPT_DIR / f"{era}_{tier}_{'neutral' if neutral else 'raw'}_off{offset:02d}.json"
                if p.exists():
                    offs.append(json.loads(p.read_text()))
            cells[key] = offs
    return cells


def offset_bootstrap(values, n_iter=BOOTSTRAP_ITERS, seed=0):
    rng = np.random.default_rng(seed)
    values = np.asarray(values, dtype=np.float64)
    values = values[np.isfinite(values)]
    if len(values) < 3:
        return None
    draws = np.array([np.mean(rng.choice(values, size=len(values), replace=True)) for _ in range(n_iter)])
    return {"lo95": float(np.percentile(draws, 2.5)), "hi95": float(np.percentile(draws, 97.5))}


def summarize(offs, method, cost):
    key = f"{method}_cost{cost}"
    vals = [o[key]["excess_cagr_vs_spy"] for o in offs if key in o and np.isfinite(o[key]["excess_cagr_vs_spy"])]
    usmv_vals = [o[key]["excess_cagr_vs_usmv"] for o in offs
                 if key in o and np.isfinite(o[key]["excess_cagr_vs_usmv"])]
    years_won = [o[key]["years_won_vs_spy"] for o in offs if key in o]
    n_years = [o[key]["n_years"] for o in offs if key in o]
    null_pct = [o.get(f"{method}_null_percentile_of_real") for o in offs
                if o.get(f"{method}_null_percentile_of_real") is not None]
    if not vals:
        return None
    ci = offset_bootstrap(vals)
    return {
        "n_offsets": len(vals),
        "mean_excess_cagr_vs_spy": float(np.mean(vals)),
        "std_excess_cagr_vs_spy": float(np.std(vals)),
        "min": float(np.min(vals)), "max": float(np.max(vals)),
        "n_offsets_positive": int(sum(v > 0 for v in vals)),
        "mean_excess_cagr_vs_usmv": float(np.mean(usmv_vals)) if usmv_vals else None,
        "mean_years_won": float(np.mean(years_won)) if years_won else None,
        "mean_n_years": float(np.mean(n_years)) if n_years else None,
        "bootstrap_ci95_between_offset": ci,
        "mean_null_percentile": float(np.mean(null_pct)) if null_pct else None,
    }


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--era", choices=["nominate", "holdout"], default="nominate")
    args = ap.parse_args()

    cells = load_cells(args.era)
    lines = [f"# Factor-composite reset -- {args.era} era report", ""]
    lines.append("Offset-averaged over all 40 grid offsets actually completed "
                  "(see PREREGISTRATION.md section 5). Not offset-0.\n")

    best = None
    table_rows = []
    for key, offs in cells.items():
        if not offs:
            lines.append(f"## {key}: NO COMPLETED OFFSETS YET\n")
            continue
        lines.append(f"## {key}  ({len(offs)}/{N_OFFSETS} offsets completed)\n")
        for method in ("decile_volq", "topn_ew"):
            for cost in (15, 50):
                s = summarize(offs, method, cost)
                if s is None:
                    continue
                lines.append(f"### {method}, {cost}bp round-trip")
                lines.append(f"- excess CAGR vs SPY: **{s['mean_excess_cagr_vs_spy']:+.2%}/yr** "
                             f"(sd across offsets {s['std_excess_cagr_vs_spy']:.2%}, "
                             f"range [{s['min']:+.2%}, {s['max']:+.2%}], "
                             f"{s['n_offsets_positive']}/{s['n_offsets']} offsets positive)")
                if s["bootstrap_ci95_between_offset"]:
                    ci = s["bootstrap_ci95_between_offset"]
                    lines.append(f"- between-offset bootstrap 95% CI: [{ci['lo95']:+.2%}, {ci['hi95']:+.2%}]")
                if s["mean_excess_cagr_vs_usmv"] is not None:
                    lines.append(f"- excess CAGR vs USMV: **{s['mean_excess_cagr_vs_usmv']:+.2%}/yr**")
                lines.append(f"- mean calendar years beaten: {s['mean_years_won']:.1f} of "
                             f"{s['mean_n_years']:.1f}")
                if s["mean_null_percentile"] is not None:
                    lines.append(f"- mean percentile vs matched shuffle null: "
                                 f"{s['mean_null_percentile']:.0%}")
                lines.append("")
                if cost == 15 and (best is None or s["mean_excess_cagr_vs_spy"] > best[2]):
                    best = (key, method, s["mean_excess_cagr_vs_spy"])
                table_rows.append((key, method, cost, s))

    if best:
        lines.append(f"\n## Nomination-era leader (15bp, excess vs SPY): "
                     f"**{best[0]} / {best[1]}** at {best[2]:+.2%}/yr\n")
        lines.append("Per PREREGISTRATION.md section 8, this is a candidate for the ONE "
                     "hold-out confirmation, subject to LOYO and Gate A checks not yet run here.\n")

    OUT_MD.parent.mkdir(parents=True, exist_ok=True)
    out_path = Path(str(OUT_MD).format(era=args.era))
    out_path.write_text("\n".join(lines))
    print(f"-> {out_path}")
    print("\n".join(lines))


if __name__ == "__main__":
    sys.exit(main())
