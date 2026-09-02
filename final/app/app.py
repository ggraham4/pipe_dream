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
from lib import paths, stock_model as sm, options_model as om, data_refresh as dr, pit_model as pm

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
        if feat is None:
            st.info("No data yet.")
        else:
            pit_df, pit_meta = pm.get_signal()
            uc = pm.universe_counts()
            c1, c2, c3 = st.columns(3)
            if uc is not None:
                c1.metric("PIT universe", f"{uc['total_pit_tickers']:,}",
                          help=f"{uc['current_universe_tickers']:,} current-universe + "
                               f"{uc['total_pit_tickers'] - uc['current_universe_tickers']:,} valid "
                               f"point-in-time gap tickers (delisted/acquired/bankrupt), if the current "
                               f"count could be resolved."
                          if uc.get("current_universe_tickers") is not None else None)
            else:
                c1.metric("Universe (price data)", f"{feat['ticker'].nunique():,}",
                          help="No PIT panel on disk yet — this is the plain non-PIT current-universe "
                               "count, not the primary model's own universe.")
            if pit_meta:
                c2.metric("As of", pit_meta["as_of_date"])
                c3.metric("Stop-loss", pct(pit_meta.get("stop_loss_pct")))
            else:
                c3.metric("Forward horizon", f"{sm.universe_summary()['forward_window_days']}d")
            if pit_df is not None:
                st.caption("Augmented + stop-loss (PIT, primary signal) — today's picks")
                show = pit_df[["ticker", "allocation_pct", "close", "suggested_stop_loss_price"]].copy()
                show["allocation_pct"] = show["allocation_pct"].map(lambda v: f"{v:.2f}%")
                st.dataframe(show, hide_index=True, use_container_width=True)
            else:
                st.info("No current_signal_pit.csv yet — see the Today's Picks tab.")

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
        "Not investment advice. The stock signal above is the point-in-time (survivorship-bias-corrected) "
        "augmented model with an empirically-optimized 15% stop-loss (see "
        "backtest/survivorship-bias-correction-results.md, Round 7/8); the options signal is a Tweedie GLM "
        "on premium. No transaction costs, and backtest sample-size caveats — see each model's Backtest "
        "tab for the full writeup."
    )


# --------------------------------------------------------------------------
# Stock model tabs
# --------------------------------------------------------------------------

def render_stock_secondary():
    """The non-PIT price-only XGBoost and LSTM signals, kept here for
    transparency/comparison. Neither feeds into the primary Today's Picks
    signal (the PIT augmented+stop-loss model, lib/pit_model.py) -- these
    predate the survivorship-bias-correction work and are shown here as a
    reference point, not a recommendation."""
    if feat is None:
        st.warning("No features.parquet — run a data refresh first (Data & Updates tab).")
        return

    st.caption(
        "Secondary/reference models, not survivorship-bias-corrected (no point-in-time mid-cap+ floor, no "
        "delisted-company coverage) and not part of the primary **Today's Picks** signal. Kept here for "
        "transparency and cross-checking, not as a recommendation."
    )

    xgb_top, xgb_meta = sm.get_current_top("xgb")
    lstm_top, lstm_meta = sm.get_current_top("lstm")

    xgb_status = sm.cached_model_status("xgb")
    lstm_status = sm.cached_model_status("lstm")
    if xgb_status.stale or lstm_status.stale:
        st.warning(
            f"The saved models were trained as of {xgb_status.as_of_date}, but the latest data on disk "
            f"goes through {xgb_status.latest_data_date}. Retrain to pick up the newer data."
        )

    if st.button("🔁 Retrain both models on latest data", key="retrain_stock"):
        dr.run_step_sequence("stock_retrain", sm.retrain_commands(),
                              ["Rebuild features.parquet", "Retrain XGBoost", "Retrain LSTM"],
                              cwd=paths.SRC_DIR)
        st.rerun()

    state = dr.refresh_status("stock_retrain")
    if state.status == "running":
        st.info(f"Retraining in progress (started {state.started_at})... this can take 1-2 minutes, "
                f"mostly the LSTM. This page will keep refreshing.")
        with st.expander("Log", expanded=True):
            st.code(dr.tail_log("stock_retrain"))
        time.sleep(2)
        st.rerun()
    elif state.status in ("done", "failed"):
        (st.success if state.status == "done" else st.error)(
            f"Last retrain {state.status} at {state.finished_at}."
        )
        with st.expander("Log"):
            st.code(dr.tail_log("stock_retrain"))

    col1, col2 = st.columns(2)
    with col1:
        st.subheader("XGBoost")
        if xgb_meta:
            st.caption(f"As of {xgb_meta['as_of_date']} · trained on {xgb_meta['train_rows']:,} rows · "
                       f"label cutoff (75th pct {xgb_meta['forward_window_trading_days']}d return) = "
                       f"{pct(xgb_meta['label_cutoff_fwd_return'])} · universe scored {xgb_meta['universe_size']:,}")
        if xgb_top is not None:
            st.dataframe(xgb_top, hide_index=True, use_container_width=True)
        else:
            st.info("No current_top10.csv yet.")
    with col2:
        st.subheader("LSTM")
        if lstm_meta:
            st.caption(f"As of {lstm_meta['as_of_date']} · trained on {lstm_meta['train_sequences']:,} sequences · "
                       f"label cutoff = {pct(lstm_meta['label_cutoff_fwd_return'])} · "
                       f"universe scored {lstm_meta['universe_size']:,} · best epoch {lstm_meta['best_epoch']}")
        if lstm_top is not None:
            st.dataframe(lstm_top, hide_index=True, use_container_width=True)
        else:
            st.info("No lstm_current_top10.csv yet.")

    if xgb_top is not None and lstm_top is not None:
        overlap = sorted(set(xgb_top["ticker"]) & set(lstm_top["ticker"]))
        st.caption(f"Overlap between the two top-10 lists: **{len(overlap)}/10** — {', '.join(overlap) if overlap else 'none'}.")


