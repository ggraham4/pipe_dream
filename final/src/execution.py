"""
Realistic execution / position-realization engine (Round 9, 2026-09-07).

Motivation
----------
An independent methodology review of the PIT augmented + stop-loss model
raised four execution-layer problems, all of which inflate the backtest:

  1. SAME-BAR EXECUTION. Features were computed from close[t]
     (features.py:162-175) and the recorded entry price was that same
     close (continuous_walkforward_pit.py:330). A signal cannot be
     computed from the closing print and also transacted at it.

  2. EXACT STOP FILLS. simulate_stop_loss() booked every stop at
     precisely -stop_pct. On names selected for maximum trailing
     volatility, a material share of stops are gap-throughs that would
     have filled far below the trigger.

  3. NO TRANSACTION COSTS. No commission, spread, slippage or impact
     model existed anywhere in the pipeline, against ~475% one-way
     annual turnover plus stop exits.

  4. SURVIVORSHIP AT THE EXIT. Positions whose price series ends inside
     the holding window were dropped rather than exited at the last
     available print.

This module is the single place all four are fixed, so every backtest
variant realizes positions the same way instead of each script growing
its own copy of the arithmetic.

Conventions
-----------
`tp` (the timepoint) is the SIGNAL date: features are computed from
close[tp]. Nothing on bar `tp` is tradable. Entry happens `entry_lag`
bars later (default 1 = the next trading day), at that bar's open by
default -- the honest convention, since the signal is known after the
close of `tp` and the next opportunity to transact is the following
open.

The holding window is `horizon` bars measured from the entry bar. A
stop is checked against each bar's low; when it triggers, the fill is
`min(stop_price, bar_open)`, so a bar that gapped straight through the
trigger books the gap, not the trigger. When the price series ends
before the horizon does, the position exits at the last available
close (the delisting exit floor) rather than being dropped.

Costs are a round-trip figure in basis points, applied half on each
side: buy at entry*(1 + c/2), sell at exit*(1 - c/2).
"""

import numpy as np
import pandas as pd

# Defaults chosen from the review's turnover and price analysis: median
# entry price $35.63, but 135 of 614 picks under $20 and 23 under $10, on
# high-volatility mid-caps traded with resting stop orders. 50bp
# round-trip is a central estimate for that book, not a stress case.
# Round 9 (2026-09-07). Was 50bp, taken from the review's assertion that
# "50-100bp round-trip is realistic" for high-volatility mid-caps traded with
# resting stop orders. That was never checked against how this account
# actually trades, and it is roughly 3-5x too high for it: at the median pick
# price of ~$37, 50bp round trip is ~9 cents/share PER SIDE (~18 cents round
# trip), whereas a few cents per share one way is ~11-17bp round trip.
#
# 15bp ~= 2.8 cents/share per side at $37. Set --cost-bps explicitly to match
# real fills. Stop-loss configurations still deserve a higher figure than the
# unstopped ones, since a triggered stop crosses the spread in a fast market.
DEFAULT_COST_BPS = 15.0
DEFAULT_ENTRY_LAG = 1
DEFAULT_ENTRY_AT = "open"

_REQUIRED_COLS = ("date", "open", "high", "low", "close")


def realize_position(prices, tp, horizon, entry_lag=DEFAULT_ENTRY_LAG,
                     entry_at=DEFAULT_ENTRY_AT, stop_pct=None,
                     cost_bps=DEFAULT_COST_BPS):
    """Realize one position from the actual OHLC path.

    prices    : DataFrame for ONE ticker with columns date/open/high/low/
                close, sorted ascending by date.
    tp        : signal date (pd.Timestamp). close[tp] produced the signal;
                bar tp is NOT tradable.
    horizon   : holding period in trading days, measured from the entry bar.
    entry_lag : bars after tp at which the position is opened (1 = next bar).
    entry_at  : "open" or "close" of the entry bar.
    stop_pct  : e.g. 0.15 for a 15% stop, or None for no stop.
    cost_bps  : round-trip transaction cost in basis points.

    Returns a dict describing the realized position, or None when the
    position was never tradable (no bar after tp).
    """
    future = prices[prices["date"] > tp]

    if entry_lag == 0:
        # The as-published convention, kept only so the corrected engine can
        # reproduce the original numbers for comparison: the signal bar's own
        # close is also the entry price. This is the same-bar execution the
        # review flags -- not a tradable assumption.
        sig = prices[prices["date"] == tp]
        if sig.empty:
            return None
        entry_row = sig.iloc[0]
        entry_price = float(entry_row["close"])
        window = future.iloc[:horizon]
    else:
        if len(future) < entry_lag:
            return None
        entry_row = future.iloc[entry_lag - 1]
        entry_price = float(entry_row["open"] if entry_at == "open" else entry_row["close"])
        # Bars over which the position is exposed. Entering at the open of the
        # entry bar means that bar's own intraday range can stop us out;
        # entering at its close means exposure starts with the following bar.
        first_exposed = entry_lag - 1 if entry_at == "open" else entry_lag
        window = future.iloc[first_exposed:first_exposed + horizon]

    if not np.isfinite(entry_price) or entry_price <= 0:
        return None
    if window.empty:
        return None

    truncated = len(window) < horizon  # series ended inside the window

    exit_price = float(window["close"].iloc[-1])
    exit_date = window["date"].iloc[-1]
    exit_reason = "horizon" if not truncated else "series_end"
    stopped = False
    gap_through = False

    if stop_pct is not None:
        stop_price = entry_price * (1.0 - stop_pct)
        hit = window[window["low"] <= stop_price]
        if not hit.empty:
            bar = hit.iloc[0]
            bar_open = float(bar["open"])
            # A bar that opened at or below the stop never offered the
            # trigger price -- the realistic fill is the open.
            fill = min(stop_price, bar_open) if np.isfinite(bar_open) else stop_price
            gap_through = fill < stop_price - 1e-12
            exit_price = float(fill)
            exit_date = bar["date"]
            exit_reason = "stop"
            stopped = True

    half = (cost_bps / 1e4) / 2.0
    eff_entry = entry_price * (1.0 + half)
    eff_exit = exit_price * (1.0 - half)

    gross_return = exit_price / entry_price - 1.0
    net_return = eff_exit / eff_entry - 1.0

    return {
        "entry_date": entry_row["date"],
        "entry_price": entry_price,
        "exit_date": exit_date,
        "exit_price": exit_price,
        "gross_return": float(gross_return),
        "net_return": float(net_return),
        "stopped": bool(stopped),
        "gap_through": bool(gap_through),
        "truncated": bool(truncated),
        "exit_reason": exit_reason,
        "bars_held": int(len(window)),
    }


