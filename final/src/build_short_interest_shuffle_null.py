"""
The FINRA short-interest backlog, screened with the shuffled-feature null --
on its OWN era, not the 2007-2020 nomination era `build_shuffle_null.py` uses.

    python3 build_short_interest_shuffle_null.py --plan
    python3 build_short_interest_shuffle_null.py --score
    python3 build_short_interest_shuffle_null.py --confirm --column short_interest_days_to_cover

WHY A SEPARATE SCRIPT
----------------------
Same reason as `build_options_shuffle_null.py`: this data starts 2020-04-15
(+8 business day publish lag), so across 2007-2020 it's empty. Mirrors that
script's design exactly -- own era via `portfolio.decile_series(era=...)`
directly on cached scores, own output file, never touching
`results_nominate.csv`.

THE ERA
-------
nominate  2020-04-15 .. 2025-01-01   (~4.7yr)
confirm   2025-01-01 .. present      (~1.7yr, untouched until --confirm)

Same nominate/confirm boundary convention as the options family for
consistency across this round's "own era" candidates.

METHOD
------
Identical to build_options_shuffle_null.py: own null per candidate, pooled
variance for degrees of freedom, BH correction across the 2 candidates,
decile_volq_excess primary. `--confirm` refused without
`--i-am-confirming`, only for a column that already cleared `--score`.
"""
import argparse
import json
import sys
from pathlib import Path

import numpy as np
import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parent))
from features import OUT_DIR, DATA_DIR                          # noqa: E402
from sweep import scorecache as SC                              # noqa: E402
from sweep import portfolio as P                                # noqa: E402
import build_shuffle_null as BSN                                # noqa: E402
import build_options_shuffle_null as BOSN                        # noqa: E402 (reuse _metrics)

RUNS = Path(__file__).resolve().parent / "sweep" / "runs"
PLAN = RUNS / "short_interest_backlog_cells.json"
MANIFEST = RUNS / "short_interest_backlog_manifest.json"
OUT_CSV = OUT_DIR / "sweep" / "short_interest_backlog_shuffle_null.csv"
OUTCOMES_PATH = OUT_DIR / "sweep" / "outcomes.parquet"

SI_NOMINATE_ERA = ("2020-04-15", "2025-01-01")
SI_CONFIRM_ERA = ("2025-01-01", "2027-01-01")

BASE = {"horizon": 40, "label": "q75", "label_basis": "tradable", "model": "xgb",
        "depth": 3, "eta": 0.1, "rounds": 100, "train": "expanding",
        "train_cap": 500000, "universe": "pit", "cap_tier": "all",
        "step": 40, "seed": 0}
METRICS = ["decile_volq_excess", "mult_ratio", "info_ratio"]
PRIMARY = "decile_volq_excess"


def _cfg(**kw):
    from sweep.scorecache import SignalConfig
    return SignalConfig(**{**BASE, **kw})


def plan(draws):
    RUNS.mkdir(parents=True, exist_ok=True)
    cells, man = [], {"candidates": [], "baseline": None, "draws": draws,
                      "era_nominate": SI_NOMINATE_ERA,
                      "era_confirm": SI_CONFIRM_ERA}

    base = _cfg(features="price_fund")
    cells.append(dict(base)); man["baseline"] = base.id

    for fs in SC.SHORT_INTEREST_BACKLOG_SETS:
        col = fs[3:]
        c = _cfg(features=fs)
        cells.append(dict(c))
        nulls = []
        for k in range(draws):
            n = _cfg(features=fs, shuffle_col=col, shuffle_seed=k)
            cells.append(dict(n))
            nulls.append(n.id)
        man["candidates"].append({"id": c.id, "featureset": fs, "column": col,
                                  "panel": SC.PANEL_FOR[fs], "null": nulls})

    PLAN.write_text(json.dumps(cells, indent=1))
    MANIFEST.write_text(json.dumps(man, indent=1))
    k = len(man["candidates"])
    todo = k * draws
    print(f"{k} candidates x {draws} own null draws = {todo} new null cells "
          f"+ {k} new real cells (+1 baseline, already cached)")
    print(f"  era: nominate {SI_NOMINATE_ERA}, confirm {SI_CONFIRM_ERA}")
    print(f"  ~{291 * (todo + k) / 3600:.1f}h of scoring\n")
    d = Path(__file__).resolve().parent
    print("run:")
    print(f"  cd {d}")
    print(f"  python3 -m sweep.cli scores --cells sweep/runs/{PLAN.name}")
    print(f"  python3 build_short_interest_shuffle_null.py --score")


def _load_prep(cid, tab):
    meta = json.load(open(SC.meta_path(cid)))
    H = int(meta["config"]["horizon"])
    scores = pd.read_parquet(SC.cache_path(cid))
    return P.Prepared(scores, tab, H, None), H


