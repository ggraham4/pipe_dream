"""
Local ledger for running the PIT buy signal (final/src/current_signal_pit.py,
see lib/pit_model.py) as a paper-trading test in Schwab thinkorswim's
paperMoney simulator.

HARD SAFETY BOUNDARY -- READ BEFORE TOUCHING THIS FILE
--------------------------------------------------------
This module makes NO network calls, holds NO brokerage credentials, and
imports NO broker/trading API client. That is deliberate, not an oversight:
Schwab's Trader API has no order-entry surface for paperMoney at all (it only
sees real, live brokerage accounts -- confirmed against developer.schwab.com
and the schwab-py project, 2026-09-18), so the only way to guarantee this
never touches LiveTrading is for the code to be structurally incapable of
placing ANY order anywhere. A permission check or account-ID allowlist is not
enough -- it still requires holding a live-capable credential and trusting
code not to misuse it. This file holds no such credential, on purpose.

The output of this module is a human-readable order sheet. A person reads it
and hand-enters each line into thinkorswim's paperMoney blotter -- never
LiveTrading -- themselves. If you are tempted to add a "just auto-submit it"
mode, don't: that would require adding exactly the credential this design
exists to avoid holding. Take it to Gabe first.

Ledger mechanics
-----------------
Sizing is off a fixed `base_equity` (default $200,000 -- thinkorswim
paperMoney's default starting balance), not a live account value, since
there is no API to read the real paperMoney balance. The ledger is this
tool's own bookkeeping of what it last told you to hold; it is only as
accurate as your last `confirm` run. Re-sync it by hand if your real
paperMoney fills ever diverge (partial fills, price gaps, manual trades
placed outside this tool).
"""
from __future__ import annotations

import json
from datetime import date, datetime, timezone
from pathlib import Path

from . import paths

LEDGER_PATH = paths.OUT_DIR / "paper_ledger.json"
ORDERS_DIR = paths.OUT_DIR / "paper_orders"

DEFAULT_STARTING_EQUITY = 200_000.0  # thinkorswim paperMoney's default balance

VARIANT_META = {
    "q75": paths.OUT_DIR / "current_signal_pit_meta.json",
    "xrank": paths.OUT_DIR / "current_signal_pit_xrank_meta.json",
}


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def new_ledger(starting_equity: float = DEFAULT_STARTING_EQUITY, variant: str = "q75") -> dict:
    return {
        "account_label": "paperMoney (thinkorswim) -- simulated locally, never traded via any API",
        "starting_equity": starting_equity,
        "base_equity": starting_equity,
        "variant": variant,
        "cash": starting_equity,
        "positions": {},  # ticker -> shares (int)
        "created": _now_iso(),
        "last_rebalance_date": None,
        "pending_sheet": None,
        "history": [],
    }


def load_ledger() -> dict:
    if not LEDGER_PATH.exists():
        return new_ledger()
    with open(LEDGER_PATH) as f:
        return json.load(f)


def save_ledger(ledger: dict) -> None:
    paths.OUT_DIR.mkdir(parents=True, exist_ok=True)
    with open(LEDGER_PATH, "w") as f:
        json.dump(ledger, f, indent=2)


def load_signal(variant: str) -> dict:
    meta_path = VARIANT_META.get(variant)
    if meta_path is None:
        raise ValueError(f"unknown variant {variant!r}, expected one of {list(VARIANT_META)}")
    if not meta_path.exists():
        raise FileNotFoundError(
            f"{meta_path} not found -- run the {variant} signal refresh in the app first"
        )
    with open(meta_path) as f:
        return json.load(f)


