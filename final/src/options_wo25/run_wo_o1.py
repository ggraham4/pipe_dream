"""
WO-O1 cash-secured put-selling backtester (WO-25). Spec, decision rules and
every constant below: final/models/2026-09-29-options-readiness-wo25.md
section 4 (committed before any Phase 2 number).

    # Phase 1 plumbing: pure-noise settlement (no real outcome in any aggregate)
    python run_wo_o1.py --labels noise
    # Phase 2: real settlement (guarded; hold-out read #8 for entries >= 2020)
    python run_wo_o1.py --phase2

Inputs (read only): WO-25 unified chain (gate_a.py output), v2 universe,
composite_panel_v2 (icw8 score at t-1), Sharadar SEP (settlement), SPY.csv,
treasury_yields.csv, WO-18 split-half OOS weights.

Named survivorship check (hard fail, BOTH modes): LEH/WM/WB puts entered
2008-08-20 (and WM/WB 2008-09-17) must be in arm (a)'s pool; their settlement
is computed on REAL Sharadar prices for those contracts only, never aggregated.

Why no 'shuffled' mode here: a within-date shuffle of stock returns keeps each
date's market move, so aggregate short-put P&L on shuffled labels would still
be the real 2008-2010 put P&L. Noise mode draws S_T from a lognormal at each
contract's own IV, so the expected per-cycle excess is known in advance
(about -(mid - bid)/K, the half-spread) and serves as a unit test.
"""
from __future__ import annotations

import argparse
import json
import math
import subprocess
import sys
import time
from pathlib import Path

import numpy as np
import pandas as pd

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE.parent / "reset2026"))
import ic_weighted_composite as ICW   # noqa: E402
sys.path.insert(0, str(HERE.parent))
from build_option_chain_unified import bs_price   # noqa: E402
sys.path.insert(0, str(HERE))
from wo25_io import read_on_dates         # noqa: E402

MAIN = Path("/Users/ggraham/pipe_dream/final")
REPO = HERE.parents[2]
OUT = HERE.parents[1] / "out" / "options_wo25"
CHAIN = OUT / "chain" / "source=av_monthly"
FEATS = OUT / "av_options_features_wo25.parquet"
UNIVERSE_V2 = MAIN / "data" / "sharadar" / "downcap_universe_v2.parquet"
PANEL_V2 = MAIN / "out" / "reset2026" / "composite_panel_v2.parquet"
SEP = MAIN / "data" / "sharadar" / "panel" / "stocks"
SPY_CSV = MAIN / "scripts" / "td_data_local" / "SPY.csv"
RATES = MAIN / "data" / "rates" / "treasury_yields.csv"
SEAS_REPORT = HERE.parents[1] / "out" / "seasonality" / "seas_screen_report.json"
PREREG_DOC = "final/models/2026-09-29-options-readiness-wo25.md"
ARRIVAL = OUT / "arrival_report.json"

# ---- pre-registered constants (doc section 4)
DELTAS = [-0.20, -0.30, -0.45]
PRIMARY_DELTA = -0.30
DELTA_TOL = 0.075
MIN_DTE = 14
INTRINSIC_SLACK = 0.05
SMOOTH_ABS, SMOOTH_REL = 0.10, 0.30
LIQ_COST = 0.00075            # half of 15bp round trip on assigned shares
SPY_DIV_YIELD = 0.02
QUINTILE = 0.20
NULL_DRAWS, NULL_PCTILE = 20, 0.80
HOLDOUT = pd.Timestamp("2020-01-01")
SIZE_POPULATED = 0.90         # Amendment 1: F2 only where >= 90% of the name's bid>0 contracts carry a size
SPLIT_SNAP = 0.02             # |r-1| below this = cent-rounding noise in adjusted close -> r = 1
NAMED = [("LEHMQ", "2008-08-20"), ("WAMUQ", "2008-08-20"), ("WB1", "2008-08-20"),
         ("WAMUQ", "2008-09-17"), ("WB1", "2008-09-17")]


def log(m):
    print(f"[{time.strftime('%H:%M:%S')}] {m}", flush=True)


