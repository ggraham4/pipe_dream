"""Offline unit tests for the Schwab collector (mocked HTTP, no network).

    cd final/src && python -m unittest schwab.tests.test_schwab -v
"""
import inspect
import json
import os
import stat
import sys
import tempfile
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path, PureWindowsPath
from unittest import mock

import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from schwab import checks, parse, pull, store                     # noqa: E402
from schwab import client as C                                    # noqa: E402

UTC = timezone.utc


class Resp:
    def __init__(self, status=200, body=None, headers=None):
        self.status_code, self._body, self.headers = status, body or {}, headers or {}
        self.text = json.dumps(self._body)

    def json(self):
        return self._body


class FakeSession:
    """Scripted responses. Records every call; fails the test on a non-allowed URL."""

    def __init__(self, get=None, post=None):
        self.get_queue, self.post_queue = list(get or []), list(post or [])
        self.calls = []

    def get(self, url, headers=None, params=None, timeout=None):
        C.assert_market_data_url(url)
        self.calls.append(("GET", url, dict(params or {}), dict(headers or {})))
        r = self.get_queue.pop(0)
        return r(url, params) if callable(r) else r

    def post(self, url, headers=None, data=None, timeout=None):
        C.assert_market_data_url(url)
        self.calls.append(("POST", url, dict(data or {}), dict(headers or {})))
        return self.post_queue.pop(0)


class Clock:
    def __init__(self, t=1_000_000.0):
        self.t, self.sleeps = t, []

    def __call__(self):
        return self.t

    def sleep(self, s):
        self.sleeps.append(s)
        self.t += s


def make_client(tmp, session, clock=None, **kw):
    clock = clock or Clock()
    return C.SchwabClient(app_key="KEY", app_secret="SECRET",
                          token_store=C.TokenStore(Path(tmp) / "tok.json"), session=session,
                          rate_limiter=C.RateLimiter(1000, 60, clock=clock, sleep=clock.sleep),
                          clock=clock, sleep=clock.sleep, **kw), clock


TOKEN = {"access_token": "A1", "refresh_token": "R1", "expires_in": 1800, "scope": "api",
         "token_type": "Bearer"}

QUOTE_PAYLOAD = {
    "AAPL": {"assetMainType": "EQUITY", "realtime": True, "symbol": "AAPL",
             "reference": {"cusip": "037833100", "description": "Apple Inc", "exchangeName": "NASDAQ"},
             "quote": {"bidPrice": 333.0, "askPrice": 333.05, "bidSize": 2, "askSize": 3,
                       "lastPrice": 333.02, "closePrice": 330.0, "totalVolume": 1000,
                       "quoteTime": 1790798400000, "tradeTime": 1790798399000,
                       "securityStatus": "Normal", "52WeekHigh": 350.0},
             "regular": {"regularMarketLastPrice": 333.02, "regularMarketTradeTime": 1790798400000}},
    "BRK/B": {"assetMainType": "EQUITY", "symbol": "BRK/B",
              "quote": {"bidPrice": 497.9, "askPrice": 498.0, "quoteTime": 1790798400000}},
    "errors": {"invalidSymbols": ["ZZZZ"]},
}


def contract(put_call, strike, exp, bid, ask, **kw):
    d = {"putCall": put_call, "symbol": f"AAPL  {exp}{put_call[0]}{strike}", "bid": bid, "ask": ask,
         "last": (bid + ask) / 2, "bidSize": 10, "askSize": 12, "totalVolume": 50,
         "openInterest": 400, "volatility": 25.0, "delta": 0.5, "gamma": 0.01, "theta": -0.1,
         "vega": 0.2, "rho": -999.0, "strikePrice": strike, "expirationType": "S",
         "quoteTimeInLong": 1790798400000, "tradeTimeInLong": 1790798000000,
         "daysToExpiration": 15, "multiplier": 100.0}
    d.update(kw)
    return d


def chain_payload(expiries=("2026-10-16", "2026-11-20", "2026-12-18"), symbol="AAPL"):
    calls, puts = {}, {}
    for e in expiries:
        calls[f"{e}:15"] = {"330.0": [contract("CALL", 330.0, e, 5.0, 5.2)],
                            "335.0": [contract("CALL", 335.0, e, 3.0, 3.1)]}
        puts[f"{e}:15"] = {"330.0": [contract("PUT", 330.0, e, 4.0, 4.1)]}
    return {"symbol": symbol, "status": "SUCCESS", "underlyingPrice": 333.0, "isDelayed": False,
            "interestRate": 4.0, "underlying": {"quoteTime": 1790798400000},
            "callExpDateMap": calls, "putExpDateMap": puts}


