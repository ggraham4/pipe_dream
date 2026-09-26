"""
WO-10: a FORWARD record of the IWM-hedged icw8 composite, on the working
(v2) panel from its first record. Forward test, not an in-era trial.
Pre-registration (committed before the first record):
    final/models/2026-09-25-forward-hedged-icw8.md

The bet (registered tier cap150; cap2000 recorded as DESCRIPTIVE, no kill):
    long  the icw8 decile_volq book (noscore_control_v2.build_books'
          construction: ICW.compute_composite_ic_weighted ->
          C.pick_decile_volq) on the working panel with the v2 universe rule
    short IWM at equal notional (weight -1.0)

Per recorded panel date t (entry open[t+1], exit close[t+40]):
    hedged = net_book_price + book_div - iwm_price - iwm_div - SHORT_COST
    net_book_price = (1+g)(1-h)/(1+h) - 1, h = 15bp/2, i.e.
                     run_backtest.turnover_net_return with f_new = 1 (a
                     standalone record has no prior book: full entry + exit)
    g        = sum_i w_i * close_i[x]/open_i[e] - 1          (price only)
    book_div = sum_i w_i * close_i[x]/open_i[e] * (f_i[x]/f_i[e] - 1),
               f = closeadj/close from the Sharadar SEP panel
    IWM the same with f = Adj Close / Close; SHORT_COST = 10bp.
    e = t+1, x = t+40 on each name's own bars; a name whose series ends
    before x exits at its last close (execution.py's delisting exit floor);
    a name with no bar after t was never opened and its weight is
    renormalised over the rest (noscore_control_v2.realise's rule).

Commands
    record    record_hedge(): the working panel's latest date, blind
    score     score_hedge(): refuses any date whose exit bar has not happened
    selftest  construction + scoring self-tests on a pre-2020 date
    status    counted dates / kill-rule state from the scores CSV

Nothing here pulls a price. score_hedge reads IWM from IWM_LIVE_CSV, which
does not exist until someone pulls it after a record date has matured.
"""
import hashlib
import json
import sys
import time
from pathlib import Path

import numpy as np
import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parent))
import composite as C                      # noqa: E402
import ic_weighted_composite as ICW        # noqa: E402
import run_backtest as RB                  # noqa: E402
import working_panel as W                  # noqa: E402

R26 = W.R26
SEP_DIR = W.SH / "panel" / "stocks"
IWM_CSV = W.MAIN_ROOT / "data" / "benchmarks" / "IWM.csv"          # to 2019-12-31 (WO-9)
IWM_LIVE_CSV = W.MAIN_ROOT / "data" / "benchmarks" / "IWM_live.csv"  # pulled only after maturity

HEDGE_CSV = R26 / "prediction_ledger_hedge.csv"
HEDGE_SCORES_CSV = R26 / "prediction_ledger_hedge_scores.csv"
HEDGE_VERSION = "hedge1_icw8_dvolq_minus_iwm_v2panel_2026-09-25"
FIRST_DATE = pd.Timestamp("2026-09-08")
H = RB.HORIZON                         # 40
BOOK_COST_BPS = 15.0                   # run_backtest.turnover_net_return, f_new = 1
SHORT_COST = 0.0010                    # 10bp per record, short leg
TIERS = {"cap150": "REGISTERED", "cap2000": "DESCRIPTIVE"}
MIN_MATURED = 6
LABEL = "forward_return_tradable_40"
HEDGE_COLS = ["panel_date", "recorded_at", "hedge_version", "panel_source", "tier", "role", "leg",
              "ticker", "icw8_score", "vol_bucket", "volatility_60", "market_cap", "weight"]
PANEL_COLS = ["sector", "close", "market_cap", "volatility_60", LABEL] + C.FACTOR_COLS


def log(m):
    print(f"[{time.strftime('%H:%M:%S')}] {m}", flush=True)


