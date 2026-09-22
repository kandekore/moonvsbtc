"""
app.py -- Streamlit dashboard for "BTC vs Moon".

Run with:
    .venv/bin/streamlit run app.py

Explores whether full moons mark local tops and new moons mark local bottoms
in Bitcoin, measures the average signed lag (+/- spread), projects that forward
to predict upcoming turning points, and - in the Track record tab - scores every
past moon against what was expected of it at the time.

Layout
------
The page is organised as tabs rather than one long scroll: Overview, Chart,
Track record, Upcoming, Distributions, Data. Everything is computed once from a
single ``run_analysis`` call; the tabs only choose what to show.
"""

from __future__ import annotations

import datetime as _dt
import math

import pandas as pd
import plotly.graph_objects as go
import streamlit as st

import moon_engine as me
from btcmoon.research.track_record import (
    build_track_record, placebo_baseline, track_record_frame,
    track_record_summary,
)

# ---------------------------------------------------------------------------
# Page config + theme colours
# ---------------------------------------------------------------------------
st.set_page_config(page_title="BTC vs Moon", page_icon="🌕", layout="wide")

C_PRICE = "#e8e8ea"
C_FULL = "#ffd54a"      # full moon / tops
C_NEW = "#5a9bff"       # new moon / bottoms
C_HIGH = "#ff6b6b"      # swing highs
C_LOW = "#4ecb8d"       # swing lows
C_PRED_TOP = "rgba(255, 213, 74, 0.18)"
C_PRED_BOT = "rgba(90, 155, 255, 0.18)"
C_HIT = "#4ecb8d"
C_MISS = "#ff6b6b"

st.markdown(
    """
    <style>
      .block-container {padding-top: 1.6rem; max-width: 1500px;}
      h1 {font-weight: 700;}
      [data-testid="stMetricValue"] {font-size: 1.6rem;}
      [data-testid="stTabs"] button {font-size: 1rem;}
    </style>
    """,
    unsafe_allow_html=True,
)


# ---------------------------------------------------------------------------
# Data loading (cached)
# ---------------------------------------------------------------------------
@st.cache_data(ttl=60 * 60, show_spinner="Downloading BTC price history…")
def load_price(start: str) -> pd.DataFrame:
    """Daily CLOSE only - the input the frozen website methodology expects."""
    return me.fetch_btc(start=start)


@st.cache_data(ttl=60 * 60, show_spinner="Downloading intraday highs and lows…")
def load_ohlc(start: str) -> tuple[pd.DataFrame | None, str]:
    """Daily OHLC, for finding the ACTUAL high or low rather than the closing one.

    A close can miss a spike: the lowest price traded in a window often falls on
    a different day from the lowest close.

    Returns ``(frame, reason)``. On failure the frame is None and ``reason``
    carries the real error - swallowing it, as an earlier version did, left the
    banner saying "unavailable" with no way to find out why.

    Two sources are tried, because they fail independently: the cached adapter,
    then a direct download shaped like the close-only fetch that is already
    known to work here.
    """
    reasons = []
    try:
        from btcmoon.market_data import get_ohlc_history

        df = get_ohlc_history(start=start)
        if df is not None and not df.empty and {"high", "low"} <= set(df.columns):
            return df, ""
        reasons.append(
            f"adapter returned {0 if df is None else len(df)} rows with columns "
            f"{sorted(df.columns) if df is not None else 'n/a'}"
        )
    except Exception as exc:
        reasons.append(f"adapter: {type(exc).__name__}: {exc}")

    # Fallback: same call shape as the close-only fetch, keeping high/low.
    try:
        import yfinance as yf

        raw = yf.download(
            "BTC-USD", start=start,
            end=(_dt.date.today() + _dt.timedelta(days=1)).isoformat(),
            progress=False, auto_adjust=True,
        )
        if raw is None or raw.empty:
            raise ValueError("empty response")
        if isinstance(raw.columns, pd.MultiIndex):
            raw.columns = [c[0] for c in raw.columns]
        raw.columns = [str(c).lower() for c in raw.columns]
        if not {"high", "low", "close"} <= set(raw.columns):
            raise ValueError(f"no high/low in {sorted(raw.columns)}")
        df = raw[["high", "low", "close"]].astype(float)
        df.index = pd.to_datetime(df.index).tz_localize(None).normalize()
        df = df[~df.index.duplicated(keep="last")].sort_index().dropna()
        return df, ""
    except Exception as exc:
        reasons.append(f"direct: {type(exc).__name__}: {exc}")

    return None, " | ".join(reasons)


