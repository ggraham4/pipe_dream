"""WO-60 Gate A4 (hand-verify the largest winning shorts against CRSP) + B1 Markit 2011 fee
distributions (bottom decile vs universe, cap2000 and cap150).

A4: for each checked position (ticker, signal date t), CRSP total return over the same hold =
  (|prc[e]| / openprc[e]) * prod_{e < j <= x} (1 + ret[j]) - 1, times (1 + dlret) if CRSP delists the
  permno within the window; e = entry date (t+1), x = exit date. Compared with the engine's r_tot.
  Pass: |diff| <= 5pp for every checked position.
Writes final/out/shortbook/gate_a4.json and markit_2011_fees.json.
"""
import json
import sys
from pathlib import Path

import numpy as np
import pandas as pd

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
import engine as E  # noqa: E402
import prechecks as PC  # noqa: E402
import sb_common as K  # noqa: E402


def crsp_total(permno, d_e, d_x):
    yrs = range(pd.Timestamp(d_e).year, pd.Timestamp(d_x).year + 1)
    f = pd.concat([pd.read_parquet(K.WRDS / "crsp" / f"dsf_{y}.parquet", filters=[("permno", "==", int(permno))]) for y in yrs])
    f["date"] = pd.to_datetime(f["date"])
    f = f[(f["date"] >= d_e) & (f["date"] <= d_x)].sort_values("date")
    if f.empty or not np.isfinite(f["openprc"].iloc[0]) or f["date"].iloc[0] != d_e:
        return None, "no CRSP bar / open on entry date"
    first = abs(f["prc"].iloc[0]) / f["openprc"].iloc[0]
    rest = (1 + f["ret"].iloc[1:].fillna(0.0)).prod()
    dl = pd.read_parquet(K.WRDS / "crsp" / "dsedelist.parquet", columns=["permno", "dlstdt", "dlstcd", "dlret"])
    dl = dl[(dl["permno"] == permno)]
    dl = dl[(pd.to_datetime(dl["dlstdt"]) >= d_e) & (pd.to_datetime(dl["dlstdt"]) <= d_x + pd.Timedelta(days=60)) & (dl["dlstcd"] >= 200)]
    note = ""
    tot = first * rest
    if len(dl) and pd.notna(dl["dlret"].iloc[0]) and f["date"].iloc[-1] < d_x:
        tot *= 1 + dl["dlret"].iloc[0]; note = f"CRSP delist {int(dl['dlstcd'].iloc[0])}"
    return float(tot - 1), note


def check(rows, picks):
    ln = pd.read_parquet(K.WRDS / "link" / "permno_sharadar.parquet")
    ln["valid_from"] = pd.to_datetime(ln["valid_from"]); ln["valid_to"] = pd.to_datetime(ln["valid_to"]).fillna(pd.Timestamp("2099-12-31"))
    out = []
    for _, p in picks.iterrows():
        r = rows[(rows["ticker"] == p["ticker"]) & (rows["date"] == pd.Timestamp(p["date"]))].iloc[0]
        base = p["ticker"].split("__")[0]
        c = ln[(ln["ticker"] == base) & (ln["valid_from"] <= r["d_e"]) & (ln["valid_to"] >= r["d_e"])]
        rec = {"ticker": p["ticker"], "date": str(pd.Timestamp(p["date"]).date()), "entry": str(r["d_e"].date()),
               "exit": str(r["d_x"].date()), "r_engine": float(r["r_tot"]), "r_px": float(r["r_px"]), "div": float(r["div"]),
               "dl": float(r["dl"]), "dl_class": r["dl_class"]}
        if c.empty:
            rec.update(r_crsp=None, diff=None, ok=False, note="no permno link")
        else:
            rc, note = crsp_total(int(c["permno"].iloc[0]), r["d_e"], r["d_x"])
            rec.update(permno=int(c["permno"].iloc[0]), r_crsp=rc, note=note,
                       diff=(None if rc is None else float(r["r_tot"] - rc)),
                       ok=bool(rc is not None and abs(r["r_tot"] - rc) <= 0.05))
        out.append(rec)
        K.log(f"A4 {rec}")
    return out


def main():
    res = {}
    E.load("cap2000")
    R = E.G["R"]
    base = np.load(K.OUT_BIG / "pick_base_cap2000.npy")
    sel = base & E.G["shortable"]
    df = R.loc[sel, ["ticker", "date", "r_tot"]]
    top_raw = df.nsmallest(20, "r_tot")
    top_dist = df.sort_values("r_tot").drop_duplicates("ticker").head(20)
    worst_loss = df.sort_values("r_tot", ascending=False).drop_duplicates("ticker").head(5)
    res["top20_positions"] = check(R, top_raw)
    res["top20_distinct_tickers"] = check(R, top_dist)
    res["largest5_losses_distinct"] = check(R, worst_loss)
    allc = res["top20_positions"] + res["top20_distinct_tickers"]
    res["A4_pass"] = bool(all(x["ok"] for x in allc))
    res["n_checked"] = len(allc); res["n_ok"] = int(sum(x["ok"] for x in allc))
    (K.OUT / "gate_a4.json").write_text(json.dumps(res, indent=1, default=str))
    K.log(f"A4 pass {res['A4_pass']} ({res['n_ok']}/{res['n_checked']})")

    # ---- Markit 2011-03-21 fee distribution: bottom decile vs universe, both tiers
    mk = pd.read_parquet(K.OUT_BIG / "markit_2011_cap150.parquet")[["ticker", "indicativefee", "dcbs"]]
    fees = {}
    for tier in ("cap2000", "cap150"):
        E.load(tier)
        R = E.G["R"]; b = np.load(K.OUT_BIG / f"pick_base_{tier}.npy")
        day = R["date"] == PC.MARKIT_DATE
        for nm, msk in (("bottom_decile", day & b), ("universe", day)):
            g = R.loc[msk.to_numpy(), ["ticker"]].merge(mk, on="ticker", how="left")
            f = g["indicativefee"].dropna()
            fees[f"{tier}_{nm}"] = {"n": int(len(g)), "n_with_fee": int(len(f)), "median": float(f.median()),
                                    "mean": float(f.mean()), "p75": float(f.quantile(0.75)), "p90": float(f.quantile(0.9)),
                                    "p99": float(f.quantile(0.99)), "share_dcbs_ge3": float((g["dcbs"].dropna() >= 3).mean()),
                                    "share_fee_gt10pct": float((f > 0.10).mean())}
    (K.OUT / "markit_2011_fees.json").write_text(json.dumps(fees, indent=1))
    print(json.dumps(fees, indent=1))


if __name__ == "__main__":
    main()
