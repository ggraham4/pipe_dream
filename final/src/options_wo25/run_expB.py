"""
WO-25 Experiment B runner: AV option factors, as pre-registered in
PREREGISTRATION.md "Experiment B" + "Amendment 1" (cap2000 primary), with the
clarifications and the companion portfolio check fixed in
final/models/2026-09-29-options-readiness-wo25.md section 3.

    # Phase 1 plumbing (no real labels; output names carry _SHUFFLED_TEST):
    python run_expB.py --labels shuffled --stage screen
    python run_expB.py --labels noise    --stage screen
    python run_expB.py --labels shuffled --stage confirm --test-confirm-on-nominate
    # Phase 2 (real labels; guarded):
    python run_expB.py --phase2 --stage screen
    python run_expB.py --phase2 --stage confirm      # ONE shot, hold-out read #7

Shared machinery (NW t, per-date Spearman IC, IC-shrinkage weight rule,
coverage-renormalised rank score, sector neutralisation) is imported from
reset2026/era_transfer.py, never edited. Two deviations from that file are
fixes stated in the pre-registration doc: (3) all 9 weights refit together,
(4) the null refits the shuffled candidate's weight on every draw.

Label modes
  real      Phase 2 only (--phase2).
  shuffled  forward_return_tradable_40 and gross_return_40 permuted within date
            with ONE shared permutation; gross_return_40 then demeaned per date
            and SPY set to 0, so no market-level outcome survives.
  noise     iid N(0, 0.15) labels, SPY = 0.
"""
from __future__ import annotations

import argparse
import json
import subprocess
import sys
import time
from pathlib import Path

import numpy as np
import pandas as pd
from scipy.stats import norm

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE.parent / "reset2026"))
import composite as C          # noqa: E402
import era_transfer as ET      # noqa: E402
import run_backtest as RB      # noqa: E402
sys.path.insert(0, str(HERE))
from wo25_io import read_on_dates  # noqa: E402

MAIN = Path("/Users/ggraham/pipe_dream/final")
REPO = HERE.parents[2]
OUT = HERE.parents[1] / "out" / "options_wo25"
FEATS = OUT / "av_options_features_wo25.parquet"
PANEL_V2 = MAIN / "out" / "reset2026" / "composite_panel_v2.parquet"
OUTCOME_V2 = MAIN / "out" / "reset2026" / "outcome_cache_v2.parquet"
UNIVERSE_V2 = MAIN / "data" / "sharadar" / "downcap_universe_v2.parquet"
PREREG_DOC = "final/models/2026-09-29-options-readiness-wo25.md"
ARRIVAL = OUT / "arrival_report.json"
LABEL = ET.LABEL
BASE_SIGNS = ET.BASE_SIGNS
OPTION_SIGNS = ET.OPTION_SIGNS
NOMINATE_B, CONFIRM_B = ET.NOMINATE_B, ET.CONFIRM_B
NULL_DRAWS, NULL_PCTILE = ET.NULL_DRAWS, ET.NULL_PCTILE
COST_BPS = 15.0
N_OFFSETS = 2          # monthly dates ~20-25 trading days apart: every other date ~ one 40d window
MIN_NOMINATE_DATES = 120
log = ET.log


# ------------------------------------------------------------------ guards
def phase2_guard(stage):
    try:
        subprocess.run(["git", "-C", str(REPO), "ls-files", "--error-unmatch", PREREG_DOC],
                       check=True, capture_output=True)
    except subprocess.CalledProcessError:
        raise SystemExit(f"--phase2 refused: {PREREG_DOC} is not committed")
    if not ARRIVAL.exists():
        raise SystemExit("--phase2 refused: run check_arrival.py first")
    arr = json.loads(ARRIVAL.read_text())
    if arr.get("overall") != "PASS":
        raise SystemExit("--phase2 refused: arrival_report overall != PASS")
    if stage == "screen" and not arr.get("exp_b_screen_ready"):
        raise SystemExit("--phase2 refused: fewer than 120 nominate-era dates complete at cap2000")
    if stage == "confirm" and not arr.get("exp_b_confirm_ready"):
        raise SystemExit("--phase2 refused: 2019-01..2026-08 not complete at cap2000")


