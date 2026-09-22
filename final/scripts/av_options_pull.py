"""
Bulk pull of Alpha Vantage HISTORICAL_OPTIONS over the point-in-time down-cap
universe, 2008-01-02 (AV's first available date) to the latest universe date.

WHY / WHAT (see final/models/2026-09-22-alpha-vantage-spin.md):
  AV's options history carries per-contract volume + open_interest (the
  DoltHub chain has neither), starts 2008 (DoltHub: 2019), and is indexed by
  the symbol a company traded under ON THAT DATE, so dead issuers are present
  -- provided we query the as-traded symbol, not Sharadar's final ticker
  (NVTAQ -> NVTA, APC1 -> APC). Every hit is identity-checked by comparing
  put-call-parity spot to Sharadar closeunadj.

WORK ORDER (date-major, so a partial run leaves complete cross-sections):
  pass 1  "monthly": the monthly-options entry date (3rd Friday - 30 days,
          always a Wednesday; same rule as buy_no_buy_options_v2's
          build02a_entry_pairs.py), every cap150-eligible name.
          2008-01..2019-01 first (entirely new data), then 2019-02 onward.
  pass 2  "weekly": every other Wednesday, cap150-eligible names that are
          NOT cap2000 (the down-cap slice the thin-liquidity idea is about).
  Wednesdays avoid expiry Fridays (exercise moves OI with no volume).
  A holiday Wednesday rolls to the next trading day.

OUTPUT (never touches the DoltHub chain or any Sharadar file):
  <data-root>/options/<pass>/date=YYYY-MM-DD.parquet   one file per date
  <data-root>/pull_log.sqlite   one row per (pass, date, ticker) with
        status ok | no_data | error. A date's rows and its log entries are
        committed together AFTER its parquet is written atomically, so a
        crash loses at most the date in progress, never half of it.
        Resume skips only ok/no_data; error rows are retried.

AV IV/greeks are stored as av_iv/av_delta/... raw columns and are NOT
trustworthy (DELL 2012: every call delta 1.0) -- recompute downstream.

RUN (on Gabe's machine; key from the environment, never in a file):
  cd /Users/ggraham/pipe_dream
  ALPHAVANTAGE_API_KEY=... nohup caffeinate -i python3 final/scripts/av_options_pull.py \
      > final/data/alphavantage/pull.out 2>&1 &
  python3 final/scripts/av_options_pull.py --status          # progress
  pkill -f av_options_pull.py                                 # stop (resumable)
Test a slice without touching the real store:
  ALPHAVANTAGE_API_KEY=... python3 final/scripts/av_options_pull.py \
      --data-root /tmp/avtest --only-dates 2008-06-18 --max-names 200
"""
from __future__ import annotations

import argparse
import json
import os
import re
import sqlite3
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path

import numpy as np
import pandas as pd

FINAL = Path(__file__).resolve().parents[1]
DEFAULT_SHARADAR = FINAL / "data" / "sharadar"
DEFAULT_ROOT = FINAL / "data" / "alphavantage"
AV_URL = "https://www.alphavantage.co/query"
FIRST_DATE = pd.Timestamp("2008-01-02")
SPLIT_2019 = pd.Timestamp("2019-02-01")
RATE_PER_MIN = 70
PARITY_TOL = 0.15
NEG_DAYS = 180

NUM_COLS = ["strike", "last", "mark", "bid", "bid_size", "ask", "ask_size",
            "volume", "open_interest", "implied_volatility", "delta", "gamma",
            "theta", "vega", "rho"]
RENAME = {"implied_volatility": "av_iv", "delta": "av_delta", "gamma": "av_gamma",
          "theta": "av_theta", "vega": "av_vega", "rho": "av_rho"}


# ----------------------------------------------------------------- calendar
def third_friday(y: int, m: int) -> pd.Timestamp:
    d = pd.Timestamp(year=y, month=m, day=1)
    return d + pd.Timedelta(days=(4 - d.weekday()) % 7 + 14)