# ---------------------------------------------------------------------------
# Sidebar controls
# ---------------------------------------------------------------------------
st.sidebar.title("🌕 Controls")

_START_MAP = {
    "Max (2014→)": "2014-09-17",
    "Last 4 years": (_dt.date.today() - _dt.timedelta(days=365 * 4)).isoformat(),
    "Last 2 years": (_dt.date.today() - _dt.timedelta(days=365 * 2)).isoformat(),
}
start_choice = st.sidebar.selectbox("Price history", options=list(_START_MAP), index=2)
start = _START_MAP[start_choice]

st.sidebar.subheader("Swing-pivot sensitivity")
distance = st.sidebar.slider(
    "Min days between pivots", 3, 30, 30,
    help="Larger = fewer, more significant pivots. Default 30 = one per lunar cycle.",
)
prominence_pct = st.sidebar.slider(
    "Min prominence (% of price)", 0.5, 15.0, 15.0, step=0.5,
    help="How far a swing must stand out from its surroundings. Default 15% = only major swings.",
)

st.sidebar.subheader("Matching & prediction")
max_lag = st.sidebar.slider(
    "Max moon→pivot lag (days)", 5, 20, 14,
    help="A moon only matches a pivot within this many days. Default 14 ≈ half a "
    "lunar cycle, the point where the moon flips to the opposite phase.",
)
horizon_days = st.sidebar.slider(
    "Prediction horizon (days)", 30, 365, 120, step=30,
)

log_scale = st.sidebar.checkbox("Log price axis", value=True)

st.sidebar.caption(
    "The defaults reproduce the published website methodology. Moving a slider "
    "explores a different rule — it does not change any frozen protocol."
)

# ---------------------------------------------------------------------------
# Run analysis (always on FULL history — the view range only zooms the chart)
# ---------------------------------------------------------------------------
price = load_price(start)
ohlc, ohlc_error = load_ohlc(start)
res = me.run_analysis(
    distance=distance,
    prominence_pct=prominence_pct,
    max_lag=max_lag,
    horizon_days=horizon_days,
    price_df=price,
)

# ---------------------------------------------------------------------------
# View controls
# ---------------------------------------------------------------------------
st.sidebar.subheader("View")

data_min = price.index.min().date()
last_price_date = price.index.max().date()
# include the prediction horizon so future bands are visible in the default view
data_max = max(last_price_date, _dt.date.today() + _dt.timedelta(days=horizon_days))
default_start = max(data_min, last_price_date - _dt.timedelta(days=365))

view_range = st.sidebar.date_input(
    "Chart date range",
    value=(default_start, data_max),
    min_value=data_min,
    max_value=data_max,
    help="Zoom the chart to a date window. Analysis still uses full history.",
)
# date_input returns a tuple once both ends are picked; guard the mid-edit state
if isinstance(view_range, (tuple, list)) and len(view_range) == 2:
    view_start, view_end = view_range
else:
    view_start, view_end = default_start, data_max
view_start_ts = pd.Timestamp(view_start)
view_end_ts = pd.Timestamp(view_end)

top_stats, bottom_stats = res.top_stats, res.bottom_stats
today_ts = pd.Timestamp(_dt.date.today())


# ---------------------------------------------------------------------------
# Header
# ---------------------------------------------------------------------------
st.title("🌕 Bitcoin vs the Moon")
st.caption(
    "Testing whether **full moons mark local tops** and **new moons mark local "
    "bottoms** — measuring the average lag, projecting it forward, and scoring "
    "every past call against what actually happened."
)

tab_overview, tab_chart, tab_record, tab_upcoming, tab_dist, tab_data = st.tabs(
    ["Overview", "Chart", "Track record", "Upcoming", "Distributions", "Data"]
)


def _fmt_offset(stats: me.OffsetStats) -> tuple[str, str]:
    if stats.n == 0:
        return "—", "no matches"
    when = "after" if stats.mean >= 0 else "before"
    return (
        f"{abs(stats.mean):.1f} d {when}",
        f"±{stats.std:.1f} d · median {stats.median:+.0f} · n={stats.n}",
    )


