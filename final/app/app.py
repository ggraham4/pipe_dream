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
                 pit_model as pm, composite_model as cm)

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


def render_ticker_taxonomy(ticker: str, as_of=None):
    """One ticker's full industry path, with what the model did to each group.

    Used from both the ticker query and the Sector Bets tab. The group label is
    a fact about the TICKER; the picks/expected/q columns beside it are a fact
    about the MODEL, and putting them on one row is what makes the lookup worth
    more than a classification table. It is still description, not a reason to
    buy anything -- Round 13 measured that sector-neutralising removes
    essentially all of the edge, so an enriched group is where the model bets,
    not where it was shown to be right.
    """
    from lib import sector_view as sv

    t = str(ticker).strip().upper()
    if not sv.known_ticker(t):
        st.caption(f"**{t}** is not in `tickers_master.csv`, so it has no "
                   f"industry classification. That is a data gap, not a model "
                   f"verdict.")
        return
    d = sv.ticker_groups(t, as_of, sv.load_enrichment())
    show = d.copy()
    ren = {"level": "level", "group": "group",
           "n_eligible_today": "peers eligible today", "picks": "picks (620)",
           "expected": "expected", "ratio": "×", "q_enrich": "q over",
           "q_deplete": "q under"}
    for c in ("expected",):
        if c in show:
            show[c] = show[c].map(lambda v: f"{v:.1f}" if pd.notna(v) else "—")
    if "ratio" in show:
        show["ratio"] = show["ratio"].map(
            lambda v: f"{v:.2f}x" if pd.notna(v) else "—")
    for c in ("q_enrich", "q_deplete"):
        if c in show:
            show[c] = show[c].map(lambda v: f"{v:.3g}" if pd.notna(v) else "—")
    show = show.rename(columns=ren)
    st.dataframe(show, hide_index=True, use_container_width=True)
    st.caption(
        "Coarse to fine. `picks (620)` is how often the deployed model has "
        "bought *anything* from that group across all 124 rebalance windows, "
        "against what a draw from the same volatility quintiles would give; "
        "`q` is BH-corrected across every group at that level. A group can be "
        "strongly enriched at one level and flat at the next — that gap is "
        "where the bet actually lives."
    )


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
            with st.expander(f"{t} — industry classification & the model's "
                             f"standing bet on it"):
                render_ticker_taxonomy(t, result.get("as_of_date"))
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