# ------------------------------------------------------------------ data
def load(start, end, feats_path):
    f = pd.read_parquet(feats_path)
    f = f[f.source == "av_monthly"].drop(columns=["source"])
    f["date"] = pd.to_datetime(f["date"])
    f = f[(f.date >= start) & (f.date <= end)]
    dates = sorted(f.date.unique())
    if not dates:
        raise SystemExit(f"no av_monthly feature dates in {start.date()}..{end.date()}")
    cols = ["ticker", "date", "sector", LABEL, "volatility_60", "eligible_cap2000"] + list(BASE_SIGNS)
    p = read_on_dates(PANEL_V2, cols, dates)
    p["date"] = pd.to_datetime(p["date"]); p["ticker"] = p["ticker"].astype(str)
    u = read_on_dates(UNIVERSE_V2, ["date", "ticker", "eligible_cap2000"], dates)
    u["date"] = pd.to_datetime(u["date"])
    ue = u[u.eligible_cap2000]
    have = ue.merge(p[["date", "ticker"]], on=["date", "ticker"], how="left", indicator=True)
    cov = float((have["_merge"] == "both").mean())
    log(f"pool integrity: {cov:.2%} of v2 cap2000-eligible name-dates present in panel v2")
    if cov < ET.MIN_POOL_COVERAGE:
        raise SystemExit(f"cap2000 pool integrity {cov:.1%} < 99% (Amendment 1)")
    p = p[p.eligible_cap2000].drop(columns=["eligible_cap2000"])
    m = p.merge(f, on=["date", "ticker"], how="inner")
    m["opt_vrp"] = m["opt_atm_iv"] - m["volatility_60"] * np.sqrt(252.0)
    oc = read_on_dates(OUTCOME_V2, ["ticker", "date", "gross_return_40"], dates)
    oc["date"] = pd.to_datetime(oc["date"])
    spy = oc[oc.ticker == "SPY"].set_index("date")["gross_return_40"]
    m = m.merge(oc[~oc.ticker.isin(["SPY", "USMV"])], on=["date", "ticker"], how="left")
    m = m.sort_values(["date", "ticker"]).reset_index(drop=True)
    return m, spy, cov


def apply_label_mode(m, spy, mode, seed=12345):
    if mode == "real":
        return m, spy
    rng = np.random.default_rng(seed)
    m = m.copy()
    if mode == "shuffled":
        dcode = pd.factorize(m["date"])[0]
        order = np.lexsort((rng.random(len(m)), dcode))       # permutation within date (m sorted by date)
        m[LABEL] = m[LABEL].to_numpy()[order]
        m["gross_return_40"] = m["gross_return_40"].to_numpy()[order]
        m["gross_return_40"] = m["gross_return_40"] - m.groupby("date")["gross_return_40"].transform("mean")
    elif mode == "noise":
        m[LABEL] = rng.normal(0, 0.15, len(m))
        m["gross_return_40"] = rng.normal(0, 0.15, len(m))
    else:
        raise ValueError(mode)
    return m, pd.Series(0.0, index=spy.index)


# ------------------------------------------------------------------ books
def shuffle_col(df, col, seed):
    rng = np.random.default_rng(seed)
    out = df.copy()
    out[col] = out.groupby("date")[col].transform(lambda s: s.sample(frac=1, random_state=int(rng.integers(1 << 30))).to_numpy())
    return out


def portfolio(scored, spy, score_col="score"):
    """decile_volq, net 15bp (turnover), excess vs SPY x252/40, mean over N_OFFSETS interleaved date sets."""
    picks = {}
    for d, g in scored.groupby("date", sort=True):
        g = g.reset_index(drop=True)
        pk = C.pick_decile_volq(g, pd.DataFrame({"ticker": g.ticker, "composite": g[score_col]}))
        ret = dict(zip(g.ticker, g.gross_return_40))
        pk = [(t, w) for t, w in pk if pd.notna(ret.get(t))]
        if not pk:
            continue
        ws = sum(w for _, w in pk)
        picks[d] = (sum((w / ws) * (1 + ret[t]) for t, w in pk) - 1, {t for t, _ in pk})
    dates = sorted(picks)
    per_off = []
    for off in range(N_OFFSETS):
        prev, recs = set(), []
        for d in dates[off::N_OFFSETS]:
            gross, cur = picks[d]
            recs.append({"date": d, "gross": gross, "f_new": sum(t not in prev for t in cur) / len(cur),
                         "spy": spy.get(d, np.nan)})
            prev = cur
        if not recs:
            continue
        net = RB.turnover_net_return(recs, COST_BPS)
        s = np.array([r["spy"] for r in recs], float)
        ok = np.isfinite(s)
        per_off.append(float((net[ok] - s[ok]).mean() * 252.0 / 40.0))
    return {"excess_ann_mean_offsets": float(np.mean(per_off)) if per_off else np.nan,
            "per_offset": per_off, "n_dates": len(dates)}


