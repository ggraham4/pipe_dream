"""
pipe_dream model dashboard.

Run it from inside final/app/:
    pip install -r requirements.txt
    streamlit run app.py

This is a thin presentation layer over the two model pipelines that already
live in this repo (final/src/ for the stock buy/no-buy model, final/models/
+ app/lib/options_common.py for the options premium model). It reads
whatever those pipelines have most recently produced -- it does not hardcode
ticker counts, feature lists, hyperparameters, or backtest numbers anywhere.
If you retrain with more data, add a feature, or change a hyperparameter in
features.py / options_common.py, this dashboard reflects it the next time
you refresh the page (Streamlit's cache is keyed on each file's mtime).

See README.md in this folder for setup, what each button does, and known
limitations (a couple of options-model features are reconstructed
approximations -- clearly flagged both there and in the Options tab).
"""
from __future__ import annotations

import sys
import time
from pathlib import Path

import pandas as pd
import streamlit as st

sys.path.insert(0, str(Path(__file__).resolve().parent))
from lib import (paths, stock_model as sm, options_model as om, data_refresh as dr,
                 pit_model as pm, blend_model as bm)

st.set_page_config(page_title="pipe_dream — Model Dashboard", layout="wide", page_icon="📈")

MISSING_DEPS = []
for _mod in ["xgboost", "torch", "sklearn", "pyarrow"]:
    try:
        __import__(_mod)
    except ImportError:
        MISSING_DEPS.append(_mod)

if MISSING_DEPS:
    st.error(
        f"Missing Python packages: {', '.join(MISSING_DEPS)}. Install them in the same "
        f"environment you run this app with, e.g.:\n\n`pip install {' '.join(MISSING_DEPS)}`"
    )
    st.stop()


# --------------------------------------------------------------------------
# small formatting helpers
# --------------------------------------------------------------------------

def pct(x, digits=2):
    if x is None or pd.isna(x):
        return "—"
    return f"{x * 100:.{digits}f}%"


def money(x):
    if x is None or pd.isna(x):
        return "—"
    return f"${x:,.2f}"


def age_str(mtime_ts):
    if mtime_ts is None:
        return "never"
    delta = time.time() - mtime_ts
    if delta < 3600:
        return f"{int(delta / 60)} min ago"
    if delta < 86400:
        return f"{delta / 3600:.1f} hr ago"
    return f"{delta / 86400:.1f} days ago"


def file_mtime(p: Path):
    try:
        return p.stat().st_mtime
    except FileNotFoundError:
        return None


# --------------------------------------------------------------------------
# sidebar
# --------------------------------------------------------------------------

with st.sidebar:
    st.title("pipe_dream")
    st.caption("Buy/no-buy + options premium models — live dashboard")

    feat = sm.get_features()
    if feat is not None:
        usumm = sm.universe_summary()
        st.metric("Stock universe", f"{usumm['feature_ticker_count']:,} tickers")
        st.caption(f"{usumm['date_min'].date()} → {usumm['date_max'].date()}  ·  "
                   f"{usumm['forward_window_days']}-day forward horizon")
    else:
        st.warning("No features.parquet yet — see the Data & Updates tab.")

    ousumm = om.universe_summary()
    if ousumm["chain"]:
        st.metric("Options universe", f"{ousumm['chain']['n_tickers']:,} tickers")
        st.caption(f"{ousumm['chain']['date_min'].date()} → {ousumm['chain']['date_max'].date()} (options history)")

    st.divider()
    st.caption("Data freshness")
    for label, p in [
        ("Stock prices", paths.STOCK_DATA_DIR),
        ("Stock features", paths.FEATURES_PARQUET),
        ("Options history", paths.OPTION_CHAIN_SP500),
        ("Live options snapshot", paths.LIVE_CALLS_CHAIN),
    ]:
        if label == "Stock prices":
            csvs = list(p.glob("*.csv")) if p.exists() else []
            mt = max((f.stat().st_mtime for f in csvs), default=None)
        else:
            mt = file_mtime(p)
        st.caption(f"{label}: {age_str(mt)}")

    st.divider()
    if st.button("🔄 Clear cache & reload", use_container_width=True):
        st.cache_data.clear()
        st.cache_resource.clear()
        st.rerun()


# --------------------------------------------------------------------------
# Overview
# --------------------------------------------------------------------------

