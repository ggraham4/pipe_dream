"""WO-47 A1 extra cross-check: SEP rows of each symbol not covered (+/-5 days) by ANY Sharadar entity
that ever carried the symbol (or S+digits). Writes final/out/tickerreuse/uncovered_rows.csv."""
import numpy as np
import pandas as pd

from common import OUT, MASTERS
import build_features_sharadar as BF
from detect import load_sep_keys

sep = load_sep_keys()
ents = BF.load_reuse_entities(MASTERS)
tol = np.timedelta64(5, "D")
rows = []
for sym, g in sep.groupby("ticker", sort=False):
    d = g["date"].to_numpy()
    c = ents.get(sym, [])
    cov = np.zeros(len(d), bool)
    for _, f, l in c:
        cov |= (d >= f - tol) & (d <= l + tol)
    n = int((~cov).sum())
    if n:
        u = d[~cov]
        rows.append({"ticker": sym, "rows": len(d), "uncovered": n, "n_entities": len(c),
                     "first_uncovered": pd.Timestamp(u.min()).date(),
                     "last_uncovered": pd.Timestamp(u.max()).date()})
U = pd.DataFrame(rows).sort_values("uncovered", ascending=False)
U.to_csv(OUT / "uncovered_rows.csv", index=False)
print(len(U), "symbols with uncovered rows;", int(U.uncovered.sum()), "rows")
print(int((U.uncovered > 5).sum()), "with >5 uncovered rows")
print(U.head(25).to_string(index=False))