class NeverTrade(unittest.TestCase):
    def test_refuses_accounts_and_orders(self):
        base = "https://api.schwabapi.com"
        for bad in [f"{base}/trader/v1/accounts", f"{base}/trader/v1/accounts/123/orders",
                    f"{base}/trader/v1/orders", f"{base}/marketdata/v1/orders",
                    f"{base}/marketdata/v1/../../trader/v1/accounts",
                    f"{base}/marketdata/v1/quotes?next=/accounts",
                    f"{base}/marketdata/v1/%2Forders", f"{base}/marketdata/v1/%252Faccounts",
                    f"{base}/trader/v1/userPreference", f"{base}/v1/oauth/revoke",
                    "https://evil.example/marketdata/v1/quotes",
                    "http://api.schwabapi.com/marketdata/v1/quotes"]:
            with self.assertRaises(C.ForbiddenEndpointError, msg=bad):
                C.assert_market_data_url(bad)
        for ok in [f"{base}/marketdata/v1/quotes", f"{base}/marketdata/v1/chains?symbol=AAPL",
                   f"{base}/v1/oauth/token", f"{base}/v1/oauth/authorize?client_id=x"]:
            self.assertEqual(C.assert_market_data_url(ok), ok)

    def test_client_get_refuses_before_any_network_call(self):
        with tempfile.TemporaryDirectory() as tmp:
            s = FakeSession()
            cl, _ = make_client(tmp, s)
            for path in ["../../trader/v1/accounts", "orders", "accounts/1/orders", "x/orders/y"]:
                with self.assertRaises(C.ForbiddenEndpointError):
                    cl.get(path)
            with self.assertRaises(C.ForbiddenEndpointError):
                cl.get("quotes", {"symbols": "/orders"})
            self.assertEqual(s.calls, [])

    def test_no_order_or_account_methods_or_write_verbs(self):
        banned = ("order", "account", "trade", "place", "cancel", "replace", "buy", "sell",
                  "preference", "transaction")
        names = [n for n, _ in inspect.getmembers(C.SchwabClient) if not n.startswith("__")]
        for n in names:
            self.assertFalse(any(b in n.lower() for b in banned), n)
        pkg = Path(C.__file__).parent
        for f in list(pkg.glob("*.py")) + [pkg.parents[1] / "scripts" / "schwab_pull.py",
                                           pkg.parents[1] / "scripts" / "schwab_check.py"]:
            src = f.read_text()
            for verb in (".put(", ".delete(", ".patch(", "session.request("):
                self.assertNotIn(verb, src, f"{f.name} uses {verb}")
            # the only POST in the package is the OAuth token exchange
            self.assertEqual(src.count(".post("), 1 if f.name == "client.py" else 0, f.name)

    def test_trading_scope_stops_login(self):
        with tempfile.TemporaryDirectory() as tmp:
            s = FakeSession(post=[Resp(200, dict(TOKEN, scope="api trading"))])
            cl, _ = make_client(tmp, s)
            with self.assertRaises(C.TradingScopeError):
                cl.login_with_redirect("https://127.0.0.1/?code=abc%40&session=1")
            self.assertFalse((Path(tmp) / "tok.json").exists())


class Tokens(unittest.TestCase):
    def test_login_refresh_and_file_mode(self):
        with tempfile.TemporaryDirectory() as tmp:
            s = FakeSession(post=[Resp(200, TOKEN), Resp(200, dict(TOKEN, access_token="A2")),
                                  Resp(200, dict(TOKEN, access_token="A3"))],
                            get=[Resp(200, {"ok": 1}), Resp(200, {"ok": 2}),
                                 Resp(401, {}), Resp(200, {"ok": 3})])
            cl, clock = make_client(tmp, s)
            cl.login_with_redirect("https://127.0.0.1/?code=C0DE%40&session=xyz")
            post = s.calls[0]
            self.assertEqual(post[2]["grant_type"], "authorization_code")
            self.assertEqual(post[2]["code"], "C0DE@")              # url-decoded
            self.assertTrue(post[3]["Authorization"].startswith("Basic "))
            tok_path = Path(tmp) / "tok.json"
            if os.name == "posix":       # Windows has no mode bits; the profile ACL protects it
                self.assertEqual(stat.S_IMODE(os.stat(tok_path).st_mode), 0o600)

            self.assertEqual(cl.get("markets", {"markets": "equity"}), {"ok": 1})
            self.assertEqual(s.calls[-1][3]["Authorization"], "Bearer A1")
            self.assertEqual(len([c for c in s.calls if c[0] == "POST"]), 1)   # no refresh yet

            clock.t += 1800 - 60                                    # inside the refresh skew
            self.assertEqual(cl.get("markets"), {"ok": 2})
            self.assertEqual(s.calls[-2][2], {"grant_type": "refresh_token", "refresh_token": "R1"})
            self.assertEqual(s.calls[-1][3]["Authorization"], "Bearer A2")

            self.assertEqual(cl.get("markets"), {"ok": 3})          # 401 -> refresh -> retry
            self.assertEqual(s.calls[-1][3]["Authorization"], "Bearer A3")
            st = cl.token_status()
            self.assertTrue(st["logged_in"])
            self.assertLess(st["refresh_days_left"], 7.0)           # clock runs from the login

    def test_expired_refresh_token_asks_for_login(self):
        with tempfile.TemporaryDirectory() as tmp:
            s = FakeSession(post=[Resp(200, TOKEN), Resp(400, {"error": "invalid_grant"})])
            cl, clock = make_client(tmp, s)
            cl.login_with_redirect("https://127.0.0.1/?code=c")
            clock.t += 8 * 86400
            with self.assertRaises(C.LoginRequired):
                cl.get("markets")

    def test_token_store_refuses_repo_path_and_no_secret_leak(self):
        with tempfile.TemporaryDirectory() as tmp:
            with self.assertRaises(ValueError):
                C.TokenStore(Path(tmp) / "repo" / "tok.json", repo_root=Path(tmp) / "repo")
            s = FakeSession(post=[Resp(401, {"error": "bad SECRET R1 C0DE"})])
            cl, _ = make_client(tmp, s)
            self.assertNotIn("SECRET", repr(cl))
            with self.assertRaises(C.SchwabHTTPError) as cm:
                cl.login_with_redirect("https://127.0.0.1/?code=C0DE")
            self.assertNotIn("C0DE", str(cm.exception))
            self.assertNotIn("SECRET", str(cm.exception))

    def test_retries_429_and_500_with_backoff(self):
        with tempfile.TemporaryDirectory() as tmp:
            s = FakeSession(post=[Resp(200, TOKEN)],
                            get=[Resp(429, {}, {"Retry-After": "7"}), Resp(503, {}), Resp(200, {"x": 1}),
                                 Resp(400, {"message": "bad"})])
            cl, clock = make_client(tmp, s)
            cl.login_with_redirect("https://127.0.0.1/?code=c")
            self.assertEqual(cl.get("quotes", {"symbols": "AAPL"}), {"x": 1})
            self.assertEqual(len(clock.sleeps), 2)
            self.assertGreaterEqual(clock.sleeps[0], 7)
            with self.assertRaises(C.SchwabHTTPError):               # 400 is not retried
                cl.get("quotes", {"symbols": "AAPL"})
            self.assertEqual(len(clock.sleeps), 2)