# ------------------------------------------------------------------ book
def book_one_date(elig):
    """icw8 decile_volq book for ONE eligible cross-section (universe rule
    already applied). Returns a frame with the bucket and score; tickers and
    weights are asserted identical to C.pick_decile_volq."""
    elig = elig.reset_index(drop=True)
    sc = ICW.compute_composite_ic_weighted(elig)
    picks = C.pick_decile_volq(elig, sc)
    vol = elig["volatility_60"].to_numpy(np.float64)
    comp = sc["composite"].to_numpy(np.float64)
    valid = np.isfinite(vol) & np.isfinite(comp)
    idx = np.flatnonzero(valid)
    q = pd.qcut(vol[idx], C.N_VOL_QUINTILES, labels=False, duplicates="drop")
    bucket = dict(zip(elig["ticker"].to_numpy()[idx], q))
    book = pd.DataFrame(picks, columns=["ticker", "weight"])
    look = elig.set_index("ticker")
    book["icw8_score"] = book["ticker"].map(dict(zip(sc["ticker"], sc["composite"])))
    book["vol_bucket"] = book["ticker"].map(bucket).astype(int)
    book["volatility_60"] = book["ticker"].map(look["volatility_60"])
    book["market_cap"] = (book["ticker"].map(look["market_cap"]) if "market_cap" in look.columns
                          else np.nan)          # load_column("c") carries no market_cap
    ref = C.pick_decile_volq(elig, sc)
    assert [t for t, _ in ref] == book["ticker"].tolist()
    assert np.max(np.abs(np.array([w for _, w in ref]) - book["weight"].to_numpy())) < 1e-12
    info = {"n_eligible": int(len(elig)), "n_valid": int(valid.sum()), "n_book": int(len(book)),
            "n_per_bucket": {int(b): int((q == b).sum()) for b in np.unique(q)},
            "book_per_bucket": {int(b): int((book["vol_bucket"] == b).sum()) for b in np.unique(q)}}
    return book, info


def nan_vol_guard(book, info, tier):
    """The KARD trap: no NaN/inf vol or score, weights sum to 1, book ~10% of valid."""
    v = book["volatility_60"].to_numpy(np.float64)
    s = book["icw8_score"].to_numpy(np.float64)
    checks = {
        "no_nonfinite_vol": bool(np.isfinite(v).all()),
        "no_nonfinite_score": bool(np.isfinite(s).all()),
        "vol_positive": bool((v > 0).all()),
        "weights_sum_1": bool(abs(book["weight"].sum() - 1.0) < 1e-12),
        "book_frac_of_valid": info["n_book"] / info["n_valid"],
        "book_frac_ok": bool(abs(info["n_book"] / info["n_valid"] - 0.10) < 0.01),
    }
    bad = [k for k, ok in checks.items() if k != "book_frac_of_valid" and not ok]
    if bad:
        raise SystemExit(f"NaN-vol/book guard FAILED for {tier}: {bad} {checks}")
    return checks


# ------------------------------------------------------------------ record
def _recorded_dates():
    if not HEDGE_CSV.exists():
        return set()
    return set(pd.read_csv(HEDGE_CSV, usecols=["panel_date"])["panel_date"].astype(str))


def build_record_rows(date=None):
    cross, uinfo = W.working_cross_section(PANEL_COLS + [f"eligible_{t}" for t in TIERS], date=date)
    pdate = cross["date"].max()
    rows, report = [], {"panel_date": pdate.date().isoformat(), "universe": uinfo, "tiers": {}}
    for tier, role in TIERS.items():
        elig = cross[cross[f"eligible_{tier}"]].reset_index(drop=True)
        n_mat = int(elig[LABEL].notna().sum())
        if n_mat:
            raise SystemExit(f"REFUSING: {n_mat} {tier} names on {pdate.date()} have a realised "
                             f"{LABEL} -- this date is not blind.")
        book, info = book_one_date(elig)
        checks = nan_vol_guard(book, info, tier)
        report["tiers"][tier] = {**info, "guards": checks, "role": role}
        b = book.assign(panel_date=pdate.date().isoformat(), tier=tier, role=role, leg="long")
        s = pd.DataFrame([{"panel_date": pdate.date().isoformat(), "tier": tier, "role": role, "leg": "short",
                           "ticker": "IWM", "icw8_score": np.nan, "vol_bucket": np.nan,
                           "volatility_60": np.nan, "market_cap": np.nan, "weight": -1.0}])
        rows += [b, s]
    out = pd.concat(rows, ignore_index=True)
    out["recorded_at"] = pd.Timestamp.now().isoformat()
    out["hedge_version"] = HEDGE_VERSION
    out["panel_source"] = W.WORKING_PANEL_SOURCE
    return out[HEDGE_COLS], pdate, report


