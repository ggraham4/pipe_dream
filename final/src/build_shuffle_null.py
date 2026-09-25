"""
The shuffled-feature null: does a candidate column improve the PORTFOLIO?

    python3 build_shuffle_null.py --plan                 write the run files
    python3 build_shuffle_null.py --score                read results, verdict

WHY THIS REPLACES THE IC GATE
-----------------------------
Gabe, 2026-09-16: "our thresholds are so strict that they would exclude features
already in the model."

He is right, and the numbers are not close. On `sweep.cli features`, nomination
era, h=40:

    volatility_60      t -0.41     60.3% of XGBoost's importance
    momentum_20        t +0.23     production feature, flips sign on 16/40 grids
    accel_20           t +1.88     rejected on this evidence

A screen that rejects the model's single most important feature cannot decide
what goes in the model. Three things are wrong with it at once: IC weights all
~1,600 names equally while the book holds 5; the non-overlapping grid makes the
estimate offset-dependent for any weak feature (check_grid_offset.py); and none
of it is denominated in what the portfolio earns.

THE REPLACEMENT
---------------
Metric: what the portfolio does. `decile_volq_excess` for power (top 10% within
each volatility quintile -- the selection rule the book actually uses, with
enough names to resolve) plus compounded ratio vs SPY for the traded answer.

Null: refit the SAME cell with the candidate column PERMUTED WITHIN EACH DATE.
Same marginals, same column count, cross-sectional information destroyed.
Dropping the column instead would change the model's shape and confound "this
feature carries nothing" with "24 columns behave differently from 25".

Gate: the real cell must beat the 80th percentile of the null distribution.
That is a 20% false-pass rate per feature, which is Gabe's chosen trade for a
single candidate; screening many features this way needs a correction and this
script prints the reminder.

WHY ONE SHARED NULL SERVES MANY CANDIDATES
------------------------------------------
The null asks what adding an UNINFORMATIVE column of a given shape does to this
model. That barely depends on which column was scrambled, so N draws can be
shared across candidates instead of paying N per candidate -- 23 rejected
features would otherwise cost ~37 hours. `--sources` draws the shuffles from
more than one CANDIDATE column so the assumption is testable rather than
assumed: if the per-source null distributions differ materially, the shared null
is invalid and this script says so at --score time.

A source must never be a production feature. Permuting momentum_20 does not
sample accel_20's null -- it builds a model that has LOST real information,
which lands far below the null and would make any candidate look like a pass.
plan() refuses it.

COST
----
One cell is ~291s on Gabe's machine. --draws 20 is ~1.6h.
"""
import argparse
import json
import subprocess
import sys
from pathlib import Path

import numpy as np
import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parent))
from features import OUT_DIR                                  # noqa: E402

RUNS = Path(__file__).resolve().parent / "sweep" / "runs"
RESULTS = OUT_DIR / "sweep" / "results_nominate.csv"
PLAN = RUNS / "shuffle_null_cells.json"
BPLAN = RUNS / "backlog_cells.json"
BMANIFEST = RUNS / "backlog_manifest.json"
GRID = RUNS / "shuffle_null_portfolio.json"
MANIFEST = RUNS / "shuffle_null_manifest.json"

BASE = {"horizon": 40, "label": "q75", "label_basis": "tradable", "model": "xgb",
        "depth": 3, "eta": 0.1, "rounds": 100, "train": "expanding",
        "train_cap": 500000, "universe": "pit", "cap_tier": "all",
        "step": 40, "seed": 0}
PORTFOLIO = [{"top_n": 5, "weighting": "invvol", "bucket": "volq",
              "cost_bps": 15.0, "cost_model": "turnover", "untradable": "drop"}]
# decile_volq_excess FIRST: it is the primary. mult_ratio is reported beside
# it and is no longer the gate -- a 5-name book's compounded multiple swings
# from 1.06x to 2.97x on a single column swap, which is luck, not signal.
METRICS = ["decile_volq_excess", "mult_ratio", "info_ratio"]
PRIMARY = "decile_volq_excess"


def _cfg(**kw):
    from sweep.scorecache import SignalConfig
    return SignalConfig(**{**BASE, **kw})


