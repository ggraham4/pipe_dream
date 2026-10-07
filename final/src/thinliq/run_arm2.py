"""
WO-37 Arm 2 (secondary; cannot create a pass): sell one cash-secured put per
thin-slice name at the 0.30-delta bucket, with the WO-O1 backtester's rules
UNCHANGED. Every rule function is imported from options_wo25/run_wo_o1.py
(target_expiry, filter_puts F0-F6 + Amendment 1, pick_contract, settle,
pnl_row, summarize, cycle_excess). Spec: final/models/2026-10-01-thin-liquidity-prereg.md
section 4.

    python run_arm2.py --labels noise [--seed 7]     # plumbing: lognormal S_T, no real market path
    python run_arm2.py --phase2                      # the one real run (guarded)

What this file adds to WO-O1: the thin universe, one bucket, no score arm, the
fillable rule and the capacity numbers.
"""
from __future__ import annotations

import argparse
import json
import math
import time

import numpy as np
import pandas as pd

import tl_common as T
import run_wo_o1 as W                                   # noqa: E402  (imported, never edited)
from build_option_chain_unified import bs_price          # noqa: E402

# ---- pre-registered constants (doc section 4)
DELTA = -0.30
MIN_BID_SIZE = 5           # contracts quoted at the bid (applies where AV populates sizes for the name-date)
MIN_OI = 50                # open interest of the chosen contract (prior close)
OI_PARTICIPATION = 0.10    # capacity: at most 10% of the contract's open interest ...
CAP_MIN_SURVIVE = 250_000  # median $ collateral deployable per month for SURVIVES
CAP_DEAD = 100_000         # below this, DEAD on capacity whatever the return
NAMED = [("WAMUQ", "2008-08-20"), ("WAMUQ", "2008-09-17"), ("ATPAQ", "2012-07-18")]
RESULT = T.OUT / "arm2_results.json"


_TRADING_DAYS = None


def trading_days():
    """Sorted DatetimeIndex of market days (SPY), as run_wo_o1 passes to accepted_expiries. Cached."""
    global _TRADING_DAYS
    if _TRADING_DAYS is None:
        _TRADING_DAYS = pd.DatetimeIndex(sorted(pd.read_csv(W.SPY_CSV, usecols=["date"],
                                                            parse_dates=["date"])["date"].unique()))
    return _TRADING_DAYS


def hand_check():
    """Hand-computed contracts (doc section 6.3). Literal expected values, written before the code ran."""
    cases = []
    # 1. assigned, no split: K 10, bid 0.50, S_T 8, 3m bill 2%, 30 days
    #    premium 50; payoff 100*(10-8)=200; liquidation 100*8*0.00075=0.60; interest 1000*(1.02^(30/365)-1)=1.62894
    cases.append(("assigned", W.pnl_row(10.0, 0.50, 8.0, 1.0, 0.02, 30)["pnl"], 50 - 200 - 0.60 + 1.62894))
    # 2. 2:1 split inside the holding period: unadjusted S_T 4.5, r 2 -> deliverable worth 9 against strike 10
    #    payoff 100*(10-9)=100; liquidation 100*2*4.5*0.00075=0.675
    cases.append(("split_2for1", W.pnl_row(10.0, 0.50, 4.5, 2.0, 0.02, 30)["pnl"], 50 - 100 - 0.675 + 1.62894))
    # 3. expires worthless: S_T 12
    cases.append(("otm", W.pnl_row(10.0, 0.50, 12.0, 1.0, 0.02, 30)["pnl"], 50 + 1.62894))
    # 4. settle(): split ratio from adjusted/unadjusted closes, and the delisting floor
    t, s1, s2 = pd.Timestamp("2015-01-02"), pd.Timestamp("2015-01-16"), pd.Timestamp("2015-02-20")
    px = pd.DataFrame({"date": [t, s1], "close": [10.0, 4.5], "closeunadj": [20.0, 4.5]})
    a = W.settle(px, t, s1)
    b = W.settle(px, t, s2)     # series ends before the settlement day -> last close, delisted_floor
    out = {"cases": [{"case": n, "code": float(c), "by_hand": float(h), "ok": bool(abs(c - h) < 1e-3)} for n, c, h in cases],
           "settle_split": {"r": a["r"], "S_T": a["S_T"], "status": a["status"], "ok": bool(a["r"] == 2.0 and a["S_T"] == 4.5 and a["status"] == "normal")},
           "settle_delisted": {"S_T": b["S_T"], "status": b["status"], "ok": bool(b["S_T"] == 4.5 and b["status"] == "delisted_floor")}}
    out["all_ok"] = bool(all(c["ok"] for c in out["cases"]) and out["settle_split"]["ok"] and out["settle_delisted"]["ok"])
    return out


