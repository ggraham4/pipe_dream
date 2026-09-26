"""
WO-14 acceptance checks for a refresh of the working panel (read-only).

    python final/src/reset2026/wo14_acceptance.py <old_end YYYY-MM-DD>

Reads the refreshed composite_panel_v2.parquet and its dated backup
composite_panel_v2_through_<old_end>.parquet, the refresh report, SEP and SF1.
Writes out/reset2026/downcap_v2/wo14_acceptance_<new_end>.json.

 1 overlap identity (dates <= old_end): every non-label column bit-identical
   except the tickers the refresh report lists (revised / new); labels differ
   only as NaN -> value
 3 new dates: rows per date within +-5% of 3,901; AAPL MSFT NVDA NATH WLKP
   present, eligible_cap150 and kept by the SPAC rule; close == raw SEP close
   (3 tickers x every new date); fundamentals as-of (3 tickers): market_cap
   == close x sharesbas of the latest SF1 ARQ/ARY filing with date <= row date
 4 reproduction: one ticker rebuilt from its FULL history with the original
   v2 builders (module mains, paths repointed, one-ticker universe) equals
   the refreshed panel on the new dates
"""
import json
import sys
import tempfile
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE.parent))
sys.path.insert(0, str(HERE))
MAIN = Path("/Users/ggraham/pipe_dream/final")
import features as _f  # noqa: E402
_f.PROJECT_ROOT = MAIN
_f.DATA_DIR = MAIN / "scripts" / "td_data_local"
_f.OUT_DIR = MAIN / "out"
_f.MODELS_DIR = MAIN / "out" / "models"

import numpy as np  # noqa: E402
import pandas as pd  # noqa: E402
import pyarrow as pa  # noqa: E402
import pyarrow.parquet as pq  # noqa: E402

import working_panel as W  # noqa: E402

R26 = MAIN / "out" / "reset2026"
V2DIR = R26 / "downcap_v2"
LABELS = ["forward_return_40", "forward_return_tradable_40"]
NAMED = ["AAPL", "MSFT", "NVDA", "NATH", "WLKP"]
RAW_CHECK = ["AAPL", "NATH", "WLKP"]
REPRO_TICKER = "NATH"


def eq(a, b):
    a, b = np.asarray(a), np.asarray(b)
    if a.dtype.kind == "f" or b.dtype.kind == "f":
        a, b = a.astype(np.float64), b.astype(np.float64)
        return (a == b) | (np.isnan(a) & np.isnan(b))
    return a == b


def check_overlap(old_end, rep):
    excl = set(rep["revised_recomputed"]) | set(rep["new_tickers"])
    bk = R26 / f"composite_panel_v2_through_{old_end}.parquet"
    res = {"excluded_tickers": sorted(excl), "columns": {}}
    old = pd.read_parquet(bk)
    new = pd.read_parquet(W.WORKING_PANEL, filters=[("date", "<=", old_end)])
    for d in (old, new):
        d["ticker"] = d["ticker"].astype(str)
    res["rows_backup"], res["rows_refreshed_le_old_end"] = len(old), len(new)
    oo, nn = old[~old.ticker.isin(excl)], new[~new.ticker.isin(excl)]
    res["rows_compared"] = len(oo)
    m = oo.merge(nn, on=["ticker", "date"], how="outer", suffixes=("", "__n"), indicator=True)
    res["row_set_equal"] = bool((m["_merge"] == "both").all())
    ok = res["row_set_equal"]
    for c in [c for c in old.columns if c not in ("ticker", "date")]:
        e = eq(m[c].to_numpy(), m[c + "__n"].to_numpy())
        if c in LABELS:
            nan_to_val = (pd.isna(m[c]) & ~pd.isna(m[c + "__n"])).to_numpy()
            other = ~e & ~nan_to_val
            res["columns"][c] = {"nan_to_value": int(nan_to_val.sum()), "other_changes": int(other.sum())}
            ok &= not other.any()
        else:
            res["columns"][c] = {"mismatches": int((~e).sum())}
            ok &= bool(e.all())
    # the excluded tickers: how their rows moved
    ox, nx = old[old.ticker.isin(excl)], new[new.ticker.isin(excl)]
    res["excluded_rows_backup"], res["excluded_rows_refreshed"] = len(ox), len(nx)
    res["PASS"] = bool(ok)
    return res


