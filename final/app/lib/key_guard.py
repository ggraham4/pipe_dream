"""
SHARADAR_API_KEY presence check and the WO-15 SUE guard-log reader.

Presence only: nothing here reads, returns, logs or displays the key's value.
Job subprocesses inherit Streamlit's environment, so a Streamlit launched from
a shell that did not source ~/.config/pipe_dream/secrets.env silently breaks
every Sharadar pull in "Retrain ALL models" (Gabe, 2026-09-26: "have it tell me
if SHARADAR_API_KEY is missing or lost for whatever reason").
"""
from __future__ import annotations

import os

import pandas as pd

from . import paths

KEY_NAME = "SHARADAR_API_KEY"
SECRETS_FILE = "~/.config/pipe_dream/secrets.env"

# What stops working without the key (shown in the banner and the preflight).
BREAKS = (
    "the weekly refresh in \"Retrain ALL models\" (Sharadar price/fundamentals top-up), "
    "the WO-16 SF1 top-up, and the WO-15 SUE forward record (skipped every week; the first countable "
    "week is W40, so a missed week may not be recoverable)"
)
FIX = (
    "Stop Streamlit and relaunch it from a shell that has sourced "
    f"`{SECRETS_FILE}` (a new terminal does this via ~/.zshrc), e.g.\n\n"
    f"```\nsource {SECRETS_FILE}\nconda activate pipe_dream\ncd final/app && streamlit run app.py\n```"
)

# sue_forward.log_guard() columns (integration 6ac64e6).
GUARD_COLS = ["logged_at", "panel_date", "iso_week", "event", "ticker", "detail"]


def sharadar_key_present() -> bool:
    """True if the variable is set and non-blank. Never returns the value."""
    return bool((os.environ.get(KEY_NAME) or "").strip())


def _read_guard_log() -> pd.DataFrame | None:
    p = paths.SUE_GUARD_LOG
    if not p.exists():
        return None
    try:
        return pd.read_csv(p, dtype=str, keep_default_na=False)
    except Exception:
        return None


def sue_guard_row_count() -> int:
    """Data rows in the append-only guard log now (0 if it doesn't exist)."""
    df = _read_guard_log()
    return 0 if df is None else len(df)


def sue_guard_rows_since(n_before: int) -> pd.DataFrame:
    """Rows appended after a baseline count taken when the job started. The log
    is append-only (record_weekly.py prefix-hash-checks it), so position is a
    reliable 'written during this run' test, independent of clocks."""
    df = _read_guard_log()
    if df is None or len(df) <= n_before:
        return pd.DataFrame(columns=GUARD_COLS)
    return df.iloc[n_before:].reset_index(drop=True)


def looks_like_key_or_pull_failure(detail: str) -> bool:
    """sf1_eps_live_pull.py exits 2 when the key is missing, which ensure_live()
    logs as 'SF1 live pull failed (rc 2)'. Any other pull failure is rc 1."""
    d = (detail or "").lower()
    return any(s in d for s in ("rc 2", "sharadar_api_key", "blocked", "pull failed"))
