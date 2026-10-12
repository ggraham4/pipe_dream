"""
WO-61 Part 2 (DESCRIPTIVE ONLY): spread-based costs for the WO-58 base and variant books (133 dates, 2 offsets).
Plan: final/models/2026-10-10-thinbook-audit.md section 5.   caffeinate -i $PY run_costs.py
Half-spread = (ask-bid)/(ask+bid) from CRSP closing quotes (dsf_bidask_YYYY.parquet) on e=t+1 (entry) and x=t+40
(exit; last row in (e, x] if the name stops trading); invalid/missing -> Corwin-Schultz from Sharadar SEP OHLC
(day-1, day); OHLC missing -> 7.5bp. Floor 5bp per side; x1.5 after the floor.
Research code only; never trades.
"""
from __future__ import annotations

import numpy as np
import pandas as pd

import ta_common as A
import ta_frame as F
import common as K
import run_book as RBK   # cwbook runner (ew_pool), read-only

B, log = A.B, A.log
FLOOR = 5e-4
DEFAULT = 7.5e-4
MAXREL = 0.50
DAY0 = np.datetime64("1990-01-01", "D")


def load_quotes(perms):
    q = pd.concat([pd.read_parquet(K.CRSP_DIR / f"dsf_bidask_{y}.parquet",
                                   filters=[("permno", "in", perms)]) for y in range(2008, 2020)], ignore_index=True)
    q["date"] = pd.to_datetime(q.date).astype("datetime64[ns]")
    assert q.date.max() <= A.READ_CAP
    q = q.sort_values(["permno", "date"]).drop_duplicates(["permno", "date"]).reset_index(drop=True)
    bid, ask = q.bid.to_numpy(float), q.ask.to_numpy(float)
    with np.errstate(invalid="ignore", divide="ignore"):
        hs = (ask - bid) / (ask + bid)
        ok = (bid > 0) & (ask > bid) & (2 * hs <= MAXREL)
    q["hs"] = np.where(ok, hs, np.nan)
    q["key"] = q.permno.to_numpy(np.int64) * 100000 + (q.date.values.astype("datetime64[D]") - DAY0).astype(np.int64)
    return q


def load_cs(tickers):
    """Corwin-Schultz half-spread per (ticker, date) from Sharadar SEP high/low on (prev row, row)."""
    months = pd.period_range("2007-12", "2019-03", freq="M")
    parts = []
    for m in months:
        f = B.T.SEP / f"{m}.parquet"
        if f.exists():
            s = pd.read_parquet(f, columns=["ticker", "date", "high", "low"], filters=[("ticker", "in", tickers)])
            parts.append(s)
    s = pd.concat(parts, ignore_index=True)
    s["date"] = pd.to_datetime(s.date).astype("datetime64[ns]")
    s = s[s.date <= A.READ_CAP].sort_values(["ticker", "date"]).drop_duplicates(["ticker", "date"]).reset_index(drop=True)
    h, l = s.high.to_numpy(float), s.low.to_numpy(float)
    same = s.ticker.to_numpy()[1:] == s.ticker.to_numpy()[:-1]
    hp = np.r_[np.nan, np.where(same, h[:-1], np.nan)]
    lp = np.r_[np.nan, np.where(same, l[:-1], np.nan)]
    with np.errstate(invalid="ignore", divide="ignore"):
        beta = np.log(h / l) ** 2 + np.log(hp / lp) ** 2
        gamma = np.log(np.maximum(h, hp) / np.minimum(l, lp)) ** 2
        k = 3 - 2 * np.sqrt(2)
        alpha = (np.sqrt(2 * beta) - np.sqrt(beta)) / k - np.sqrt(gamma / k)
        S = 2 * (np.exp(alpha) - 1) / (1 + np.exp(alpha))
    S = np.where(np.isfinite(S), np.maximum(S, 0.0), np.nan)
    s["cs_hs"] = S / 2.0
    return s[["ticker", "date", "cs_hs"]]