def check_new_dates(old_end):
    res = {}
    new = pd.read_parquet(W.WORKING_PANEL, filters=[("date", ">", old_end)])
    new["ticker"] = new["ticker"].astype(str)
    cnt = new.groupby("date").size()
    res["rows_per_date"] = {k: int(v) for k, v in cnt.items()}
    res["rows_ok"] = bool(((cnt >= 3901 * 0.95) & (cnt <= 3901 * 1.05)).all())
    keep = W.universe_keep(new["ticker"])
    new["keep"] = keep
    last = new["date"].max()
    named = {}
    for t in NAMED:
        r = new[new.ticker == t]
        named[t] = {"dates_present": int(len(r)), "n_new_dates": int(len(cnt)),
                    "eligible_cap150_all": bool(r["eligible_cap150"].all()) if len(r) else False,
                    "spac_rule_keep": bool(r["keep"].all()) if len(r) else False}
    res["named"] = named
    res["named_ok"] = all(v["dates_present"] == v["n_new_dates"] and v["eligible_cap150_all"] and v["spac_rule_keep"]
                          for v in named.values())
    # raw SEP close
    sep = []
    for f in sorted((MAIN / "data/sharadar/panel/stocks").glob("*.parquet"))[-2:]:
        sep.append(pd.read_parquet(f, columns=["ticker", "date", "close"]))
    sep = pd.concat(sep)
    j = new[new.ticker.isin(RAW_CHECK)][["ticker", "date", "close"]].merge(sep, on=["ticker", "date"], suffixes=("", "_raw"))
    res["raw_close"] = {"rows_checked": int(len(j)), "mismatches": int((~eq(j.close, j.close_raw)).sum()),
                        "example": j.tail(3).to_dict("records")}
    # fundamentals as-of: market_cap == close * sharesbas(latest ARQ/ARY filing, date <= row date)
    sf1 = pd.read_parquet(MAIN / "data/sharadar/sf1_fundamentals.parquet",
                          columns=["ticker", "dimension", "date", "datekey", "reportperiod", "sharesbas"]) \
        if "datekey" in pq.read_schema(MAIN / "data/sharadar/sf1_fundamentals.parquet").names else \
        pd.read_parquet(MAIN / "data/sharadar/sf1_fundamentals.parquet",
                        columns=["ticker", "dimension", "date", "reportperiod", "sharesbas"])
    sf1 = sf1[sf1.dimension.isin(["ARQ", "ARY"]) & sf1.sharesbas.notna()]
    sf1["date"] = pd.to_datetime(sf1["date"])
    fa = []
    for t in RAW_CHECK:
        r = new[(new.ticker == t) & (new.date == last)].iloc[0]
        s = sf1[(sf1.ticker == t) & (sf1.date <= pd.Timestamp(last))].sort_values("date")
        s = s.drop_duplicates("date", keep="last").iloc[-1]
        mc = r["close"] * s["sharesbas"]
        fa.append({"ticker": t, "row_date": last, "filing_date_used": str(s["date"].date()),
                   "reportperiod": str(s["reportperiod"])[:10], "filing_le_row_date": bool(s["date"] <= pd.Timestamp(last)),
                   "market_cap_panel": float(r["market_cap"]), "close_x_sharesbas": float(mc),
                   "match": bool(r["market_cap"] == mc)})
    res["fundamentals_asof"] = fa
    res["sf1_max_filing_date"] = str(sf1["date"].max().date())
    res["PASS"] = bool(res["rows_ok"] and res["named_ok"] and res["raw_close"]["mismatches"] == 0
                       and all(x["match"] and x["filing_le_row_date"] for x in fa))
    return res


