#!/usr/bin/env python3
"""Schwab Trader API forward market-data collector (WO-41). MARKET DATA ONLY.

This script can never place, modify or cancel an order: the client refuses
every URL outside /marketdata/v1/ and the OAuth paths (never-trade rule,
Gabe 2026-10-01). Doc: final/models/2026-10-01-schwab-collector.md

First run (two commands):
    python final/scripts/schwab_pull.py login
    python final/scripts/schwab_pull.py daily --dry-run

Then, each trading day (best between 15:00 and 16:00 New York time so option
bid/ask are live; takes about an hour):
    python final/scripts/schwab_pull.py daily

Commands
    login          browser login; paste the redirected https://127.0.0.1/?code=... URL back
    status         token lifetimes and today's pull-log counts (no API call)
    quotes         batched quotes for the universe
    chains         one option-chain call per name
    pricehistory   daily candles, one call per name
    daily          market hours + quotes + chains + pricehistory
    export-universe  write the universe to one csv for a machine without the panel
                   (no API call): export-universe --universe cap150 --out FILE.csv

Options: --universe cap150|cap500|cap2000|panel|AAPL,MSFT|path  --date YYYY-MM-DD
         --dry-run  --no-resume  --allow-closed  --data-root DIR  --rate N
         --out FILE --panel PATH (export-universe)  --min-refresh-days N (status)
         --visible-paste (login)

Windows scheduled task: final/scripts/SCHWAB_PULL_WINDOWS.md. There the universe
is an exported csv (--universe C:/pipe_dream/universe_cap150.csv); the pull
warns when its panel date is more than 10 days old and refuses after 45.

Exit codes: 0 done (also a closed market: nothing pulled), 1 login needed or
error, 2 refused (bad date or universe file), 3 trading scope, 4 universe file
too old. `status --min-refresh-days N`: 0 fine, 10 fewer than N days left,
11 expired or not logged in, 12 app key/secret not found.

Re-running the same command on the same day resumes: names already answered
are skipped. Use --no-resume for a second full snapshot of the same day (it
goes to new files keyed by UTC time; nothing is overwritten).
"""
import argparse
import getpass
import os
import sys
from datetime import date
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO / "final" / "src"))

from schwab import pull, store                                   # noqa: E402
from schwab.client import (LoginRequired, RateLimiter, SchwabClient, TokenStore,  # noqa: E402
                           TradingScopeError, TOKEN_FILE)
from schwab.parse import ny_today                                # noqa: E402

LIVE_ONLY = ("quotes", "chains")


def make_client(args):
    return SchwabClient(token_store=TokenStore(TOKEN_FILE, repo_root=REPO),
                        rate_limiter=RateLimiter(max_calls=args.rate))


def cmd_login(args):
    client = make_client(args)
    print("1. Open this URL in a browser and log in with your Schwab credentials:\n")
    print("   " + client.authorize_url() + "\n")
    print("2. After you approve, the browser lands on https://127.0.0.1/?code=... and shows a\n"
          "   connection error. That is expected. Copy the full URL from the address bar.\n"
          "3. Paste it below (input is hidden; the code expires in about 30 seconds).\n"
          "   Windows: paste with a right-click or Ctrl+V, then Enter. If nothing is\n"
          "   accepted, run `login --visible-paste` (the URL is then shown as you paste).\n")
    if args.visible_paste:
        redirected = input("Redirected URL: ")
    else:
        redirected = getpass.getpass("Redirected URL: ")
    try:
        client.login_with_redirect(redirected)
    except TradingScopeError as e:
        print(f"STOP: {e}")
        return 3
    st = client.token_status()
    how = "mode 600" if os.name == "posix" else "protected by the Windows user profile ACL"
    print(f"Logged in. Token file {TOKEN_FILE} ({how}). Scope reported: {st['scope']}.")
    print(f"Refresh token good for about {st['refresh_days_left']} days; then run login again.")
    return 0


def cmd_status(args):
    check = args.min_refresh_days is not None
    try:
        client = make_client(args)
    except LoginRequired as e:
        if not check:
            raise
        print(f"LOGIN NEEDED: {e}")
        return 12
    st = client.token_status()
    print("token:", st)
    if check:
        left = st.get("refresh_days_left") if st.get("logged_in") else None
        if left is None or left <= 0:
            print("LOGIN NEEDED: no valid refresh token (expired or never logged in). "
                  "Run `schwab_pull.py login`.")
            return 11
        if left < args.min_refresh_days:
            print(f"LOGIN NEEDED: the refresh token has {left} days left (under "
                  f"{args.min_refresh_days}). Run `schwab_pull.py login`.")
            return 10
    root = store.data_root(args.data_root)
    if (root / "pull_log.sqlite").exists():
        log = store.PullLog(root / "pull_log.sqlite")
        print(f"pull log {args.date}:", log.summary(args.date) or "nothing yet")
    return 0