def half_spreads(pr, q, cs):
    """hs_e, hs_x and source per pick row."""
    qk, qhs, qd = q.key.to_numpy(), q.hs.to_numpy(), q.date.values
    qp = q.permno.to_numpy(np.int64)
    mapped = pr.permno.notna().to_numpy()
    pm = np.where(mapped, pr.permno.fillna(0).to_numpy(), 0).astype(np.int64)
    e, x = pr.e.values.astype("datetime64[ns]"), pr.x.values.astype("datetime64[ns]")
    ke = pm * 100000 + (e.astype("datetime64[D]") - DAY0).astype(np.int64)
    kx = pm * 100000 + (x.astype("datetime64[D]") - DAY0).astype(np.int64)
    ie = np.clip(np.searchsorted(qk, ke), 0, len(qk) - 1)
    has_e = mapped & (qk[ie] == ke)
    ix = np.clip(np.searchsorted(qk, kx, side="right") - 1, 0, len(qk) - 1)
    has_x = mapped & (qp[ix] == pm) & (qd[ix] > e)            # last CRSP row in (e, x]
    x_day = np.where(has_x, qd[ix], x)                         # exit day (earlier if the name stopped trading)
    hs_e = np.where(has_e, qhs[ie], np.nan)
    hs_x = np.where(has_x, qhs[ix], np.nan)
    csi = cs.set_index(["ticker", "date"]).cs_hs
    cs_t = cs.groupby("ticker")
    out = {}
    for leg, hs, day in (("e", hs_e, e), ("x", hs_x, x_day)):
        src = np.where(np.isfinite(hs), "quote", "")
        need = np.flatnonzero(~np.isfinite(hs))
        vals = csi.reindex(pd.MultiIndex.from_arrays([pr.ticker.values[need], day[need]])).to_numpy(float).copy()
        if leg == "x":   # name stopped before x in Sharadar too: last Sharadar row <= x
            miss = need[~np.isfinite(vals)]
            for j in miss:
                t = pr.ticker.values[j]
                if t in cs_t.groups:
                    g = cs_t.get_group(t)
                    g = g[(g.date.values <= x[j]) & (g.date.values > e[j])]
                    if len(g):
                        vals[np.searchsorted(need, j)] = g.cs_hs.iloc[-1]
        hs = hs.copy()
        hs[need] = vals
        src[need] = np.where(np.isfinite(vals), "corwin_schultz", "default")
        hs = np.where(np.isfinite(hs), hs, DEFAULT)
        out[leg] = (hs, src)
    return out


def eval_costs(D, picks, pr, mode, mult=1.0, flat=None):
    """Per-date net with per-name costs. mode 'primary' (WO-58 formula analog, count share) or 'weighted'."""
    by_i = {i: g for i, g in pr.groupby("i", sort=True)}
    kept = []
    for i, dd in enumerate(D):
        if i not in by_i:
            continue
        g = by_i[i]
        ce = np.full(len(g), flat) if flat is not None else mult * np.maximum(g.hs_e.to_numpy(), FLOOR)
        cx = np.full(len(g), flat) if flat is not None else mult * np.maximum(g.hs_x.to_numpy(), FLOOR)
        gross = float(np.dot(g.wn.to_numpy(), 1.0 + g.r_S.to_numpy()) - 1.0)
        kept.append((dd["date"], gross, g.ticker.to_numpy(), g.wn.to_numpy(), ce, cx, dd["spy"]))
    per = []
    for off in range(B.N_OFF):
        seq = kept[off::B.N_OFF]
        prev = np.empty(0, object)
        ex = []
        for k, (d, gross, cur, wn, ce, cx, s) in enumerate(seq):
            new = ~np.isin(cur, prev)
            if mode == "primary":
                c_in, c_out = ce[new].sum() / len(cur), cx[new].sum() / len(cur)
            else:
                nxt = seq[k + 1][2] if k + 1 < len(seq) else np.empty(0, object)
                leave = ~np.isin(cur, nxt)
                c_in, c_out = float((wn * ce)[new].sum()), float((wn * cx)[leave].sum())
            net = (1.0 + gross) * (1.0 - c_in) / (1.0 + c_out) - 1.0
            prev = cur
            if np.isfinite(s):
                ex.append(net - s)
        per.append(float(np.mean(ex) * A.ANN))
    return float(np.mean(per)), per


