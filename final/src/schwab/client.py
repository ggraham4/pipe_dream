"""Schwab market-data HTTP client: OAuth, token file, rate limiter, retries.

MARKET DATA ONLY. Every request goes through `assert_market_data_url`, which
allows only https://api.schwabapi.com/marketdata/v1/... and the two OAuth
paths, and refuses anything containing "/accounts" or "/orders" (also
"/trader/", the Accounts and Trading product root). There are no account or
order methods on this client, and a unit test fails if one is added.

Secrets: the app key/secret come from the environment or
~/.config/pipe_dream/secrets.env and are never printed, logged or written.
The token file lives outside the repo (~/.config/pipe_dream/schwab_token.json,
mode 600). The pasted redirect URL carries the one-time auth code, so it is
never echoed or stored.
"""
from __future__ import annotations

import base64
import json
import os
import random
import threading
import time
from collections import deque
from pathlib import Path
from urllib.parse import parse_qs, quote, unquote, urlencode, urlsplit

API_HOST = "api.schwabapi.com"
BASE = f"https://{API_HOST}"
MARKETDATA_PREFIX = "/marketdata/v1/"
AUTHORIZE_PATH = "/v1/oauth/authorize"
TOKEN_PATH = "/v1/oauth/token"
ALLOWED_OAUTH_PATHS = (AUTHORIZE_PATH, TOKEN_PATH)
FORBIDDEN_FRAGMENTS = ("/accounts", "/orders", "/trader/", "/userpreference")

SECRETS_ENV = Path.home() / ".config" / "pipe_dream" / "secrets.env"
TOKEN_FILE = Path.home() / ".config" / "pipe_dream" / "schwab_token.json"
CALLBACK_URL = "https://127.0.0.1"

ACCESS_TOKEN_SKEW_S = 120          # refresh this long before expiry
REFRESH_TOKEN_LIFETIME_S = 7 * 24 * 3600   # Schwab: 7 days, then a browser re-login
DEFAULT_RATE_PER_MIN = 110         # Schwab limit is 120/min; keep headroom


class ForbiddenEndpointError(RuntimeError):
    """Raised before any network I/O when a URL is not a market-data URL."""


class TradingScopeError(RuntimeError):
    """The token response suggests more than market-data scope. Stop and report."""


class LoginRequired(RuntimeError):
    """No usable token: run `schwab_pull.py login`."""


class SchwabHTTPError(RuntimeError):
    def __init__(self, status, message):
        super().__init__(f"HTTP {status}: {message}")
        self.status = status


def assert_market_data_url(url: str) -> str:
    """Return `url` if it is an allowed market-data or OAuth URL, else raise.

    Allowlist, not a blocklist: host must be api.schwabapi.com over https and
    the path must start with /marketdata/v1/ or be one of the two OAuth
    paths. The "/accounts" / "/orders" check runs first and on the decoded,
    lower-cased URL, so it also catches them in a query string or encoded.
    """
    decoded = unquote(unquote(str(url))).lower()
    for frag in FORBIDDEN_FRAGMENTS:
        if frag in decoded:
            raise ForbiddenEndpointError(
                f"refused: URL contains {frag!r}. This collector is market data only "
                "(never-trade rule, Gabe 2026-10-01).")
    parts = urlsplit(str(url))
    if parts.scheme != "https" or parts.hostname != API_HOST:
        raise ForbiddenEndpointError(f"refused: not https://{API_HOST}")
    path = parts.path
    if ".." in path or "//" in path:
        raise ForbiddenEndpointError("refused: path traversal")
    if not (path.startswith(MARKETDATA_PREFIX) or path in ALLOWED_OAUTH_PATHS):
        raise ForbiddenEndpointError(
            f"refused: path {path!r} is outside {MARKETDATA_PREFIX} and the OAuth paths")
    return str(url)


def load_app_credentials(env=None, secrets_path=SECRETS_ENV):
    """(key, secret) from the environment, else from secrets.env. Never printed."""
    env = os.environ if env is None else env
    vals = {k: env.get(k) for k in ("SCHWAB_APP_KEY", "SCHWAB_APP_SECRET")}
    if not all(vals.values()) and Path(secrets_path).exists():
        for line in Path(secrets_path).read_text().splitlines():
            line = line.strip()
            if line.startswith("export "):
                line = line[len("export "):].strip()
            if "=" not in line or line.startswith("#"):
                continue
            k, v = line.split("=", 1)
            k = k.strip()
            if k in vals and not vals[k]:
                vals[k] = v.strip().strip('"').strip("'")
    if not all(vals.values()):
        raise LoginRequired(
            "SCHWAB_APP_KEY / SCHWAB_APP_SECRET not found in the environment or "
            f"{secrets_path}")
    return vals["SCHWAB_APP_KEY"], vals["SCHWAB_APP_SECRET"]


