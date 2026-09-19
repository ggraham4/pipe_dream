"""
At what resolution is the deployed model's bet actually placed?

    python3 screen_sector_hierarchy.py

Round 13 neutralised on 11 sectors and found essentially the whole edge
disappeared. Gabe's question (2026-09-16): is the bet finer than "sector"?
Healthcare is not one business -- DNA services and medical equipment are
different things, and if the model is really betting at that resolution then
"sector bet" understates what it knows.

--------------------------------------------------------------------------
THE DESIGN
--------------------------------------------------------------------------
For each taxonomy level, residualise the forward return on size + vol + group
dummies and re-measure the model. Two statistics, both of which matter:

    IC                 full cross-section rank correlation
    decile_volq_excess top 10% within each volatility quintile -- the
                       selection rule the strategy actually uses

Then the same against a MATCHED RANDOM PARTITION: identical group count,
identical size distribution, zero industry content. The random control has the
same degrees of freedom, so anything the real taxonomy removes BEYOND it is
industry information rather than arithmetic.

Reading the output: the quantity of interest is `real - random` at each level.
If it grows from sector to industry, the bet is finer than Round 13 measured
and there is structure to exploit. If it is flat, the bet is coarse and the
extra dummies are just eating degrees of freedom. If the RAW numbers fall with
finer levels but `real - random` does not, that is the overfitting artifact
this control exists to catch, and it would have been read as a finding.

--------------------------------------------------------------------------
NOMINATION ERA ONLY
--------------------------------------------------------------------------
2007-2019. This is a diagnostic of a deployed model, not a search over
configurations, but it is still a measurement and the hold-out stays shut.
"""
import sys
from pathlib import Path

import numpy as np
import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parent))
from features import OUT_DIR                          # noqa: E402
from sweep import portfolio as P                      # noqa: E402
from sweep import factors as F                        # noqa: E402
from sweep import taxonomy as T                       # noqa: E402
from sweep import _num                                # noqa: E402

SCORES = OUT_DIR / "sweep" / "scores"
CELL = "price_fund_h40_q75_trd_xgb_d3e01r100_expanding_cap500k_pit_s40"
ERA = ("2007-01-01", "2020-01-01")
H = 40
MIN_NAMES = 40
SEEDS = (0, 1, 2)


def stats_for(prep, smap, era):
    """(IC, decile_volq_excess) per window, with the target residualised on
    size + vol + the supplied grouping. smap=None means no neutralisation."""
    ics, dec = [], []
    for tp, d in prep.g.items():
        t = pd.Timestamp(tp)
        if not (pd.Timestamp(era[0]) <= t < pd.Timestamp(era[1])):
            continue
        ok = np.isfinite(d["ret"]) & d["tradable"] & np.isfinite(d["score"])
        if ok.sum() < MIN_NAMES * 2:
            continue
        y, sc = d["ret"][ok], d["score"][ok]
        if smap is not None:
            D, _ = F.build_design(d["ticker"][ok], d["cap"][ok], d["vol"][ok],
                                  spec="size_vol_sector", sector_map=smap)
            y = F.residualize(y, D)
        g = np.isfinite(y)
        if g.sum() < MIN_NAMES * 2:
            continue
        y, sc2, vol = y[g], sc[g], d["vol"][ok][g]
        ics.append(_num.spearman(sc2, y))
        b = P._bucket_idx(vol, 5)
        sel = []
        for bi in range(5):
            m = np.flatnonzero(b == bi)
            if len(m) < 10:
                continue
            k = max(1, int(0.10 * len(m)))
            sel.append(m[np.argpartition(-sc2[m], k - 1)[:k]])
        if sel:
            idx = np.concatenate(sel)
            dec.append(float(y[idx].mean()) - float(y.mean()))
    return np.asarray(ics), np.asarray(dec)


def t_of(v):
    v = np.asarray(v, np.float64); v = v[np.isfinite(v)]
    if len(v) < 3 or v.std(ddof=1) == 0:
        return np.nan, np.nan
    return float(v.mean()), float(v.mean() / (v.std(ddof=1) / np.sqrt(len(v))))


