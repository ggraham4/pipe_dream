"""
Incrementally refresh the options historical data (option_chain_sp500.parquet
and volatility_history_sp500.parquet) from the local DoltHub clone at
../options_raw (i.e. pipe_dream/options_raw, which already has a `.dolt`
folder -- see models/options-premium-model-design.md's "Access mechanics"
section for how that clone was originally set up).

This deliberately does NOT repeat the original one-time export approach
(byte-range slicing with dd/awk to work around the device-bridge shell's
45-second-per-call cap). Run directly on your own machine there's no such
cap, and `dolt sql` can filter server-side, so an incremental update is much
simpler: pull the latest commits, then SELECT only rows newer than what we
already have, for only the tickers in our universe -- no multi-GB
intermediate CSV needed.

Prerequisites (best-effort -- this script checks and explains, it doesn't
try to install these for you):
  - the `dolt` CLI (https://docs.dolthub.com/introduction/installation)
  - network access to dolthub.com from THIS machine, run directly (not
    through Claude's device bridge, which is blocked by an org allowlist --
    see the design doc; Gabe's own browser/network access worked fine)

Usage:
    python3 update_options_history.py             # pull + incremental update
    python3 update_options_history.py --dry-run    # show what would change, write nothing
"""
import io
import shutil
import subprocess
import sys
from pathlib import Path

import pandas as pd

PROJECT_ROOT = Path(__file__).resolve().parent.parent          # final/
DOLT_REPO_DIR = PROJECT_ROOT.parent / "options_raw"             # pipe_dream/options_raw
RAW_DIR = PROJECT_ROOT / "data" / "options_raw"
OPTION_CHAIN_PARQUET = RAW_DIR / "option_chain_sp500.parquet"
VOLHIST_PARQUET = RAW_DIR / "volatility_history_sp500.parquet"

DRY_RUN = "--dry-run" in sys.argv


def check_prereqs() -> bool:
    if shutil.which("dolt") is None:
        print("ERROR: the `dolt` CLI isn't on PATH. Install it from "
              "https://docs.dolthub.com/introduction/installation, then re-run this script.")
        return False
    if not (DOLT_REPO_DIR / ".dolt").exists():
        print(f"ERROR: no dolt repo found at {DOLT_REPO_DIR} (expected a .dolt/ folder there).\n"
              f"If this is a fresh machine, first clone it yourself:\n"
              f"    cd {DOLT_REPO_DIR.parent} && dolt clone post-no-preference/options options_raw")
        return False
    return True


def ensure_dolt_identity():
    """`dolt pull` can perform a local merge commit under the hood, which fails
    outright if this repo clone has no configured commit identity yet ("Author
    identity unknown ... fatal: empty ident name not allowed"). That's a
    one-time local `dolt config` gap, not a network problem -- self-heal it
    here (falling back to a local, repo-scoped config if no global one is
    set) so a fresh machine doesn't need a manual step before its first run.
    """
    for key, default in (("user.email", "pipe_dream@localhost"), ("user.name", "pipe_dream-bot")):
        r = subprocess.run(["dolt", "config", "--get", key], cwd=DOLT_REPO_DIR,
                            capture_output=True, text=True)
        if r.returncode == 0 and r.stdout.strip():
            continue
        print(f"No dolt `{key}` configured for this repo -- setting a local default ({default}). "
              f"Run `dolt config --global --add {key} <your value>` yourself at any point to override.")
        subprocess.run(["dolt", "config", "--local", "--add", key, default],
                        cwd=DOLT_REPO_DIR, capture_output=True, text=True)


def dolt_pull() -> bool:
    print(f"Pulling latest commits into {DOLT_REPO_DIR} ...")
    r = subprocess.run(["dolt", "pull"], cwd=DOLT_REPO_DIR, capture_output=True, text=True)
    print(r.stdout.strip())
    if r.returncode != 0:
        stderr = r.stderr or ""
        if "ident" in stderr.lower() or "identity" in stderr.lower():
            cause = ("This is a dolt commit-identity problem -- `ensure_dolt_identity()` should have "
                     "caught this before `dolt pull` ran; if you're still seeing it, the "
                     "`dolt config --local --add user.email/user.name` calls above may have failed "
                     "silently (e.g. no write access to the repo's .dolt/config.json).")
        elif "network" in stderr.lower() or "connect" in stderr.lower() or "dial" in stderr.lower():
            cause = ("This looks like a network problem reaching dolthub.com -- if this machine has "
                     "an org-level network allowlist, dolthub.com needs to be on it.")
        else:
            cause = ("Could not tell from the error text alone whether this is a network, auth, or "
                     "identity problem -- read the stderr above for the specific cause.")
        print(f"ERROR: `dolt pull` failed (exit {r.returncode}).\n{r.stderr}\n{cause} Nothing was changed.")
        return False
    return True


