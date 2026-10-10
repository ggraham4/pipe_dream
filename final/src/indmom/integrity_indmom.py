"""
WO-50 gate 7 (Gate A) parts (a) and (c), outcome-free. Pre-reg section 1.7 gate 7.
(a) PIT: (a1) factor on date t rebuilt from population rows dated <= t only == cache, on sample dates;
    (a2) x7 rescale of every panel close after a cut date: momentum recomputed from close
         (shift 21 / shift 252, prices <= t) and the factor rebuilt; every factor value on or before
         the cut unchanged, values after it change (the test bites);
    (a3) hold-out assert: nothing dated >= 2020-01-01 loaded.
(c) named hand-check: energy mid-2014, bank 2009, semiconductor 2017, recomputed independently from
    composite_panel_v2 + tickers_master (own SPAC filter, own member list), match to 1e-12.
Usage: python integrity_indmom.py -> final/out/indmom/indmom_integrity.json
"""
import json
import sys
import time
from pathlib import Path

import numpy as np
import pandas as pd

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
import build_indmom as B  # noqa: E402  (asserts the pre-reg sha)

R26 = Path("/Users/ggraham/pipe_dream/final/out/reset2026")
PANEL = R26 / "composite_panel_v2.parquet"
HI = pd.Timestamp("2019-12-31")
CUT = pd.Timestamp("2013-06-28")
HAND = [("XOM", "2014-06-30", "energy mid-2014"), ("JPM", "2009-06-30", "bank 2009"), ("INTC", "2017-06-30", "semiconductor 2017")]
log = B.log