def check_repro(old_end):
    """Original builders, full history, one ticker."""
    import build_features_sharadar as BF
    import build_features_fundamentals_sharadar as FF
    import quality_factors as Q
    import build_panel as BP
    import build_beta_feature as BB
    from sweep.issuance import build_issuance_features
    from sweep.short_interest import build_short_interest_features
    from sweep import events as E
    t = REPRO_TICKER
    with tempfile.TemporaryDirectory() as td:
        td = Path(td)
        pd.DataFrame({"ticker": [t]}).to_parquet(td / "u.parquet", index=False)
        BF.UNIVERSE, BF.OUT = td / "u.parquet", td / "price.parquet"
        BF.build()
        FF.PRICE_PANEL, FF.OUT = td / "price.parquet", td / "fund.parquet"
        FF.main()
        fund = pd.read_parquet(td / "fund.parquet")
        build_issuance_features(fund.copy())[["ticker", "date", "net_issuance_pct"]].to_parquet(td / "iss.parquet")
        build_short_interest_features(fund.copy())[["ticker", "date", "short_interest_days_to_cover"]].to_parquet(td / "si.parquet")
        E.build_event_features(fund.copy(), horizon=40, verbose=False)[
            ["ticker", "date", "days_to_next_filing_seasonal"]].to_parquet(td / "ev.parquet")
        Q.PRICE_PANEL, Q.OUT = td / "price.parquet", td / "q.parquet"
        Q.main()
        BP.BASE_PANEL, BP.ISSUANCE_PANEL, BP.SHORT_INT_PANEL = td / "fund.parquet", td / "iss.parquet", td / "si.parquet"
        BP.EVENTS_PANEL, BP.QUALITY_PANEL = td / "ev.parquet", td / "q.parquet"
        # flags are not under test here (they come from downcap_universe.py); pass the panel's through
        BP.DOWNCAP_UNIVERSE = W.WORKING_PANEL
        BP.OUT = td / "panel.parquet"
        BP.main()
        BB.PANEL_PATH, BB.OUT = td / "price.parquet", td / "beta.parquet"
        BB.main()
        rp = pd.read_parquet(td / "panel.parquet")
        rb = pd.read_parquet(td / "beta.parquet")
    cur = pd.read_parquet(W.WORKING_PANEL, filters=[("ticker", "==", t)])
    curb = pd.read_parquet(W.WORKING_BETA, filters=[("ticker", "==", t)])
    out = {"ticker": t}
    for name, a, b in (("panel", rp, cur), ("beta", rb, curb)):
        a = a[a.date > old_end]
        b = b[b.date > old_end]
        m = a.merge(b, on=["ticker", "date"], suffixes=("", "__cur"))
        cols = [c for c in b.columns if c not in ("ticker", "date") and not c.startswith("eligible")
                and c in a.columns]
        mm = {c: int((~eq(m[c].to_numpy(), m[c + "__cur"].to_numpy())).sum()) for c in cols}
        out[name] = {"new_date_rows_rebuilt": len(a), "rows_refreshed": len(b), "matched": len(m),
                     "mismatches": mm}
    out["PASS"] = all(out[n]["matched"] == out[n]["rows_refreshed"] > 0 and not any(out[n]["mismatches"].values())
                      for n in ("panel", "beta"))
    return out


def main():
    old_end = sys.argv[1]
    new_end = W.latest_date().date().isoformat()
    rep = json.loads((V2DIR / f"refresh_report_{new_end}.json").read_text())
    res = {"old_end": old_end, "new_end": new_end}
    res["1_overlap"] = check_overlap(old_end, rep)
    print("1", json.dumps({k: v for k, v in res["1_overlap"].items() if k != "excluded_tickers"}, default=str))
    res["3_new_dates"] = check_new_dates(old_end)
    print("3", json.dumps(res["3_new_dates"], default=str))
    res["4_repro"] = check_repro(old_end)
    print("4", json.dumps(res["4_repro"], default=str))
    (V2DIR / f"wo14_acceptance_{new_end}.json").write_text(json.dumps(res, indent=2, default=str))
    ok = res["1_overlap"]["PASS"] and res["3_new_dates"]["PASS"] and res["4_repro"]["PASS"]
    print("ALL PASS" if ok else "SOME FAIL")
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