def build_order_sheet(ledger: dict, variant: str | None = None) -> dict:
    """Diff target allocation (from the latest signal) against the ledger's
    last-known positions. Does NOT mutate the ledger -- call apply_order_sheet
    after the orders have actually been hand-entered in paperMoney."""
    variant = variant or ledger.get("variant", "q75")
    signal = load_signal(variant)
    base_equity = ledger.get("base_equity", DEFAULT_STARTING_EQUITY)
    current_positions = dict(ledger.get("positions", {}))

    targets = {}
    for row in signal["allocation"]:
        ticker = row["ticker"]
        close = row["close"]
        target_dollars = base_equity * row["allocation_pct"] / 100.0
        target_shares = int(target_dollars // close)  # whole shares only, round down
        targets[ticker] = {
            "shares": target_shares,
            "close": close,
            "allocation_pct": row["allocation_pct"],
            "stop_loss_price": row.get("suggested_stop_loss_price"),
        }

    tickers_touched = set(targets) | set(current_positions)
    orders = []
    for ticker in sorted(tickers_touched):
        have = int(current_positions.get(ticker, 0))
        want = targets.get(ticker, {}).get("shares", 0)
        delta = want - have
        if delta == 0:
            continue
        info = targets.get(ticker)
        close = info["close"] if info else None
        orders.append({
            "ticker": ticker,
            "side": "BUY" if delta > 0 else "SELL",
            "qty": abs(delta),
            "ref_price": close,
            "est_value": round(abs(delta) * close, 2) if close else None,
            "stop_loss_price": info["stop_loss_price"] if info else None,
            "target_shares": want,
            "prior_shares": have,
        })

    sheet = {
        "generated_at": _now_iso(),
        "variant": variant,
        "as_of_date": signal.get("as_of_date"),
        "base_equity": base_equity,
        "target_positions": targets,
        "orders": orders,
        "account": "paperMoney ONLY -- do not enter these in LiveTrading",
    }
    return sheet


def sheet_path_for(sheet: dict) -> Path:
    as_of = sheet.get("as_of_date") or date.today().isoformat()
    return ORDERS_DIR / f"{as_of}_{sheet['variant']}.json"


def save_order_sheet(sheet: dict, ledger: dict) -> Path:
    ORDERS_DIR.mkdir(parents=True, exist_ok=True)
    out_path = sheet_path_for(sheet)
    with open(out_path, "w") as f:
        json.dump(sheet, f, indent=2)
    ledger["pending_sheet"] = str(out_path)
    save_ledger(ledger)
    return out_path


def render_order_sheet(sheet: dict) -> str:
    lines = []
    lines.append("=" * 72)
    lines.append("PAPER ORDER SHEET -- thinkorswim paperMoney ONLY")
    lines.append("Do NOT enter these orders in LiveTrading / any live account.")
    lines.append("=" * 72)
    lines.append(f"variant: {sheet['variant']}   as_of: {sheet['as_of_date']}   "
                  f"base_equity: ${sheet['base_equity']:,.2f}")
    lines.append("")
    if not sheet["orders"]:
        lines.append("No changes -- current ledger already matches the target allocation.")
    else:
        lines.append(f"{'SIDE':<5} {'TICKER':<7} {'QTY':>6}  {'REF PX':>10}  {'EST VALUE':>12}  {'STOP':>10}")
        for o in sheet["orders"]:
            stop = f"{o['stop_loss_price']:.2f}" if o["stop_loss_price"] else "--"
            ref = f"{o['ref_price']:.2f}" if o["ref_price"] else "--"
            val = f"{o['est_value']:,.2f}" if o["est_value"] else "--"
            lines.append(f"{o['side']:<5} {o['ticker']:<7} {o['qty']:>6}  {ref:>10}  {val:>12}  {stop:>10}")
    lines.append("")
    lines.append("Reference prices are the signal's last close, not a live quote -- check the")
    lines.append("actual paperMoney fill price before sizing anything close to a round number.")
    lines.append("After entering these by hand in paperMoney, run: paper_orders.py confirm")
    return "\n".join(lines)


def apply_order_sheet(ledger: dict, sheet: dict) -> dict:
    """Mark the sheet as filled at its reference prices and roll the ledger
    forward. Call this only after the orders were actually placed by hand in
    paperMoney."""
    positions = dict(ledger.get("positions", {}))
    cash = ledger.get("cash", ledger.get("base_equity", DEFAULT_STARTING_EQUITY))

    for o in sheet["orders"]:
        signed_qty = o["qty"] if o["side"] == "BUY" else -o["qty"]
        new_shares = int(positions.get(o["ticker"], 0)) + signed_qty
        if new_shares == 0:
            positions.pop(o["ticker"], None)
        else:
            positions[o["ticker"]] = new_shares
        if o["ref_price"]:
            cash -= signed_qty * o["ref_price"]

    ledger["positions"] = positions
    ledger["cash"] = round(cash, 2)
    ledger["variant"] = sheet["variant"]
    ledger["last_rebalance_date"] = sheet["as_of_date"]
    ledger["pending_sheet"] = None
    ledger.setdefault("history", []).append({
        "applied_at": _now_iso(),
        "as_of_date": sheet["as_of_date"],
        "variant": sheet["variant"],
        "orders": sheet["orders"],
    })
    return ledger


def mark_to_market(ledger: dict, variant: str | None = None) -> dict:
    """Best-effort valuation using the latest signal's close prices. Tickers
    held but no longer in the signal universe keep no live price here --
    check paperMoney directly for those."""
    variant = variant or ledger.get("variant", "q75")
    try:
        signal = load_signal(variant)
        prices = {row["ticker"]: row["close"] for row in signal["allocation"]}
    except FileNotFoundError:
        prices = {}

    positions = ledger.get("positions", {})
    priced_value = 0.0
    unpriced = []
    for ticker, shares in positions.items():
        if ticker in prices:
            priced_value += shares * prices[ticker]
        else:
            unpriced.append(ticker)

    return {
        "cash": ledger.get("cash", 0.0),
        "priced_positions_value": round(priced_value, 2),
        "unpriced_tickers": unpriced,
        "estimated_total": round(ledger.get("cash", 0.0) + priced_value, 2),
        "starting_equity": ledger.get("starting_equity", DEFAULT_STARTING_EQUITY),
    }
