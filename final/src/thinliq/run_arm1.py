"""
WO-37 Arm 1 (primary): avoid-the-bottom-decile screen on opt_cw_spread in the
thin slice, 40-day forward STOCK return. Spec and every number below:
final/models/2026-10-01-thin-liquidity-prereg.md section 3.

    # plumbing / null calibration (labels are shuffled within date, or pure noise; never real)
    python run_arm1.py --labels shuffled --universe cap2000 --seeds 100
    python run_arm1.py --labels noise    --universe cap2000 --seeds 100
    python run_arm1.py --labels shuffled --universe thin    --seeds 100     # 9 early dates: smoke only
    # the one real run (guarded: doc tracked in git + arrival gate + presence checks + no earlier result)
    python run_arm1.py --phase2

Metric per date d (fraction, reported in % per 40 days):
    M_d = mean(label | rest of slice) - mean(label | bottom decile of opt_cw_spread)
so POSITIVE means the screen helps. Label = outcome_cache_v2.gross_return_40
(entry open[d+1], exit close[d+40], delisting floor: exit at the last close).
"""
from __future__ import annotations

import argparse
import json
import time

import numpy as np
import pandas as pd
from scipy.stats import rankdata

import tl_common as T

# ---- pre-registered constants (doc section 3)
SIGNAL = "opt_cw_spread"
DECILE = 0.10
MIN_NAMES = 100            # a date needs >= 100 names with a signal and a label
NW_LAG = 39
NULL_DRAWS, NULL_PCTILE = 100, 0.80
T_MAIN, T_CHECK = 3.75, 3.0   # nominal 2.5 and 2.0 scaled by 1.5: the lag-39 t has sd about 1.5 under the null (doc 6.2)
M_FLOOR = 0.010            # +1.0% per 40 days
YEAR_SHARE_MAX = 0.45
NOISE_SD = 0.15
RESULT = T.OUT / "arm1_results.json"


def pct_rank(x):
    return rankdata(x, method="average") / len(x)


def bottom_idx(sig, k):
    return np.argsort(sig, kind="stable")[:k]


def split(ret, b):
    return (ret.sum() - ret[b].sum()) / (len(ret) - len(b)) - ret[b].mean()


def group_demean(x, codes, ng):
    s = np.bincount(codes, weights=x, minlength=ng)
    c = np.bincount(codes, minlength=ng)
    return x - (s / np.maximum(c, 1))[codes]


def load_frame(universe, dates):
    """Signal-side frame only (no label)."""
    f = pd.read_parquet(T.FEATS, columns=["date", "ticker", SIGNAL, "opt_log_oi", "opt_log_vol"])
    f["date"] = pd.to_datetime(f.date); f["ticker"] = f.ticker.astype(str)
    f = f[f.date.isin(dates) & f[SIGNAL].notna()]
    u = T.universe_on(dates)
    u = u[u.thin] if universe == "thin" else u[u.eligible_cap2000]
    n_univ = u.groupby("date").size()
    m = u[["date", "ticker", "marketcap"]].merge(f, on=["date", "ticker"])
    p = T.read_on_dates(T.PANEL_V2, ["ticker", "date", "sector", "volatility_60"], dates)
    p["ticker"] = p.ticker.astype(str)
    m = m.merge(p, on=["date", "ticker"], how="left")
    return m.sort_values(["date", "ticker"]).reset_index(drop=True), n_univ


def attach_labels(m, mode, seed):
    """real -> gross_return_40 from the outcome cache, aligned to m. Called with mode 'real' either under
    --phase2 or by the shuffled-label path, which permutes it within date before anything is computed."""
    assert mode == "real"
    dd = sorted(m.date.unique())
    o = pd.read_parquet(T.OUTCOME_V2, columns=["ticker", "date", "gross_return_40"],
                        filters=[("date", "in", [pd.Timestamp(x).to_pydatetime() for x in dd])])
    o["ticker"] = o.ticker.astype(str); o["date"] = pd.to_datetime(o.date)
    y = m[["date", "ticker"]].merge(o, on=["date", "ticker"], how="left").gross_return_40.astype(float)
    y.index = m.index
    return y