def record_hedge(date=None):
    """date=None: latest working-panel date. date=YYYY-MM-DD: that date
    (WO-14 weekly catch-up via record_weekly.py); same guards either way."""
    out, pdate, report = build_record_rows(date)
    iso = pdate.date().isoformat()
    if iso in _recorded_dates():
        raise SystemExit(f"REFUSING: {HEDGE_CSV.name} already has panel_date {iso} (duplicate-date guard)")
    if pdate < FIRST_DATE:
        raise SystemExit(f"REFUSING: {iso} is before the registered first date {FIRST_DATE.date()}")
    write_header = not HEDGE_CSV.exists()
    out.to_csv(HEDGE_CSV, mode="a", header=write_header, index=False)
    W.record_manifest(HEDGE_CSV, pdate, W.WORKING_PANEL)
    log(f"appended {len(out)} rows to {HEDGE_CSV} for {iso}")
    return out, report


# ------------------------------------------------------------------ prices
def load_sep(tickers, start, end):
    """Sharadar SEP monthly files between start and end (inclusive months).
    Returns {ticker: dict(date, open, close, f)} and the max date read."""
    lo, hi = pd.Timestamp(start).strftime("%Y-%m"), pd.Timestamp(end).strftime("%Y-%m")
    files = sorted(f for f in SEP_DIR.glob("*.parquet") if lo <= f.stem <= hi)
    parts = [pd.read_parquet(f, columns=["ticker", "date", "open", "close", "closeadj"],
                             filters=[("ticker", "in", sorted(tickers))]) for f in files]
    allmax = max(pd.read_parquet(files[-1], columns=["date"])["date"].pipe(pd.to_datetime).max(),
                 pd.Timestamp("1900-01-01")) if files else pd.NaT
    px = pd.concat(parts, ignore_index=True)
    px["date"] = pd.to_datetime(px["date"])
    px = px[px["date"] <= pd.Timestamp(end)]
    px = px.drop_duplicates(["ticker", "date"]).sort_values(["ticker", "date"])
    out = {}
    for t, g in px.groupby("ticker", sort=False):
        out[t] = {"date": g["date"].to_numpy(), "open": g["open"].to_numpy(np.float64),
                  "close": g["close"].to_numpy(np.float64),
                  "f": (g["closeadj"] / g["close"]).to_numpy(np.float64)}
    return out, min(allmax, pd.Timestamp(end))


def load_iwm(path):
    d = pd.read_csv(path, parse_dates=["date"])
    return d.sort_values("date").reset_index(drop=True)


def iwm_leg(iwm, t):
    """(price 40d, total 40d, exit date) on HC.ret40's basis, or None if the
    exit bar i+40 does not exist yet (still blind)."""
    d = pd.DatetimeIndex(iwm["date"])
    i = d.get_indexer([pd.Timestamp(t)])[0]
    if i < 0:
        raise SystemExit(f"IWM has no bar on {pd.Timestamp(t).date()}")
    if i + H > len(d) - 1:
        return None
    o, c = iwm["open"].to_numpy(np.float64), iwm["close"].to_numpy(np.float64)
    f = iwm["adj_close"].to_numpy(np.float64) / c
    pr = c[i + H] / o[i + 1] - 1.0
    tr = c[i + H] * f[i + H] / (o[i + 1] * f[i + 1]) - 1.0
    return pr, tr, d[i + H]