def render_stock_query():
    if feat is None:
        st.warning("No features.parquet — run a data refresh first.")
        return
    st.caption(
        "Scores against the **primary PIT augmented + stop-loss model** — the same signal as the Today's "
        "Picks tab — against the currently *saved* checkpoint (instant — no retraining). If you've pulled "
        "new price data since the last retrain, hit \"Retrain\" on the Today's Picks tab first for fully "
        "current results. BUY/NO BUY uses the model's top-quartile-of-predicted-probability rule (same "
        "convention as the Secondary Models query) — that's a different bar than being in today's absolute "
        "top-5 picks, so a ticker can show BUY here without being one of today's 5 allocated positions. A "
        "ticker can also show INELIGIBLE — the model may like it, but it fails the point-in-time mid-cap+ "
        "floor today (market cap < $2B or price < $10), so it isn't actually a live pick regardless of "
        "what the model thinks of it."
    )
    raw = st.text_input("Ticker(s), comma or space separated", placeholder="AAPL, MSFT, NVDA")
    if st.button("Look up", key="stock_query_btn") and raw.strip():
        tickers = [t for t in raw.replace(",", " ").split() if t]
        with st.spinner("Scoring..."):
            result = pm.query_tickers(tickers)
        if "error" in result:
            st.error(result["error"])
        else:
            cap = f"As of {result['as_of_date']}"
            if result.get("stop_loss_pct") is not None:
                cap += f" · suggested stop-loss {pct(result['stop_loss_pct'])} below entry"
            st.caption(cap)

            df = pd.DataFrame(result["rows"])
            col_order = (["ticker", "verdict", "buy_proba", "rank", "percentile"] + pm.CONTEXT_COLS)
            df = df[[c for c in col_order if c in df.columns]]
            st.dataframe(df, hide_index=True, use_container_width=True)

            for t in tickers:
                hist = sm.ticker_history(t, feat)
                if hist is not None:
                    with st.expander(f"{t} — price & momentum history"):
                        st.line_chart(hist.set_index("date")[["close"]])
                        st.line_chart(hist.set_index("date")[["momentum_20", "momentum_60", "momentum_120"]])

            with st.expander("Also compare against the secondary XGBoost / LSTM models"):
                st.caption(
                    "These are the standalone, non-PIT models shown on the Secondary Models tab — not "
                    "part of the primary signal above. Shown here only for cross-checking."
                )
                sec = sm.query_tickers(tickers)
                if "error" in sec:
                    st.info(sec["error"])
                else:
                    st.caption(f"XGBoost as of {sec['as_of_xgb']} · LSTM as of {sec['as_of_lstm']}")
                    st.dataframe(pd.DataFrame(sec["rows"]), hide_index=True, use_container_width=True)