def cmd_export_universe(args):
    if not args.out:
        print("REFUSED: export-universe needs --out FILE.csv")
        return 2
    try:
        df = store.export_universe(args.universe, args.out, args.panel)
    except FileNotFoundError as e:
        print(f"REFUSED: {e}")
        return 2
    print(f"wrote {args.out}: {len(df)} names ({int(df['in_cap2000'].sum())} cap2000, "
          f"{int(df['is_benchmark'].sum())} benchmarks), universe "
          f"{df['universe_name'].iloc[0]}, panel date {df['panel_date'].iloc[0]}")
    print(f"Copy it to the Windows box. The pull warns when the panel date is more than "
          f"{store.UNIVERSE_WARN_DAYS} days old and refuses after {store.UNIVERSE_REFUSE_DAYS}.")
    return 0


def check_universe_file(name, session_date, out=print):
    """Exit code for a universe given as a file: None to go on, 2 or 4 to refuse."""
    if name in store.TIERS or name == "panel" or not store.looks_like_path(name):
        return None
    if not Path(name).exists():
        out(f"REFUSED: universe file not found: {name}")
        return 2
    if Path(name).suffix.lower() != ".csv":
        return None
    df = store.read_universe_csv(name)
    if not store.is_exported_universe(df):
        return None                       # a plain ticker list: no age to check
    level, age = store.universe_freshness(df, session_date)
    panel_date = df["panel_date"].iloc[0] if len(df) else None
    if level == "refuse":
        out(f"REFUSED: universe file {name} is {age} days old (panel date {panel_date}; "
            f"limit {store.UNIVERSE_REFUSE_DAYS}). On the Mac run `schwab_pull.py "
            "export-universe --universe cap150 --out <file>` and copy the new file over. "
            "Nothing pulled.")
        return 4
    if level == "warn":
        bar = "!" * 78
        out(f"{bar}\nWARNING: STALE UNIVERSE. {name} is {age} days old (panel date "
            f"{panel_date}; refresh weekly; warn above {store.UNIVERSE_WARN_DAYS} days, refuse "
            f"above {store.UNIVERSE_REFUSE_DAYS}). Pulling anyway. Export a new file on the Mac "
            f"and copy it over.\n{bar}")
    return None