def roll(ts: pd.Timestamp, trading: pd.DatetimeIndex) -> pd.Timestamp | None:
    i = trading.searchsorted(ts)
    return trading[i] if i < len(trading) else None


def build_dates(trading: pd.DatetimeIndex) -> tuple[list, list]:
    last = trading.max()
    monthly = []
    for y in range(2008, last.year + 2):
        for m in range(1, 13):
            d = roll(third_friday(y, m) - pd.Timedelta(days=30), trading)
            if d is not None and FIRST_DATE <= d <= last:
                monthly.append(d)
    monthly = sorted(set(monthly))
    weds = pd.date_range(FIRST_DATE, last, freq="W-WED")
    weekly = sorted({roll(w, trading) for w in weds} - {None} - set(monthly))
    weekly = [d for d in weekly if d <= last]
    early = [d for d in monthly if d < SPLIT_2019]
    late = [d for d in monthly if d >= SPLIT_2019]
    return early + late, weekly


# ----------------------------------------------------------------- symbols
_UNITISH = re.compile(r"[.\-]|U$|W$|WS$")


def candidates(ticker: str, related: str | float) -> list[str]:
    out = [ticker]
    base = re.sub(r"\d+$", "", ticker)
    if base and base != ticker:
        out.append(base)
    if len(base) >= 4 and base.endswith("Q"):
        out.append(base[:-1])
    if isinstance(related, str):
        for r in related.split():
            if r and not _UNITISH.search(r):
                out.append(r)
    seen, res = set(), []
    for c in out:
        if c not in seen:
            seen.add(c)
            res.append(c)
    return res


# ----------------------------------------------------------------- AV client
class AV:
    def __init__(self, key: str, per_min: int = RATE_PER_MIN):
        self.key = key
        self.gap = 60.0 / per_min
        self.next_t = 0.0
        self.consec_err = 0

    def _wait(self):
        now = time.monotonic()
        if now < self.next_t:
            time.sleep(self.next_t - now)
        self.next_t = max(now, self.next_t) + self.gap

    def chain(self, symbol: str, date: str) -> tuple[str, list]:
        """Return (status, rows): ok | no_data | error."""
        q = urllib.parse.urlencode({"function": "HISTORICAL_OPTIONS", "symbol": symbol,
                                    "date": date, "apikey": self.key})
        for attempt in range(5):
            self._wait()
            try:
                r = json.loads(urllib.request.urlopen(f"{AV_URL}?{q}", timeout=60).read())
            except (urllib.error.URLError, TimeoutError, json.JSONDecodeError, ConnectionError, OSError):
                time.sleep(5 * (attempt + 1))
                continue
            if r.get("data"):
                self.consec_err = 0
                return "ok", r["data"]
            msg = str(r.get("message", "")) + str(r.get("Information", "")) + str(r.get("Error Message", ""))
            if "No data for symbol" in msg:
                self.consec_err = 0
                return "no_data", []
            if r.get("message") == "success" and r.get("data") == []:
                self.consec_err = 0
                return "no_data", []
            # burst / quota / anything else: back off and retry
            time.sleep(10 * (attempt + 1))
        self.consec_err += 1
        if self.consec_err >= 10:
            print(f"[{time.ctime()}] 10 consecutive errors, sleeping 5 min", flush=True)
            time.sleep(300)
            self.consec_err = 0
        return "error", []


def to_frame(rows: list) -> pd.DataFrame:
    df = pd.DataFrame(rows)
    for c in NUM_COLS:
        if c in df:
            df[c] = pd.to_numeric(df[c], errors="coerce")
    return df.rename(columns=RENAME)


def parity_spot(df: pd.DataFrame) -> float:
    d = df.assign(mid=(df.bid + df.ask) / 2)
    d = d[(d.bid > 0) & (d.ask > 0)]
    if d.empty:
        return np.nan
    for e in sorted(d.expiration.unique())[:3]:
        s = d[d.expiration == e].pivot_table(index="strike", columns="type", values="mid")
        if {"call", "put"} <= set(s.columns):
            s = s.dropna()
            if len(s):
                k = (s.call - s.put).abs().idxmin()
                return float(k + s.loc[k, "call"] - s.loc[k, "put"])
    return np.nan