# ------------------------------------------------------------------ calendar
def third_friday(y, m):
    d = pd.Timestamp(year=y, month=m, day=1)
    return d + pd.Timedelta(days=(4 - d.weekday()) % 7 + 14)


def target_expiry(t):
    """First standard monthly expiry (3rd Friday) with >= MIN_DTE calendar days."""
    y, m = t.year, t.month
    for _ in range(4):
        tf = third_friday(y, m)
        if (tf - t).days >= MIN_DTE:
            return tf
        m += 1
        if m > 12:
            y, m = y + 1, 1
    raise ValueError(t)


# ------------------------------------------------------------------ quote filter
def filter_puts(p, spot, sizes_populated=True):
    """p: puts of ONE name, ONE expiry. Returns p with a 'why' column ('' = passes)."""
    p = p.sort_values("strike").reset_index(drop=True)
    why = pd.Series("", index=p.index, dtype=object)
    dupk = p.strike.duplicated(keep=False)
    why[dupk] = "F0_dup_key"
    q = p[~dupk].copy()
    why[q.index[(q.bid <= 0) | (q.ask <= q.bid)] if len(q) else []] += "F1_bidask;"
    if sizes_populated:   # Amendment 1 (doc 4): F2 only where AV populates bid_size for this name-date
        why[q.index[q.bid_size.fillna(0) <= 0]] += "F2_bidsize0;"
    why[q.index[~np.isfinite(q.vol)]] += "F3_noiv;"
    intr = np.maximum(q.strike - spot, 0)
    why[q.index[q.bid < intr - INTRINSIC_SLACK]] += "F4_below_intrinsic;"
    # F5 monotonicity vs next higher listed strike (same expiry)
    nxt_ask = q.ask.shift(-1)
    why[q.index[(nxt_ask > 0) & (q.bid > nxt_ask)]] += "F5_monotone;"
    # F6 smoothness vs adjacent strikes with an IV
    iv = q.vol.where(np.isfinite(q.vol))
    ivq = iv.dropna()
    if len(ivq) >= 2:
        prev = ivq.shift(1); nxt = ivq.shift(-1)
        nb = pd.concat([prev, nxt], axis=1).mean(axis=1, skipna=True)
        bad = (ivq - nb).abs() > np.maximum(SMOOTH_ABS, SMOOTH_REL * nb)
        why[bad[bad].index] += "F6_smooth;"
    p["why"] = why
    return p


def pick_contract(pf, target):
    """Nearest-delta put inside tolerance that passes the filter; plus what the
    unfiltered nearest contract was (for drop-rate reporting)."""
    d = pf[np.isfinite(pf.delta)].copy()
    d["dd"] = (d.delta - target).abs()
    d = d[d.dd <= DELTA_TOL].sort_values(["dd", "strike"])
    if d.empty:
        return None, None
    nearest = d.iloc[0]
    ok = d[d.why == ""]
    return (ok.iloc[0] if len(ok) else None), nearest


# ------------------------------------------------------------------ data
def load_prices(tickers, start, end):
    months = pd.period_range(start, end, freq="M")
    parts = [pd.read_parquet(SEP / f"{m}.parquet", columns=["ticker", "date", "close", "closeunadj"],
                             filters=[("ticker", "in", list(tickers))])
             for m in months if (SEP / f"{m}.parquet").exists()]
    s = pd.concat(parts, ignore_index=True)
    s["date"] = pd.to_datetime(s.date)
    return {t: g.sort_values("date").reset_index(drop=True) for t, g in s.groupby("ticker")}


def settle(px, t, settle_day):
    """Real settlement. Returns dict(S_T, r, settle_date, status) or None if no entry row."""
    if px is None:
        return None
    e = px[px.date == t]
    if e.empty:
        return None
    e = e.iloc[0]
    upto = px[(px.date <= settle_day)]
    last = upto.iloc[-1]
    status = "normal" if last.date == settle_day else ("delisted_floor" if px.date.max() < settle_day else "halted_last_print")
    f0 = e.close / e.closeunadj if e.closeunadj > 0 else np.nan
    f1 = last.close / last.closeunadj if last.closeunadj > 0 else np.nan
    r = f1 / f0 if np.isfinite(f0) and np.isfinite(f1) and f0 > 0 else 1.0
    if abs(r - 1) < SPLIT_SNAP:
        r = 1.0
    return {"S_T": float(last.closeunadj), "r": float(r), "settle_date": last.date, "status": status}