def render_overview():
    st.header("Overview")
    col1, col2 = st.columns(2)

    with col1:
        st.subheader("📈 Stock buy/no-buy")
        blend_df, blend_meta = bm.get_signal()
        if blend_meta is None:
            st.info("No current_signal_blend.csv yet — see the Today's Picks tab.")
        else:
            c1, c2, c3 = st.columns(3)
            c1.metric("Eligible universe (cap2000)", f"{blend_meta['n_eligible_universe']:,}")
            c2.metric("As of", blend_meta["as_of_date"])
            c3.metric("Horizon", "40d")
            st.caption(
                "**Composite + q75 blend** (rank-averaged 50/50, decile-within-vol-"
                "quintile, inverse-vol weighted) — today's picks. Promoted 2026-09-19; "
                "single-grid backtest, still negative vs SPY in absolute terms on the "
                "2020-2026 hold-out. See the Today's Picks tab before acting on these."
            )
            show = blend_df[["ticker", "sector", "weight", "close"]].head(10).copy()
            show["weight"] = show["weight"].map(lambda v: f"{v:.2%}")
            st.dataframe(show, hide_index=True, use_container_width=True)

    with col2:
        st.subheader("📊 Options premium (calls)")
        if not paths.OPTIONS_CALLS_TRAINING.exists():
            st.info("No options training data yet.")
        else:
            live_meta = om.live_chain_meta()
            ousumm2 = om.universe_summary()
            c1, c2, c3 = st.columns(3)
            if ousumm2["calls_training"]:
                c1.metric("Training rows", f"{ousumm2['calls_training']['n_rows']:,}")
            if live_meta:
                c2.metric("Live snapshot", live_meta["entry_date"])
                c3.metric("Expiration", live_meta["expiration_date"])
            st.caption("Puts are not production-ready yet (see Options tab → Model Weights) — calls only.")
            bt = om.get_backtest_tables()
            if "calls_backtest" in bt:
                df = bt["calls_backtest"]
                win_rate = df["beat_spy"].mean()
                st.caption(f"Backtest: beat SPY in {int(df['beat_spy'].sum())}/{len(df)} timepoints "
                           f"({pct(win_rate)}), avg model return {pct(df['model_return_pct'].mean())} "
                           f"vs SPY {pct(df['spy_return_pct'].mean())}.")

    st.divider()
    st.caption(
        "Not investment advice. The stock signal is the point-in-time "
        "(survivorship-bias-corrected) price + fundamentals model, held to a "
        "40-day horizon with no stop-loss; the 15% stop price is per-name risk "
        "guidance, not part of the backtested configuration. The options signal "
        "is a Tweedie GLM on premium. Neither has a demonstrated edge: see the "
        "Stock → Today's Picks and Backtest & History tabs for what was actually "
        "measured, including the noise band that any result here has to be read "
        "against."
    )


# --------------------------------------------------------------------------
# Stock model tabs
#
# Round 18 (2026-09-16). This tab shows TWO signals side by side at Gabe's
# request -- the deployed q75 model and the xrank candidate that failed the
# hold-out -- plus SPY and USMV as reference lines. The pre-Round-18
# "Secondary Models (XGBoost / LSTM)" tab and every cross-check expander that
# pointed at it have been removed: those models were trained on the old,
# survivorship-contaminated universe that Round 11 replaced, so showing them
# beside point-in-time picks invited a comparison that was not valid in either
# direction.
# --------------------------------------------------------------------------