# ----------------------------------------------------------------- store
def open_log(root: Path) -> sqlite3.Connection:
    con = sqlite3.connect(root / "pull_log.sqlite")
    con.execute("""CREATE TABLE IF NOT EXISTS calls(
        pass TEXT, date TEXT, ticker TEXT, status TEXT, symbol TEXT,
        n INTEGER, identity TEXT, spot_parity REAL, closeunadj REAL,
        tries INTEGER, ts REAL, PRIMARY KEY(pass, date, ticker))""")
    con.execute("CREATE TABLE IF NOT EXISTS symcache(ticker TEXT PRIMARY KEY, symbol TEXT)")
    con.commit()
    return con


def done_set(con, pas: str, date: str) -> set:
    return {t for (t,) in con.execute(
        "SELECT ticker FROM calls WHERE pass=? AND date=? AND status IN ('ok','no_data')", (pas, date))}


def status(root: Path):
    con = open_log(root)
    q = """SELECT pass, status, COUNT(*), COUNT(DISTINCT date), SUM(n) FROM calls GROUP BY pass, status"""
    print(pd.DataFrame(con.execute(q).fetchall(),
                       columns=["pass", "status", "calls", "dates", "contracts"]).to_string(index=False))
    q = """SELECT pass, MIN(date), MAX(date) FROM calls GROUP BY pass"""
    print(pd.DataFrame(con.execute(q).fetchall(), columns=["pass", "first", "last"]).to_string(index=False))
    q = """SELECT identity, COUNT(*) FROM calls WHERE status='ok' GROUP BY identity"""
    print(pd.DataFrame(con.execute(q).fetchall(), columns=["identity", "n"]).to_string(index=False))