def _betacf(a, b, x, itmax=300, eps=3e-16):
    """Continued fraction for the incomplete beta (Lentz). No scipy."""
    qab, qap, qam = a + b, a + 1.0, a - 1.0
    c, d = 1.0, 1.0 - qab * x / qap
    if abs(d) < 1e-300:
        d = 1e-300
    d = 1.0 / d
    h = d
    for m in range(1, itmax + 1):
        m2 = 2 * m
        aa = m * (b - m) * x / ((qam + m2) * (a + m2))
        d = 1.0 + aa * d
        if abs(d) < 1e-300:
            d = 1e-300
        c = 1.0 + aa / c
        if abs(c) < 1e-300:
            c = 1e-300
        d = 1.0 / d
        h *= d * c
        aa = -(a + m) * (qab + m) * x / ((a + m2) * (qap + m2))
        d = 1.0 + aa * d
        if abs(d) < 1e-300:
            d = 1e-300
        c = 1.0 + aa / c
        if abs(c) < 1e-300:
            c = 1e-300
        d = 1.0 / d
        delta = d * c
        h *= delta
        if abs(delta - 1.0) < eps:
            break
    return h


def _betainc(a, b, x):
    from math import exp, lgamma
    if x <= 0.0:
        return 0.0
    if x >= 1.0:
        return 1.0
    lb = (lgamma(a + b) - lgamma(a) - lgamma(b)
          + a * np.log(x) + b * np.log(1.0 - x))
    if x < (a + 1.0) / (a + b + 2.0):
        return exp(lb) * _betacf(a, b, x) / a
    return 1.0 - exp(lb) * _betacf(b, a, 1.0 - x) / b


def t_sf(t, df):
    """One-sided P(T > t) for Student's t. df from the null draws."""
    t, df = float(t), float(df)
    if df <= 0 or not np.isfinite(t):
        return float("nan")
    x = df / (df + t * t)
    p = 0.5 * _betainc(df / 2.0, 0.5, x)
    return p if t > 0 else 1.0 - p


def parametric_p(real, null):
    """One-sided p that the real cell is drawn from the null distribution.

    Uses the PREDICTION form -- sd * sqrt(1 + 1/n) -- because the question is
    whether ONE new observation belongs to that distribution, not whether its
    mean differs. The plain standard error would be too narrow and would
    manufacture significance.

    Parametric rather than the empirical rank because the empirical p is
    floored at 1/(n+1): with 25 draws that is 0.038, and Benjamini-Hochberg
    across 15 candidates needs the best one under 0.20/15 = 0.013 to reject
    anything at all. An empirical-rank gate with this many draws is GUARANTEED
    to fail every candidate regardless of the data, which is not a test.
    """
    v = np.asarray([x for x in null if np.isfinite(x)], dtype=float)
    n = len(v)
    if n < 5:
        return float("nan"), float("nan")
    sd = v.std(ddof=1)
    if sd <= 0:
        return float("nan"), float("nan")
    t = (float(real) - v.mean()) / (sd * np.sqrt(1.0 + 1.0 / n))
    return t, t_sf(t, n - 1)


def bh(pvals):
    """Benjamini-Hochberg q-values, order preserved, monotone-enforced."""
    p = np.asarray(list(pvals), dtype=float)
    ok = np.isfinite(p)
    q = np.full(len(p), np.nan)
    if not ok.any():
        return q
    pp = p[ok]
    m = len(pp)
    o = np.argsort(pp)
    ranked = pp[o] * m / np.arange(1, m + 1)
    ranked = np.minimum.accumulate(ranked[::-1])[::-1]
    qq = np.empty(m)
    qq[o] = np.clip(ranked, 0.0, 1.0)
    q[ok] = qq
    return q


