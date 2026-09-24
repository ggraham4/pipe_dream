"""
WO-6: build the survivorship-safe down-cap feature grid (composite_panel_v2)
by running the EXISTING builders unchanged over a wider ticker set.

Each step imports the original builder module, repoints its module-level
input/output paths to new *_downcap_v2 files, and calls that module's own
main()/build(). No formula is restated here, so a difference from the old
grid can only come from the ticker set. Every step refuses to run if its
output already exists -- nothing existing is ever overwritten.

Ticker set: union of the old grid (pit_universe.parquet, 4,011) and every
ticker in downcap_universe_v2.parquet (9,266), SPACs included (excluded at
analysis time).

    python3 build_downcap_grid_v2.py --all          # every step, one subprocess each
    python3 build_downcap_grid_v2.py --step prices  # one step

Steps, in order:
    tickers      write the ticker list (+ the list of tickers needing OHLC CSVs)
    prices       build_features_sharadar.build()          -> features_sharadar_pit_downcap_v2
    fundamentals build_features_fundamentals_sharadar     -> features_with_fundamentals_sharadar_pit_downcap_v2
    issuance     build_issuance_features                  -> features_with_issuance_..._downcap_v2
    short        build_short_interest_features            -> features_with_short_interest_..._downcap_v2
    events       build_event_features                     -> features_with_events_..._downcap_v2
    quality      reset2026/quality_factors                -> reset2026/quality_factors_v2
    panel        reset2026/build_panel (v2 flags) + v1 flags as eligible_cap*_v1
                                                          -> reset2026/composite_panel_v2
    beta         reset2026/build_beta_feature             -> reset2026/beta_feature_v2
    ohlc         export_sharadar_ohlc (added tickers only) -> scripts/td_data_sharadar_downcap_v2/
    outcome      reset2026/build_outcome_cache over td_data_sharadar + the new dir
                                                          -> reset2026/outcome_cache_v2
"""
import argparse
import subprocess
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent          # .../final/src/reset2026
SRC = HERE.parent                               # .../final/src
sys.path.insert(0, str(SRC))
sys.path.insert(0, str(HERE))

MAIN = Path("/Users/ggraham/pipe_dream/final")

# features.PROJECT_ROOT is derived from __file__, so when this runs from a
# worktree every builder's data path would point at the worktree's (empty)
# final/data. Repoint the root at the main checkout BEFORE any builder is
# imported; each builder then derives its constants from it exactly as it
# does when run from the main checkout.
import features as _features  # noqa: E402
_features.PROJECT_ROOT = MAIN
_features.DATA_DIR = MAIN / "scripts" / "td_data_local"
_features.OUT_DIR = MAIN / "out"
_features.MODELS_DIR = MAIN / "out" / "models"

OUT = MAIN / "out"
R26 = OUT / "reset2026"
V2DIR = R26 / "downcap_v2"
SH = MAIN / "data" / "sharadar"

TICKERS = V2DIR / "grid_tickers_v2.parquet"
OHLC_TICKERS = V2DIR / "ohlc_added_tickers_v2.parquet"
F_PRICE = OUT / "features_sharadar_pit_downcap_v2.parquet"
F_FUND = OUT / "features_with_fundamentals_sharadar_pit_downcap_v2.parquet"
F_ISS = OUT / "features_with_issuance_sharadar_pit_downcap_v2.parquet"
F_SI = OUT / "features_with_short_interest_sharadar_pit_downcap_v2.parquet"
F_EV = OUT / "features_with_events_sharadar_pit_downcap_v2.parquet"
Q_V2 = R26 / "quality_factors_v2.parquet"
PANEL_TMP = V2DIR / "composite_panel_v2_v2flags_only.parquet"
PANEL_V2 = R26 / "composite_panel_v2.parquet"
BETA_V2 = R26 / "beta_feature_v2.parquet"
OHLC_OLD = MAIN / "scripts" / "td_data_sharadar"
OHLC_NEW = MAIN / "scripts" / "td_data_sharadar_downcap_v2"
OUTCOME_V2 = R26 / "outcome_cache_v2.parquet"

STEPS = ["tickers", "prices", "fundamentals", "issuance", "short", "events",
         "quality", "panel", "beta", "ohlc", "outcome"]


def refuse_if_exists(*paths):
    for p in paths:
        if Path(p).exists():
            raise SystemExit(f"REFUSING: {p} already exists (never overwrite)")


def step_tickers():
    import pandas as pd
    import pyarrow.parquet as pq
    refuse_if_exists(TICKERS, OHLC_TICKERS)
    V2DIR.mkdir(parents=True, exist_ok=True)
    old = set(pd.read_parquet(SH / "pit_universe.parquet", columns=["ticker"])["ticker"].astype(str))
    v2 = set(pq.read_table(SH / "downcap_universe_v2.parquet", columns=["ticker"])
             .column("ticker").unique().to_pylist())
    allt = sorted(old | v2)
    pd.DataFrame({"ticker": allt}).to_parquet(TICKERS, index=False)
    have = {p.stem for p in OHLC_OLD.glob("*.csv")}
    add = sorted(set(allt) - have)
    pd.DataFrame({"ticker": add}).to_parquet(OHLC_TICKERS, index=False)
    print(f"old grid {len(old):,}, v2 {len(v2):,}, union {len(allt):,}; "
          f"OHLC CSVs to add {len(add):,} (existing {len(have):,})")


