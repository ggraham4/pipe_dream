"""WO-58 label-free check: cb_core.score_icw5 == ic_weighted_composite.compute_composite_ic_weighted(weights=W5),
on the full pool and on the screened pool, for every Stage-1 date. No forward return is read."""
import json

import numpy as np

import cb_core as B

b, pool, dates, info = B.load_book(1)
D, _ = B.prep(b)
err = 0.0
for dd in D:
    g = b.loc[dd["ix"]].reset_index(drop=True)
    for keep in (None, ~dd["bottom"]):
        fast = B.score_icw5(dd["F"], keep)
        gg = g if keep is None else g[keep].reset_index(drop=True)
        slow = B.ICW.compute_composite_ic_weighted(gg, weights=B.W5)["composite"].to_numpy(float)
        f = fast if keep is None else fast[keep]
        assert np.array_equal(np.isnan(f), np.isnan(slow))
        err = max(err, float(np.nanmax(np.abs(f - slow))))
out = {"dates": len(D), "max_abs_err_score_vs_compute_composite_ic_weighted": err, "pass": err < 1e-12}
(B.OUT / "check_score.json").write_text(json.dumps(out, indent=1))
print(out)
