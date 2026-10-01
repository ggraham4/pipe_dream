"""Pull loops: quotes (batched), option chains (one call per name, split by
expiry month when a chain is too big), daily price history (one call per
name) and market hours. Resumable through the sqlite pull log.

A ticker is logged only after the part file holding its rows is on disk, so
a crash can lose work but never logs data that was not written.
"""
from __future__ import annotations

from collections import defaultdict
from datetime import date, datetime, timedelta, timezone

from . import parse
from .client import LoginRequired, SchwabHTTPError
from .store import REFERENCE_NAMES

QUOTE_BATCH = 200            # symbols per /quotes call (Schwab documents no maximum)
BIG_CHAINS = ("SPY", "QQQ", "IWM")   # always pulled month by month
FINAL_GRACE = timedelta(minutes=10)


def _utcnow():
    return datetime.now(timezone.utc)


def plan(n_universe, quote_batch=QUOTE_BATCH, rate_per_min=110, kinds=("quotes", "chains",
                                                                       "pricehistory")):
    """Request counts and minutes at the rate limit, for --dry-run and the doc."""
    req = {"hours": 1}
    if "quotes" in kinds:
        req["quotes"] = -(-n_universe // quote_batch)
    if "chains" in kinds:
        # one call per name, + expirationchain for the reference names, + month splits
        req["chains"] = n_universe + len(REFERENCE_NAMES) + 3 * 24
    if "pricehistory" in kinds:
        req["pricehistory"] = n_universe
    total = sum(req.values())
    return {"requests": req, "total_requests": total,
            "minutes_at_limit": round(total / rate_per_min, 1)}


def pull_hours(client, writer, session_date, snapshot):
    """Store market hours for the session. -> dict(is_open, start, end) for equities."""
    pulled = _utcnow()
    payload = client.market_hours(("equity", "option"), str(session_date))
    rows = parse.parse_market_hours(payload, pulled, session_date, snapshot)
    if writer is not None:
        writer.write("hours", rows)
    eq = [r for r in rows if r["market"] == "equity"]
    if not eq:
        return {"is_open": None, "start": None, "end": None}
    return {"is_open": any(r["is_open"] for r in eq),
            "start": eq[0]["regular_start_utc"], "end": eq[0]["regular_end_utc"]}


def _todo(uni, log, session_date, kind, resume=True):
    done = log.done(session_date, kind) if resume else set()
    return [(t, s) for t, s in zip(uni["ticker"], uni["schwab_symbol"]) if t not in done]


def pull_quotes(client, uni, writer, log, session_date, snapshot, batch=QUOTE_BATCH,
                resume=True, progress=print):
    todo = _todo(uni, log, session_date, "quotes", resume)
    n_ok = 0

    def do(chunk):
        nonlocal n_ok
        sym2t = {s: t for t, s in chunk}
        pulled = _utcnow()
        try:
            payload = client.quotes([s for _, s in chunk])
        except LoginRequired:
            raise
        except SchwabHTTPError as e:
            if len(chunk) > 1 and 400 <= e.status < 500 and e.status != 429:
                mid = len(chunk) // 2          # one bad symbol can fail a batch: bisect
                do(chunk[:mid])
                do(chunk[mid:])
                return
            log.record(session_date, "quotes", [(t, "error", 0, str(e)) for t, _ in chunk],
                       snapshot)
            return
        rows, _invalid = parse.parse_quotes(payload, sym2t, pulled, session_date, snapshot)
        writer.write("quotes", rows)
        got = {r["ticker"] for r in rows}
        n_ok += len(got)
        log.record(session_date, "quotes",
                   [(t, "ok", 1, "") if t in got else (t, "error", 0, "not returned (invalid symbol)")
                    for t, _ in chunk], snapshot)

    for i in range(0, len(todo), batch):
        do(todo[i:i + batch])
        progress(f"quotes: {min(i + batch, len(todo))}/{len(todo)}")
    return {"todo": len(todo), "ok": n_ok}


def _month_windows(expiries):
    """Expiry dates -> [(from, to)] one window per calendar month."""
    by = defaultdict(list)
    for e in expiries:
        by[e[:7]].append(e)
    return [(min(v), max(v)) for _, v in sorted(by.items())]


def fetch_chain_rows(client, ticker, symbol, session_date, snapshot, force_split=False):
    """-> (chain_rows, expiration_rows, status, error). Splits by month if needed."""
    exp_rows = []
    err = ""
    if not force_split:
        pulled = _utcnow()
        try:
            payload = client.option_chain(symbol)
            if str(payload.get("status", "SUCCESS")).upper() != "FAILED":
                rows = parse.parse_chain(payload, ticker, pulled, session_date, snapshot)
                return rows, exp_rows, ("ok" if rows else "empty"), ""
            err = "status FAILED"
        except LoginRequired:
            raise
        except SchwabHTTPError as e:
            if e.status == 404:
                return [], exp_rows, "empty", str(e)
            err = str(e)
    # too big (or failed): list the expiries, then one call per calendar month
    try:
        pulled = _utcnow()
        exp_payload = client.expiration_chain(symbol)
        exp_rows = parse.parse_expirations(exp_payload, ticker, pulled, session_date, snapshot)
        if not exp_rows:
            return [], exp_rows, "empty", err
    except LoginRequired:
        raise
    except SchwabHTTPError as e:
        if e.status == 404:
            return [], exp_rows, "empty", str(e)
        return [], exp_rows, "error", f"{err}; expirationchain: {e}" if err else str(e)
    expiries = sorted({r["expiry"] for r in exp_rows})
    rows, failed = [], []

    def window(lo, hi):
        pulled = _utcnow()
        payload = client.option_chain(symbol, from_date=lo, to_date=hi)
        if str(payload.get("status", "SUCCESS")).upper() == "FAILED":
            raise SchwabHTTPError(200, "status FAILED")
        return parse.parse_chain(payload, ticker, pulled, session_date, snapshot)

    for lo, hi in _month_windows(expiries):
        try:
            rows += window(lo, hi)
        except SchwabHTTPError:
            # a month of daily expiries can still be too big: one expiry at a time,
            # keeping everything already pulled
            for e1 in [x for x in expiries if lo <= x <= hi]:
                try:
                    rows += window(e1, e1)
                except SchwabHTTPError as e:
                    failed.append(f"{e1} ({e.status})")
    if failed:      # rows are kept on disk, but the name is logged as an error and retried
        return rows, exp_rows, "error", "missing expiries: " + ", ".join(failed)[:150]
    return rows, exp_rows, ("ok" if rows else "empty"), ""


def pull_chains(client, uni, writer, log, session_date, snapshot, resume=True,
                flush_every=25, progress=print):
    todo = _todo(uni, log, session_date, "chains", resume)
    buf, exp_buf, pending, n_ok = [], [], [], 0

    def flush():
        nonlocal buf, exp_buf, pending
        writer.write("chains", buf)
        writer.write("expirations", exp_buf)
        log.record(session_date, "chains", pending, snapshot)
        buf, exp_buf, pending = [], [], []

    for i, (t, s) in enumerate(todo, 1):
        rows, exp_rows, status, err = fetch_chain_rows(
            client, t, s, session_date, snapshot, force_split=t in BIG_CHAINS)
        if t in REFERENCE_NAMES and not exp_rows and status == "ok":
            try:                                   # listed expiries, for the monthly test
                exp_rows = parse.parse_expirations(client.expiration_chain(s), t, _utcnow(),
                                                   session_date, snapshot)
            except SchwabHTTPError:
                pass
        buf += rows
        exp_buf += exp_rows
        pending.append((t, status, len(rows), err))
        n_ok += status == "ok"
        if i % flush_every == 0:
            flush()
            progress(f"chains: {i}/{len(todo)}")
    flush()
    return {"todo": len(todo), "ok": n_ok}


def pull_pricehistory(client, uni, writer, log, session_date, snapshot, lookback_days=14,
                      final_cutoff_utc=None, resume=True, flush_every=200, progress=print):
    todo = _todo(uni, log, session_date, "pricehistory", resume)
    sd = date.fromisoformat(str(session_date))
    start = datetime(sd.year, sd.month, sd.day, tzinfo=parse.NY) - timedelta(days=lookback_days)
    end = datetime(sd.year, sd.month, sd.day, 23, 59, 59, tzinfo=parse.NY)
    start_ms, end_ms = int(start.timestamp() * 1000), int(end.timestamp() * 1000)
    buf, pending, n_ok = [], [], 0

    def flush():
        nonlocal buf, pending
        writer.write("pricehistory", buf)
        log.record(session_date, "pricehistory", pending, snapshot)
        buf, pending = [], []

    for i, (t, s) in enumerate(todo, 1):
        pulled = _utcnow()
        try:
            payload = client.price_history_daily(s, start_ms, end_ms)
            rows = parse.parse_price_history(payload, t, pulled, session_date, snapshot,
                                             final_cutoff_utc=final_cutoff_utc)
            status, err = ("ok" if rows else "empty"), ""
        except LoginRequired:
            raise
        except SchwabHTTPError as e:
            rows, status, err = [], ("empty" if e.status == 404 else "error"), str(e)
        buf += rows
        pending.append((t, status, len(rows), err))
        n_ok += status == "ok"
        if i % flush_every == 0:
            flush()
            progress(f"pricehistory: {i}/{len(todo)}")
    flush()
    return {"todo": len(todo), "ok": n_ok}