def render_stock_pit():
    """Today's Picks -- PRIMARY signal as of 2026-09-19: the composite+q75
    blend (final/src/current_signal_blend.py). Promoted over the prior
    q75/xrank display per Gabe's explicit instruction; the caveats below are
    not decorative -- read current_signal_blend.py's module docstring and
    final/models/2026-09-19-factor-composite-reset.md for the full context."""
    st.warning(
        "**Read before acting on these picks.** The blend's backtest is a "
        "SINGLE-GRID result (q75's score cache has only one cadence -- this "
        "project's usual 40-offset average isn't available for it), and it "
        "still shows NEGATIVE excess vs SPY in absolute terms on the "
        "2020-2026 hold-out (-0.36%, the least-bad of three constructions "
        "tested, not a winner). It was promoted anyway, on explicit "
        "instruction, over that recommendation. Full detail: "
        "`final/models/2026-09-19-factor-composite-reset.md`."
    )

    df, meta = bm.get_signal()
    if st.button("🔁 Refresh the blend's picks", key="retrain_blend"):
        dr.run_step_sequence("stock_retrain_blend", bm.retrain_commands(),
                             ["down-cap universe", "quality factors", "build panel", "score blend"],
                             cwd=paths.SRC_DIR)
        st.rerun()

    state = dr.refresh_status("stock_retrain_blend")
    if state.status == "running":
        st.info("Refreshing... this page keeps updating.")
        with st.expander("Log", expanded=True):
            st.code(dr.tail_log("stock_retrain_blend"))
        time.sleep(2)
        st.rerun()
    elif state.status in ("done", "failed"):
        (st.success if state.status == "done" else st.error)(
            f"Last refresh {state.status} at {state.finished_at}.")
        with st.expander("Log"):
            st.code(dr.tail_log("stock_retrain_blend"))

    if df is None:
        st.info("No current_signal_blend.csv yet — hit Refresh above. "
               "(Needs features_with_fundamentals_sharadar_pit.parquet and "
               "out/models/xgb_pit_augmented_model.json to already exist -- "
               "run the base Retrain in Data & Updates first if this is a "
               "fresh checkout.)")
        return

    c1, c2, c3 = st.columns(3)
    c1.metric("As of", meta["as_of_date"])
    c2.metric("Positions", meta["n_picks"])
    c3.metric("Eligible universe (cap2000 tier)", f"{meta['n_eligible_universe']:,}")
    st.write("**Construction:** " + meta["construction"])
    with st.expander("The 9 composite factors, signs, and the q75/composite blend weight"):
        st.json({"q75_weight": meta["q75_weight"], "composite_weight": meta["composite_weight"],
                "composite_factor_signs": meta["factors"]})
    with st.expander("Backtest summary (single grid — see the warning above)"):
        st.json(meta["backtest_summary"])
    st.dataframe(
        df[["ticker", "sector", "close", "market_cap", "volatility_60",
            "q75_score", "composite_score", "blend_score", "weight"]]
          .style.format({"close": "${:.2f}", "market_cap": "${:,.0f}",
                          "volatility_60": "{:.2%}", "q75_score": "{:.3f}",
                          "composite_score": "{:.3f}", "blend_score": "{:.3f}",
                          "weight": "{:.2%}"}),
        use_container_width=True, height=480,
    )
    st.caption(meta["note"])


def render_stock_query():
    st.caption(
        "Looks a ticker up against today's full scanned universe "
        "(`current_signal_blend_full.csv`) — instant, no rescoring. Every "
        "ticker gets one of four answers: **PICK**, **ELIGIBLE_NOT_PICKED** "
        "(scored, with its exact blend score and rank within its volatility "
        "quintile), **ELIGIBLE_NOT_SCORED** (in the universe but missing a "
        "score), or **INELIGIBLE_TODAY** (fails the point-in-time cap2000 "
        "screen — not considered at all)."
    )
    raw = st.text_input("Ticker(s), comma or space separated", placeholder="AAPL, MSFT, NVDA")
    if st.button("Look up", key="stock_query_btn") and raw.strip():
        tickers = [t for t in raw.replace(",", " ").split() if t]
        with st.spinner("Looking up..."):
            result = bm.query_tickers(tickers)

        rows = []
        for t, r in result.items():
            row = {"ticker": t, **r}
            rows.append(row)
        df = pd.DataFrame(rows)
        st.dataframe(df, hide_index=True, use_container_width=True)

        if feat is not None:
            for t in tickers:
                hist = sm.ticker_history(t, feat)
                if hist is not None:
                    with st.expander(f"{t} — price & momentum history"):
                        st.line_chart(hist.set_index("date")[["close"]])
                        st.line_chart(hist.set_index("date")[["momentum_20", "momentum_60", "momentum_120"]])


def render_stock_universe():
    """NOTE ON WHAT THIS TAB DESCRIBES. The counts below come from
    features.parquet -- the plain current-universe price panel. That is NOT the
    universe either signal picks from. Both models are restricted, on every
    date, to that date's point-in-time universe
    (data/sharadar/pit_universe.parquet), which includes companies that have
    since been delisted, acquired or gone bankrupt and excludes ones that had
    not yet qualified. The PIT count is the metric at the top of this block;
    everything under it is the price panel."""
    uc = pm.universe_counts()
    if uc is not None:
        p1, p2 = st.columns(2)
        p1.metric("Point-in-time universe (what the models pick from)",
                  f"{uc['total_pit_tickers']:,}")
        if uc.get("current_universe_tickers") is not None:
            p2.metric("of which currently listed", f"{uc['current_universe_tickers']:,}",
                      help=f"The remaining "
                           f"{uc['total_pit_tickers'] - uc['current_universe_tickers']:,} "
                           f"are point-in-time gap tickers: delisted, acquired or "
                           f"bankrupt names that were genuinely investable at the "
                           f"time. Round 11 found the old pool was missing a third "
                           f"of the eligible 2008 universe, 89% of it dead, which "
                           f"is why every performance number predating 2026-09-09 "
                           f"was invalidated.")
        st.divider()
    st.caption("Below: the plain current-universe price panel (features.parquet), "
               "used for the sidebar, ticker history charts and this tab only.")
    u = sm.universe_summary()
    c1, c2, c3, c4 = st.columns(4)
    c1.metric("Tickers (price CSVs)", f"{u['csv_ticker_count']:,}" if u["csv_ticker_count"] else "—")
    c2.metric("Tickers (in features)", f"{u['feature_ticker_count']:,}" if u["feature_ticker_count"] else "—")
    c3.metric("History start", str(u["date_min"].date()) if u["date_min"] is not None else "—")
    c4.metric("History end", str(u["date_max"].date()) if u["date_max"] is not None else "—")
    if u["csv_ticker_count"] and u["feature_ticker_count"] and u["csv_ticker_count"] != u["feature_ticker_count"] + 1:
        st.caption("Note: feature-panel ticker count excludes SPY (used only as the relative-strength "
                   "benchmark), so it's normally exactly one less than the CSV count.")
    st.write(f"**Forward-return horizon:** {u['forward_window_days']} trading days")
    st.write(f"**Feature columns ({len(u['feature_cols'])}):**")
    st.code(", ".join(u["feature_cols"]))
    if u["total_rows"]:
        st.write(f"**Total feature rows:** {u['total_rows']:,}  ·  **Rows with a resolved label:** "
                 f"{u['labeled_rows']:,} ({u['labeled_rows'] / u['total_rows']:.1%})")
    st.caption("Universe construction methodology (market cap > $2B, US-incorporated, price > $10, "
               "dual-class dedup, etc.) is documented in universe/2026-08-27-expanded-universe-methodology.md.")


