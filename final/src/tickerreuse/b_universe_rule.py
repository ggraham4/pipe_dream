"""WO-47 B: why are 19 Sep-11 panel tickers outside the universe rebuilt from Sep inputs?
Per ticker: does it pass marketcap>=2000 on any day; with the closeunadj floor; with the adjusted
close floor; the agreement rule. Also tries rule variants for the whole set.
Writes final/out/tickerreuse/b_universe_rule.json."""
import json

import pandas as pd

from common import OUT, SHARADAR
from b_universe_cf import PANEL, MASTER, SHARES, THROUGH, shares, DOMESTIC, DISAGREE_FACTOR

MISS = "ABTC ADAM CPHI CTEV DOMA EMBK FLNT GRCE GTE HGLI HIPO HKRSQ MFA NVTP RADCQ RBBN UIS VIEWQ VTNRQ".split()


def main():
    fr = []
    for f in sorted((PANEL / "daily").glob("*.parquet")):
        d = pd.read_parquet(f, columns=["ticker", "date", "marketcap"])
        s = pd.read_parquet(PANEL / "stocks" / f.name, columns=["ticker", "date", "close", "closeunadj"])
        j = d.merge(s, on=["ticker", "date"], how="inner")
        fr.append(j[j["marketcap"] >= 2000])
    J = pd.concat(fr, ignore_index=True)
    J["date"] = pd.to_datetime(J["date"])
    J = J[J["date"] <= THROUGH["sep"]].sort_values("date")
    sh = shares(SHARES["sep"])
    J = pd.merge_asof(J, sh, on="date", by="ticker", direction="backward")
    J["cxs"] = J["close"] * J["sharesbas"] / 1e6
    J["agree_bad"] = J["sharesbas"].notna() & (J["cxs"] > 0) & (J["marketcap"] / J["cxs"] > DISAGREE_FACTOR)
    J["floor_unadj"] = J["closeunadj"].fillna(J["close"]) > 10
    J["floor_adj"] = J["close"] > 10
    out = {}
    for t in MISS:
        g = J[J.ticker == t]
        out[t] = {"days_cap_ge_2000": int(len(g)),
                  "first_cap_day": str(g.date.min().date()) if len(g) else None,
                  "pass_unadj_floor": int(g.floor_unadj.sum()),
                  "pass_adj_floor": int(g.floor_adj.sum()),
                  "pass_adj_floor_and_agree": int((g.floor_adj & ~g.agree_bad).sum()),
                  "pass_unadj_floor_and_agree": int((g.floor_unadj & ~g.agree_bad).sum()),
                  "median_close_over_unadj": float((g.close / g.closeunadj).median()) if len(g) else None}
    dom = set(pd.read_csv(MASTER["sep"], dtype=str, keep_default_na=False).query("category in @DOMESTIC")["ticker"])
    Jd = J[J.ticker.isin(dom)]
    variants = {"unadj_floor+agree (current rule)": Jd.floor_unadj & ~Jd.agree_bad,
                "adj_floor+agree": Jd.floor_adj & ~Jd.agree_bad,
                "either_floor+agree": (Jd.floor_adj | Jd.floor_unadj) & ~Jd.agree_bad}
    import pyarrow.parquet as pq
    from common import MAIN
    sep11 = set(pq.read_table(MAIN / "out" / "features_with_rates_sharadar_pit.parquet", columns=["ticker"])
                .column("ticker").unique().to_pylist())
    res = {"per_ticker": out, "variants": {}}
    for k, v in variants.items():
        s = set(Jd.loc[v, "ticker"])
        res["variants"][k] = {"n": len(s), "equals_sep11": s == sep11,
                              "missing_vs_sep11": sorted(sep11 - s), "extra_vs_sep11": sorted(s - sep11)}
    (OUT / "b_universe_rule.json").write_text(json.dumps(res, indent=2, default=str))
    print(json.dumps(res, indent=1, default=str)[:6000])


if __name__ == "__main__":
    main()
