"""
Detects and neutralizes fabricated single-day price "returns" caused by
unadjusted corporate-action discontinuities (bankruptcy-reorganization
equity conversions, botched split adjustments, and similar data-vendor
artifacts) -- built 2026-09-01 after `continuous_walkforward_pit.py`'s
first real run produced an obviously-impossible $10k -> $797M augmented
result.

Root cause, confirmed against real data: CHRD (Chord Energy) traded at
$0.09-0.17/share through mid-November 2020 (Whiting Petroleum's stock,
mid-Chapter-11), then jumped to $31.00 on 2020-11-20 -- Whiting's actual
emergence from bankruptcy as the reorganized Chord Energy. The old
(worthless, about-to-be-cancelled) pre-petition equity and the new
(real, continuing) post-reorg equity got stored as one continuous ticker
series, so `forward_return_40` computed a +6,254% "return" for a window
that straddled the reorg -- a return no real investor could have earned
(pre-petition equity holders are typically wiped out or diluted to a
token stake in a Chapter 11, not converted 1:1 into the new company).
Scanning the full panel for `forward_return_40 > 300%` found 117 tickers;
most are real (if extreme) volatility -- GME's actual 2021 squeeze, MARA,
several 2024-2025 quantum-computing/crypto-treasury meme stocks -- but a
handful (CHRD by far the worst, plus similar step-pattern cases) carry
the unmistakable signature of a data seam: price is flat for days, jumps
10x+ in a single session, and continues trading at the new level with no
per-day amplitude consistent with the jump being organic.

This module flags that specific pattern -- NOT "a big one-day move"
generically, which would falsely nuke real volatility -- and splits the
ticker's history at the break point into two independent synthetic
ticker identities, so no rolling feature or forward-return label ever
spans the seam. This is the same "flag and quarantine rather than guess"
philosophy this project already uses for recycled ticker symbols
(features_pit.py's validate_gap_coverage()) and untrustworthy delisting
dates (KNOWN_DELISTING_DATES) -- extended to a new failure mode.

Detection rule (deliberately conservative -- calibrated against real
data, see the module's origin above):
  A break is flagged at date D for ticker T when BOTH:
    1. close[D] / close[D-1] > UP_RATIO_THRESHOLD (a same-day 8x+ gain)
       OR close[D] / close[D-1] < DOWN_RATIO_THRESHOLD (a same-day 87.5%+
       loss, i.e. down to <1/8th)
    2. close[D-1] / close[D-2] is within FLAT_TOLERANCE of 1.0 (the prior
       day was itself close to flat) -- this is what separates a data
       seam (dormant, near-zero-volatility trading right up to the break,
       then one clean jump) from genuine organic volatility, which keeps
       moving day-to-day even during its most extreme stretch. Verified
       against real tickers before shipping: this rule catches CHRD
       (258x), DFTX (48x up / 0.021x down), ALM (9.95x), IVT (10.08x up /
       0.10x down), EQ (8.31x) -- all flat-then-step patterns -- while
       leaving GME (2021 squeeze, max 2.35x/day), MARA, BMNR (2025 rally,
       7.95x -- deliberately just under the threshold), RGTI, QBTS, LUNR,
       and TGTX (a real, continued-volatility biotech crash, not a single
       clean step) untouched.

This is explicitly a first pass, not a final classifier -- Gabe's own
framing for this whole exercise ("we will keep doing this until nothing
suspicious pops out"). If a future run's top-return list still shows an
implausible single-window number, check whether the responsible ticker
has a break pattern this rule's thresholds don't catch (a slower-motion
version of the same artifact, e.g. spread over 2-3 days instead of one)
before assuming the model actually earned it.

Known limitation, not fixed here: a GAP ticker (one of the 339 in
sharadar_data_pull.py's GAP_TICKERS) that also has a detected break gets
a segmented identity like "TICKER__post20081015" for its post-break rows
-- these renamed rows no longer match the original symbol in
`gap_tickers_used.json` or in pit_universe_continuous's real-symbol
lookups, so they fall through to being treated as ordinary current-
universe candidates (always eligible, no PIT date restriction) rather
than correctly gap-restricted. Narrow in practice (requires a historical
gap ticker to ALSO have kept trading for years after a reorg under the
same symbol), not fixed here for time -- flagging it rather than leaving
it silent.
"""
import pandas as pd