def build_entries(dates, universe="thin"):
    """One row per (date, name) that has a listed put inside the delta tolerance on the target expiry.
    Quote-side only: no settlement, no return."""
    u = T.universe_on(dates)
    u = u[u.thin] if universe == "thin" else u[u.eligible_cap2000]
    elig = u.groupby("date").ticker.apply(set).to_dict()
    rows = []
    for t in dates:
        ch = pd.read_parquet(T.CHAIN / f"date={t.date()}.parquet")
        cb = ch[ch.bid > 0]
        sizes_pop = ((cb.bid_size.fillna(0) > 0).groupby(cb.sharadar_ticker).mean() >= W.SIZE_POPULATED).to_dict()
        ch = ch[(ch.call_put == "Put") & ch.sharadar_ticker.isin(elig.get(t, set()))]
        exp = W.target_expiry(t)
        ch["expiration"] = pd.to_datetime(ch.expiration)
        # WO-47: WO-35 holiday-expiry fix (82fc8db), same rule run_wo_o1 uses: the 3rd Friday, the
        # Saturday after, or the trading day before when that Friday is a market holiday.
        ch = ch[ch.expiration.isin(W.accepted_expiries(exp, trading_days()))]
        for tk, g in ch.groupby("sharadar_ticker"):
            spot = float(g.spot.iloc[0])
            sp = bool(sizes_pop.get(tk, False))
            pf = W.filter_puts(g, spot, sizes_populated=sp)
            c, nearest = W.pick_contract(pf, DELTA)
            if nearest is None:
                continue
            x = c if c is not None else nearest
            oi = float(x.open_interest) if np.isfinite(x.open_interest) else 0.0
            bs = float(x.bid_size) if np.isfinite(x.bid_size) else 0.0
            quoted = c is not None
            size_ok = (bs >= MIN_BID_SIZE) if sp else True          # size unknown before ~2010: not held against the entry
            fill = quoted and oi >= MIN_OI and size_ok
            cap_n = math.floor(OI_PARTICIPATION * oi)
            if sp:
                cap_n = min(cap_n, int(bs))
            rows.append({"date": t, "ticker": tk, "expiry": exp, "quoted": quoted, "nearest_why": nearest.why,
                         "strike": float(x.strike), "bid": float(x.bid), "ask": float(x.ask), "iv": float(x.vol),
                         "delta": float(x.delta), "spot": spot, "bid_size": bs, "open_interest": oi,
                         "volume": float(x.volume) if np.isfinite(x.volume) else 0.0, "sizes_populated": sp,
                         "rel_spread": (float(x.ask) - float(x.bid)) / ((float(x.ask) + float(x.bid)) / 2) if x.ask + x.bid > 0 else np.nan,
                         "fillable": bool(fill), "fillable_strict": bool(quoted and sp and bs >= MIN_BID_SIZE and oi >= MIN_OI),
                         "fillable_oi_only": bool(quoted and oi >= MIN_OI),
                         "cap_contracts": int(cap_n) if fill else 0})
    for r_ in rows:   # verdict capacity: also capped at the contract's own volume on the entry day
        r_["cap_contracts_vol"] = int(min(r_["cap_contracts"], r_["volume"]))
    E = pd.DataFrame(rows)
    E["cap_collateral"] = E.cap_contracts * 100 * E.strike
    E["cap_premium"] = E.cap_contracts * 100 * E.bid
    E["cap_collateral_vol"] = E.cap_contracts_vol * 100 * E.strike
    E["cap_premium_vol"] = E.cap_contracts_vol * 100 * E.bid
    return E, {t: len(elig.get(t, set())) for t in dates}


