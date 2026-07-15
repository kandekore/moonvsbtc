"""
app.py -- Streamlit dashboard for "BTC vs Moon".

Run with:
    .venv/bin/streamlit run app.py

Explores whether full moons mark local tops and new moons mark local bottoms
in Bitcoin, measures the average signed lag (+/- spread), and projects that
forward to predict upcoming turning points.
"""

from __future__ import annotations

import datetime as _dt

import numpy as np
import pandas as pd
import plotly.graph_objects as go
import streamlit as st

import moon_engine as me

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

st.markdown(
    """
    <style>
      .block-container {padding-top: 2rem; max-width: 1500px;}
      h1 {font-weight: 700;}
      [data-testid="stMetricValue"] {font-size: 1.6rem;}
    </style>
    """,
    unsafe_allow_html=True,
)


# ---------------------------------------------------------------------------
# Data loading (cached)
# ---------------------------------------------------------------------------
@st.cache_data(ttl=60 * 60, show_spinner="Downloading BTC price history…")
def load_price(start: str) -> pd.DataFrame:
    return me.fetch_btc(start=start)


# ---------------------------------------------------------------------------
# Sidebar controls
# ---------------------------------------------------------------------------
st.sidebar.title("🌕 Controls")

start_choice = st.sidebar.selectbox(
    "Price history",
    options={
        "Max (2014→)": "2014-09-17",
        "Last 4 years": (_dt.date.today() - _dt.timedelta(days=365 * 4)).isoformat(),
        "Last 2 years": (_dt.date.today() - _dt.timedelta(days=365 * 2)).isoformat(),
    }.keys(),
    index=2,
)
start_map = {
    "Max (2014→)": "2014-09-17",
    "Last 4 years": (_dt.date.today() - _dt.timedelta(days=365 * 4)).isoformat(),
    "Last 2 years": (_dt.date.today() - _dt.timedelta(days=365 * 2)).isoformat(),
}
start = start_map[start_choice]

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


# ---------------------------------------------------------------------------
# Run analysis (always on FULL history — the view range only zooms the chart)
# ---------------------------------------------------------------------------
price = load_price(start)
res = me.run_analysis(
    distance=distance,
    prominence_pct=prominence_pct,
    max_lag=max_lag,
    horizon_days=horizon_days,
    price_df=price,
)

# ---------------------------------------------------------------------------
# View controls (zoom / date range / display mode)
# ---------------------------------------------------------------------------
st.sidebar.subheader("View")
display_mode = st.sidebar.radio(
    "Display", ["Chart", "Table", "Both"], index=0, horizontal=True,
)

data_min = price.index.min().date()
# default the view to the last 12 months so it opens zoomed-in, not all-time
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

# ---------------------------------------------------------------------------
# Header + KPIs
# ---------------------------------------------------------------------------
st.title("🌕 Bitcoin vs the Moon")
st.caption(
    "Testing whether **full moons mark local tops** and **new moons mark local "
    "bottoms** — and measuring the average lag to predict future turning points."
)

t, b = res.top_stats, res.bottom_stats
k1, k2, k3, k4 = st.columns(4)


def _fmt_offset(stats: me.OffsetStats) -> tuple[str, str]:
    if stats.n == 0:
        return "—", "no matches"
    when = "after" if stats.mean >= 0 else "before"
    return f"{abs(stats.mean):.1f} d {when}", f"±{stats.std:.1f} d · median {stats.median:+.0f} · n={stats.n}"


v, d = _fmt_offset(t)
k1.metric("Top vs Full Moon", v, d, delta_color="off")
v, d = _fmt_offset(b)
k2.metric("Bottom vs New Moon", v, d, delta_color="off")
k3.metric("Swing highs / lows", f"{len(res.swing_highs)} / {len(res.swing_lows)}")
k4.metric(
    "Price range",
    f"${price['close'].iloc[-1]:,.0f}",
    f"{price.index.min().date()} → {price.index.max().date()}",
    delta_color="off",
)

st.divider()

# ---------------------------------------------------------------------------
# Main price chart
# ---------------------------------------------------------------------------
fig = go.Figure()