# ===========================================================================
# Overview
# ===========================================================================
with tab_overview:
    k1, k2, k3, k4 = st.columns(4)
    v, d = _fmt_offset(top_stats)
    k1.metric("Top vs Full Moon", v, d, delta_color="off")
    v, d = _fmt_offset(bottom_stats)
    k2.metric("Bottom vs New Moon", v, d, delta_color="off")
    k3.metric("Swing highs / lows", f"{len(res.swing_highs)} / {len(res.swing_lows)}")
    k4.metric(
        "Last close",
        f"${price['close'].iloc[-1]:,.0f}",
        f"{price.index.min().date()} → {price.index.max().date()}",
        delta_color="off",
    )

    # An active window is the single most decision-relevant thing on the page,
    # so it is surfaced here rather than buried in the Upcoming tab.
    if not res.predictions.empty:
        active = res.predictions[res.predictions["status"] == "active"]
        if active.empty:
            nxt = res.predictions[res.predictions["status"] == "upcoming"].head(1)
            if not nxt.empty:
                r = nxt.iloc[0]
                days = (r["predicted_date"] - today_ts).days
                st.info(
                    f"**No window is open today.** Next: {r['moon_type']} moon on "
                    f"{r['moon_date'].date()} → predicted {r['kind'].lower()} around "
                    f"**{r['predicted_date'].date()}** ({days} days away)."
                )
        else:
            for _, r in active.iterrows():
                st.success(
                    f"**Window open now:** {r['moon_type']} moon on {r['moon_date'].date()} "
                    f"→ predicted {r['kind'].lower()} around **{r['predicted_date'].date()}** "
                    f"(window {r['window_start'].date()} → {r['window_end'].date()})."
                )

    st.divider()
    st.subheader("How this reads")
    st.markdown(
        f"""
- **{top_stats.summary}**
- **{bottom_stats.summary}**

A mean near 0 with a wide σ means turning points scatter fairly symmetrically
around the moon — that is a *null* result, not a positive one. A clearly positive
mean supports the "tops lag the full moon" idea.

The **Track record** tab is the honest test: it scores each past moon against the
average that was available *before* it, so the hit rate is not flattered by
hindsight. Use the sidebar sliders to see how quickly the pattern falls apart
when the pivot definition changes.
"""
    )
    st.warning(
        "Educational / exploratory only. Lunar phases have no established causal "
        "effect on markets; this is pattern-fitting on historical data and is not "
        "financial advice.",
        icon="⚠️",
    )


# ===========================================================================
# Chart
# ===========================================================================
def _price_on(dates):
    """Price value on-or-before each date (for placing moon markers on the line)."""
    ser = price["close"]
    return [float(ser.asof(pd.Timestamp(d))) for d in dates]


