# Schwab Trader API forward market-data collector (WO-41, Phases 0-1)

2026-10-01. Branch `wo41-schwab-collector`. Infrastructure only: no backtest,
no hold-out read, no signal test. Nothing here touches the live app.

## The never-trade rule

Gabe, 2026-10-01: never execute a trade, and never write code that can place,
modify or cancel an order. This collector is market data only.

- The client allows only `https://api.schwabapi.com/marketdata/v1/...` and the
  two OAuth paths (`/v1/oauth/authorize`, `/v1/oauth/token`). Everything else
  raises `ForbiddenEndpointError` before any network call.
- Any URL containing `/accounts`, `/orders`, `/trader/` or `/userpreference`
  is refused, also when it is URL-encoded or sits in a query string.
- The client has no account or order method. The only HTTP verbs in the
  package are GET (market data) and one POST (the OAuth token exchange). A
  unit test fails if either of these changes.
- The Schwab app is registered with the **Market Data Production** product
  only. Do not add "Accounts and Trading Production" to it.
- Limit of the scope check: Schwab's token response normally says `scope: api`
  whatever products the app has, so the login check (`check_scope`) only
  catches an explicit trading scope. The real control is the product list on
  the developer portal. **Gabe: confirm on developer.schwab.com that the app
  lists only Market Data Production.** With that, a call to `/trader/...`
  would be rejected by Schwab even if someone wrote one.

## Phase 0 findings

### What could and could not be verified

developer.schwab.com returns HTTP 403 to anything that is not a logged-in
browser, so the official pages could not be read. The figures below come from
the documentation of two open-source wrappers (schwab-py, schwabdev), which
agree with each other and with the work order. No API call was made: the
login needs Gabe's Schwab credentials.

| Question | Answer | Source / status |
|---|---|---|
| Rate limit | 120 requests per minute; HTTP 429 above it | schwabdev docs. The collector runs at 110/min |
| Access token lifetime | 30 minutes | schwabdev / schwabr docs. Refreshed automatically |
| Refresh token lifetime | 7 days, then a browser re-login | same. Weekly manual `login` |
| Daily price history depth | 20+ years (AAPL back to 1985) | schwab-py docs |
| Minute price history depth | 1-minute bars: about 48 days. 5/10/15/30-minute bars: about 9 months | schwab-py docs |
| Historical option chains | None. Chains and quotes are live only | work order; no endpoint exists |
| Coverage | Symbols listed today only. No delisted names | work order |
| **Terms: may the data be archived for personal use?** | **UNVERIFIED** | The terms page is behind the portal login. Not found in any public source |

**Open item for Gabe before Phase 2.** Read the API terms on
developer.schwab.com (the agreement accepted when the app was registered) for
any clause on storing, caching or retaining market data. If it forbids
keeping the data, do not run the daily pull and tell the COO. The work order
says to stop if the terms forbid archiving; they could not be read, so this
was built but must not be treated as cleared.

Also unverified until the first live run: the maximum number of symbols per
`/quotes` call (the collector uses 200 and bisects a batch that fails),
whether the full SPY chain fits in one response (the collector pulls SPY, QQQ
and IWM month by month, falls back to that for any chain that fails, and
retries a month that fails one expiry at a time; chain size is the most
likely first-run fix), and
whether Schwab daily candles are on the same split-adjusted basis as Sharadar
SEP `close` (acceptance test T2 measures it).

### Market-data endpoints used

All under `https://api.schwabapi.com/marketdata/v1/`.

