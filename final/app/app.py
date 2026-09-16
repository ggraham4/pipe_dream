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
            pit_df, pit_meta = pm.get_signal(pm.PRIMARY)
            cand_df, _ = pm.get_signal(pm.CANDIDATE)
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
                               "count, not the deployed model's own universe.")
            if pit_meta:
                c2.metric("As of", pit_meta["as_of_date"])
                c3.metric("Horizon", f"{pit_meta.get('forward_window_trading_days', 40)}d")
            else:
                c3.metric("Forward horizon", f"{sm.universe_summary()['forward_window_days']}d")
            if pit_df is not None:
                st.caption("**Deployed signal** (q75, point-in-time, vol-bucketed top-5, "
                           "inverse-vol weighted) — today's picks. Not a validated edge.")
                show = pit_df[["ticker", "allocation_pct", "close",
                               "suggested_stop_loss_price"]].copy()
                show["allocation_pct"] = show["allocation_pct"].map(lambda v: f"{v:.2f}%")
                st.dataframe(show, hide_index=True, use_container_width=True)
            else:
                st.info("No current_signal_pit.csv yet — see the Today's Picks tab.")
            if cand_df is not None:
                agree = pm.get_agreement()
                n = agree.get("n_overlap") if agree else None
                st.caption(
                    f"Tracked candidate (xrank) picks: **{', '.join(cand_df['ticker'])}**"
                    + (f" · overlap {n}/5" if n is not None else "")
                    + ". Shown for comparison only — it returned −4.28%/yr excess "
                      "(0.771× SPY) on the 2020-2026 hold-out. Today's Picks tab has "
                      "the detail."
                )

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

HOLDOUT_BANNER = (
    "**The candidate is displayed, not followed.** `xrank` recovered "
    "model-level information coefficient in Round 17b and then lost to SPY on "
    "the 2020-2026 hold-out: **-4.28%/yr excess, 0.771x SPY**, against the "
    "deployed model's **+7.33%/yr, 1.526x**. It is on this page so its "
    "disagreements with the deployed model are visible, not as an alternative "
    "to trade. See `backtest/2026-09-12-xrank-fails-the-holdout-do-not-switch.md`."
)

NOT_AN_EDGE = (
    "**This is not a validated edge, and it is not claimed to be one.** A "
    "pre-registered sweep of 1,152 configurations (Round 12) failed its "
    "acceptance criteria — Deflated Sharpe 0.746 against a 0.95 threshold, "
    "White Reality Check p = 0.61. Round 13 showed every fundamental feature "
    "that appeared to carry signal is a **sector bet** (the strongest drops "
    "from t = 3.28 to t = 0.77 under sector neutralization). Rounds 15 and 15b "
    "closed off breadth and horizon as levers: effective breadth is capped at "
    "~16 bets per window by an average pairwise active correlation of 0.055–"
    "0.076, and varying breadth **13×** did not move the result. "
    "What the model demonstrably owns is a **low-volatility tilt** "
    "(score-vs-volatility correlation −0.134) plus a tech/healthcare sector "
    "bet — both purchasable as ETFs, which is why USMV is on the chart in "
    "Backtest & History. For calibration: in a synthetic grid containing **no "
    "signal at all**, 27% of configurations beat the market and the best "
    "reached 2.58×."
)


def _signal_freshness_warning(status: dict, label: str):
    if status["exists"] and status["stale"]:
        st.warning(
            f"{label}: picks were computed as of {status['as_of_date']}, but the "
            f"panel on disk goes through {status['latest_data_date']}. Retrain to "
            f"pick up the newer data."
        )


def _picks_table(df: pd.DataFrame, compact: bool = False) -> pd.DataFrame:
    show = df.copy()
    if "allocation_pct" in show.columns:
        show["allocation_pct"] = show["allocation_pct"].map(lambda v: f"{v:.2f}%")
    if compact:
        cols = [c for c in ("ticker", "allocation_pct", "close",
                            "suggested_stop_loss_price") if c in show.columns]
        return show[cols]
    return show


def _noise_band_caption(comp):
    """The single most important number for reading anything else on the page."""
    ns = (comp or {}).get("noise_scale")
    if not ns:
        return None
    return (
        f"**Noise scale: {ns['excess_cagr_pct_min']:+.2f} to "
        f"{ns['excess_cagr_pct_max']:+.2f} %/yr excess, sd "
        f"{ns['excess_cagr_pct_sd']:.2f}** — across {ns['n_cells']} cells that "
        f"differ from the deployed one only by a turned knob (training window, "
        f"training cap, tree depth, market-cap tier, label basis), on the same "
        f"features, label and model. Any difference smaller than this band is "
        f"not evidence of anything, including the difference between the two "
        f"models on this page."
    )