def realize_portfolio(picks, price_by_ticker, tp, horizon,
                      entry_lag=DEFAULT_ENTRY_LAG, entry_at=DEFAULT_ENTRY_AT,
                      stop_pct=None, cost_bps=DEFAULT_COST_BPS):
    """Equal-weight a list of tickers through realize_position().

    Returns (portfolio_dict, per_ticker_dict). Tickers that were never
    tradable are excluded from the weighting; if none were tradable the
    portfolio dict is None.
    """
    per_ticker = {}
    for ticker in picks:
        g = price_by_ticker.get(ticker)
        if g is None or g.empty:
            continue
        pos = realize_position(g, tp, horizon, entry_lag=entry_lag,
                               entry_at=entry_at, stop_pct=stop_pct,
                               cost_bps=cost_bps)
        if pos is not None:
            per_ticker[ticker] = pos

    if not per_ticker:
        return None, per_ticker

    w = 1.0 / len(per_ticker)
    gross = sum(w * (1.0 + p["gross_return"]) for p in per_ticker.values()) - 1.0
    net = sum(w * (1.0 + p["net_return"]) for p in per_ticker.values()) - 1.0

    portfolio = {
        "n_positions": len(per_ticker),
        "gross_return": float(gross),
        "net_return": float(net),
        "n_stopped": int(sum(p["stopped"] for p in per_ticker.values())),
        "n_gap_through": int(sum(p["gap_through"] for p in per_ticker.values())),
        "n_truncated": int(sum(p["truncated"] for p in per_ticker.values())),
    }
    return portfolio, per_ticker


class LazyOHLCPanel:
    """Dict-like OHLC panel that reads a ticker's CSV on first use.

    Round 9 (2026-09-07): the walk-forward only ever realizes TOP_N picks per
    window, so eagerly loading ~1,800 tickers of full daily history costs
    hundreds of MB for data that is mostly never touched. This loads on
    demand and caches what it has seen, which is a few hundred tickers by the
    end of a run.
    """

    def __init__(self, dirs):
        from pathlib import Path
        self._dirs = [Path(d) for d in dirs]
        self._cache = {}

    def get(self, ticker, default=None):
        if ticker in self._cache:
            return self._cache[ticker]
        df = None
        for d in self._dirs:
            path = d / f"{ticker}.csv"
            if path.exists():
                try:
                    df = pd.read_csv(path, usecols=list(_REQUIRED_COLS),
                                     parse_dates=["date"])
                    df = df.sort_values("date").reset_index(drop=True)
                except Exception:
                    df = None
                break
        self._cache[ticker] = df
        return df if df is not None else default

    def __getitem__(self, ticker):
        v = self.get(ticker)
        if v is None:
            raise KeyError(ticker)
        return v

    def __contains__(self, ticker):
        return self.get(ticker) is not None

    def __len__(self):
        return len(self._cache)


