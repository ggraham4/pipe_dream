"""WO-58 plumbing smoke on SHUFFLED labels (permuted within date, demeaned, SPY = 0). Not a result.
Runs run_book.run_stage(1) end to end with 3 null draws and writes smoke_SHUFFLED_TEST_labels-shuffled.json."""
import numpy as np

import cb_core as B
import run_book as R

_orig = B.attach_labels


def shuffled(D, b, dates, stage):
    D = _orig(D, b, dates, stage)
    rng = np.random.default_rng(7)
    for dd in D:
        r = dd["ret"].copy()
        ok = np.isfinite(r)
        v = rng.permutation(r[ok])
        r[ok] = v - v.mean()
        dd["ret"] = r
        dd["spy"] = 0.0
    return D


B.attach_labels = shuffled
R.guard = lambda stage: None
R.N_DRAWS = 3
R.RESULT = {1: R.OUT / "smoke_SHUFFLED_TEST_labels-shuffled.json"}
R.run_stage(1)