class Limiter(unittest.TestCase):
    def test_never_more_than_max_calls_per_window(self):
        clock = Clock(0.0)
        rl = C.RateLimiter(max_calls=5, period=60, clock=clock, sleep=clock.sleep)
        stamps = []
        for _ in range(23):
            rl.acquire()
            stamps.append(clock.t)
        for i in range(len(stamps)):
            in_window = [t for t in stamps if stamps[i] <= t < stamps[i] + 60]
            self.assertLessEqual(len(in_window), 5)
        self.assertGreaterEqual(stamps[-1], 4 * 60)                  # 23 calls need 4 full waits
        self.assertEqual(stamps[:5], [0.0] * 5)                      # first burst is not delayed


class Parsing(unittest.TestCase):
    now = datetime(2026, 10, 1, 19, 45, tzinfo=UTC)

    def test_quote_payload(self):
        rows, invalid = parse.parse_quotes(QUOTE_PAYLOAD, {"BRK/B": "BRK.B"}, self.now,
                                           "2026-10-01", "S1")
        self.assertEqual(invalid, ["ZZZZ"])
        by = {r["ticker"]: r for r in rows}
        self.assertEqual(set(by), {"AAPL", "BRK.B"})
        a = by["AAPL"]
        self.assertEqual((a["bid"], a["ask"], a["prev_close"], a["volume"]),
                         (333.0, 333.05, 330.0, 1000.0))
        self.assertEqual(a["quote_time_utc"], datetime.fromtimestamp(1790798400, tz=UTC))
        self.assertEqual(a["pulled_at_utc"], self.now)
        self.assertEqual((a["session_date"], a["snapshot"]), ("2026-10-01", "S1"))
        self.assertEqual(by["BRK.B"]["schwab_symbol"], "BRK/B")
        self.assertIsNone(by["BRK.B"]["last"])
        pd.DataFrame(rows).to_parquet(Path(tempfile.mkdtemp()) / "q.parquet")   # serialisable

    def test_chain_payload(self):
        rows = parse.parse_chain(chain_payload(), "AAPL", self.now, "2026-10-01", "S1")
        self.assertEqual(len(rows), 9)                               # 3 expiries x (2 calls + 1 put)
        self.assertEqual({r["expiry"] for r in rows}, {"2026-10-16", "2026-11-20", "2026-12-18"})
        self.assertEqual({r["put_call"] for r in rows}, {"CALL", "PUT"})
        r = [x for x in rows if x["put_call"] == "PUT"][0]
        self.assertEqual((r["strike"], r["bid"], r["ask"], r["open_interest"], r["volume"]),
                         (330.0, 4.0, 4.1, 400.0, 50.0))
        self.assertEqual(r["delta"], 0.5)
        self.assertIsNone(r["rho"])                                  # -999 sentinel -> missing
        self.assertEqual(r["underlying_price"], 333.0)
        self.assertIsNotNone(r["quote_time_utc"])
        self.assertEqual(r["pulled_at_utc"], self.now)
        self.assertEqual(parse.parse_chain({"symbol": "X", "status": "SUCCESS"}, "X", self.now,
                                           "2026-10-01", "S1"), [])

    def test_price_history_dates_are_new_york_and_final_flag(self):
        # Schwab stamps daily candles at 05:00/06:00 UTC of the trading date
        ms = lambda y, m, d, h: int(datetime(y, m, d, h, tzinfo=UTC).timestamp() * 1000)  # noqa: E731
        payload = {"symbol": "AAPL", "candles": [
            {"open": 1, "high": 2, "low": 1, "close": 1.5, "volume": 10, "datetime": ms(2026, 9, 30, 5)},
            {"open": 1, "high": 2, "low": 1, "close": 1.7, "volume": 10, "datetime": ms(2026, 10, 1, 5)}]}
        cutoff = datetime(2026, 10, 1, 20, 10, tzinfo=UTC)
        rows = parse.parse_price_history(payload, "AAPL", self.now, "2026-10-01", "S1", cutoff)
        self.assertEqual([r["candle_date"] for r in rows], ["2026-09-30", "2026-10-01"])
        self.assertEqual([r["is_final"] for r in rows], [True, False])   # pulled before the close
        rows = parse.parse_price_history(payload, "AAPL", cutoff + timedelta(minutes=1),
                                         "2026-10-01", "S1", cutoff)
        self.assertEqual([r["is_final"] for r in rows], [True, True])

    def test_session_date_is_new_york_not_utc(self):
        self.assertEqual(str(parse.ny_today(datetime(2026, 10, 2, 1, 30, tzinfo=UTC))), "2026-10-01")

    def test_symbol_mapping(self):
        self.assertEqual(C.to_schwab_symbol("BRK.B"), "BRK/B")
        self.assertEqual(C.to_schwab_symbol("aapl"), "AAPL")


