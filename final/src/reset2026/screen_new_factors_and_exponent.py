"""
Two pre-registered tests (PREREGISTRATION.md's "Trial-count ledger and
next round (2026-09-22)" section, written before this ran):

1. IC screen for fcf_yield, leverage, profitability_trend -- one trial
   each, split-half (odd/even years), sign pre-declared.
2. Exponent variant: signed_rank_k -> sign(r)*|r|^p, p=2 fixed in advance,
   applied per-factor before the existing IC-shrinkage weighted sum.
   Tested the same genuinely-out-of-sample way as the weighting rule
   itself (fit on one half, IC measured on the other).

Usage: python3 screen_new_factors_and_exponent.py
"""
import json
import sys
import time
from pathlib import Path

import numpy as np
import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parent))
import composite as C            # noqa: E402
import ic_weighted_composite as ICW  # noqa: E402

MAIN_ROOT = Path("/Users/ggraham/pipe_dream/final")
PANEL_PATH = MAIN_ROOT / "out" / "reset2026" / "composite_panel.parquet"
NEWFACT_PATH = MAIN_ROOT / "out" / "reset2026" / "new_factors.parquet"
BETA_PATH = MAIN_ROOT / "out" / "reset2026" / "beta_feature.parquet"
OUT_JSON = MAIN_ROOT / "out" / "reset2026" / "new_factor_screens_report.json"
OUT_JSON_EXP = MAIN_ROOT / "out" / "reset2026" / "exponent_variant_report.json"

NOMINATE_START = pd.Timestamp("2007-01-02")
NOMINATE_END = pd.Timestamp("2019-12-31")
LABEL = "forward_return_tradable_40"
NW_LAG = 39
NEW_FACTOR_SIGNS = {"fcf_yield": +1, "leverage": -1, "profitability_trend": +1}
EXPONENT_P = 2.0


def log(msg):
    print(f"[{time.strftime('%H:%M:%S')}] {msg}", flush=True)


def newey_west_mean_t(x, lag=NW_LAG):
    x = np.asarray(x, dtype=np.float64)
    x = x[np.isfinite(x)]
    n = len(x)
    if n < 10:
        return {"mean": np.nan, "t": np.nan, "n": n}
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


def part1_new_factor_screens(nom):
    log("\n=== Part 1: new factor IC screens ===")
    report = {}
    for c, sign in NEW_FACTOR_SIGNS.items():
        full = pooled_ic(nom, c, LABEL)
        years = nom["date"].dt.year
        odd = pooled_ic(nom[years % 2 == 1], c, LABEL)
        even = pooled_ic(nom[years % 2 == 0], c, LABEL)
        measured_sign = int(np.sign(full["mean"])) if np.isfinite(full["mean"]) else 0
        report[c] = {
            "assigned_sign": sign, "pooled": full, "odd_years": odd, "even_years": even,
            "measured_sign": measured_sign, "sign_matches": measured_sign == sign,
        }
        log(f"  {c:22s} IC={full['mean']:+.4f} t={full['t']:+.2f}  "
            f"odd={odd['mean']:+.4f}(t={odd['t']:+.2f}) even={even['mean']:+.4f}(t={even['t']:+.2f})  "
            f"assigned={sign:+d} matches={report[c]['sign_matches']}")
    return report


def compute_exponent_weighted_score(df_date, weights, p):
    factor_cols = list(weights)
    weighted = pd.DataFrame(index=df_date.index)
    avail_weight = pd.DataFrame(index=df_date.index)
    for c in factor_cols:
        rz = C.rank_z(df_date[c])
        rz_pow = np.sign(rz) * (rz.abs() ** p)
        weighted[c] = rz_pow * weights[c]
        avail_weight[c] = np.where(rz.notna(), abs(weights[c]), 0.0)
    total_avail = avail_weight.sum(axis=1)
    raw_sum = weighted.sum(axis=1, skipna=True)
    coverage = weighted.notna().sum(axis=1)
    out = pd.Series(np.where(total_avail > 0, raw_sum / total_avail, np.nan), index=df_date.index)
    out[coverage == 0] = np.nan
    return out