def main():
    T0 = time.time()
    C = pd.read_parquet(B.CACHE)
    C["date"] = pd.to_datetime(C["date"]); C["ticker"] = C["ticker"].astype(str)
    assert C["date"].max() < B.HOLDOUT, "HOLD-OUT BREACH"
    labels = B.load_labels()
    out = {"work_order": "WO-50", "cache_sha256": B.sha(B.CACHE)}

    # (a1) truncation
    rng = np.random.default_rng(50000)
    dates = np.sort(C["date"].unique())
    samp = sorted(pd.Timestamp(d) for d in rng.choice(dates, 8, replace=False))
    a1 = []
    for t in samp:
        P = C[C["date"] <= t][["ticker", "date", "momentum_12_1"]]
        F = B.build_factor(P, labels)
        got = F.loc[P["date"] == t, B.COL].to_numpy()
        ref = C.loc[C["date"] == t, B.COL].to_numpy()
        a1.append({"date": str(t.date()), "n": int(len(ref)), "identical": bool(np.array_equal(got, ref, equal_nan=True))})
    out["a1_truncation"] = a1
    log(f"a1 truncation: {sum(x['identical'] for x in a1)}/{len(a1)} identical")

    # (a2) x7 rescale
    p = pd.read_parquet(PANEL, columns=["ticker", "date", "close", "momentum_12_1"], filters=[("date", "<=", HI.date().isoformat())])
    p["date"] = pd.to_datetime(p["date"]); p["ticker"] = p["ticker"].astype(str)
    assert p["date"].max() < B.HOLDOUT, "HOLD-OUT BREACH"
    p = p.sort_values(["ticker", "date"]).reset_index(drop=True)

    def mom(close):
        g = close.groupby(p["ticker"])
        return g.shift(21) / g.shift(252) - 1.0

    key = pd.MultiIndex.from_arrays([C["ticker"], C["date"]])
    pk = pd.MultiIndex.from_arrays([p["ticker"], p["date"]])
    assert pk.is_unique
    m0 = pd.Series(mom(p["close"].astype(np.float64)).to_numpy(), index=pk).reindex(key).to_numpy()
    close7 = p["close"].astype(np.float64).where(p["date"] <= CUT, p["close"].astype(np.float64) * 7.0)
    m7 = pd.Series(mom(close7).to_numpy(), index=pk).reindex(key).to_numpy()
    base = C[["ticker", "date"]].copy()
    F0 = B.build_factor(base.assign(momentum_12_1=m0), labels)[B.COL].to_numpy()
    F7 = B.build_factor(base.assign(momentum_12_1=m7), labels)[B.COL].to_numpy()
    pre = (C["date"] <= CUT).to_numpy()
    pm = C["momentum_12_1"].to_numpy(np.float64)
    both = np.isfinite(pm) & np.isfinite(m0)
    out["a2_rescale"] = {
        "cut": str(CUT.date()), "rows_on_or_before_cut": int(pre.sum()),
        "unchanged_on_or_before_cut": bool(np.array_equal(F0[pre], F7[pre], equal_nan=True)),
        "share_changed_after_cut": float(np.mean(~np.isclose(F0[~pre], F7[~pre], equal_nan=True))),
        "recomputed_vs_panel_mom_match_share_1e-5": float(np.mean(np.abs(m0[both] - pm[both]) <= 1e-5 * np.maximum(1, np.abs(pm[both])))),
        "recomputed_vs_panel_mom_finite_overlap": int(both.sum())}
    log(f"a2 rescale: {out['a2_rescale']}")
    out["a3_holdout"] = {"cache_max_date": str(C["date"].max().date()), "panel_max_date_loaded": str(p["date"].max().date()), "ok": True}
    del p

    # (c) hand check, independent of build_factor / load_theo
    tm = pd.read_csv(B.TM, dtype=str, usecols=["table", "ticker", "industry", "sector", "sicindustry"])
    tm = tm[tm["table"] == "stocks"].set_index("ticker")
    old_t = set(pd.read_parquet(R26 / "composite_panel.parquet", columns=["ticker"])["ticker"].astype(str).unique())
    spac = set(tm.index[tm["sicindustry"].fillna("").str.contains("Blank Check")])
    hc = []
    for tick, d, what in HAND:
        d = pd.Timestamp(d)
        x = pd.read_parquet(PANEL, columns=["ticker", "date", "momentum_12_1", "eligible_cap2000", "eligible_cap150"],
                            filters=[("date", "==", d.date().isoformat())])
        x["ticker"] = x["ticker"].astype(str)
        x = x[x["eligible_cap2000"].astype(bool)]
        x = x[x["ticker"].isin(old_t) | ~x["ticker"].isin(spac)]
        x = x[np.isfinite(x["momentum_12_1"].astype(np.float64))]
        me = x[x["ticker"] == tick]
        assert len(me) == 1, (tick, d)
        ind, sec = tm.loc[tick, "industry"], tm.loc[tick, "sector"]
        mem_i = x[x["ticker"].map(tm["industry"]) == ind]
        if len(mem_i) >= B.MIN_N:
            lvl, mem = "industry", mem_i
        else:
            lvl, mem = "sector", x[x["ticker"].map(tm["sector"]) == sec]
        hand = float(np.mean(mem["momentum_12_1"].astype(np.float64).to_numpy()))
        pipe = float(C.loc[(C["ticker"] == tick) & (C["date"] == d), B.COL].iloc[0])
        hc.append({"what": what, "ticker": tick, "date": str(d.date()), "industry": ind, "sector": sec, "level": lvl,
                   "cap150_eligible": bool(me["eligible_cap150"].iloc[0]), "n_members": int(len(mem)),
                   "members_head": sorted(mem["ticker"].tolist())[:40], "own_mom": float(me["momentum_12_1"].iloc[0]),
                   "hand": hand, "pipeline": pipe, "abs_diff": abs(hand - pipe), "match": bool(abs(hand - pipe) <= 1e-12)})
        log(f"hand {tick} {d.date()} {ind} n={len(mem)} hand {hand:.12f} pipe {pipe:.12f} match {hc[-1]['match']}")
    out["hand_check"] = hc
    out["pass_a_c"] = bool(all(x["identical"] for x in a1) and out["a2_rescale"]["unchanged_on_or_before_cut"]
                           and out["a2_rescale"]["share_changed_after_cut"] > 0 and all(h["match"] and h["cap150_eligible"] for h in hc))
    out["runtime_s"] = time.time() - T0
    (B.OUT / "indmom_integrity.json").write_text(json.dumps(out, indent=1, default=float))
    log(f"integrity pass (a)+(c): {out['pass_a_c']}")


if __name__ == "__main__":
    main()