def render_sector_enrichment(sv, picks, desc):
    """Which groups the model over-picks, and whether it is more than chance.

    Two tests, and the difference between them is the point.

    TODAY is five draws. Against 145 industry groups a single group needs two
    of the five before Benjamini-Hochberg can call anything at all, so an empty
    table is the EXPECTED table and is labelled as such. Reporting an uncorrected
    p here would manufacture a finding from a 5-name portfolio.

    POOLED is the 124 rebalance windows in the score cache -- 620 draws -- which
    is where the power is. It is computed offline by build_sector_enrichment.py
    because it needs the cached score cross-section the app never loads.

    Both use the construction-matched null: the model takes the best name in
    each of five volatility quintiles, so the count in a group is a sum of five
    one-draw hypergeometrics rather than one five-draw hypergeometric. The flat
    p is shown beside it so the size of that correction is visible.
    """
    st.subheader("Is any of this more than chance?")
    st.caption(
        "A hypergeometric enrichment test, the same one used for GO terms — "
        "but matched to how the model actually draws. It takes the single best "
        "name in each of **five trailing-volatility quintiles**, so a group's "
        "pick count is a sum of five *one-draw* hypergeometrics, not one "
        "five-draw hypergeometric. The two have the same expectation and "
        "different dispersion, and for a group that sits inside one quintile "
        "(utilities low, biotech high — most of what a fine taxonomy separates) "
        "the flat version is over-dispersed and understates a real "
        "concentration by roughly an order of magnitude. Every p is reported "
        "with a Benjamini-Hochberg **q** across all groups at that level."
    )

    enr = sv.load_enrichment()
    t_pool, t_today = st.tabs(["Pooled, 124 windows (620 draws)",
                               "Today's 5 picks (underpowered)"])

    with t_pool:
        if not enr:
            st.info("Not built yet — run `python3 final/src/build_sector_enrichment.py`.")
        else:
            c1, c2 = st.columns(2)
            lvl = c1.selectbox("Level", sv.DISPLAY_LEVELS, key="enr_level")
            era = c2.selectbox("Era", ["nominate", "holdout", "all"],
                               key="enr_era",
                               format_func=lambda e: {
                                   "nominate": "2007–2019 (nomination)",
                                   "holdout": "2020–2026 (hold-out)",
                                   "all": "2007–2026 (all)"}[e])
            meta = enr.get("eras", {}).get(era, {})
            d = sv.enrichment_frame(enr, lvl, era)
            if d.empty:
                st.info("No rows at this level and era.")
            else:
                sig = d[d["q_enrich"] < 0.10]
                st.caption(
                    f"{meta.get('n_windows', '?')} windows, "
                    f"{meta.get('n_draws', '?')} draws. "
                    f"**{len(sig)} of {len(d)} groups** clear q < 0.10."
                )
                show = d.head(40).copy()
                show = show[["group", "observed", "expected", "ratio",
                             "p_enrich", "q_enrich", "q_deplete",
                             "p_enrich_flat"]]
                show.columns = ["group", "picks", "expected", "×", "p",
                                "q over (BH)", "q under (BH)",
                                "p if unstratified"]
                show["expected"] = show["expected"].map(lambda v: f"{v:.1f}")
                show["×"] = show["×"].map(lambda v: f"{v:.2f}x")
                for c in ("p", "q over (BH)", "q under (BH)",
                          "p if unstratified"):
                    show[c] = show[c].map(lambda v: f"{v:.3g}")
                st.dataframe(show, hide_index=True, use_container_width=True,
                             height=min(620, 40 + 28 * len(show)))
                st.caption(
                    "`expected` is what a random draw from the *same volatility "
                    "quintiles* would have produced. Sorted by q; the top 40 are "
                    "shown. This is descriptive — it reports what the model did "
                    "and selects nothing — which is why the hold-out era is "
                    "shown here at all, and why it is split rather than pooled."
                )
                if len(sig):
                    both = None
                    dn = sv.enrichment_frame(enr, lvl, "nominate", q_max=0.10)
                    dh = sv.enrichment_frame(enr, lvl, "holdout", q_max=0.10)
                    if not dn.empty and not dh.empty:
                        both = sorted(set(dn["group"]) & set(dh["group"]))
                    if both:
                        st.success(
                            "**Enriched in both eras** (q < 0.10 in the "
                            "nomination era *and* independently in the hold-out): "
                            + ", ".join(f"**{g}**" for g in both)
                            + ". A tilt that survives the hold-out is the only "
                            "kind worth describing as a standing preference."
                        )
                    else:
                        st.info(
                            "No group clears q < 0.10 in both eras. Treat any "
                            "single-era result as a description of that era."
                        )
                # The other tail. A 5-name book must be underweight almost
                # everything, so "avoided" only means something against the
                # SAME construction-matched null the overweights are judged on
                # -- and there it is a real, separately-testable statement.
                av = d[d["q_deplete"] < 0.10]
                if len(av):
                    st.caption(
                        "**Significantly avoided** at q < 0.10 (the depletion "
                        "tail of the same test, corrected separately): "
                        + ", ".join(f"{r.group} ({r.observed} vs "
                                    f"{r.expected:.0f} expected)"
                                    for r in av.head(8).itertuples())
                        + ". A 5-name book is underweight nearly everything by "
                        "construction; these are the groups it is underweight "
                        "by more than the volatility-quintile draw explains."
                    )

    with t_today:
        st.caption(
            "Five draws. A group needs **2 of the 5** before BH can call "
            "anything at 145 groups, so an empty table here is the expected "
            "outcome and is not evidence that today's book is untilted — it is "
            "evidence that five draws cannot answer the question. It needs the "
            "full scored cross-section (~2.3GB panel), so it loads on request."
        )
        lvl_t = st.selectbox("Level", sv.DISPLAY_LEVELS, key="enr_today_level")
        if st.button("Run the test on today's picks", key="enr_today_go"):
            st.session_state["_enr_today"] = lvl_t
        if st.session_state.get("_enr_today"):
            lt = st.session_state["_enr_today"]
            with st.spinner("Scoring the eligible universe ..."):
                scored, _ = pm.scored_universe(pm.PRIMARY)
            if scored is None:
                st.info("No saved checkpoint or panel yet — retrain first.")
            else:
                rows = sv.enrichment_today(lt, picks, scored)
                if not rows:
                    st.info("Could not stratify today's universe — every "
                            "eligible name needs a finite `volatility_60`, "
                            "since that is what the quintiles are cut on.")
                else:
                    d = pd.DataFrame([r for r in rows if r["observed"] > 0])
                    d = d[["group", "observed", "expected", "ratio",
                           "p_enrich", "q_enrich"]]
                    d.columns = ["group", "picks", "expected", "×", "p", "q (BH)"]
                    d["expected"] = d["expected"].map(lambda v: f"{v:.3f}")
                    d["×"] = d["×"].map(lambda v: f"{v:.1f}x")
                    for c in ("p", "q (BH)"):
                        d[c] = d[c].map(lambda v: f"{v:.3g}")
                    st.dataframe(d, hide_index=True, use_container_width=True)
                    n_sig = sum(1 for r in rows if r["q_enrich"] < 0.10)
                    if n_sig:
                        st.success(f"{n_sig} group(s) clear q < 0.10 on five "
                                   f"draws — which takes a real concentration.")
                    else:
                        st.info("Nothing clears q < 0.10, which is what five "
                                "draws almost always says. Use the pooled tab.")