def main():
    A.guard_inputs([A.PANEL_V2, A.OUTCOME_V2, A.UNIVERSE, A.FEATS1, B.SEAS_EXT, A.XWALK])
    b, D, uniq, dates, base, var, info = F.wo58_frame()
    cal = K.market_calendar(A.READ_CAP)
    rows = {}
    for name, pk in (("base", base), ("variant", var)):
        pr = F.attach_permno(F.pick_rows(D, uniq, pk, b))
        ci = np.searchsorted(cal, pr.date.values.astype("datetime64[ns]"))
        assert (cal[ci] == pr.date.values).all() and (ci + 40 < len(cal)).all()
        pr["e"], pr["x"] = cal[ci + 1], cal[ci + 40]
        assert pr.x.max() <= np.datetime64(A.READ_CAP)
        rows[name] = pr
    allp = pd.concat(rows.values())
    perms = sorted({int(x) for x in allp.permno.dropna()})
    q = load_quotes(perms)
    cs = load_cs(sorted(allp.ticker.unique().tolist()))
    for name, pr in rows.items():
        hs = half_spreads(pr, q, cs)
        pr["hs_e"], pr["src_e"] = hs["e"]
        pr["hs_x"], pr["src_x"] = hs["x"]
    ew = RBK.ew_pool(D)["gross_minus_spy_ann"]
    out = {"descriptive_only": True, "ew_thin_pool_gross_minus_spy": ew, "books": {}}
    for name, pk in (("base", base), ("variant", var)):
        pr = rows[name]
        ev, _ = B.evaluate(D, pk)
        flat15 = B.level(ev)
        mine_flat, _ = eval_costs(D, pk, pr, "primary", flat=7.5e-4)
        assert abs(mine_flat - flat15) < 1e-12, (name, mine_flat, flat15)
        res = {"flat15": flat15, "flat15_per_offset": [float(o["ex"].mean() * A.ANN) for o in ev]}
        for lab, mult in (("spread", 1.0), ("spread_x1.5", 1.5)):
            lv, po = eval_costs(D, pk, pr, "primary", mult)
            lw, _ = eval_costs(D, pk, pr, "weighted", mult)
            res[lab] = lv; res[lab + "_per_offset"] = po; res[lab + "_weighted_exact_turnover"] = lw
        lw15, _ = eval_costs(D, pk, pr, "weighted", flat=7.5e-4)
        res["flat15_weighted_exact_turnover"] = lw15
        res["vs_ew_pool"] = {k: res[k] - ew for k in ("flat15", "spread", "spread_x1.5")}
        src = pd.concat([pr.src_e, pr.src_x])
        res["source_share"] = {k: float(v) for k, v in src.value_counts(normalize=True).items()}
        he = np.maximum(pr.hs_e, FLOOR)
        res["half_spread_entry_floored_bp"] = {"median": float(he.median() * 1e4), "mean": float(he.mean() * 1e4),
                                               "p90": float(he.quantile(0.9) * 1e4),
                                               "share_at_floor": float((pr.hs_e <= FLOOR).mean())}
        res["half_spread_entry_by_year_bp"] = {int(y): {"median": float(g.median() * 1e4), "mean": float(g.mean() * 1e4)}
                                               for y, g in he.groupby(pr.date.dt.year)}
        out["books"][name] = res
        log(f"{name}: flat15 {100 * flat15:+.3f} spread {100 * res['spread']:+.3f} x1.5 {100 * res['spread_x1.5']:+.3f} "
            f"(weighted {100 * res['spread_weighted_exact_turnover']:+.3f}); median entry hs "
            f"{res['half_spread_entry_floored_bp']['median']:.1f}bp")
    bb, vv = out["books"]["base"], out["books"]["variant"]
    assert abs(bb["flat15"] - A.WO58_BASE) < 1e-9 and abs(vv["flat15"] - A.WO58_VAR) < 1e-9
    out["delta_variant_minus_base"] = {k: vv[k] - bb[k] for k in
                                       ("flat15", "spread", "spread_x1.5", "spread_weighted_exact_turnover",
                                        "spread_x1.5_weighted_exact_turnover", "flat15_weighted_exact_turnover")}
    log(f"delta: {out['delta_variant_minus_base']}")
    A.dump("part2_costs.json", out)


if __name__ == "__main__":
    main()