def capacity(E):
    """Verdict capacity is the volume-capped one. The open-interest-only figure is an upper bound (descriptive)."""
    f = E[E.fillable]
    by = f.groupby("date").agg(entries=("ticker", "size"), collateral=("cap_collateral", "sum"), premium=("cap_premium", "sum"),
                               collateral_vol=("cap_collateral_vol", "sum"), premium_vol=("cap_premium_vol", "sum"),
                               traded=("cap_contracts_vol", lambda x: int((x > 0).sum())))
    by = by.reindex(sorted(E.date.unique()), fill_value=0)
    return {"fillable_entries_per_month_median": float(by.entries.median()),
            "VERDICT_volume_capped": {
                "entries_with_capacity_per_month_median": float(by.traded.median()),
                "collateral_usd_per_month_median": float(by.collateral_vol.median()),
                "collateral_usd_per_month_min": float(by.collateral_vol.min()),
                "premium_usd_per_month_median": float(by.premium_vol.median()),
                "share_of_fillable_entries_with_zero_volume": float((f.volume == 0).mean()) if len(f) else None,
                "rule": f"min(bid_size where populated, floor({OI_PARTICIPATION:.0%} x OI), the contract's own volume that day) x 100 x strike"},
            "open_interest_only_UPPER_BOUND_DESCRIPTIVE": {
                "collateral_usd_per_month_median": float(by.collateral.median()), "collateral_usd_per_month_min": float(by.collateral.min()),
                "premium_usd_per_month_median": float(by.premium.median()),
                "median_cap_contracts_per_entry": float(f.cap_contracts.median()) if len(f) else 0.0,
                "rule": f"min(bid_size where populated, floor({OI_PARTICIPATION:.0%} x OI)) x 100 x strike"}}


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--labels", choices=["noise"], default=None)
    ap.add_argument("--phase2", action="store_true")
    ap.add_argument("--seed", type=int, default=7)
    a = ap.parse_args()
    if a.phase2 == (a.labels is not None):
        raise SystemExit("choose exactly one of --phase2 or --labels noise")
    t0 = time.time()
    hc = hand_check()
    if not hc["all_ok"]:
        raise SystemExit("hand-check arithmetic FAILED: " + json.dumps(hc))
    if a.phase2:
        dates = T.phase2_guard(RESULT)
        mode, tag = "real", ""
    else:
        comp = set(T.arrival_gate(write=False)["thin_complete_dates"])
        dates = [d for d in T.monthly_dates() if str(d.date()) in comp and (T.CHAIN / f"date={d.date()}.parquet").exists()]
        mode, tag = "noise", f"_SHUFFLED_TEST_labels-noise_seed{a.seed}"
    T.log(f"{mode} mode: {len(dates)} entry dates {dates[0].date()}..{dates[-1].date()}")
    E, n_elig = build_entries(dates, "thin")
    spy = pd.read_csv(W.SPY_CSV, usecols=["date", "close"], parse_dates=["date"]).set_index("date").close.sort_index()
    rates = pd.read_csv(W.RATES, usecols=["date", "y3m"], parse_dates=["date"]).set_index("date").y3m.sort_index() / 100
    rng = np.random.default_rng(a.seed)
    Q = E[E.quoted].copy()
    rows, named = [], {}
    for t, g in Q.groupby("date"):
        exp = g.expiry.iloc[0]
        settle_day = spy.index[spy.index <= exp.normalize() + pd.Timedelta(days=1)].max()
        days = (settle_day - t).days
        y3m = float(rates[rates.index <= t].iloc[-1])
        want_named = [n for n, d in NAMED if pd.Timestamp(d) == t]
        if mode == "real":
            spy_tr = spy[settle_day] / spy[t] - 1 + W.SPY_DIV_YIELD * days / 365.25
            px = W.load_prices(sorted(g.ticker.unique()), t, settle_day)
        else:
            spy_tr = (1 + y3m) ** (days / 365.0) - 1
            px = W.load_prices(want_named or ["__none__"], t, settle_day)
        for r in g.itertuples():
            real = W.settle(px.get(r.ticker), t, settle_day) if (mode == "real" or r.ticker in want_named) else None
            if mode == "real":
                if real is None:
                    continue
                S_T, rr, st = real["S_T"], real["r"], real["status"]
            else:
                Tn = max(days, 1) / 365.0
                S_T = r.spot * math.exp(math.log1p(y3m) * Tn - 0.5 * r.iv ** 2 * Tn + r.iv * math.sqrt(Tn) * rng.standard_normal())
                rr, st = 1.0, "noise"
            rows.append({"date": t, "ticker": r.ticker, "strike": r.strike, "bid": r.bid, "iv": r.iv, "spot": r.spot, "y3m": y3m,
                         "days": days, "spy_tr": spy_tr, "S_T": S_T, "r": rr, "settle_status": st,
                         "fillable": r.fillable, "fillable_strict": r.fillable_strict, "fillable_oi_only": r.fillable_oi_only,
                         "half_spread_over_K": (r.ask - r.bid) / 2 / r.strike, **W.pnl_row(r.strike, r.bid, S_T, rr, y3m, days)})
            if r.ticker in want_named and real is not None:   # real settlement for the named contract only (data-integrity check)
                nr = W.pnl_row(r.strike, r.bid, real["S_T"], real["r"], y3m, days)
                named[f"{r.ticker}@{t.date()}"] = {"strike": r.strike, "bid": r.bid, "settle_date": str(pd.Timestamp(real["settle_date"]).date()),
                                                    "S_T": real["S_T"], "r": real["r"], "settle_status": real["status"], "payoff": nr["payoff"],
                                                    "payoff_formula_ok": bool(abs(nr["payoff"] - 100 * max(r.strike - real["r"] * real["S_T"], 0)) < 1e-9)}
    P = pd.DataFrame(rows)
    # named presence: a thin-eligible name with a kept chain on a pulled date must be in the quoted pool
    ok_named = True
    u = T.universe_on([pd.Timestamp(d) for _, d in NAMED])
    for tk, ds in NAMED:
        key, d = f"{tk}@{ds}", pd.Timestamp(ds)
        if key in named:
            continue
        thin = bool(u[(u.ticker == tk) & (u.date == d)].thin.any())
        has = d in dates and bool((pd.read_parquet(T.CHAIN / f"date={ds}.parquet", columns=["sharadar_ticker"]).sharadar_ticker == tk).any())
        if thin and has:
            e = E[(E.ticker == tk) & (E.date == d)]
            named[key] = {"status": "thin with a kept chain but not in the quoted pool",
                          "reason": e.nearest_why.iloc[0] if len(e) else "no put inside the delta tolerance on the target expiry"}
            ok_named &= bool(len(e) == 0)      # absent for want of a 0.30-delta strike is a fact; filtered out is a FAIL
        else:
            named[key] = {"status": "not in pool: " + ("date not pulled for the thin slice yet" if d not in dates else
                                                       "not thin-eligible" if not thin else "no kept chain")}
    if "WAMUQ@2008-08-20" in named and "S_T" in named["WAMUQ@2008-08-20"]:
        w = named["WAMUQ@2008-08-20"]      # WO-25 doc section 4 published this close: 4.25 on 2008-09-19
        w["S_T_matches_published_4.25"] = bool(abs(w["S_T"] - 4.25) < 1e-9)
        ok_named &= w["S_T_matches_published_4.25"] and w["payoff_formula_ok"]

    spy_by = P.groupby("date").spy_tr.first()
    sets = {"quoted": P, "fillable": P[P.fillable], "fillable_strict_DESCRIPTIVE": P[P.fillable_strict],
            "fillable_oi_only_DESCRIPTIVE": P[P.fillable_oi_only]}
    res = {}
    for k, B in sets.items():
        s = W.summarize(W.cycle_excess(B, spy_by)) if len(B) else {"n_cycles": 0}
        s.pop("from2020_holdout_read_8", None); s.pop("pre2020", None)
        s.update({"positions": int(len(B)), "assigned_share": float(B.assigned.mean()) if len(B) else None,
                  "settle_status": B.settle_status.value_counts().to_dict() if len(B) else {},
                  "mean_half_spread_over_K": float(B.half_spread_over_K.mean()) if len(B) else None})
        res[k] = s
    cap = capacity(E)
    out = {"label_mode": mode, "entry_dates": [str(d.date()) for d in dates], "delta_bucket": DELTA,
           "fillable_rule": f"quoted (WO-O1 F0-F6) AND open_interest >= {MIN_OI} AND bid_size >= {MIN_BID_SIZE} where sizes are populated "
                            "for the name-date (>= 90% rule); size unknown is not held against the entry",
           "hand_check": hc, "named_check": named, "named_check_pass": bool(ok_named), "sets": res, "capacity": cap,
           "holdout_read": "none (no date from 2019 on is read)"}
    if mode == "noise":
        B = P
        Tn, rr = B.days / 365.0, np.log1p(B.y3m)
        epay = 100 * np.exp(rr * Tn) * bs_price(B.spot.to_numpy(), B.strike.to_numpy(), Tn.to_numpy(), rr.to_numpy(),
                                                B.iv.to_numpy(), np.zeros(len(B), bool))
        prd = (B.premium - epay + B.interest).groupby(B.date).sum() / B.collateral.groupby(B.date).sum() - spy_by
        ex = W.cycle_excess(B, spy_by).set_index("date").excess
        dif = ex - prd
        out["noise_unit_test"] = {"mean_cycle_excess": float(ex.mean()), "predicted_analytic": float(prd.mean()),
                                  "z_realized_minus_predicted": float(dif.mean() / (dif.std(ddof=1) / np.sqrt(len(dif)))),
                                  "note": "S_T is lognormal at each contract's own IV; excess is vs T-bill carry; expected about minus the half-spread"}
        out["verdict"] = None
    else:
        f = res["fillable"]
        capm = cap["VERDICT_volume_capped"]["collateral_usd_per_month_median"]
        survives = (f.get("excess_ann", -1) > 0 and f.get("odd_years", -1) > 0 and f.get("even_years", -1) > 0
                    and f.get("loyo_min", -1) > 0 and capm >= CAP_MIN_SURVIVE)
        dead = (not f.get("excess_ann", -1) > 0) or capm < CAP_DEAD
        out["verdict"] = "SURVIVES" if survives else ("DEAD" if dead else "MIDDLE")
    out["runtime_s"] = time.time() - t0
    path = T.OUT / f"arm2_results{tag}.json"
    path.write_text(json.dumps(out, indent=1, default=str))
    P.to_parquet(T.OUT / f"arm2_positions{tag}.parquet", index=False)
    T.log(f"hand check {'OK' if hc['all_ok'] else 'FAIL'}; named {'PASS' if ok_named else 'FAIL'}; wrote {path.name}")
    if mode == "noise":
        T.log(f"  noise unit test: {out['noise_unit_test']}")
    if not ok_named:
        raise SystemExit(2)


if __name__ == "__main__":
    main()
