

def cmd_live(args):
    """Rank cells on the LIVE construction, by profit.

    Round 18. This exists because Rounds 17b/17c ranked on sector-NEUTRAL
    performance, which deliberately discards factor exposure -- and Gabe has
    been explicit, more than once, that factor and sector bets are acceptable
    and that the objective is profit. Selecting on a criterion the owner has
    rejected is not conservatism, it is answering the wrong question.

    So: the ranking metric here is excess CAGR on the construction that is
    actually deployed (top-5, volq buckets, inverse-vol weights), against its
    own construction-matched null.

    The sector-neutral number is still computed and printed, but as a
    DIAGNOSTIC in its own column -- it is the only way to tell how much of a
    result is stock selection versus factor loading, which is worth knowing
    even when both are wanted. It does not drive the ranking.
    """
    tab = pd.read_parquet(OUTCOMES_PATH)
    tab["ticker"] = tab["ticker"].astype(str)
    spy = _spy()
    era = NOMINATE_ERA
    if args.era != "nominate":
        raise SystemExit(
            "Live evaluation is nomination-era only. The 2020-2026 hold-out was "
            "spent in Round 13 and was touched once more in error on 2026-09-12; "
            "it is not a clean test of anything and must not be used to choose.")
    smap = F.load_sector_map()
    base = dict(top_n=args.top_n, weighting=args.weighting, bucket=args.bucket)
    print(f"era = nominate {era}")
    print(f"LIVE construction: top_n={args.top_n}, {args.weighting}, "
          f"bucket={args.bucket}, {args.cost_bps:.0f}bp\n")

    cells = _load_cells(args.cells) if args.cells else None
    ids = [c.id for c in cells] if cells else sorted(
        p.stem for p in SC.CACHE_DIR.glob("*.parquet"))

    rows = []
    for cid in ids:
        if not SC.have(cid):
            continue
        meta = json.load(open(SC.meta_path(cid)))
        cfg = meta["config"]
        H = int(cfg["horizon"])
        if H != args.horizon:
            continue
        scores = pd.read_parquet(SC.cache_path(cid))
        prep = P.Prepared(scores, tab, H, None)
        spy_ret = P.spy_windows(spy, np.sort(scores["timepoint"].unique()), H)

        pw = P.simulate(prep, horizon=H, cost_bps=args.cost_bps, **base)
        m = P.score_run(pw, spy_ret, H, era=era)
        if m is None:
            continue

        # matched null on the SAME construction -- the only thing that separates
        # "this ranking earned it" from "this construction earned it"
        pct = np.nan
        if args.null_draws:
            nl = S.random_selection_null(
                prep, P.simulate, lambda p, s: P.score_run(p, s, H, era=era),
                spy_ret, n_draws=args.null_draws, seed=17,
                horizon=H, cost_bps=args.cost_bps, **base)
            pct = S.percentile_of(m["mult_ratio"], nl.get("_null_mults", []))

        # leave-one-year-out on the live construction
        d = pw[(pw.timepoint >= era[0]) & (pw.timepoint < era[1])]
        yrs = sorted(set(pd.to_datetime(d.timepoint).dt.year))
        lo = []
        for y in yrs:
            mm = P.score_run(pw[pd.to_datetime(pw.timepoint).dt.year != y],
                             spy_ret, H, era=era)
            if mm:
                lo.append(mm["excess_cagr"] * 100)
        worst = float(min(lo)) if lo else np.nan
        allpos = bool(all(v > 0 for v in lo)) if lo else False

        # DIAGNOSTIC ONLY: how much survives removing the sector bet
        sn = _sector_neutral_excess(prep, spy_ret, smap, H, era,
                                    per_sector=args.diag_per_sector,
                                    cost_bps=args.cost_bps)

        rows.append({"features": cfg["features"], "label": cfg["label"],
                     "model": cfg["model"], "n_cols": len(meta.get("feature_cols", [])),
                     "excess_cagr": m["excess_cagr"] * 100,
                     "mult_ratio": m["mult_ratio"],
                     "null_pctile": pct, "loyo_worst": worst,
                     "loyo_all_pos": allpos,
                     "diag_sector_neutral": sn, "cell_id": cid})
        print(f"  {cfg['features']:<26} {cfg['label']:<6} {cfg['model']:<8} "
              f"{m['excess_cagr']*100:>+7.2f}%/yr  pctile {pct:.3f}", flush=True)

    if not rows:
        raise SystemExit("no cells evaluated")
    res = pd.DataFrame(rows).sort_values("excess_cagr", ascending=False)

    print("\n" + "=" * 92)
    print("RANKED BY EXCESS CAGR ON THE LIVE CONSTRUCTION  (the objective)")
    print("=" * 92)
    cols = ["features", "label", "model", "n_cols", "excess_cagr", "mult_ratio",
            "null_pctile", "loyo_worst", "loyo_all_pos", "diag_sector_neutral"]
    print(res[cols].to_string(index=False, float_format=lambda v: f"{v:8.3f}"))

    print("\n  excess_cagr          THE RANKING METRIC -- profit on what is live.")
    print("  null_pctile          same construction, rankings shuffled. Below ~0.95")
    print("                       the construction earned it, not the model.")
    print("  loyo_worst           worst single-year-drop. A result that goes")
    print("                       negative on one drop has a fragile expectation.")
    print("  diag_sector_neutral  DIAGNOSTIC, not a gate: excess CAGR with the")
    print("                       sector bet removed. Says how much is stock")
    print("                       selection vs factor loading. Both are wanted,")
    print("                       but knowing the split is how we know what we")
    print("                       have and what will happen when factors turn.")

    best = res.iloc[0]
    print(f"\nbest on the objective: {best.features} / {best.label} / {best.model}")
    print(f"  {best.excess_cagr:+.2f}%/yr   null pctile {best.null_pctile:.3f}   "
          f"worst year-drop {best.loyo_worst:+.2f}%/yr")
    if len(res) > 1:
        d = best.excess_cagr - res.iloc[1].excess_cagr
        print(f"  margin over #2: {d:+.2f}%/yr")
    print(f"\n  Selected from {len(res)} cells. In-sample and biased upward; the")
    print(f"  2020-2026 hold-out is spent and cannot adjudicate this.")

    res.to_csv(SWEEP_DIR / "live_nominate.csv", index=False)
    print(f"\nwritten {SWEEP_DIR / 'live_nominate.csv'}")