def render_stock_weights():
    st.subheader("Augmented + stop-loss (PIT, primary)")
    st.caption(
        "The point-in-time mid-cap+ eligibility floor and the 15% stop-loss are both applied AFTER this "
        "model scores a ticker — they don't change what the model itself learned, only which tickers it's "
        "allowed to pick and when a pick exits. The feature importances below are what actually drive the "
        "model's ranking."
    )
    pimp = pm.get_feature_importances()
    if pimp is not None:
        imp_df = pimp["importances"].copy()
        st.bar_chart(imp_df.set_index("feature")[["importance"]])
        imp_df["feature"] = imp_df.apply(
            lambda r: f"{r['feature']} 🧾" if r["is_fundamentals_feature"] else r["feature"], axis=1
        )
        imp_df["importance"] = imp_df["importance"].map(lambda v: f"{v:.1%}")
        st.dataframe(imp_df[["feature", "importance"]], hide_index=True, use_container_width=True)
        top = pimp["importances"].iloc[0]
        st.caption(
            f"🧾 = a fundamentals feature — together they account for {pimp['fundamentals_share']:.1%} of "
            f"this model's total importance. Top feature: **{top['feature']}** ({top['importance']:.1%})."
        )
    else:
        st.info("No saved xgb_pit_augmented_model.json yet — hit \"Retrain\" on the Today's Picks tab first.")

    st.divider()
    with st.expander("Also see the secondary XGBoost / LSTM model weights"):
        st.subheader("XGBoost feature importances")
        imp = sm.get_feature_importances()
        if imp is not None:
            st.bar_chart(imp.set_index("feature"))
            st.dataframe(imp.assign(importance=imp["importance"].map(lambda v: f"{v:.1%}")),
                         hide_index=True, use_container_width=True)
            top_feat = imp.iloc[0]
            st.caption(
                f"**{top_feat['feature']}** alone accounts for {top_feat['importance']:.1%} of the model's "
                f"decision-making. This concentration is a known, discussed property of this model, not a bug — "
                f"see models/final-buy-no-buy-model.md."
            )
        else:
            st.info("No feature_importances.csv yet — retrain on the Secondary Models tab.")

        st.divider()
        st.subheader("LSTM architecture")
        lstm_full_meta = sm.lstm_meta()
        if lstm_full_meta:
            arch = {
                "Sequence length (trailing days)": lstm_full_meta.get("seq_len"),
                "Hidden size": lstm_full_meta.get("hidden_size"),
                "LSTM layers": lstm_full_meta.get("num_layers"),
                "Training sequences (cap)": f"{lstm_full_meta.get('train_sequences'):,}",
                "Best epoch (early stopping)": lstm_full_meta.get("best_epoch"),
                "Forward window (days)": lstm_full_meta.get("forward_window_trading_days"),
            }
            st.table(pd.Series(arch, name="value"))
            st.caption(
                "An LSTM doesn't have a simple per-feature weight table the way XGBoost's feature_importances_ "
                "does — its 11 input features are consumed jointly by the recurrent layer across a 20-day "
                "sequence. A permutation-importance or integrated-gradients pass would be the way to get an "
                "analogous per-feature breakdown for it; not computed yet."
            )
        else:
            st.info("No lstm_current_model_meta.json yet.")