def step_prices():
    import build_features_sharadar as m
    refuse_if_exists(F_PRICE)
    m.UNIVERSE, m.OUT = TICKERS, F_PRICE
    m.build()


def step_fundamentals():
    import build_features_fundamentals_sharadar as m
    refuse_if_exists(F_FUND)
    assert hasattr(m, "process_ticker"), "expected integration's process_ticker-based builder"
    m.PRICE_PANEL, m.OUT = F_PRICE, F_FUND
    m.main()


def _chain(modname, src, dst):
    import importlib
    m = importlib.import_module(modname)
    refuse_if_exists(dst)
    m.SRC_PANEL, m.DST_PANEL = src, dst
    m.main()


def step_quality():
    import quality_factors as m
    refuse_if_exists(Q_V2)
    m.PRICE_PANEL, m.OUT = F_PRICE, Q_V2
    m.main()


def step_panel():
    import pandas as pd
    import pyarrow as pa
    import pyarrow.parquet as pq
    import build_panel as m
    refuse_if_exists(PANEL_TMP, PANEL_V2)
    m.BASE_PANEL, m.ISSUANCE_PANEL = F_FUND, F_ISS
    m.SHORT_INT_PANEL, m.EVENTS_PANEL = F_SI, F_EV
    m.QUALITY_PANEL = Q_V2
    m.DOWNCAP_UNIVERSE = SH / "downcap_universe_v2.parquet"
    m.OUT = PANEL_TMP
    m.main()
    print("adding v1 eligibility flags as eligible_cap*_v1 ...")
    p = pd.read_parquet(PANEL_TMP)
    v1 = pd.read_parquet(SH / "downcap_universe.parquet",
                         columns=["ticker", "date", "eligible_cap2000",
                                  "eligible_cap500", "eligible_cap150"])
    v1["ticker"] = v1["ticker"].astype(str)
    v1["date"] = pd.to_datetime(v1["date"]).dt.strftime("%Y-%m-%d")
    v1 = v1.rename(columns={c: c + "_v1" for c in
                            ("eligible_cap2000", "eligible_cap500", "eligible_cap150")})
    n = len(p)
    p = p.merge(v1, on=["ticker", "date"], how="left")
    assert len(p) == n, "v1 flag merge changed row count"
    for c in ("eligible_cap2000_v1", "eligible_cap500_v1", "eligible_cap150_v1"):
        p[c] = p[c].fillna(False).astype(bool)
    pq.write_table(pa.Table.from_pandas(p, preserve_index=False), PANEL_V2)
    PANEL_TMP.unlink()
    print(f"-> {PANEL_V2} ({len(p):,} rows)")


def step_beta():
    import build_beta_feature as m
    refuse_if_exists(BETA_V2)
    m.PANEL_PATH, m.OUT = PANEL_V2, BETA_V2
    m.main()


def step_ohlc():
    import export_sharadar_ohlc as m
    if OHLC_NEW.exists() and any(OHLC_NEW.glob("*.csv")):
        raise SystemExit(f"REFUSING: {OHLC_NEW} already has CSVs")
    m.UNIVERSE, m.OUTDIR = OHLC_TICKERS, OHLC_NEW
    sys.argv = ["export_sharadar_ohlc.py"]
    m.main()


def step_outcome():
    import execution
    import build_outcome_cache as m
    refuse_if_exists(OUTCOME_V2)
    orig = execution.load_ohlc_panel

    def both_dirs(dirs, tickers=None):
        # old dir first, so an existing CSV always wins (same as today)
        return orig([OHLC_OLD, OHLC_NEW], tickers)

    execution.load_ohlc_panel = both_dirs
    m.OUT = OUTCOME_V2
    sys.argv = ["build_outcome_cache.py"]
    m.main()


def run_step(name):
    fn = {
        "tickers": step_tickers, "prices": step_prices,
        "fundamentals": step_fundamentals,
        "issuance": lambda: _chain("build_issuance_features", F_FUND, F_ISS),
        "short": lambda: _chain("build_short_interest_features", F_FUND, F_SI),
        "events": lambda: _chain("build_event_features", F_FUND, F_EV),
        "quality": step_quality, "panel": step_panel, "beta": step_beta,
        "ohlc": step_ohlc, "outcome": step_outcome,
    }[name]
    fn()


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--step", choices=STEPS)
    ap.add_argument("--all", action="store_true")
    ap.add_argument("--from-step", choices=STEPS, default=STEPS[0])
    a = ap.parse_args()
    if a.step:
        run_step(a.step)
        return
    if not a.all:
        ap.error("--step or --all")
    for s in STEPS[STEPS.index(a.from_step):]:
        print(f"\n===== step {s} =====", flush=True)
        r = subprocess.run([sys.executable, __file__, "--step", s])
        if r.returncode != 0:
            raise SystemExit(f"step {s} failed ({r.returncode})")


if __name__ == "__main__":
    main()
