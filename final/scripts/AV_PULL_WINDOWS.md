# Running the AV options pull on a Windows machine

The pull is rate-limited by Alpha Vantage (~70 calls/min), not by CPU, so a
Windows box runs it exactly as fast as the Mac — and can stay on 24/7.
Only the pull moves; building the chain/features and all modelling stay on
the Mac.

## 1. One-time setup (PowerShell)
```powershell
winget install -e --id Python.Python.3.11
# new PowerShell window, then:
py -3.11 -m pip install pandas pyarrow numpy
mkdir C:\avpull\sharadar, C:\avpull\alphavantage
```

## 2. Stop the Mac pull, then copy files over (Mac -> Windows)
Stop first so the two machines never share the key's rate limit or write the
same log:
```bash
pkill -f "av_options_pull.py --data-root"
```
Copy (USB, network share, or cloud drive):

| from (Mac) | to (Windows) |
|---|---|
| `final/scripts/av_options_pull.py` (this branch) | `C:\avpull\av_options_pull.py` |
| `final/data/sharadar/downcap_universe_v2.parquet` (386 MB) | `C:\avpull\sharadar\` |
| `final/data/sharadar/tickers_master.csv` (8 MB) | `C:\avpull\sharadar\` |
| `final/data/alphavantage/pull_log.sqlite` + `options\` folder | `C:\avpull\alphavantage\` (resume state — copy BOTH or neither) |

## 3. Run
```powershell
[Environment]::SetEnvironmentVariable("ALPHAVANTAGE_API_KEY", "<key>", "User")
# new window:
cd C:\avpull
py -3.11 av_options_pull.py --data-root C:\avpull\alphavantage --sharadar-dir C:\avpull\sharadar --passes monthly --only-tier cap2000
```
Then, once that finishes, the rest of the monthly pass and the weekly pass:
```powershell
py -3.11 av_options_pull.py --data-root C:\avpull\alphavantage --sharadar-dir C:\avpull\sharadar
```
Progress: add `--status` to the same command.

Keep it awake: Settings > System > Power > Sleep = Never (plugged in), or
`powercfg /change standby-timeout-ac 0`. To survive logoff/reboot, create a
Task Scheduler task running the command above "whether user is logged on or
not"; the script resumes on its own after any interruption.

## 4. Bring results back to the Mac
Copy `C:\avpull\alphavantage\pull_log.sqlite` and `options\` back into
`final/data/alphavantage/` (replace), then on the Mac:
```bash
python3 final/src/build_option_chain_unified.py
python3 final/src/build_av_options_features.py
```
Both are incremental.