def render_stock_backtest():
    st.subheader("Augmented + stop-loss (PIT, primary)")
    gbt = pm.get_backtest_tables()
    if not gbt:
        st.info("No PIT continuous walk-forward backtest output yet — run "
                 "continuous_walkforward_pit.py (see backtest/survivorship-bias-correction-results.md).")
    else:
        if "continuous_walkforward_summary" in gbt:
            summ = gbt["continuous_walkforward_summary"]
            st.write(f"**Continuous point-in-time walk-forward** — non-overlapping 40-day windows, "
                      f"universe={summ.get('universe', 'expanded')}, stop_pct={pct(summ.get('stop_pct'))}")
            curves = summ.get("curves", {})
            if curves:
                chart_df = pd.DataFrame({
                    name: {row["timepoint"]: row["value"] for row in curve if row["timepoint"]}
                    for name, curve in curves.items()
                })
                st.line_chart(chart_df)
                finals = {name: curve[-1]["value"] for name, curve in curves.items() if curve}
                st.dataframe(
                    pd.DataFrame([{"mode": k, "$10k ->": money(v)} for k, v in finals.items()]),
                    hide_index=True, use_container_width=True,
                )
                if "augmented_stoploss" in finals and "spy" in finals:
                    n_windows = len(summ.get("results", {}).get("augmented_stoploss", []))
                    st.caption(
                        f"augmented_stoploss (this model, {pct(summ.get('stop_pct'))} stop): "
                        f"{money(finals['augmented_stoploss'])} vs. SPY {money(finals['spy'])} over "
                        f"{n_windows} windows. See backtest/survivorship-bias-correction-results.md, "
                        f"Round 7 (universe/eligibility floor fix) and Round 8 (this stop-loss percentage's "
                        f"optimization sweep), for the full methodology and caveats — small-sample, no "
                        f"transaction costs, and the stop-loss level was chosen from a backtested sweep, "
                        f"not guaranteed to hold going forward."
                    )

            fi = summ.get("feature_importance_avg", {}).get("augmented")
            if fi:
                st.divider()
                st.write("**Aggregate feature importance across all walk-forward steps**")
                fi_df = pd.DataFrame([{"feature": k, "importance": v} for k, v in fi.items()])
                st.bar_chart(fi_df.set_index("feature"))
                st.dataframe(fi_df.assign(importance=fi_df["importance"].map(lambda v: f"{v:.1%}")),
                             hide_index=True, use_container_width=True)

        if "stop_pct_sweep" in gbt:
            st.divider()
            st.write("**Stop-loss percentage sweep (Round 8)** — re-simulates the same picks across a grid "
                      "of stop percentages to find the empirically-best level")
            sweep = gbt["stop_pct_sweep"].get("sweep", [])
            if sweep:
                sweep_df = pd.DataFrame(sweep)
                st.dataframe(sweep_df, hide_index=True, use_container_width=True)
                best = sweep_df.loc[sweep_df["final_value"].idxmax()]
                st.caption(
                    f"Best in this sweep: {pct(best['stop_pct'])} stop ({money(best['final_value'])} final "
                    f"value) — the operating value shown above may differ slightly (a rounder, less "
                    f"overfit choice within the same plateau; see Round 8 in the project doc for why)."
                )

    st.divider()
    with st.expander("Also see the secondary XGBoost / LSTM backtest & horizon sweep"):
        bt = sm.get_backtest_tables()
        if not bt:
            st.info("No backtest output yet.")
        else:
            col1, col2 = st.columns(2)
            with col1:
                st.subheader("XGBoost")
                if "xgb_picks" in bt:
                    st.dataframe(bt["xgb_picks"], hide_index=True, use_container_width=True)
                if "xgb_metrics" in bt:
                    st.dataframe(pd.DataFrame(bt["xgb_metrics"]), hide_index=True, use_container_width=True)
            with col2:
                st.subheader("LSTM")
                if "lstm_picks" in bt:
                    st.dataframe(bt["lstm_picks"], hide_index=True, use_container_width=True)
                if "lstm_metrics" in bt:
                    st.dataframe(pd.DataFrame(bt["lstm_metrics"]), hide_index=True, use_container_width=True)

            if bt.get("chart_path"):
                st.image(str(bt["chart_path"]), caption="Backtest equity curve")

            if "horizon_sweep" in bt:
                st.divider()
                st.subheader("Horizon sweep (10 / 20 / 40 / 60 trading days)")
                rows = []
                for horizon, models in bt["horizon_sweep"].items():
                    for model_name, m in models.items():
                        rows.append({"horizon_days": int(horizon), "model": model_name,
                                     "win_rate": f"{m['wins']}/{m['n']}",
                                     "avg_model_pct": m["avg_model_pct"], "avg_spy_pct": m["avg_spy_pct"]})
                st.dataframe(pd.DataFrame(rows).sort_values(["horizon_days", "model"]),
                             hide_index=True, use_container_width=True)
                st.caption(
                    "40 trading days is the current permanent default — see models/final-buy-no-buy-model.md "
                    "for why. Change FORWARD_WINDOW in features.py to test a different horizon; this table "
                    "will only update after horizon_sweep.py is rerun."
                )