# --------------------------------------------------------------------------
# Options model tabs
# --------------------------------------------------------------------------

def render_options_today():
    if not paths.OPTIONS_CALLS_TRAINING.exists():
        st.warning("No options training data found.")
        return
    if feat is None:
        st.warning("Options scoring needs the stock model's features.parquet too — refresh stock data first.")
        return

    live_meta = om.live_chain_meta()
    if live_meta is None:
        st.warning("No live option-chain snapshot found. Use \"Refresh live options chain\" on the "
                   "Data & Updates tab.")
        return

    age_days = (pd.Timestamp.now() - pd.Timestamp(live_meta["entry_date"])).days
    if age_days > 3:
        st.warning(f"This snapshot is from {live_meta['entry_date']} ({age_days} days old) — refresh it "
                   f"on the Data & Updates tab for a same-day read.")
    st.caption(f"Snapshot: entry {live_meta['entry_date']}, expiring {live_meta['expiration_date']} "
               f"({live_meta['n_contracts']:,} contracts across {live_meta['n_tickers']} tickers)")

    with st.spinner("Fitting model and scoring the live chain..."):
        result = om.get_live_scored(feat)
    if result is None:
        st.error("Couldn't score the live chain — check that features.parquet, garch_volatility.parquet, "
                 "and the live snapshot files all cover overlapping dates.")
        return
    ranked, picks, cash_left, _ = result

    st.subheader(f"Kelly-sized picks (${om_common_total():,.0f} notional)")
    if len(picks):
        show = picks[["rank", "act_symbol", "strike", "entry_premium", "days_to_expiration",
                      "pred_pct_return", "decile", "kelly_frac", "dollar_alloc"]].copy()
        show["pred_pct_return"] = show["pred_pct_return"].map(pct)
        show["kelly_frac"] = show["kelly_frac"].map(pct)
        show["dollar_alloc"] = show["dollar_alloc"].map(money)
        st.dataframe(show, hide_index=True, use_container_width=True)
    else:
        st.info("No positive-edge deciles today — the calibrated sizer says hold cash.")
    st.caption(f"Cash held: {money(cash_left)} ({cash_left / om_common_total():.0%})")

    st.subheader(f"Full ranking (top 20 of {len(ranked)} tickers, by raw predicted edge)")
    show2 = ranked.head(20)[["rank", "act_symbol", "strike", "underlying_close_entry", "entry_premium",
                              "days_to_expiration", "pred_pct_return", "decile"]].copy()
    show2["pred_pct_return"] = show2["pred_pct_return"].map(pct)
    st.dataframe(show2, hide_index=True, use_container_width=True)
    st.caption(
        "Reminder from this model's own diagnostics: predicted-edge ranking within the top deciles is "
        "noisy — the model's cleanest signal is separating 'will pay out something' from 'won't,' not "
        "fine-grained best-vs-worst ranking. That's why sizing uses the calibrated decile stats, not the "
        "raw predicted %."
    )


def om_common_total():
    from lib import options_common as oc
    return oc.TOTAL_CAPITAL_DEFAULT