def hedged_return(t, book, px, px_max, iwm):
    """book: frame(ticker, weight) of one tier's long leg. Returns a dict or
    None when not matured (IWM exit bar missing, or the stock panel does not
    yet reach IWM's exit date)."""
    leg = iwm_leg(iwm, t)
    if leg is None:
        return None
    iwm_p, iwm_t, exit_date = leg
    if px_max < exit_date:
        return None
    t64 = np.datetime64(pd.Timestamp(t))
    kept, stats = [], {"n_names": int(len(book)), "missing": 0, "never_opened": 0, "delist_floor": 0}
    for tk, w in zip(book["ticker"], book["weight"]):
        s = px.get(tk)
        if s is None:
            stats["missing"] += 1
            continue
        i = int(np.searchsorted(s["date"], t64))
        if i >= len(s["date"]) or s["date"][i] != t64:
            stats["missing"] += 1
            continue
        n = len(s["date"])
        e, x = i + 1, i + H
        if e > n - 1:
            stats["never_opened"] += 1
            continue
        if x > n - 1:
            x = n - 1                    # delisting exit floor (execution.py)
            stats["delist_floor"] += 1
        pr = s["close"][x] / s["open"][e]
        kept.append((w, pr, pr * (s["f"][x] / s["f"][e] - 1.0)))
    if stats["missing"]:
        raise SystemExit(f"{stats['missing']} book names absent from the SEP panel on {pd.Timestamp(t).date()}")
    wv = np.array([k[0] for k in kept])
    wv = wv / wv.sum()
    g = float((wv * np.array([k[1] for k in kept])).sum() - 1.0)
    bdiv = float((wv * np.array([k[2] for k in kept])).sum())
    net = float(RB.turnover_net_return([{"gross": g, "f_new": 1.0}], BOOK_COST_BPS)[0])
    hedged = net + bdiv - iwm_p - (iwm_t - iwm_p) - SHORT_COST
    return {"book_gross_price": g, "book_net_price": net, "book_div": bdiv, "iwm_price": iwm_p,
            "iwm_div": iwm_t - iwm_p, "short_cost": SHORT_COST, "hedged": hedged,
            "exit_date": exit_date.date().isoformat(), **stats}


# ------------------------------------------------------------------ score
def _approx_exit(t):
    """A calendar pre-check that never reads a price: 40 NYSE days is at
    least 56 calendar days. Dates before that are refused outright."""
    return pd.Timestamp(t) + pd.Timedelta(days=56)


def score_hedge(today=None):
    today = pd.Timestamp.now().normalize() if today is None else pd.Timestamp(today)
    if not HEDGE_CSV.exists():
        log("no hedge ledger yet")
        return []
    led = pd.read_csv(HEDGE_CSV)
    done = set()
    if HEDGE_SCORES_CSV.exists():
        sc = pd.read_csv(HEDGE_SCORES_CSV, usecols=["panel_date", "tier"])
        done = set(zip(sc["panel_date"].astype(str), sc["tier"]))
    results = []
    for (pdate, tier), rows in led.groupby([led["panel_date"].astype(str), "tier"]):
        if (pdate, tier) in done:
            continue
        if today < _approx_exit(pdate):
            log(f"hedge {pdate} {tier}: still blind (exit ~{_approx_exit(pdate).date()} not reached; nothing read)")
            continue
        if not IWM_LIVE_CSV.exists():
            log(f"hedge {pdate} {tier}: still blind ({IWM_LIVE_CSV.name} not pulled yet)")
            continue
        iwm = load_iwm(IWM_LIVE_CSV)
        if iwm_leg(iwm, pdate) is None:
            log(f"hedge {pdate} {tier}: still blind (IWM exit bar not in {IWM_LIVE_CSV.name})")
            continue
        long = rows[rows["leg"] == "long"]
        assert (rows.loc[rows["leg"] == "short", "weight"] == -1.0).all()
        exit_d = iwm_leg(iwm, pdate)[2]
        px, px_max = load_sep(set(long["ticker"]), pdate, exit_d + pd.Timedelta(days=10))
        r = hedged_return(pdate, long, px, px_max, iwm)
        if r is None:
            log(f"hedge {pdate} {tier}: still blind (SEP panel ends {px_max.date()} < exit {exit_d.date()})")
            continue
        r.update({"panel_date": pdate, "tier": tier, "role": rows["role"].iloc[0],
                  "hedge_version": rows["hedge_version"].iloc[0], "scored_at": pd.Timestamp.now().isoformat()})
        results.append(r)
        log(f"hedge {pdate} {tier}: hedged {r['hedged']:+.4f}")
    if results:
        pd.DataFrame(results).to_csv(HEDGE_SCORES_CSV, mode="a", header=not HEDGE_SCORES_CSV.exists(), index=False)
        status()
    return results