def build_price_figure() -> go.Figure:
    fig = go.Figure()
    fig.add_trace(
        go.Scatter(
            x=price.index, y=price["close"], mode="lines", name="BTC close",
            line=dict(color=C_PRICE, width=1.2),
            hovertemplate="%{x|%Y-%m-%d}<br>$%{y:,.0f}<extra></extra>",
        )
    )
    fig.add_trace(
        go.Scatter(
            x=res.swing_highs, y=price.loc[res.swing_highs, "close"], mode="markers",
            name="Swing high", marker=dict(color=C_HIGH, size=6, symbol="triangle-down"),
            hovertemplate="High %{x|%Y-%m-%d}<br>$%{y:,.0f}<extra></extra>",
        )
    )
    fig.add_trace(
        go.Scatter(
            x=res.swing_lows, y=price.loc[res.swing_lows, "close"], mode="markers",
            name="Swing low", marker=dict(color=C_LOW, size=6, symbol="triangle-up"),
            hovertemplate="Low %{x|%Y-%m-%d}<br>$%{y:,.0f}<extra></extra>",
        )
    )
    fig.add_trace(
        go.Scatter(
            x=[pd.Timestamp(m) for m in res.full_moons], y=_price_on(res.full_moons),
            mode="markers", name="Full moon",
            marker=dict(color=C_FULL, size=9, symbol="circle",
                        line=dict(width=1, color="#222")),
            hovertemplate="🌕 Full %{x|%Y-%m-%d}<extra></extra>",
        )
    )
    fig.add_trace(
        go.Scatter(
            x=[pd.Timestamp(m) for m in res.new_moons], y=_price_on(res.new_moons),
            mode="markers", name="New moon",
            marker=dict(color=C_NEW, size=9, symbol="circle-open",
                        line=dict(width=2, color=C_NEW)),
            hovertemplate="🌑 New %{x|%Y-%m-%d}<extra></extra>",
        )
    )

    for _, row in res.predictions.iterrows():
        fill = C_PRED_TOP if row["kind"] == "Top" else C_PRED_BOT
        line = C_FULL if row["kind"] == "Top" else C_NEW
        fig.add_vrect(x0=row["window_start"], x1=row["window_end"],
                      fillcolor=fill, line_width=0, layer="below")
        fig.add_vline(x=row["predicted_date"], line=dict(color=line, width=1, dash="dot"))

    fig.add_vline(x=today_ts, line=dict(color="#888", width=1, dash="dash"))

    # Fit the y-axis to whatever price falls inside the chosen view window so a
    # zoomed-in range isn't squashed against the full-history min/max.
    visible = price.loc[
        (price.index >= view_start_ts) & (price.index <= view_end_ts), "close"
    ]
    if not visible.empty:
        lo_v, hi_v = float(visible.min()), float(visible.max())
        pad = (hi_v - lo_v) * 0.08 or hi_v * 0.05
        if log_scale:
            y_range = [math.log10(max(lo_v - pad, 1)), math.log10(hi_v + pad)]
        else:
            y_range = [max(lo_v - pad, 0), hi_v + pad]
    else:
        y_range = None

    fig.update_layout(
        template="plotly_dark",
        height=560,
        margin=dict(l=10, r=10, t=30, b=10),
        legend=dict(orientation="h", yanchor="bottom", y=1.01, xanchor="left", x=0),
        hovermode="x unified",
        yaxis=dict(title="Price (USD)", type="log" if log_scale else "linear",
                   range=y_range, autorange=y_range is None),
        xaxis=dict(
            title=None,
            range=[view_start_ts, view_end_ts],
            rangeslider=dict(visible=True, thickness=0.06),
            rangeselector=dict(
                buttons=[
                    dict(count=1, label="1M", step="month", stepmode="backward"),
                    dict(count=3, label="3M", step="month", stepmode="backward"),
                    dict(count=6, label="6M", step="month", stepmode="backward"),
                    dict(count=1, label="YTD", step="year", stepmode="todate"),
                    dict(count=1, label="1Y", step="year", stepmode="backward"),
                    dict(step="all", label="All"),
                ],
                bgcolor="#222", activecolor="#555", font=dict(color="#ddd"),
            ),
        ),
    )
    return fig


with tab_chart:
    st.plotly_chart(build_price_figure(), use_container_width=True)
    st.caption(
        "Shaded bands = predicted future turning-point windows (moon date + mean "
        "offset ± 1 std). Dashed grey line = today. Drag to zoom, use the buttons "
        "or the range slider, or set an exact range in the sidebar."
    )


