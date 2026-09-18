#!/usr/bin/env python3
"""
CLI for the paperMoney-only order sheet workflow. See lib/paper_broker.py for
the hard safety boundary this is built on: no broker API, no credentials, no
code path that could ever place a live order. This script prints instructions
for a human to hand-enter into thinkorswim paperMoney -- nothing more.

Usage (run from final/app/):
    python paper_orders.py sheet [--variant q75|xrank]
        Compute target allocation from the latest signal, diff it against the
        local ledger, print + save an order sheet. Does not change the ledger.

    python paper_orders.py confirm [--sheet PATH]
        AFTER you have hand-entered the pending sheet's orders in paperMoney,
        run this to roll the local ledger forward to match. Defaults to the
        ledger's pending_sheet.

    python paper_orders.py status
        Print current ledger positions, cash, and a best-effort mark-to-market
        total using the latest signal's close prices.

    python paper_orders.py reset [--equity 200000]
        Wipe the local ledger and start over (e.g. new paperMoney account).
"""
from __future__ import annotations

import argparse
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from lib import paper_broker as pb


def cmd_sheet(args):
    ledger = pb.load_ledger()
    sheet = pb.build_order_sheet(ledger, variant=args.variant)
    out_path = pb.save_order_sheet(sheet, ledger)
    print(pb.render_order_sheet(sheet))
    print(f"\nSaved to {out_path}")


def cmd_confirm(args):
    ledger = pb.load_ledger()
    sheet_path = Path(args.sheet) if args.sheet else (
        Path(ledger["pending_sheet"]) if ledger.get("pending_sheet") else None
    )
    if sheet_path is None or not sheet_path.exists():
        print("No pending order sheet found. Run `sheet` first, or pass --sheet PATH.")
        sys.exit(1)
    import json
    with open(sheet_path) as f:
        sheet = json.load(f)

    print(pb.render_order_sheet(sheet))
    resp = input(
        "\nConfirm: have you entered ALL of the above in thinkorswim paperMoney "
        "(not LiveTrading)? [y/N] "
    ).strip().lower()
    if resp != "y":
        print("Not applied. Ledger unchanged.")
        return

    ledger = pb.apply_order_sheet(ledger, sheet)
    pb.save_ledger(ledger)
    print(f"Ledger updated. Positions: {ledger['positions']}")
    print(f"Cash: ${ledger['cash']:,.2f}")


def cmd_status(args):
    ledger = pb.load_ledger()
    mtm = pb.mark_to_market(ledger, variant=args.variant)
    print(f"variant: {ledger.get('variant')}   last_rebalance: {ledger.get('last_rebalance_date')}")
    print(f"positions: {ledger.get('positions') or '(flat)'}")
    print(f"cash: ${mtm['cash']:,.2f}")
    print(f"priced positions value: ${mtm['priced_positions_value']:,.2f}")
    if mtm["unpriced_tickers"]:
        print(f"unpriced (check paperMoney directly): {mtm['unpriced_tickers']}")
    print(f"estimated total: ${mtm['estimated_total']:,.2f}  "
          f"(started at ${mtm['starting_equity']:,.2f})")
    if ledger.get("pending_sheet"):
        print(f"\nPending, unconfirmed sheet: {ledger['pending_sheet']}")


def cmd_reset(args):
    resp = input(
        f"This wipes {pb.LEDGER_PATH} and starts a fresh local ledger at "
        f"${args.equity:,.2f}. Continue? [y/N] "
    ).strip().lower()
    if resp != "y":
        print("Not reset.")
        return
    ledger = pb.new_ledger(starting_equity=args.equity, variant=args.variant)
    pb.save_ledger(ledger)
    print(f"New ledger created: ${args.equity:,.2f}, variant={args.variant}")


def main():
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = parser.add_subparsers(dest="cmd", required=True)

    p_sheet = sub.add_parser("sheet", help="Generate a paperMoney order sheet from the latest signal")
    p_sheet.add_argument("--variant", choices=["q75", "xrank"], default=None)
    p_sheet.set_defaults(func=cmd_sheet)

    p_confirm = sub.add_parser("confirm", help="Apply a hand-entered order sheet to the local ledger")
    p_confirm.add_argument("--sheet", default=None, help="Path to a specific sheet JSON (default: pending)")
    p_confirm.set_defaults(func=cmd_confirm)

    p_status = sub.add_parser("status", help="Show current ledger positions and estimated value")
    p_status.add_argument("--variant", choices=["q75", "xrank"], default=None)
    p_status.set_defaults(func=cmd_status)

    p_reset = sub.add_parser("reset", help="Start a fresh local ledger")
    p_reset.add_argument("--equity", type=float, default=pb.DEFAULT_STARTING_EQUITY)
    p_reset.add_argument("--variant", choices=["q75", "xrank"], default="q75")
    p_reset.set_defaults(func=cmd_reset)

    args = parser.parse_args()
    args.func(args)


if __name__ == "__main__":
    main()