def counted_dates(recorded, calendar):
    """Registered subset rule: greedy from FIRST_DATE; each next counted date
    is the earliest recorded panel date >= 40 trading days (on `calendar`)
    after the previous counted one."""
    cal = pd.DatetimeIndex(sorted(calendar))
    rec = sorted(pd.Timestamp(d) for d in recorded if pd.Timestamp(d) >= FIRST_DATE)
    out, prev = [], None
    for d in rec:
        if prev is None:
            if d == FIRST_DATE:
                out.append(d)
                prev = d
            continue
        n = int(((cal > prev) & (cal <= d)).sum())
        if n >= H:
            out.append(d)
            prev = d
    return out


def status():
    if not HEDGE_SCORES_CSV.exists():
        log("status: no matured dates yet -- no verdict possible")
        return {"n_matured_counted": 0, "state": "NO DATA"}
    sc = pd.read_csv(HEDGE_SCORES_CSV)
    sc = sc[sc["tier"] == "cap150"]
    iwm = load_iwm(IWM_LIVE_CSV)
    # WO-14 addendum (Gabe, 2026-09-25, weekly cadence): records flagged
    # recorded_late in ledger_record_log.csv are descriptive only and can
    # never be counted dates. The greedy rule itself is unchanged.
    late = set()
    rec_log = R26 / "ledger_record_log.csv"
    if rec_log.exists():
        lg = pd.read_csv(rec_log)
        lg = lg[(lg["ledger"] == HEDGE_CSV.name) & lg["recorded_late"].astype(bool)]
        late = set(lg["panel_date"].astype(str))
    # COO 2026-09-25: rows annotated incomplete_week (ledger_record_annotations.csv)
    # are descriptive only too.
    ann = R26 / "ledger_record_annotations.csv"
    if ann.exists():
        an = pd.read_csv(ann)
        an = an[(an["ledger"] == HEDGE_CSV.name) & an["annotation"].astype(str).str.startswith("incomplete_week")]
        late |= set(an["panel_date"].astype(str))
    cd = {d.date().isoformat() for d in counted_dates(_recorded_dates() - late, iwm["date"])}
    m = sc[sc["panel_date"].astype(str).isin(cd)]
    n, mean = len(m), float(m["hedged"].mean()) if len(m) else float("nan")
    state = ("INSUFFICIENT (<6 matured counted dates)" if n < MIN_MATURED else
             "KILL" if mean <= 0 else "PASS -> PROMOTE-CANDIDATE question to Gabe")
    log(f"status cap150: {n} matured counted dates, mean hedged {mean:+.4f} -> {state}")
    return {"n_matured_counted": n, "mean_hedged": mean, "state": state}


