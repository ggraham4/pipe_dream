# 2026-09-27: AV options pull retry fix (WO-20)

Branch `worktree-agent-aa131ac1ee41fbf09`, based on integration c8dec17.
This is a code fix only. No pull was run and no Alpha Vantage calls were made.

## What broke

The HISTORICAL_OPTIONS bulk pull (started 2026-09-22) died on 2026-09-23 at
18:03. It had logged monthly 2010-08-18 (33 of 225 monthly dates, 0 of 750
weekly). The end of `final/data/alphavantage/pull.out` shows
`http.client.IncompleteRead(70492 bytes read, 111102 more expected)`, raised by
`urlopen(...).read()` inside `AV.chain`. `IncompleteRead` subclasses
`http.client.HTTPException`, not `OSError`, so the retry tuple
`(URLError, TimeoutError, JSONDecodeError, ConnectionError, OSError)` let it
through and it killed the process. `BadStatusLine` escaped the same way.
`RemoteDisconnected` was already caught, because it is also a ConnectionError.

## Fix (`final/scripts/av_options_pull.py`)

- A module constant `FETCH_ERRORS` holds the old tuple plus
  `http.client.HTTPException`. The backoff is unchanged: 5 tries, with a
  sleep of 5 s × attempt.
- The fetch is now `AV._fetch(url)`. It closes the response through `with` and
  gives tests one seam to patch.
- A truncated body raises before `json.loads`, so nothing partial is returned.
  The loop re-requests. After 5 failures `chain` returns `error`, which follows
  the existing path: the name is logged `error`, the date is committed, the
  loop continues, and the next run retries `error` rows. A non-dict JSON body
  is also retried now, where before it would have raised AttributeError.
- `--only-tier cap2000` needed no port. It was already in `final/scripts`
  (e58dfd5, landed 2026-09-23). Only the main checkout's
  `final/data/alphavantage/bin/` copy carried it as an uncommitted edit.

## Offline test (`/tmp/wo20/test_retry.py`, not committed)

`AV._fetch` was monkeypatched, `urlopen` was replaced with a function that
fails loudly if called, and `time.sleep` was a no-op. All tests passed:

```
T1 IncompleteRead x2 then ok: status=ok rows=2 requests=3
T2 IncompleteRead every try: status=error rows=0 requests=5
T2b RemoteDisconnected once then ok: status=ok requests=2
T2b BadStatusLine once then ok: status=ok requests=2
T2c non-dict JSON once then ok: status=ok requests=2
T3 main() run: log={'AAA': 'ok', 'BBB': 'error'} requests={'AAA': 3, 'BBB': 5}   (process completes; parquet has AAA only)
T4 resume: log={'AAA': 'ok', 'BBB': 'ok'} requests={'BBB': 1}                  (ok skipped, error re-requested)
T5 --only-tier cap2000: log={'AAA': 'ok'} requests={'AAA': 1}
ALL PASS
```

`py_compile` passed.

## Resuming (Gabe's call, needs the key)

The live checkout (`round18-app-two-models`) has no `final/scripts/av_options_pull.py`
or `av_options_run_pull.sh`. The crashed run used
`final/data/alphavantage/bin/av_options_pull.py`, and that copy still lacks the
fix. Resume with the launcher from a checkout that has this fix: either the
integrator's integration worktree, or the live checkout once these scripts are
deployed there. The launcher copies its sibling script over `bin/`, and it writes
to the live `final/data/alphavantage/` using absolute paths:

```
ALPHAVANTAGE_API_KEY=... AV_PULL_ARGS="--passes monthly --only-tier cap2000" \
    zsh <checkout>/final/scripts/av_options_run_pull.sh
```

A resume skips every ok or no_data row already in `pull_log.sqlite`.