class WriteOnce(unittest.TestCase):
    rows = [{"ticker": "AAPL", "x": 1}]

    def test_same_day_repull_goes_to_new_file_and_nothing_is_overwritten(self):
        with tempfile.TemporaryDirectory() as tmp:
            w1 = store.SnapshotWriter(tmp, "2026-10-01", "20261001T190000Z", today="2026-10-01")
            p1 = w1.write("quotes", self.rows)
            p1b = w1.write("quotes", self.rows)
            w2 = store.SnapshotWriter(tmp, "2026-10-01", "20261001T203000Z", today="2026-10-01")
            p2 = w2.write("quotes", [{"ticker": "AAPL", "x": 2}])
            self.assertEqual(len({p1, p1b, p2}), 3)
            self.assertEqual(pd.read_parquet(p1)["x"].tolist(), [1])
            # a writer that reuses a snapshot id still cannot clobber part 1
            w3 = store.SnapshotWriter(tmp, "2026-10-01", "20261001T190000Z", today="2026-10-01")
            p3 = w3.write("quotes", [{"ticker": "AAPL", "x": 3}])
            self.assertNotIn(p3, (p1, p1b))
            self.assertEqual(pd.read_parquet(p1)["x"].tolist(), [1])
            self.assertEqual(len(store.read_kind(tmp, "quotes", "2026-10-01")), 4)
            self.assertIsNone(w1.write("quotes", []))

    def test_past_date_with_data_is_refused(self):
        with tempfile.TemporaryDirectory() as tmp:
            store.SnapshotWriter(tmp, "2026-10-01", "A", today="2026-10-01").write(
                "pricehistory", self.rows)
            late = store.SnapshotWriter(tmp, "2026-10-01", "B", today="2026-10-02")
            with self.assertRaises(store.WriteOnceError):
                late.write("pricehistory", self.rows)
            self.assertEqual(len(list((Path(tmp) / "pricehistory" / "date=2026-10-01").iterdir())), 1)
            # an empty past date may be back-filled once (price history only, see CLI)
            store.SnapshotWriter(tmp, "2026-09-30", "B", today="2026-10-02").write(
                "pricehistory", self.rows)

    def test_cli_refuses_live_kinds_for_a_past_date(self):
        sys.path.insert(0, str(Path(C.__file__).parents[2] / "scripts"))
        import schwab_pull
        with tempfile.TemporaryDirectory() as tmp:
            rc = schwab_pull.main(["quotes", "--date", "2020-01-02", "--universe", "AAPL",
                                   "--data-root", tmp])
            self.assertEqual(rc, 2)
            self.assertEqual(list(Path(tmp).iterdir()), [])