def pnl_row(K, bid, S_T, r, y3m, days):
    premium = 100 * bid
    payoff = 100 * max(K - r * S_T, 0.0)
    liq = 100 * r * S_T * LIQ_COST if payoff > 0 else 0.0
    interest = 100 * K * ((1 + y3m) ** (days / 365.0) - 1)
    return {"premium": premium, "payoff": payoff, "liq_cost": liq, "interest": interest,
            "pnl": premium - payoff - liq + interest, "collateral": 100 * K, "assigned": bool(payoff > 0)}


def icw8_scores(entry_dates):
    """icw8 score at t-1 (previous panel date), ranked over v2 cap2000-eligible names.
    Split-half OOS (WO-18 weights, by score-date year parity) before 2020; frozen
    PRODUCTION_WEIGHTS from 2020."""
    rep = json.loads(SEAS_REPORT.read_text())["portfolio"]
    w_fit_odd, w_fit_even = rep["weights8_fit_odd"], rep["weights8_fit_even"]
    fc8 = list(ICW.PRODUCTION_WEIGHTS)
    pdates = pd.to_datetime(pd.read_parquet(PANEL_V2, columns=["date"]).date.unique())
    pdates = pd.DatetimeIndex(sorted(pdates))
    score_date = {}
    for t in entry_dates:
        i = pdates.searchsorted(t) - 1
        if i >= 0:
            score_date[t] = pdates[i]
    sd = sorted(set(score_date.values()))
    p = read_on_dates(PANEL_V2, ["ticker", "date", "eligible_cap2000"] + fc8, sd)
    p["date"] = pd.to_datetime(p.date); p["ticker"] = p.ticker.astype(str)
    p = p[p.eligible_cap2000]
    out, wsrc = {}, {}
    for d, g in p.groupby("date"):
        if d >= HOLDOUT:
            w, src = ICW.PRODUCTION_WEIGHTS, "production_frozen"
        elif d.year % 2 == 1:
            w, src = w_fit_even, "fit_even_scores_odd"
        else:
            w, src = w_fit_odd, "fit_odd_scores_even"
        out[d] = dict(zip(g.ticker, ICW.compute_weighted_score(g.reset_index(drop=True), w, fc8).to_numpy()))
        wsrc[d] = src
    return {t: out.get(score_date.get(t), {}) for t in entry_dates}, {str(t.date()): (str(score_date[t].date()), wsrc.get(score_date[t])) for t in entry_dates if t in score_date}


