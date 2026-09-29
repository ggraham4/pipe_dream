"""WO-23: combine the period A/B audit JSONs, apply the pre-registered flags
F1/F2 and S1 (final/models/2026-09-27-model-audit.md section 2.6) and print
markdown tables. Output: final/out/audit/model_audit_wo23.json"""
import json
from pathlib import Path

import numpy as np

OUT = Path(__file__).resolve().parents[2] / "out" / "audit"
A = json.loads((OUT / "model_audit_wo23_A.json").read_text())
B = json.loads((OUT / "model_audit_wo23_B.json").read_text())


def f(x, p=4, sign=True):
    if x is None or (isinstance(x, float) and not np.isfinite(x)):
        return "n/a"
    return f"{x:+.{p}f}" if sign else f"{x:.{p}f}"


def ws(fac):
    return bool(fac["wrong_signed"])


res = {"theoretical": {}, "blend": {}}
sdA, sdB = A["theoretical"]["icw9_seas"]["sd40"], B["theoretical"]["icw9_seas"]["sd40"]
lines = ["### Theoretical icw9_seas (cap150), per factor", "",
         "| factor | sign | live w | implied w A | implied w B | IC A (t) | IC B (t) | sector t A | sector t B | LOO delta A (sd40) | LOO delta B (sd40) | F1 | F2 |",
         "|---|---|---|---|---|---|---|---|---|---|---|---|---|"]
for k, a in A["theoretical"]["factors"].items():
    b = B["theoretical"]["factors"][k]
    f1 = ws(a) and ws(b)
    f2 = a["loo"]["delta_mean40"] < -sdA and b["loo"]["delta_mean40"] < -sdB
    res["theoretical"][k] = {"F1": f1, "F2": f2}
    lines.append(f"| {k} | {a['sign']:+d} | {f(a['current_weight'])} | {f(a['implied_weight'])} | {f(b['implied_weight'])} | "
                 f"{f(a['mean'])} ({f(a['t'],2)}){' WS' if ws(a) else ''} | {f(b['mean'])} ({f(b['t'],2)}){' WS' if ws(b) else ''} | "
                 f"{f(a['sector_both_sides_t'],2)} | {f(b['sector_both_sides_t'],2)} | "
                 f"{f(a['loo']['delta_mean40']*100,2)} ({f(a['loo']['delta_sd40']*100,2,False)}) | "
                 f"{f(b['loo']['delta_mean40']*100,2)} ({f(b['loo']['delta_sd40']*100,2,False)}) | {'FLAG' if f1 else '-'} | {'FLAG' if f2 else '-'} |")
lines += ["", f"LOO deltas in %/yr (full minus without; + = factor helps). F2 thresholds: sd40(full) A {sdA*100:.2f}, B {sdB*100:.2f} %/yr. WS = wrong-signed.", "",
          "### Blend composite leg (cap2000), per factor", "",
          "| factor | sign | live w | implied w A | implied w B | IC A (t) | IC B (t) | sector t A | sector t B | LOO delta A (1 grid) | LOO delta B (1 grid) | F1 |",
          "|---|---|---|---|---|---|---|---|---|---|---|---|"]
for k, a in A["blend"]["factors"].items():
    b = B["blend"]["factors"][k]
    f1 = ws(a) and ws(b)
    res["blend"][k] = {"F1": f1}
    lines.append(f"| {k} | {a['sign']:+d} | {f(a['current_weight'])} | {f(a['implied_weight'])} | {f(b['implied_weight'])} | "
                 f"{f(a['mean'])} ({f(a['t'],2)}){' WS' if ws(a) else ''} | {f(b['mean'])} ({f(b['t'],2)}){' WS' if ws(b) else ''} | "
                 f"{f(a['sector_both_sides_t'],2)} | {f(b['sector_both_sides_t'],2)} | "
                 f"{f(a['loo_single_grid']['delta']*100,2)} | {f(b['loo_single_grid']['delta']*100,2)} | {'FLAG' if f1 else '-'} |")