def render_stock_pit():
    """Today's Picks -- the deployed signal, with the tracked candidate beside
    it. Both are produced by final/src/current_signal_pit.py in one run; see
    lib/pit_model.py for what each file on disk is."""
    if feat is None:
        st.warning("No features.parquet — run a data refresh first (Data & Updates tab).")
        return

    st.caption(
        "**Deployed configuration.** Trains on the most recent **500,000 labelled "
        "rows** of price momentum + point-in-time SEC fundamentals (24 features), "
        "restricts today's candidates to that date's **point-in-time universe** "
        "(the same screen the backtest used), then takes the **single best name "
        "in each of 5 trailing-volatility quintiles** and weights them by "
        "**inverse volatility**. Entry is the next open; the position is held to "
        "the 40-day horizon with **no stop-loss**. The 15% stop price shown per "
        "name is risk guidance only and is not part of the backtested "
        "configuration."
    )
    st.error(NOT_AN_EDGE)
    st.warning(HOLDOUT_BANNER)

    if not pm.fundamentals_pit_panel_exists():
        st.info(
            "No features_with_fundamentals_sharadar_pit.parquet yet — hit "
            "\"Retrain\" below. The first run rebuilds the Sharadar panel, the "
            "point-in-time universe and both feature panels from scratch, so it "
            "is much slower than a normal retrain."
        )

    statuses = pm.all_signal_status()
    for v in pm.VARIANTS:
        _signal_freshness_warning(statuses[v["key"]], v["short_name"])

    if st.button("🔁 Retrain both signals on latest data", key="retrain_pit"):
        dr.run_step_sequence("stock_retrain_pit", pm.retrain_commands(),
                             pm.PIT_STEP_LABELS, cwd=paths.SRC_DIR)
        st.rerun()

    state = dr.refresh_status("stock_retrain_pit")
    if state.status == "running":
        st.info(
            f"Retraining in progress (started {state.started_at})... rebuilding "
            f"the panels from scratch can take several minutes; this page keeps "
            f"refreshing."
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

    signals = pm.get_all_signals()
    primary_df, primary_meta = signals[pm.PRIMARY]
    if primary_meta:
        c1, c2, c3 = st.columns(3)
        c1.metric("As of", primary_meta["as_of_date"])
        c2.metric("Eligible universe today", f"{primary_meta.get('n_eligible_today', 0):,}")
        c3.metric("Horizon", f"{primary_meta.get('forward_window_trading_days', 40)}d")

    cols = st.columns(len(pm.VARIANTS))
    for col, v in zip(cols, pm.VARIANTS):
        df, meta = signals[v["key"]]
        with col:
            if v["role"] == "primary":
                st.subheader(f"✅ {v['display_name']}")
                st.caption("The signal this app runs.")
            else:
                st.subheader(f"👁️ {v['display_name']}")
                st.caption("Tracked for comparison. **Not** a recommendation.")
            if df is None:
                st.info(f"No {v['signal_csv']} yet — hit Retrain above.")
                continue
            st.dataframe(_picks_table(df), hide_index=True, use_container_width=True)
            if meta:
                bits = [f"cell `{meta.get('cell_id', v['cell_id'])}`"]
                if meta.get("holdout_excess_cagr_pct") is not None:
                    bits.append(
                        f"hold-out 2020-2026: **{meta['holdout_excess_cagr_pct']:+.2f}%/yr** "
                        f"excess ({meta.get('holdout_mult_vs_spy')}× SPY)")
                st.caption(" · ".join(bits))

    agree = pm.get_agreement()
    if agree:
        n = agree.get("n_overlap", 0)
        names = ", ".join(agree.get("overlap", [])) or "none"
        st.info(f"**Overlap today: {n}/5** — {names}")
        st.caption(agree.get("caveat", ""))

    comp = pm.get_comparison()
    band = _noise_band_caption(comp)
    if band:
        st.caption(band)


def render_stock_query():
    if feat is None:
        st.warning("No features.parquet — run a data refresh first.")
        return
    st.caption(
        "Scores a ticker against **both** saved checkpoints — the deployed model "
        "and the tracked candidate — using the currently saved weights (instant, "
        "no retraining). If you have pulled new price data since the last "
        "retrain, hit \"Retrain\" on the Today's Picks tab first. "
        "**BUY** here means top quartile of predicted score among eligible names, "
        "which is a lower bar than being one of today's five allocated positions, "
        "so a ticker can read BUY without being a pick. **INELIGIBLE** means the "
        "name is not in today's point-in-time universe, so it is not pickable "
        "regardless of what the model thinks of it."
    )
    st.caption(
        "The candidate's verdict is a second opinion to read against the "
        "deployed one, not a vote to average with it — it lost to SPY on the "
        "hold-out (-4.28%/yr excess)."
    )
    raw = st.text_input("Ticker(s), comma or space separated", placeholder="AAPL, MSFT, NVDA")
    if st.button("Look up", key="stock_query_btn") and raw.strip():
        tickers = [t for t in raw.replace(",", " ").split() if t]
        with st.spinner("Scoring..."):
            result = pm.query_tickers(tickers)
        if "error" in result:
            st.error(result["error"])
            return

        cap = f"As of {result['as_of_date']}"
        if result.get("stop_loss_pct") is not None:
            cap += f" · suggested stop-loss {pct(result['stop_loss_pct'])} below entry (guidance only)"
        st.caption(cap)

        df = pd.DataFrame(result["rows"])
        col_order = (["ticker", "verdict", "score", "rank",
                      "candidate_verdict", "candidate_score", "candidate_rank"]
                     + pm.CONTEXT_COLS)
        df = df[[c for c in col_order if c in df.columns]]
        st.dataframe(df, hide_index=True, use_container_width=True)

        disagree = [r["ticker"] for r in result["rows"]
                    if r.get("verdict") != r.get("candidate_verdict")]
        if disagree:
            st.caption(f"The two models disagree on: **{', '.join(disagree)}**. "
                       f"Disagreement is information about how stable the ranking "
                       f"is, not a tiebreak to resolve.")

        for t in tickers:
            hist = sm.ticker_history(t, feat)
            if hist is not None:
                with st.expander(f"{t} — price & momentum history"):
                    st.line_chart(hist.set_index("date")[["close"]])
                    st.line_chart(hist.set_index("date")[["momentum_20", "momentum_60", "momentum_120"]])


def render_stock_weights():
    st.caption(
        "Gain-based feature importances off each saved checkpoint. Read them as "
        "*what the trees split on*, not as *what predicts returns*: Round 17 "
        "took a raw feature with t = +3.40 and watched it come out of this "
        "pipeline at t = −0.65, and Round 13 showed the fundamental block's "
        "apparent signal is a sector bet. A tall bar here is a description of "
        "the model, not evidence about the world."
    )
    tabs = st.tabs([v["display_name"] for v in pm.VARIANTS])
    for tab, v in zip(tabs, pm.VARIANTS):
        with tab:
            if v["role"] == "candidate":
                st.warning(HOLDOUT_BANNER)
            pimp = pm.get_feature_importances(v["key"])
            if pimp is None:
                st.info(f"No saved {v['model_file']} yet — hit \"Retrain\" on the "
                        f"Today's Picks tab first.")
                continue
            imp_df = pimp["importances"].copy()
            st.bar_chart(imp_df.set_index("feature")[["importance"]])
            shown = imp_df.copy()
            shown["feature"] = shown.apply(
                lambda r: f"{r['feature']} 🧾" if r["is_fundamentals_feature"] else r["feature"],
                axis=1)
            shown["importance"] = shown["importance"].map(lambda x: f"{x:.1%}")
            st.dataframe(shown[["feature", "importance"]], hide_index=True,
                         use_container_width=True)
            top = imp_df.iloc[0]
            st.caption(
                f"🧾 = a fundamentals feature — together {pimp['fundamentals_share']:.1%} "
                f"of this model's total importance. Top feature: "
                f"**{top['feature']}** ({top['importance']:.1%})."
            )

    st.divider()
    st.caption(
        "Both models use the identical 24 columns and identical hyperparameters "
        "(depth 3, eta 0.1, 100 rounds, most recent 500k labelled rows). The "
        "only difference between them is the training target: a binary "
        "top-quartile label versus a within-date percentile rank. Any "
        "difference in the charts above is that one change propagating through "
        "the trees."
    )


def render_stock_backtest():
    comp = pm.get_comparison()
    if comp is None:
        st.info(
            "No out/app_model_comparison.json yet — run "
            "`python3 final/src/build_app_benchmarks.py`, or hit \"Retrain\" on "
            "the Today's Picks tab (it is the last step of that sequence)."
        )
        return

    cons = comp.get("construction", {})
    st.caption(
        f"Non-overlapping {cons.get('horizon_trading_days', 40)}-trading-day "
        f"windows. Each window: top name in each of {cons.get('top_n', 5)} "
        f"volatility quintiles, {cons.get('weighting', 'invvol')}-weighted, "
        f"entered at the **next open**, exited at the close "
        f"{cons.get('horizon_trading_days', 40)} trading days later, "
        f"{cons.get('cost_bps', 15)}bp charged against turnover. Benchmarks use "
        f"the identical entry/exit convention. "
        f"**{cons.get('returns', 'price only, no dividends on either side')}** — "
        f"so SPY and USMV are each understated by roughly their ~1.8–1.9%/yr "
        f"distribution yield, and so are the model's own picks."
    )

    band = _noise_band_caption(comp)
    if band:
        st.warning(band)

    era_labels = {"nominate": "2007–2019 (selection era)",
                  "holdout": "2020–2026 (hold-out)"}
    present = [e for e in ("holdout", "nominate") if e in comp.get("eras", {})]
    if not present:
        st.info("The comparison file has no eras in it — rebuild it.")
        return

    tabs = st.tabs([era_labels.get(e, e) for e in present])
    for tab, era in zip(tabs, present):
        with tab:
            if era == "holdout":
                st.caption(
                    "**Spent.** 2020-2026 was used once, in Round 13, to confirm "
                    "the top-5 breadth choice, and once more in Round 18 to test "
                    "the xrank label. It is replotted here because those numbers "
                    "are already paid for — it cannot adjudicate anything new. "
                    "Nothing from here may be confirmed on it."
                )
            else:
                st.caption(
                    "**In-sample.** The deployed configuration was selected on "
                    "this span out of 1,152 candidates, so its result here is "
                    "biased upward by the search and is not an estimate of "
                    "forward return."
                )
            df = pm.comparison_frame(era)
            if df is not None:
                st.line_chart(df)
                st.caption(
                    "Growth of $1 across the windows in this era. A series that "
                    "starts later (USMV, inception 2011-10) is rebased to $1 at "
                    "its own first window rather than back-filled, so read its "
                    "level against SPY over the same sub-span, not against the "
                    "left edge of the chart."
                )
            summ = comp["eras"][era].get("summary", {})
            labels = {}
            labels.update({k: v["display_name"] for k, v in comp.get("cells", {}).items()})
            labels.update({k: v["display_name"] for k, v in comp.get("benchmarks", {}).items()})
            rows = []
            for k, s in summ.items():
                if not s:
                    continue
                rows.append({
                    "series": labels.get(k, k),
                    "windows": s["n_windows"],
                    "$1 →": f"${s['mult']:.2f}",
                    "CAGR": f"{s['cagr_pct']:+.2f}%",
                    "excess vs SPY": ("—" if s.get("excess_cagr_pct") is None
                                      else f"{s['excess_cagr_pct']:+.2f}%/yr"),
                    "× SPY": ("—" if s.get("mult_vs_spy") is None
                              else f"{s['mult_vs_spy']:.3f}"),
                    "max drawdown": f"{s['max_drawdown_pct']:.2f}%",
                    "full span": "yes" if s.get("covers_full_era", True) else "partial",
                })
            if rows:
                st.dataframe(pd.DataFrame(rows), hide_index=True, use_container_width=True)

    unavailable = [b["display_name"] for b in comp.get("benchmarks", {}).values()
                   if b.get("unavailable_reason")]
    if unavailable:
        why = "; ".join(f"{b['display_name']}: {b['unavailable_reason']}"
                        for b in comp.get("benchmarks", {}).values()
                        if b.get("unavailable_reason"))
        st.caption(f"Missing benchmark line(s) — {why}. Rerun "
                   f"`build_app_benchmarks.py` from a machine with network "
                   f"access; it pulls once and caches to data/benchmarks/.")

    st.caption(
        "Read the whole table against the noise band above before concluding "
        "anything from a gap between two rows."
    )


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
        "**both** stock signals — the deployed q75 model and the tracked xrank candidate — and rebuilds "
        "the SPY/USMV comparison chart. The options Tweedie GLM "
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
            cmds = [[py, str(paths.SRC_DIR / "features.py")]] + pm.retrain_commands()
            labels = ["Rebuild price features.parquet (sidebar + Universe tab)"] \
                + pm.PIT_STEP_LABELS
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
    t1, t2, t3, t4, t5 = st.tabs(
        ["Today's Picks", "Query a Ticker", "Model Weights",
         "Backtest & History", "Universe"]
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
