"""WO-47: for symbols with >5 SEP rows outside every entity span, show price at the coverage
edges (a same-company span mismatch shows a continuous price; a silent reuse shows a jump)."""
import numpy as np
import pandas as pd

from common import OUT, SEP_DIR, MASTERS
import build_features_sharadar as BF

U = pd.read_csv(OUT / "uncovered_rows.csv", keep_default_na=False)
U = U[U.uncovered.astype(int) > 5]
syms = U.ticker.tolist()
fr = [pd.read_parquet(f, columns=["ticker", "date", "close", "volume"], filters=[("ticker", "in", syms)])
      for f in sorted(SEP_DIR.glob("*.parquet"))]
s = pd.concat(fr).sort_values(["ticker", "date"])
s["date"] = pd.to_datetime(s["date"])
ents = BF.load_reuse_entities(MASTERS)
tol = np.timedelta64(5, "D")
out = []
for sym, g in s.groupby("ticker"):
    d = g.date.to_numpy()
    cov = np.zeros(len(d), bool)
    for _, f, l in ents.get(sym, []):
        cov |= (d >= f - tol) & (d <= l + tol)
    if not cov.any():
        out.append({"ticker": sym, "edge": "no entity covers any row", "into": "", "close_ratio": None,
                    "max_abs_logret_pm5": None})
    for i in np.flatnonzero(cov[1:] != cov[:-1]) + 1:
        a, b = g.iloc[i - 1], g.iloc[i]
        w = g.close.iloc[max(i - 5, 0):i + 5].clip(lower=1e-9).to_numpy()
        out.append({"ticker": sym, "edge": f"{a.date.date()}>{b.date.date()}",
                    "into": "covered" if cov[i] else "uncovered",
                    "close_ratio": round(b.close / a.close, 3) if a.close else None,
                    "max_abs_logret_pm5": round(float(np.nanmax(np.abs(np.diff(np.log(w))))), 3)})
E = pd.DataFrame(out)
E.to_csv(OUT / "uncovered_edges.csv", index=False)
print(E.to_string(index=False))
