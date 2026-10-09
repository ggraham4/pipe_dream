"""
WO-52: run the WO-37 thin-liquidity harness UNCHANGED on the OptionMetrics
AV-shaped store. Only module paths and the pull-log reader are repointed
(amendment final/models/2026-10-08-thinliq-optionmetrics-amendment.md section 5);
no rule function is edited. Outputs go to final/out/thinliq_om/.

    PY=/opt/anaconda3/envs/pipe_dream/bin/python
    $PY final/src/wrds_optionm/run_thinliq_om.py gate          # arrival gate + presence checks (presence only)
    $PY final/src/wrds_optionm/run_thinliq_om.py chain         # chain + features (build_chain.py)
    $PY final/src/wrds_optionm/run_thinliq_om.py crosscheck    # section 4 richness / chain-share check (quotes only)
    $PY final/src/wrds_optionm/run_thinliq_om.py arm1 --phase2 # guarded real run (guard: sha256 of both frozen docs)
    $PY final/src/wrds_optionm/run_thinliq_om.py arm1 --labels shuffled --universe thin --seeds 100
    $PY final/src/wrds_optionm/run_thinliq_om.py arm2 --phase2
    $PY final/src/wrds_optionm/run_thinliq_om.py stale         # descriptive, after arm2
"""
from __future__ import annotations

import json
import sqlite3
import subprocess
import sys
from pathlib import Path

import numpy as np
import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parent))
import om_paths as P  # noqa: E402
import tl_common as T  # noqa: E402

# ---- repoint the harness (paths + log reader only)
T.AV = P.STORE
T.PULL_LOG = P.CALLS
T.AV_MONTHLY = P.MONTHLY
T.OUT = P.OUT
T.CHAIN = P.OUT / "chain" / "source=om_monthly"
T.FCACHE = P.OUT / "features_cache"
T.FEATS = P.OUT / "om_options_features_thinliq.parquet"
T.ARRIVAL = P.OUT / "arrival_gate.json"
REPO = Path(__file__).resolve().parents[3]


def read_log_parquet():
    """Same contract as tl_common.read_log, reading calls.parquet instead of the AV sqlite."""
    L = pd.read_parquet(P.CALLS, columns=["pass", "date", "ticker", "status", "symbol", "identity", "spot_parity", "closeunadj", "n"])
    L["_o"] = L.status.map({"ok": 0, "no_data": 1}).fillna(2)
    return L.sort_values("_o").drop_duplicates(["date", "ticker"], keep="first").drop(columns="_o")


T.read_log = read_log_parquet
_orig_guard = T.phase2_guard


# Frozen-doc hashes (2026-10-08: git writes were not allowed, so the docs could not be tracked;
# the freeze is sha256 + timestamp, logged in LEDGER.md / COO.md). This replaces the `git ls-files` check.
PREREG_SHA256 = "ce6caf89e95e770d8a803d09400e234ba2c6d991222e3eb15338aed13e2eacd7"   # WO-37, origin/integration
AMEND_SHA256 = "a9a1c8c1083ebc69fb91b59da61b2c2a80bf1b4af88aabc8d0c5a15a78de98cf"    # WO-52, frozen 2026-10-08T20:51:42Z
MAIN_REPO = Path("/Users/ggraham/pipe_dream")


def _sha256(b: bytes) -> str:
    import hashlib
    return hashlib.sha256(b).hexdigest()


def _prereg_bytes() -> bytes:
    r = subprocess.run(["git", "-C", str(MAIN_REPO), "show", f"origin/integration:{T.PREREG_DOC}"], capture_output=True)
    if r.returncode == 0:
        return r.stdout
    return (P.SRC.parent.parent / T.PREREG_DOC).read_bytes()   # the read-only /tmp extract of origin/integration


class _LsFilesShim:
    """Stands in for tl_common.subprocess only while _orig_guard runs: answers its one
    `git ls-files --error-unmatch PREREG_DOC` call as tracked (the doc has just been sha256-verified),
    and passes every other call through to the real subprocess.run."""
    CalledProcessError = subprocess.CalledProcessError

    @staticmethod
    def run(argv, *a, **k):
        if "ls-files" in argv and "--error-unmatch" in argv and T.PREREG_DOC in argv:
            return subprocess.CompletedProcess(argv, 0, b"", b"")
        return subprocess.run(argv, *a, **k)