def cmd_pull(args, kinds):
    root = store.data_root(args.data_root)
    today = str(ny_today())
    sd = args.date
    live = [k for k in kinds if k in LIVE_ONLY]
    if sd != today and live and not args.dry_run:
        print(f"REFUSED: {', '.join(live)} are live snapshots and can only be pulled for today "
              f"({today} New York), not {sd}. Schwab has no historical quotes or chains.")
        return 2
    if sd > today:
        print(f"REFUSED: {sd} is in the future")
        return 2
    rc = check_universe_file(args.universe, sd)
    if rc is not None:
        return rc
    if not args.dry_run and not args.allow_closed and not store.is_trading_day(sd):
        # offline calendar: nothing is written and no API call is made
        print(f"Market is closed on {sd} (weekend or NYSE holiday). Nothing pulled, nothing "
              "written (use --allow-closed to override).")
        return 0
    # the universe is frozen to disk only once the market is known to be open
    uni, upath, is_new = store.frozen_universe(root, sd, args.universe, write=False)
    n = len(uni)
    p = pull.plan(n, rate_per_min=args.rate, kinds=kinds)
    client = make_client(args)
    st = client.token_status()
    print(f"session date {sd} (New York) | universe {args.universe}: {n} names "
          f"({int(uni['in_cap2000'].sum())} cap2000, {int(uni['is_benchmark'].sum())} benchmarks; "
          f"panel date {uni['panel_date'].iloc[0]}) | {'frozen now' if is_new else 'already frozen'}"
          f" at {upath}")
    print(f"requests: {p['requests']} = {p['total_requests']} total, about "
          f"{p['minutes_at_limit']} min at {args.rate}/min (Schwab limit 120/min)")
    print(f"data root {root} | token: {st}")
    if st.get("logged_in") and st["refresh_days_left"] < 1.5:
        print("WARNING: the refresh token expires within 1.5 days. Run `schwab_pull.py login`.")

    if args.dry_run:
        if (root / "pull_log.sqlite").exists():
            print("already in the pull log for this date:",
                  store.PullLog(root / "pull_log.sqlite").summary(sd) or "nothing")
        if not st.get("logged_in"):
            print("DRY RUN: not logged in. Run `schwab_pull.py login` first. Nothing written.")
            return 1
        try:   # one read-only market-hours call proves the token works; nothing is written
            hrs = pull.pull_hours(client, None, sd, "dryrun")
        except LoginRequired as e:
            print(f"DRY RUN: {e}")
            return 1
        print(f"DRY RUN: token works (1 market-hours call). Market open on {sd}: "
              f"{hrs['is_open']}; regular session {hrs['start']} to {hrs['end']} UTC. "
              "Nothing written.")
        return 0

    snapshot = store.new_snapshot_id()
    writer = store.SnapshotWriter(root, sd, snapshot, today=today)
    for k in kinds:
        writer.check_writable(k)
    log = store.PullLog(root / "pull_log.sqlite")
    resume = not args.no_resume
    try:
        hrs = pull.pull_hours(client, writer, sd, snapshot)
        if hrs["is_open"] is False and not args.allow_closed:
            print(f"Market is closed on {sd}. Nothing pulled (use --allow-closed to override).")
            return 0
        if is_new:
            upath.parent.mkdir(parents=True, exist_ok=True)
            uni.to_csv(upath, index=False)
        cutoff = hrs["end"] + pull.FINAL_GRACE if hrs["end"] else None
        results = {}
        if "quotes" in kinds:
            results["quotes"] = pull.pull_quotes(client, uni, writer, log, sd, snapshot,
                                                 resume=resume)
        if "chains" in kinds:
            results["chains"] = pull.pull_chains(client, uni, writer, log, sd, snapshot,
                                                 resume=resume)
        if "pricehistory" in kinds:
            results["pricehistory"] = pull.pull_pricehistory(
                client, uni, writer, log, sd, snapshot, lookback_days=args.lookback_days,
                final_cutoff_utc=cutoff, resume=resume)
    except LoginRequired as e:
        print(f"STOPPED: {e}. Progress is saved; re-run the same command after login.")
        return 1
    print(f"done, snapshot {snapshot}, {client.n_requests} requests: {results}")
    print("pull log:", log.summary(sd))
    return 0


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0],
                                 formatter_class=argparse.RawDescriptionHelpFormatter,
                                 epilog=__doc__)
    ap.add_argument("command", choices=["login", "status", "quotes", "chains", "pricehistory",
                                        "daily", "export-universe"])
    ap.add_argument("--universe", default="cap150")
    ap.add_argument("--date", default=str(ny_today()),
                    help="session date, New York (default today)")
    ap.add_argument("--dry-run", action="store_true")
    ap.add_argument("--no-resume", action="store_true")
    ap.add_argument("--allow-closed", action="store_true")
    ap.add_argument("--data-root", default=None)
    ap.add_argument("--rate", type=int, default=110, help="requests per minute (max 120)")
    ap.add_argument("--lookback-days", type=int, default=14,
                    help="calendar days of daily candles per pricehistory call")
    ap.add_argument("--out", default=None, help="export-universe: the csv to write")
    ap.add_argument("--panel", default=None,
                    help="export-universe: panel parquet (default the working panel)")
    ap.add_argument("--min-refresh-days", type=float, default=None,
                    help="status: exit 10 if the refresh token has fewer days left, 11 if "
                         "expired or not logged in")
    ap.add_argument("--visible-paste", action="store_true",
                    help="login: show the pasted URL (if hidden paste fails in the terminal)")
    args = ap.parse_args(argv)
    date.fromisoformat(args.date)
    if not 1 <= args.rate <= 120:
        ap.error("--rate must be between 1 and 120")
    if args.command == "login":
        return cmd_login(args)
    if args.command == "status":
        return cmd_status(args)
    if args.command == "export-universe":
        return cmd_export_universe(args)
    kinds = ("quotes", "chains", "pricehistory") if args.command == "daily" else (args.command,)
    return cmd_pull(args, kinds)


if __name__ == "__main__":
    sys.exit(main())