def render_options_query():
    if feat is None or not paths.OPTIONS_CALLS_TRAINING.exists():
        st.warning("Needs both the stock features and the options training data.")
        return
    ticker = st.text_input("Ticker", placeholder="AAPL", key="options_ticker")
    if st.button("Look up", key="options_query_btn") and ticker.strip():
        with st.spinner("Scoring..."):
            df = om.query_ticker_options(ticker, feat)
        if df is None or df.empty:
            st.info(f"No scoreable live contracts found for {ticker.upper()} — either it's not in the "
                    f"live snapshot, or it's missing a required feature (GARCH forecast, HV/IV, etc.).")
        else:
            show = df[["strike", "entry_premium", "days_to_expiration", "entry_iv",
                       "pred_pct_return", "decile", "kelly_frac"]].copy()
            show["pred_pct_return"] = show["pred_pct_return"].map(pct)
            show["kelly_frac"] = show["kelly_frac"].map(pct)
            st.dataframe(show, hide_index=True, use_container_width=True)


def render_options_weights():
    st.subheader("Calls model: Tweedie GLM")
    bundle = om.get_model_and_calibration()
    if bundle is None:
        st.info("No options training data yet.")
        return
    from lib import options_common as oc
    coefs = pd.Series(bundle["model"].coef_, index=oc.FEATURES).sort_values(key=abs, ascending=False)
    st.caption(f"power={oc.TWEEDIE_POWER}, alpha={oc.TWEEDIE_ALPHA} (round-2 winning hyperparameters, "
               f"round2_results.json). Coefficients are on the standardized-feature, log-link scale, so "
               f"sign and relative magnitude are meaningful, raw units are not.")
    st.bar_chart(coefs)
    st.dataframe(coefs.rename("coefficient").reset_index().rename(columns={"index": "feature"}),
                 hide_index=True, use_container_width=True)

    st.divider()
    st.subheader("Model bake-off (design-doc record)")
    st.caption("Round 1 (10k-row quick read, calls only) — from models/options-premium-model-design.md:")
    round1 = pd.DataFrame([
        {"model": "benchmark: zero edge", "MAE": 1.65, "Tweedie deviance": 5.11, "dir. accuracy": 0.696},
        {"model": "benchmark: train mean", "MAE": 1.80, "Tweedie deviance": 4.92, "dir. accuracy": 0.304},
        {"model": "Linear regression", "MAE": 2.16, "Tweedie deviance": 380.11, "dir. accuracy": 0.466},
        {"model": "GAM (hurdle)", "MAE": 1.50, "Tweedie deviance": 4.53, "dir. accuracy": 0.686},
        {"model": "Quasi-likelihood (Tweedie GLM)", "MAE": 1.61, "Tweedie deviance": 4.41, "dir. accuracy": 0.649},
        {"model": "Bayesian (hurdle, ADVI)", "MAE": 9.11, "Tweedie deviance": 6.20, "dir. accuracy": 0.417},
    ])
    st.dataframe(round1, hide_index=True, use_container_width=True)

    r2 = bt = om.get_backtest_tables().get("round2")
    if r2:
        st.caption("Round 2 (full ~580k-row dataset, purged walk-forward CV, held-out from 2026-04-01):")
        for kind in ("calls", "puts"):
            if kind in r2:
                st.write(f"**{kind.capitalize()}** — held-out n={r2[kind]['holdout_n']:,}")
                comp = pd.DataFrame([
                    {"model": "benchmark (zero edge)", "MAE": r2[kind]["bench_hold_mae"], "Tweedie deviance": r2[kind]["bench_hold_dev"]},
                    {"model": f"Tweedie GLM (power={r2[kind]['tw_best'][0]}, alpha={r2[kind]['tw_best'][1]})",
                     "MAE": r2[kind]["tw_hold_mae"], "Tweedie deviance": r2[kind]["tw_hold_dev"]},
                    {"model": f"GAM hurdle (lam={r2[kind]['gam_best'][0]}, n_splines={r2[kind]['gam_best'][1]})",
                     "MAE": r2[kind]["gam_hold_mae"], "Tweedie deviance": r2[kind]["gam_hold_dev"]},
                ])
                st.dataframe(comp, hide_index=True, use_container_width=True)
        st.warning(
            "Puts never beat the benchmark on any metric in round 2, and haven't been rerun since a "
            "data-quality fix removed 8.36% of contaminated puts rows (vs. 0.43% for calls) — see "
            "models/options-premium-model-design.md. Treat puts as an open research problem, not a "
            "usable signal; this dashboard doesn't offer puts picks for that reason."
        )


