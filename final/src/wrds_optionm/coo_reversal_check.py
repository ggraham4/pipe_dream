"""WO-52 COO post-hoc DESCRIPTIVE checks on the exact Arm 1 pool (not judged; the pre-registered verdict stands).
Re-derives M independently, then: (a) drops truncated labels (delisting-path labels, cf. WO-51 terminal-treatment gap),
(b) residualises the signal rank on 21d (and 5d) trailing return. Output: final/out/thinliq_om/coo_reversal_check_DESCRIPTIVE.json"""
import json, sys
from pathlib import Path
import numpy as np, pandas as pd
HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
sys.argv = ["x"]
import run_thinliq_om as R  # noqa: E402  (repoints the harness paths)
import run_arm1 as A1  # noqa: E402
T = R.T
OUT = R.P.OUT
dates = [pd.Timestamp(d) for d in json.loads((OUT / "arm1_nullcal_SHUFFLED_TEST_thin_labels-shuffled.json").read_text())["dates"]]
m, _ = A1.load_frame("thin", dates)
o = pd.read_parquet(T.OUTCOME_V2, columns=["ticker", "date", "gross_return_40", "truncated"],
                    filters=[("date", "in", [d.to_pydatetime() for d in dates])])
o["ticker"] = o.ticker.astype(str); o["date"] = pd.to_datetime(o.date)
m = m.merge(o, on=["date", "ticker"], how="left")
lo = min(dates) - pd.Timedelta(days=45)
p = pd.read_parquet(T.PANEL_V2, columns=["ticker", "date", "close"], filters=[("date", ">=", str(lo.date())), ("date", "<=", str(max(dates).date()))])
p["date"] = pd.to_datetime(p.date); p["ticker"] = p.ticker.astype(str); p = p.sort_values(["ticker", "date"])
p["r21"] = p.groupby("ticker").close.pct_change(21); p["r5"] = p.groupby("ticker").close.pct_change(5)
m = m.merge(p[["ticker", "date", "r21", "r5"]], on=["ticker", "date"], how="left")
S = A1.SIGNAL

def Md(g, col):
    n = len(g)
    if n < A1.MIN_NAMES: return np.nan
    k = max(1, int(round(A1.DECILE * n)))
    g = g.sort_values([col, "ticker"], kind="mergesort")
    return g.gross_return_40.iloc[k:].mean() - g.gross_return_40.iloc[:k].mean()

def resid(g, cols):
    g = g.dropna(subset=cols).copy()
    if len(g) < A1.MIN_NAMES: g["res"] = np.nan; return g
    X = np.column_stack([np.ones(len(g))] + [g[c].rank(pct=True) for c in cols]); y = g[S].rank(pct=True).to_numpy()
    g["res"] = y - X @ np.linalg.lstsq(X, y, rcond=None)[0]; return g

base = m[m.gross_return_40.notna()]
res = {"note": "COO post-hoc DESCRIPTIVE on the exact Arm 1 thin pool (run_arm1.load_frame); not judged.",
       "n_dates": int(base.date.nunique()),
       "M_rederived_pct": 100 * base.groupby("date").apply(lambda g: Md(g, S)).mean(),
       "truncated_share_bottom_decile": float(base.groupby("date").apply(lambda g: g.sort_values([S, "ticker"]).truncated.iloc[:max(1, round(.1 * len(g)))].mean()).mean()),
       "truncated_share_rest": float(base.groupby("date").apply(lambda g: g.sort_values([S, "ticker"]).truncated.iloc[max(1, round(.1 * len(g))):].mean()).mean()),
       "M_drop_truncated_pct": 100 * base[base.truncated != True].groupby("date").apply(lambda g: Md(g, S)).mean(),  # noqa: E712
       "M_resid_r21_pct": 100 * base.groupby("date").apply(lambda g: Md(resid(g, ["r21"]), "res")).mean(),
       "M_resid_r5_r21_pct": 100 * base.groupby("date").apply(lambda g: Md(resid(g, ["r5", "r21"]), "res")).mean(),
       "spearman_signal_r21_median": float(base.groupby("date").apply(lambda g: g[S].corr(g.r21, method="spearman")).median())}
res = {k: (round(float(v), 4) if isinstance(v, (float, np.floating)) else v) for k, v in res.items()}
(OUT / "coo_reversal_check_DESCRIPTIVE.json").write_text(json.dumps(res, indent=1))
print(json.dumps(res, indent=1))