class SegmentedOHLCPanel(LazyOHLCPanel):
    """Lazy OHLC panel that respects price_discontinuity.py's segmentation.

    Round 9 (2026-09-07). price_discontinuity.py splits a ticker at a
    detected break into "CHRD" and "CHRD__post20201120", because the two
    sides are not the same security -- CHRD's 2020 bankruptcy reorg takes
    the back-adjusted price from $0.12 to $31.00 in one bar, a 258x move
    that no holder ever received.

    The raw per-ticker CSVs are NOT segmented. Pricing a position out of
    them therefore prices straight through the break. This is not
    hypothetical: the first corrected retrain booked a +6,209% window on a
    CHRD pick entered at $0.12.

    Before Round 9 this could not happen, because the pre-break segment's
    forward label is NaN near the break and the old
    `dropna(subset=[LABEL_COL])` removed those rows from the candidate pool
    entirely. Removing that dropna (the survivorship fix) is correct, but it
    exposes these rows -- so execution has to honour the segment boundary
    instead. A position whose segment ends inside the holding window exits
    at the segment's last print, which is exactly the delisting exit floor.
    """

    def __init__(self, dirs, segments):
        super().__init__(dirs)
        self._segments = segments or {}
        self._seg_cache = {}

    def get(self, ticker, default=None):
        if ticker in self._seg_cache:
            return self._seg_cache[ticker]
        seg = self._segments.get(ticker)
        orig = seg[0] if seg else ticker
        base = super().get(orig)
        if base is None:
            self._seg_cache[ticker] = None
            return default
        if seg is not None:
            lo, hi = seg[1], seg[2]
            base = base[(base["date"] >= lo) & (base["date"] <= hi)]
            base = base.reset_index(drop=True)
        self._seg_cache[ticker] = base
        return base if len(base) else default


def apply_turnover_costs(results, cost_bps, key="gross_return_pct"):
    """Charge transaction costs on ACTUAL turnover, not on every position in
    every window.

    Round 9 (2026-09-07), Gabe's point: the walk-forward rebalances every 40
    trading days, but a name the model re-selects is simply HELD -- there is
    no sale and no repurchase, so there is no round trip to pay for. Charging
    one anyway overstates costs by about a third: measured on the corrected
    retrain, 75% of each window's book is new and 75% is exited, not 100%.

    A position pays:
      - the entry half-spread only if it was NOT held in the previous window
      - the exit half-spread only if it is NOT held in the next window

    so  (1 + net) = (1 + gross) * (1 - h*exit) / (1 + h*entry),  h = bps/2.

    Exact when a window records `per_ticker_gross` (each position priced
    individually); otherwise it falls back to applying the window's new- and
    exited-fractions to the portfolio return, which agrees to first order and
    differs only through the covariance between a position's return and
    whether it happened to be carried.
    """
    seq = sorted(results, key=lambda r: r["timepoint"])
    h = (cost_bps / 1e4) / 2.0
    for i, r in enumerate(seq):
        ex = r.get("execution")
        if not ex or ex.get(key) is None:
            continue
        cur = list(r["picks"])
        if not cur:
            continue
        prev = set(seq[i - 1]["picks"]) if i > 0 else set()
        nxt = set(seq[i + 1]["picks"]) if i < len(seq) - 1 else set()

        pt = ex.get("per_ticker_gross")
        if pt:
            names = [t for t in cur if t in pt]
            if not names:
                continue
            w = 1.0 / len(names)
            net = sum(w * (1.0 + pt[t])
                      * (1.0 - h * (0.0 if t in nxt else 1.0))
                      / (1.0 + h * (0.0 if t in prev else 1.0))
                      for t in names) - 1.0
            f_new = sum(1 for t in names if t not in prev) / len(names)
            f_exit = sum(1 for t in names if t not in nxt) / len(names)
        else:
            f_new = sum(1 for t in cur if t not in prev) / len(cur)
            f_exit = sum(1 for t in cur if t not in nxt) / len(cur)
            gross = ex[key] / 100.0
            net = (1.0 + gross) * (1.0 - h * f_exit) / (1.0 + h * f_new) - 1.0

        r["model_return_pct"] = round(float(net) * 100, 2)
        ex["frac_new"] = round(float(f_new), 3)
        ex["frac_exit"] = round(float(f_exit), 3)
        ex["cost_model"] = "turnover_aware"
        ex["cost_bps"] = cost_bps
        spy = r.get("spy_return_pct")
        if spy is not None:
            r["beat_spy"] = bool(net > spy / 100.0)
    return seq


def load_ohlc_panel(dirs, tickers=None):
    """Build {ticker: DataFrame[date,open,high,low,close]} from one or more
    directories of per-ticker CSVs (e.g. td_data_local and
    td_data_delisted). Earlier directories win on a name collision.
    """
    from pathlib import Path

    panel = {}
    for d in dirs:
        d = Path(d)
        if not d.exists():
            continue
        for path in sorted(d.glob("*.csv")):
            t = path.stem
            if t in panel:
                continue
            if tickers is not None and t not in tickers:
                continue
            try:
                df = pd.read_csv(path, usecols=list(_REQUIRED_COLS),
                                 parse_dates=["date"])
            except Exception:
                continue
            df = df.sort_values("date").reset_index(drop=True)
            panel[t] = df
    return panel
