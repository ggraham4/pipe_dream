"""
WO-9 ITERATE #1: the tradable hedged composite, with the dividend basis fixed.
Pre-registration: final/models/2026-09-25-hedged-composite.md section 3.6
(frozen before this ran).

tradable hedged (per rebalance) = price-only hedged + (book div yield - IWM div yield)
  implemented as backtest_vectors(icw8, bench = IWM40 + 10bp - (book_div - iwm_div))

Book dividend return per name over the hold, entry bar e=i+1 (open), exit
x=i+40 (or the series' last bar when the name genuinely stops trading, the
outcome cache's delisting floor), with f = closeadj/close from the Sharadar
SEP panel (the source every book OHLC CSV was exported from):
    div = close[x]/open[e] * (f[x]/f[e] - 1)
IWM: the same, with f = Adj Close / Close (yfinance).

Imports hedged_composite (HC), noscore_control_v2 (NX), downcap_v2_readout (R).
Panel loaded 2006-12..2019-12 only; every frame asserts max(date) < 2020-01-01.

Output: /Users/ggraham/pipe_dream/final/out/reset2026/downcap_v2/hedged_tradable.json
"""
import json
import sys
import time
from pathlib import Path

import numpy as np
import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parent))
import downcap_v2_readout as R             # noqa: E402
import noscore_control_v2 as NX            # noqa: E402
import hedged_composite as HC              # noqa: E402

OUT = R.V2 / "hedged_tradable.json"
PANEL = R.SH / "panel" / "stocks"
TIERS = HC.TIERS
ANN = HC.ANN
log = R.log
NAME_CHECK = {("JNJ", 2017): 3.32, ("JNJ", 2018): 3.54, ("XOM", 2017): 3.06}


def load_panel(tickers):
    files = sorted(f for f in PANEL.glob("*.parquet") if "2006-12" <= f.stem <= "2019-12")
    parts = []
    for f in files:
        d = pd.read_parquet(f, columns=["ticker", "date", "open", "close", "closeadj"],
                            filters=[("ticker", "in", sorted(tickers))])
        parts.append(d)
    px = pd.concat(parts, ignore_index=True)
    px["date"] = pd.to_datetime(px["date"])
    px = HC.guard(px)
    px = px.drop_duplicates(["ticker", "date"]).sort_values(["ticker", "date"])
    out = {}
    for t, g in px.groupby("ticker", sort=False):
        out[t] = {"date": g["date"].to_numpy(), "open": g["open"].to_numpy(np.float64),
                  "close": g["close"].to_numpy(np.float64),
                  "f": (g["closeadj"] / g["close"]).to_numpy(np.float64)}
    return out


def name_check(px):
    res = {}
    for (t, y), tgt in NAME_CHECK.items():
        s = px[t]
        f, c, d = s["f"], s["close"], pd.DatetimeIndex(s["date"])
        ratio = f[:-1] / f[1:]
        ex = np.flatnonzero(np.abs(ratio - 1.0) > 1e-6) + 1
        divs = c[ex - 1] * (1.0 - f[ex - 1] / f[ex])
        m = d[ex].year == y
        got = float(divs[m].sum())
        res[f"{t}_{y}"] = {"got": got, "target": tgt, "n_exdates": int(m.sum()),
                           "per_ex": [(str(d[e].date()), round(float(v), 4)) for e, v in zip(ex[m], divs[m])],
                           "ok": abs(got / tgt - 1.0) <= 0.02}
        log(f"name-check {t} {y}: {got:.4f} vs {tgt} ({m.sum()} ex-dates) {res[f'{t}_{y}']['per_ex']}")
        assert res[f"{t}_{y}"]["ok"], f"DIVIDEND NAME-CHECK FAIL {t} {y}"
    return res