def refit(t_base, c, t_c):
    return ET.fit_weights({**t_base, c: {"t": t_c}}, {**BASE_SIGNS, c: OPTION_SIGNS[c]})


# ------------------------------------------------------------------ stages
def screen(m, spy, rng_seed=20260929):
    log(f"screen: {len(m):,} optionable cap2000 name-dates, {m.date.nunique()} dates")
    neu = ET.neutralise(m, list(OPTION_SIGNS) + list(BASE_SIGNS))
    base_t = {c: ET.pooled(m, c) for c in BASE_SIGNS}
    base_w = ET.fit_weights(base_t, BASE_SIGNS)
    res = {}
    for c, sgn in OPTION_SIGNS.items():
        res[c] = {"sign": sgn, "ic_raw": ET.pooled(m, c), "ic_neutral": ET.pooled(neu, c),
                  "coverage": float(m[c].notna().mean())}
    ps = {c: (2 * (1 - norm.cdf(abs(r["ic_neutral"]["t"]))) if np.isfinite(r["ic_neutral"]["t"]) else 1.0)
          for c, r in res.items()}
    order = sorted(ps, key=ps.get)
    passed = set()
    for i, c in enumerate(order):
        if ps[c] <= 0.05 / (len(order) - i):
            if np.sign(res[c]["ic_neutral"]["mean"]) == res[c]["sign"]:
                passed.add(c)
        else:
            break
    for c in OPTION_SIGNS:
        rows = m[m[c].notna()].copy()
        w9 = refit(base_t, c, res[c]["ic_raw"]["t"])
        sb = ET.score_frame(rows, base_w)
        sp = ET.score_frame(rows, w9)
        ic_b, ic_p = ET.per_date_ic(sb, "score"), ET.per_date_ic(sp, "score")
        diff = (ic_p - ic_b).dropna()
        pf_b, pf_p = portfolio(sb, spy), portfolio(sp, spy)
        null_ic, null_pf, null_w = [], [], []
        for k in range(NULL_DRAWS):
            sh = shuffle_col(rows, c, rng_seed + k)
            wn = refit(base_t, c, ET.pooled(sh, c)["t"])
            sn = ET.score_frame(sh, wn)
            null_ic.append(float((ET.per_date_ic(sn, "score") - ic_b).dropna().mean()))
            null_pf.append(portfolio(sn, spy)["excess_ann_mean_offsets"])
            null_w.append(wn[c])
        ic_p80 = float(np.quantile(null_ic, NULL_PCTILE))
        pf_p80 = float(np.quantile(null_pf, NULL_PCTILE))
        real_gain = float(diff.mean())
        res[c].update({
            "weights9": w9,
            "admission_ic_gain": real_gain, "admission_gain_nw": ET.newey_west_mean_t(diff.to_numpy()),
            "ic_null_p80": ic_p80, "ic_null_median": float(np.median(null_ic)), "ic_null_draws": null_ic,
            "null_candidate_weights": null_w,
            "companion": {"composite": pf_b, "composite_plus": pf_p, "null_p80": pf_p80,
                          "null_median": float(np.median(null_pf)), "null_draws": null_pf,
                          "pass": bool(pf_p["excess_ann_mean_offsets"] > pf_p80)},
            "passed_screen": c in passed,
            "admitted_ic": bool(c in passed and real_gain > ic_p80),
        })
        res[c]["admitted"] = bool(res[c]["admitted_ic"] and res[c]["companion"]["pass"])
        log(f"  {c}: screen {'Y' if c in passed else 'n'} | ic gain vs p80 {'>' if real_gain > ic_p80 else '<='} | "
            f"companion {'PASS' if res[c]['companion']['pass'] else 'fail'}")
    admitted = [c for c in res if res[c]["admitted"]]
    w_conf = ET.fit_weights({**base_t, **{c: res[c]["ic_raw"] for c in admitted}},
                            {**BASE_SIGNS, **{c: OPTION_SIGNS[c] for c in admitted}}) if admitted else None
    return {"stage": "screen", "dates": [str(pd.Timestamp(d).date()) for d in sorted(m.date.unique())],
            "base_t": base_t, "base_weights": base_w, "holm_p": ps, "factors": res,
            "admitted": admitted, "confirm_weights_frozen": w_conf}