def prep(m):
    """Per-date fixed structures. The bottom-decile index sets depend on the signal only."""
    D = []
    for d, g in m.groupby("date", sort=True):
        g = g[g.y.notna()]
        n = len(g)
        if n < MIN_NAMES:
            continue
        sig = g[SIGNAL].to_numpy(float)
        pr = pct_rank(sig)
        k = max(1, int(round(DECILE * n)))
        codes, _ = pd.factorize(g.sector.fillna("NA"))
        ng = codes.max() + 1
        v = (np.isfinite(g.marketcap) & (g.marketcap > 0) & np.isfinite(g.volatility_60)).to_numpy()
        X = np.column_stack([np.ones(v.sum()), pct_rank(np.log(g.marketcap.to_numpy()[v])), pct_rank(g.volatility_60.to_numpy()[v])])
        Q, _ = np.linalg.qr(X)
        res = pr[v] - Q @ (Q.T @ pr[v])
        oi = g.opt_log_oi.to_numpy(float)
        ter = np.full(n, -1)
        ok = np.isfinite(oi)
        ter[ok] = np.minimum((rankdata(oi[ok], method="ordinal") - 1) * 3 // ok.sum(), 2).astype(int)
        tb = {}
        for j in range(3):
            ix = np.where(ter == j)[0]
            if len(ix) >= 30:
                tb[j] = (ix, bottom_idx(sig[ix], max(1, int(round(DECILE * len(ix))))))
        D.append({"date": d, "n": n, "k": k, "b_raw": bottom_idx(sig, k), "codes": codes, "ng": ng,
                  "b_sn": bottom_idx(group_demean(pr, codes, ng), k), "v": v, "Q": Q,
                  "b_res": bottom_idx(res, max(1, int(round(DECILE * v.sum())))), "ter": tb, "idx": g.index.to_numpy()})
    return D


def evaluate(D, y, null_seed=0, with_null=True):
    """y: numpy array of labels aligned to the frame index. Returns metrics + criteria."""
    rows = []
    rng = np.random.default_rng(null_seed)
    null = np.zeros(NULL_DRAWS)
    for x in D:
        r = y[x["idx"]]
        rs = group_demean(r, x["codes"], x["ng"])
        rv = r[x["v"]]
        rr = rv - x["Q"] @ (x["Q"].T @ rv)
        row = {"date": x["date"], "n": x["n"], "raw": split(r, x["b_raw"]), "sn": split(rs, x["b_sn"]), "res": split(rr, x["b_res"])}
        for j, (ix, b) in x["ter"].items():
            row[f"oi_t{j}"] = split(r[ix], b)
        rows.append(row)
        if with_null:   # within-date shuffle of the signal == a random k-subset as "bottom decile"
            pick = np.argpartition(rng.random((NULL_DRAWS, x["n"])), x["k"], axis=1)[:, :x["k"]]
            bs = r[pick].sum(1)
            null += (r.sum() - bs) / (x["n"] - x["k"]) - bs / x["k"]
    S = pd.DataFrame(rows)
    nd = len(S)
    null = null / max(nd, 1)
    yr = S.date.dt.year.to_numpy()
    raw = S.raw.to_numpy()
    nw = T.newey_west_mean_t(raw, NW_LAG)
    M = float(raw.mean()) if nd else np.nan
    p80 = float(np.quantile(null, NULL_PCTILE)) if with_null else np.nan
    off = [float(raw[i::2].mean()) if len(raw[i::2]) else np.nan for i in (0, 1)]
    odd, even = raw[yr % 2 == 1], raw[yr % 2 == 0]
    h_odd, h_even = (float(odd.mean()) if len(odd) else np.nan), (float(even.mean()) if len(even) else np.nan)
    c1, c2 = (float(raw[:nd // 2].mean()) if nd >= 2 else np.nan), (float(raw[nd // 2:].mean()) if nd >= 2 else np.nan)
    years = sorted(set(yr))
    loyo = {int(v): float(raw[yr != v].mean()) for v in years} if len(years) > 1 else {}
    tot = raw.sum()
    share = {int(v): float(raw[yr == v].sum() / tot) for v in years} if tot > 0 else {}
    max_share = max(share.values()) if share else np.nan
    sn, rs_ = T.newey_west_mean_t(S.sn.to_numpy(), NW_LAG), T.newey_west_mean_t(S.res.to_numpy(), NW_LAG)
    pos = lambda v: bool(np.isfinite(v) and v > 0)  # noqa: E731
    crit = {
        "S1_M_gt_null_p80": bool(with_null and M > p80 and M > 0),
        "S2_nw39_t_ge_3.75": bool(np.isfinite(nw["t"]) and nw["t"] >= T_MAIN),
        "S3_M_ge_1.0pct": bool(M >= M_FLOOR),
        "S4_sector_neutral": bool(pos(sn["mean"]) and np.isfinite(sn["t"]) and sn["t"] >= T_CHECK),
        "S5_halves_all_positive": bool(pos(h_odd) and pos(h_even) and pos(c1) and pos(c2)),
        "S6_loyo_and_year_share": bool(loyo and min(loyo.values()) > 0 and np.isfinite(max_share) and max_share <= YEAR_SHARE_MAX),
        "S7_both_offsets_positive": bool(pos(off[0]) and pos(off[1])),
        "S8_size_vol_residual": bool(pos(rs_["mean"]) and np.isfinite(rs_["t"]) and rs_["t"] >= T_CHECK),
    }
    kill = {
        "K1_M_le_null_p80": bool(with_null and not (M > p80 and M > 0)),
        "K2_offset_sign_flip": bool(np.isfinite(off[0]) and np.isfinite(off[1]) and off[0] * off[1] <= 0),
        "K3_odd_even_sign_flip": bool(np.isfinite(h_odd) and np.isfinite(h_even) and h_odd * h_even <= 0),
        "K4_year_share_gt_45pct": bool(np.isfinite(max_share) and max_share > YEAR_SHARE_MAX),
        "K5_sector_neutral_le_0": bool(not pos(sn["mean"])),
        "K6_size_vol_residual_le_0": bool(not pos(rs_["mean"])),
    }
    verdict = "PASS" if all(crit.values()) else ("KILL" if any(kill.values()) else "MIDDLE")
    pc = lambda v: None if v is None or not np.isfinite(v) else round(100 * v, 4)  # noqa: E731
    return {"n_dates": int(nd), "median_names_per_date": float(S.n.median()) if nd else None,
            "M_pct_per_40d": pc(M), "nw39_t": nw["t"], "nw2_t_DESCRIPTIVE": T.newey_west_mean_t(raw, 2)["t"],
            "null_p80_pct": pc(p80), "null_median_pct": pc(float(np.median(null))) if with_null else None,
            "sector_neutral": {"M_pct": pc(sn["mean"]), "nw39_t": sn["t"]},
            "size_vol_residual": {"M_pct": pc(rs_["mean"]), "nw39_t": rs_["t"]},
            "odd_years_pct": pc(h_odd), "even_years_pct": pc(h_even),
            "chrono_first_half_pct": pc(c1), "chrono_second_half_pct": pc(c2),
            "offsets_pct": [pc(off[0]), pc(off[1])],
            "loyo_pct": {k: pc(v) for k, v in loyo.items()}, "loyo_min_pct": pc(min(loyo.values())) if loyo else None,
            "year_share": share, "max_year_share": None if not np.isfinite(max_share) else max_share,
            "oi_terciles_DESCRIPTIVE_pct": {f"t{j}_{lab}": pc(float(S[f"oi_t{j}"].mean())) if f"oi_t{j}" in S else None
                                            for j, lab in enumerate(["thinnest", "middle", "thickest"])},
            "criteria": crit, "kill": kill, "verdict": verdict}


def coverage_note(m, n_univ, D):
    have = m.groupby("date").size()
    used = {x["date"] for x in D}
    return {"dates_in_frame": int(m.date.nunique()), "dates_used": len(D),
            "dates_dropped_lt_min_names": [str(d.date()) for d in sorted(set(m.date.unique()) - used)],
            "share_of_universe_with_signal_median": float((have / n_univ.reindex(have.index)).median())}


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--labels", choices=["shuffled", "noise"], default=None)
    ap.add_argument("--universe", choices=["thin", "cap2000"], default="thin")
    ap.add_argument("--seeds", type=int, default=100)
    ap.add_argument("--phase2", action="store_true")
    a = ap.parse_args()
    if a.phase2 == (a.labels is not None):
        raise SystemExit("choose exactly one of --phase2 or --labels {shuffled,noise}")
    t0 = time.time()
    if a.phase2:
        if a.universe != "thin":
            raise SystemExit("--phase2 runs the thin slice only (cap2000 is computed alongside, descriptive)")
        dates = T.phase2_guard(RESULT)
        m, nu = load_frame("thin", dates)
        m["y"] = attach_labels(m, "real", 0)
        D = prep(m)
        out = {"label_mode": "real", "universe": "thin", "window": [str(dates[0].date()), str(dates[-1].date())],
               "holdout_read": "none (no date from 2019 on is read)", "coverage": coverage_note(m, nu, D),
               "arm1": evaluate(D, m.y.to_numpy(float), null_seed=20261001)}
        c, nc = load_frame("cap2000", dates)
        c["y"] = attach_labels(c, "real", 0)
        Dc = prep(c)
        ec = evaluate(Dc, c.y.to_numpy(float), null_seed=20261001)
        out["cap2000_same_dates_DESCRIPTIVE"] = {k: ec[k] for k in ["n_dates", "M_pct_per_40d", "nw39_t", "null_p80_pct"]}
        out["verdict"] = out["arm1"]["verdict"]
        out["runtime_s"] = time.time() - t0
        RESULT.write_text(json.dumps(out, indent=1, default=str))
        T.log(f"Arm 1 verdict {out['verdict']} -> {RESULT}")
        return

    dates = T.monthly_dates()
    on_disk = {pd.Timestamp(p.stem.split("=")[1]) for p in T.FCACHE.glob("date=*.parquet")}
    dates = [d for d in dates if d in on_disk]
    if a.universe == "thin":   # only dates where the thin slice was actually pulled
        comp = set(T.arrival_gate(write=False)["thin_complete_dates"])
        dates = [d for d in dates if str(d.date()) in comp]
    m, nu = load_frame(a.universe, dates)
    runs = []
    if a.labels == "shuffled":   # real labels are loaded only to be permuted; the unpermuted order is never evaluated
        m["y"] = attach_labels(m, "real", 0)
        m = m[m.y.notna()].reset_index(drop=True)
    else:
        m["y"] = 0.0
    base = m.y.to_numpy(float)
    D = prep(m)
    for s in range(a.seeds):
        rng = np.random.default_rng(1000 + s)
        if a.labels == "noise":
            y = rng.normal(0, NOISE_SD, len(m))
        else:
            y = np.full(len(m), np.nan)
            for x in D:
                y[x["idx"]] = rng.permutation(base[x["idx"]])
        runs.append(evaluate(D, y, null_seed=s))
        if (s + 1) % 20 == 0:
            T.log(f"  seed {s + 1}/{a.seeds}")
    crit = pd.DataFrame([r["criteria"] for r in runs]).mean().round(4).to_dict()
    kill = pd.DataFrame([r["kill"] for r in runs]).mean().round(4).to_dict()
    ver = pd.Series([r["verdict"] for r in runs]).value_counts(normalize=True).to_dict()
    Ms = np.array([r["M_pct_per_40d"] for r in runs], float)
    ts = np.array([r["nw39_t"] for r in runs], float)
    out = {"label_mode": a.labels, "NOT_A_RESULT": "labels are " + ("permuted within date" if a.labels == "shuffled" else "pure noise") +
           "; this file calibrates the decision rule under the null and proves the plumbing",
           "universe": a.universe, "dates": [str(d.date()) for d in dates], "coverage": coverage_note(m, nu, D),
           "seeds": a.seeds, "verdict_rates": ver, "pass_rate": float(ver.get("PASS", 0.0)),
           "criterion_pass_rates": crit, "kill_trigger_rates": kill,
           "null_label_M_pct": {"mean": float(np.nanmean(Ms)), "sd": float(np.nanstd(Ms)), "p5": float(np.nanpercentile(Ms, 5)),
                                "p95": float(np.nanpercentile(Ms, 95))},
           "null_label_nw39_t": ({"mean": float(np.nanmean(ts)), "sd": float(np.nanstd(ts)),
                                  "share_ge_2.5": float(np.mean(ts >= 2.5)), "share_ge_3.75": float(np.mean(ts >= T_MAIN)), "share_abs_ge_2": float(np.mean(np.abs(ts) >= 2))}
                                 if np.isfinite(ts).any() else "n < 10 dates: NW t undefined"),
           "example_run_seed0": runs[0], "runtime_s": time.time() - t0}
    path = T.OUT / f"arm1_nullcal_SHUFFLED_TEST_{a.universe}_labels-{a.labels}.json"
    path.write_text(json.dumps(out, indent=1, default=str))
    T.log(f"{a.universe}/{a.labels}: {len(D)} dates, PASS rate {out['pass_rate']:.3f}, verdicts {ver} -> {path.name}")
    T.log(f"  criteria {crit}")


if __name__ == "__main__":
    main()
