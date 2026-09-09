"""
Round 10 (2026-09-08): can any point-in-time screen build a universe that
beats SPY equal-weighted?

Why this is the highest-leverage question left
----------------------------------------------
The null test decomposed the strategy's shortfall into three independent,
separately-measurable pieces:

    universe      eligible pool, equal-weighted   $41,010  Sharpe 0.49
                  SPY, same windows               $48,077  Sharpe 0.59
                  -> the pool itself is a ~15% headwind before anything else

    concentration random 5 names, median          $33,447  Sharpe 0.40
                  random 50 names, median         $38,191  Sharpe 0.47
                  -> holding 5 costs ~12% of the median outcome, no mean gain

    selection     model vs 10,000 random draws    p76.5 terminal / p55.1 Sharpe
                  -> indistinguishable from chance

Selection is the piece that has absorbed nearly all the project's effort and
is worth zero. The universe is the piece nobody has touched, and it is the
largest measurable deficit. The current screen (market cap >= $2B, price >
$10, PIT index membership or gap ticker) is a LIQUIDITY screen -- it was
never meant to select good companies, and it doesn't.

So: before building another picker, find out whether any simple, mechanically
defensible, point-in-time screen produces a pool whose equal-weight beats the
index. If one does, every downstream strategy starts ahead instead of 15%
behind. If none does, that is decisive information about this universe and
the stock-picking line should close.

Each screen is evaluated the only honest way: equal-weighted, no selection,
no tuning. A screen that needs a picker on top to look good has not been
shown to work.

    python3 universe_probe.py [--cost-bps 5]
"""
import argparse
import gc
import json

import numpy as np
import pandas as pd

from features import FEATURE_COLS, FORWARD_WINDOW, OUT_DIR, DATA_DIR
from fundamentals_features_beta import FUNDAMENTAL_FEATURE_COLS
from execution import SegmentedOHLCPanel, realize_position
import continuous_walkforward_pit as cw
from pit_universe_continuous import members_asof

TRADING_DAYS = 252.0
SCREEN_COLS = ["volatility_60", "momentum_120", "market_cap", "roe",
               "operating_margin", "fcf_margin", "debt_to_equity",
               "pe_ratio", "revenue_growth_yoy"]


def q(a, p):
    """Nan-safe within-window quantile."""
    v = a[np.isfinite(a)]
    return np.nanpercentile(v, p) if len(v) else np.nan


