"""
WO-11 overlap report: the live composite book (icw8 decile_volq) on the v1
panel vs the v2 working panel for 2026-09-08, per tier, plus the blend's
final picks v1 vs v2. Descriptive only (no return is read: forward labels on
2026-09-08 do not exist).

    v1: composite_panel.parquet, raw eligible_<tier> flags (the pre-switch live rule)
    v2: composite_panel_v2.parquet via working_panel.working_cross_section
        (v2 flags, SPACs excluded unless in the old 4,011-ticker grid)

Cross-checks: the cap150 v1 book == out/current_signal_composite_v1panel_2026-09-08.csv
and the cap150 v2 book == out/current_signal_composite.csv (the v2 rerun).

Output: out/reset2026/downcap_v2/wo11_overlap.json
"""
import json
import sys
from pathlib import Path

import numpy as np
import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parent))
import working_panel as W                  # noqa: E402
import forward_hedge as FH                 # noqa: E402

OUT = W.R26 / "downcap_v2" / "wo11_overlap.json"
O = W.MAIN_ROOT / "out"
DATE = pd.Timestamp("2026-09-08")
TIERS = ["cap150", "cap500", "cap2000"]
COLS = FH.PANEL_COLS + [f"eligible_{t}" for t in TIERS]


def overlap(a, b, key="ticker", w="weight", mcap="market_cap"):
    sa, sb = set(a[key]), set(b[key])
    inter = sa & sb
    wa, wb = a.set_index(key)[w], b.set_index(key)[w]
    wmin = float(sum(min(wa[t], wb[t]) for t in inter))

    def only(x, other):
        o = x[~x[key].isin(other)].sort_values(w, ascending=False).head(5)
        return [{"ticker": r[key], "weight": float(r[w]),
                 "market_cap": float(r[mcap]) if pd.notna(r[mcap]) else None,
                 **({"sector": r["sector"]} if "sector" in x.columns else {})} for _, r in o.iterrows()]
    return {"n_v1": len(sa), "n_v2": len(sb), "n_common": len(inter),
            "jaccard": len(inter) / len(sa | sb), "weight_overlap_sum_min": wmin,
            "top5_v1_not_v2": only(a, sb), "top5_v2_not_v1": only(b, sa)}


def main():
    v1, _ = W.working_cross_section(COLS, date=DATE, path=W.V1_PANEL, apply_universe_rule=False)
    v2, uinfo = W.working_cross_section(COLS, date=DATE)
    out = {"date": DATE.date().isoformat(), "v2_universe_rule": uinfo, "tiers": {}}
    for tier in TIERS:
        e1 = v1[v1[f"eligible_{tier}"]].reset_index(drop=True)
        e2 = v2[v2[f"eligible_{tier}"]].reset_index(drop=True)
        b1, i1 = FH.book_one_date(e1)
        b2, i2 = FH.book_one_date(e2)
        b1 = b1.merge(e1[["ticker", "sector"]], on="ticker")
        b2 = b2.merge(e2[["ticker", "sector"]], on="ticker")
        res = {"v1": i1, "v2": i2, **overlap(b1, b2)}
        if tier == "cap150":
            live1 = pd.read_csv(O / "current_signal_composite_v1panel_2026-09-08.csv")
            live2 = pd.read_csv(O / "current_signal_composite.csv")
            for tag, b, live in (("v1", b1, live1), ("v2", b2, live2)):
                m = b.merge(live[["ticker", "weight"]], on="ticker", how="outer", suffixes=("", "_live"))
                ok = m["weight"].notna().all() and m["weight_live"].notna().all() and \
                    float((m["weight"] - m["weight_live"]).abs().max()) < 1e-12
                res[f"equals_live_scorer_csv_{tag}"] = bool(ok)
        out["tiers"][tier] = res
        print(f"{tier}: v1 {res['n_v1']} v2 {res['n_v2']} common {res['n_common']} "
              f"jaccard {res['jaccard']:.3f} weight-overlap {res['weight_overlap_sum_min']:.3f}")

    bl1 = pd.read_csv(O / "current_signal_blend_v1panel_2026-09-08.csv")
    bl2 = pd.read_csv(O / "current_signal_blend.csv")
    out["blend"] = overlap(bl1, bl2)
    out["blend"]["max_abs_weight_diff_common"] = float(
        bl1.merge(bl2, on="ticker").pipe(lambda m: (m["weight_x"] - m["weight_y"]).abs().max()))
    print(f"blend: v1 {out['blend']['n_v1']} v2 {out['blend']['n_v2']} common {out['blend']['n_common']} "
          f"jaccard {out['blend']['jaccard']:.3f} weight-overlap {out['blend']['weight_overlap_sum_min']:.3f}")
    OUT.write_text(json.dumps(out, indent=2, default=str))
    print(f"-> {OUT}")


if __name__ == "__main__":
    main()