class PullLoops(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp()
        self.uni = pd.DataFrame({"ticker": ["AAPL", "BRK.B", "ZZZZ"],
                                 "schwab_symbol": ["AAPL", "BRK/B", "ZZZZ"]})
        self.writer = store.SnapshotWriter(self.tmp, "2026-10-01", "S1", today="2026-10-01")
        self.log = store.PullLog(Path(self.tmp) / "pull_log.sqlite")

    def client(self, get):
        s = FakeSession(post=[Resp(200, TOKEN)], get=get)
        cl, _ = make_client(self.tmp, s)
        cl.login_with_redirect("https://127.0.0.1/?code=c")
        return cl, s

    def test_quotes_resume_skips_done_names(self):
        cl, s = self.client([Resp(200, QUOTE_PAYLOAD), Resp(200, {"errors": {"invalidSymbols": ["ZZZZ"]}})])
        r = pull.pull_quotes(cl, self.uni, self.writer, self.log, "2026-10-01", "S1",
                             progress=lambda *_: None)
        self.assertEqual(r, {"todo": 3, "ok": 2})
        self.assertEqual(s.calls[-1][2]["symbols"], "AAPL,BRK/B,ZZZZ")
        self.assertEqual(self.log.done("2026-10-01", "quotes"), {"AAPL", "BRK.B"})
        r = pull.pull_quotes(cl, self.uni, self.writer, self.log, "2026-10-01", "S1",
                             progress=lambda *_: None)
        self.assertEqual(r["todo"], 1)                               # only the failed name
        self.assertEqual(s.calls[-1][2]["symbols"], "ZZZZ")
        self.assertEqual(self.log.summary("2026-10-01")[("quotes", "ok")], 2)

    def test_big_chain_falls_back_to_month_windows(self):
        exps = {"expirationList": [
            {"expirationDate": "2026-10-16", "expirationType": "S", "standard": True},
            {"expirationDate": "2026-10-23", "expirationType": "W", "standard": True},
            {"expirationDate": "2026-11-20", "expirationType": "S", "standard": True}]}
        cl, s = self.client([Resp(400, {"message": "Body buffer overflow"}), Resp(200, exps),
                             Resp(200, chain_payload(("2026-10-16", "2026-10-23"))),
                             Resp(200, chain_payload(("2026-11-20",)))])
        rows, exp_rows, status, err = pull.fetch_chain_rows(cl, "AAPL", "AAPL", "2026-10-01", "S1")
        self.assertEqual((status, len(rows), len(exp_rows)), ("ok", 9, 3))
        self.assertEqual((s.calls[-2][2]["fromDate"], s.calls[-2][2]["toDate"]),
                         ("2026-10-16", "2026-10-23"))
        self.assertEqual(s.calls[-1][2]["fromDate"], "2026-11-20")


    def test_window_that_fails_is_retried_one_expiry_at_a_time(self):
        exps = {"expirationList": [{"expirationDate": e, "expirationType": "S"}
                                   for e in ("2026-10-16", "2026-10-23", "2026-11-20")]}
        over = Resp(400, {"message": "Body buffer overflow"})
        cl, s = self.client([Resp(200, exps), over, Resp(200, chain_payload(("2026-10-16",))),
                             Resp(200, chain_payload(("2026-10-23",))),
                             Resp(200, chain_payload(("2026-11-20",)))])
        rows, _, status, _ = pull.fetch_chain_rows(cl, "SPY", "SPY", "2026-10-01", "S1",
                                                   force_split=True)
        self.assertEqual((status, len(rows)), ("ok", 9))
        # an expiry that still fails: rows kept, name logged as error (so it is retried)
        cl, s = self.client([Resp(200, exps), over, Resp(200, chain_payload(("2026-10-16",))),
                             over, Resp(200, chain_payload(("2026-11-20",)))])
        rows, _, status, err = pull.fetch_chain_rows(cl, "SPY", "SPY", "2026-10-01", "S1",
                                                     force_split=True)
        self.assertEqual((status, len(rows)), ("error", 6))
        self.assertIn("2026-10-23", err)


class Acceptance(unittest.TestCase):
    """The checker on a synthetic 5-day archive: passes when clean, fails when broken."""

    DAYS = ["2026-10-05", "2026-10-06", "2026-10-07", "2026-10-08", "2026-10-09"]

    def build(self, tmp, drop_quotes_on=None, bad_close=False, crossed=False, stale=False,
              drop_expiry=False):
        names = list(store.REFERENCE_NAMES) + [f"N{i:03d}" for i in range(195)]
        panel = []
        for d in self.DAYS:
            ts = datetime.fromisoformat(d + "T19:00:00+00:00")
            uni = pd.DataFrame({"ticker": names, "schwab_symbol": names,
                                "in_cap2000": [i < 100 for i in range(len(names))]})
            p = store.universe_path(tmp, d, "cap150")
            p.parent.mkdir(parents=True)
            uni.to_csv(p, index=False)
            w = store.SnapshotWriter(tmp, d, "S", today=d)
            qn = names[:150] if d == drop_quotes_on else names
            qt = ts - timedelta(days=1) if stale else ts
            w.write("quotes", [{"ticker": t, "quote_time_utc": qt, "snapshot": "S"} for t in qn])
            w.write("pricehistory", [{"ticker": t, "candle_date": d, "is_final": True,
                                      "close": 100.02 if (bad_close and t.startswith("N00")) else 100.0,
                                      "pulled_at_utc": ts} for t in names])
            exps = [str(x) for x in store.monthly_expiries(d, "2027-01-31") if str(x) > d]
            ch = [{"ticker": t, "expiry": e, "bid": 1.2 if crossed else 1.0, "ask": 1.1,
                   "snapshot": "S"} for t in names for e in (exps[1:] if drop_expiry else exps)]
            w.write("chains", ch)
            w.write("expirations", [{"ticker": t, "expiry": e, "expiration_type": "S"}
                                    for t in store.REFERENCE_NAMES for e in exps])
            w.write("hours", [{"market": "equity", "product": "EQ",
                               "regular_start_utc": datetime.fromisoformat(d + "T13:30:00+00:00"),
                               "regular_end_utc": datetime.fromisoformat(d + "T20:00:00+00:00")}])
            panel += [{"ticker": t, "date": d, "close": 100.0} for t in names]
        pp = Path(tmp) / "panel.parquet"
        pd.DataFrame(panel).to_parquet(pp)
        return pp

    def statuses(self, **kw):
        with tempfile.TemporaryDirectory() as tmp:
            pp = self.build(tmp, **kw)
            return [r["status"] for r in checks.run_all(tmp, pp)]

    def test_clean_archive_passes_all_four(self):
        self.assertEqual(self.statuses(), ["PASS"] * 4)

    def test_each_break_fails_its_own_test(self):
        self.assertEqual(self.statuses(drop_quotes_on="2026-10-07"), ["FAIL", "PASS", "PASS", "PASS"])
        self.assertEqual(self.statuses(bad_close=True), ["PASS", "FAIL", "PASS", "PASS"])
        self.assertEqual(self.statuses(crossed=True), ["PASS", "PASS", "FAIL", "PASS"])
        self.assertEqual(self.statuses(drop_expiry=True), ["PASS", "PASS", "FAIL", "PASS"])
        self.assertEqual(self.statuses(stale=True), ["PASS", "PASS", "PASS", "FAIL"])

    def test_smoke_test_universe_never_counts_for_coverage(self):
        with tempfile.TemporaryDirectory() as tmp:
            pp = self.build(tmp)
            d = Path(tmp) / "universe" / "date=2026-10-07"
            (d / "universe_cap150.csv").rename(d / "universe_custom.csv")
            r = checks.run_all(tmp, pp)[0]
            self.assertEqual(r["status"], "NOT_EVALUABLE")

    def test_empty_archive_is_not_evaluable(self):
        with tempfile.TemporaryDirectory() as tmp:
            self.assertEqual({r["status"] for r in checks.run_all(tmp, Path(tmp) / "none.parquet")},
                             {"NOT_EVALUABLE"})

    def test_calendar(self):
        self.assertFalse(store.is_trading_day("2026-04-03"))         # Good Friday
        self.assertFalse(store.is_trading_day("2026-11-26"))         # Thanksgiving
        self.assertTrue(store.is_trading_day("2026-10-12"))          # Columbus Day: open
        self.assertEqual(str(store.monthly_expiries("2025-04-01", "2025-04-30")[0]), "2025-04-17")
        self.assertIsNone(checks.latest_consecutive_days(
            ["2026-10-05", "2026-10-06", "2026-10-08", "2026-10-09", "2026-10-12"]))
        self.assertEqual(len(checks.latest_consecutive_days(
            ["2026-10-08", "2026-10-09", "2026-10-12", "2026-10-13", "2026-10-14"])), 5)


def _cli():
    sys.path.insert(0, str(Path(C.__file__).parents[2] / "scripts"))
    import schwab_check
    import schwab_pull
    return schwab_pull, schwab_check


def _no_client(*_a, **_k):
    raise AssertionError("this test must stop before a Schwab client is built")


def write_panel(tmp, panel_date="2026-09-30"):
    """A tiny working panel: two dates, the eligibility flags, a close."""
    rows = []
    for d, names in (("2025-12-01", ["OLD"]), (panel_date, ["AAPL", "BRK.B", "NA", "TINY", "MID"])):
        for t in names:
            rows.append({"ticker": t, "date": d, "close": 10.0,
                         "eligible_cap2000": t in ("AAPL", "BRK.B"),
                         "eligible_cap500": t in ("AAPL", "BRK.B", "MID"),
                         "eligible_cap150": t != "OLD"})
    p = Path(tmp) / "panel.parquet"
    pd.DataFrame(rows).to_parquet(p)
    return p


class WindowsHandoff(unittest.TestCase):
    """WO-41b: the collector on a machine that has no panel and no Mac paths."""

    def test_root_resolution_with_and_without_env(self):
        with tempfile.TemporaryDirectory() as tmp:
            tmp = Path(tmp).resolve()
            (tmp / "repo" / "final" / "src" / "schwab").mkdir(parents=True)
            (tmp / "mac" / "final").mkdir(parents=True)
            here = tmp / "repo" / "final" / "src" / "schwab" / "store.py"
            mac = tmp / "mac" / "final"
            r = store.resolve_main_root
            # 1. the env var wins, given as the repo root or as the final folder
            self.assertEqual(r({"PIPE_DREAM_ROOT": str(tmp / "repo")}, here, mac, "darwin"),
                             tmp / "repo" / "final")
            self.assertEqual(r({"PIPE_DREAM_ROOT": str(tmp / "repo" / "final")}, here, mac, "win32"),
                             tmp / "repo" / "final")
            self.assertEqual(r({"PIPE_DREAM_ROOT": str(tmp / "new")}, here, mac, "win32"),
                             tmp / "new" / "final")
            # 2. no env, on the Mac: the main checkout when it exists (today's behaviour)
            self.assertEqual(r({}, here, mac, "darwin"), mac)
            # 3. no env, elsewhere (or no main checkout): the checkout the file sits in
            self.assertEqual(r({}, here, mac, "win32"), tmp / "repo" / "final")
            self.assertEqual(r({}, here, tmp / "absent", "darwin"), tmp / "repo" / "final")
            self.assertEqual(r({"PIPE_DREAM_ROOT": "  "}, here, mac, "win32"), tmp / "repo" / "final")
        # the module default still hangs off the resolved root; the data root stays overridable
        self.assertEqual(store.DEFAULT_DATA_ROOT, store.MAIN_ROOT / "data" / "schwab")
        self.assertEqual(store.MAIN_ROOT.name, "final")
        with mock.patch.dict(os.environ, {"PIPE_DREAM_SCHWAB_DATA": "/x/env"}):
            self.assertEqual(store.data_root(), Path("/x/env"))
            self.assertEqual(store.data_root("/x/flag"), Path("/x/flag"))

    def test_export_universe_round_trip(self):
        schwab_pull, _ = _cli()
        with tempfile.TemporaryDirectory() as tmp, \
                mock.patch.object(schwab_pull, "make_client", _no_client):
            panel = write_panel(tmp)
            out = Path(tmp) / "win" / "universe_cap150.csv"
            self.assertEqual(schwab_pull.main(["export-universe", "--universe", "cap150"]), 2)
            self.assertEqual(schwab_pull.main(["export-universe", "--universe", "cap150", "--out",
                                               str(out), "--panel", str(Path(tmp) / "no.parquet")]), 2)
            self.assertFalse(out.exists())
            self.assertEqual(schwab_pull.main(["export-universe", "--universe", "cap150", "--out",
                                               str(out), "--panel", str(panel)]), 0)
            mac = store.build_universe("cap150", panel)
            # the "Windows" side: no panel anywhere
            win = store.build_universe(str(out), Path(tmp) / "no_panel.parquet")
            for col in store.EXPORT_COLUMNS + ("is_benchmark", "in_cap500", "in_cap150"):
                self.assertEqual(win[col].tolist(), mac[col].tolist(), col)
            self.assertEqual(set(win["ticker"]),
                             {"AAPL", "BRK.B", "NA", "TINY", "MID"} | set(store.BENCHMARKS)
                             | set(store.REFERENCE_NAMES))
            by = win.set_index("ticker")
            self.assertEqual(by.at["BRK.B", "schwab_symbol"], "BRK/B")
            self.assertIn("NA", by.index)                           # not read as a missing value
            self.assertTrue(by.at["AAPL", "in_cap2000"])
            self.assertFalse(by.at["TINY", "in_cap2000"])
            self.assertEqual(win["in_cap2000"].dtype, bool)
            self.assertEqual(set(win["panel_date"]), {"2026-09-30"})
            self.assertEqual(set(win["universe_name"]), {"cap150"})
            # frozen under the tier's name, so the checker counts a Windows day
            root = Path(tmp) / "data"
            df, path, is_new = store.frozen_universe(root, "2026-10-02", str(out),
                                                     Path(tmp) / "no_panel.parquet")
            self.assertTrue(is_new)
            self.assertEqual(path.name, "universe_cap150.csv")
            self.assertEqual(checks.target_dates(root), ["2026-10-02"])
            again, path2, is_new2 = store.frozen_universe(root, "2026-10-02", str(out))
            self.assertEqual((path2, is_new2), (path, False))
            self.assertEqual(again["ticker"].tolist(), win["ticker"].tolist())
            self.assertEqual(again["in_cap2000"].tolist(), win["in_cap2000"].tolist())
            self.assertEqual(checks._universe_for(root, "2026-10-02")["ticker"].tolist(),
                             win["ticker"].tolist())
            # a plain ticker csv is still a custom list
            plain = Path(tmp) / "mine.csv"
            plain.write_text("ticker\nAAPL\nNA\n")
            self.assertEqual(store.universe_label(str(plain)), "custom")
            self.assertEqual(store.build_universe(str(plain), panel)["ticker"].tolist()[:2],
                             ["AAPL", "NA"])

    def test_stale_universe_warns_then_refuses(self):
        schwab_pull, _ = _cli()
        uni = pd.DataFrame({"ticker": ["AAPL"], "panel_date": ["2026-09-30"]})
        f = store.universe_freshness
        self.assertEqual(f(uni, "2026-10-01"), ("ok", 1))
        self.assertEqual(f(uni, "2026-10-10"), ("ok", 10))
        self.assertEqual(f(uni, "2026-10-11"), ("warn", 11))
        self.assertEqual(f(uni, "2026-11-14"), ("warn", 45))
        self.assertEqual(f(uni, "2026-11-15"), ("refuse", 46))
        self.assertEqual(f(pd.DataFrame({"ticker": ["AAPL"]}), "2026-10-01"), ("refuse", None))
        self.assertEqual(f(pd.DataFrame({"ticker": ["A"], "panel_date": ["None"],
                                         "exported_utc": ["2026-10-01T12:00:00Z"]}),
                           "2026-10-13"), ("warn", 12))
        with tempfile.TemporaryDirectory() as tmp, \
                mock.patch.object(schwab_pull, "make_client", _no_client):
            out = Path(tmp) / "universe_cap150.csv"
            store.export_universe("cap150", out, write_panel(tmp))
            said = []
            self.assertIsNone(schwab_pull.check_universe_file(str(out), "2026-10-05", said.append))
            self.assertEqual(said, [])
            self.assertIsNone(schwab_pull.check_universe_file(str(out), "2026-10-20", said.append))
            self.assertIn("WARNING: STALE UNIVERSE", said[0])        # loud, and the pull goes on
            self.assertEqual(schwab_pull.check_universe_file(str(out), "2026-12-01", said.append), 4)
            self.assertIn("REFUSED", said[1])
            self.assertIsNone(schwab_pull.check_universe_file("cap150", "2030-01-01", said.append))
            self.assertIsNone(schwab_pull.check_universe_file("AAPL,BRK.B", "2030-01-01", said.append))

    def test_cli_refuses_old_or_missing_universe_file_before_any_client(self):
        schwab_pull, _ = _cli()
        with tempfile.TemporaryDirectory() as tmp, \
                mock.patch.object(schwab_pull, "make_client", _no_client):
            out = Path(tmp) / "universe_cap150.csv"
            store.export_universe("cap150", out, write_panel(tmp, panel_date="2026-01-05"))
            data = Path(tmp) / "data"
            rc = schwab_pull.main(["pricehistory", "--date", "2026-09-29", "--universe", str(out),
                                   "--data-root", str(data)])
            self.assertEqual(rc, 4)                                  # 267 days old
            rc = schwab_pull.main(["pricehistory", "--date", "2026-09-29", "--universe",
                                   str(Path(tmp) / "typo.csv"), "--data-root", str(data)])
            self.assertEqual(rc, 2)                                  # not read as a ticker list
            self.assertFalse(data.exists())
            with self.assertRaises(FileNotFoundError):
                store.build_universe(r"C:\pipe_dream\universe_cap150.csv")

    def test_closed_day_exits_zero_and_writes_nothing(self):
        schwab_pull, _ = _cli()
        with tempfile.TemporaryDirectory() as tmp, \
                mock.patch.object(schwab_pull, "make_client", _no_client):
            out = Path(tmp) / "universe_cap150.csv"
            store.export_universe("cap150", out, write_panel(tmp))
            data = Path(tmp) / "data"
            for closed in ("2026-09-26", "2026-09-07"):              # a Saturday, Labor Day
                rc = schwab_pull.main(["pricehistory", "--date", closed, "--universe", str(out),
                                       "--data-root", str(data)])
                self.assertEqual(rc, 0)
            self.assertFalse(data.exists())

    def test_unscheduled_closure_freezes_no_universe(self):
        """Schwab says closed on a calendar trading day: exit 0, only the hours row."""
        schwab_pull, _ = _cli()
        with tempfile.TemporaryDirectory() as tmp:
            closed = {"equity": {"equity": {"date": "2026-09-29", "isOpen": False}}}
            s = FakeSession(post=[Resp(200, TOKEN)], get=[Resp(200, closed)])
            cl, _ = make_client(tmp, s)
            cl.login_with_redirect("https://127.0.0.1/?code=c")
            out = Path(tmp) / "universe_cap150.csv"
            store.export_universe("cap150", out, write_panel(tmp))
            data = Path(tmp) / "data"
            with mock.patch.object(schwab_pull, "make_client", lambda args: cl):
                rc = schwab_pull.main(["pricehistory", "--date", "2026-09-29", "--universe",
                                       str(out), "--data-root", str(data)])
            self.assertEqual(rc, 0)
            self.assertFalse((data / "universe").exists())
            self.assertFalse((data / "pricehistory").exists())
            self.assertEqual(checks.target_dates(data), [])
            self.assertEqual(len([c for c in s.calls if c[0] == "GET"]), 1)

    def test_open_day_freezes_the_exported_universe_as_cap150(self):
        schwab_pull, _ = _cli()
        with tempfile.TemporaryDirectory() as tmp:
            hours = {"equity": {"EQ": {"date": "2026-09-29", "isOpen": True, "sessionHours": {
                "regularMarket": [{"start": "2026-09-29T09:30:00-04:00",
                                   "end": "2026-09-29T16:00:00-04:00"}]}}}}
            candles = lambda url, params: Resp(200, {"symbol": params["symbol"], "candles": [  # noqa: E731
                {"open": 1, "high": 2, "low": 1, "close": 1.5, "volume": 10,
                 "datetime": int(datetime(2026, 9, 28, 5, tzinfo=UTC).timestamp() * 1000)}]})
            s = FakeSession(post=[Resp(200, TOKEN)], get=[Resp(200, hours)] + [candles] * 20)
            cl, _ = make_client(tmp, s)
            cl.login_with_redirect("https://127.0.0.1/?code=c")
            out = Path(tmp) / "universe_cap150.csv"
            n = len(store.export_universe("cap150", out, write_panel(tmp)))
            data = Path(tmp) / "data"
            with mock.patch.object(schwab_pull, "make_client", lambda args: cl):
                rc = schwab_pull.main(["pricehistory", "--date", "2026-09-29", "--universe",
                                       str(out), "--data-root", str(data)])
            self.assertEqual(rc, 0)
            self.assertEqual(checks.target_dates(data), ["2026-09-29"])
            got = store.read_kind(data, "pricehistory", "2026-09-29")
            self.assertEqual(got["ticker"].nunique(), n)
            self.assertIn("BRK/B", {c[2].get("symbol") for c in s.calls if c[0] == "GET"})

    def test_status_min_refresh_days_exit_codes(self):
        schwab_pull, _ = _cli()
        with tempfile.TemporaryDirectory() as tmp:
            s = FakeSession(post=[Resp(200, TOKEN)])
            cl, clock = make_client(tmp, s)
            run = lambda *a: schwab_pull.main(["status", "--data-root", tmp, *a])  # noqa: E731
            with mock.patch.object(schwab_pull, "make_client", lambda args: cl):
                self.assertEqual(run("--min-refresh-days", "2"), 11)     # never logged in
                self.assertEqual(run(), 0)                               # plain status: unchanged
                cl.login_with_redirect("https://127.0.0.1/?code=c")
                self.assertEqual(run("--min-refresh-days", "2"), 0)
                clock.t += 5.5 * 86400
                self.assertEqual(run("--min-refresh-days", "2"), 10)     # 1.5 days left
                clock.t += 2 * 86400
                self.assertEqual(run("--min-refresh-days", "2"), 11)     # expired
                self.assertEqual(run(), 0)
            self.assertEqual([c[0] for c in s.calls], ["POST"])          # status calls no API

            def no_creds(args):
                raise C.LoginRequired("SCHWAB_APP_KEY / SCHWAB_APP_SECRET not found")
            with mock.patch.object(schwab_pull, "make_client", no_creds):
                self.assertEqual(run("--min-refresh-days", "2"), 12)

    def test_windows_paths_and_file_names(self):
        self.assertTrue(store.looks_like_path(r"C:\pipe_dream\universe_cap150.csv"))
        self.assertTrue(store.looks_like_path("universe_cap150.csv"))
        self.assertTrue(store.looks_like_path("/Users/x/u.txt"))
        for name in ("cap150", "panel", "AAPL,MSFT", "BRK.B", "AAPL,BRK.B"):
            self.assertFalse(store.looks_like_path(name), name)
        # every folder and file name the collector creates is legal on NTFS
        root = PureWindowsPath(r"C:\pipe_dream\final\data\schwab")
        snap = store.new_snapshot_id(datetime(2026, 10, 2, 18, 45, 7, tzinfo=UTC))
        with tempfile.TemporaryDirectory() as tmp:
            w = store.SnapshotWriter(tmp, "2026-10-02", snap, today="2026-10-02")
            made = [w.write(k, [{"ticker": "AAPL"}]).relative_to(tmp) for k in store.KINDS]
            made.append(store.universe_path(tmp, "2026-10-02", "cap150").relative_to(tmp))
        for rel in made:
            win = root.joinpath(*rel.parts)
            self.assertEqual(win.parts[:5], ("C:\\", "pipe_dream", "final", "data", "schwab"))
            for part in rel.parts:
                self.assertFalse(set(part) & set('<>:"/\\|?*'), part)
                self.assertFalse(part.endswith((".", " ")), part)
        self.assertEqual(str(PureWindowsPath(r"C:\pipe_dream") / "final" / "data" / "schwab"),
                         str(root))
        # the token file must stay outside the repo on either OS
        with self.assertRaises(ValueError):
            C.TokenStore(Path(tempfile.gettempdir()) / "r" / "final" / "tok.json",
                         repo_root=Path(tempfile.gettempdir()) / "r")

    def test_write_once_without_hard_links_and_token_save_without_chmod(self):
        with tempfile.TemporaryDirectory() as tmp, \
                mock.patch.object(os, "link", side_effect=OSError("no hard links")), \
                mock.patch.object(os, "chmod", side_effect=PermissionError("no chmod")):
            w = store.SnapshotWriter(tmp, "2026-10-02", "S", today="2026-10-02")
            p1 = w.write("quotes", [{"ticker": "AAPL", "x": 1}])
            p2 = w.write("quotes", [{"ticker": "AAPL", "x": 2}])
            self.assertNotEqual(p1, p2)
            self.assertEqual(pd.read_parquet(p1)["x"].tolist(), [1])
            self.assertEqual(sorted(x.name for x in p1.parent.iterdir()), [p1.name, p2.name])
            ts = C.TokenStore(Path(tmp) / "tok.json")
            ts.save({"a": 1})
            ts.save({"a": 2})                                        # replaces the old file
            self.assertEqual(ts.load(), {"a": 2})
            self.assertEqual([x.name for x in Path(tmp).glob("tok*")], ["tok.json"])

    def test_checker_reads_a_synced_folder_with_both_machines_logs(self):
        _, schwab_check = _cli()
        with tempfile.TemporaryDirectory() as tmp:
            pp = Acceptance().build(tmp)                             # 5 days, cap150 universe files
            days = Acceptance.DAYS
            # day 1 pulled on the Mac, days 2-5 on Windows: "NOOPT" has no listed options
            for d in days:
                u = store.universe_path(tmp, d, "cap150")
                df = pd.read_csv(u)
                extra = pd.DataFrame({"ticker": [f"NOOPT{i}" for i in range(5)],
                                      "schwab_symbol": [f"NOOPT{i}" for i in range(5)],
                                      "in_cap2000": False})
                pd.concat([df, extra]).to_csv(u, index=False)
                w = store.SnapshotWriter(tmp, d, "S2", today=d)
                ts = datetime.fromisoformat(d + "T19:00:00+00:00")
                w.write("quotes", [{"ticker": t, "quote_time_utc": ts, "snapshot": "S2"}
                                   for t in extra["ticker"]])
                w.write("pricehistory", [{"ticker": t, "candle_date": d, "is_final": True,
                                          "close": 100.0, "pulled_at_utc": ts}
                                         for t in extra["ticker"]])
            empties = [(f"NOOPT{i}", "empty", 0, "") for i in range(5)]
            self.assertEqual(checks.t1_coverage(tmp, None)["status"], "FAIL")   # 200 of 205
            mac = store.PullLog(Path(tmp) / "pull_log.sqlite")
            mac.record(days[0], "chains", empties, "S")
            mac.close()
            self.assertEqual(checks.t1_coverage(tmp, store.MergedPullLog(tmp))["status"], "FAIL")
            win = store.PullLog(Path(tmp) / "pull_log_windows.sqlite")
            for d in days[1:]:
                win.record(d, "chains", empties, "S")
            win.record(days[0], "chains", [("NOOPT0", "error", 0, "x")], "S")   # never downgrades
            win.close()
            merged = store.MergedPullLog(tmp)
            self.assertEqual(len(merged), 2)
            self.assertEqual(merged.best_status(days[0], "chains")["NOOPT0"], "empty")
            self.assertEqual(checks.t1_coverage(tmp, merged)["status"], "PASS")
            merged.close()
            self.assertEqual(schwab_check.main(["--data-root", tmp, "--panel", str(pp)]), 0)


if __name__ == "__main__":
    unittest.main()