def render_options_backtest():
    bt = om.get_backtest_tables()
    if "calls_backtest" in bt:
        st.subheader("Calls backtest (Tweedie GLM, top-5 equal-weight)")
        df = bt["calls_backtest"]
        st.dataframe(df, hide_index=True, use_container_width=True)
        c1, c2, c3 = st.columns(3)
        c1.metric("Win rate vs SPY", f"{int(df['beat_spy'].sum())}/{len(df)}")
        c2.metric("Avg model return", pct(df["model_return_pct"].mean()))
        c3.metric("Avg SPY return", pct(df["spy_return_pct"].mean()))

    if "old_vs_new" in bt:
        st.divider()
        st.subheader("Sizing comparison: equal-weight top-5 (OLD) vs. calibrated-decile Kelly (NEW)")
        st.dataframe(bt["old_vs_new"], hide_index=True, use_container_width=True)
        st.caption("NEW trades some average return for much lower volatility by sizing down when the "
                   "predicted-edge decile's historical calibration is weak or negative — see the 2026 row, "
                   "where OLD lost -50.5% and NEW (mostly in cash) lost only -10.9%.")

    if "decile_table" in bt:
        st.divider()
        st.subheader("Decile calibration diagnostic")
        dt = bt["decile_table"]
        st.bar_chart(dt.set_index("decile")[["p_win"]])
        st.dataframe(dt, hide_index=True, use_container_width=True)
        st.caption("Win rate (p_win) is almost perfectly monotonic by decile — the model's cleanest signal "
                   "is 'will this pay out at all,' i.e. a filter. Mean realized return is NOT monotonic past "
                   "decile 2 — decile 5 beats decile 9. That's why sizing (Model Weights tab) uses the "
                   "calibrated decile stats rather than the model's raw predicted magnitude.")


def render_options_universe():
    u = om.universe_summary()
    for label, key in [("Option chain (raw)", "chain"), ("Volatility history", "volhist"),
                        ("Calls training table", "calls_training"), ("Puts training table", "puts_training")]:
        st.write(f"**{label}**")
        d = u[key]
        if d is None:
            st.caption("not found")
        else:
            c1, c2, c3 = st.columns(3)
            c1.metric("Tickers", f"{d['n_tickers']:,}")
            c2.metric("Rows", f"{d['n_rows']:,}")
            c3.metric("Date range", f"{d['date_min'].date()} → {d['date_max'].date()}")
    st.caption(
        "Options universe is the S&P 500 (497 tickers) — deliberately not expanded to the 1,620-ticker "
        "stock-model universe (see models/options-premium-model-design.md, Universe section)."
    )
    st.caption(
        "Known reconstruction note: `cumulative_return` and `volume_20`, two of the 18 model features, "
        "aren't produced by the current final/src/features.py and are reconstructed directly from price "
        "history for live scoring (see app/lib/options_common.py docstring) — a best-effort match to the "
        "original training data's definitions, not a confirmed-identical reimplementation."
    )


# --------------------------------------------------------------------------
# Data & Updates
# --------------------------------------------------------------------------