# ----------------------------------------------------------------- main loop
def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--data-root", type=Path, default=DEFAULT_ROOT)
    ap.add_argument("--sharadar-dir", type=Path, default=DEFAULT_SHARADAR)
    ap.add_argument("--passes", default="monthly,weekly")
    ap.add_argument("--only-dates", default="")
    ap.add_argument("--max-names", type=int, default=0)
    ap.add_argument("--only-tickers", default="")
    ap.add_argument("--status", action="store_true")
    a = ap.parse_args()
    a.data_root.mkdir(parents=True, exist_ok=True)
    if a.status:
        status(a.data_root)
        return

    key = os.environ.get("ALPHAVANTAGE_API_KEY")
    if not key:
        sys.exit("set ALPHAVANTAGE_API_KEY in the environment")

    u = pd.read_parquet(a.sharadar_dir / "downcap_universe.parquet",
                        columns=["date", "ticker", "closeunadj", "eligible_cap2000", "eligible_cap150"])
    u["date"] = pd.to_datetime(u["date"])
    u = u[u.eligible_cap150 & (u.date >= FIRST_DATE)]
    trading = pd.DatetimeIndex(sorted(u.date.unique()))
    tm = (pd.read_csv(a.sharadar_dir / "tickers_master.csv", usecols=["ticker", "relatedtickers"])
          .drop_duplicates("ticker").set_index("ticker")["relatedtickers"])

    monthly, weekly = build_dates(trading)
    plan = []
    if "monthly" in a.passes:
        plan += [("monthly", d) for d in monthly]
    if "weekly" in a.passes:
        plan += [("weekly", d) for d in weekly]
    if a.only_dates:
        keep = {pd.Timestamp(x) for x in a.only_dates.split(",")}
        plan = [(p, d) for p, d in plan if d in keep]
    print(f"[{time.ctime()}] plan: {len(monthly)} monthly dates, {len(weekly)} weekly dates; "
          f"running {len(plan)}", flush=True)

    con = open_log(a.data_root)
    cache = dict(con.execute("SELECT ticker, symbol FROM symcache").fetchall())
    av = AV(key)
    # ticker -> date of last full-candidate miss. Within NEG_DAYS, a name that
    # had no chain under ANY symbol is retried under its first candidate only.
    neg: dict[str, pd.Timestamp] = {}
    by_date = {d: g for d, g in u.groupby("date")}

    for pas, d in plan:
        ds = d.strftime("%Y-%m-%d")
        out = a.data_root / "options" / pas / f"date={ds}.parquet"
        g = by_date[d]
        if pas == "weekly":
            g = g[~g.eligible_cap2000]
        g = g.sort_values("ticker")
        if a.only_tickers:
            g = g[g.ticker.isin(a.only_tickers.split(","))]
        if a.max_names:
            g = g.head(a.max_names)
        done = done_set(con, pas, ds)
        todo = g[~g.ticker.isin(done)]
        if todo.empty:
            continue
        t0 = time.time()
        frames, logs = [], []
        if out.exists():   # resume a date: keep what's already stored
            frames.append(pd.read_parquet(out))
        for r in todo.itertuples():
            cands = candidates(r.ticker, tm.get(r.ticker))
            if r.ticker in cache and cache[r.ticker] in cands:
                cands.remove(cache[r.ticker])
                cands.insert(0, cache[r.ticker])
            if r.ticker in neg and (d - neg[r.ticker]).days < NEG_DAYS:
                cands = cands[:1]
            st_final, hit, tries, any_err = "no_data", None, 0, False
            unverified = None
            for sym in cands:
                st, rows = av.chain(sym, ds)
                tries += 1
                if st == "error":
                    any_err = True
                    continue
                if st == "no_data":
                    continue
                df = to_frame(rows)
                sp = parity_spot(df)
                ok = (np.isfinite(sp) and r.closeunadj > 0
                      and abs(sp / r.closeunadj - 1) < PARITY_TOL)
                if ok:
                    hit = (sym, df, sp, "verified")
                    break
                if not np.isfinite(sp) and unverified is None:
                    unverified = (sym, df, sp, "unverified")
                # finite but mismatched spot = wrong issuer: keep looking
            if hit is None and unverified is not None:
                hit = unverified
            if hit is not None:
                neg.pop(r.ticker, None)
                sym, df, sp, ident = hit
                df.insert(0, "sharadar_ticker", r.ticker)
                df.insert(1, "av_symbol", sym)
                df["closeunadj"] = r.closeunadj
                frames.append(df)
                st_final = "ok"
                if ident == "verified" and cache.get(r.ticker) != sym:
                    cache[r.ticker] = sym
                    con.execute("INSERT OR REPLACE INTO symcache VALUES (?,?)", (r.ticker, sym))
            elif any_err:
                st_final = "error"
            elif tries > 1 or r.ticker not in neg:
                neg[r.ticker] = d
            logs.append((pas, ds, r.ticker, st_final, hit[0] if hit else None,
                         len(hit[1]) if hit else 0, hit[3] if hit else None,
                         hit[2] if hit else None, float(r.closeunadj), tries, time.time()))
        if frames:
            allf = pd.concat(frames, ignore_index=True)
            out.parent.mkdir(parents=True, exist_ok=True)
            tmp = out.with_suffix(".tmp")
            allf.to_parquet(tmp, index=False)
            os.replace(tmp, out)
        con.executemany("INSERT OR REPLACE INTO calls VALUES (?,?,?,?,?,?,?,?,?,?,?)", logs)
        con.commit()
        s = pd.Series([x[3] for x in logs]).value_counts().to_dict()
        print(f"[{time.ctime()}] {pas} {ds}: {len(todo)} names {s} "
              f"calls={sum(x[9] for x in logs)} {time.time()-t0:.0f}s", flush=True)
    print(f"[{time.ctime()}] plan complete", flush=True)


if __name__ == "__main__":
    main()
