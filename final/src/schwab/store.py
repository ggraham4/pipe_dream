"""Write-once parquet snapshots, the sqlite pull log, the frozen universe and
a small NYSE calendar.

Layout under the data root (default /Users/ggraham/pipe_dream/final/data/schwab,
gitignored, never committed):

    quotes/date=YYYY-MM-DD/quotes_<snapshot>_part0001.parquet
    chains/date=YYYY-MM-DD/chains_<snapshot>_part0001.parquet
    expirations/date=YYYY-MM-DD/...   (listed expiries of the reference names)
    pricehistory/date=YYYY-MM-DD/...
    hours/date=YYYY-MM-DD/...
    universe/date=YYYY-MM-DD/universe_<name>.csv   (frozen denominator)
    pull_log.sqlite

Write-once: a file is never overwritten, and a date partition that is in the
past (New York date) and already holds data never gets a new file. A re-pull
on the same day writes new files under a new snapshot id (UTC time).
"""
from __future__ import annotations

import os
import sqlite3
from datetime import date, datetime, timedelta, timezone
from pathlib import Path

import pandas as pd

from .client import to_schwab_symbol
from .parse import ny_today

MAIN_ROOT = Path("/Users/ggraham/pipe_dream/final")
DEFAULT_DATA_ROOT = MAIN_ROOT / "data" / "schwab"
WORKING_PANEL = MAIN_ROOT / "out" / "reset2026" / "composite_panel_v2.parquet"
KINDS = ("quotes", "chains", "expirations", "pricehistory", "hours")
BENCHMARKS = ("SPY", "IWM", "USMV", "QQQ")
REFERENCE_NAMES = ("AAPL", "SPY", "MSFT", "NVDA", "JPM")
TIERS = ("cap2000", "cap500", "cap150")


class WriteOnceError(RuntimeError):
    pass


def data_root(override=None):
    return Path(override or os.environ.get("PIPE_DREAM_SCHWAB_DATA") or DEFAULT_DATA_ROOT)


def new_snapshot_id(now=None):
    now = now or datetime.now(timezone.utc)
    return now.strftime("%Y%m%dT%H%M%SZ")


class SnapshotWriter:
    """Writes part files for one (session_date, snapshot). Never overwrites."""

    def __init__(self, root, session_date, snapshot, today=None):
        self.root, self.session_date, self.snapshot = Path(root), str(session_date), snapshot
        self.today = str(today or ny_today())
        self._parts = {}

    def partition(self, kind):
        if kind not in KINDS:
            raise ValueError(kind)
        return self.root / kind / f"date={self.session_date}"

    def check_writable(self, kind):
        part = self.partition(kind)
        if self.session_date < self.today and part.exists():
            others = [p.name for p in part.glob("*.parquet")
                      if f"_{self.snapshot}_" not in p.name]
            if others:
                raise WriteOnceError(
                    f"{part} is a past date and already holds data ({len(others)} file(s)); "
                    "past dates are write-once")

    def write(self, kind, rows):
        """rows: list of dicts or DataFrame. Returns the path, or None if empty."""
        df = rows if isinstance(rows, pd.DataFrame) else pd.DataFrame(rows)
        if df.empty:
            return None
        self.check_writable(kind)
        part = self.partition(kind)
        part.mkdir(parents=True, exist_ok=True)
        n = self._parts.get(kind, 0) + 1
        path = part / f"{kind}_{self.snapshot}_part{n:04d}.parquet"
        while path.exists():                      # same snapshot id reused: next part
            n += 1
            path = part / f"{kind}_{self.snapshot}_part{n:04d}.parquet"
        tmp = part / f".{path.name}.{os.getpid()}.tmp"
        df.to_parquet(tmp, index=False)
        try:
            os.link(tmp, path)                    # fails if the target exists
        except FileExistsError:
            raise WriteOnceError(f"refusing to overwrite {path}") from None
        finally:
            os.unlink(tmp)
        os.chmod(path, 0o444)
        self._parts[kind] = n
        return path