def main():
    T0 = time.time()
    out = {"work_order": "WO-9 ITERATE #1", "prereg": "final/models/2026-09-25-hedged-composite.md §3.6",
           "dividend_source": "Sharadar SEP panel closeadj/close (actions.csv covers only 2025-09..2026-09)",
           "book_cost_bps": R.COST_BPS, "short_leg_bps_per_rebalance": HC.SHORT_BPS}

    iwm = HC.load_iwm()
    p, spy = R.load_column("c")
    HC.guard(p)
    all_dates = sorted(p["date"].unique())
    DI = pd.DatetimeIndex(all_dates)
    spy_s = spy.astype(np.float64).reindex(DI)
    iwm_p = HC.ret40(iwm).reindex(DI)
    iwm_t = HC.ret40(iwm, total_return=True).reindex(DI)
    iwm_div = (iwm_t - iwm_p)
    live = iwm_p.notna()
    common = DI >= HC.COMMON_START
    sb = HC.SHORT_BPS / 1e4

    books, _ = NX.build_books(p, TIERS, with_null=False)
    del p
    log(f"books built ({time.time()-T0:.0f}s)")

    tickers = {t for t, _ in NAME_CHECK}
    for tier in TIERS:
        for d, v in books[tier]["icw8"].items():
            tickers |= set(v[2])
    px = load_panel(tickers)
    log(f"panel loaded: {len(px)} tickers ({time.time()-T0:.0f}s)")
    out["dividend_name_check"] = name_check(px)

    tm = pd.read_csv(R.SH / "tickers_master.csv", dtype=str, usecols=["ticker", "lastpricedate"])
    tm["lastpricedate"] = pd.to_datetime(tm["lastpricedate"], errors="coerce")
    lastprice = tm.groupby("ticker")["lastpricedate"].max().to_dict()
    live_set = set(DI[live.to_numpy()])

    out["tiers"] = {}
    for tier in TIERS:
        bk = books[tier]["icw8"]
        bdiv, stats = {}, {"dates": 0, "names": 0, "missing_in_panel": 0, "era_truncated": 0,
                           "delist_floor": 0, "gross_max_abs_diff": 0.0}
        for d, v in bk.items():
            if d not in live_set:
                continue
            tk, w = v[2], v[3]
            dv, gr, wsum = 0.0, 0.0, 0.0
            for t, wi in zip(tk, w):
                s = px.get(t)
                if s is None:
                    stats["missing_in_panel"] += 1
                    continue
                i = int(np.searchsorted(s["date"], np.datetime64(d)))
                assert i < len(s["date"]) and s["date"][i] == np.datetime64(d), f"{t} {d} not in panel"
                n = len(s["date"])
                e, x = i + 1, i + HC.H
                if x > n - 1:
                    lp = lastprice.get(t)
                    if lp is not None and pd.notna(lp) and lp <= R.END:
                        x = n - 1
                        stats["delist_floor"] += 1
                    else:
                        stats["era_truncated"] += 1
                        x = n - 1
                pr = s["close"][x] / s["open"][e]
                gr += wi * pr
                dv += wi * pr * (s["f"][x] / s["f"][e] - 1.0)
                stats["names"] += 1
            stats["dates"] += 1
            stats["gross_max_abs_diff"] = max(stats["gross_max_abs_diff"], abs((gr - 1.0) - v[0]))
            bdiv[d] = dv
        log(f"{tier}: basis reconcile book gross max|diff| {stats['gross_max_abs_diff']:.2e}; {stats}")
        assert stats["missing_in_panel"] == 0
        assert stats["gross_max_abs_diff"] < 1e-5, "BOOK GROSS BASIS RECONCILE FAIL"

        bd = pd.Series(bdiv).reindex(DI)
        spread = bd - iwm_div
        yld = {}
        for wname, m in (("full", live.to_numpy()), ("common", live.to_numpy() & common)):
            yld[wname] = {"book_div_yield_ann": float(bd[m].mean() * ANN),
                          "iwm_div_yield_ann": float(iwm_div[m].mean() * ANN),
                          "book_minus_iwm_ann": float(spread[m].mean() * ANN),
                          "n_rebalance_dates": int(m.sum())}
        log(f"  {tier} yields: {yld}")

        tr = {"basis_stats": stats, "yields_pooled": yld, "variants": {}}
        for vname, base, cost in (("tradable_15bp", iwm_p + sb, None), ("tradable_0bp", iwm_p, 0.0),
                                  ("price_only_15bp_recheck", iwm_p + sb, None)):
            bench = base - spread if vname != "price_only_15bp_recheck" else base
            full, _, _, _ = HC.run_vec(bk, all_dates, bench, cost)
            comm, _, _, _ = HC.run_vec(bk, all_dates, bench.where(common), cost)
            c = R.COST_BPS if cost is None else cost
            ex_f = HC.extras(HC.chain_series(bk, all_dates, bench, c), spy_s)
            ex_c = HC.extras(HC.chain_series(bk, all_dates, bench.where(common), c), spy_s)
            tr["variants"][vname] = {"full": {**full, **ex_f}, "common": {**comm, **ex_c},
                                     "gates_as_primary": HC.gates(full, comm, ex_f)}
            log(f"  {tier} {vname}: full {full['mean40']:+.4f} ({full['offsets_positive']}/40, LOYO min "
                f"{full['loyo_min']:+.4f} drop {full['loyo_min_dropped_year']}) common {comm['mean40']:+.4f} "
                f"({comm['offsets_positive']}/40, LOYO {comm['loyo_min']:+.4f}) beta {ex_f['beta_to_spy']['beta']:+.3f}")
        prev = json.loads((R.V2 / "hedged_composite.json").read_text())["tiers"][tier]["hedged"]["primary_15bp"]
        rc = tr["variants"]["price_only_15bp_recheck"]
        assert abs(rc["full"]["mean40"] - prev["full"]["mean40"]) < 1e-12
        assert abs(rc["common"]["mean40"] - prev["common"]["mean40"]) < 1e-12
        out["tiers"][tier] = tr
        OUT.write_text(json.dumps(out, indent=2, default=str))

    t150 = out["tiers"]["cap150"]["variants"]["tradable_15bp"]
    v = "KILL" if t150["common"]["mean40"] <= 0 else "MIDDLE"
    out["frozen_reading_cap150"] = {"tradable_common_mean40": t150["common"]["mean40"],
                                    "tradable_full_mean40": t150["full"]["mean40"],
                                    "tradable_full_loyo_min": t150["full"]["loyo_min"], "verdict": v}
    OUT.write_text(json.dumps(out, indent=2, default=str))
    log(f"FROZEN READING cap150: {v} ({time.time()-T0:.0f}s)")


if __name__ == "__main__":
    main()
