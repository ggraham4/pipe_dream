# Running the Schwab daily pull on a Windows machine (Scheduled Task)

**No trading (Gabe, 2026-10-01):** no agent, script or job may place, modify or cancel any order unless Gabe himself types out the exact trade details as confirmation. See AGENTS.md standing constraint #7.

The collector is market data only: the client refuses every URL outside
`/marketdata/v1/` and the two OAuth paths. Nothing in this handoff changes
that. Collector doc: `final/models/2026-10-01-schwab-collector.md`.

The Windows box never sleeps, so the daily pull moves there (Gabe,
2026-10-01). Only the pull moves. The checker (`schwab_check.py`) and all
modelling stay on the Mac, which gets the data by a file copy (section 7).

**Not tested on Windows.** Everything here was written and unit-tested on the
Mac (36 offline tests). The PowerShell script, the Task Scheduler commands and
the hidden paste at login have never run on a Windows machine. Expect small
fixes on the first run; section 9 lists what is untested.

## Checklist

1. Mac: export the universe file (section 2). Copy it and the code to `C:\pipe_dream` (section 3).
2. Windows: install Python 3.11 and the packages, then run the unit tests (sections 1 and 4).
3. Windows: set `SCHWAB_APP_KEY` and `SCHWAB_APP_SECRET` as User environment variables (section 4).
4. Windows: `schwab_pull.py login` in PowerShell, then `daily --dry-run` (section 5). Do this on the morning of the first Windows day.
5. Windows: check the time zone, register the task, run it once by hand on a trading day (section 6).
6. From then on: only Windows pulls. Every Monday morning: log in again on Windows and copy a fresh universe file over. Copy the data back to the Mac when you want to check it (section 7).

## Paste-ready prompt for a Claude session on the Windows box

```
You are on Gabe's Windows machine. Set up the Schwab daily market-data pull as
a Scheduled Task by following C:\pipe_dream\final\scripts\SCHWAB_PULL_WINDOWS.md
step by step (sections 1, 4, 5, 6). Rules: market data only, never write or run
anything that can place, modify or cancel an order, and do not change
final\src\schwab\client.py's URL guard or its test. Never print, log or store
the values of SCHWAB_APP_KEY, SCHWAB_APP_SECRET or the token file. Gabe sets
the two environment variables and does the browser login himself: stop and ask
him at those two steps. First run the unit tests. If an assertion fails on
Windows, show me the failure and fix the code, not the test. If the only
errors are temp-folder clean-up errors (PermissionError / WinError 5 or 32 at
the end of a test), report them and change nothing. Do not run `daily` without
--dry-run until the tests pass and the dry run prints "token works". Then
check the time zone, register the task exactly as in section 6, and report
what you changed and what the first log file says.
```

## 1. One-time setup (PowerShell)

```powershell
winget install -e --id Python.Python.3.11
# new PowerShell window, then:
py -3.11 -m pip install requests pandas pyarrow tzdata python-dateutil
mkdir C:\pipe_dream
```

`tzdata` is required: Windows has no time-zone database and the collector
works in New York time. Without it every command stops with "time-zone data
not found".

Use a local NTFS drive for `C:\pipe_dream`. Do not put it inside OneDrive,
Dropbox or a network share: the sqlite pull log and the write-once files need
a real local disk.

Keep the box awake: Settings > System > Power > Sleep = Never (plugged in), or
`powercfg /change standby-timeout-ac 0`.

## 2. Export the universe on the Mac

The Windows box has no Sharadar panel, so it cannot work out the cap150
universe itself. The Mac writes it to one csv:

```bash
cd /Users/ggraham/pipe_dream/.claude/worktrees/integrator
/opt/anaconda3/envs/pipe_dream/bin/python final/scripts/schwab_pull.py export-universe --universe cap150 --out ~/Desktop/universe_cap150.csv
```

(Any Mac checkout that has this change works. No API call is made.) On
2026-10-01 this wrote 3,080 names, 1,607 of them cap2000, panel date
2026-09-30. The file carries `ticker`, `schwab_symbol`, `in_cap2000` (plus
`in_cap500`, `in_cap150`, `is_benchmark`), `panel_date`, `universe_name` and
`exported_utc`.

