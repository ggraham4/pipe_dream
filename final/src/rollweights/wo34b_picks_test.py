"""WO-34b picks test (hard asserts). r252_forward.write_picks with the R252
weights replaced by the live icw9_seas weights must equal what the live
Theoretical scorer (current_signal_composite.main) writes for the same panel
date: same columns, tickers, order and every value, bit for bit; meta keys a
superset in the same order. Everything is written to a temp directory, never
to the main checkout's final/out.

    python final/src/rollweights/wo34b_picks_test.py
"""
import json
import sys
import tempfile
from pathlib import Path

import pandas as pd

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
sys.path.insert(0, str(HERE.parent))
import r252_forward as RF                      # noqa: E402
import current_signal_composite as CSC         # noqa: E402

LIVE_OUT = Path("/Users/ggraham/pipe_dream/final/out")
WATCH = ("current_signal_r252.csv", "current_signal_r252_meta.json",
         "current_signal_composite.csv", "current_signal_composite_meta.json")


def frames_equal(a, b):
    assert list(a.columns) == list(b.columns), (list(a.columns), list(b.columns))
    assert len(a) == len(b), (len(a), len(b))
    for c in a.columns:
        x, y = a[c], b[c]
        same = (x == y) | (x.isna() & y.isna())
        assert same.all(), f"column {c}: {int((~same).sum())} rows differ"


def snap():
    return {n: ((LIVE_OUT / n).stat().st_size, (LIVE_OUT / n).stat().st_mtime) if (LIVE_OUT / n).exists() else None
            for n in WATCH}


def main():
    res = {}
    before = snap()
    with tempfile.TemporaryDirectory() as ta, tempfile.TemporaryDirectory() as tb, tempfile.TemporaryDirectory() as tc:
        CSC.main(["--out-dir", ta])
        th = pd.read_csv(Path(ta) / CSC.OUT_CSV.name, float_precision="round_trip")
        thm = json.loads((Path(ta) / CSC.OUT_META.name).read_text())
        # (1) R252 weights := live icw9_seas weights -> identical picks file
        RF.write_picks(weights=dict(CSC.WEIGHTS), out_dir=tb)
        pk = pd.read_csv(Path(tb) / RF.PICKS_CSV.name, float_precision="round_trip")
        pkm = json.loads((Path(tb) / RF.PICKS_META.name).read_text())
        assert (Path(tb) / RF.PICKS_CSV.name).read_bytes() == (Path(ta) / CSC.OUT_CSV.name).read_bytes(), \
            "picks CSV bytes != Theoretical CSV bytes"
        frames_equal(th, pk)
        assert list(pk["ticker"]) == list(th["ticker"]) and (pk["weight"] == th["weight"]).all()
        assert list(pkm)[:len(thm)] == list(thm), "meta keys/order differ from the Theoretical meta"
        assert list(pkm)[len(thm):] == ["r252"]
        for k in ("as_of_date", "tier", "n_eligible_universe", "n_picks", "n_factors", "construction",
                  "factor_signs", "factor_weights", "seas", "picks_overlap_vs_icw8", "panel_source",
                  "universe_rule", "role"):
            assert pkm[k] == thm[k], f"meta[{k}] differs"
        assert pkm["r252"]["picks_overlap_vs_icw9_seas"]["shared"] == thm["n_picks"]
        res["equal_with_icw9_seas_weights"] = {"as_of_date": thm["as_of_date"], "n_picks": thm["n_picks"],
                                               "csv_bytes_identical": True, "meta_shared_keys_equal": True}
        # (2) the live file on disk, when it is for the same panel date and model
        live_m = json.loads((LIVE_OUT / CSC.OUT_META.name).read_text())
        if live_m["as_of_date"] == thm["as_of_date"] and live_m["model_version"] == thm["model_version"]:
            lv = pd.read_csv(LIVE_OUT / CSC.OUT_CSV.name, float_precision="round_trip")
            frames_equal(lv, pk)
            res["equal_to_live_file_on_disk"] = True
        else:
            res["equal_to_live_file_on_disk"] = (f"not compared: live file as_of {live_m['as_of_date']} "
                                                 f"vs panel latest {thm['as_of_date']}")
        # (3) the real R252 picks: same schema, date, universe and position count
        _r, rm = RF.write_picks(out_dir=tc)
        rr = pd.read_csv(Path(tc) / RF.PICKS_CSV.name, float_precision="round_trip")
        assert list(rr.columns) == list(th.columns) == RF.PICKS_COLS
        assert [str(t) for t in rr.dtypes] == [str(t) for t in th.dtypes]
        assert rm["as_of_date"] == thm["as_of_date"] and rm["n_eligible_universe"] == thm["n_eligible_universe"]
        assert rm["n_picks"] == thm["n_picks"] == len(rr), (rm["n_picks"], thm["n_picks"])
        assert abs(rr["weight"].sum() - 1) < 1e-9 and rr["weight"].is_monotonic_decreasing
        assert list(rm)[:len(thm)] == list(thm)
        res["r252_picks"] = {"as_of_date": rm["as_of_date"], "n_picks": rm["n_picks"],
                             "refit_idx": rm["r252"]["refit_idx"], "refit_date": rm["r252"]["refit_date"],
                             "refit_in_weight_path": rm["r252"]["refit_in_weight_path"],
                             "factor_weights": rm["factor_weights"],
                             "overlap_vs_icw9_seas": rm["r252"]["picks_overlap_vs_icw9_seas"]}
    assert snap() == before, "the test touched a picks file in the main checkout's final/out"
    res["main_out_picks_files_untouched"] = True
    res["pass"] = True
    dst = HERE.parents[1] / "out" / "rollweights" / "wo34b_picks_test.json"
    dst.write_text(json.dumps(res, indent=1, default=str))
    print(json.dumps(res, indent=1, default=str))
    print(f"PASS -> {dst}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
