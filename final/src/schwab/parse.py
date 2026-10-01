"""Turn Schwab market-data JSON payloads into flat rows (lists of dicts).

Every row carries: `pulled_at_utc` (when we asked), `session_date` (the
America/New_York date the snapshot belongs to), `snapshot` (run id) and the
API's own timestamps converted to UTC. The raw Sharadar-style ticker is in
`ticker`; the symbol Schwab was asked for is in `schwab_symbol`.
"""
from __future__ import annotations

from datetime import date, datetime, timedelta, timezone
from zoneinfo import ZoneInfo

NY = ZoneInfo("America/New_York")


def ms_to_utc(ms):
    """Epoch milliseconds -> tz-aware UTC datetime (None for 0/None)."""
    if ms in (None, 0, "0", ""):
        return None
    return datetime.fromtimestamp(int(ms) / 1000.0, tz=timezone.utc)


def ms_to_ny_date(ms):
    d = ms_to_utc(ms)
    return None if d is None else d.astimezone(NY).date()


def ny_today(now=None):
    now = now or datetime.now(timezone.utc)
    return now.astimezone(NY).date()


def _stamp(row, pulled_at, session_date, snapshot):
    row["pulled_at_utc"] = pulled_at
    row["session_date"] = str(session_date)
    row["snapshot"] = snapshot
    return row


def _f(x):
    try:
        return None if x is None or x == "" else float(x)
    except (TypeError, ValueError):
        return None


QUOTE_FIELDS = {          # output column -> key in payload["quote"]
    "bid": "bidPrice", "ask": "askPrice", "bid_size": "bidSize", "ask_size": "askSize",
    "last": "lastPrice", "last_size": "lastSize", "mark": "mark",
    "open": "openPrice", "high": "highPrice", "low": "lowPrice",
    "prev_close": "closePrice", "net_change": "netChange", "volume": "totalVolume",
    "high_52w": "52WeekHigh", "low_52w": "52WeekLow",
}


def parse_quotes(payload, symbol_to_ticker, pulled_at, session_date, snapshot):
    """-> (rows, invalid_symbols). One row per symbol Schwab returned."""
    rows = []
    invalid = list(((payload.get("errors") or {}).get("invalidSymbols")) or [])
    for sym, body in payload.items():
        if sym == "errors" or not isinstance(body, dict):
            continue
        q = body.get("quote") or {}
        reg = body.get("regular") or {}
        ref = body.get("reference") or {}
        fund = body.get("fundamental") or {}
        row = {"ticker": symbol_to_ticker.get(sym, sym), "schwab_symbol": sym,
               "asset_type": body.get("assetMainType"),
               "realtime": body.get("realtime"),
               "security_status": q.get("securityStatus"),
               "exchange": ref.get("exchangeName") or ref.get("exchange"),
               "description": ref.get("description"), "cusip": ref.get("cusip")}
        for col, key in QUOTE_FIELDS.items():
            row[col] = _f(q.get(key))
        row["quote_time_utc"] = ms_to_utc(q.get("quoteTime"))
        row["trade_time_utc"] = ms_to_utc(q.get("tradeTime"))
        row["bid_time_utc"] = ms_to_utc(q.get("bidTime"))
        row["ask_time_utc"] = ms_to_utc(q.get("askTime"))
        row["regular_last"] = _f(reg.get("regularMarketLastPrice"))
        row["regular_trade_time_utc"] = ms_to_utc(reg.get("regularMarketTradeTime"))
        row["avg_10d_volume"] = _f(fund.get("avg10DaysVolume"))
        row["div_yield"] = _f(fund.get("divYield"))
        row["next_div_ex_date"] = (str(fund.get("nextDivExDate"))
                                   if fund.get("nextDivExDate") else None)
        rows.append(_stamp(row, pulled_at, session_date, snapshot))
    return rows, invalid


CONTRACT_FIELDS = {       # output column -> key in a contract dict
    "bid": "bid", "ask": "ask", "last": "last", "mark": "mark",
    "bid_size": "bidSize", "ask_size": "askSize", "last_size": "lastSize",
    "open": "openPrice", "high": "highPrice", "low": "lowPrice", "prev_close": "closePrice",
    "volume": "totalVolume", "open_interest": "openInterest",
    "iv": "volatility", "delta": "delta", "gamma": "gamma", "theta": "theta",
    "vega": "vega", "rho": "rho", "theo_value": "theoreticalOptionValue",
    "theo_vol": "theoreticalVolatility", "time_value": "timeValue",
    "intrinsic_value": "intrinsicValue", "multiplier": "multiplier",
    "days_to_expiration": "daysToExpiration",
}