def render_data_updates():
    st.subheader("Dataset freshness")
    rows = []
    for label, p, is_dir in [
        ("Stock price CSVs", paths.STOCK_DATA_DIR, True),
        ("Stock features.parquet", paths.FEATURES_PARQUET, False),
        ("PIT universe (pit_universe.parquet)", paths.PIT_UNIVERSE_PARQUET, False),
        ("PIT panel (features_with_fundamentals_sharadar_pit.parquet)", pm.FUND_PIT_PARQUET, False),
        ("Deployed checkpoint (q75)", pm.model_path(pm.PRIMARY), False),
        ("Candidate checkpoint (xrank)", pm.model_path(pm.CANDIDATE), False),
        ("Deployed picks (current_signal_pit.csv)", pm.signal_csv(pm.PRIMARY), False),
        ("Candidate picks (current_signal_pit_xrank.csv)", pm.signal_csv(pm.CANDIDATE), False),
        ("Benchmark comparison (app_model_comparison.json)", pm.COMPARISON_JSON, False),
        ("Options raw (option_chain)", paths.OPTION_CHAIN_SP500, False),
        ("Options raw (volatility_history)", paths.VOLATILITY_HISTORY_SP500, False),
        ("Options calls training table", paths.OPTIONS_CALLS_TRAINING, False),
        ("GARCH volatility panel", paths.GARCH_PARQUET, False),
        ("Live options chain snapshot", paths.LIVE_CALLS_CHAIN, False),
        ("Decile calibration table", paths.OPTIONS_SRC_DIR / "decile_calibration_table.csv", False),
    ]:
        if is_dir:
            files = list(p.glob("*.csv")) if p.exists() else []
            mt = max((f.stat().st_mtime for f in files), default=None)
            note = f"{len(files)} files"
        else:
            mt = file_mtime(p)
            note = "" if mt else "missing"
        rows.append({"dataset": label, "last updated": age_str(mt), "note": note})
    st.dataframe(pd.DataFrame(rows), hide_index=True, use_container_width=True)

    st.divider()
    st.subheader("0. One-click: refresh everything")
    st.caption(
        "Runs the full pipeline end to end so you don't have to babysit each step below. \"Update all "
        "training data\" tops up the last ~40 days of prices (full universe + SPY) instead of "
        "re-pulling full history, and runs an options history update — all from your own network, so "
        "this should finish in a few minutes even across the full universe. \"Retrain all models\" "
        "rebuilds every feature panel (including the point-in-time price/fundamentals panels), retrains "
        "q75 (whose checkpoint the primary blend scores off of), rebuilds the SPY/USMV comparison "
        "chart, and rescoring the blend itself — so this one button is what actually refreshes "
        "Today's Picks end to end. The options Tweedie GLM "
        "needs no separate retrain step — it refits automatically next time it's used, off whatever "
        "training data is newest on disk. Run the data update first, then retrain, if you want a fully "
        "current read in one sitting. Note: neither button refreshes scripts/fundamentals_raw/ (SEC "
        "EDGAR) or scripts/fundamentals_raw_delisted/ (Sharadar) — those are separate, much less "
        "frequent pulls, see AGENTS.md."
    )
    c1, c2 = st.columns(2)
    with c1:
        if st.button("📥 Update ALL training data", key="btn_update_all_data", use_container_width=True):
            py = sys.executable
            # DoltHub (below) is best-effort and goes LAST: it needs `dolt`
            # installed and configured (`dolt config --global user.name/
            # user.email`, one-time) plus network access to dolthub.com, and
            # historically has been flakier than the yfinance pulls. Wrapped
            # in `|| echo ...` so a failure here logs clearly but doesn't
            # abort the pipeline (run_step_sequence's wrapper script uses
            # `set -e`) or block the live options chain pull, which is more
            # important for day-to-day use and used to run after it.
            # No double quotes, backticks, or $ in this message -- the whole
            # string gets wrapped in an outer pair of double quotes below
            # (run_step_sequence's naive per-argv quoting), and bash treats
            # backticks/$ as live substitution even inside double quotes.
            dolt_script = str(paths.SCRIPTS_DIR / "update_options_history.py")
            dolt_inner = (
                f"'{py}' '{dolt_script}' || echo "
                "'DoltHub history update failed or was skipped -- see the dolt error "
                "above for the exact fix (usually a one-time dolt config --global "
                "--add user.name and user.email). This step is best-effort and does "
                "not block the rest of the refresh.'"
            )
            cmds = [
                [py, str(paths.SCRIPTS_DIR / "local_data_pull.py"), "--refresh-recent"],
                [py, str(paths.SCRIPTS_DIR / "local_data_pull.py"), "--refresh-recent",
                 "^VIX", "GLD", "TLT", "HYG", "^TNX"],
                [py, str(paths.SCRIPTS_DIR / "pull_live_options_chain.py")],
                ["bash", "-c", dolt_inner],
            ]
            labels = [
                "Pull stock price data — full universe + SPY (yfinance)",
                "Pull macro/regime data — VIX/GLD/TLT/HYG/TNX (yfinance, kept for regime_signals_beta.py "
                "experimentation; not used by the current primary model)",
                "Pull live options chain snapshot (yfinance)",
                "Pull options history update (DoltHub, best-effort)",
            ]
            dr.run_step_sequence("update_all_data", cmds, labels)
            st.rerun()
        _job_status_block("update_all_data")
    with c2:
        if st.button("🔁 Retrain ALL models", key="btn_retrain_all_models", use_container_width=True):
            py = sys.executable
            # Round 18: this is now exactly pm.retrain_commands(), with the
            # plain features.parquet rebuild kept in front of it because the
            # sidebar and the Universe tab still read that panel. The old
            # current_signal.py / lstm_current_signal.py steps were dropped
            # with the models they fed -- they trained on the pre-Round-11
            # universe, so rerunning them only refreshed numbers nothing on
            # this page should be compared against.
            #
            # 2026-09-22: bm.retrain_commands() appended so this button
            # actually refreshes what's now the primary signal. Before this,
            # a full retrain left current_signal_blend.csv stale -- q75's
            # checkpoint and the fundamentals panel would update, but
            # Today's Picks would keep showing whatever the last standalone
            # blend refresh produced. Must run AFTER pm.retrain_commands():
            # the blend scores q75's freshly-retrained checkpoint and reads
            # the freshly-rebuilt fundamentals panel, not the other way round.
            cmds = ([[py, str(paths.SRC_DIR / "features.py")]] + pm.retrain_commands()
                    + bm.retrain_commands())
            labels = (["Rebuild price features.parquet (sidebar + Universe tab)"]
                     + pm.PIT_STEP_LABELS
                     + ["Down-cap universe (blend)", "Quality factors (blend)",
                        "Composite panel (blend)", "Score today's blend"])
            dr.run_step_sequence("retrain_all_models", cmds, labels, cwd=paths.SRC_DIR)
            st.rerun()
        _job_status_block("retrain_all_models")

    st.divider()
    st.subheader("1. Refresh stock price data + retrain both signals")
    st.caption(
        "Runs local_data_pull.py (yfinance, your own network) for the full universe, then the full "
        "point-in-time rebuild and both signal retrains. The price pull only tops up the last ~40 days "
        "for tickers you already have data for (--refresh-recent), so it's much quicker than a "
        "first-time pull across ~1,600 tickers. This is the same sequence as \"Retrain ALL models\" "
        "above with a price pull in front of it."
    )
    if st.button("Run full stock refresh", key="btn_stock_refresh"):
        py = sys.executable
        cmds = ([[py, str(paths.SCRIPTS_DIR / "local_data_pull.py"), "--refresh-recent"]]
                + pm.retrain_commands())
        dr.run_step_sequence("stock_full_refresh", cmds,
                             ["Pull price data (yfinance)"] + pm.PIT_STEP_LABELS)
        st.rerun()
    _job_status_block("stock_full_refresh")

    st.divider()
    st.subheader("2. Refresh today's live options chain")
    st.caption(
        "Pulls a fresh live option chain via yfinance (your own network) for the nearest ~30-day monthly "
        "expiration, for every ticker with local price history. Needed before scoring today's options "
        "picks against a same-day snapshot."
    )
    if st.button("Pull live options chain", key="btn_options_live"):
        py = sys.executable
        dr.run_step_sequence("options_live_refresh",
                              [[py, str(paths.SCRIPTS_DIR / "pull_live_options_chain.py")]],
                              ["Pull live option chain (yfinance)"])
        st.rerun()
    _job_status_block("options_live_refresh")

    st.divider()
    st.subheader("3. Update options historical data (DoltHub)")
    st.caption(
        "Best-effort: requires the `dolt` CLI and network access to dolthub.com from this machine "
        "(run directly, not through any sandboxed shell). Pulls new rows since the last update into "
        "option_chain_sp500.parquet / volatility_history_sp500.parquet. Does NOT rebuild the engineered "
        "training tables or the GARCH panel — those need a separate rebuild pass (see README)."
    )
    if st.button("Pull options history update", key="btn_options_history"):
        py = sys.executable
        dr.run_step_sequence("options_history_refresh",
                              [[py, str(paths.SCRIPTS_DIR / "update_options_history.py")]],
                              ["dolt pull + incremental export"])
        st.rerun()
    _job_status_block("options_history_refresh")