class PullLog:
    """sqlite log of every (session_date, kind, symbol) attempt. No secrets, no URLs."""

    def __init__(self, path):
        Path(path).parent.mkdir(parents=True, exist_ok=True)
        self.db = sqlite3.connect(str(path), timeout=60)
        self.db.execute("PRAGMA journal_mode=WAL")
        self.db.execute(
            "CREATE TABLE IF NOT EXISTS pulls (session_date TEXT, kind TEXT, ticker TEXT, "
            "snapshot TEXT, status TEXT, n_rows INTEGER, error TEXT, pulled_at_utc TEXT)")
        self.db.execute("CREATE INDEX IF NOT EXISTS ix_pulls ON pulls(session_date, kind, ticker)")
        self.db.commit()

    def record(self, session_date, kind, entries, snapshot):
        """entries: iterable of (ticker, status, n_rows, error). status: ok|empty|error."""
        now = datetime.now(timezone.utc).isoformat(timespec="seconds")
        self.db.executemany(
            "INSERT INTO pulls VALUES (?,?,?,?,?,?,?,?)",
            [(str(session_date), kind, t, snapshot, s, int(n), (e or "")[:200], now)
             for t, s, n, e in entries])
        self.db.commit()

    def done(self, session_date, kind):
        """Tickers already answered (ok or empty) for this date and kind."""
        cur = self.db.execute(
            "SELECT DISTINCT ticker FROM pulls WHERE session_date=? AND kind=? "
            "AND status IN ('ok','empty')", (str(session_date), kind))
        return {r[0] for r in cur}

    def summary(self, session_date):
        cur = self.db.execute(
            "SELECT kind, status, COUNT(DISTINCT ticker) FROM pulls WHERE session_date=? "
            "GROUP BY kind, status", (str(session_date),))
        return {(k, s): n for k, s, n in cur}

    def best_status(self, session_date, kind):
        """ticker -> best status seen (ok > empty > error)."""
        rank = {"ok": 2, "empty": 1, "error": 0}
        out = {}
        for t, s in self.db.execute(
                "SELECT ticker, status FROM pulls WHERE session_date=? AND kind=?",
                (str(session_date), kind)):
            if rank.get(s, -1) > rank.get(out.get(t), -1):
                out[t] = s
        return out

    def close(self):
        self.db.close()


# ------------------------------------------------------------------ universe
def build_universe(name="cap150", panel_path=WORKING_PANEL):
    """Universe frame: ticker, schwab_symbol, in_cap2000/500/150, is_benchmark, panel_date.

    name: cap150 (default, the live tier and the widest eligible set), cap500,
    cap2000, panel (every ticker on the latest panel date), a comma list
    ("AAPL,MSFT"), or a path to a file with one ticker per line / a `ticker`
    column. Benchmarks and the five reference names are always added.
    """
    panel_date, flags = None, None
    if Path(panel_path).exists():
        import pyarrow.compute as pc
        import pyarrow.parquet as pq
        panel_date = pc.max(pq.read_table(panel_path, columns=["date"]).column("date")).as_py()
        panel_date = str(panel_date)[:10]
        flags = pd.read_parquet(panel_path,
                                columns=["ticker"] + [f"eligible_{t}" for t in TIERS],
                                filters=[("date", "==", panel_date)])
        flags["ticker"] = flags["ticker"].astype(str)
        flags = flags.drop_duplicates("ticker").set_index("ticker")
    if name in TIERS or name == "panel":
        if flags is None:
            raise FileNotFoundError(f"working panel not found: {panel_path}")
        tickers = list(flags.index if name == "panel"
                       else flags.index[flags[f"eligible_{name}"].astype(bool)])
    elif Path(name).exists():
        txt = Path(name)
        if txt.suffix == ".csv":
            tickers = pd.read_csv(txt, dtype=str)["ticker"].dropna().tolist()
        else:
            tickers = [l.strip() for l in txt.read_text().splitlines()
                       if l.strip() and not l.startswith("#")]
    else:
        tickers = [t.strip().upper() for t in name.split(",") if t.strip()]
        if not tickers:
            raise ValueError(f"unknown universe {name!r}")
    seen, rows = set(), []
    for t in list(tickers) + list(BENCHMARKS) + list(REFERENCE_NAMES):
        if t in seen:
            continue
        seen.add(t)
        row = {"ticker": t, "schwab_symbol": to_schwab_symbol(t),
               "is_benchmark": t in BENCHMARKS, "in_panel": bool(flags is not None and t in flags.index)}
        for tier in TIERS:
            row[f"in_{tier}"] = bool(flags is not None and t in flags.index
                                     and flags.at[t, f"eligible_{tier}"])
        rows.append(row)
    df = pd.DataFrame(rows)
    df["panel_date"] = panel_date
    df["universe_name"] = name if (name in TIERS or name == "panel") else "custom"
    return df