def dolt_sql_csv(query: str) -> pd.DataFrame:
    r = subprocess.run(["dolt", "sql", "-q", query, "-r", "csv"],
                        cwd=DOLT_REPO_DIR, capture_output=True, text=True)
    if r.returncode != 0:
        raise RuntimeError(f"dolt sql failed: {r.stderr}")
    return pd.read_csv(io.StringIO(r.stdout))


def existing_universe() -> list[str]:
    if not VOLHIST_PARQUET.exists():
        print(f"WARNING: {VOLHIST_PARQUET} not found -- can't determine the existing options universe, "
              f"falling back to every ticker with a local price CSV (final/scripts/td_data_local/).")
        return sorted(p.stem for p in (PROJECT_ROOT / "scripts" / "td_data_local").glob("*.csv"))
    vh = pd.read_parquet(VOLHIST_PARQUET, columns=["act_symbol"])
    return sorted(vh["act_symbol"].unique().tolist())


def sql_in_list(tickers: list[str]) -> str:
    return "(" + ",".join(f"'{t}'" for t in tickers) + ")"


def latest_date(parquet_path: Path, date_col: str) -> str | None:
    if not parquet_path.exists():
        return None
    df = pd.read_parquet(parquet_path, columns=[date_col])
    return str(pd.to_datetime(df[date_col]).max().date())


def main():
    if not check_prereqs():
        sys.exit(1)
    ensure_dolt_identity()
    if not dolt_pull():
        sys.exit(1)

    universe = existing_universe()
    print(f"Universe: {len(universe)} tickers.")
    tickers_sql = sql_in_list(universe)

    # ---- option_chain ----
    since = latest_date(OPTION_CHAIN_PARQUET, "date")
    if since is None:
        print(f"No existing {OPTION_CHAIN_PARQUET.name} found -- run the original full export first "
              f"(see the 'Access mechanics' section of models/options-premium-model-design.md); "
              f"this script only does INCREMENTAL updates.")
    else:
        print(f"Fetching option_chain rows newer than {since} for {len(universe)} tickers...")
        query = f"SELECT * FROM option_chain WHERE date > '{since}' AND act_symbol IN {tickers_sql}"
        new_rows = dolt_sql_csv(query)
        print(f"  {len(new_rows)} new rows.")
        if len(new_rows) and not DRY_RUN:
            existing = pd.read_parquet(OPTION_CHAIN_PARQUET)
            combined = pd.concat([existing, new_rows], ignore_index=True)
            combined = combined.drop_duplicates(subset=["date", "act_symbol", "expiration", "strike", "call_put"])
            combined.to_parquet(OPTION_CHAIN_PARQUET, index=False, compression="zstd")
            print(f"  Updated {OPTION_CHAIN_PARQUET} -> {len(combined)} total rows "
                  f"(was {len(existing)}, +{len(combined) - len(existing)}).")

    # ---- volatility_history ----
    since = latest_date(VOLHIST_PARQUET, "date")
    if since is None:
        print(f"No existing {VOLHIST_PARQUET.name} found -- skipping (see note above).")
    else:
        print(f"Fetching volatility_history rows newer than {since} for {len(universe)} tickers...")
        query = f"SELECT * FROM volatility_history WHERE date > '{since}' AND act_symbol IN {tickers_sql}"
        new_rows = dolt_sql_csv(query)
        print(f"  {len(new_rows)} new rows.")
        if len(new_rows) and not DRY_RUN:
            existing = pd.read_parquet(VOLHIST_PARQUET)
            combined = pd.concat([existing, new_rows], ignore_index=True)
            combined = combined.drop_duplicates(subset=["date", "act_symbol"])
            combined.to_parquet(VOLHIST_PARQUET, index=False)
            print(f"  Updated {VOLHIST_PARQUET} -> {len(combined)} total rows "
                  f"(was {len(existing)}, +{len(combined) - len(existing)}).")

    if DRY_RUN:
        print("\n--dry-run: no files were written.")
    print("\nNote: this refreshes the raw options history only. The engineered training tables "
          "(final/data/training/options_calls_training.parquet, ...puts_training.parquet) and the GARCH "
          "volatility panel (final/data/garch_volatility.parquet) need their own rebuild to pick up new "
          "expirations -- see models/options-premium-model-design.md for that pipeline's methodology; "
          "not yet automated into a single script here.")


if __name__ == "__main__":
    main()
