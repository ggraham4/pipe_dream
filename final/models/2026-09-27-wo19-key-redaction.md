# WO-19: keep the Sharadar key out of job logs (2026-09-27)

Hygiene fix, scripts only. No model, data, or app change.

## What was wrong

No Sharadar script builds a key-bearing URL string. Every one already passes
the key through `requests.get(..., params=...)`. The leak route is different:
when a request fails at the connection level, the `requests` exception text
carries the full request path, query string included:

    HTTPSConnectionPool(host='api.sharadar.com', port=443): Max retries exceeded
    with url: /v1.0/data/daily?api_key=<KEY>&format=csv&... (Caused by ...)

Scripts that printed `{e}`, put it into a RuntimeError, or let the exception
propagate uncaught (a traceback) wrote the key to stdout. That output lands in
the app job logs (`final/app/logs/...`). A read-only scan of the live
`final/app/logs` found no key-shaped `api_key=` string today.

## Audit of every file on integration that mentions `api_key`

| file | before | fix |
|---|---|---|
| src/sharadar_pull_pit_panel.py (app runs it via pit_model.py) | `{e}` in retry print and final RuntimeError | scrubbed |
| src/sharadar_pull_fundamentals.py | same as above | scrubbed |
| scripts/sharadar_splits_pull.py | prints `{e}` | scrubbed |
| scripts/sharadar_data_pull.py | prints `{e}` | scrubbed |
| src/sharadar_universe_probe.py, probe2.py, probe3.py | return `{e}`, caller prints it | scrubbed |
| src/sharadar_pull_shares.py | uncaught exception, traceback carries URL | re-raise same type, scrubbed text, `from None` |
| src/diagnose_marketcap_units.py | uncaught exception, traceback | same |
| src/sharadar_build_identity_map.py (also used by scripts/sharadar_reference_refresh.py) | uncaught exception, traceback | same |
| scripts/sharadar_downcap_pull.py | redacted the exact key only | now uses the full scrub (adds URL-encoded key + `api_key=` regex) |
| src/reset2026/sf1_topup.py | already safe (logs only `type(e).__name__`) | defence in depth: HTTP-body snippet scrubbed |
| src/sue/sf1_eps_live_pull.py | already safe (logs only `type(e).__name__` / status code) | unchanged |
| scripts/sharadar_reference_refresh.py | already had `scrub()` + `from None` | unchanged |
| app/lib/data_refresh.py, app/lib/key_guard.py | app side already redacts | not touched (app-manager owned) |

The helper, `_scrub(s, key)`, is inlined in each file, like the existing
`scrub()` in sharadar_reference_refresh.py. That is deliberate: the scripts
run from four different directories, and a shared module would need sys.path
changes. The helper replaces the raw key, its URL-encoded form, and any
`api_key=...` query fragment with `***`. New raises inside `except` blocks use
`from None`, so the original URL never appears in a chained traceback.

Behaviour is otherwise unchanged. Exception types are the same, the key still
goes over `params=`, and retries and paging are untouched.

## Checks

- `py_compile` on all 13 files: OK.
- `final/scripts/test_wo19_key_redaction.py`, offline.
  - How it runs: it sets `SHARADAR_API_KEY=FAKEKEY123` before import, blocks
    `socket.connect`, and swaps `requests.get` for a mock that raises a
    realistic ConnectionError built from the prepared URL.
  - **Leak test, pre-fix copies:** 10 of 13 LEAK. That proves the test sees
    the leak.
  - **Leak test, fixed code:** 13 of 13 clean. It checks stdout, stderr, the
    formatted traceback and the return value.
  - **Success parity:** a mocked 200 CSV with PAGE=3, so paging is exercised,
    gives byte-identical pickled results and identical stdout/stderr, old vs
    new, for all 13 files. Result: PASS.

## Not done

The live checkout (`round18-app-two-models`) still runs the pre-fix scripts
until Gabe OKs a deploy of these files.