def parse_chain(payload, ticker, pulled_at, session_date, snapshot):
    """-> rows, one per contract (calls and puts). Empty list if no contracts."""
    rows = []
    und = payload.get("underlying") or {}
    und_price = _f(payload.get("underlyingPrice")) or _f(und.get("mark")) or _f(und.get("last"))
    und_quote_time = ms_to_utc(und.get("quoteTime"))
    for side_key in ("callExpDateMap", "putExpDateMap"):
        for exp_key, strikes in (payload.get(side_key) or {}).items():
            expiry = str(exp_key).split(":")[0]
            for _, contracts in (strikes or {}).items():
                for c in contracts or []:
                    row = {"ticker": ticker, "schwab_symbol": payload.get("symbol"),
                           "option_symbol": c.get("symbol"),
                           "put_call": c.get("putCall") or ("CALL" if side_key.startswith("call")
                                                            else "PUT"),
                           "expiry": expiry, "strike": _f(c.get("strikePrice")),
                           "expiration_type": c.get("expirationType"),
                           "settlement_type": c.get("settlementType"),
                           "exercise_type": c.get("exerciseType"),
                           "option_root": c.get("optionRoot"),
                           "non_standard": c.get("nonStandard"),
                           "in_the_money": c.get("inTheMoney"),
                           "exchange": c.get("exchangeName")}
                    for col, key in CONTRACT_FIELDS.items():
                        v = _f(c.get(key))
                        # Schwab uses -999 (and "NaN") for greeks it cannot compute
                        if v is not None and (v != v or v == -999.0):
                            v = None
                        row[col] = v
                    row["quote_time_utc"] = ms_to_utc(c.get("quoteTimeInLong"))
                    row["trade_time_utc"] = ms_to_utc(c.get("tradeTimeInLong"))
                    row["underlying_price"] = und_price
                    row["underlying_quote_time_utc"] = und_quote_time
                    row["is_delayed"] = payload.get("isDelayed")
                    row["interest_rate"] = _f(payload.get("interestRate"))
                    rows.append(_stamp(row, pulled_at, session_date, snapshot))
    return rows


def parse_expirations(payload, ticker, pulled_at, session_date, snapshot):
    rows = []
    for e in payload.get("expirationList") or []:
        rows.append(_stamp({
            "ticker": ticker, "expiry": str(e.get("expirationDate"))[:10],
            "expiration_type": e.get("expirationType"),
            "settlement_type": e.get("settlementType"),
            "option_roots": e.get("optionRoots"), "standard": e.get("standard"),
            "days_to_expiration": _f(e.get("daysToExpiration"))},
            pulled_at, session_date, snapshot))
    return rows


def parse_price_history(payload, ticker, pulled_at, session_date, snapshot,
                        final_cutoff_utc=None):
    """Daily candles. `candle_date` is the New York date of the candle epoch.

    `is_final` is False for the session_date candle when the pull happened
    before `final_cutoff_utc` (regular close + grace): that bar is still
    moving and must not be compared with Sharadar's close.
    """
    rows = []
    sd = date.fromisoformat(str(session_date))
    for c in payload.get("candles") or []:
        cd = ms_to_ny_date(c.get("datetime"))
        if cd is None:
            continue
        final = cd < sd or (final_cutoff_utc is not None and pulled_at >= final_cutoff_utc
                            and cd == sd)
        rows.append(_stamp({
            "ticker": ticker, "schwab_symbol": payload.get("symbol"),
            "candle_date": str(cd), "candle_time_utc": ms_to_utc(c.get("datetime")),
            "open": _f(c.get("open")), "high": _f(c.get("high")), "low": _f(c.get("low")),
            "close": _f(c.get("close")), "volume": _f(c.get("volume")),
            "is_final": bool(final)}, pulled_at, session_date, snapshot))
    return rows


def parse_market_hours(payload, pulled_at, session_date, snapshot):
    """One row per (market, product) with the regular session start/end in UTC."""
    rows = []
    for market, products in (payload or {}).items():
        if not isinstance(products, dict):
            continue
        for product, body in products.items():
            reg = ((body.get("sessionHours") or {}).get("regularMarket") or [{}])[0]
            start = _iso_to_utc(reg.get("start"))
            end = _iso_to_utc(reg.get("end"))
            rows.append(_stamp({
                "market": market, "product": product, "hours_date": body.get("date"),
                "is_open": bool(body.get("isOpen")),
                "regular_start_utc": start, "regular_end_utc": end},
                pulled_at, session_date, snapshot))
    return rows


def _iso_to_utc(s):
    if not s:
        return None
    return datetime.fromisoformat(s).astimezone(timezone.utc)


def default_session_bounds(session_date):
    """09:30-16:00 New York, in UTC. Used only when market hours were not stored."""
    d = date.fromisoformat(str(session_date))
    start = datetime(d.year, d.month, d.day, 9, 30, tzinfo=NY)
    return start.astimezone(timezone.utc), (start + timedelta(hours=6, minutes=30)).astimezone(
        timezone.utc)
