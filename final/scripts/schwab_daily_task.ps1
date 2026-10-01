# Schwab daily market-data pull, for a Windows Scheduled Task (WO-41b).
# MARKET DATA ONLY: this runs schwab_pull.py, which cannot place, modify or
# cancel an order. Doc: final/scripts/SCHWAB_PULL_WINDOWS.md
#
#   powershell.exe -NoProfile -ExecutionPolicy Bypass -File C:\pipe_dream\final\scripts\schwab_daily_task.ps1
#
# What it does:
#   1. `schwab_pull.py status --min-refresh-days N` (no API call). Writes a
#      LOGIN NEEDED line when the refresh token has under 2 days left (on a
#      Friday: under 3.25, so it lasts to Monday's run) or is expired.
#      Expired / not logged in / no app key: stops, exit code 1.
#   2. `schwab_pull.py daily --universe <csv> --data-root <dir>`.
#   3. On a failure that a retry can fix, waits 10 minutes and runs it once
#      more (the pull resumes; nothing is pulled twice).
# Everything is appended to <data root>\logs\schwab_daily_<New York date>.log.
# The exit code of the pull is the exit code of this script.
# No secret is read, printed or logged here: the key, the secret and the
# token are only ever read by the Python client.

param(
    [string]$RepoRoot = "",
    [string]$Universe = "",
    [string]$DataRoot = "",
    [string]$PythonExe = "py",
    [string]$PythonVersionArg = "-3.11",
    [double]$MinRefreshDays = 2,
    [int]$RetryWaitSeconds = 600
)

$ErrorActionPreference = "Continue"

if (-not $RepoRoot) { $RepoRoot = (Resolve-Path (Join-Path $PSScriptRoot "..\..")).Path }
if (-not $Universe) { $Universe = Join-Path $RepoRoot "universe_cap150.csv" }
if (-not $DataRoot) { $DataRoot = Join-Path $RepoRoot "final\data\schwab" }
$Script = Join-Path $RepoRoot "final\scripts\schwab_pull.py"

Set-Location -Path $RepoRoot
$env:PYTHONUTF8 = "1"
$env:PYTHONUNBUFFERED = "1"

# New York time, whatever time zone this machine is set to
$nyZone = [System.TimeZoneInfo]::FindSystemTimeZoneById("Eastern Standard Time")
$nyNow = [System.TimeZoneInfo]::ConvertTimeFromUtc([DateTime]::UtcNow, $nyZone)

$logDir = Join-Path $DataRoot "logs"
New-Item -ItemType Directory -Force -Path $logDir | Out-Null
$Log = Join-Path $logDir ("schwab_daily_{0}.log" -f $nyNow.ToString("yyyy-MM-dd"))

function Write-Log([string]$Text) {
    $stamp = (Get-Date).ToString("yyyy-MM-dd HH:mm:ss")
    "$stamp  $Text" | Out-File -FilePath $Log -Append -Encoding utf8
    Write-Host "$stamp  $Text"
}

function Invoke-Pull([string[]]$PullArgs) {
    # runs python, appends stdout and stderr to the log, returns the exit code
    $all = @()
    if ($PythonVersionArg) { $all += $PythonVersionArg }
    $all += $Script
    $all += $PullArgs
    # 9009 stays if Python never started (not installed, wrong -PythonExe)
    $global:LASTEXITCODE = 9009
    try {
        & $PythonExe @all 2>&1 | ForEach-Object { "$_" } | Out-File -FilePath $Log -Append -Encoding utf8
    }
    catch {
        "could not start ${PythonExe}: $_" | Out-File -FilePath $Log -Append -Encoding utf8
    }
    $code = $global:LASTEXITCODE
    if ($null -eq $code) { $code = 9009 }
    return [int]$code
}

Write-Log "===== schwab daily task start ====="
Write-Log ("local time zone: {0} | New York time: {1}" -f [System.TimeZoneInfo]::Local.Id, $nyNow.ToString("yyyy-MM-dd HH:mm"))
Write-Log "repo $RepoRoot | universe $Universe | data root $DataRoot"

$minutes = $nyNow.Hour * 60 + $nyNow.Minute
if ($minutes -lt (14 * 60 + 30) -or $minutes -gt (15 * 60 + 15)) {
    Write-Log ("WARNING: started at {0} New York time; the task is meant to start at 14:45. Check the trigger time and this machine's time zone (see SCHWAB_PULL_WINDOWS.md)." -f $nyNow.ToString("HH:mm"))
}

# ---- 1. token check (no API call) -------------------------------------------
# the token must last until the next weekday run: on a Friday that is Monday
$need = $MinRefreshDays
if ($nyNow.DayOfWeek -eq [System.DayOfWeek]::Friday) { $need = [Math]::Max($MinRefreshDays, 3.25) }
$st = Invoke-Pull @("status", "--data-root", $DataRoot, "--min-refresh-days", "$need")
if ($st -eq 11 -or $st -eq 12) {
    Write-Log "LOGIN NEEDED: no valid Schwab login on this machine (status exit code ${st}; 11 =refresh token expired or never logged in, 12 = SCHWAB_APP_KEY / SCHWAB_APP_SECRET not set). Open PowerShell and run: py -3.11 final\scripts\schwab_pull.py login   Nothing pulled today."
    Write-Log "RESULT: FAILED (login needed), exit code 1"
    exit 1
}
elseif ($st -eq 10) {
    Write-Log "LOGIN NEEDED: the Schwab refresh token has under $need days left. Today's pull runs, but log in again before the next run: py -3.11 final\scripts\schwab_pull.py login"
}
elseif ($st -ne 0) {
    Write-Log "status check failed with exit code $st (Python missing, a package missing, or a script error; see the lines above). Nothing pulled."
    Write-Log "RESULT: FAILED, exit code $st"
    exit $st
}

# ---- 2. the pull, with one retry ---------------------------------------------
$pullArgs = @("daily", "--universe", $Universe, "--data-root", $DataRoot)
$rc = Invoke-Pull $pullArgs
Write-Log "daily finished with exit code $rc"

# 2 = refused (bad date or universe file), 3 = trading scope, 4 = universe file
# older than 45 days: a retry cannot fix these
if ($rc -ne 0 -and $rc -ne 2 -and $rc -ne 3 -and $rc -ne 4) {
    Write-Log "daily failed (exit code $rc). Waiting $RetryWaitSeconds seconds, then one retry (the pull resumes where it stopped)."
    Start-Sleep -Seconds $RetryWaitSeconds
    $rc = Invoke-Pull $pullArgs
    Write-Log "retry finished with exit code $rc"
}

if ($rc -eq 0) {
    Write-Log "RESULT: OK, exit code 0"
}
else {
    Write-Log "RESULT: FAILED, exit code $rc"
}
exit $rc
