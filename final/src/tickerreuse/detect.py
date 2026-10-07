"""WO-47 A1/A2: find every ticker-symbol reuse in the raw SEP panel and report its reach.

    caffeinate -i /opt/anaconda3/envs/pipe_dream/bin/python final/src/tickerreuse/detect.py

Writes final/out/tickerreuse/{reuse_boundaries.csv, d2_gaps.csv, reach_labels.csv, reach_ledgers.csv,
detect_summary.json}. Pre-registration: final/models/2026-10-07-ticker-reuse-panel-drift.md (A1, A2).
"""
import json

import numpy as np
import pandas as pd
import pyarrow.parquet as pq

from common import OUT, SEP_DIR, FROZEN, MASTERS, MAIN
import build_features_sharadar as BF

N_GAP = 20
H = 40
TRAIL = 252


def load_sep_keys():
    fr = [pd.read_parquet(f, columns=["ticker", "date"]) for f in sorted(SEP_DIR.glob("*.parquet"))]
    df = pd.concat(fr, ignore_index=True)
    df["date"] = pd.to_datetime(df["date"]).astype("datetime64[ns]")
    df["ticker"] = df["ticker"].astype(str)
    return df.drop_duplicates().sort_values(["ticker", "date"]).reset_index(drop=True)


def main():
    sep = load_sep_keys()
    cal = np.sort(sep["date"].unique())
    pos = np.searchsorted(cal, sep["date"].to_numpy())
    print(f"SEP {len(sep):,} rows, {sep.ticker.nunique():,} symbols, {len(cal):,} days")

    ents = BF.load_reuse_entities(MASTERS)
    # stale-master-only run: what the live builder would see today without a TICKERS refresh
    ents_live = BF.load_reuse_entities((FROZEN / "tickers_master.csv",))

    tick = sep["ticker"].to_numpy()
    d = sep["date"].to_numpy()
    starts = np.r_[0, np.flatnonzero(tick[1:] != tick[:-1]) + 1]
    ends = np.r_[starts[1:], len(tick)]
    bnd_rows, gap_rows, nocand = [], [], 0
    for s, e in zip(starts, ends):
        sym = tick[s]
        c = ents.get(sym, [])
        if not c:
            nocand += 1
        b_all = set(BF.reuse_boundaries(d[s:e], c))
        b_live = set(BF.reuse_boundaries(d[s:e], ents_live.get(sym, [])))
        for b in sorted(b_all | b_live):
            cov = lambda x: sorted(pt for pt, f, l in c
                                   if f - np.timedelta64(5, "D") <= x <= l + np.timedelta64(5, "D"))
            bnd_rows.append({"ticker": sym, "prev_date": pd.Timestamp(d[s + b - 1]).date(),
                             "next_date": pd.Timestamp(d[s + b]).date(),
                             "gap_trading_days": int(pos[s + b] - pos[s + b - 1] - 1),
                             "rows_before": int(b), "rows_after": int(e - s - b),
                             "found_fresh_union": b in b_all, "found_live_master": b in b_live,
                             "entities_prev": " ".join(cov(d[s + b - 1])),
                             "entities_next": " ".join(cov(d[s + b]))})
        p = pos[s:e]
        gi = np.flatnonzero(np.diff(p) - 1 > N_GAP)
        for g in gi:
            b = g + 1
            a_dt, b_dt = d[s + b - 1], d[s + b]
            tol = np.timedelta64(5, "D")
            same = any(f - tol <= a_dt <= l + tol and f - tol <= b_dt <= l + tol for _, f, l in c)
            cls = ("a_D1_boundary" if b in b_all else
                   "b_same_entity" if same else "c_unresolved")
            gap_rows.append({"ticker": sym, "prev_date": pd.Timestamp(a_dt).date(),
                             "next_date": pd.Timestamp(b_dt).date(),
                             "gap_trading_days": int(p[b] - p[b - 1] - 1), "class": cls})
    B = pd.DataFrame(bnd_rows)
    G = pd.DataFrame(gap_rows)
    B.to_csv(OUT / "reuse_boundaries.csv", index=False)
    G.to_csv(OUT / "d2_gaps.csv", index=False)

    # ---- reach: price/XGB panel and v2 panel ------------------------------------------------
    syms = sorted(B.ticker.unique()) if len(B) else []
    px = pq.read_table(FROZEN / "features_sharadar_pit.parquet", columns=["ticker", "date"],
                       filters=[("ticker", "in", syms)]).to_pandas() if syms else pd.DataFrame()
    v2 = pq.read_table(FROZEN / "composite_panel_v2.parquet", columns=["ticker", "date"],
                       filters=[("ticker", "in", syms)]).to_pandas() if syms else pd.DataFrame()
    reach = []
    for sym in syms:
        bb = B[B.ticker == sym]
        r = {"ticker": sym, "n_boundaries": len(bb),
             "boundaries": ";".join(f"{a}>{b}" for a, b in zip(bb.prev_date, bb.next_date)),
             "in_price_panel": bool((px.ticker == sym).any()) if len(px) else False,
             "in_v2_panel": bool((v2.ticker == sym).any()) if len(v2) else False}
        for name, P in (("price", px), ("v2", v2)):
            g = P[P.ticker == sym].sort_values("date") if len(P) else P
            if not len(g):
                r.update({f"{name}_label_cross_2007_2019": 0, f"{name}_label_cross_all": 0,
                          f"{name}_trail_cross_all": 0, f"{name}_trail_cross_2026": 0})
                continue
            gd = g["date"].to_numpy().astype("datetime64[ns]")
            seg = np.zeros(len(gd), int)
            for nd in pd.to_datetime(bb.next_date).to_numpy():
                seg += (gd >= nd)
            i = np.arange(len(gd))
            j = i + H
            lab = (j < len(gd)) & (seg[np.minimum(j, len(gd) - 1)] != seg)
            k = i - (TRAIL - 1)
            trl = (k >= 0) & (seg[np.maximum(k, 0)] != seg) | ((k < 0) & (seg != 0))
            yr = pd.DatetimeIndex(gd).year
            r[f"{name}_label_cross_2007_2019"] = int((lab & (yr >= 2007) & (yr <= 2019)).sum())
            r[f"{name}_label_cross_all"] = int(lab.sum())
            r[f"{name}_trail_cross_all"] = int(trl.sum())
            r[f"{name}_trail_cross_2026"] = int((trl & (yr >= 2026)).sum())
            r[f"{name}_label_cross_dates"] = ";".join(str(pd.Timestamp(x).date()) for x in gd[lab])[:400]
        reach.append(r)
    R = pd.DataFrame(reach)
    R.to_csv(OUT / "reach_labels.csv", index=False)

    # ---- forward ledgers since 2026-09-08 --------------------------------------------------
    led = []
    L = MAIN / "out" / "reset2026"
    for nm in ["v3", "ext", "sue", "seas", "io", "r252", "blend_seas"]:
        f = L / f"prediction_ledger_{nm}.csv"
        x = pd.read_csv(f, low_memory=False)
        x = x[pd.to_datetime(x.panel_date) >= "2026-09-08"]
        x = x[x.ticker.astype(str).isin(syms)]
        for _, row in x.iterrows():
            bb = B[B.ticker == row.ticker]
            after = (pd.to_datetime(bb.next_date) <= pd.Timestamp(row.panel_date)).any()
            rk = [c for c in x.columns if c.endswith("rank_pct")]
            led.append({"ledger": nm, "ticker": row.ticker, "panel_date": row.panel_date,
                        "after_boundary": bool(after),
                        **{c: row[c] for c in rk},
                        **({"is_pick": row["is_pick"]} if "is_pick" in x.columns else {})})
    LD = pd.DataFrame(led)
    LD.to_csv(OUT / "reach_ledgers.csv", index=False)

    summ = {
        "sep_rows": int(len(sep)), "sep_symbols": int(sep.ticker.nunique()),
        "symbols_without_any_tickers_entity": int(nocand),
        "D1_reuse_symbols": int(B[B.found_fresh_union].ticker.nunique()) if len(B) else 0,
        "D1_boundaries": int(B.found_fresh_union.sum()) if len(B) else 0,
        "D1_live_master_only_symbols": int(B[B.found_live_master].ticker.nunique()) if len(B) else 0,
        "D1_boundaries_gap_le_20": int((B.found_fresh_union & (B.gap_trading_days <= N_GAP)).sum()) if len(B) else 0,
        "D2_gaps": int(len(G)), "D2_by_class": G["class"].value_counts().to_dict() if len(G) else {},
        "reuse_symbols_in_price_panel": int(R.in_price_panel.sum()) if len(R) else 0,
        "reuse_symbols_in_v2_panel": int(R.in_v2_panel.sum()) if len(R) else 0,
        "price_label_cross_2007_2019_rows": int(R.price_label_cross_2007_2019.sum()) if len(R) else 0,
        "v2_label_cross_2007_2019_rows": int(R.v2_label_cross_2007_2019.sum()) if len(R) else 0,
        "ledger_rows_since_2026_09_08": int(len(LD)),
        "ledger_rows_after_boundary": int(LD.after_boundary.sum()) if len(LD) else 0,
    }
    (OUT / "detect_summary.json").write_text(json.dumps(summ, indent=2, default=str))
    print(json.dumps(summ, indent=2, default=str))


if __name__ == "__main__":
    main()
