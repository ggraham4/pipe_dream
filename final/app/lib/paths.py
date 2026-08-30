"""
Central path resolution for the pipe_dream dashboard app, following the same
convention as final/src/features.py: everything is resolved relative to this
file's location, not hardcoded to any one machine, so the app works the same
on Gabe's Mac and anywhere else this repo gets cloned.

Layout assumed (matches the rest of the repo as of 2026-08-27):
    final/
        app/            <- this dashboard app lives here
        src/            <- stock buy/no-buy model scripts (features.py, etc.)
        scripts/
            td_data_local/      <- one CSV per ticker, from local_data_pull.py
        out/
            models/              <- saved XGBoost/LSTM checkpoints
        models/          <- options premium model scripts + artifacts
        data/
            training/            <- options_calls_training.parquet, options_puts_training.parquet
            options_raw/         <- option_chain_sp500.parquet, volatility_history_sp500.parquet
            live_score/          <- most recent live option-chain snapshot
            garch_volatility.parquet

If you move this app or reorganize the repo, this is the one file that
needs to change -- every other module in app/lib imports paths from here.
"""
from pathlib import Path
import sys

APP_DIR = Path(__file__).resolve().parent.parent          # final/app
FINAL_DIR = APP_DIR.parent                                 # final/
PROJECT_ROOT = FINAL_DIR                                    # kept as an alias; matches features.py's naming

# stock buy/no-buy model
SRC_DIR = FINAL_DIR / "src"
STOCK_DATA_DIR = FINAL_DIR / "scripts" / "td_data_local"
OUT_DIR = FINAL_DIR / "out"
STOCK_MODELS_DIR = OUT_DIR / "models"
FEATURES_PARQUET = OUT_DIR / "features.parquet"

# options premium model
OPTIONS_SRC_DIR = FINAL_DIR / "models"          # the scripts Gabe's chats produced (live_score.py etc.) live here
OPTIONS_DATA_DIR = FINAL_DIR / "data"
OPTIONS_TRAINING_DIR = OPTIONS_DATA_DIR / "training"
OPTIONS_RAW_DIR = OPTIONS_DATA_DIR / "options_raw"
LIVE_SCORE_DIR = OPTIONS_DATA_DIR / "live_score"
GARCH_PARQUET = OPTIONS_DATA_DIR / "garch_volatility.parquet"

OPTIONS_CALLS_TRAINING = OPTIONS_TRAINING_DIR / "options_calls_training.parquet"
OPTIONS_PUTS_TRAINING = OPTIONS_TRAINING_DIR / "options_puts_training.parquet"
OPTION_CHAIN_SP500 = OPTIONS_RAW_DIR / "option_chain_sp500.parquet"
VOLATILITY_HISTORY_SP500 = OPTIONS_RAW_DIR / "volatility_history_sp500.parquet"
LIVE_CALLS_CHAIN = LIVE_SCORE_DIR / "live_calls_chain.parquet"
LIVE_VOLHIST = LIVE_SCORE_DIR / "live_volhist.parquet"

# scripts this app shells out to (data refresh)
SCRIPTS_DIR = FINAL_DIR / "scripts"
LOGS_DIR = APP_DIR / "logs"

# universe screen source of truth for how many tickers *should* exist --
# read the actual count from the CSV directory at runtime rather than
# hardcoding a number that will go stale the moment the universe changes.
DOLT_REPO_DIR = FINAL_DIR.parent / "options_raw"   # pipe_dream/options_raw (has .dolt/)


def ensure_src_on_path():
    """Let app modules `import features`, `import lstm_backtest`, etc. the
    same way the repo's own scripts do, without duplicating that logic here.
    Import this before importing anything from final/src."""
    for p in (str(SRC_DIR),):
        if p not in sys.path:
            sys.path.insert(0, p)


def ensure_dirs():
    LOGS_DIR.mkdir(parents=True, exist_ok=True)
