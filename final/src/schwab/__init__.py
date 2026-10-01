"""Schwab Trader API forward market-data collector (WO-41).

MARKET DATA ONLY. Standing rule (Gabe, 2026-10-01): this package never
places, modifies or cancels an order and never touches an account. There is
no code path to /accounts or /orders; `client.assert_market_data_url`
refuses any URL outside the market-data allowlist. Do not add one.

Design, commands and acceptance criteria:
final/models/2026-10-01-schwab-collector.md
"""