def render_stock_pit():
    """Primary signal (2026-09-02): the point-in-time (survivorship-bias-
    corrected) augmented model, with an empirically-optimized 15% stop-loss.
    Replaces the HMM-gated blend per Gabe's explicit instruction -- "we are
    no longer using the HMM, augmented stoploss should be the primary
    model displayed in the app." See lib/pit_model.py and
    backtest/survivorship-bias-correction-results.md (Round 7/8) for the
    full methodology."""
    if feat is None:
        st.warning("No features.parquet — run a data refresh first (Data & Updates tab).")
        return

    st.caption(
        "**Primary signal.** Trains the augmented model (price momentum + point-in-time SEC fundamentals, "
        "no_staleness) fresh on all history through today, restricts today's candidates to the same "
        "point-in-time mid-cap+ eligibility floor used in the backtest (market cap ≥ $2B and price > $10 "
        "*as of today*, not just at some point in the past — see Round 7), and takes the top-5 by "
        "predicted probability. Each pick's suggested stop-loss is 15% below its entry close — the "
        "empirically-optimized level from a sweep over the backtest (Round 8), not an automated order."
    )
    st.caption(
        "Backtested $10k → $214,606 vs. SPY's $53,306 over 123 non-overlapping 40-day windows, 2007–2026 "
        "(expanded, mid-cap-floor-corrected universe). Caveats worth keeping in view: no transaction-cost/ "
        "slippage modeling, and the stop-loss percentage was chosen from a backtested sweep — a broad, "
        "well-supported plateau (12–17%), not a single lucky point, but still not guaranteed to hold going "
        "forward. See backtest/survivorship-bias-correction-results.md, Round 7 and Round 8, for the full "
        "writeup."
    )

    if not pm.fundamentals_pit_panel_exists():
        st.info(
            "No features_with_fundamentals_pit.parquet yet — hit \"Retrain\" below. The first run also "
            "rebuilds the base price panel and the PIT fundamentals panel from scratch, so it's slower "
            "than a normal retrain. Note: this needs features_pit.py's point-in-time gap-ticker data "
            "(scripts/td_data_delisted/, scripts/fundamentals_raw_delisted/, via sharadar_data_pull.py) to "
            "already be on disk — see the project doc's \"What Gabe needs to do next\" section if this is "
            "a fresh machine."
        )

    pit_df, pit_meta = pm.get_signal()
    status = pm.signal_status()
    if status["exists"] and status["stale"]:
        st.warning(
            f"The saved picks were computed as of {status['as_of_date']}, but the latest data on "
            f"disk goes through {status['latest_data_date']}. Retrain to pick up the newer data."
        )

    if st.button("🔁 Retrain on latest data", key="retrain_pit"):
        dr.run_step_sequence(
            "stock_retrain_pit", pm.retrain_commands(),
            ["Rebuild features.parquet", "Rebuild PIT price panel", "Rebuild PIT fundamentals panel",
             "Retrain model + compute today's picks"],
            cwd=paths.SRC_DIR,
        )
        st.rerun()

    state = dr.refresh_status("stock_retrain_pit")
    if state.status == "running":
        st.info(
            f"Retraining in progress (started {state.started_at})... rebuilding the full PIT price and "
            f"fundamentals panels from scratch can take several minutes; this page will keep refreshing."
        )
        with st.expander("Log", expanded=True):
            st.code(dr.tail_log("stock_retrain_pit"))
        time.sleep(2)
        st.rerun()
    elif state.status in ("done", "failed"):
        (st.success if state.status == "done" else st.error)(
            f"Last retrain {state.status} at {state.finished_at}."
        )
        with st.expander("Log"):
            st.code(dr.tail_log("stock_retrain_pit"))

    if pit_meta:
        c1, c2, c3 = st.columns(3)
        c1.metric("As of", pit_meta["as_of_date"])
        c2.metric("Stop-loss", pct(pit_meta.get("stop_loss_pct")))
        c3.metric("Eligible universe today", f"{pit_meta.get('n_eligible_today', 0):,}")

    if pit_df is not None:
        st.subheader("Today's picks")
        show = pit_df.copy()
        show["allocation_pct"] = show["allocation_pct"].map(lambda v: f"{v:.2f}%")
        st.dataframe(show, hide_index=True, use_container_width=True)
        if pit_meta:
            st.caption(f"Picks: {', '.join(pit_meta['picks'])}")
    else:
        st.info("No current_signal_pit.csv yet — hit Retrain above.")


