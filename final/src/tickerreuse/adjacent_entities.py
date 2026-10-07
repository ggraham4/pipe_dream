"""WO-47: the D1 rule cannot split a reuse where the new entity starts within 5 calendar days of the
old one's last price. List every SEP symbol whose candidate entities sit that close (<= 10 days apart)
with SEP rows inside both spans. Writes final/out/tickerreuse/adjacent_entities.csv."""
import numpy as np
import pandas as pd

from common import OUT, MASTERS
import build_features_sharadar as BF
from detect import load_sep_keys

sep = load_sep_keys()
ents = BF.load_reuse_entities(MASTERS)
rows = []
for sym, g in sep.groupby("ticker", sort=False):
    c = sorted(ents.get(sym, []), key=lambda x: x[1])
    if len(c) < 2:
        continue
    d = g["date"].to_numpy()
    for (p1, f1, l1), (p2, f2, l2) in zip(c[:-1], c[1:]):
        sep_days = (f2 - l1) / np.timedelta64(1, "D")
        if -1 <= sep_days <= 10:
            n1 = int(((d >= f1) & (d <= l1)).sum())
            n2 = int(((d >= f2) & (d <= l2)).sum())
            if n1 and n2:
                rows.append({"ticker": sym, "entity_a": p1, "a_last": pd.Timestamp(l1).date(),
                             "entity_b": p2, "b_first": pd.Timestamp(f2).date(),
                             "days_apart": sep_days, "rows_a": n1, "rows_b": n2})
A = pd.DataFrame(rows, columns=["ticker", "entity_a", "a_last", "entity_b", "b_first", "days_apart", "rows_a", "rows_b"])
A.to_csv(OUT / "adjacent_entities.csv", index=False)
print(len(A), "symbols with adjacent entities and SEP rows on both sides")
print(A.to_string(index=False))