def render_stock_sectors():
    """What the model is betting on, at every level of the industry tree.

    Round 13 found essentially all of this model's performance is a sector bet,
    and the 2026-09-16 hierarchy screen found the bet is somewhat FINER than
    sector at the traded tail. Neither was visible anywhere in this app until
    now, which meant the single best-established fact about the model was the
    one thing a user could not see."""
    from lib import sector_view as sv

    df, meta = pm.get_signal(pm.PRIMARY)
    if df is None or meta is None:
        st.info("No current signal yet — hit Retrain on the Today's Picks tab.")
        return

    st.caption(
        "**Active weight**, not portfolio weight: the book's weight in a group "
        "minus the *eligible universe's* weight in that group on the same date. "
        "A portfolio 30% in technology when the universe is 28% technology is "
        "not a technology bet, it is the market. The universe is equal-weighted "
        "because that is the benchmark the model's own construction-matched "
        "null uses — a random pick from the eligible set."
    )
    st.caption(
        "Why this tab exists: Round 13 measured that essentially **all** of this "
        "model's performance is a sector bet — sector-neutralising drops the "
        "nomination era from 2.7957× to 0.7719 against a null median of 0.7721, "
        "the exact centre. The 2026-09-16 hierarchy screen then found the bet is "
        "somewhat finer than sector at the traded tail (industry-level "
        "neutralisation explains ~47% more of the decile edge than sector-level, "
        "t ≈ 1.5). So this is not a curiosity — it is the clearest picture "
        "available of what the model actually does."
    )

    desc = sv.describe(df, meta["as_of_date"])
    conc = sv.concentration(desc)
    hist = sv.load_tilt_history()

    if not desc.get("_universe_ok"):
        st.error(
            f"**No point-in-time universe for {meta['as_of_date']}** — "
            f"`data/sharadar/pit_universe.parquet` is missing or has no row for "
            f"that date. Every number below is then computed against a universe "
            f"weight of zero, which makes the whole book look like a 100% "
            f"active bet. Read nothing off this tab until that file is built "
            f"(`build_pit_universe.py`)."
        )
    else:
        st.caption(f"Benchmark: the {desc['_n_universe']:,} names in the "
                   f"point-in-time universe on {meta['as_of_date']}.")

    top = desc["sector"]
    top = top[top["n_picks"] > 0]
    if len(top):
        lead = top.iloc[0]
        c1, c2, c3 = st.columns(3)
        c1.metric(f"Largest sector bet", lead["sector"],
                  f"{lead['active_pct']:+.1f}pp vs universe")
        c2.metric("Sectors held", f"{int((desc['sector']['n_picks'] > 0).sum())} of "
                                  f"{len(desc['sector'])}")
        if hist:
            h = {r["group"]: r for r in
                 hist["levels"]["sector"]["nominate"]["groups"]}
            hm = h.get(lead["sector"], {}).get("mean_active")
            if hm is not None:
                ratio = lead["active_pct"] / hm if hm > 0 else float("nan")
                c3.metric("vs its own history", f"{hm:+.1f}pp typical",
                          f"{ratio:.1f}x today" if ratio == ratio else None,
                          delta_color="off")

    st.subheader("Today's active weights by sector")
    bar = desc["sector"].set_index("sector")[["active_pct"]]
    bar = bar[bar["active_pct"].abs() > 1e-9].sort_values("active_pct")
    st.bar_chart(bar)
    st.caption("Above zero = overweight the eligible universe. Below = underweight, "
               "which for a 5-name book is most of the market by construction.")

    st.divider()
    st.subheader("All the way down")
    st.caption(
        "The statistics stop at 145 groups — fitting 366 industry dummies on a "
        "1,665-name cross-section absorbs noise rather than industry, so "
        "`sic3` and `sicindustry` are excluded from the neutralisation "
        "experiment. That objection is about **regression**, not **counting**: "
        "\"three of five picks are in Biotechnology\" is a fact about the "
        "portfolio, not an estimate with a standard error. So the description "
        "goes deeper than the statistics do, and the two are consistent."
    )
    tabs = st.tabs([f"{l} ({len(desc[l])} groups)" for l in sv.DISPLAY_LEVELS])
    for tab, lvl in zip(tabs, sv.DISPLAY_LEVELS):
        with tab:
            d = desc[lvl].copy()
            held = d[d["n_picks"] > 0].copy()
            show = held[[lvl, "portfolio_pct", "universe_pct", "active_pct",
                         "n_picks", "n_universe"]]
            for c in ("portfolio_pct", "universe_pct", "active_pct"):
                show[c] = show[c].map(lambda v: f"{v:+.2f}%")
            st.dataframe(show, hide_index=True, use_container_width=True)
            st.caption(
                f"Concentration at this level: **{conc[lvl]:.1f}%** of the book "
                f"sits in groups it is overweight. This rises mechanically as "
                f"the tree gets finer — a 5-name portfolio cannot match a "
                f"{len(desc[lvl])}-group universe — so compare it across dates, "
                f"never across levels."
            )
            if hist and lvl in hist["levels"]:
                h = {r["group"]: r for r in hist["levels"][lvl]["nominate"]["groups"]}
                rows = []
                for _, r in held.iterrows():
                    e = h.get(r[lvl])
                    rows.append({
                        lvl: r[lvl],
                        "today": f"{r['active_pct']:+.1f}pp",
                        "2007-2019 mean": (f"{e['mean_active']:+.1f}pp" if e else "—"),
                        "held in": (f"{e['frequency']:.0%} of windows" if e else "never"),
                    })
                if rows:
                    st.caption("**Is today typical?**")
                    st.dataframe(pd.DataFrame(rows), hide_index=True,
                                 use_container_width=True)

    st.divider()
    st.subheader("Where does a ticker sit?")
    st.caption(
        "Its group at every level of the tree, beside what the model has "
        "historically done with each of those groups. Works for any classified "
        "ticker, held or not."
    )
    tq = st.text_input("Ticker", placeholder="AMGN", key="sector_ticker_q")
    if tq.strip():
        render_ticker_taxonomy(tq, meta["as_of_date"])

    st.divider()
    render_sector_enrichment(sv, df, desc)

    st.divider()
    st.subheader("Look inside a group")
    st.caption(
        "Every name the model **scored** in one group, not just the ones it "
        "bought — including what it thought of the names it passed over. "
        "Scoring the full eligible cross-section needs the point-in-time panel "
        "(~2.3GB), so the first load is slow and every later one is cached."
    )
    lvl_pick = st.selectbox("Level", sv.DISPLAY_LEVELS, key="drill_level")
    d_lvl = desc[lvl_pick]
    held_groups = d_lvl[d_lvl["n_picks"] > 0][lvl_pick].tolist()
    other = [g for g in d_lvl[lvl_pick].tolist() if g not in held_groups]
    choices = held_groups + other
    labels = {g: (f"● {g}" if g in held_groups else g) for g in choices}
    grp = st.selectbox("Group  (● = the model holds something here)", choices,
                       format_func=lambda g: labels[g], key="drill_group")

    if st.button("Load group", key="drill_go"):
        st.session_state["_drill"] = (lvl_pick, grp)
    if st.session_state.get("_drill"):
        lvl_s, grp_s = st.session_state["_drill"]
        with st.spinner(f"Scoring the eligible universe for {grp_s} ..."):
            scored, smeta = pm.scored_universe(pm.PRIMARY)
        if scored is None:
            st.info("No saved checkpoint or panel yet — retrain first.")
        else:
            prof = sv.group_rank_profile(lvl_s, grp_s, scored)
            if prof:
                c1, c2, c3, c4 = st.columns(4)
                c1.metric("Names scored", f"{prof['n_scored']:,}")
                c2.metric("Median percentile", f"{prof['median_percentile']:.2f}",
                          f"{prof['median_percentile'] - 0.5:+.2f} vs 0.50",
                          delta_color="inverse")
                c3.metric("Best rank in group", f"{prof['best_rank']:,}")
                c4.metric("In model's top decile",
                          f"{prof['share_top_decile']:.0%}")
                mp = prof["median_percentile"]
                if mp < 0.42:
                    st.success(
                        f"The model rates **this whole group** highly — a typical "
                        f"member sits at percentile {mp:.2f} against 0.50 for a "
                        f"group it is indifferent to. That is a group bet: the "
                        f"specific names held are close to incidental, and almost "
                        f"any member would have served."
                    )
                elif mp > 0.58:
                    st.warning(
                        f"The model rates this group POORLY overall (median "
                        f"percentile {mp:.2f}) yet holds something in it — so the "
                        f"position is within-group selection, not a group bet."
                    )
                else:
                    st.info(
                        f"The model is roughly indifferent to this group as a "
                        f"whole (median percentile {mp:.2f}). Anything held here "
                        f"is genuine within-group selection — which Round 13 "
                        f"measured as at or below random in aggregate, so treat "
                        f"it accordingly."
                    )
            mem = sv.group_members(lvl_s, grp_s, scored, picks=df)
            show = mem.copy()
            # group_members() already supplies `held` as a bool; overwrite it
            # in place rather than insert(), which raises on an existing
            # column. The `keep` list below does the ordering anyway.
            show["held"] = show["held"].map(lambda b: "●" if b else "")
            keep = [c for c in ["held", "ticker", "rank", "percentile", "score",
                                "eligible_today", "close", "market_cap",
                                "volatility_20", "momentum_20"]
                    if c in show.columns]
            show = show[keep]
            for c in ("percentile", "score"):
                if c in show:
                    show[c] = pd.to_numeric(show[c], errors="coerce").round(4)
            st.dataframe(show, hide_index=True, use_container_width=True,
                         height=min(560, 40 + 28 * len(show)))
            st.caption(
                f"{len(mem)} names in **{grp_s}**, ordered by the model's overall "
                f"rank across the whole eligible universe. `eligible_today` = "
                f"False means the name is not in that date's point-in-time "
                f"universe, so it could not have been bought whatever its score."
            )

    if hist:
        st.divider()
        st.subheader("Standing tilts, 2007–2019")
        st.caption(
            "Mean active weight across **all** windows in the era, so a group "
            "held once at +40pp shows as +40/n — the honest description of a "
            "standing allocation. The frequency column is what separates "
            "\"always a little\" from \"rarely, a lot\"; a large mean built "
            "from three enormous bets is a different animal from a persistent "
            "overweight and should not be read as one."
        )
        tl = sv.tilt_levels(hist)
        st.caption(
            f"Built by `build_sector_tilt.py`, which predates the finer levels "
            f"and stores {len(tl)}: {', '.join(tl)}. Rerun it to add the rest."
        )
        lvl = st.selectbox("Level", tl, key="tilt_hist_level")
        g = hist["levels"][lvl]["nominate"]["groups"][:15]
        st.dataframe(pd.DataFrame([{
            lvl: r["group"],
            "mean active": f"{r['mean_active']:+.2f}pp",
            "held in": f"{r['frequency']:.0%}",
            "largest single bet": f"{r['max_active']:+.1f}pp",
            "windows held": r["n_windows_held"],
        } for r in g]), hide_index=True, use_container_width=True)
        st.caption(
            f"From {hist['levels'][lvl]['nominate']['n_windows']} windows. "
            f"Built by `final/src/build_sector_tilt.py`; rerun it after a "
            f"retrain to refresh."
        )
    else:
        st.info("No out/sector_tilt_history.json yet — run "
                "`python3 final/src/build_sector_tilt.py` to add the historical "
                "comparison.")


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