lines += ["", "### Model level (excess vs SPY, %/yr, net 15bp)", "",
          "| model | A mean | A sd40 | A LOYO min (yr) | A post-2011-10 | B mean | B sd40 | B LOYO min (yr) |", "|---|---|---|---|---|---|---|---|"]
for k in ("icw9_seas", "icw8"):
    a, b = A["theoretical"][k], B["theoretical"][k]
    lines.append(f"| {k} (40 offsets) | {f(a['excess_cagr_vs_spy_mean40']*100,2)} | {a['sd40']*100:.2f} | {f(a['loyo_min']*100,2)} ({a['loyo_min_dropped_year']}) | "
                 f"{f(a['post2011_10']*100,2)} | {f(b['excess_cagr_vs_spy_mean40']*100,2)} | {b['sd40']*100:.2f} | {f(b['loyo_min']*100,2)} ({b['loyo_min_dropped_year']}) |")
for k in ("blend_seas10", "blend_prev9"):
    a, b = A["blend"][k], B["blend"][k]
    lines.append(f"| {k} (1 grid, n={a['n_windows']}/{b['n_windows']}) | {f(a['excess_cagr_vs_spy']*100,2)} | - | {f(a['loyo_min']*100,2)} ({a['loyo_min_dropped_year']}) | "
                 f"{f(a['post2011_10']*100,2)} | {f(b['excess_cagr_vs_spy']*100,2)} | - | {f(b['loyo_min']*100,2)} ({b['loyo_min_dropped_year']}) |")
dA, dB = A["theoretical"]["icw9_minus_icw8"], B["theoretical"]["icw9_minus_icw8"]
lines += ["", f"icw9_seas - icw8: A {dA['mean40']*100:+.2f} (sd40 {dA['sd40']*100:.2f}), B {dB['mean40']*100:+.2f} (sd40 {dB['sd40']*100:.2f}) %/yr.",
          f"blend10 - blend9: A {A['blend']['blend10_minus_blend9']*100:+.2f}, B {B['blend']['blend10_minus_blend9']*100:+.2f} %/yr (single grid)."]

sb = B["theoretical"]["factors"]["seas"]
s1 = (sb["t"] <= 0) and (sb["loo"]["delta_mean40"] <= 0)
res["S1"] = {"seas_t_B": sb["t"], "seas_loo_delta_B": sb["loo"]["delta_mean40"], "triggered": bool(s1),
             "outcome": "recommend removal now" if s1 else "S2: removal decided at the forward ledgers' 6th counted date"}
lines += ["", f"S1: seas B t = {sb['t']:+.2f}, LOO delta B = {sb['loo']['delta_mean40']*100:+.2f} %/yr -> {res['S1']['outcome']}"]

# per-year IC tables
for model in ("theoretical", "blend"):
    fa, fb = A[model]["factors"], B[model]["factors"]
    yrs = sorted(set(int(y) for k in fa for y in fa[k]["per_year"]) | set(int(y) for k in fb for y in fb[k]["per_year"]))
    lines += ["", f"### Per-year mean daily IC, {model} ({'cap150' if model == 'theoretical' else 'cap2000'})", "",
              "| factor | " + " | ".join(str(y) for y in yrs) + " |", "|---|" + "---|" * len(yrs)]
    for k in fa:
        py = {**{int(y): v for y, v in fa[k]["per_year"].items()}, **{int(y): v for y, v in fb[k]["per_year"].items()}}
        lines.append(f"| {k} | " + " | ".join(f"{py[y]*100:+.1f}" if y in py else "n/a" for y in yrs) + " |")
    lines.append("")
    lines.append("Values are IC x 100. 2026 covers Jan-Jul (" +
                 str(next(iter(fb.values()))["per_year_n_dates"].get("2026", "?")) + " dates).")
res["flags_any"] = {"F1": [k for m in ("theoretical", "blend") for k, v in res[m].items() if v["F1"]],
                    "F2": [k for k, v in res["theoretical"].items() if v["F2"]]}
res["tables_md"] = "\n".join(lines)
(OUT / "model_audit_wo23.json").write_text(json.dumps({"A": A, "B": B, "flags": res}, indent=1, default=float))
print("\n".join(lines))
print("\nflags", res["flags_any"], "S1", res["S1"])