fig.add_trace(
    go.Scatter(
        x=price.index, y=price["close"], mode="lines", name="BTC close",
        line=dict(color=C_PRICE, width=1.2), hovertemplate="%{x|%Y-%m-%d}<br>$%{y:,.0f}<extra></extra>",
    )
)

# swing pivots
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


def _price_on(dates):
    """Price value on-or-before each date (for placing moon markers on the line)."""
    ser = price["close"]
    return [float(ser.asof(pd.Timestamp(d))) for d in dates]


# moon markers along the price line
fig.add_trace(
    go.Scatter(
        x=[pd.Timestamp(m) for m in res.full_moons], y=_price_on(res.full_moons),
        mode="markers", name="Full moon",
        marker=dict(color=C_FULL, size=9, symbol="circle", line=dict(width=1, color="#222")),
        hovertemplate="🌕 Full %{x|%Y-%m-%d}<extra></extra>",
    )
)
fig.add_trace(
    go.Scatter(
        x=[pd.Timestamp(m) for m in res.new_moons], y=_price_on(res.new_moons),
        mode="markers", name="New moon",
        marker=dict(color=C_NEW, size=9, symbol="circle-open", line=dict(width=2, color=C_NEW)),
        hovertemplate="🌑 New %{x|%Y-%m-%d}<extra></extra>",
    )
)

# future prediction bands
for _, row in res.predictions.iterrows():
    fill = C_PRED_TOP if row["kind"] == "Top" else C_PRED_BOT
    line = C_FULL if row["kind"] == "Top" else C_NEW
    fig.add_vrect(
        x0=row["window_start"], x1=row["window_end"],
        fillcolor=fill, line_width=0, layer="below",
    )
    fig.add_vline(x=row["predicted_date"], line=dict(color=line, width=1, dash="dot"))

# mark "today"
today_ts = pd.Timestamp(_dt.date.today())
fig.add_vline(x=today_ts, line=dict(color="#888", width=1, dash="dash"))

# fit the y-axis to whatever price falls inside the chosen view window so a
# zoomed-in range isn't squashed against the full-history min/max.
visible = price.loc[(price.index >= view_start_ts) & (price.index <= view_end_ts), "close"]
if not visible.empty:
    lo_v, hi_v = float(visible.min()), float(visible.max())
    pad = (hi_v - lo_v) * 0.08 or hi_v * 0.05
    if log_scale:
        import math
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
    yaxis=dict(
        title="Price (USD)", type="log" if log_scale else "linear",
        range=y_range, autorange=y_range is None,
    ),
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

if display_mode in ("Chart", "Both"):
    st.plotly_chart(fig, use_container_width=True)
    st.caption(
        "Shaded bands = predicted future turning-point windows (moon date + mean offset ± 1 std). "
        "Dashed grey line = today. Drag on the chart to zoom, use the buttons or the "
        "range slider beneath it, or set an exact range in the sidebar."
    )

# ---------------------------------------------------------------------------
# Data table (daily price with moon-phase + pivot flags), filtered to the view
# ---------------------------------------------------------------------------
if display_mode in ("Table", "Both"):
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

    only_events = st.checkbox("Show only moon / pivot days", value=False)
    if only_events:
        mask = view_tbl[["Full moon", "New moon", "Swing high", "Swing low"]].any(axis=1)
        view_tbl = view_tbl[mask]

    st.caption(f"{len(view_tbl):,} rows · {view_start} → {view_end}")
    st.dataframe(view_tbl, use_container_width=True, hide_index=True, height=420)
    st.download_button(
        "Download this table (CSV)", view_tbl.to_csv(index=False),
        file_name="btc_moon_daily.csv", mime="text/csv",
    )

st.divider()

# ---------------------------------------------------------------------------
# Offset distributions
# ---------------------------------------------------------------------------
st.subheader("How the turning points cluster around the moon")

hc1, hc2 = st.columns(2)