**Refresh it weekly**, after the live panel refresh, and copy the new file
over the old one on Windows. The pull measures the file's age from its
`panel_date`:

| age of the panel date | what the pull does |
|---|---|
| 10 days or less | runs |
| 11 to 45 days | prints a loud `WARNING: STALE UNIVERSE` block and runs |
| more than 45 days | refuses, exit code 4, nothing pulled |

A stale file means new listings and names that newly became eligible are
not pulled, and those days cannot be back-filled (quotes and chains are live
only).

## 3. Copy files over (Mac -> Windows)

Keep the folder layout: the scripts find the package by their own location.
Copy by USB, network share or cloud drive.

| from (Mac, a checkout with this change) | to (Windows) |
|---|---|
| `final/src/schwab/` (whole folder, including `tests/`) | `C:\pipe_dream\final\src\schwab\` |
| `final/scripts/schwab_pull.py` | `C:\pipe_dream\final\scripts\` |
| `final/scripts/schwab_check.py` | `C:\pipe_dream\final\scripts\` (the unit tests read it) |
| `final/scripts/schwab_daily_task.ps1` | `C:\pipe_dream\final\scripts\` |
| `final/scripts/SCHWAB_PULL_WINDOWS.md` | `C:\pipe_dream\final\scripts\` |
| `~/Desktop/universe_cap150.csv` (section 2) | `C:\pipe_dream\universe_cap150.csv` |

Do **not** copy `~/.config/pipe_dream/schwab_token.json` or `secrets.env`
(section 5 says why), and do not copy the Mac's `final/data/schwab/` folder:
Windows starts with an empty archive and the Mac keeps day 1.

On Windows the data goes to `C:\pipe_dream\final\data\schwab\` (the folder the
code sits in, then `final\data\schwab`). To put it elsewhere, pass
`--data-root` / the script's `-DataRoot`, or set `PIPE_DREAM_SCHWAB_DATA`.
`PIPE_DREAM_ROOT` (the folder that holds `final`) overrides the root on any
machine; it is not needed with the layout above.

## 4. Secrets and the offline tests (Windows)

On the Mac the app key and secret are in `~/.config/pipe_dream/secrets.env`.
On Windows use User environment variables. Gabe types the values himself;
they are never written to a file in `C:\pipe_dream`, a log or a chat:

```powershell
[Environment]::SetEnvironmentVariable("SCHWAB_APP_KEY", "<key>", "User")
[Environment]::SetEnvironmentVariable("SCHWAB_APP_SECRET", "<secret>", "User")
# then open a NEW PowerShell window
```

PowerShell saves typed commands, values included, in its history file
(`(Get-PSReadLineOption).HistorySavePath`). Either delete those two lines
from that file afterwards, or set the two variables in the GUI instead
(Start > "Edit environment variables for your account"), which leaves no
history.

Check that they are set, without showing them:

```powershell
"SCHWAB_APP_KEY","SCHWAB_APP_SECRET" | ForEach-Object { "$_ set: " + [bool][Environment]::GetEnvironmentVariable($_, "User") }
```

Run the unit tests (offline, no API call, about a second):

```powershell
cd C:\pipe_dream
py -3.11 -m unittest discover -s final\src\schwab\tests -t final\src
```

Expect `Ran 36 tests ... OK`. These tests are the only check this code has had
on Windows, so do not skip them.

## 5. Login on Windows (once, then weekly)

```powershell
cd C:\pipe_dream
py -3.11 final\scripts\schwab_pull.py login
```

1. The command prints a URL. Open it in a browser, log in to Schwab, approve.
   (The URL contains the app key as `client_id`. Do not paste the command's
   output anywhere.)
2. The browser lands on `https://127.0.0.1/?code=...` and shows a connection
   error. That is expected. Copy the full URL from the address bar.
3. Back in PowerShell, paste it (right-click, or Ctrl+V) and press Enter. The
   input is hidden, so nothing appears as you paste. The code expires in about
   30 seconds.
4. If the hidden paste is not accepted, run
   `py -3.11 final\scripts\schwab_pull.py login --visible-paste` and paste
   again; the URL is then shown on screen. The code in it is single-use and
   dead after 30 seconds, but clear the window afterwards (`cls`).