class RateLimiter:
    """Sliding window: at most `max_calls` in any `period` seconds."""

    def __init__(self, max_calls=DEFAULT_RATE_PER_MIN, period=60.0,
                 clock=time.monotonic, sleep=time.sleep):
        if max_calls < 1:
            raise ValueError("max_calls must be >= 1")
        self.max_calls, self.period = int(max_calls), float(period)
        self._clock, self._sleep = clock, sleep
        self._calls = deque()
        self._lock = threading.Lock()

    def acquire(self):
        with self._lock:
            while True:
                now = self._clock()
                while self._calls and now - self._calls[0] >= self.period:
                    self._calls.popleft()
                if len(self._calls) < self.max_calls:
                    self._calls.append(now)
                    return
                self._sleep(max(self.period - (now - self._calls[0]), 0.001))


class TokenStore:
    """JSON token file outside the repo, mode 600, written atomically."""

    def __init__(self, path=TOKEN_FILE, repo_root=None):
        self.path = Path(path).expanduser()
        if repo_root is not None:
            try:
                self.path.resolve().relative_to(Path(repo_root).resolve())
            except ValueError:
                pass
            else:
                raise ValueError("token file must live outside the git repo")

    def load(self):
        if not self.path.exists():
            return None
        return json.loads(self.path.read_text())

    def save(self, tok: dict):
        self.path.parent.mkdir(parents=True, exist_ok=True)
        tmp = self.path.with_name(self.path.name + ".tmp")
        fd = os.open(str(tmp), os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
        with os.fdopen(fd, "w") as f:
            json.dump(tok, f)
        os.chmod(tmp, 0o600)
        os.replace(tmp, self.path)


def check_scope(token_response: dict):
    """Stop if the token response names anything that looks like trading scope.

    Schwab normally returns scope "api" for every app, so this cannot prove
    the app is market-data-only; the product list on the developer portal is
    the real control (see the doc). It does catch an explicit trading scope.
    """
    scope = str(token_response.get("scope", "")).lower()
    for bad in ("trad", "account", "order"):
        if bad in scope:
            raise TradingScopeError(
                f"token scope {scope!r} looks like trading/account scope. STOP: this "
                "collector must only ever hold a Market Data Production token.")
    return scope


class SchwabClient:
    """Market-data-only client. See module docstring."""

    def __init__(self, app_key=None, app_secret=None, token_store=None, session=None,
                 rate_limiter=None, callback_url=CALLBACK_URL, max_retries=5,
                 clock=time.time, sleep=time.sleep, timeout=30):
        if app_key is None or app_secret is None:
            app_key, app_secret = load_app_credentials()
        self._key, self._secret = app_key, app_secret
        self.tokens = token_store or TokenStore()
        if session is None:
            import requests
            session = requests.Session()
        self.session = session
        self.limiter = rate_limiter or RateLimiter()
        self.callback_url = callback_url
        self.max_retries = max_retries
        self._clock, self._sleep, self.timeout = clock, sleep, timeout
        self.n_requests = 0

    def __repr__(self):                       # never expose the key or secret
        return "SchwabClient(market-data only)"

    # ------------------------------------------------------------- OAuth
    def authorize_url(self):
        q = urlencode({"client_id": self._key, "redirect_uri": self.callback_url})
        return assert_market_data_url(f"{BASE}{AUTHORIZE_PATH}?{q}")

    def _basic(self):
        raw = f"{self._key}:{self._secret}".encode()
        return {"Authorization": "Basic " + base64.b64encode(raw).decode(),
                "Content-Type": "application/x-www-form-urlencoded"}

    def _token_post(self, data):
        url = assert_market_data_url(f"{BASE}{TOKEN_PATH}")
        r = self.session.post(url, headers=self._basic(), data=data, timeout=self.timeout)
        if r.status_code != 200:
            # body may echo the code/refresh token: report the status only
            raise SchwabHTTPError(r.status_code, "token endpoint refused the request")
        return r.json()

    def _store(self, resp, previous=None):
        check_scope(resp)
        now = self._clock()
        tok = {
            "access_token": resp["access_token"],
            "refresh_token": resp.get("refresh_token") or (previous or {}).get("refresh_token"),
            "scope": resp.get("scope"),
            "token_type": resp.get("token_type", "Bearer"),
            "access_expires_at": now + float(resp.get("expires_in", 1800)),
            # the 7-day clock starts at the browser login, not at each refresh
            "refresh_issued_at": (previous or {}).get("refresh_issued_at", now),
        }
        self.tokens.save(tok)
        return tok

    def login_with_redirect(self, redirected_url: str):
        """Exchange the code in the pasted redirect URL for tokens."""
        qs = parse_qs(urlsplit(redirected_url.strip()).query)
        code = (qs.get("code") or [None])[0]
        if not code:
            raise LoginRequired("no ?code= in the pasted URL (paste the full address-bar URL)")
        resp = self._token_post({"grant_type": "authorization_code", "code": code,
                                 "redirect_uri": self.callback_url})
        return self._store(resp, previous=None)

    def refresh(self):
        tok = self.tokens.load()
        if not tok or not tok.get("refresh_token"):
            raise LoginRequired("no token file: run `schwab_pull.py login`")
        try:
            resp = self._token_post({"grant_type": "refresh_token",
                                     "refresh_token": tok["refresh_token"]})
        except SchwabHTTPError as e:
            if e.status in (400, 401):
                raise LoginRequired("refresh token rejected (7-day lifetime): run "
                                    "`schwab_pull.py login` again") from None
            raise
        return self._store(resp, previous=tok)

    def token_status(self):
        tok = self.tokens.load()
        if not tok:
            return {"logged_in": False}
        now = self._clock()
        return {"logged_in": True,
                "access_seconds_left": int(tok["access_expires_at"] - now),
                "refresh_days_left": round(
                    (tok["refresh_issued_at"] + REFRESH_TOKEN_LIFETIME_S - now) / 86400, 2),
                "scope": tok.get("scope")}

    def _access_token(self):
        tok = self.tokens.load()
        if not tok:
            raise LoginRequired("no token file: run `schwab_pull.py login`")
        if self._clock() >= tok["access_expires_at"] - ACCESS_TOKEN_SKEW_S:
            tok = self.refresh()
        return tok["access_token"]

    # ------------------------------------------------------------- GET
    def get(self, path, params=None, max_retries=None):
        """GET a market-data path (e.g. "quotes"). Rate limited, retried."""
        url = assert_market_data_url(f"{BASE}{MARKETDATA_PREFIX}{path.lstrip('/')}")
        params = {k: v for k, v in (params or {}).items() if v is not None}
        assert_market_data_url(url + ("?" + urlencode(params) if params else ""))
        refreshed_on_401 = False
        last = None
        retries = self.max_retries if max_retries is None else max_retries
        for attempt in range(retries + 1):
            self.limiter.acquire()
            headers = {"Authorization": f"Bearer {self._access_token()}",
                       "Accept": "application/json"}
            try:
                self.n_requests += 1
                r = self.session.get(url, headers=headers, params=params, timeout=self.timeout)
            except LoginRequired:
                raise
            except Exception as e:                         # network error: retry
                last = SchwabHTTPError(0, type(e).__name__)
                self._backoff(attempt)
                continue
            if r.status_code == 200:
                return r.json()
            if r.status_code == 401 and not refreshed_on_401:
                refreshed_on_401 = True
                self.refresh()
                continue
            last = SchwabHTTPError(r.status_code, _short_error(r))
            if r.status_code == 429 or r.status_code >= 500:
                self._backoff(attempt, retry_after=_retry_after(r))
                continue
            raise last                                     # other 4xx: not retryable
        raise last

    def _backoff(self, attempt, retry_after=None):
        delay = retry_after if retry_after is not None else min(60.0, 2.0 ** attempt)
        self._sleep(delay + random.uniform(0, 0.25))

    # ------------------------------------------------------------- market data wrappers
    def quotes(self, symbols, fields="quote,reference,fundamental,regular"):
        return self.get("quotes", {"symbols": ",".join(symbols), "fields": fields,
                                   "indicative": "false"})

    def option_chain(self, symbol, from_date=None, to_date=None, strike_count=None,
                     max_retries=2):
        # few retries: a chain that is too big fails the same way every time
        return self.get("chains", {
            "symbol": symbol, "contractType": "ALL", "strategy": "SINGLE",
            "includeUnderlyingQuote": "true", "fromDate": from_date, "toDate": to_date,
            "strikeCount": strike_count}, max_retries=max_retries)

    def expiration_chain(self, symbol):
        return self.get("expirationchain", {"symbol": symbol})

    def price_history_daily(self, symbol, start_ms, end_ms):
        return self.get("pricehistory", {
            "symbol": symbol, "periodType": "year", "frequencyType": "daily", "frequency": 1,
            "startDate": int(start_ms), "endDate": int(end_ms),
            "needExtendedHoursData": "false", "needPreviousClose": "false"})

    def price_history_minute(self, symbol, start_ms, end_ms, frequency=1):
        return self.get("pricehistory", {
            "symbol": symbol, "periodType": "day", "frequencyType": "minute",
            "frequency": int(frequency), "startDate": int(start_ms), "endDate": int(end_ms),
            "needExtendedHoursData": "false", "needPreviousClose": "false"})

    def market_hours(self, markets=("equity", "option"), date=None):
        return self.get("markets", {"markets": ",".join(markets), "date": date})

    def instruments(self, symbol, projection="symbol-search"):
        return self.get("instruments", {"symbol": symbol, "projection": projection})


def _retry_after(r):
    try:
        return float(r.headers.get("Retry-After"))
    except (TypeError, ValueError, AttributeError):
        return None


def _short_error(r):
    try:
        text = r.text or ""
    except Exception:
        text = ""
    return text[:200].replace("\n", " ")


def to_schwab_symbol(ticker: str) -> str:
    """Sharadar ticker -> Schwab symbol. Share classes: BRK.B -> BRK/B."""
    return str(ticker).strip().upper().replace(".", "/").replace("-", "/")


__all__ = ["SchwabClient", "RateLimiter", "TokenStore", "assert_market_data_url",
           "ForbiddenEndpointError", "TradingScopeError", "LoginRequired",
           "SchwabHTTPError", "load_app_credentials", "check_scope", "to_schwab_symbol",
           "quote"]