def plan(featureset, candidate, sources, draws):
    # A shuffle source must be a CANDIDATE, never a production feature.
    # Permuting momentum_20 or volatility_60 does not sample this candidate's
    # null -- it builds a model that has LOST real information, which lands far
    # below the null and would make any candidate look like a pass. The first
    # version of this script defaulted to exactly that.
    from features import FEATURE_COLS
    bad = [c for c in sources if c in FEATURE_COLS]
    if bad:
        raise SystemExit(
            f"shuffle source(s) {bad} are production features in FEATURE_COLS. "
            f"Shuffling those measures the cost of DESTROYING information, not "
            f"the null for adding an uninformative column. Use candidate "
            f"columns only.")
    RUNS.mkdir(parents=True, exist_ok=True)
    cells, manifest = [], {"featureset": featureset, "candidate": candidate,
                           "sources": sources, "draws": draws,
                           "real": None, "null": [], "baseline": None}

    real = _cfg(features=featureset)
    cells.append(dict(real)); manifest["real"] = real.id

    # The incumbent, for context. Already cached, so it costs nothing.
    base = _cfg(features="price_fund")
    cells.append(dict(base)); manifest["baseline"] = base.id

    per = max(1, draws // len(sources))
    for si, src in enumerate(sources):
        for k in range(per):
            c = _cfg(features=featureset, shuffle_col=src,
                     shuffle_seed=1000 * si + k)
            cells.append(dict(c))
            manifest["null"].append({"id": c.id, "source": src,
                                     "seed": 1000 * si + k})

    PLAN.write_text(json.dumps(cells, indent=1))
    GRID.write_text(json.dumps(PORTFOLIO, indent=1))
    MANIFEST.write_text(json.dumps(manifest, indent=1))
    n = len(manifest["null"])
    print(f"planned {len(cells)} cells: 1 real + 1 baseline + {n} null draws")
    print(f"  shuffle sources: {', '.join(sources)} ({per} draws each)")
    print(f"  ~{291 * (len(cells) - 1) / 3600:.1f}h of scoring "
          f"(the baseline is already cached)\n")
    print("run:")
    print(f"  cd {Path(__file__).resolve().parent}")
    print(f"  python3 -m sweep.cli scores --cells {PLAN.relative_to(Path(__file__).resolve().parent)}")
    print(f"  python3 -m sweep.cli portfolio --grid "
          f"{GRID.relative_to(Path(__file__).resolve().parent)} --era nominate")
    print(f"  python3 build_shuffle_null.py --score")


def score(pctile):
    man = json.loads(MANIFEST.read_text())
    if not RESULTS.exists():
        raise SystemExit(f"{RESULTS} not found -- run the portfolio step first")
    res = pd.read_csv(RESULTS).drop_duplicates("cell_id", keep="last")
    r = res.set_index("cell_id")

    missing = [c["id"] for c in man["null"] if c["id"] not in r.index]
    if man["real"] not in r.index:
        raise SystemExit(f"real cell {man['real']} not in results")
    if missing:
        print(f"WARNING: {len(missing)} of {len(man['null'])} null cells "
              f"missing from results; scoring on what is there.")
    null = [c for c in man["null"] if c["id"] in r.index]
    if len(null) < 5:
        raise SystemExit(f"only {len(null)} null draws -- refusing to quote a "
                         f"percentile")

    print(f"candidate: {man['candidate']}   feature set: {man['featureset']}")
    print(f"{len(null)} null draws, gate = beat the {pctile}th percentile\n")

    # Is the shared null actually shared? If sources disagree, it is not.
    print("exchangeability of the shuffle sources (shared null is only valid "
          "if these agree):")
    for m in METRICS:
        by = {}
        for c in null:
            by.setdefault(c["source"], []).append(float(r.loc[c["id"], m]))
        line = "   ".join(f"{s}: {np.mean(v):+.4f}+-{np.std(v):.4f} (n={len(v)})"
                          for s, v in by.items())
        print(f"  {m:<12} {line}")
        if len(by) > 1:
            means = [np.mean(v) for v in by.values()]
            sds = [np.std(v) for v in by.values()]
            if max(means) - min(means) > 1.5 * max(sds):
                print(f"    ^ SOURCES DISAGREE on {m}: the shared null is not "
                      f"valid for this metric; draw a null per candidate.")

    print(f"\n{'metric':<14}{'real':>10}{'baseline':>11}{'null p50':>11}"
          f"{f'null p{pctile}':>11}{'pctile':>9}   verdict")
    verdicts = {}
    for m in METRICS:
        real = float(r.loc[man["real"], m])
        basev = (float(r.loc[man["baseline"], m])
                 if man["baseline"] in r.index else float("nan"))
        v = np.array([float(r.loc[c["id"], m]) for c in null])
        p50, pgate = np.percentile(v, 50), np.percentile(v, pctile)
        pc = 100.0 * (v < real).mean()
        ok = real > pgate
        verdicts[m] = ok
        print(f"  {m:<12}{real:>10.4f}{basev:>11.4f}{p50:>11.4f}{pgate:>11.4f}"
              f"{pc:>8.0f}%   {'PASS' if ok else 'fail'}")

    primary = "mult_ratio"
    print(f"\nVERDICT on {primary}: "
          f"{'PASS' if verdicts[primary] else 'FAIL'} "
          f"-- the real cell is at the {100.0 * (np.array([float(r.loc[c['id'], primary]) for c in null]) < float(r.loc[man['real'], primary])).mean():.0f}th "
          f"percentile of what a scrambled column of the same shape achieves.")
    print(f"\n  A {pctile}th-percentile gate is a {100 - pctile}% false-pass "
          f"rate PER FEATURE. Screening k features this way needs a correction; "
          f"with k=23 (the rejected backlog) expect ~{0.01 * (100 - pctile) * 23:.0f} "
          f"to pass on noise alone.")


# --------------------------------------------------------------------------
# The backlog: every candidate rejected on the retired IC gate
# --------------------------------------------------------------------------
def plan_backlog(draws, null_source=None):
    """One cell per candidate, plus ITS OWN null. No shared null.

    The shared-null run of 2026-09-16 passed 11 of 15 candidates and was an
    artifact. Two nulls measured on the same era and construction came back at
    1.919 +- 0.415 (shuffling accel_20) and 1.230 +- 0.330 (shuffling
    earnings_in_window) -- a gap of two standard deviations, not explained by
    the column's cardinality (rank corr with the result +0.066). Adding ONE
    column to a 24-column model moves the backtest from 1.06x to 2.97x whether
    that column is real or scrambled, so the null's location is a property of
    the specific column slot and cannot be borrowed from another candidate.

    `draws` per candidate, with the variance POOLED across candidates at score
    time: 8 draws gives a poor per-candidate sd but a fine per-candidate mean,
    and pooling buys df = k*(draws-1) for the spread. That is the standard
    trade and it is what makes 8 draws workable instead of 25.
    """
    from sweep.scorecache import BACKLOG_SETS, PANEL_FOR
    RUNS.mkdir(parents=True, exist_ok=True)
    cells, man = [], {"candidates": [], "baseline": None, "draws": draws,
                      "design": "per-candidate null, pooled variance"}

    base = _cfg(features="price_fund")
    cells.append(dict(base)); man["baseline"] = base.id

    for fs in BACKLOG_SETS:
        col = fs[3:]
        c = _cfg(features=fs)
        cells.append(dict(c))
        nulls = []
        for k in range(draws):
            n = _cfg(features=fs, shuffle_col=col, shuffle_seed=k)
            cells.append(dict(n))
            nulls.append(n.id)
        man["candidates"].append({"id": c.id, "featureset": fs, "column": col,
                                  "panel": PANEL_FOR[fs], "null": nulls})

    BPLAN.write_text(json.dumps(cells, indent=1))
    GRID.write_text(json.dumps(PORTFOLIO, indent=1))
    BMANIFEST.write_text(json.dumps(man, indent=1))
    k = len(man["candidates"])
    todo = k * draws                     # the real cells are already cached
    print(f"{k} candidates x {draws} own null draws = {todo} new cells "
          f"(+{k} real and 1 baseline, already cached)")
    print(f"  ~{291 * todo / 3600:.1f}h\n")
    d = Path(__file__).resolve().parent
    print("run (live output AND a log; prints a DONE banner when finished):\n")
    print(f"  cd {d}")
    print(f"  ( python3 -m sweep.cli scores --cells sweep/runs/{BPLAN.name} 2>&1; \\")
    print(f"    echo \"=== SCORES DONE $(date) ===\" ) | tee ../out/backlog2.log")
    print()
    print(f"  ( python3 -m sweep.cli portfolio --grid sweep/runs/{GRID.name} "
          f"--era nominate 2>&1; \\")
    print(f"    echo \"=== PORTFOLIO DONE $(date) ===\" ) | tee ../out/backlog2_pf.log")
    print(f"  python3 build_shuffle_null.py --score-backlog")


def score_backlog(q_max=0.20):
    man = json.loads(BMANIFEST.read_text())
    res = pd.read_csv(RESULTS).drop_duplicates("cell_id", keep="last").set_index("cell_id")
    if PRIMARY not in res.columns:
        raise SystemExit(f"{PRIMARY} not in results -- rerun the portfolio step "
                         f"so sweep.cli writes the new metric.")
    base = {m: (float(res.loc[man["baseline"], m])
                if man["baseline"] in res.index else float("nan"))
            for m in METRICS}

    # Pass 1: per-candidate mean, and the residuals that feed the pooled sd.
    rows, resid = [], {m: [] for m in METRICS}
    for c in man["candidates"]:
        if c["id"] not in res.index:
            continue
        nid = [i for i in c["null"] if i in res.index]
        if len(nid) < 3:
            continue
        r = {"column": c["column"], "panel": c["panel"].split("_")[2],
             "n_null": len(nid)}
        for m in METRICS:
            v = np.array([float(res.loc[i, m]) for i in nid])
            r[m] = float(res.loc[c["id"], m])
            r[f"null_{m}"] = v.mean()
            r[f"pct_{m}"] = 100.0 * (v < r[m]).mean()
            resid[m].append(v - v.mean())
        rows.append(r)
    if not rows:
        raise SystemExit("no candidate has enough scored null draws yet")

    # Pooled sd: one spread for all candidates, df = sum(n_i - 1).
    pooled, df = {}, 0
    for m in METRICS:
        e = np.concatenate(resid[m])
        df = sum(r["n_null"] - 1 for r in rows)
        pooled[m] = float(np.sqrt((e ** 2).sum() / df)) if df > 0 else np.nan

    n_mean = np.mean([r["n_null"] for r in rows])
    print(f"{len(rows)} candidates, {n_mean:.0f} own null draws each, "
          f"pooled sd on df={df}")
    print(f"primary metric: {PRIMARY}   gate: BH q <= {q_max}\n")
    for m in METRICS:
        print(f"  pooled null sd, {m:<20} {pooled[m]:.5f}"
              f"   baseline price_fund {base[m]:+.5f}")
    print()

    for r in rows:
        for m in METRICS:
            sd = pooled[m] * np.sqrt(1.0 + 1.0 / r["n_null"])
            t = (r[m] - r[f"null_{m}"]) / sd if sd > 0 else np.nan
            r[f"t_{m}"] = t
            r[f"p_{m}"] = t_sf(t, df)
    d = pd.DataFrame(rows)
    for m in METRICS:
        d[f"q_{m}"] = bh(d[f"p_{m}"])
    d = d.sort_values(f"p_{PRIMARY}")

    print(f"{'column':<30}{'panel':<8}{'decile':>9}{'its null':>10}{'pct':>6}"
          f"{'t':>7}{'raw p':>9}{'BH q':>8}{'mult':>8}")
    for _, r in d.iterrows():
        print(f"{r['column']:<30}{r['panel']:<8}{r[PRIMARY]:>+9.5f}"
              f"{r['null_' + PRIMARY]:>+10.5f}{r['pct_' + PRIMARY]:>5.0f}%"
              f"{r['t_' + PRIMARY]:>+7.2f}{r['p_' + PRIMARY]:>9.4f}"
              f"{r['q_' + PRIMARY]:>8.4f}{r['mult_ratio']:>8.3f}")

    out = OUT_DIR / "sweep" / "backlog_shuffle_null.csv"
    d.to_csv(out, index=False)
    passed = d[d[f"q_{PRIMARY}"] <= q_max]
    print(f"\nPASS at BH q <= {q_max} on {PRIMARY}: "
          f"{', '.join(passed['column']) if len(passed) else 'NONE'}")
    if not len(passed):
        lib = d[d[f"p_{PRIMARY}"] <= 0.20]
        print(f"  raw p <= 0.20, UNCORRECTED ({len(d)} tests, expect "
              f"~{0.20 * len(d):.0f} by chance): "
              f"{', '.join(lib['column']) if len(lib) else 'none'}")
        print("  Leads to retest, not results.")
    agree = d[(d[f"q_{PRIMARY}"] <= q_max) & (d["pct_mult_ratio"] >= 80)]
    if len(passed):
        print(f"  also top-quintile on mult_ratio: "
              f"{', '.join(agree['column']) if len(agree) else 'none'} "
              f"(agreement between the two metrics is the reassuring case)")
    print(f"\nwritten {out}")
    print("=== SCORING DONE ===")


if __name__ == "__main__":
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--plan-backlog", action="store_true")
    ap.add_argument("--score-backlog", action="store_true")
    ap.add_argument("--null-source", default=None)
    ap.add_argument("--q-max", type=float, default=0.20)
    ap.add_argument("--plan", action="store_true")
    ap.add_argument("--score", action="store_true")
    ap.add_argument("--featureset", default="price_fund_path")
    ap.add_argument("--candidate", default="accel_20")
    ap.add_argument("--sources", default="accel_20",
                    help="CANDIDATE columns to draw shuffles from (never a "
                         "production feature -- see plan()). Naming more than "
                         "one tests whether a shared null is exchangeable.")
    ap.add_argument("--draws", type=int, default=20)
    ap.add_argument("--pctile", type=float, default=80)
    a = ap.parse_args()
    if a.plan_backlog:
        plan_backlog(a.draws)
    elif a.score_backlog:
        score_backlog(a.q_max)
    elif a.plan:
        plan(a.featureset, a.candidate,
             [s.strip() for s in a.sources.split(",") if s.strip()], a.draws)
    elif a.score:
        score(a.pctile)
    else:
        ap.error("pass --plan, --score, --plan-backlog or --score-backlog")