def universe_path(root, session_date, name):
    label = name if (name in TIERS or name == "panel") else "custom"
    return Path(root) / "universe" / f"date={session_date}" / f"universe_{label}.csv"


def frozen_universe(root, session_date, name="cap150", panel_path=WORKING_PANEL, write=True):
    """The universe for `session_date`: frozen on first use, reused afterwards."""
    path = universe_path(root, session_date, name)
    if path.exists():
        return pd.read_csv(path, dtype={"ticker": str, "schwab_symbol": str}), path, False
    df = build_universe(name, panel_path)
    if write:
        path.parent.mkdir(parents=True, exist_ok=True)
        df.to_csv(path, index=False)
    return df, path, True


def read_kind(root, kind, session_date, columns=None):
    part = Path(root) / kind / f"date={session_date}"
    files = sorted(part.glob("*.parquet")) if part.exists() else []
    if not files:
        return pd.DataFrame()
    return pd.concat([pd.read_parquet(f, columns=columns) for f in files], ignore_index=True)


def partition_dates(root, kind):
    base = Path(root) / kind
    if not base.exists():
        return []
    return sorted(p.name[5:] for p in base.glob("date=*") if any(p.iterdir()))


# ------------------------------------------------------------------ NYSE calendar
def _observed(d):
    if d.weekday() == 5:
        return d - timedelta(days=1)
    if d.weekday() == 6:
        return d + timedelta(days=1)
    return d


def _nth_weekday(year, month, weekday, n):
    d = date(year, month, 1)
    d += timedelta(days=(weekday - d.weekday()) % 7)
    return d + timedelta(weeks=n - 1)


def nyse_holidays(year):
    from dateutil.easter import easter
    last_mon_may = date(year, 5, 31)
    last_mon_may -= timedelta(days=last_mon_may.weekday())
    hol = {
        _observed(date(year, 1, 1)), _nth_weekday(year, 1, 0, 3), _nth_weekday(year, 2, 0, 3),
        easter(year) - timedelta(days=2), last_mon_may, _observed(date(year, 6, 19)),
        _observed(date(year, 7, 4)), _nth_weekday(year, 9, 0, 1),
        _nth_weekday(year, 11, 3, 4), _observed(date(year, 12, 25)),
    }
    # New Year's Day on a Saturday is not observed on the Friday before
    if date(year, 1, 1).weekday() == 5:
        hol.discard(date(year - 1, 12, 31))
    return hol


def is_trading_day(d):
    d = date.fromisoformat(str(d)) if not isinstance(d, date) else d
    return d.weekday() < 5 and d not in nyse_holidays(d.year)


def trading_days_between(start, end):
    start, end = date.fromisoformat(str(start)), date.fromisoformat(str(end))
    out, d = [], start
    while d <= end:
        if is_trading_day(d):
            out.append(d)
        d += timedelta(days=1)
    return out


def monthly_expiries(start, end):
    """Standard monthly expiries in [start, end]: the 3rd Friday, or the trading
    day before it when that Friday is a market holiday (Good Friday)."""
    start, end = date.fromisoformat(str(start)), date.fromisoformat(str(end))
    out = []
    y, m = start.year, start.month
    while date(y, m, 1) <= end:
        d = _nth_weekday(y, m, 4, 3)
        while not is_trading_day(d):
            d -= timedelta(days=1)
        if start <= d <= end:
            out.append(d)
        y, m = (y + 1, 1) if m == 12 else (y, m + 1)
    return out