# ===========================================================================
# Track record  -- what we expected vs what actually happened
# ===========================================================================
with tab_record:
    st.subheader("Track record: expected vs actual")
    st.caption(
        "Every past moon, scored against the offset that was available before it. "
        "This is the half the prediction table cannot show, because a window that "
        "has elapsed is dropped from it."
    )

    c0, c1, c2 = st.columns([2, 3, 2])
    window_mode = c0.radio(
        "Search window",
        ["Forward only (T0 → T+n)", "Symmetric (±n)"],
        help=(
            "Forward only looks from the moon onwards, as the pre-registered "
            "New-Moon protocol does (T0:T+3). Symmetric also looks BACK up to n "
            "days — that is what the legacy website matcher does, but it spans "
            "most of a lunar month, so it can pick up an extreme belonging to the "
            "PREVIOUS cycle and credit it to this moon."
        ),
    )
    mode_key = "forward" if window_mode.startswith("Forward") else "symmetric"
    measure = c1.radio(
        "What counts as 'the turn'",
        ["Local extreme (always measurable)", "Significant pivot (rare)"],
        help=(
            "Local extreme = the highest/lowest close within ±max-lag of the moon. "
            "It always exists, so every moon gets a measurement. "
            "Significant pivot = the frozen website detector, which finds roughly "
            "one pivot per 91 days — most moons cannot match one at all."
        ),
    )
    measure_key = "extreme" if measure.startswith("Local") else "pivot"
    basis = c2.radio(
        "Expected offset from", ["walk-forward", "full-sample"], horizontal=True,
        help=(
            "walk-forward uses only the moons BEFORE each event — what you could "
            "actually have known at the time. full-sample uses the average over all "
            "history, which is hindsight and will look better than it was."
        ),
    )

    entries = build_track_record(res, basis=basis.replace("-", "_"),
                                 max_lag=max_lag, ohlc=ohlc,
                                 window_mode=mode_key)
    source = next((e.extreme_source for e in entries if e.extreme_source), None)
    if measure_key == "extreme":
        if source == "close":
            st.error(
                "**Intraday highs and lows are unavailable, so these extremes were "
                "found on CLOSING prices.** A close can miss a spike entirely — the "
                "lowest price traded in a window often falls on a different day from "
                "the lowest close. Treat the dates below as approximate.",
                icon="⚠️",
            )
            with st.expander("Why — and how to fix it", expanded=True):
                st.code(ohlc_error or "no reason recorded", language="text")
                st.markdown(
                    "`.cache/` is git-ignored, so a fresh deployment has no OHLC "
                    "cache and must fetch live. Check outbound HTTPS and that the "
                    "working directory is writable:\n\n"
                    "```bash\n"
                    "cd ~/moonvsbtc\n"
                    ".venv/bin/python -c \"from btcmoon.market_data import "
                    "get_ohlc_history as g; d=g(); print(d.shape, list(d.columns))\"\n"
                    "ls -la .cache/\n"
                    "```"
                )
        else:
            st.caption(
                "Extremes are the **actual intraday high (tops) / low (bottoms)** — "
                "the highest and lowest prices traded, not closing prices. The "
                "significant-pivot measure and the headline offsets above remain on "
                "closes, as the frozen website methodology defines them."
            )
    summary = track_record_summary(entries, measure=measure_key)
    fm, nm = summary["full_moon_to_high"], summary["new_moon_to_low"]

    if basis == "full-sample":
        st.warning(
            "Full-sample basis: each moon is scored against an average that includes "
            "that moon. Treat the accuracy below as an upper bound, not a record.",
            icon="⚠️",
        )

    m1, m2, m3, m4 = st.columns(4)
    m1.metric(
        "Full Moon → high",
        f"{fm['hit_rate_pct']:.0f}% in window" if fm["hit_rate_pct"] is not None else "—",
        f"MAE {fm['mean_absolute_error_days']} d · n={fm['n_scored']}"
        if fm["mean_absolute_error_days"] is not None else "not enough data",
        delta_color="off",
    )
    m2.metric(
        "New Moon → low",
        f"{nm['hit_rate_pct']:.0f}% in window" if nm["hit_rate_pct"] is not None else "—",
        f"MAE {nm['mean_absolute_error_days']} d · n={nm['n_scored']}"
        if nm["mean_absolute_error_days"] is not None else "not enough data",
        delta_color="off",
    )
    m3.metric(
        "Measured", f"{fm['n_scored'] + nm['n_scored']} / {fm['n_moons'] + nm['n_moons']}",
        "moons with a usable measurement", delta_color="off",
    )
    if measure_key == "extreme":
        m4.metric(
            "Of those, real turns",
            f"{fm['n_extreme_was_turning_point'] + nm['n_extreme_was_turning_point']}",
            f"{fm['n_extreme_at_window_edge'] + nm['n_extreme_at_window_edge']} "
            f"sat on the window edge (trending, not turning)", delta_color="off",
        )
    else:
        m4.metric(
            "Undecidable", f"{fm['n_undecidable'] + nm['n_undecidable']}",
            "no significant pivot within the lag window", delta_color="off",
        )

    # --- the number that actually matters ---------------------------------
    if measure_key == "extreme":
        st.markdown("#### Does the Moon beat a random date?")
        base = placebo_baseline(res, max_lag=max_lag, n_trials=1000, ohlc=ohlc,
                                window_mode=mode_key)
        bc = st.columns(2)
        for col, (key, name) in zip(bc, (("full_moon_to_high", "Full Moon → high"),
                                         ("new_moon_to_low", "New Moon → low"))):
            stat = base[key]
            if stat["edge_pct"] is None:
                col.info(f"{name}: not enough data for a baseline.")
                continue
            verdict = (
                "Distinguishable from chance." if stat["significant"]
                else "**Not distinguishable from chance.**"
            )
            col.markdown(
                f"**{name}** — window {stat['window_days'][0]:+d} to "
                f"{stat['window_days'][1]:+d} d\n\n"
                f"- Real moons: **{stat['real_hit_rate_pct']}%** (n={stat['n_real']})\n"
                f"- Random dates: **{stat['placebo_hit_rate_pct']}%** (n={stat['n_trials']})\n"
                f"- Edge: **{stat['edge_pct']:+.1f} ± {stat['edge_se_pct']:.1f}** pp\n\n"
                f"{verdict}"
            )
        st.caption(
            "A local extreme always exists inside the window, so the raw hit rate "
            "above has a large floor that has nothing to do with the Moon. The edge "
            "over random dates — scored through the identical measurement, with the "
            "same window — is the only figure here that tests the hypothesis."
        )

    st.divider()

    # --- the table ---------------------------------------------------------
    f1, f2, f3 = st.columns([2, 3, 3])
    phase_pick = f1.radio("Phase", ["Both", "Full", "New"], horizontal=True)
    hide_edge = f2.checkbox(
        "Hide extremes on the window boundary", value=False,
        help="Where |offset| is at the edge, price trended through the window "
             "rather than turning in it.",
    ) if measure_key == "extreme" else False
    turns_only = f3.checkbox(
        "Only genuine turns (strict 7-day rule)", value=False,
        help="The extreme must be strictly beyond the 3 bars either side of it "
             "on intraday prices — a real pivot, not just the window maximum.",
    ) if measure_key == "extreme" else False

    df = track_record_frame(entries)
    if phase_pick != "Both":
        df = df[df["moon_type"] == phase_pick]
    df = df[df[f"{measure_key}_error_days"].notna()]
    if hide_edge:
        df = df[~df["extreme_at_window_edge"].fillna(False)]
    if turns_only:
        df = df[df["extreme_is_turning_point"].fillna(False)]

    if df.empty:
        st.info("No scored entries for this combination of filters.")
    else:
        view = pd.DataFrame({
            "Moon": df["moon_type"],
            "Moon date": df["moon_date"],
            "Expected": df[f"expected_{measure_key}_date"],
            "Actual": df[f"{measure_key}_date"],
            "Offset": df[f"{measure_key}_offset_days"],
            "Error (d)": df[f"{measure_key}_error_days"],
            "In window": df[f"{measure_key}_hit"].map({True: "✅ hit", False: "❌ miss"}),
        })
        if measure_key == "extreme":
            view["Real turn?"] = df["extreme_is_turning_point"].map(
                {True: "✅ strict turn", False: "— no turn"})
            view["Edge of window?"] = df["extreme_at_window_edge"].map(
                {True: "⚠️ trending", False: ""})
            view["Price $"] = df["extreme_price"]
            view["From"] = df["extreme_source"]
        else:
            view["Price $"] = df["pivot_close"]

        st.dataframe(
            view, use_container_width=True, hide_index=True, height=420,
            column_config={
                "Offset": st.column_config.NumberColumn(format="%+d d"),
                "Error (d)": st.column_config.NumberColumn(
                    format="%+.2f",
                    help="actual − expected. Positive = the turn came later than expected."),
                "Price $": st.column_config.NumberColumn(format="$%.0f"),
            },
        )
        st.download_button(
            "Download track record (CSV)", track_record_frame(entries).to_csv(index=False),
            file_name=f"btc_moon_track_record_{measure_key}_{basis}.csv", mime="text/csv",
        )

        fig_err = go.Figure()
        for phase, colour in (("Full", C_FULL), ("New", C_NEW)):
            sub = df[df["moon_type"] == phase]
            if sub.empty:
                continue
            fig_err.add_trace(go.Scatter(
                x=pd.to_datetime(sub["moon_date"]), y=sub[f"{measure_key}_error_days"],
                mode="markers", name=f"{phase} moon",
                marker=dict(color=colour, size=8, line=dict(
                    width=1.5,
                    color=[C_HIT if h else C_MISS for h in sub[f"{measure_key}_hit"]])),
                hovertemplate="%{x|%Y-%m-%d}<br>error %{y:+.1f} d<extra></extra>",
            ))
        fig_err.add_hline(y=0, line=dict(color="#aaa", width=1, dash="dash"))
        fig_err.update_layout(
            template="plotly_dark", height=340, margin=dict(l=10, r=10, t=40, b=10),
            title="Timing error over time (0 = landed exactly on the expected day)",
            yaxis_title="error (days)", xaxis_title=None,
            legend=dict(orientation="h", yanchor="bottom", y=1.02, x=0),
        )
        st.plotly_chart(fig_err, use_container_width=True)

    if mode_key == "symmetric":
        st.info(
            "**Symmetric window.** A ±%d day window spans most of a synodic "
            "month, so the extreme it finds may belong to the previous cycle — "
            "e.g. the 12 Aug 2026 New Moon returns a low 9 days *before* it, "
            "which really belongs to the preceding phase. Switch to forward-only "
            "to measure the way the pre-registered protocol does." % max_lag,
            icon="ℹ️",
        )

    with st.expander("How to read this — two different questions"):
        st.markdown(
            f"""
**Local extreme** answers *where was the turn?* There is always a highest and a
lowest close inside a ±{max_lag} day window, so every moon gets a measurement.
That is why this view is populated where the old one said "no data".

**Significant pivot** answers *was it a real turning point?* The frozen website
detector (spacing 30, prominence 15% of median close) finds about one pivot per
91 days, against a moon every 14.8 days — so most moons cannot match one. That
is a property of the detector, not missing data.

**"Real turn?"** applies the protocol's strict 7-day rule to intraday prices:
the HIGH (or LOW) must be strictly beyond the three bars either side. A window
maximum that fails this was not a turn — price was passing through.

**The window-edge warning matters.** {fm['n_extreme_at_window_edge'] + nm['n_extreme_at_window_edge']}
of {fm['n_scored'] + nm['n_scored']} extremes sit on the boundary of the window.
For those, price trended straight through and the true extreme lies outside —
they are not evidence of a lunar turn, and the |offset| histogram piling up at
±{max_lag} is the signature of a trending market, not a lunar one.

**In window** means the actual turn fell inside expected ± 1 standard deviation.
That window is wide, so a hit rate near 50–60% is what chance alone produces —
which is exactly why the placebo comparison above is the only number that tests
the hypothesis.
"""
        )