def render_stock_composite():
    """The factor-composite reset (2026-09-19) -- a TRACKED CANDIDATE, kept
    fully separate from the q75/xrank signals above (different universe,
    different construction, no trained model). Same honesty convention as
    the xrank candidate: shown so its picks can be watched in real time, not
    presented as a validated replacement for the deployed signal."""
    st.warning(
        "**Candidate, not deployed.** Nomination era (2007-2019): +3.75%/yr "
        "excess vs SPY, survives sector-neutralization and leave-one-year-out "
        "cleanly. Hold-out (2020-2026), confirmed once: +1.85%/yr excess vs "
        "SPY, but **fails leave-one-year-out** -- only 2 of 7 hold-out years "
        "(2020, 2022) are positive, and dropping 2020 alone flips the 7-year "
        "mean to -2.05%/yr. Full write-up: "
        "`final/models/2026-09-19-factor-composite-reset.md`."
    )
    df, meta = cm.get_signal()
    if df is None:
        st.info("No picks generated yet. Run `python3 src/current_signal_composite.py` "
               "(after `src/reset2026/downcap_universe.py`, `quality_factors.py` and "
               "`build_panel.py` are up to date).")
        return

    c1, c2, c3 = st.columns(3)
    c1.metric("As of", meta["as_of_date"])
    c2.metric("Positions", meta["n_picks"])
    c3.metric("Eligible universe (cap150 tier)", f"{meta['n_eligible_universe']:,}")

    st.write("**Construction:** " + meta["construction"])
    with st.expander("The 9 factors and their signs (zero fitted parameters)"):
        st.json(meta["factors"])

    st.dataframe(
        df[["ticker", "sector", "close", "market_cap", "volatility_60",
            "composite_score", "weight"]]
          .style.format({"close": "${:.2f}", "market_cap": "${:,.0f}",
                          "volatility_60": "{:.2%}", "composite_score": "{:.3f}",
                          "weight": "{:.2%}"}),
        use_container_width=True, height=420,
    )
    st.caption(meta["note"])


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
    t1, t2, t3, t4, t5, t6, t7 = st.tabs(
        ["Today's Picks", "Query a Ticker", "Sector Bets", "Model Weights",
         "Backtest & History", "Universe", "Small-Cap Composite (Candidate)"]
    )
    with t1:
        render_stock_pit()
    with t2:
        render_stock_query()
    with t3:
        render_stock_sectors()
    with t4:
        render_stock_weights()
    with t5:
        render_stock_backtest()
    with t6:
        render_stock_universe()
    with t7:
        render_stock_composite()
    with t6:
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
