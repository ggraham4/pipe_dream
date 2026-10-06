"""
WO-43 Step 1b: did the CACHED q75 run actually train on the violating rows?

step1_audit.py found, on the CURRENT panel (rebuilt 2026-10-05), 6 training
rows that violate the cutoff rule: ticker ADRX, rows 2006-09-11..2006-09-18,
whose 40-row label shift lands on 6 rows of a NEW listing under the same
symbol dated 2026-09-25..2026-10-02 (ticker reuse merged into one block). They
enter the training set of the 6 score dates 2007-01-03..2007-10-18.

The cache was written 2026-09-10, before any of those 2026 rows existed, so
in the cache's panel those 6 rows had no row i+40 and a NaN label (not
trained on). This script tests that directly by refitting the cached cell at
violating and non-violating score dates with three training sets:

  masked   rows whose label exits after the score date dropped (what the
           cache's panel implies)
  ph0/ph1  the 6 rows INCLUDED with a placeholder label (-1.0 -> class 0,
           +10.0 -> class 1). Placeholders, not the real 2026-based label, so no
           2020+ return is ever computed.

and comparing each to the cached scores on the cached tickers. If masked
reproduces the cache exactly and both placeholders do not, the cache did not
train on the rows.

Output: final/out/xgbretrain/step1b_cache_replay.json
"""
import json
import sys
import time
from pathlib import Path

import numpy as np
import pandas as pd

HERE = Path(__file__).resolve().parent
SRC = HERE.parent
sys.path.insert(0, str(SRC))
MAIN = Path("/Users/ggraham/pipe_dream/final")
import features as F                      # noqa: E402
import continuous_walkforward_pit as W    # noqa: E402
W.OUT_DIR = MAIN / "out"
W.PIT_UNIVERSE_PATH = MAIN / "data" / "sharadar" / "pit_universe.parquet"
from sweep import scorecache as SC       # noqa: E402

import step1_audit as A                   # noqa: E402

OUT = HERE.parents[1] / "out" / "xgbretrain" / "step1b_cache_replay.json"
DATES = ["2007-01-03", "2007-10-18", "2007-12-14", "2015-02-10"]


def log(m):
    print(f"[{time.strftime('%H:%M:%S')}] {m}", flush=True)