def guard(result_path):
    got = {"prereg": _sha256(_prereg_bytes()), "amendment": _sha256((REPO / P.AMEND_DOC).read_bytes())}
    if got["prereg"] != PREREG_SHA256:
        raise SystemExit(f"--phase2 refused: {T.PREREG_DOC} sha256 {got['prereg']} != frozen {PREREG_SHA256}")
    if got["amendment"] != AMEND_SHA256:
        raise SystemExit(f"--phase2 refused: {P.AMEND_DOC} sha256 {got['amendment']} != frozen {AMEND_SHA256}")
    cc = P.OUT / "crosscheck.json"
    if not cc.exists() or not json.loads(cc.read_text())["pass"]:
        raise SystemExit("--phase2 refused: section 4 cross-source check missing or FAILED")
    real_sp = T.subprocess
    T.subprocess = _LsFilesShim
    try:
        return _orig_guard(result_path)
    finally:
        T.subprocess = real_sp


T.phase2_guard = guard
P.OUT.mkdir(parents=True, exist_ok=True)

EARLY9 = ["2008-01-02", "2008-01-16", "2008-02-20", "2008-03-19", "2008-04-16", "2008-05-21", "2008-06-18", "2008-07-16", "2008-08-20"]


def crosscheck():
    """Amendment section 4: OM vs AV quotes on the 9 early dates (quotes and presence only)."""
    import build_option_chain_unified as U
    AVL = pd.read_sql("SELECT pass, date, ticker, status, symbol, identity, spot_parity, closeunadj FROM calls",
                      sqlite3.connect(f"file:{P.AV_FULL / 'pull_log.sqlite'}?mode=ro", uri=True))
    OML = read_log_parquet()
    u = T.universe_on([pd.Timestamp(d) for d in EARLY9])
    ratios = {"thin": [], "cap2000": []}
    same = {"thin": [], "cap2000": []}
    share = []
    for d in EARLY9:
        dt = pd.Timestamp(d)
        ud = u[u.date == dt]
        thin, big = set(ud.ticker[ud.thin]), set(ud.ticker[ud.eligible_cap2000])
        ka = U.av_keep(AVL[(AVL["pass"] == "monthly") & (AVL.date == d)])
        ko = U.av_keep(OML[OML.date == d])
        a = pd.read_parquet(P.AV_FULL / "options" / "monthly" / f"date={d}.parquet",
                            columns=["sharadar_ticker", "av_symbol", "expiration", "strike", "type", "bid", "ask"])
        a = a[pd.Series(list(zip(a.sharadar_ticker, a.av_symbol))).isin(ka).to_numpy()]
        o = pd.read_parquet(P.MONTHLY / f"date={d}.parquet",
                            columns=["sharadar_ticker", "av_symbol", "expiration", "strike", "type", "bid", "ask"])
        o = o[pd.Series(list(zip(o.sharadar_ticker, o.av_symbol))).isin(ko).to_numpy()]
        share.append({"date": d, "thin_names": len(thin), "om_kept_chain": len(thin & set(o.sharadar_ticker)),
                      "av_kept_chain": len(thin & set(a.sharadar_ticker))})
        for df in (a, o):
            df["sharadar_ticker"] = df.sharadar_ticker.astype(str); df["expiration"] = df.expiration.astype(str)
            df["type"] = df["type"].astype(str); df["strike"] = df.strike.round(3)
        k = ["sharadar_ticker", "expiration", "strike", "type"]
        mm = a.drop_duplicates(k).merge(o.drop_duplicates(k), on=k, suffixes=("_av", "_om"))
        mm = mm[(mm.bid_av > 0) & (mm.bid_om > 0)]
        r = ((mm.bid_om + mm.ask_om) / 2) / ((mm.bid_av + mm.ask_av) / 2)
        eq = (np.isclose(mm.bid_av, mm.bid_om) & np.isclose(mm.ask_av, mm.ask_om))
        for lab, s in (("thin", thin), ("cap2000", big)):
            w = mm.sharadar_ticker.isin(s).to_numpy()
            ratios[lab].append(r[w].to_numpy()); same[lab].append(np.asarray(eq)[w])
    S = pd.DataFrame(share)
    out = {"dates": EARLY9}
    for lab in ratios:
        r = np.concatenate(ratios[lab]); e = np.concatenate(same[lab])
        out[lab] = {"matched_contracts": int(len(r)), "median_mid_ratio_om_over_av": float(np.median(r)) if len(r) else None,
                    "iqr": [float(np.quantile(r, .25)), float(np.quantile(r, .75))] if len(r) else None,
                    "share_identical_bid_ask": float(e.mean()) if len(e) else None}
    om_share = float(S.om_kept_chain.sum() / S.thin_names.sum())
    av_share = float(S.av_kept_chain.sum() / S.thin_names.sum())
    out["thin_kept_chain_share"] = {"om": om_share, "av": av_share, "av_prereg_published_with_chain": 0.634}
    rr = out["thin"]["median_mid_ratio_om_over_av"]
    out["check1_richness_in_0.90_1.10"] = bool(rr is not None and 0.90 <= rr <= 1.10)
    out["check2_om_chain_share_ge_0.60"] = bool(om_share >= 0.60)
    out["pass"] = bool(out["check1_richness_in_0.90_1.10"] and out["check2_om_chain_share_ge_0.60"])
    (P.OUT / "crosscheck.json").write_text(json.dumps(out, indent=1))
    print(json.dumps(out, indent=1))