# ===========================================================================
# Upcoming
# ===========================================================================
with tab_upcoming:
    st.subheader("🔮 Predicted upcoming turning points")
    if res.predictions.empty:
        st.write("No predictions (no matches to base offsets on).")
    else:
        pred_view = res.predictions.copy()
        pred_view["days_away"] = (pred_view["predicted_date"] - today_ts).dt.days
        badge = {"active": "🟢 now", "upcoming": "🔵 upcoming", "passed": "⚪ passed"}
        pred_view["status"] = pred_view["status"].map(badge).fillna(pred_view["status"])
        for c in ("moon_date", "predicted_date", "window_start", "window_end"):
            pred_view[c] = pred_view[c].dt.date
        pred_view = pred_view[
            ["status", "kind", "moon_type", "moon_date",
             "predicted_date", "days_away", "window_start", "window_end"]
        ].rename(columns={
            "status": "Status", "kind": "Type", "moon_type": "Moon",
            "moon_date": "Moon date", "predicted_date": "Predicted",
            "days_away": "Days away", "window_start": "Window start",
            "window_end": "Window end",
        })

        active = pred_view[pred_view["Status"] == "🟢 now"]
        for _, r in active.iterrows():
            st.success(
                f"**We're in an active window now:** {r['Moon']} moon on "
                f"{r['Moon date']} → predicted {r['Type'].lower()} around "
                f"**{r['Predicted']}** (window {r['Window start']} → {r['Window end']})."
            )

        st.dataframe(pred_view, use_container_width=True, hide_index=True)
        st.caption(
            "These are the windows that have not yet fully elapsed. Once one passes "
            "it moves to the **Track record** tab and is scored against what actually "
            "happened."
        )