UP_RATIO_THRESHOLD = 8.0
DOWN_RATIO_THRESHOLD = 1.0 / 8.0
FLAT_TOLERANCE = 0.05  # prior day's ratio must be within +/-5% of 1.0


def find_and_apply_breaks(data: pd.DataFrame, ticker_col: str = "ticker",
                           date_col: str = "date", close_col: str = "close"):
    """data: long-format df with at least [ticker_col, date_col, close_col],
    one row per ticker per trading day. Must already be sorted by
    [ticker_col, date_col] (features_pit.py's load_all_tickers_pit()
    already returns data in this order).

    Returns (data_with_segmented_tickers, ticker_orig_col_name, breaks_found)
    where:
      - data_with_segmented_tickers: same df, with `ticker_col` rewritten
        to a synthetic "{orig}__post{YYYYMMDD}" identity for every row
        from a detected break date onward (chained through multiple
        breaks on the same ticker), and a new column "ticker_orig"
        holding the real, original symbol for every row (needed so a
        fundamentals merge keyed on the real symbol still works).
      - breaks_found: list of dicts, one per detected break, with the
        original ticker, the break date, the price on each side, and the
        ratio -- for printing/logging so this is never a silent rewrite.
    """
    data = data.copy()
    data["ticker_orig"] = data[ticker_col]

    breaks_found = []
    new_ticker_col = []

    for ticker, g in data.groupby(ticker_col, sort=False):
        idx = g.index
        closes = g[close_col].values
        dates = g[date_col].values
        n = len(closes)

        ratio = [None] * n
        for i in range(1, n):
            prev = closes[i - 1]
            if prev and prev > 0:
                ratio[i] = closes[i] / prev

        # ratio one step further back (prior-day-to-prior-prior-day), used
        # for the "was it flat right before the jump" check
        prior_ratio = [None] * n
        for i in range(1, n):
            if ratio[i - 1] is not None:
                prior_ratio[i] = ratio[i - 1]

        segment_suffix = ""  # applied to every row from the most recent break onward
        local_labels = [None] * n
        for i in range(n):
            is_break = False
            if i >= 2 and ratio[i] is not None and prior_ratio[i] is not None:
                jump = ratio[i] > UP_RATIO_THRESHOLD or ratio[i] < DOWN_RATIO_THRESHOLD
                was_flat = abs(prior_ratio[i] - 1.0) <= FLAT_TOLERANCE
                if jump and was_flat:
                    is_break = True

            if is_break:
                break_date = pd.Timestamp(dates[i])
                breaks_found.append({
                    "ticker": ticker,
                    "break_date": str(break_date.date()),
                    "close_before": float(closes[i - 1]),
                    "close_after": float(closes[i]),
                    "ratio": float(ratio[i]),
                })
                segment_suffix = f"__post{break_date.strftime('%Y%m%d')}"

            local_labels[i] = f"{ticker}{segment_suffix}"

        new_ticker_col.extend(local_labels)

    data[ticker_col] = new_ticker_col
    return data, "ticker_orig", breaks_found


def print_breaks_report(breaks_found):
    if not breaks_found:
        print("Price-discontinuity check: no suspected corporate-action "
              "artifacts found (nothing cleared the UP/DOWN ratio + "
              "flat-before-jump thresholds).")
        return
    print(f"Price-discontinuity check: {len(breaks_found)} suspected "
          f"data-artifact break(s) found and segmented (see price_discontinuity.py's "
          f"module docstring for the detection rule and its known limitations). "
          f"Each split ticker keeps ALL its data -- only the LABEL/FEATURE "
          f"computation is prevented from spanning the seam:")
    for b in sorted(breaks_found, key=lambda b: -b["ratio"] if b["ratio"] >= 1 else -1 / b["ratio"]):
        direction = "UP" if b["ratio"] > 1 else "DOWN"
        print(f"  {b['ticker']:10s} {b['break_date']}  {direction}  "
              f"{b['close_before']:.4f} -> {b['close_after']:.4f}  "
              f"(ratio {b['ratio']:.2f}x)")