def _hist(matched: pd.DataFrame, stats: me.OffsetStats, color: str, title: str):
    if matched.empty:
        return go.Figure().update_layout(template="plotly_dark", height=320, title=title)
    o = matched["offset_days"]
    fig_h = go.Figure()
    fig_h.add_trace(
        go.Histogram(
            x=o, xbins=dict(start=-max_lag - 0.5, end=max_lag + 0.5, size=1),
            marker_color=color, opacity=0.85, name="offsets",
        )
    )
    fig_h.add_vline(x=0, line=dict(color="#aaa", width=1, dash="dash"))
    fig_h.add_vline(x=stats.mean, line=dict(color="#fff", width=2))
    fig_h.update_layout(
        template="plotly_dark", height=320, bargap=0.05,
        margin=dict(l=10, r=10, t=48, b=10),
        title=f"{title}<br><sub>mean {stats.mean:+.1f} d · median {stats.median:+.0f} d · σ {stats.std:.1f} · n={stats.n}</sub>",
        xaxis_title="offset (days from moon; − before, + after)",
        yaxis_title="count", showlegend=False,
    )
    return fig_h


hc1.plotly_chart(
    _hist(res.top_matches, t, C_FULL, "Tops relative to Full Moon"),
    use_container_width=True,
)
hc2.plotly_chart(
    _hist(res.bottom_matches, b, C_NEW, "Bottoms relative to New Moon"),
    use_container_width=True,
)

st.info(
    f"**Reading it:** {t.summary}. {b.summary}. "
    "A mean near 0 with a wide σ means turning points scatter fairly symmetrically "
    "around the moon; a clearly positive mean supports the 'tops lag the full moon' idea. "
    "Adjust the pivot sensitivity in the sidebar to see how robust the pattern is."
)

st.divider()

# ---------------------------------------------------------------------------
# Predictions + matched-pairs tables
# ---------------------------------------------------------------------------
st.subheader("🔮 Predicted upcoming turning points")
if res.predictions.empty:
    st.write("No predictions (no matches to base offsets on).")
else:
    today = pd.Timestamp(_dt.date.today()).normalize()
    pred_view = res.predictions.copy()
    pred_view["days_away"] = (pred_view["predicted_date"] - today).dt.days
    badge = {"active": "🟢 now", "upcoming": "🔵 upcoming", "passed": "⚪ passed"}
    pred_view["status"] = pred_view["status"].map(badge).fillna(pred_view["status"])
    for c in ("moon_date", "predicted_date", "window_start", "window_end"):
        pred_view[c] = pred_view[c].dt.date
    pred_view = pred_view[
        ["status", "kind", "moon_type", "moon_date",
         "predicted_date", "days_away", "window_start", "window_end"]
    ].rename(
        columns={
            "status": "Status", "kind": "Type", "moon_type": "Moon",
            "moon_date": "Moon date", "predicted_date": "Predicted",
            "days_away": "Days away", "window_start": "Window start",
            "window_end": "Window end",
        }
    )

    active = pred_view[pred_view["Status"] == "🟢 now"]
    if not active.empty:
        for _, r in active.iterrows():
            st.success(
                f"**We're in an active window now:** {r['Moon']} moon on "
                f"{r['Moon date']} → predicted {r['Type'].lower()} around "
                f"**{r['Predicted']}** (window {r['Window start']} → {r['Window end']})."
            )

    st.dataframe(pred_view, use_container_width=True, hide_index=True)

with st.expander("Matched historical pairs (data behind the stats)"):
    tabs = st.tabs(["Tops (Full moon)", "Bottoms (New moon)"])
    for tab, matched in zip(tabs, (res.top_matches, res.bottom_matches)):
        with tab:
            if matched.empty:
                st.write("No matches.")
            else:
                view = matched.copy()
                view["moon_date"] = view["moon_date"].dt.date
                view["pivot_date"] = view["pivot_date"].dt.date
                view["pivot_price"] = view["pivot_price"].round(0)
                view = view.rename(
                    columns={
                        "moon_type": "Moon", "moon_date": "Moon date",
                        "pivot_date": "Pivot date", "offset_days": "Offset (d)",
                        "pivot_price": "Pivot $",
                    }
                )
                st.dataframe(view, use_container_width=True, hide_index=True)
                st.download_button(
                    "Download CSV", matched.to_csv(index=False),
                    file_name=f"{'tops' if matched is res.top_matches else 'bottoms'}.csv",
                    mime="text/csv",
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