def _sector_neutral_excess(prep, spy_ret, smap, H, era, per_sector=5,
                           cost_bps=15.0):
    """Excess CAGR with equal weight across sectors -- zero sector bet."""
    rows, prev = [], set()
    for tp in prep.tps:
        t = pd.Timestamp(tp)
        if not (pd.Timestamp(era[0]) <= t < pd.Timestamp(era[1])):
            continue
        d = prep.g.get(np.datetime64(tp))
        if d is None:
            continue
        labs = np.array([F._base_ticker(x) for x in d["ticker"]])
        labs = np.array([smap.get(x, "") for x in labs])
        ok = np.isfinite(d["ret"]) & d["tradable"] & np.isfinite(d["score"])
        picks = []
        for s in sorted(set(labs[ok]) - {""}):
            m = np.flatnonzero(ok & (labs == s))
            if len(m) < per_sector * 2:
                continue
            picks.append(m[np.argsort(-d["score"][m])[:per_sector]])
        if len(picks) < 6:
            continue
        w = np.zeros(len(d["score"]))
        for g in picks:
            w[g] = 1.0 / (len(picks) * len(g))
        idx = np.flatnonzero(w > 0)
        gr = float((w[idx] * d["ret"][idx]).sum())
        cur = set(d["ticker"][idx])
        turn = 1.0 - (len(cur & prev) / max(len(cur), 1))
        prev = cur
        rows.append({"sleeve": 0, "timepoint": t, "n": len(idx), "gross": gr,
                     "net": gr - turn * cost_bps / 1e4, "exposure": 1.0,
                     "turnover": turn})
    if not rows:
        return np.nan
    m = P.score_run(pd.DataFrame(rows), spy_ret, H, era=era)
    return m["excess_cagr"] * 100 if m else np.nan