def fit_weights_from_t(t_stats, factor_cols, floor=0.1):
    raw = {}
    for c in factor_cols:
        t = t_stats[c]["t"]
        mag = max(floor, abs(t) - 1.0) if np.isfinite(t) else floor
        raw[c] = C.FACTOR_SIGNS[c] * mag
    total = sum(abs(v) for v in raw.values())
    return {c: raw[c] / total for c in factor_cols}


def per_factor_t(nom, factor_cols):
    return {c: pooled_ic(nom, c, LABEL) for c in factor_cols}


def score_ic(nom, weights, p, factor_cols, label=""):
    parts = []
    for d, g in nom.groupby("date"):
        gg = g.reset_index(drop=True)
        s = compute_exponent_weighted_score(gg, weights, p)
        parts.append(pd.DataFrame({"date": d, "score": s.to_numpy(), "label": gg[LABEL].to_numpy()}))
    scored = pd.concat(parts, ignore_index=True)
    ic = pooled_ic(scored, "score", "label")
    log(f"  [{label}] IC={ic['mean']:+.4f} t={ic['t']:+.2f} n={ic['n_dates']}")
    return ic


def part2_exponent_variant(nom):
    log(f"\n=== Part 2: exponent variant (p={EXPONENT_P}), genuinely out-of-sample ===")
    factor_cols = C.FACTOR_COLS
    years = nom["date"].dt.year
    odd = nom[years % 2 == 1]
    even = nom[years % 2 == 0]

    t_odd = per_factor_t(odd, factor_cols)
    t_even = per_factor_t(even, factor_cols)
    w_odd = fit_weights_from_t(t_odd, factor_cols)
    w_even = fit_weights_from_t(t_even, factor_cols)

    report = {}
    log("fit-odd -> test-even:")
    report["exponent_p2_fit_odd_test_even"] = score_ic(even, w_odd, EXPONENT_P, factor_cols, "p=2, fit-odd/test-even")
    report["linear_p1_fit_odd_test_even"] = score_ic(even, w_odd, 1.0, factor_cols, "p=1 (baseline), fit-odd/test-even")

    log("fit-even -> test-odd:")
    report["exponent_p2_fit_even_test_odd"] = score_ic(odd, w_even, EXPONENT_P, factor_cols, "p=2, fit-even/test-odd")
    report["linear_p1_fit_even_test_odd"] = score_ic(odd, w_even, 1.0, factor_cols, "p=1 (baseline), fit-even/test-odd")

    return report


def main():
    t0 = time.time()
    need = list(dict.fromkeys(["ticker", "date", "eligible_cap150", LABEL] + C.FACTOR_COLS))
    panel = pd.read_parquet(PANEL_PATH, columns=need)
    panel["date"] = pd.to_datetime(panel["date"])
    panel["ticker"] = panel["ticker"].astype(str)

    newfact = pd.read_parquet(NEWFACT_PATH)
    newfact["date"] = pd.to_datetime(newfact["date"])
    newfact["ticker"] = newfact["ticker"].astype(str)
    panel = panel.merge(newfact, on=["ticker", "date"], how="left")

    nom = panel[(panel["date"] >= NOMINATE_START) & (panel["date"] <= NOMINATE_END)
                & panel["eligible_cap150"]].copy()
    log(f"nomination-era cap150-eligible rows: {len(nom):,}")

    r1 = part1_new_factor_screens(nom)
    OUT_JSON.parent.mkdir(parents=True, exist_ok=True)
    with open(OUT_JSON, "w") as f:
        json.dump(r1, f, indent=2, default=str)
    log(f"wrote {OUT_JSON}")

    r2 = part2_exponent_variant(nom)
    with open(OUT_JSON_EXP, "w") as f:
        json.dump(r2, f, indent=2, default=str)
    log(f"wrote {OUT_JSON_EXP}")

    log(f"\ndone ({time.time()-t0:.0f}s total)")


if __name__ == "__main__":
    main()