Then check, with nothing written to the archive:

```powershell
py -3.11 final\scripts\schwab_pull.py daily --dry-run --universe C:\pipe_dream\universe_cap150.csv
py -3.11 final\scripts\schwab_pull.py status --min-refresh-days 2
```

The dry run must print `DRY RUN: token works`. It makes one market-hours
call. `status` makes no API call.

The token file is `C:\Users\<you>\.config\pipe_dream\schwab_token.json`. On
the Mac it has mode 600. Windows has no such mode bits, and the code does
not set an ACL: the file is protected by the Windows user profile's ACL
(other standard users cannot read your profile folder; administrators can).
The code refuses to keep the token inside the repo folder.

**The refresh token lasts 7 days from the browser login.** Log in again every
Monday morning before 14:45 New York time. The scheduled script writes a
`LOGIN NEEDED` line when under 2 days are left (on a Friday: under 3.25 days,
so that the token lasts to Monday's run), and stops with exit code 1 when the
token has expired. With a Monday-morning login the line appears in every
Friday log (about 2.7 days left, and the token ends before Monday's 14:45
run): that is the reminder for Monday's login. Nobody is notified, the line
is only in the log, so put the Monday login in your calendar.

**Use a fresh login on Windows. Do not copy the Mac's token file.**

- The token file is a secret. Copying it over USB or a cloud drive puts it
  somewhere it should not be.
- A copied token keeps the Mac's 7-day clock: the Mac login from 2026-10-01
  expires about 2026-10-08 on both machines. A fresh login starts a full 7
  days.
- Two machines refreshing the same token is an untested case with Schwab. One
  login per machine avoids it.

## 6. The scheduled task

`final\scripts\schwab_daily_task.ps1` does, in order:

1. `status --min-refresh-days` (no API call) and the `LOGIN NEEDED` line.
2. `daily --universe C:\pipe_dream\universe_cap150.csv --data-root C:\pipe_dream\final\data\schwab`.
3. If the pull fails with an exit code a retry can fix (anything but 2, 3,
   4), it waits 10 minutes and runs the pull once more. The pull resumes:
   names already answered are skipped.
4. Appends everything to
   `C:\pipe_dream\final\data\schwab\logs\schwab_daily_<New York date>.log` and
   exits with the pull's exit code.

The retry is in the script, not in Task Scheduler's "restart on failure":
that setting is not reliable for a program that starts and then exits with
an error code.

### Time zone: check it, do not assume it

The pull must start at **14:45 America/New_York** (option quotes are only
live while the market is open; the pull takes about an hour). Task Scheduler
triggers use the machine's local time. Check what the box is set to:

```powershell
Get-TimeZone                 # Id, and SupportsDaylightSavingTime
tzutil /g
```

The registration below converts 14:45 New York to the box's local time on the
day you run it.

- If the box is on US Eastern, Central, Mountain or Pacific time, that local
  time is right all year.
- If the box is on a zone that does not change clocks with New York (UTC,
  Arizona, anywhere outside the US), the local time is wrong after each US
  clock change (second Sunday of March, first Sunday of November). Register
  the task again after each one.

The script logs the New York time at every start and writes a `WARNING` line
when it started outside 14:30 to 15:15 New York time, so a wrong trigger shows
up in the first log.

### Register (PowerShell, as the user who did the login)

```powershell
$ny = [TimeZoneInfo]::FindSystemTimeZoneById("Eastern Standard Time")
$at = [TimeZoneInfo]::ConvertTime([datetime]::SpecifyKind((Get-Date).Date.AddHours(14).AddMinutes(45), "Unspecified"), $ny, [TimeZoneInfo]::Local)
"14:45 New York is $($at.ToString('HH:mm')) local time on this machine"

$action   = New-ScheduledTaskAction -Execute "powershell.exe" -Argument '-NoProfile -ExecutionPolicy Bypass -File "C:\pipe_dream\final\scripts\schwab_daily_task.ps1"' -WorkingDirectory "C:\pipe_dream"
$trigger  = New-ScheduledTaskTrigger -Weekly -DaysOfWeek Monday,Tuesday,Wednesday,Thursday,Friday -At $at
$settings = New-ScheduledTaskSettingsSet -MultipleInstances IgnoreNew -ExecutionTimeLimit (New-TimeSpan -Hours 4)
Register-ScheduledTask -TaskName "pipe_dream_schwab_daily" -Action $action -Trigger $trigger -Settings $settings -Description "Schwab market-data pull (market data only, no trading)"
```

- Weekdays only. `-MultipleInstances IgnoreNew`: a second start while one is
  running is dropped, so two pulls never overlap.
- The task runs as you, only while you are logged on (a locked screen is
  fine). That is deliberate: it sees your User environment variables and your
  token file with no stored password. Stay logged on.
- A missed run is not started later (a pull after the close would store dead
  option quotes).
- Change the time later:
  `Set-ScheduledTask -TaskName "pipe_dream_schwab_daily" -Trigger (New-ScheduledTaskTrigger -Weekly -DaysOfWeek Monday,Tuesday,Wednesday,Thursday,Friday -At "HH:mm")`.
- Remove: `Unregister-ScheduledTask -TaskName "pipe_dream_schwab_daily"`.

### Run it once by hand, then verify

On a trading day, about 14:45 New York time (not on a day the Mac pulls):

```powershell
Start-ScheduledTask -TaskName "pipe_dream_schwab_daily"
Get-ScheduledTaskInfo -TaskName "pipe_dream_schwab_daily"     # LastTaskResult 0 = OK; 267009 = still running
Get-Content C:\pipe_dream\final\data\schwab\logs\schwab_daily_*.log -Tail 20
```

A good log ends with `RESULT: OK, exit code 0`, and above it a
`pull log: {('quotes', 'ok'): ..., ('chains', 'ok'): ..., ('pricehistory', 'ok'): ...}`
line with about 3,080 names per kind. The universe line must say
`already frozen` or `frozen now at ...\universe_cap150.csv`: that file name
is what makes the day count for acceptance test T1.

### Holidays and closed days

- Weekends and NYSE holidays (offline calendar in the code): the pull prints
  `Market is closed ... Nothing pulled, nothing written`, makes no API call,
  writes nothing to the archive and exits 0. Only the day's log file is
  written.
- A closure the calendar does not know (Schwab's market-hours call says
  closed): exit 0, no quotes, chains, candles or universe file. One small
  `hours\date=...` file records that Schwab reported the market closed, and
  `pull_log.sqlite` is created if it did not exist yet (no rows added).
- Early-close days (13:00 New York: the day after Thanksgiving, some
  Christmas Eves): the 14:45 run starts after the close. It still pulls, but
  quotes and option bid/ask are from after the close. Either accept that or
  start the task by hand at about 12:00 New York on those days.

### Exit codes

| code | meaning |
|---|---|
| 0 | pulled, or the market was closed |
| 1 | login needed, or an error (see the log; the script already retried once) |
| 2 | refused: universe file missing, or a bad date |
| 3 | the token reports trading scope: stop and tell Gabe |
| 4 | universe file older than 45 days |

## 7. Bring the data back to the Mac

The archive is write-once: a file is never changed after it is written, so a
plain copy that skips existing files is safe in either direction. The one
file that does change is `pull_log.sqlite`. Each machine has its own, so the
Windows log goes to the Mac under a different name and the Mac's own log
(which holds day 1) is never overwritten.

Copy only when the task is not running (not between 14:45 and about 16:15 New
York time).

Windows, to a USB stick or share (`E:\schwab` here):

```powershell
robocopy C:\pipe_dream\final\data\schwab E:\schwab /E /XC /XN /XO /XF pull_log.sqlite pull_log.sqlite-wal pull_log.sqlite-shm
Copy-Item C:\pipe_dream\final\data\schwab\pull_log.sqlite E:\schwab\pull_log_windows.sqlite -Force
```

Mac (`/Volumes/USB/schwab` here):

```bash
rsync -av --ignore-existing --exclude 'pull_log.sqlite*' /Volumes/USB/schwab/ /Users/ggraham/pipe_dream/final/data/schwab/
cp /Volumes/USB/schwab/pull_log_windows.sqlite /Users/ggraham/pipe_dream/final/data/schwab/pull_log_windows.sqlite
cd /Users/ggraham/pipe_dream/.claude/worktrees/integrator
/opt/anaconda3/envs/pipe_dream/bin/python final/scripts/schwab_check.py
```

- `--ignore-existing` and `/XC /XN /XO` never replace a file that is already
  there.
- If `C:\pipe_dream\final\data\schwab\pull_log.sqlite-wal` exists while no
  pull is running, the last run did not close cleanly. Run
  `py -3.11 final\scripts\schwab_pull.py status` once (it opens and closes
  the log), then copy.
- The checker reads every `pull_log*.sqlite` in the folder and takes the best
  status seen on either machine. Its first line lists the logs it found and
  the days that have a cap150 universe file. A day counts for T1 whichever
  machine pulled it.
- T2 (close vs Sharadar) and the SPY cross-check need the Mac's panel and
  yfinance cache, so the checker is run on the Mac, not on Windows.
- The Mac folder is gitignored. Never commit it.

## 8. Cutover rules

- **Only one machine pulls on a given day.** Two pulls would share the
  120-requests-per-minute limit and write two partial snapshots of the same
  day.
- Day 1 (2026-10-01) is being pulled on the Mac.
- The Mac keeps pulling until Gabe has finished sections 1 to 6. The Windows
  task takes over on the next trading day after that, and the Mac stops from
  that day. The 5 consecutive days of test T1 can be a mix of Mac and Windows
  days, as long as no trading day is missed.
- Windows needs its own browser login (section 5). The Mac login from
  2026-10-01 expires about 2026-10-08 and is not needed after the cutover.
- If the Windows box is down on a trading day, pull that day on the Mac
  (`schwab_pull.py daily`, needs a valid Mac login) and do not start the
  Windows task that day. A day with no pull cannot be back-filled for quotes
  or chains.
- Weekly, every Monday morning: log in on Windows; export the universe on the
  Mac and copy it to `C:\pipe_dream\universe_cap150.csv`.

## 9. Troubleshooting, and what is untested on Windows

| symptom | cause and fix |
|---|---|
| `time-zone data not found` | `py -3.11 -m pip install tzdata` |
| `LOGIN NEEDED` in the log, status exit 12 | the two environment variables are not visible to the task. Set them at User level (section 4), sign out and in again |
| `LOGIN NEEDED`, status exit 11 | refresh token expired: `schwab_pull.py login` |
| `STOPPED: refresh token rejected` during a pull | same: log in, start the task again the same day (it resumes) |
| `REFUSED: universe file not found` | copy `universe_cap150.csv` to `C:\pipe_dream\` or pass `-Universe <path>` in the task's argument |
| `WARNING: STALE UNIVERSE` | export a new file on the Mac (section 2) |
| log says `WARNING: started at HH:mm New York` | wrong trigger time: time zone section above |
| the task shows "running" for hours | the pull takes about an hour, up to about 2.5 with the retry. The limit is 4 hours |
| `running scripts is disabled on this system` | start it with `powershell.exe -NoProfile -ExecutionPolicy Bypass -File ...` as in section 6 |
| exit code 9009 | Python did not start (`py` not found inside the task): pass `-PythonExe "C:\path\to\python.exe" -PythonVersionArg ""` in the task's argument |
| a unit test fails only on Windows | fix the code, re-run; tell the Mac side so the change gets committed there |

Untested on Windows (no Windows machine was available):

- `schwab_daily_task.ps1` has never been run or even parsed by PowerShell.
- The `Register-ScheduledTask` commands and the time-zone conversion.
- The hidden paste at `login` in PowerShell (`--visible-paste` is the
  fallback).
- The 36 unit tests on Windows, in particular temp-folder clean-up of
  read-only files and of the sqlite log.
- The write-once step (`os.link` on NTFS, with an exclusive-create fallback
  for volumes without hard links) and the atomic token write (`os.replace`).
  Both are standard on NTFS but were only exercised on macOS.
- A live pull from Windows: none was made. No Schwab API call was made for
  this handoff at all.