# ------------------------------------------------------------------ selftest
def selftest(test_date="2015-06-15"):
    """Pre-2020 only. (1) construction: book_one_date == build_books on
    load_column('c') cap150, and working_cross_section + the universe rule
    reproduces column c's cross-section. (2) scoring: hedged_return ==
    the WO-9 per-date tradable hedged value at f_new = 1."""
    import downcap_v2_readout as R
    import noscore_control_v2 as NX
    import hedged_composite as HC
    import hedged_tradable as HT
    t = pd.Timestamp(test_date)
    assert t < pd.Timestamp("2019-11-04"), "self-test date must exit before the IWM end-of-era mask"
    res = {"test_date": t.date().isoformat(), "checks": {}}

    def check(name, ok, detail=""):
        res["checks"][name] = {"pass": bool(ok), "detail": detail}
        log(f"  [{'PASS' if ok else 'FAIL'}] {name} {detail}")

    p, _spy = R.load_column("c")
    g = p[p["date"] == t].reset_index(drop=True)
    del p
    books, drops = NX.build_books(g, ["cap150"], with_null=False)
    ref = books["cap150"]["icw8"][t]
    dr = drops["cap150"]["icw8"]
    check("build_books drops == 0 on test date", dr["n_dropped"] == 0, f"({dr['n_dropped']} dropped)")
    elig_c = g[g["eligible_cap150"]].reset_index(drop=True)
    mine, info = book_one_date(elig_c)
    same_t = list(mine["ticker"]) == list(ref[2])
    wdiff = float(np.max(np.abs(mine["weight"].to_numpy() - ref[3])))
    check("construction: book_one_date == build_books (tickers)", same_t, f"({len(mine)} names)")
    check("construction: book_one_date == build_books (weights 1e-12)", wdiff < 1e-12, f"(max |dw| {wdiff:.1e})")
    cross, _u = W.working_cross_section(PANEL_COLS + ["eligible_cap150"], date=t)
    elig_w = cross[cross["eligible_cap150"]].reset_index(drop=True)
    check("working_cross_section cap150 set == load_column('c') cap150 set",
          set(elig_w["ticker"]) == set(elig_c["ticker"]), f"({len(elig_w)} vs {len(elig_c)})")
    mine_w, _ = book_one_date(elig_w)
    check("working loader book == build_books book",
          list(mine_w["ticker"]) == list(ref[2]) and np.max(np.abs(mine_w["weight"].to_numpy() - ref[3])) < 1e-12)
    nan_vol_guard(mine, info, "cap150")
    check("NaN-vol guard passes on test book", True, f"(book {info['n_book']} / valid {info['n_valid']})")

    # scoring: WO-9 reference at f_new = 1
    iwm = HC.load_iwm()
    iwm_p = float(HC.ret40(iwm)[t])
    iwm_t = float(HC.ret40(iwm, total_return=True)[t])
    pxr = HT.load_panel(set(ref[2]))
    bdiv_ref = 0.0
    for tk, wi in zip(ref[2], ref[3]):
        s = pxr[tk]
        i = int(np.searchsorted(s["date"], np.datetime64(t)))
        e, x = i + 1, min(i + HC.H, len(s["date"]) - 1)
        pr = s["close"][x] / s["open"][e]
        bdiv_ref += wi * pr * (s["f"][x] / s["f"][e] - 1.0)
    net_ref = float(RB.turnover_net_return([{"gross": ref[0], "f_new": 1.0}], R.COST_BPS)[0])
    hedged_ref = net_ref - (iwm_p + HC.SHORT_BPS / 1e4 - (bdiv_ref - (iwm_t - iwm_p)))
    px, px_max = load_sep(set(ref[2]), t, pd.Timestamp("2019-12-31"))
    got = hedged_return(t, pd.DataFrame({"ticker": ref[2], "weight": ref[3]}), px, px_max, load_iwm(IWM_CSV))
    check("scoring: book gross == outcome_cache_v2 basis (1e-6)", abs(got["book_gross_price"] - ref[0]) < 1e-6,
          f"({got['book_gross_price']:+.8f} vs {ref[0]:+.8f})")
    check("scoring: hedged == WO-9 tradable per-date value at f_new=1 (1e-6)", abs(got["hedged"] - hedged_ref) < 1e-6,
          f"({got['hedged']:+.8f} vs {hedged_ref:+.8f})")
    res["scoring"] = {"mine": got, "ref": {"net": net_ref, "bdiv": bdiv_ref, "iwm_price": iwm_p,
                                           "iwm_div": iwm_t - iwm_p, "hedged": hedged_ref}}

    # blindness of score_hedge on an unmatured date (no price read)
    check("score_hedge calendar guard refuses 2026-09-08 today",
          pd.Timestamp.now().normalize() < _approx_exit(FIRST_DATE))
    ok = all(v["pass"] for v in res["checks"].values())
    res["all_pass"] = ok
    log(f"=== hedge selftest {'PASSED' if ok else 'FAILED'} ===")
    return res


if __name__ == "__main__":
    cmd = sys.argv[1] if len(sys.argv) > 1 else "status"
    if cmd == "record":
        out, report = record_hedge()
        print(json.dumps(report, indent=2, default=str))
    elif cmd == "score":
        score_hedge()
    elif cmd == "selftest":
        r = selftest(*(sys.argv[2:3]))
        print(json.dumps(r, indent=2, default=str))
        sys.exit(0 if r["all_pass"] else 1)
    else:
        status()