# ===========================================================================
# Distributions
# ===========================================================================
def _hist(matched: pd.DataFrame, stats: me.OffsetStats, color: str, title: str):
    if matched.empty:
        return go.Figure().update_layout(template="plotly_dark", height=320, title=title)
    fig_h = go.Figure()
    fig_h.add_trace(
        go.Histogram(
            x=matched["offset_days"],
            xbins=dict(start=-max_lag - 0.5, end=max_lag + 0.5, size=1),
            marker_color=color, opacity=0.85, name="offsets",
        )
    )
    fig_h.add_vline(x=0, line=dict(color="#aaa", width=1, dash="dash"))
    fig_h.add_vline(x=stats.mean, line=dict(color="#fff", width=2))
    fig_h.update_layout(
        template="plotly_dark", height=320, bargap=0.05,
        margin=dict(l=10, r=10, t=48, b=10),
        title=(f"{title}<br><sub>mean {stats.mean:+.1f} d · median {stats.median:+.0f} d "
               f"· σ {stats.std:.1f} · n={stats.n}</sub>"),
        xaxis_title="offset (days from moon; − before, + after)",
        yaxis_title="count", showlegend=False,
    )
    return fig_h


with tab_dist:
    st.subheader("How the turning points cluster around the moon")
    hc1, hc2 = st.columns(2)
    hc1.plotly_chart(_hist(res.top_matches, top_stats, C_FULL, "Tops relative to Full Moon"),
                     use_container_width=True)
    hc2.plotly_chart(_hist(res.bottom_matches, bottom_stats, C_NEW, "Bottoms relative to New Moon"),
                     use_container_width=True)
    st.info(
        f"**Reading it:** {top_stats.summary}. {bottom_stats.summary}. "
        "A mean near 0 with a wide σ means turning points scatter fairly symmetrically "
        "around the moon; a clearly positive mean supports the 'tops lag the full moon' "
        "idea. Adjust the pivot sensitivity in the sidebar to see how robust it is."
    )