def render_stock_universe():
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
        ("PIT features_pit.parquet", paths.OUT_DIR / "features_pit.parquet", False),
        ("PIT features_with_fundamentals_pit.parquet", paths.OUT_DIR / "features_with_fundamentals_pit.parquet", False),
        ("Primary model checkpoint (PIT augmented)", paths.STOCK_MODELS_DIR / "xgb_pit_augmented_model.json", False),
        ("XGBoost checkpoint (secondary)", paths.STOCK_MODELS_DIR / "xgb_current_model.json", False),
        ("LSTM checkpoint (secondary)", paths.STOCK_MODELS_DIR / "lstm_current_model.pt", False),
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
        "rebuilds every feature panel (including the PIT price/fundamentals panels) and retrains "
        "XGBoost, the LSTM, and the primary augmented + stop-loss (PIT) model. The options Tweedie GLM "
        "needs no separate retrain step — it refits automatically next time it's used, off whatever "
        "training data is newest on disk. Run the data update first, then retrain, if you want a fully "
        "current read in one sitting. Note: neither button refreshes scripts/fundamentals_raw/ (SEC "
        "EDGAR) or scripts/fundamentals_raw_delisted/ (Sharadar) — those are separate, much less "
        "frequent pulls, see the project doc."
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
            cmds = [
                [py, str(paths.SRC_DIR / "features.py")],
                [py, str(paths.SRC_DIR / "features_pit.py")],
                [py, str(paths.SRC_DIR / "fundamentals_features_pit.py")],
                [py, str(paths.SRC_DIR / "current_signal.py")],
                [py, str(paths.SRC_DIR / "lstm_current_signal.py")],
                [py, str(paths.SRC_DIR / "current_signal_pit.py")],
            ]
            labels = [
                "Rebuild price features.parquet",
                "Rebuild PIT price panel (features_pit.py)",
                "Rebuild PIT fundamentals panel",
                "Retrain XGBoost (secondary, price-only)",
                "Retrain LSTM (secondary)",
                "Retrain primary model (augmented + stop-loss, PIT) + compute today's picks",
            ]
            dr.run_step_sequence("retrain_all_models", cmds, labels, cwd=paths.SRC_DIR)
            st.rerun()
        _job_status_block("retrain_all_models")

    st.divider()
    st.subheader("1. Refresh stock price data + retrain both models")
    st.caption(
        "Runs local_data_pull.py (yfinance, your own network) for the full universe, rebuilds "
        "features.parquet, then retrains and rescoring XGBoost and the LSTM. The price pull only tops up "
        "the last ~40 days for tickers you already have data for (--refresh-recent), so it's much "
        "quicker than a first-time pull across ~1,600 tickers; the LSTM retrain is roughly a minute on "
        "top of that."
    )
    if st.button("Run full stock refresh", key="btn_stock_refresh"):
        py = sys.executable
        cmds = [[py, str(paths.SCRIPTS_DIR / "local_data_pull.py"), "--refresh-recent"]] + sm.retrain_commands()
        dr.run_step_sequence("stock_full_refresh", cmds,
                              ["Pull price data (yfinance)", "Rebuild features", "Retrain XGBoost", "Retrain LSTM"])
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
    t1, t2, t3, t4, t5, t6 = st.tabs(
        ["Today's Picks", "Query a Ticker", "Model Weights", "Backtest & History", "Universe", "Secondary Models (XGBoost / LSTM)"]
    )
    with t1:
        render_stock_pit()
    with t2:
        render_stock_query()
    with t3:
        render_stock_weights()
    with t4:
        render_stock_backtest()
    with t5:
        render_stock_universe()
    with t6:
        render_stock_secondary()

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