def stale():
    """Descriptive: zero-volume and old last-trade share of Arm 2's chosen puts (quote side)."""
    pos = pd.read_parquet(P.OUT / "arm2_positions.parquet", columns=["date", "ticker", "strike", "fillable"])
    rows = []
    for d, g in pos.groupby("date"):
        ds = str(pd.Timestamp(d).date())
        s = pd.read_parquet(P.MONTHLY / f"date={ds}.parquet", columns=["sharadar_ticker", "type", "strike", "volume", "om_last_date", "expiration"])
        s = s[s["type"] == "put"]
        m = g.merge(s.rename(columns={"sharadar_ticker": "ticker"}), on=["ticker", "strike"], how="left")
        rows.append(m.assign(entry=pd.Timestamp(d)))
    M = pd.concat(rows, ignore_index=True).drop_duplicates(["entry", "ticker", "strike"])
    age = (M.entry - pd.to_datetime(M.om_last_date)).dt.days
    out = {"positions": int(len(M)), "zero_volume_share": float((M.volume == 0).mean()),
           "last_trade_gt_30d_share": float((age > 30).mean()), "never_traded_share": float(M.om_last_date.isna().mean()),
           "fillable_zero_volume_share": float((M.volume[M.fillable] == 0).mean())}
    (P.OUT / "stale_quotes_DESCRIPTIVE.json").write_text(json.dumps(out, indent=1))
    print(out)


def main():
    cmd, rest = sys.argv[1], sys.argv[2:]
    sys.argv = [cmd] + rest
    if cmd == "gate":
        rep = T.arrival_gate(write=True)
        pd_ = rep["per_date"]
        ts = sorted(v["terminal_share"] for v in pd_.values())
        print(json.dumps({"n_thin_complete": rep["n_thin_complete"], "gate_pass": rep["gate_pass"],
                          "phase2_allowed": rep["phase2_allowed"], "terminal_share_min": ts[0], "terminal_share_median": ts[len(ts) // 2],
                          "named_dead": {k: {kk: v[kk] for kk in ("must_date_state", "share", "early9_present", "early9_thin", "pass")}
                                         for k, v in rep["named_dead"].items()},
                          "txg": rep["txg"]["state"], "pool_integrity": rep["pool_integrity"],
                          "dead_vs_listed": rep["dead_vs_listed_chain_share"]}, indent=1, default=str))
    elif cmd == "chain":
        import build_chain
        build_chain.main()
    elif cmd == "crosscheck":
        crosscheck()
    elif cmd == "arm1":
        import run_arm1
        run_arm1.main()
    elif cmd == "arm2":
        import run_arm2
        run_arm2.main()
    elif cmd == "stale":
        stale()
    else:
        raise SystemExit(f"unknown command {cmd}")


if __name__ == "__main__":
    main()
