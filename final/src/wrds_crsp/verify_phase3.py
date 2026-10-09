"""WO-51 independent re-derivation (does not import phase3/common or the harness).
Recomputes S, C, Delta from final/data/wrds/crsp/derived/phase3_pickrows.parquet with its own
offset/turnover/cost arithmetic, plus a post-hoc (not judged) sensitivity applying dlret on rows
whose CRSP delisting date equals e. Also prints the fallback weight share."""
# Independent Delta recompute from phase3_pickrows.parquet (no import of phase3/common/harness)
import pandas as pd, numpy as np
pr = pd.read_parquet("/Users/ggraham/pipe_dream/final/data/wrds/crsp/derived/phase3_pickrows.parquet")
oc = pd.read_parquet("/Users/ggraham/pipe_dream/final/out/reset2026/outcome_cache_v2.parquet",
                     columns=["ticker", "date", "gross_return_40"],
                     filters=[("ticker", "==", "SPY"), ("date", ">=", pd.Timestamp("2007-01-02")), ("date", "<=", pd.Timestamp("2019-12-31"))])
assert pd.to_datetime(oc.date).max() < pd.Timestamp("2020-01-01")
spy = dict(zip(pd.to_datetime(oc.date), oc.gross_return_40))
dates = sorted(pr.date.unique())
h = 15e-4 / 2
by = {d: g for d, g in pr.groupby("date")}
def run(col):
    res = []
    for off in range(40):
        prev, ex = set(), []
        for d in dates[off::40]:
            g = by[d]; cur = set(g.ticker)
            f = len(cur - prev) / len(cur); prev = cur
            gross = (g.wn * (1 + g[col])).sum() - 1
            net = (1 + gross) * (1 - h * f) / (1 + h * f) - 1
            s = spy.get(pd.Timestamp(d), np.nan)
            if np.isfinite(s): ex.append(net - s)
        res.append(np.mean(ex) * 252 / 40)
    return np.mean(res)
S, C = run("r_S"), run("r_C")
print(f"S {S:.6%}  C {C:.6%}  Delta {C - S:+.6%}")

# Post-hoc sensitivity (not judged): apply dlret on rows whose CRSP delisting date equals e
dl = pd.read_parquet("/Users/ggraham/pipe_dream/final/data/wrds/crsp/dsedelist.parquet", columns=["permno", "dlret", "dlretx", "dlstcd"])
dl["dl_use"] = dl.dlret.where(dl.dlret.notna(), dl.dlretx)
m = pr.dl_on_e & ~pr.fallback
j = pr.loc[m, ["permno"]].merge(dl, on="permno", how="left")
adj = j.dl_use.fillna(0.0).to_numpy()
print("dl_on_e non-fallback rows", int(m.sum()), "missing dlret", int(j.dl_use.isna().sum()), "codes", j.dlstcd.value_counts().head(5).to_dict(),
      "weighted mean dlret", float((pr.loc[m, "wn"].to_numpy() * adj).sum() / pr.loc[m, "wn"].sum()))
pr["r_C_e"] = pr.r_C
pr.loc[m, "r_C_e"] = (1 + pr.loc[m, "r_C"].to_numpy()) * (1 + adj) - 1
by = {d: g for d, g in pr.groupby("date")}
Ce = run("r_C_e")
print(f"C with dlret on e {Ce:.6%}  Delta {Ce - S:+.6%}")

w = pr.wn
print("fallback weight share", float((w * pr.fallback).sum() / w.sum()))
