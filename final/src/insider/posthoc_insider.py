"""
POST-HOC diagnostics for the insider screen. NOT trials, selects nothing:
written after screen_insider.py showed ins_buyers_90's raw IC ~0 but its
sector-neutral IC t ~ +3. Explains that gap and sizes the directions worth
a future pre-registration. Nomination era 2007-2019 only.

  a) fire rate and mean 40d return by sector (why raw != sector-neutral)
  b) per-year sector-neutral IC (x AND return demeaned) and leave-one-year-out t
  c) sector-neutral (both sides) IC by market-cap tercile (literature: small caps)
  d) event study split: opportunistic vs routine buyers (Cohen, Malloy &
     Pomorski 2012: routine = bought in the same calendar month in each of
     the 3 prior years), sector-demeaned 40d returns

Usage: python3 posthoc_insider.py
"""
import json
import sys
import time
from pathlib import Path

import numpy as np
import pandas as pd

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
import screen_insider as S  # noqa: E402

OUT_JSON = S.MAIN_ROOT / "out" / "insider" / "insider_posthoc_report.json"
X = "ins_buyers_90"


def main():
    t0 = time.time()
    df = pd.read_parquet(S.PANEL_PATH, columns=["ticker", "date", "eligible_cap150", "sector",
                                                "market_cap", S.LABEL])
    df["date"] = pd.to_datetime(df["date"]); df["ticker"] = df["ticker"].astype(str)
    df = df[(df["date"] >= S.NOMINATE_START) & (df["date"] <= S.NOMINATE_END) & df["eligible_cap150"]]
    ins = pd.read_parquet(S.INSIDER_PATH, columns=["ticker", "date", X])
    ins["ticker"] = ins["ticker"].astype(str); ins["date"] = pd.to_datetime(ins["date"])
    df = df.merge(ins, on=["ticker", "date"], how="left").sort_values(["date", "ticker"]).reset_index(drop=True)
    df["sector"] = df["sector"].fillna("Unknown")
    df["xs"] = df[X] - df.groupby(["date", "sector"])[X].transform("mean")
    df["ys"] = df[S.LABEL] - df.groupby(["date", "sector"])[S.LABEL].transform("mean")
    df["yd"] = df[S.LABEL] - df.groupby("date")[S.LABEL].transform("mean")
    rep = {"note": "POST-HOC, descriptive only; not trials"}

    # a) sector concentration
    sec = df.groupby("sector").agg(share_rows=("ticker", "size"), fire_rate=(X, lambda s: (s > 0).mean()),
                                   mean_demeaned_ret40=("yd", "mean"))
    sec["share_rows"] /= sec["share_rows"].sum()
    rep["by_sector"] = sec.round(4).to_dict(orient="index")
    print(sec.sort_values("fire_rate").round(4).to_string())
    print("corr(sector fire rate, sector demeaned return):",
          round(sec["fire_rate"].corr(sec["mean_demeaned_ret40"]), 3))

    # b) per-year and LOYO on sector-neutral IC
    # both sides sector-neutral: x-only demeaning is a reverse sector bet
    # (high-fire sectors underperform), see (a)
    s = S.daily_corr(df, "xs", "ys")
    per_year = {int(y): S.newey_west_mean_t(g.to_numpy()) for y, g in s.groupby(s.index.year)}
    loyo = {int(y): S.newey_west_mean_t(s[s.index.year != y].to_numpy())["t"] for y in per_year}
    rep["sector_neutral_per_year"] = per_year
    rep["sector_neutral_loyo_t"] = loyo
    print("per-year sector-neutral IC:", {y: round(v["mean"], 4) for y, v in per_year.items()})
    print("LOYO t: min", round(min(loyo.values()), 2), "max", round(max(loyo.values()), 2),
          "worst year dropped", min(loyo, key=loyo.get))
    # sector-neutral both sides: demeaned return too
    rep["sector_neutral_x_and_y"] = S.ic_stats(df, "xs", "ys")
    rep["sector_neutral_x_only"] = S.ic_stats(df, "xs", S.LABEL)
    print("IC(sector-neutral x, sector-neutral y):", round(rep["sector_neutral_x_and_y"]["pooled"]["mean"], 4),
          "t", round(rep["sector_neutral_x_and_y"]["pooled"]["t"], 2))

    # c) size terciles (per date)
    df["size_t"] = df.groupby("date")["market_cap"].transform(lambda m: pd.qcut(m.rank(method="first"), 3, labels=False))
    rep["by_size_tercile"] = {}
    for k, g in df.groupby("size_t"):
        st = S.ic_stats(g, "xs", "ys")["pooled"]
        rep["by_size_tercile"][int(k)] = {**st, "fire_rate": float((g[X] > 0).mean())}
        print(f"size tercile {int(k)} (0=small): IC {st['mean']:+.4f} t {st['t']:+.2f} fire {(g[X] > 0).mean():.3f}")

    # d) opportunistic vs routine event study
    ev = pd.read_parquet(S.EVENTS_PATH)
    ev = ev[ev["is_od"] & (ev["code"] == "P")].copy()
    ev["y"] = ev["trans_date"].dt.year; ev["m"] = ev["trans_date"].dt.month
    key = set(zip(ev["issuer_cik"], ev["owner_cik"], ev["y"], ev["m"]))
    has3 = ev.groupby(["issuer_cik", "owner_cik"])["y"].transform(lambda y: (y - y.min()) >= 3)
    ev["routine"] = [all((c, o, y - k, m) in key for k in (1, 2, 3))
                     for c, o, y, m in zip(ev["issuer_cik"], ev["owner_cik"], ev["y"], ev["m"])]
    ev["classifiable"] = has3
    ev = ev[ev["classifiable"] & ev["filing_date"].between(S.NOMINATE_START, S.NOMINATE_END)]
    tm = pd.read_csv(S.TICKERS_MASTER, usecols=["ticker", "secfilings"])
    tm["cik"] = pd.to_numeric(tm["secfilings"].str.extract(r"CIK=0*(\d+)")[0], errors="coerce")
    ev = ev.assign(cik=ev["issuer_cik"].astype("int64")).merge(
        tm[["ticker", "cik"]].dropna().astype({"cik": "int64"}), on="cik")
    evd = ev.groupby(["ticker", "filing_date"]).agg(routine=("routine", "all")).reset_index().sort_values("filing_date")
    base = df[["ticker", "date", "ys"]].sort_values("date")
    hit = pd.merge_asof(evd, base, left_on="filing_date", right_on="date", by="ticker",
                        direction="forward", tolerance=pd.Timedelta(days=5)).dropna(subset=["ys"])
    rep["event_opportunistic_vs_routine"] = {}
    for name, sub in (("opportunistic", hit[~hit["routine"]]), ("routine", hit[hit["routine"]])):
        m = sub.groupby(sub["date"].dt.to_period("M"))["ys"].mean()
        t = S.newey_west_mean_t(m.to_numpy(), lag=2)["t"]  # monthly means overlap: NW lag 2
        rep["event_opportunistic_vs_routine"][name] = {"n": int(len(sub)), "mean_sector_demeaned_ret40": float(sub["ys"].mean()),
                                                       "month_nw2_t": t}
        print(f"event {name:13s} n={len(sub):6d} sector-demeaned 40d {sub['ys'].mean():+.4f} t {t:+.2f}")

    with open(OUT_JSON, "w") as f:
        json.dump(rep, f, indent=2, default=float)
    print(f"wrote {OUT_JSON} ({time.time()-t0:.0f}s)")


if __name__ == "__main__":
    main()