def score(q_max=0.20):
    man = json.loads(MANIFEST.read_text())
    tab = pd.read_parquet(OUTCOMES_PATH)
    tab["ticker"] = tab["ticker"].astype(str)
    era = tuple(man["era_nominate"])

    rows, resid = [], {m: [] for m in METRICS}
    base_vals = {}
    if SC.have(man["baseline"]):
        prep, H = _load_prep(man["baseline"], tab)
        base_vals = BOSN._metrics(prep, H, era)

    for c in man["candidates"]:
        if not SC.have(c["id"]):
            print(f"  [skip, not scored] {c['id']}")
            continue
        nid = [n for n in c["null"] if SC.have(n)]
        if len(nid) < 3:
            print(f"  [skip, only {len(nid)} null draws scored] {c['column']}")
            continue
        prep, H = _load_prep(c["id"], tab)
        real_m = BOSN._metrics(prep, H, era)
        null_m = {m: [] for m in METRICS}
        for nidid in nid:
            npz, _ = _load_prep(nidid, tab)
            mm = BOSN._metrics(npz, H, era)
            for m in METRICS:
                null_m[m].append(mm[m])
        r = {"column": c["column"], "n_null": len(nid)}
        for m in METRICS:
            v = np.array([x for x in null_m[m] if np.isfinite(x)])
            r[m] = real_m[m]
            r[f"null_{m}"] = float(v.mean()) if len(v) else np.nan
            r[f"pct_{m}"] = 100.0 * (v < real_m[m]).mean() if len(v) else np.nan
            if len(v):
                resid[m].append(v - v.mean())
        rows.append(r)

    if not rows:
        raise SystemExit("no candidate has enough scored null draws yet -- "
                         "run `cli.py scores --cells sweep/runs/short_interest_backlog_cells.json`")

    pooled, df = {}, 0
    for m in METRICS:
        e = np.concatenate(resid[m]) if resid[m] else np.array([])
        df = sum(r["n_null"] - 1 for r in rows)
        pooled[m] = float(np.sqrt((e ** 2).sum() / df)) if df > 0 and len(e) else np.nan

    print(f"era = nominate {era}")
    print(f"{len(rows)} candidates, pooled sd on df={df}")
    print(f"primary metric: {PRIMARY}   gate: BH q <= {q_max}\n")
    if base_vals:
        print(f"  baseline (price_fund, same era) {PRIMARY}: {base_vals[PRIMARY]:+.5f}\n")

    for r in rows:
        for m in METRICS:
            sd = pooled[m] * np.sqrt(1.0 + 1.0 / r["n_null"]) if np.isfinite(pooled[m]) else np.nan
            t = (r[m] - r[f"null_{m}"]) / sd if sd and sd > 0 else np.nan
            r[f"t_{m}"] = t
            r[f"p_{m}"] = BSN.t_sf(t, df) if np.isfinite(t) else np.nan
    d = pd.DataFrame(rows)
    for m in METRICS:
        d[f"q_{m}"] = BSN.bh(d[f"p_{m}"])
    d = d.sort_values(f"p_{PRIMARY}")

    print(f"{'column':<32}{'decile':>10}{'its null':>10}{'pct':>6}"
          f"{'t':>7}{'raw p':>9}{'BH q':>8}{'mult':>8}")
    for _, r in d.iterrows():
        print(f"{r['column']:<32}{r[PRIMARY]:>+10.5f}{r['null_' + PRIMARY]:>+10.5f}"
              f"{r['pct_' + PRIMARY]:>5.0f}%{r['t_' + PRIMARY]:>+7.2f}"
              f"{r['p_' + PRIMARY]:>9.4f}{r['q_' + PRIMARY]:>8.4f}{r['mult_ratio']:>8.3f}")

    d.to_csv(OUT_CSV, index=False)
    passed = d[d[f"q_{PRIMARY}"] <= q_max]
    print(f"\nPASS at BH q <= {q_max} on {PRIMARY}: "
          f"{', '.join(passed['column']) if len(passed) else 'NONE'}")
    if not len(passed):
        lib = d[d[f"p_{PRIMARY}"] <= 0.20]
        print(f"  raw p <= 0.20, UNCORRECTED ({len(d)} tests, expect "
              f"~{0.20 * len(d):.1f} by chance): "
              f"{', '.join(lib['column']) if len(lib) else 'none'}")
    print(f"\nwritten {OUT_CSV}")
    print("=== SCORING DONE ===")


def confirm(column, i_am_confirming):
    if not i_am_confirming:
        raise SystemExit(
            "refusing: --confirm spends the short-interest-era confirm window "
            "(2025-01-01..present), which is untouched. Pass "
            "--i-am-confirming to proceed, and only for a column that "
            "already passed --score.")
    man = json.loads(MANIFEST.read_text())
    cand = next((c for c in man["candidates"] if c["column"] == column), None)
    if cand is None:
        raise SystemExit(f"{column} not in the plan")
    tab = pd.read_parquet(OUTCOMES_PATH)
    tab["ticker"] = tab["ticker"].astype(str)
    era = tuple(man["era_confirm"])
    print(f"era = CONFIRM {era} -- SPENDING this window for '{column}'\n")
    for name, cid in [(f"candidate (+{column})", cand["id"]),
                      ("baseline (deployed price_fund)", man["baseline"])]:
        prep, H = _load_prep(cid, tab)
        m = BOSN._metrics(prep, H, era)
        print(f"{name}")
        print(f"  decile_volq_excess {m['decile_volq_excess']:+.5f}   "
              f"mult_ratio {m['mult_ratio']:.3f}   info_ratio {m['info_ratio']:.3f}")


if __name__ == "__main__":
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--plan", action="store_true")
    ap.add_argument("--score", action="store_true")
    ap.add_argument("--confirm", action="store_true")
    ap.add_argument("--column", default=None)
    ap.add_argument("--draws", type=int, default=8)
    ap.add_argument("--q-max", type=float, default=0.20)
    ap.add_argument("--i-am-confirming", action="store_true")
    a = ap.parse_args()
    if a.plan:
        plan(a.draws)
    elif a.score:
        score(a.q_max)
    elif a.confirm:
        if not a.column:
            raise SystemExit("--confirm needs --column")
        confirm(a.column, a.i_am_confirming)
    else:
        ap.error("pass --plan, --score, or --confirm --column <c> --i-am-confirming")