| Endpoint | Used for | Main fields kept |
|---|---|---|
| `quotes` (batched) | equity/ETF quotes | bid, ask, sizes, last, mark, open/high/low, previous close, volume, 52-week range, quote/trade/bid/ask times, regular-session last and time, security status, 10-day average volume, dividend yield, next ex-date |
| `chains` | option chain per name | per contract: bid, ask, sizes, last, mark, volume, open interest, implied vol, delta, gamma, theta, vega, rho, theoretical value, strike, expiry, expiration type, quote and trade time, underlying price |
| `expirationchain` | listed expiries | expiry, type (S = standard monthly), settlement |
| `pricehistory` | daily candles (a minute wrapper exists, the CLI does not use it) | open, high, low, close, volume, candle time |
| `markets` | session hours | open flag, regular start and end |
| `instruments` | symbol lookup | wrapper only, not used by the CLI |

Not used: movers, and everything under `/trader/` (accounts, orders,
transactions, user preference, streaming credentials).

### Incident-to-endpoint map

From LEDGER.md, COO-ARCHIVE.md, APP.md and README.md (grep, not a full read).

| Live-data incident | Fixable by Schwab? | Endpoint |
|---|---|---|
| 2026-09-29: Retrain ALL failed because `scripts/td_data_local/SPY.csv` (yfinance cache) stopped at 09-25, so `relative_strength_20` was NaN | Yes, as a second source | `pricehistory` SPY (also `quotes`) |
| yfinance writes today's bar with a blank close until Yahoo finalizes it, so a same-evening retrain can stop at the SPY guard | Yes | `quotes` regular-session last after 16:00 ET; `pricehistory` |
| Benchmark CSVs pulled once "if missing" and never topped up (APP.md: stale since 09-15) | Yes | `pricehistory` SPY, IWM, USMV, QQQ |
| IWM hedge leg comes from yfinance | Yes | `pricehistory`, `quotes` |
| Live option chain comes from yfinance (`final/scripts/pull_live_options_chain.py`): no sizes, no greeks, IV proxies | Yes | `chains` |
| WO-O2 exit rules need daily quotes per held contract; the AV archive is monthly/weekly snapshots | Forward only. No history | `chains` daily archive |
| Wide down-cap option spreads (cap150 median 26% of mid on AV data) cannot be checked against a live source | Yes, measured forward | `chains` bid/ask/size |
| Forward ledgers have no real quotes at record time | Yes | `quotes` |
| Sharadar SEP arrives a day late; no same-day check of closes on the live panel | Cross-check only | `pricehistory` vs SEP (test T2) |
| `tickers_master.csv`, `actions.csv` stale (WO-17) | No | Sharadar reference data |
| SF1 fundamentals frozen / restatements (WO-16) | No | Sharadar fundamentals |
| Survivorship in the reset2026 grid; delisted names; AV historical options archive | No | Schwab has listed symbols only and no history |
| Open correctness items (NW t on option dates, arm-2 expiry rule) | No | not data-source problems |

Schwab cannot replace Sharadar (point-in-time history) or the Alpha Vantage
`HISTORICAL_OPTIONS` archive. It adds a clean archive that grows from day 1.

Wiring any of this into the retrain, the ledgers or the app is a later work
order (app changes go through the app manager). This order only collects.

### Pull size against the rate limit

The live tier is cap150 (`current_signal_composite.py`, `TIER = "cap150"`).
Universes come from the working panel
`final/out/reset2026/composite_panel_v2.parquet`, latest date, flags
`eligible_cap2000 / cap500 / cap150`. On 2026-09-30: 3,899 panel names, 3,076
cap150, 2,473 cap500, 1,607 cap2000.

Target universe: cap150 plus SPY, IWM, USMV, QQQ = **3,080 names**, frozen per
session date in `universe/date=.../universe_cap150.csv` so the coverage
denominator cannot move.

| Step | Requests per day |
|---|---|
| Market hours | 1 |
| Quotes, 200 symbols per call | 16 |
| Option chains, one call per name, plus expiry lists and month splits | about 3,160 |
| Daily price history, one call per name | 3,080 |
| **Total** | **about 6,250 = 57 minutes at 110/min** |

One session covers the full universe, with two automatic token refreshes. No
reduction is proposed. If chains turn out slower in practice, the fallback to
propose (not applied) is chains for cap2000 only (1,611 calls, 43 minutes in
total).