def screens(w):
    """Every screen is computed from THIS window's cross-section only --
    no global thresholds, so nothing leaks across time."""
    f = w["feat"]
    n = len(w["names"])
    alive = np.ones(n, dtype=bool)
    out = {"all_eligible": alive}

    mc = f["market_cap"]
    out["mktcap_gt_10B"] = mc >= 1e10
    out["mktcap_gt_50B"] = mc >= 5e10
    out["sp500_pit"] = w["in_sp500"]

    roe, om, fcf = f["roe"], f["operating_margin"], f["fcf_margin"]
    out["profitable"] = np.isfinite(roe) & (roe > 0)
    out["quality"] = (np.isfinite(roe) & (roe > 0) &
                      np.isfinite(om) & (om > 0) &
                      np.isfinite(fcf) & (fcf > 0))

    de = f["debt_to_equity"]
    med_de = q(de, 50)
    out["low_debt"] = np.isfinite(de) & (de <= med_de)

    pe = f["pe_ratio"]
    lo_pe = q(np.where(pe > 0, pe, np.nan), 33)
    out["value"] = np.isfinite(pe) & (pe > 0) & (pe <= lo_pe)

    rg = f["revenue_growth_yoy"]
    hi_rg = q(rg, 67)
    out["growth"] = np.isfinite(rg) & (rg >= hi_rg)

    vol = f["volatility_60"]
    med_v = q(vol, 50)
    out["low_vol_half"] = np.isfinite(vol) & (vol <= med_v)

    mom = f["momentum_120"]
    out["mom_positive"] = np.isfinite(mom) & (mom > 0)

    out["quality_lowvol"] = out["quality"] & out["low_vol_half"]
    out["quality_large"] = out["quality"] & out["mktcap_gt_10B"]
    out["quality_mom"] = out["quality"] & out["mom_positive"]
    return out


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--cost-bps", type=float, default=5.0)
    ap.add_argument("--start", default=cw.DEFAULT_START_DATE)
    ap.add_argument("--entry-at", default="open")
    ap.add_argument("--min-names", type=int, default=20,
                     help="Minimum names for a window to be counted at all.")
    ap.add_argument("--min-hold", type=int, default=5,
                     help="A screen holds whatever it finds down to this many "
                          "names; below it, it holds CASH for that window rather "
                          "than the window being dropped. See the note in the loop.")
    args = ap.parse_args()

    cols = [c for c in FUNDAMENTAL_FEATURE_COLS if c != "fundamentals_age_days"]
    numeric = ["close", "open", "market_cap"] + FEATURE_COLS + cols
    print("Loading panel...")
    feat, _ = cw.load_panel_prepared(OUT_DIR / "features_with_fundamentals_pit.parquet",
                                      numeric, FEATURE_COLS, FORWARD_WINDOW)
    gap_tickers = cw.load_gap_ticker_set()
    current_universe = set(map(str, feat["ticker"].unique())) - gap_tickers
    gap_earliest = cw.build_gap_validity(feat, gap_tickers)
    all_dates = feat["date"].drop_duplicates().sort_values().reset_index(drop=True)
    step_dates = cw.build_step_dates(all_dates, args.start, FORWARD_WINDOW)
    dates_arr = feat["date"].values

    segs = feat.groupby("ticker", observed=True)["date"].agg(["min", "max"])
    panel = SegmentedOHLCPanel(
        cw.PRICE_DIRS,
        {t: (str(t).split("__post")[0], r["min"], r["max"]) for t, r in segs.iterrows()})
    del segs
    gc.collect()

    spy = pd.read_csv(DATA_DIR / "SPY.csv", parse_dates=["date"]).sort_values("date")
    spy = spy.reset_index(drop=True)

    def spy_leg(tp):
        f = spy[spy["date"] > tp]
        if f.empty:
            return None
        e = float(f.iloc[0]["open" if args.entry_at == "open" else "close"])
        i = 0 if args.entry_at == "open" else 1
        w = f.iloc[i:i + FORWARD_WINDOW]
        return None if w.empty or e <= 0 else float(w["close"].iloc[-1]) / e - 1

    print("Realizing every eligible ticker, once per window...")
    windows = []
    for tp in step_dates:
        idx = all_dates[all_dates == tp].index[0]
        if idx < FORWARD_WINDOW:
            continue
        allowed = cw.allowed_universe_at(tp, current_universe, gap_earliest, "expanded")
        lo = int(np.searchsorted(dates_arr, np.datetime64(tp), "left"))
        hi = int(np.searchsorted(dates_arr, np.datetime64(tp), "right"))
        rows = feat.iloc[lo:hi]
        rows = rows[rows["ticker"].isin(allowed)]
        if rows.empty:
            continue
        is_gap = rows["ticker"].isin(gap_earliest.index)
        ok = is_gap | ((rows["close"] > cw.MIN_PRICE) &
                       (rows["market_cap"] >= cw.MIN_MARKET_CAP))
        rows = rows[ok]
        s = spy_leg(tp)
        if len(rows) < args.min_names or s is None:
            continue

        tk = rows["ticker"].astype(str).values
        keep_i, names, rets = [], [], []
        for j, t in enumerate(tk):
            g = panel.get(t)
            if g is None:
                continue
            pos = realize_position(g, tp, FORWARD_WINDOW, entry_lag=1,
                                   entry_at=args.entry_at, stop_pct=None, cost_bps=0.0)
            if pos is not None:
                keep_i.append(j); names.append(t); rets.append(pos["gross_return"])
        if len(names) < args.min_names:
            continue
        keep_i = np.array(keep_i)
        mem = members_asof(str(tp.date()))
        windows.append({
            "tp": str(tp.date()), "names": np.array(names),
            "rets": np.array(rets, float), "spy": s,
            "in_sp500": np.array([n.split("__post")[0] in mem for n in names]),
            "feat": {c: rows[c].values[keep_i].astype(float) for c in SCREEN_COLS},
        })
        if len(windows) % 20 == 0:
            print(f"  {len(windows)} windows, last {tp.date()}", flush=True)

    n = len(windows)
    per = TRADING_DAYS / FORWARD_WINDOW
    s_arr = np.array([w["spy"] for w in windows])
    spy_term = float(np.prod(1 + s_arr) * 10000)
    spy_vol = float(s_arr.std(ddof=1) * np.sqrt(per))
    print(f"\n{n} windows. SPY ${spy_term:,.0f}, CAGR "
          f"{(spy_term/10000)**(per/n)-1:.2%}, vol {spy_vol:.1%}, "
          f"Sharpe {s_arr.mean()*per/spy_vol:.2f}\n")

    h = (args.cost_bps / 1e4) / 2.0
    names_all = [screens(w) for w in windows]
    keys = list(names_all[0].keys())

    results = {}
    for k in keys:
        # A screen that cannot fill a window must hold CASH, not vanish.
        #
        # v1 skipped such windows, which silently gave momentum- and size-based
        # screens a free pass on exactly the windows they could not fill -- and
        # for momentum_120 > 0 those are the crash windows. Their terminal was
        # then compounded over fewer periods and printed against SPY's
        # full-period figure. That is a look-ahead artifact of the same family
        # as everything else this project has had to unwind, and it made
        # mom_positive look like +14% over SPY.
        #
        # Now every screen is charged for all n windows. Sitting in cash is
        # allowed, but it is MARKET TIMING and is reported as such: cash_windows
        # counts them and spy_in_cash reports what SPY did while the screen was
        # out, so a screen that "wins" by dodging drawdowns is visible instead
        # of invisible.
        rets, sizes, prev = [], [], set()
        n_cash, spy_in_cash = 0, []
        for i, w in enumerate(windows):
            m = names_all[i][k]
            cnt = int(m.sum())
            sizes.append(cnt)
            if cnt < args.min_hold:
                n_cash += 1
                spy_in_cash.append(w["spy"])
                rets.append(-h if prev else 0.0)   # pay to exit what we held
                prev = set()
                continue
            sel = set(w["names"][m])
            g = float(w["rets"][m].mean())
            f_new = len(sel - prev) / len(sel) if sel else 1.0
            nxt = None
            if i + 1 < n:
                m2 = names_all[i + 1][k]
                if int(m2.sum()) >= args.min_hold:
                    nxt = set(windows[i + 1]["names"][m2])
            f_exit = 1.0 if nxt is None else len(sel - nxt) / len(sel)
            rets.append((1 + g) * (1 - h * f_exit) / (1 + h * f_new) - 1)
            prev = sel
        r = np.array(rets)
        assert len(r) == n, f"{k}: {len(r)} != {n}"
        term = float(np.prod(1 + r) * 10000)
        vol = float(r.std(ddof=1) * np.sqrt(per))
        ex = r - s_arr
        t = float(ex.mean() / (ex.std(ddof=1) / np.sqrt(n)))
        results[k] = {"terminal": term, "cagr": float((term/10000)**(per/n)-1),
                      "vol": vol, "sharpe": float(r.mean()*per/vol), "t_excess": t,
                      "n_windows": n, "avg_names": float(np.mean(sizes)),
                      "cash_windows": n_cash,
                      "spy_cagr_while_cash": (float(np.mean(spy_in_cash)) * 100
                                               if spy_in_cash else None)}

    hdr = (f"{'screen':<18}{'avg n':>7}{'cash':>6}{'terminal':>11}{'CAGR':>8}"
           f"{'vol':>7}{'Sharpe':>8}{'t_exc':>7}{'vs SPY':>8}")
    print(hdr); print("-" * len(hdr))
    for k in sorted(results, key=lambda x: -results[x]["terminal"]):
        v = results[k]
        print(f"{k:<18}{v['avg_names']:>7.0f}{v['cash_windows']:>6}"
              f"${v['terminal']:>10,.0f}{v['cagr']:>8.2%}{v['vol']:>7.1%}"
              f"{v['sharpe']:>8.2f}{v['t_excess']:>7.2f}"
              f"{v['terminal']/spy_term-1:>8.0%}")
    timers = {k: v for k, v in results.items() if v["cash_windows"] > 0}
    if timers:
        print("\nscreens that went to cash (this is MARKET TIMING, judge it as such):")
        for k, v in sorted(timers.items(), key=lambda kv: -kv[1]["cash_windows"]):
            print(f"  {k:<18}{v['cash_windows']:>3} of {n} windows in cash; "
                  f"SPY averaged {v['spy_cagr_while_cash']:+.2f}% per window "
                  f"while it sat out")
    print("-" * len(hdr))
    print(f"{'SPY':<18}{'':>7}${spy_term:>10,.0f}"
          f"{(spy_term/10000)**(per/n)-1:>8.2%}{spy_vol:>7.1%}"
          f"{s_arr.mean()*per/spy_vol:>8.2f}")

    json.dump({"cost_bps": args.cost_bps, "n_windows": n,
                "spy": {"terminal": spy_term, "vol": spy_vol}, "screens": results},
              open(OUT_DIR / "universe_probe.json", "w"), indent=2)
    print(f"\nSaved -> {OUT_DIR/'universe_probe.json'}")


if __name__ == "__main__":
    main()