def confirm(m, spy, scr):
    adm = scr["admitted"]
    if not adm:
        return {"stage": "confirm", "note": "nothing admitted at screen; confirmation not run; hold-out read #7 NOT used"}
    rows = m.dropna(subset=adm).copy()
    sb = ET.score_frame(rows, scr["base_weights"])
    sp = ET.score_frame(rows, scr["confirm_weights_frozen"])
    diff = (ET.per_date_ic(sp, "score") - ET.per_date_ic(sb, "score")).dropna()
    st = ET.newey_west_mean_t(diff.to_numpy())
    yrs = diff.groupby(diff.index.year).mean()
    loyo = {int(y): float(diff[diff.index.year != y].mean()) for y in yrs.index}
    pf_b, pf_p = portfolio(sb, spy), portfolio(sp, spy)
    comp_diff = pf_p["excess_ann_mean_offsets"] - pf_b["excess_ann_mean_offsets"]
    ic_ok = bool(st["mean"] > 0 and st["t"] >= 1.5 and all(v > 0 for v in loyo.values()))
    return {"stage": "confirm", "admitted": adm, "ic_gain": st, "by_year": {int(k): float(v) for k, v in yrs.items()},
            "loyo": loyo, "ic_confirmed": ic_ok, "companion": {"composite": pf_b, "composite_plus": pf_p,
                                                             "diff": comp_diff, "pass": bool(comp_diff > 0)},
            "confirmed": bool(ic_ok and comp_diff > 0)}


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--stage", choices=["screen", "confirm"], default="screen")
    ap.add_argument("--labels", choices=["shuffled", "noise"], default=None)
    ap.add_argument("--phase2", action="store_true", help="real labels (guarded)")
    ap.add_argument("--features", type=Path, default=FEATS)
    ap.add_argument("--test-confirm-on-nominate", action="store_true",
                    help="plumbing only: run confirm() on nominate-era dates with test labels")
    a = ap.parse_args()
    if a.phase2 == (a.labels is not None):
        raise SystemExit("choose exactly one of --phase2 (real labels) or --labels shuffled|noise")
    mode = "real" if a.phase2 else a.labels
    tag = "" if a.phase2 else f"_SHUFFLED_TEST_labels-{mode}"
    OUT.mkdir(parents=True, exist_ok=True)
    scr_path = OUT / f"expB_screen{tag}.json"
    conf_path = OUT / f"expB_confirm{tag}.json"
    t0 = time.time()
    if a.phase2:
        phase2_guard(a.stage)
    if a.stage == "screen":
        m, spy, cov = load(*NOMINATE_B, a.features)
        if a.phase2 and m.date.nunique() < MIN_NOMINATE_DATES:
            raise SystemExit(f"nominate era has {m.date.nunique()} dates (< {MIN_NOMINATE_DATES})")
        m, spy = apply_label_mode(m, spy, mode)
        out = screen(m, spy)
        out.update({"label_mode": mode, "pool_integrity": cov, "runtime_s": time.time() - t0})
        scr_path.write_text(json.dumps(out, indent=2, default=float))
        log(f"wrote {scr_path}")
    else:
        if not scr_path.exists():
            raise SystemExit(f"run --stage screen first ({scr_path.name})")
        if conf_path.exists() and a.phase2:
            raise SystemExit(f"{conf_path} exists: confirmation is ONE shot (hold-out read #7)")
        scr = json.loads(scr_path.read_text())
        if a.test_confirm_on_nominate and not a.phase2:
            m, spy, cov = load(*NOMINATE_B, a.features)
            if not scr["admitted"]:   # plumbing: force the first factor through so confirm() executes
                c = list(OPTION_SIGNS)[0]
                scr["admitted"] = [c]
                scr["confirm_weights_frozen"] = scr["factors"][c]["weights9"]
        else:
            m, spy, cov = load(*CONFIRM_B, a.features)
        m, spy = apply_label_mode(m, spy, mode)
        out = confirm(m, spy, scr)
        out.update({"label_mode": mode, "pool_integrity": cov, "runtime_s": time.time() - t0,
                    "holdout_read": "#7" if a.phase2 else "none (test labels)"})
        conf_path.write_text(json.dumps(out, indent=2, default=float))
        log(f"wrote {conf_path}")


if __name__ == "__main__":
    main()
