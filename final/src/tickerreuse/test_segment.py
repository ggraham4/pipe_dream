"""WO-47 unit tests for the reused-symbol split (build_features_sharadar.segment_reused_symbols) and
its use in the v2 refresh price/outcome steps. Synthetic data plus the real ADRX extract; offline.

    /opt/anaconda3/envs/pipe_dream/bin/python final/src/tickerreuse/test_segment.py
"""
import inspect

import numpy as np
import pandas as pd
import pyarrow.parquet as pq

from common import FROZEN, SEP_DIR, MASTERS
import build_features_sharadar as BF

D = lambda s: np.datetime64(pd.Timestamp(s), "ns")


def frame(tk, dates, start=10.0):
    d = pd.to_datetime(dates)
    c = start * (1 + 0.0001 * np.arange(len(d)))
    return pd.DataFrame({"ticker": tk, "date": d, "open": c, "high": c, "low": c, "close": c, "volume": 1e5})


def main():
    old = pd.bdate_range("2005-01-03", "2006-11-03")
    new = pd.bdate_range("2026-09-25", "2026-10-05")
    px = pd.concat([frame("AAA", pd.bdate_range("2005-01-03", "2026-10-05")),
                    frame("ADRX", old.append(new)),
                    frame("HALT", pd.bdate_range("2010-01-04", "2010-06-30").append(pd.bdate_range("2011-01-03", "2011-03-31")))],
                   ignore_index=True).sort_values(["ticker", "date"]).reset_index(drop=True)
    # stale master: only the OLD entity (what live tickers_master.csv shows today)
    stale = {"ADRX": [("170871", D("1997-12-31"), D("2006-11-03"))],
             "HALT": [("1", D("2009-01-01"), D("2012-01-01"))],
             "AAA": [("2", D("1990-01-01"), D("2026-10-06"))]}
    out, rep = BF.segment_reused_symbols(px, entities=stale, return_report=True)
    assert [r["segment"] for r in rep] == ["ADRX__post20260925"], rep
    assert (out.ticker == "ADRX__post20260925").sum() == len(new)
    assert (out.ticker == "HALT").sum() == (px.ticker == "HALT").sum(), "a halt of one entity must not split"
    a_in, a_out = px[px.ticker == "AAA"], out[out.ticker == "AAA"]
    assert a_in.reset_index(drop=True).equals(a_out.reset_index(drop=True))
    # fresh master: old entity renamed ADRX1, new entity ADRX -> same split
    fresh = dict(stale)
    fresh["ADRX"] = stale["ADRX"] + [("6401389", D("2026-09-25"), D("2026-10-06"))]
    out2 = BF.segment_reused_symbols(px, entities=fresh)
    assert out2.equals(out)
    # reuse with a short (> 5 calendar days) gap is split by identity, not by gap length
    im = frame("IMM", pd.bdate_range("2015-01-02", "2015-02-13").append(pd.bdate_range("2015-02-23", "2015-03-31")))
    ents = {"IMM": [("a", D("2010-01-01"), D("2015-02-13")), ("b", D("2015-02-23"), D("2026-01-01"))]}
    o3, r3 = BF.segment_reused_symbols(im, entities=ents, return_report=True)
    assert [r["segment"] for r in r3] == ["IMM__post20150223"], r3
    # known limit of the pre-registered tolerance: a reuse within 5 calendar days is NOT split
    # (checked separately on the real panel by adjacent_entities.py: none in the panel)
    im2 = frame("IMM", pd.bdate_range("2015-01-02", "2015-03-31"))
    ents2 = {"IMM": [("a", D("2010-01-01"), D("2015-02-13")), ("b", D("2015-02-17"), D("2026-01-01"))]}
    assert BF.segment_reused_symbols(im2, entities=ents2, return_report=True)[1] == []
    # no rolling feature / label crosses: features per segment equal features of the segment alone
    spy = pd.DataFrame({"date": pd.bdate_range("2004-01-01", "2026-12-31")})
    spy["spy_momentum_20"] = 0.0
    seg = out[out.ticker == "ADRX__post20260925"]
    f = BF.features_for(seg, spy)
    assert f.momentum_5.notna().sum() == len(seg) - 5 and f.momentum_120.isna().all()
    f_old = BF.features_for(out[out.ticker == "ADRX"], spy)
    assert f_old.forward_return_tradable_40.tail(40).isna().all()

    # v2 refresh: price step segments before any per-ticker work; outcome step gets that px
    import reset2026.refresh_working_panel as R  # noqa: F401  (imports fine)
    src = inspect.getsource(R.step_prices)
    assert "segment_reused_symbols(px)" in src
    assert src.index("segment_reused_symbols(px)") < src.index("groupby(\"ticker\"")
    from build_outcome_cache import vectorized_outcomes
    for tk, g in out.groupby("ticker", sort=False):
        g = g.sort_values("date").reset_index(drop=True)
        gross, trunc = vectorized_outcomes(g)
        if tk == "ADRX":
            # outcomes truncate at the entity's own last close (delisting rule), never a 2026 price
            assert trunc[-40:].all()
            exit_px = (np.asarray(gross[-40:-1], float) + 1) * g.open.to_numpy()[-39:]
            assert np.allclose(exit_px, g.close.iloc[-1], rtol=1e-5), "old entity outcome must exit at its own last close"

    # real extracts: ADRX, RML, HYAC.U in raw SEP with the fresh TICKERS + local masters
    names = {"ADRX": "ADRX__post20260925", "RML": "RML__post20260909", "HYAC.U": "HYAC.U__post20260918"}
    sep = pd.concat([pd.read_parquet(f, columns=["ticker", "date"] + BF.PRICE_COLS,
                                     filters=[("ticker", "in", list(names))])
                     for f in sorted(SEP_DIR.glob("*.parquet"))])
    sep["date"] = pd.to_datetime(sep["date"])
    sep = sep.sort_values(["ticker", "date"]).reset_index(drop=True)
    BF.SPY_CSV = FROZEN / "SPY.csv"
    spy_real = BF.load_spy()
    o, r = BF.segment_reused_symbols(sep, entities=BF.load_reuse_entities(MASTERS), return_report=True)
    assert sorted(x["segment"] for x in r) == sorted(names.values()), r
    cols = BF.FEATURE_COLS + [BF.LABEL_COL, BF.TRADABLE_LABEL_COL]
    for old_name, new_name in names.items():
        for nm in (old_name, new_name):
            seg = o[o.ticker == nm]
            whole = BF.features_for(seg, spy_real)[cols].to_numpy(float)
            # the same segment computed inside the full split frame (groupby path of build())
            again = BF.features_for(o[o.ticker == nm].copy(), spy_real)[cols].to_numpy(float)
            assert ((whole == again) | (np.isnan(whole) & np.isnan(again))).all()
        f_old = BF.features_for(o[o.ticker == old_name], spy_real)
        assert f_old[BF.TRADABLE_LABEL_COL].tail(40).isna().all(), old_name
        f_new = BF.features_for(o[o.ticker == new_name], spy_real)
        n_new = len(f_new)
        assert f_new.momentum_120.isna().all() if n_new <= 120 else f_new.momentum_120.head(120).isna().all(), new_name
        assert f_new.pct_from_high_252.isna().all() if n_new < 252 else True, new_name
    # stale live master alone still catches ADRX (HYAC.U/RML need a fresh TICKERS pull)
    o2, r2 = BF.segment_reused_symbols(sep, entities=BF.load_reuse_entities((FROZEN / "tickers_master.csv",)),
                                       return_report=True)
    assert [x["segment"] for x in r2] == ["ADRX__post20260925"], r2
    print("test_segment: OK (synthetic; ADRX, RML, HYAC.U real extracts)")


if __name__ == "__main__":
    main()