# ------------------------------------------------------------------ metrics
def summarize(ex):
    """ex: DataFrame [date, excess, days]. Annualized = mean excess x 365.25/mean days."""
    if ex.empty:
        return {"n_cycles": 0}
    ann = lambda s: float(s.excess.mean() * 365.25 / s.days.mean()) if len(s) else np.nan  # noqa: E731
    yrs = ex.date.dt.year
    med = ex.date.sort_values().iloc[len(ex) // 2]
    loyo = {int(y): ann(ex[yrs != y]) for y in sorted(yrs.unique())} if yrs.nunique() > 1 else {}
    return {"n_cycles": int(len(ex)), "excess_ann": ann(ex),
            "odd_years": ann(ex[yrs % 2 == 1]), "even_years": ann(ex[yrs % 2 == 0]),
            "loyo": loyo, "loyo_min": min(loyo.values()) if loyo else np.nan,
            "chrono_first_half_DESCRIPTIVE": ann(ex[ex.date < med]), "chrono_second_half_DESCRIPTIVE": ann(ex[ex.date >= med]),
            "pre2020": ann(ex[ex.date < HOLDOUT]), "from2020_holdout_read_8": ann(ex[ex.date >= HOLDOUT])}


def cycle_excess(pos, spy_tr):
    g = pos.groupby("date").agg(pnl=("pnl", "sum"), coll=("collateral", "sum"), days=("days", "first"), n=("pnl", "size"))
    g["R"] = g.pnl / g.coll
    g["excess"] = g.R - g.index.map(spy_tr)
    return g.reset_index()[["date", "excess", "days", "n", "R"]]


# ------------------------------------------------------------------ main
def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--labels", choices=["noise"], default=None)
    ap.add_argument("--phase2", action="store_true")
    ap.add_argument("--seed", type=int, default=7)
    a = ap.parse_args()
    if a.phase2 == (a.labels is not None):
        raise SystemExit("choose exactly one of --phase2 or --labels noise")
    mode = "real" if a.phase2 else "noise"
    tag = "" if a.phase2 else "_SHUFFLED_TEST_labels-noise"
    t0 = time.time()
    if a.phase2:
        try:
            subprocess.run(["git", "-C", str(REPO), "ls-files", "--error-unmatch", PREREG_DOC], check=True, capture_output=True)
        except subprocess.CalledProcessError:
            raise SystemExit(f"--phase2 refused: {PREREG_DOC} not committed")
        if not ARRIVAL.exists():
            raise SystemExit("--phase2 refused: run check_arrival.py first")
        arr = json.loads(ARRIVAL.read_text())
        if arr.get("overall") != "PASS":
            raise SystemExit("--phase2 refused: arrival_report overall != PASS")
        # Pre-registered bar (doc section 6): every planned monthly date through 2026-08 complete at cap2000.
        seg = arr["monthly_cap2000_completeness"]
        planned_to_aug26 = [d for d in arr["monthly_dates_complete"]]
        incomplete = [x for v in seg.values() for x in v["missing_or_partial"] if x[:10] <= "2026-08-31"]
        if incomplete:
            raise SystemExit(f"--phase2 refused: {len(incomplete)} planned monthly dates <= 2026-08 incomplete at cap2000 "
                             f"(first: {incomplete[:3]}); WO-O1 runs once, on the full store")
        on_disk = sorted(p_.stem.split("=")[1] for p_ in CHAIN.glob("date=*.parquet"))
        want = sorted(d for d in planned_to_aug26 if d <= "2026-08-31")
        if [d for d in on_disk if d <= "2026-08-31"] != want:
            raise SystemExit("--phase2 refused: chain partitions != arrival report's complete dates; re-run gate_a.py")
        if (OUT / "wo_o1_results.json").exists():
            raise SystemExit("--phase2 refused: wo_o1_results.json exists; a re-run is an iteration (cap 3) and must be "
                             "written into the doc and committed first, then the old file moved aside by hand")

    entry = sorted(pd.Timestamp(p.stem.split("=")[1]) for p in CHAIN.glob("date=*.parquet"))
    log(f"{mode} mode: {len(entry)} entry dates {entry[0].date()}..{entry[-1].date()}")
    u = read_on_dates(UNIVERSE_V2, ["date", "ticker", "eligible_cap2000"], entry)
    u["date"] = pd.to_datetime(u.date)
    elig = u[u.eligible_cap2000].groupby("date").ticker.apply(set).to_dict()
    feats = pd.read_parquet(FEATS, columns=["date", "ticker", "opt_atm_iv"])
    feats["date"] = pd.to_datetime(feats.date)
    atm = {(d, t): v for d, t, v in feats.itertuples(index=False)}
    spy = pd.read_csv(SPY_CSV, usecols=["date", "close"], parse_dates=["date"]).set_index("date").close.sort_index()
    rates = pd.read_csv(RATES, usecols=["date", "y3m"], parse_dates=["date"]).set_index("date").y3m.sort_index() / 100
    scores, score_meta = icw8_scores(entry)
    rng = np.random.default_rng(a.seed)

    rows, filt = [], []
    for t in entry:
        ch = pd.read_parquet(CHAIN / f"date={t.date()}.parquet")
        # Amendment 1: is bid_size systematically populated for this name on t (all types/expiries)?
        cb = ch[ch.bid > 0]
        sizes_pop = ((cb.bid_size.fillna(0) > 0).groupby(cb.sharadar_ticker).mean() >= SIZE_POPULATED).to_dict()
        ch = ch[(ch.call_put == "Put") & ch.sharadar_ticker.isin(elig.get(t, set()))]
        exp = target_expiry(t)
        ch["expiration"] = pd.to_datetime(ch.expiration)
        ch = ch[(ch.expiration == exp) | (ch.expiration == exp + pd.Timedelta(days=1))]
        settle_day = spy.index[spy.index <= exp.normalize() + pd.Timedelta(days=1)].max()
        days = (settle_day - t).days
        y3m = float(rates[rates.index <= t].iloc[-1])
        if mode == "real":
            spy_tr = spy[settle_day] / spy[t] - 1 + SPY_DIV_YIELD * days / 365.25
        else:   # noise: benchmark = T-bill carry, so E[excess] ~ -(half spread)/K; no real market path
            spy_tr = (1 + y3m) ** (days / 365.0) - 1
        names = sorted(ch.sharadar_ticker.unique())
        px = load_prices(names, t, settle_day) if mode == "real" else load_prices(
            [n for n, d in NAMED if pd.Timestamp(d) == t and n in names] or ["__none__"], t, settle_day)
        for tk, g in ch.groupby("sharadar_ticker"):
            spot = float(g.spot.iloc[0])
            pf = filter_puts(g, spot, sizes_populated=bool(sizes_pop.get(tk, False)))
            for tgt in DELTAS:
                c, nearest = pick_contract(pf, tgt)
                if nearest is None:
                    continue
                filt.append({"date": t, "ticker": tk, "bucket": tgt, "nearest_why": nearest.why,
                             "traded": c is not None, "atm_iv": atm.get((t, tk), np.nan)})
                if c is None:
                    continue
                K, bid = float(c.strike), float(c.bid)
                real = settle(px.get(tk), t, settle_day) if (mode == "real" or (tk, str(t.date())) in NAMED) else None
                if mode == "real":
                    if real is None:
                        continue
                    S_T, r, st = real["S_T"], real["r"], real["status"]
                else:
                    T = max(days, 1) / 365.0
                    sig = float(c.vol)
                    S_T = spot * math.exp((math.log1p(y3m)) * T - 0.5 * sig * sig * T + sig * math.sqrt(T) * rng.standard_normal())
                    r, st = 1.0, "noise"
                rec = {"date": t, "ticker": tk, "bucket": tgt, "y3m": y3m, "strike": K, "bid": bid, "ask": float(c.ask),
                       "delta": float(c.delta), "iv": float(c.vol), "spot": spot, "S_T": S_T, "r": r,
                       "settle_status": st, "days": days, "spy_tr": spy_tr,
                       "half_spread_over_K": (float(c.ask) - bid) / 2 / K,
                       "score": scores.get(t, {}).get(tk, np.nan), **pnl_row(K, bid, S_T, r, y3m, days)}
                if real is not None and (tk, str(t.date())) in NAMED:
                    rec["named_real"] = {**real, **pnl_row(K, bid, real["S_T"], real["r"], y3m, days)}
                rows.append(rec)
        log(f"  {t.date()} -> exp {exp.date()} settle {settle_day.date()}: {len(names)} names with puts")
    P = pd.DataFrame(rows)
    FL = pd.DataFrame(filt)
    spy_by_date = P.groupby("date").spy_tr.first()

    # ---------------- named survivorship check (real settlement, those contracts only)
    named = {}
    ok_named = True
    for tk, ds in NAMED:
        d = pd.Timestamp(ds)
        if d not in entry:
            named[f"{tk}@{ds}"] = {"status": "entry date not on disk"}
            if ds == "2008-08-20":
                ok_named = False
            continue
        sub = P[(P.ticker == tk) & (P.date == d)]
        if sub.empty:
            in_elig = tk in elig.get(d, set())
            ch = pd.read_parquet(CHAIN / f"date={d.date()}.parquet", columns=["sharadar_ticker"])
            has_chain = bool((ch.sharadar_ticker == tk).any())
            if in_elig and has_chain:
                named[f"{tk}@{ds}"] = {"status": "MISSING from arm (a) pool although cap2000-eligible with a chain -> FAIL",
                                       "quote_filter_rows": FL[(FL.ticker == tk) & (FL.date == d)].to_dict("records")}
                ok_named = False
            else:
                named[f"{tk}@{ds}"] = {"status": "not in pool: " + ("not cap2000-eligible on t (mcap>=$2B AND closeunadj>$10 rule)"
                                                                   if not in_elig else "no verified chain on t"),
                                       "cap2000_eligible": in_elig, "has_chain": has_chain}
            continue
        per = {}
        for r_ in sub.itertuples():
            nr = r_.named_real
            # net loss (payoff - premium) as a share of the maximum loss (100K - premium)
            loss_share = (nr["payoff"] - nr["premium"]) / (100 * r_.strike - nr["premium"]) if (100 * r_.strike - nr["premium"]) > 0 else np.nan
            per[str(r_.bucket)] = {"strike": r_.strike, "bid": r_.bid, "S_T": nr["S_T"], "r": nr["r"],
                                   "settle_date": str(pd.Timestamp(nr["settle_date"]).date()), "settle_status": nr["status"],
                                   "payoff": nr["payoff"], "premium": nr["premium"],
                                   "net_loss_over_max_loss": loss_share,
                                   "payoff_formula_ok": bool(abs(nr["payoff"] - 100 * max(r_.strike - nr["r"] * nr["S_T"], 0)) < 1e-9)}
        named[f"{tk}@{ds}"] = per
    leh = named.get("LEHMQ@2008-08-20", {})
    if not (isinstance(leh, dict) and leh and "status" not in leh):
        ok_named = False   # LEH is cap2000-eligible with a chain on 2008-08-20 (Gate A2): must be in the pool
    if isinstance(leh, dict) and leh and "status" not in leh:
        leh_ok = all(v["net_loss_over_max_loss"] >= 0.90 for v in leh.values())
        named["LEH_near_total_loss_all_buckets"] = leh_ok
        ok_named &= leh_ok
    if not ok_named:
        log("NAMED SURVIVORSHIP CHECK FAILED: " + json.dumps(named, default=str)[:1500])

    # ---------------- filter drop report (no outcomes)
    FL["atm_q"] = FL.groupby("date").atm_iv.transform(lambda s: pd.qcut(s.rank(method="first"), 5, labels=False) if s.notna().sum() >= 5 else np.nan)
    drop = {"nearest_fail_share": float((FL.nearest_why != "").mean()),
            "no_trade_share": float((~FL.traded).mean()),
            "nearest_fail_reasons": FL.loc[FL.nearest_why != "", "nearest_why"].str.split(";").explode().replace("", np.nan).dropna().value_counts().to_dict(),
            "no_trade_share_by_atm_iv_quintile": {int(k): float(v) for k, v in FL.groupby("atm_q").traded.apply(lambda s: (~s).mean()).items()}}

    # ---------------- arms, null, metrics
    cells = {}
    for tgt in DELTAS:
        B = P[P.bucket == tgt]
        a_ex = cycle_excess(B, spy_by_date)
        sc = B[np.isfinite(B.score)]
        def top(df, col):
            k = df.groupby("date")[col].transform(lambda s: max(1, int(round(QUINTILE * len(s)))))
            rk = df.groupby("date")[col].rank(ascending=False, method="first")
            return df[rk <= k]
        b = top(sc, "score")
        b_ex = cycle_excess(b, spy_by_date)
        nulls = []
        for s in range(NULL_DRAWS):
            rg = np.random.default_rng(s)
            sh = sc.copy()
            sh["score_null"] = sh.groupby("date").score.transform(lambda x: rg.permutation(x.to_numpy()))
            nulls.append(summarize(cycle_excess(top(sh, "score_null"), spy_by_date))["excess_ann"])
        ra, rb = summarize(a_ex), summarize(b_ex)
        p80 = float(np.quantile(nulls, NULL_PCTILE))
        cell = {"arm_a": ra, "arm_b_icw8": rb, "null_p80": p80, "null_median": float(np.median(nulls)),
                "null_draws": nulls, "filter_minus_a": rb.get("excess_ann", np.nan) - ra.get("excess_ann", np.nan),
                "null_p80_minus_a": p80 - ra.get("excess_ann", np.nan),
                "positions_a": int(len(B)), "positions_b": int(len(b)),
                "assigned_share_a": float(B.assigned.mean()) if len(B) else np.nan,
                "settle_status_a": B.settle_status.value_counts().to_dict(),
                "mean_half_spread_over_K_a": float(B.half_spread_over_K.mean()) if len(B) else np.nan}
        if mode == "noise":
            # Unit test of the P&L/settlement arithmetic. Noise S_T is lognormal at the contract's own IV with
            # drift log1p(y3m), so E[payoff] = forward BS put value at settle-T (analytic); the predicted cycle
            # excess is sum(premium - E[payoff] + interest)/sum(collateral) - carry. Realized minus predicted
            # must be pure sampling noise (report z). The rough -half-spread/K is kept for reference.
            Tn = B.days / 365.0
            rr = np.log1p(B.y3m)
            epay = 100 * np.exp(rr * Tn) * bs_price(B.spot.to_numpy(), B.strike.to_numpy(), Tn.to_numpy(), rr.to_numpy(),
                                                    B.iv.to_numpy(), np.zeros(len(B), bool))
            prd = (B.premium - epay + B.interest).groupby(B.date).sum() / B.collateral.groupby(B.date).sum() - spy_by_date
            dif = a_ex.set_index("date").excess - prd
            w = B.collateral / B.groupby("date").collateral.transform("sum")
            cell["noise_unit_test"] = {"mean_cycle_excess": float(a_ex.excess.mean()),
                                       "predicted_analytic": float(prd.mean()),
                                       "z_realized_minus_predicted": float(dif.mean() / (dif.std(ddof=1) / np.sqrt(len(dif)))),
                                       "rough_minus_half_spread": float(-(w * B.half_spread_over_K).groupby(B.date).sum().mean())}
        cells[str(tgt)] = cell
    pc = cells[str(PRIMARY_DELTA)]
    verdict = None
    if mode == "real":
        b_, a_ = pc["arm_b_icw8"], pc["arm_a"]
        success = (b_["odd_years"] > 0 and b_["even_years"] > 0 and b_["loyo_min"] > 0 and b_["excess_ann"] > pc["null_p80"])
        kill = ((a_["excess_ann"] <= 0 and b_["excess_ann"] <= 0) or b_["excess_ann"] <= pc["null_p80"])
        verdict = "PASS" if success else ("KILL" if kill else "MIDDLE")
    out = {"label_mode": mode, "entry_dates": [str(d.date()) for d in entry], "score_dates_and_weights": score_meta,
           "named_survivorship_check": named, "named_check_pass": bool(ok_named),
           "quote_filter": drop, "cells": cells, "primary_cell": str(PRIMARY_DELTA),
           "blend_arm": {"status": "BLOCKED", "reason": "q75 cache (2026-09-10) predates the committed purge code (e94cfe0, 2026-09-18); "
                         "~60-day score cadence; see doc section 4.1"},
           "verdict": verdict, "holdout_read": "#8 (entries >= 2020)" if mode == "real" and any(d >= HOLDOUT for d in entry) else "none",
           "runtime_s": time.time() - t0}
    OUT.mkdir(parents=True, exist_ok=True)
    path = OUT / f"wo_o1_results{tag}.json"
    path.write_text(json.dumps(out, indent=2, default=str))
    P.drop(columns=["named_real"], errors="ignore").to_parquet(OUT / f"wo_o1_positions{tag}.parquet", index=False)
    log(f"named check {'PASS' if ok_named else 'FAIL'}; wrote {path}")
    if not ok_named:
        sys.exit(2)


if __name__ == "__main__":
    main()