def main():
    tab = pd.read_parquet(OUT_DIR / "sweep" / "outcomes.parquet")
    tab["ticker"] = tab["ticker"].astype(str)
    sc = pd.read_parquet(SCORES / f"{CELL}.parquet")
    prep = P.Prepared(sc, tab, H, None)

    uni = sorted({str(x) for x in sc["ticker"].unique()})
    print("group-size profile on the scored universe:")
    print(T.describe(uni).to_string(index=False,
                                    float_format=lambda v: f"{v:8.3f}"))
    print("\n  usable=False levels are excluded: median group size 3, and a")
    print("  quarter of names fall into groups too thin for a dummy, so they")
    print("  are not comparable with levels that keep the whole cross-section.\n")

    base_ic, base_dec = stats_for(prep, None, ERA)
    m_ic, t_ic = t_of(base_ic)
    m_dc, t_dc = t_of(base_dec)
    print("=" * 94)
    print(f"DEPLOYED MODEL, nomination era, {len(base_ic)} windows")
    print("=" * 94)
    print(f"{'level':<16}{'groups':>7}{'IC':>9}{'t':>7}{'IC-rand':>10}"
          f"{'decile pp':>11}{'t':>7}{'dec-rand':>10}")
    print(f"{'(none)':<16}{'-':>7}{m_ic:>+9.4f}{t_ic:>+7.2f}{'-':>10}"
          f"{m_dc*100:>+11.3f}{t_dc:>+7.2f}{'-':>10}")

    rows = []
    for lvl in T.LEVELS:
        real = T.load(lvl)
        ic_r, dec_r = stats_for(prep, real, ERA)
        # average the control over seeds: one random partition is itself a draw
        ic_c, dec_c = [], []
        for s in SEEDS:
            a, b = stats_for(prep, T.matched_random(real, seed=s), ERA)
            ic_c.append(a); dec_c.append(b)
        ic_c = np.nanmean(np.vstack(ic_c), axis=0)
        dec_c = np.nanmean(np.vstack(dec_c), axis=0)

        n_g = len(set(real.get(F._base_ticker(u), "") for u in uni) - {""})
        mi, ti = t_of(ic_r); md, td = t_of(dec_r)
        di, _ = t_of(ic_r - ic_c[:len(ic_r)])
        dd, _ = t_of(dec_r - dec_c[:len(dec_r)])
        print(f"{lvl:<16}{n_g:>7}{mi:>+9.4f}{ti:>+7.2f}{di:>+10.4f}"
              f"{md*100:>+11.3f}{td:>+7.2f}{dd*100:>+10.3f}")
        rows.append({"level": lvl, "groups": n_g, "ic": mi, "t_ic": ti,
                     "ic_minus_random": di, "decile_pp": md * 100,
                     "t_decile": td, "decile_minus_random_pp": dd * 100})

    # Does a finer level explain MORE than sector? Paired by window, which is
    # the only way to ask it: the two neutralisations see the same 82 windows,
    # so differencing inside a window removes the market variation that
    # dominates both series and would otherwise swamp the comparison.
    print("\n" + "=" * 94)
    print("IS FINER ACTUALLY FINER?  paired by window, vs the sector (11-group) level")
    print("=" * 94)
    sec_ic, sec_dec = stats_for(prep, T.load("sector"), ERA)
    for lvl in T.LEVELS[1:]:
        r_ic, r_dec = stats_for(prep, T.load(lvl), ERA)
        n = min(len(sec_dec), len(r_dec))
        m, t = t_of(sec_dec[:n] - r_dec[:n])
        mi, ti = t_of(sec_ic[:n] - r_ic[:n])
        print(f"  {lvl:<14} decile: sector leaves {m*100:+.3f} pp MORE than "
              f"{lvl} does, t {t:+.2f}   |   IC: {mi:+.4f}, t {ti:+.2f}")
    print("\n  A positive decile number means the finer level explains more of")
    print("  the edge than sector does -- the bet is finer than Round 13 measured.")

    res = pd.DataFrame(rows)
    out = OUT_DIR / "sweep" / "sector_hierarchy.csv"
    res.to_csv(out, index=False)
    print("\n  IC-rand and dec-rand are the columns that carry the answer: the")
    print("  real taxonomy MINUS a random partition with the same group count")
    print("  and sizes. A raw number that falls with finer levels while these")
    print("  stay flat is degrees of freedom, not industry structure.")
    print("\n  More negative = that level explains MORE of the model's edge.")
    print(f"\nwritten {out}")


if __name__ == "__main__":
    main()