## Design

New files only.

- `final/src/schwab/client.py`: OAuth authorization-code flow with paste-back,
  token file `~/.config/pipe_dream/schwab_token.json` (mode 600, outside the
  repo, refused if inside it), refresh 2 minutes before expiry and on a 401,
  sliding-window rate limiter, retries with backoff on 429/5xx/network
  errors, the URL allowlist, market-data wrappers.
- `final/src/schwab/parse.py`: payload to flat rows.
- `final/src/schwab/store.py`: write-once parquet writer, sqlite pull log,
  frozen universe, NYSE calendar.
- `final/src/schwab/pull.py`: the pull loops (resume, chain month-split).
- `final/src/schwab/checks.py` and `final/scripts/schwab_check.py`: the
  acceptance tests.
- `final/scripts/schwab_pull.py`: the CLI.
- `final/src/schwab/tests/test_schwab.py`: 25 offline unit tests.

Secrets: `SCHWAB_APP_KEY` and `SCHWAB_APP_SECRET` are read from the
environment or `~/.config/pipe_dream/secrets.env`. They are never printed or
written. The pasted redirect URL (it holds the one-time code) is read with
hidden input and never stored. The pull log holds no URL and no token.

Data, under `/Users/ggraham/pipe_dream/final/data/schwab/` (override with
`--data-root` or `PIPE_DREAM_SCHWAB_DATA`; needs a `.gitignore` line, never
committed):

```
quotes/date=YYYY-MM-DD/quotes_<snapshot>_partNNNN.parquet
chains/date=YYYY-MM-DD/chains_<snapshot>_partNNNN.parquet
expirations/date=YYYY-MM-DD/...      listed expiries (reference names, split chains)
pricehistory/date=YYYY-MM-DD/...     14 calendar days of daily candles per name
hours/date=YYYY-MM-DD/...            regular session start/end
universe/date=YYYY-MM-DD/universe_cap150.csv
checks/close_mismatches_*.csv
pull_log.sqlite
```

- Every row has `pulled_at_utc`, `session_date`, `snapshot` and the API's own
  timestamps in UTC (`quote_time_utc`, `trade_time_utc`; `candle_time_utc`
  for candles).
- `date=` is the New York session date, not the UTC date. Candle dates are
  the New York date of the candle time.
- `snapshot` is the UTC start time of the run (`YYYYMMDDTHHMMSSZ`).
- Write-once: no file is ever overwritten (files are created with an
  exclusive link and set read-only). A past date that already holds data
  takes no new file. A second pull on the same day writes new files under a
  new snapshot id.
- Quotes and chains can only be pulled for today. `--date` in the past is
  accepted for `pricehistory` only, and only into an empty partition.
- Resume: re-running the same command skips names the pull log already has as
  `ok` or `empty` for that date. A name is logged only after its rows are on
  disk. `--no-resume` takes a full second snapshot.
- Share classes: Sharadar `BRK.B` is requested as `BRK/B`; the `ticker`
  column keeps the Sharadar form.
- A daily candle for the session date is marked `is_final = False` when the
  pull happened before the close plus 10 minutes. The close cross-check uses
  final candles only, so an afternoon run checks closes through the day
  before.
- On a market holiday or weekend `daily` stores the hours and stops.

## How Gabe runs it

Before the first login: read the Schwab API terms on archiving data and
confirm the app lists only Market Data Production (both above).

Use the project environment (the base conda python has a broken pandas). The
scripts are on `integration`, not in the live checkout, so run them from the
integrator's persistent `integration` worktree:

```
cd /Users/ggraham/pipe_dream/.claude/worktrees/integrator
PY=/opt/anaconda3/envs/pipe_dream/bin/python

# 1. once, then again every 7 days
$PY final/scripts/schwab_pull.py login
#    open the printed URL, log in, approve; the browser lands on
#    https://127.0.0.1/?code=... with a connection error (expected);
#    paste that full URL back within about 30 seconds (input is hidden)

# 2. check: universe size, request plan, one market-hours call, nothing written
$PY final/scripts/schwab_pull.py daily --dry-run

# 3. each trading day, about an hour
$PY final/scripts/schwab_pull.py daily

# anytime
$PY final/scripts/schwab_pull.py status
$PY final/scripts/schwab_check.py
```

The data goes to the main checkout's `final/data/schwab/` wherever the
scripts run from. Running them from `/Users/ggraham/pipe_dream` itself needs
an additive deploy of these new files to the live checkout (no `final/app`
path, no restart). That deploy needs Gabe's OK and has not been requested.

When to run: option bid/ask are only meaningful while the market is open, so
start `daily` between about 14:45 and 15:00 New York time. For final closes
the same day, also run `schwab_pull.py pricehistory --no-resume` after 16:10.
Otherwise the next day's run picks those closes up.

A smaller first test: `schwab_pull.py daily --universe AAPL,SPY,MSFT,NVDA,JPM`.

Unit tests (offline): `cd final/src && $PY -m unittest schwab.tests.test_schwab`.

## Acceptance criteria (fixed 2026-10-01, before any data)

Evaluated in Phase 2 on Gabe's machine by `schwab_check.py`.

| Test | Criterion | How the checker computes it |
|---|---|---|
| T1 | 5 consecutive trading days with >= 99% of the target universe pulled | Only days pulled on the cap150 universe count (a smoke-test list never does). The last 5 such days must be 5 consecutive NYSE trading days. Each day: share of the frozen universe with a quote row, with a price-history row, and with a chain answer (contracts, or a logged "no options listed"). All three >= 99% on all 5 days. The share with contracts is printed too |
| T2 | Schwab daily close vs Sharadar SEP close within 1bp on >= 99.5% of name-days; mismatches listed by name | Final candles, latest pull per name-day, against the working panel's `close`. Mismatches are printed (first 25) and written to `checks/` |
| T3 | Chains for AAPL, SPY, MSFT, NVDA, JPM contain every listed monthly expiry, and bid <= ask on >= 99.9% of rows | Listed = Schwab's own expiry list (type S), plus the third Fridays of the next 3 months from a calendar (the trading day before when that Friday is a holiday). Bid <= ask over the five names' rows |
| T4 | Quote timestamps within the session on >= 99% of rows; stale-quote rate reported separately for non-cap2000 names | Quote time between the stored regular open and close plus 15 minutes. Stale = quote time before the open, or missing; printed for cap2000 and for the rest |

Each test prints PASS, FAIL or NOT_EVALUABLE. The checker also prints an
informational SPY comparison against the yfinance `SPY.csv` cache.

Stop conditions from the work order: terms forbid archiving (unverified, see
above), the rate limit cannot cover the universe (it can), anything needs
trading scope (nothing does).

## Checks run for this order

- 25 unit tests pass, offline, in the `pipe_dream` conda env: token login,
  refresh and 401 retry; token file mode 600 and outside the repo; no secret
  in errors; 429/5xx backoff; rate limiter; quote, chain and candle parsing;
  New York session date; write-once; resume; chain month-split and per-expiry fallback; the
  never-trade guards; the four acceptance tests on a synthetic 5-day archive
  (clean archive passes, each planted fault fails its own test).
- `schwab_pull.py daily --dry-run` without a token: prints the plan (3,080
  names, 6,254 requests, 56.9 minutes), says to log in, writes nothing.
- `schwab_check.py` on an empty archive: four NOT_EVALUABLE.
- No live API call was made. Everything that depends on real Schwab payloads
  (field names, batch size, chain size, symbol forms such as `BRK/B`) is
  written from wrapper documentation and is untested against the live API.
  Expect small fixes on the first live run.