def _job_status_block(job_name: str):
    state = dr.refresh_status(job_name)
    if state.status == "idle":
        return
    if state.status == "running":
        st.info(f"Running (started {state.started_at})...")
        with st.expander("Log", expanded=True):
            st.code(dr.tail_log(job_name))
        time.sleep(2)
        st.rerun()
    else:
        (st.success if state.status == "done" else st.error)(f"{state.status} at {state.finished_at}")
        with st.expander("Log"):
            st.code(dr.tail_log(job_name))


# --------------------------------------------------------------------------
# main
# --------------------------------------------------------------------------

tab_overview, tab_stock, tab_options, tab_data = st.tabs(
    ["🏠 Overview", "📈 Stock Buy/No-Buy", "📊 Options Premium", "🔄 Data & Updates"]
)

with tab_overview:
    render_overview()

with tab_stock:
    # Round 18: the "Secondary Models (XGBoost / LSTM)" tab was removed. Those
    # models were trained on the pre-Round-11 universe, which was missing a
    # third of the eligible early names -- 89% of them dead -- so every number
    # they produced is measured on data now known to be defective. Keeping them
    # beside point-in-time picks invited a comparison that was not valid in
    # either direction. The two models shown now differ ONLY in training label.
    t1, t2, t3 = st.tabs(["Today's Picks", "Query a Ticker", "Universe"])
    with t1:
        render_stock_pit()
    with t2:
        render_stock_query()
    with t3:
        render_stock_universe()

with tab_options:
    t1, t2, t3, t4, t5 = st.tabs(["Today's Picks", "Query a Ticker", "Model Weights", "Backtest & History", "Universe"])
    with t1:
        render_options_today()
    with t2:
        render_options_query()
    with t3:
        render_options_weights()
    with t4:
        render_options_backtest()
    with t5:
        render_options_universe()

with tab_data:
    render_data_updates()