# ===========================================================================
# Data
# ===========================================================================
with tab_data:
    st.subheader("Daily price with moon-phase and pivot flags")
    full_set = {pd.Timestamp(m).normalize() for m in res.full_moons}
    new_set = {pd.Timestamp(m).normalize() for m in res.new_moons}
    high_set = {pd.Timestamp(d).normalize() for d in res.swing_highs}
    low_set = {pd.Timestamp(d).normalize() for d in res.swing_lows}

    tbl = price.copy()
    tbl["Full moon"] = [d.normalize() in full_set for d in tbl.index]
    tbl["New moon"] = [d.normalize() in new_set for d in tbl.index]
    tbl["Swing high"] = [d.normalize() in high_set for d in tbl.index]
    tbl["Swing low"] = [d.normalize() in low_set for d in tbl.index]
    tbl = tbl.loc[(tbl.index >= view_start_ts) & (tbl.index <= view_end_ts)]

    view_tbl = tbl.reset_index().rename(columns={"index": "Date", "close": "Close $"})
    view_tbl["Date"] = view_tbl["Date"].dt.date
    view_tbl["Close $"] = view_tbl["Close $"].round(2)

    if st.checkbox("Show only moon / pivot days", value=False):
        mask = view_tbl[["Full moon", "New moon", "Swing high", "Swing low"]].any(axis=1)
        view_tbl = view_tbl[mask]

    st.caption(f"{len(view_tbl):,} rows · {view_start} → {view_end} (set the range in the sidebar)")
    st.dataframe(view_tbl, use_container_width=True, hide_index=True, height=420)
    st.download_button(
        "Download this table (CSV)", view_tbl.to_csv(index=False),
        file_name="btc_moon_daily.csv", mime="text/csv",
    )

    st.divider()
    st.subheader("Matched historical pairs (the data behind the stats)")
    sub_top, sub_bot = st.tabs(["Tops (Full moon)", "Bottoms (New moon)"])
    for sub_tab, matched, name in (
        (sub_top, res.top_matches, "tops"), (sub_bot, res.bottom_matches, "bottoms")
    ):
        with sub_tab:
            if matched.empty:
                st.write("No matches.")
                continue
            mview = matched.copy()
            mview["moon_date"] = mview["moon_date"].dt.date
            mview["pivot_date"] = mview["pivot_date"].dt.date
            mview["pivot_price"] = mview["pivot_price"].round(0)
            mview = mview.rename(columns={
                "moon_type": "Moon", "moon_date": "Moon date",
                "pivot_date": "Pivot date", "offset_days": "Offset (d)",
                "pivot_price": "Pivot $",
            })
            st.dataframe(mview, use_container_width=True, hide_index=True)
            st.download_button(
                "Download CSV", matched.to_csv(index=False),
                file_name=f"{name}.csv", mime="text/csv", key=f"dl_{name}",
            )


st.caption(
    "⚠️ Educational / exploratory only. Lunar phases have no established causal effect "
    "on markets; this is pattern-fitting on historical data and not financial advice."
)

st.markdown(
    """
    <hr style="margin-top:2rem;margin-bottom:0.5rem;border:none;border-top:1px solid #333;">
    <div style="text-align:center;color:#888;font-size:0.85rem;padding-bottom:1rem;">
      Developed by <a href="https://darrenk.uk" target="_blank" rel="noopener noreferrer"
      style="color:#ffd54a;text-decoration:none;font-weight:600;">Darren Kandekore</a>
    </div>
    """,
    unsafe_allow_html=True,
)
