# Alpha Vantage options pull — Windows host runbook

**Audience: a Claude Code session (or a person) on the Windows machine.**
Everything needed is in this repo branch plus two API keys. No data files are
copied from the Mac: the inputs are rebuilt from Sharadar here, and the
results are handed back to the Mac at the end.

## What this machine does, and what it must not do

- Its only job is to run `final/scripts/av_options_pull.py`, which downloads
  historical option chains from Alpha Vantage into `final/data/alphavantage/`.
  The pull is rate-limited by Alpha Vantage (~70 calls/min), not by CPU.
- **Do not** run any git write command (commit, push, merge, branch, stash…).
  In this project all git writes go through a separate integrator agent on the
  Mac. Read-only git (`clone`, `pull`, `status`, `log`) is fine.
- **Do not** put API keys in any file inside the repo. Use user environment
  variables only.
- **Do not** run the pull on the Mac and on Windows at the same time. They
  share one API key and its rate limit. (As of 2026-09-25 the Mac pull is
  stopped.)
- Do not run any modelling script. The Mac does all analysis.

## 1. Install tools (PowerShell)

```powershell
winget install -e --id Git.Git
winget install -e --id Python.Python.3.11
# open a NEW PowerShell window so PATH updates, then:
py -3.11 -m pip install --upgrade pip
py -3.11 -m pip install pandas pyarrow numpy requests
```

## 2. Get the code

```powershell
cd C:\
git clone https://github.com/ggraham4/pipe_dream.git
cd C:\pipe_dream
git checkout worktree-alpha-vantage-spin
```
If the repo is private, `git clone` opens a browser window to sign in to
GitHub (Git Credential Manager comes with Git for Windows). Sign in as the
repo owner. All paths below are relative to `C:\pipe_dream`.

## 3. Set the two keys (user environment, not files)

Get both keys from Gabe.
```powershell
[Environment]::SetEnvironmentVariable("ALPHAVANTAGE_API_KEY", "<AV key>", "User")
[Environment]::SetEnvironmentVariable("SHARADAR_API_KEY", "<Sharadar key>", "User")
[Environment]::SetEnvironmentVariable("PYTHONUTF8", "1", "User")
# open a NEW PowerShell window, then check:
echo $env:ALPHAVANTAGE_API_KEY.Length $env:SHARADAR_API_KEY.Length
```

## 4. Rebuild the inputs from Sharadar (~1–2 h, ~2 GB)

This creates `final/data/sharadar/tickers_master.csv`,
`sf1_shares.csv`, the monthly `panel/` and
`downcap_universe_v2.parquet`. It is resumable: just re-run it if interrupted.
```powershell
py -3.11 final\scripts\av_pull_windows_prep.py
```
It must end with **`ALL CHECKS PASS`**. These checks compare the rebuilt
universe with the Mac's copy by name counts on three dates, e.g.
`2008-06-30 cap2000/500/150 = (947, 1993, 2953)`. If any line says FAIL,
stop and report the FAIL lines to Gabe. Do not start the pull.

`pull_log.sqlite` is not rebuilt. It's the Mac's record of what it already
pulled. This machine starts its own log and uses `--start-date` so it never
repeats the Mac's work. The Mac merges both logs at the end.

## 5. Smoke test (2 minutes, throwaway folder)

```powershell
py -3.11 final\scripts\av_options_pull.py --data-root C:\avtest --only-dates 2010-09-15 --only-tickers AAPL,MSFT,XOM
py -3.11 final\scripts\av_options_pull.py --data-root C:\avtest --status
```
Expect `ok: 3`, all `verified`. Then delete `C:\avtest`.

## 6. Run the pull: three phases, in this order

The Mac already finished: all tiers for monthly dates 2008-01..2008-08, and
the $2B tier for monthly dates through 2010-08-18. The start dates below
continue from exactly there.

Create `C:\pipe_dream\run_av_pull.ps1` with:
```powershell
Set-Location C:\pipe_dream
$py = "py"; $s = "final\scripts\av_options_pull.py"
$log = "final\data\alphavantage\pull.out"
New-Item -ItemType Directory -Force final\data\alphavantage | Out-Null
& $py -3.11 $s --passes monthly --only-tier cap2000 --start-date 2010-09-01 *>> $log
& $py -3.11 $s --passes monthly --only-tier downcap --start-date 2008-09-01 *>> $log
& $py -3.11 $s --passes weekly *>> $log
```
(`run_av_pull.ps1` sits at the repo root but is never committed.)

Keep the machine awake and run it so it survives logoff/reboot:
```powershell
powercfg /change standby-timeout-ac 0
powercfg /change hibernate-timeout-ac 0
$act = New-ScheduledTaskAction -Execute "powershell.exe" -Argument "-NoProfile -ExecutionPolicy Bypass -File C:\pipe_dream\run_av_pull.ps1"
$trg = New-ScheduledTaskTrigger -AtStartup
Register-ScheduledTask -TaskName "AVOptionsPull" -Action $act -Trigger $trg -RunLevel Highest -User $env:USERNAME
Start-ScheduledTask -TaskName "AVOptionsPull"
```
A scheduled task doesn't inherit your shell, so the keys must be **User**
environment variables (step 3), not `$env:` values set in one window. Every
phase resumes on its own after a restart, and completed phases finish in
seconds when re-run.

Expected pace: phase 1 ≈ 20 min per date (~190 dates, ~2.5 days); phase 2 ≈
45–60 min per date (~215 dates, ~8 days); phase 3 (weekly) will not finish
inside one subscription month. That's expected: it's date-ordered, so
whatever lands is usable.

## 7. Monitor

```powershell
Get-Content final\data\alphavantage\pull.out -Tail 5
py -3.11 final\scripts\av_options_pull.py --status
```
Healthy phase-1 lines look like
`monthly 2010-09-15: ~900 names {'ok': ~870, 'no_data': ~30}`.
Warning signs to report: many `error` statuses, `10 consecutive errors`,
a Python traceback, or no new line for over 90 minutes.

## 8. Hand results back to the Mac (any time, repeatable)

1. `Stop-ScheduledTask -TaskName "AVOptionsPull"` (so the SQLite log isn't
   mid-write).
2. Zip `final\data\alphavantage\pull_log.sqlite` and
   `final\data\alphavantage\options\` and send the zip to the Mac.
3. `Start-ScheduledTask -TaskName "AVOptionsPull"` (it resumes).

On the Mac (Gabe/Claude there), unzip to a scratch folder and run:
```bash
python3 final/scripts/av_merge_pull_roots.py --src <unzipped folder>
python3 final/src/build_option_chain_unified.py
python3 final/src/build_av_options_features.py
```
The merge is idempotent, so sending a newer zip later is fine.
