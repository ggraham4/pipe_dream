"""
Full compounding equity curve for the confirmed configuration
(cap150_raw / decile_volq / 15bp round-trip), 2007-2026, nomination era
chained into the hold-out era so the curve spans everything this package has
computed. Not a new experiment -- reuses window_returns_for_offset with
NULL_DRAWS forced to 0 (a pure compounding walk needs no null; that machinery
is for the significance tests already run in run_backtest.py) and turns the
real per-window net returns into a $10,000-starting equity curve for every
one of the 40 grid offsets, then averages them pointwise onto a single
calendar-day axis -- the "average over offsets" construction
`sweep/RUNBOOK.md` flags as the not-yet-implemented durable fix for grid-
offset dependence, applied here for visualization rather than a gate.

SPY and USMV are shown two ways: a real continuous buy-and-hold (their own
daily close series, no windowing) and the same 40-day-window construction the
strategy itself uses (from `outcome_cache.parquet`), so both "what if you'd
just bought and held" and "apples-to-apples, same dates, same cadence" are
answerable from the same output.

OUTPUT
    <MAIN_ROOT>/out/reset2026/compounding_curve.json
        per-offset and offset-averaged equity curves, terminal values
"""
import json
import sys
from pathlib import Path

import numpy as np
import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parent))
import composite as C  # noqa: E402
import run_backtest as R  # noqa: E402

MAIN_ROOT = Path("/Users/ggraham/pipe_dream/final")
OUT = MAIN_ROOT / "out" / "reset2026" / "compounding_curve.json"
SPY_CSV = MAIN_ROOT / "scripts" / "td_data_local" / "SPY.csv"
USMV_CSV = MAIN_ROOT / "data" / "benchmarks" / "USMV.csv"

TIER = "cap150"
NEUTRAL = False
METHOD = "decile_volq"
COST_BPS = 15.0
START_VALUE = 10_000.0


def offset_curve(by_date, dates, offset, spy, usmv, rng):
    R.NULL_DRAWS = 0  # pure compounding walk -- no null needed here
    records = R.window_returns_for_offset(by_date, dates, offset, TIER, NEUTRAL, spy, usmv, rng)
    df = pd.DataFrame(records)
    sub = df[(df["method"] == METHOD) & (df["draw"] == "real")].sort_values("date")
    if sub.empty:
        return []
    net = R.turnover_net_return(sub.to_dict("records"), COST_BPS)
    out = []
    for (_, row), n in zip(sub.iterrows(), net):
        out.append({"date": row["date"].strftime("%Y-%m-%d"), "net_return": float(n),
                    "spy_window_return": float(row["spy"]) if pd.notna(row["spy"]) else None,
                    "usmv_window_return": float(row["usmv"]) if pd.notna(row["usmv"]) else None})
    return out


def to_equity(curve_points, value_key="net_return", start=START_VALUE):
    dates, values = [], []
    v = start
    for p in curve_points:
        r = p.get(value_key)
        if r is None:
            continue
        v = v * (1.0 + r)
        dates.append(p["date"])
        values.append(v)
    return dates, values


def main():
    rng = np.random.default_rng(7)

    nom = R.load_data("nominate")
    hold = R.load_data("holdout")

    all_offsets = {}
    for offset in range(R.N_OFFSETS):
        nom_pts = offset_curve(nom[0], nom[1], offset, nom[2], nom[3], rng)
        hold_pts = offset_curve(hold[0], hold[1], offset, hold[2], hold[3], rng)
        combined = nom_pts + hold_pts
        dates, strat_v = to_equity(combined, "net_return")
        _, spy_v = to_equity(combined, "spy_window_return")
        _, usmv_v = to_equity(combined, "usmv_window_return")
        all_offsets[offset] = {"dates": dates, "strategy": strat_v, "spy_window": spy_v, "usmv_window": usmv_v}
        print(f"offset {offset:02d}: {len(dates)} windows, "
              f"terminal ${strat_v[-1] if strat_v else float('nan'):,.0f} "
              f"vs SPY(window) ${spy_v[-1] if spy_v else float('nan'):,.0f}", flush=True)

    # Pointwise average across offsets onto a shared calendar-year-month grid
    # (each offset's windows land on different days -- align by year-month so
    # 40 differently-phased step functions become one comparable curve).
    frames = []
    for offset, d in all_offsets.items():
        if not d["dates"]:
            continue
        df = pd.DataFrame({"date": pd.to_datetime(d["dates"]), "strategy": d["strategy"],
                           "spy_window": d["spy_window"] + [np.nan] * (len(d["dates"]) - len(d["spy_window"])),
                           "offset": offset})
        frames.append(df)
    pooled = pd.concat(frames, ignore_index=True)
    pooled["year_month"] = pooled["date"].dt.to_period("M")
    avg_curve = pooled.groupby("year_month").agg(
        strategy_mean=("strategy", "mean"), strategy_min=("strategy", "min"), strategy_max=("strategy", "max"),
        spy_window_mean=("spy_window", "mean"),
    ).reset_index()
    avg_curve["year_month"] = avg_curve["year_month"].astype(str)

    # Real continuous buy-and-hold, no windowing, normalized to the same start.
    def continuous_bh(csv_path, start_date):
        g = pd.read_csv(csv_path, usecols=["date", "close"], parse_dates=["date"])
        g = g[g["date"] >= start_date].sort_values("date").reset_index(drop=True)
        base = g["close"].iloc[0]
        g["equity"] = START_VALUE * (g["close"] / base)
        return g[["date", "equity"]]

    strat_start = pd.to_datetime(all_offsets[0]["dates"][0])
    spy_bh = continuous_bh(SPY_CSV, strat_start)
    usmv_bh = continuous_bh(USMV_CSV, strat_start)

    terminal = {
        "strategy_mean_terminal": float(avg_curve["strategy_mean"].iloc[-1]),
        "strategy_min_offset_terminal": float(min(d["strategy"][-1] for d in all_offsets.values() if d["strategy"])),
        "strategy_max_offset_terminal": float(max(d["strategy"][-1] for d in all_offsets.values() if d["strategy"])),
        "spy_buyhold_terminal": float(spy_bh["equity"].iloc[-1]),
        "usmv_buyhold_terminal": float(usmv_bh["equity"].iloc[-1]),
        "start_date": strat_start.strftime("%Y-%m-%d"),
        "end_date": all_offsets[0]["dates"][-1],
    }
    print("\n" + json.dumps(terminal, indent=2))

    out = {
        "terminal": terminal,
        "offset_averaged_monthly": avg_curve.to_dict("records"),
        "spy_buyhold": [{"date": d.strftime("%Y-%m-%d"), "equity": float(e)}
                        for d, e in zip(spy_bh["date"], spy_bh["equity"])],
        "usmv_buyhold": [{"date": d.strftime("%Y-%m-%d"), "equity": float(e)}
                         for d, e in zip(usmv_bh["date"], usmv_bh["equity"])],
    }
    OUT.parent.mkdir(parents=True, exist_ok=True)
    OUT.write_text(json.dumps(out))
    print(f"\n-> {OUT}")


if __name__ == "__main__":
    sys.exit(main())