def main():
    global OUT
    if len(sys.argv) > 1:                       # alternative panel (older build)
        A.PANEL = Path(sys.argv[1])
        OUT = OUT.with_name(f"step1b_cache_replay_{A.PANEL.stem}.json")
    cfg = SC.SignalConfig(features="price_fund", horizon=40, label="q75", label_basis="tradable",
                          model="xgb", depth=3, eta=0.1, rounds=100, train="expanding",
                          train_cap=500000, universe="pit", step=40, seed=0)
    assert cfg.id == "price_fund_h40_q75_trd_xgb_d3e01r100_expanding_cap500k_pit_s40"
    fcols = list(SC.FEATURE_SETS["price_fund"])
    log("raw pass (exit dates) ...")
    R = A.raw_pass()
    raw_idx = np.flatnonzero(R["keep"])
    raw_idx = raw_idx[np.argsort(R["dates"][raw_idx], kind="stable")]
    f_exit = R["exit_date"][raw_idx]
    log("load_panel_prepared ...")
    df, _ = W.load_panel_prepared(A.PANEL, ["close", "open", "market_cap"] + fcols, list(F.FEATURE_COLS), 40)
    assert (df["date"].to_numpy() == R["dates"][raw_idx]).all()
    X = np.ascontiguousarray(df[fcols].to_numpy(np.float32))
    lab_all = df[F.TRADABLE_LABEL_COL].to_numpy(np.float32)
    dates_arr = df["date"].values
    all_dates = pd.Series(sorted(df["date"].unique()))
    pit_map = W.load_pit_universe()
    cur = set(df["ticker"].cat.categories.tolist())
    cache = pd.read_parquet(A.CACHE, columns=["timepoint", "ticker", "score"])
    cache["timepoint"] = pd.to_datetime(cache["timepoint"])
    dates = DATES
    if len(sys.argv) > 2 and sys.argv[2] == "all":   # every PRE-2020 cache date (no 2020+ fit)
        dates = [str(pd.Timestamp(t).date()) for t in sorted(cache["timepoint"].unique())
                 if pd.Timestamp(t) < pd.Timestamp("2020-01-01")]
        OUT = OUT.with_name(OUT.stem + "_all_pre2020.json")
    out = {"cell": cfg.id, "panel": str(A.PANEL), "dates": {}}
    for ds in dates:
        tp = pd.Timestamp(ds)
        idx = all_dates[all_dates == tp].index[0]
        cutoff = all_dates.iloc[idx - 40]
        hi = int(np.searchsorted(dates_arr, np.datetime64(cutoff), "right"))
        allowed = W.allowed_universe_at(tp, cur, None, "pit", pit_map)
        te_lo = int(np.searchsorted(dates_arr, np.datetime64(tp), "left"))
        te_hi = int(np.searchsorted(dates_arr, np.datetime64(tp), "right"))
        tick = df["ticker"].iloc[te_lo:te_hi].astype(str).to_numpy()
        sel = np.isin(tick, list(allowed))
        pos = np.arange(te_lo, te_hi)[sel]
        tick = tick[sel]
        cs = cache[cache["timepoint"] == tp].set_index("ticker")["score"]
        viol = np.flatnonzero(np.isfinite(lab_all[:hi]) & (f_exit[:hi] > np.datetime64(tp)))
        bad_lab = np.flatnonzero(~np.isfinite(lab_all[:hi]) & (f_exit[:hi] > np.datetime64(tp)))
        variants = {"masked": None}
        if len(viol):
            variants.update({"ph0": -1.0, "ph1": 10.0})
        rec = {"n_violating_rows": int(len(viol)), "variants": {}}
        for name, ph in variants.items():
            lab = lab_all[:hi].copy()
            if ph is None:
                lab[viol] = np.nan
            else:
                lab[viol] = ph
            mask = np.isfinite(lab)
            n_sel = int(mask.sum())
            if n_sel > 500000:
                s = np.flatnonzero(mask)
                mask[s[:-500000]] = False
                n_sel = 500000
            n_viol_used = int(mask[viol].sum()) if len(viol) else 0
            cut = float(np.percentile(lab[mask], 75))
            y = (lab > cut).astype(np.float32)
            score, _ = SC._fit_predict(cfg, X, y, hi, mask, X[pos], 0, n_sel)
            s = pd.Series(score, index=tick)
            common = cs.index.intersection(s.index)
            d = np.abs(s[common].to_numpy(np.float64) - cs[common].to_numpy(np.float64))
            rec["variants"][name] = {"violating_rows_in_train": n_viol_used, "n_common": int(len(common)),
                                     "n_cache": int(len(cs)), "n_now": int(len(s)),
                                     "max_abs_diff": float(d.max()), "n_bit_equal": int((d == 0).sum())}
            log(f"  {ds} {name}: viol used {n_viol_used}, max|diff| {d.max():.3g}, bit-equal {(d == 0).sum()}/{len(common)}")
        out["dates"][ds] = rec
    v = [r["variants"]["masked"] for r in out["dates"].values()]
    out["summary_masked"] = {"n_dates": len(v), "max_abs_diff": max(x["max_abs_diff"] for x in v),
                             "all_bit_equal": all(x["n_bit_equal"] == x["n_common"] == x["n_cache"] for x in v),
                             "violating_rows_used": sum(x["violating_rows_in_train"] for x in v)}
    log(f"summary {out['summary_masked']}")
    OUT.write_text(json.dumps(out, indent=1))
    log(f"-> {OUT}")


if __name__ == "__main__":
    main()
