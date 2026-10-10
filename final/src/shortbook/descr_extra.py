"""WO-60 descriptive extras (not decisive): M with the post-SPAC thin-print names (ORGO, PHUN; CRSP-
confirmed prints on a few thousand shares) removed from the cap2000 book, and the 2011 Markit mean fee
of the cap2000 bottom decile used as a flat fee instead of the B1 tiers. Writes descr_extra.json."""
import json
import sys
from pathlib import Path

import numpy as np

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
import engine as E  # noqa: E402
import sb_common as K  # noqa: E402

E.load("cap2000")
R = E.G["R"]
base = np.load(K.OUT_BIG / "pick_base_cap2000.npy")
out = {}
thin = R["ticker"].isin(["ORGO", "PHUN"]).to_numpy()
out["M_ex_ORGO_PHUN"] = E.stats(E.chains(E.per_date(base & ~thin), "H1"))["M"]
mk = json.loads((K.OUT / "markit_2011_fees.json").read_text())["cap2000_bottom_decile"]["mean"]
pdb = E.per_date(base)
out["M_flat_markit2011_bottom_decile_mean_fee"] = {"fee": mk, "M": E.stats(E.chains({d: (v[0], mk) + v[2:] for d, v in pdb.items()}, "H1"))["M"]}
out["M_pre_2011_10"] = None
ch = E.chains(pdb, "H1")
post = [c["R"][c["date"] >= np.datetime64("2011-10-01")].mean() * K.ANN for c in ch]
pre = [c["R"][c["date"] < np.datetime64("2011-10-01")].mean() * K.ANN for c in ch]
out["M_pre_2011_10"], out["M_post_2011_10"] = float(np.mean(pre)), float(np.mean(post))
(K.OUT / "descr_extra.json").write_text(json.dumps(out, indent=1))
print(out)
