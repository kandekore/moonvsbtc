"""
moon_engine.py
--------------
Core analysis engine for the "BTC vs Moon" project.

Thesis under test:
    * Full moon  -> local TOP in Bitcoin price
    * New moon   -> local BOTTOM in Bitcoin price
    * Empirically the top appears to lag the full moon by several days,
      so we measure the *signed* offset (days after the moon) and use its
      average +/- spread to PREDICT future tops/bottoms.

Methodology:
    1. Download full BTC-USD daily history (yfinance).
    2. Compute every full/new moon across the range (ephem).
    3. Detect *true swing pivots* in price (scipy.signal.find_peaks) rather
       than "the max in a fixed window" -- these are genuine local
       highs/lows with a minimum prominence and spacing.
    4. Match each moon to the nearest pivot of the correct type within a
       maximum lag, recording the signed day offset.
    5. Summarise the offsets (mean / median / std) and project upcoming
       moons forward to predicted top/bottom dates with a +/- band.

This module is pure logic (no UI) so it can be unit-tested and reused.
"""

from __future__ import annotations

import datetime as _dt
from dataclasses import dataclass, field

import ephem
import numpy as np
import pandas as pd
import yfinance as yf
from scipy.signal import find_peaks


# ---------------------------------------------------------------------------
# 1) Price data
# ---------------------------------------------------------------------------
def fetch_btc(start: str = "2014-09-17", end: str | None = None) -> pd.DataFrame:
    """Download BTC-USD daily closes as a tidy DataFrame indexed by date.

    Returns a DataFrame with a single 'close' column and a DatetimeIndex
    (tz-naive, normalised to midnight). Raises ValueError if nothing came back.
    """
    if end is None:
        end = (_dt.date.today() + _dt.timedelta(days=1)).isoformat()

    raw = yf.download(
        "BTC-USD",
        start=start,
        end=end,
        progress=False,
        auto_adjust=True,
    )
    if raw is None or raw.empty:
        raise ValueError("No BTC price data returned from yfinance.")

    # yfinance can return a MultiIndex (column, ticker) frame -- flatten it.
    close = raw["Close"]
    if isinstance(close, pd.DataFrame):
        close = close.iloc[:, 0]

    df = pd.DataFrame({"close": close.astype(float)})
    df.index = pd.to_datetime(df.index).tz_localize(None).normalize()
    df = df[~df.index.duplicated(keep="last")].sort_index()
    df = df.dropna()
    return df


# ---------------------------------------------------------------------------
# 2) Moon phases
# ---------------------------------------------------------------------------
def moon_phases(
    start: _dt.date, end: _dt.date, phase: str = "full"
) -> list[_dt.date]:
    """Return the list of full ('full') or new ('new') moon dates in [start, end]."""
    if phase == "full":
        step = ephem.next_full_moon
    elif phase == "new":
        step = ephem.next_new_moon
    else:
        raise ValueError("phase must be 'full' or 'new'")

    out: list[_dt.date] = []
    cursor = step(_dt.datetime(start.year, start.month, start.day) - _dt.timedelta(days=1))
    while True:
        d = cursor.datetime().date()
        if d > end:
            break
        if d >= start:
            out.append(d)
        cursor = step(cursor)
    return out


# ---------------------------------------------------------------------------
# 3) Swing-pivot detection
# ---------------------------------------------------------------------------
def detect_pivots(
    df: pd.DataFrame,
    distance: int = 30,
    prominence_pct: float = 15.0,
) -> tuple[pd.DatetimeIndex, pd.DatetimeIndex]:
    """Detect true swing highs and lows in the close series.

    Parameters
    ----------
    distance : minimum number of days between two pivots of the same type.
    prominence_pct : minimum vertical prominence of a pivot, as a percentage
        of the median price -- filters out insignificant wiggles.

    Returns (swing_high_dates, swing_low_dates).
    """
    close = df["close"].to_numpy(dtype=float)
    if close.size == 0:
        empty = pd.DatetimeIndex([])
        return empty, empty

    prominence = np.median(close) * (prominence_pct / 100.0)

    high_idx, _ = find_peaks(close, distance=distance, prominence=prominence)
    low_idx, _ = find_peaks(-close, distance=distance, prominence=prominence)

    return df.index[high_idx], df.index[low_idx]


# ---------------------------------------------------------------------------
# 4) Match moons to nearest pivots
# ---------------------------------------------------------------------------
def match_moons_to_pivots(
    moon_dates: list[_dt.date],
    pivot_dates: pd.DatetimeIndex,
    df: pd.DataFrame,
    max_lag: int = 14,
    moon_type: str = "Full",
) -> pd.DataFrame:
    """For each moon, find the nearest pivot within +/- max_lag days.

    The signed offset = (pivot_date - moon_date) in days:
        negative -> pivot came BEFORE the moon
        positive -> pivot came AFTER the moon
    Returns a DataFrame (one row per matched moon).
    """
    if len(pivot_dates) == 0:
        return pd.DataFrame(
            columns=[
                "moon_type", "moon_date", "pivot_date",
                "offset_days", "pivot_price",
            ]
        )

    pivot_arr = np.array([pd.Timestamp(p).normalize() for p in pivot_dates])
    rows = []
    for m in moon_dates:
        m_ts = pd.Timestamp(m)
        deltas = np.array([(p - m_ts).days for p in pivot_arr])
        within = np.abs(deltas) <= max_lag
        if not within.any():
            continue
        # nearest pivot within the window
        candidate_pos = np.where(within)[0]
        best = candidate_pos[np.argmin(np.abs(deltas[candidate_pos]))]
        pivot_date = pivot_arr[best]
        price = float(df["close"].asof(pivot_date))
        rows.append(
            {
                "moon_type": moon_type,
                "moon_date": m_ts.normalize(),
                "pivot_date": pivot_date,
                "offset_days": int(deltas[best]),
                "pivot_price": price,
            }
        )

    return pd.DataFrame(rows)


# ---------------------------------------------------------------------------
# 5) Summary statistics
# ---------------------------------------------------------------------------
@dataclass
class OffsetStats:
    label: str
    n: int
    mean: float
    median: float
    std: float
    min: int
    max: int

    @property
    def summary(self) -> str:
        if self.n == 0:
            return f"{self.label}: no matches"
        sign = "after" if self.mean >= 0 else "before"
        return (
            f"{self.label}: {abs(self.mean):.1f} days {sign} on average "
            f"(±{self.std:.1f}), n={self.n}"
        )


def offset_stats(matched: pd.DataFrame, label: str) -> OffsetStats:
    """Compute mean/median/std of the signed offsets for a matched table."""
    if matched.empty:
        return OffsetStats(label, 0, 0.0, 0.0, 0.0, 0, 0)
    o = matched["offset_days"].to_numpy(dtype=float)
    return OffsetStats(
        label=label,
        n=int(o.size),
        mean=float(np.mean(o)),
        median=float(np.median(o)),
        std=float(np.std(o, ddof=1)) if o.size > 1 else 0.0,
        min=int(o.min()),
        max=int(o.max()),
    )


# ---------------------------------------------------------------------------
# 6) Future predictions
# ---------------------------------------------------------------------------
def predict_future(
    last_date: _dt.date,
    horizon_days: int,
    top_stats: OffsetStats,
    bottom_stats: OffsetStats,
    today: _dt.date | None = None,
) -> pd.DataFrame:
    """Project upcoming full/new moons forward to predicted top/bottom dates.

    Predicted date = moon date + mean offset, with a +/- std uncertainty band.

    We start the search one full lunar cycle *before* today so that a moon which
    has *already occurred* (e.g. yesterday's new moon) still shows up while its
    predicted turning-point window is in the future. A row is kept as long as its
    window has not fully elapsed (``window_end >= today``), so the phase we are
    currently in always appears in the list.
    """
    if today is None:
        today = _dt.date.today()

    today_ts = pd.Timestamp(today).normalize()
    # look back a bit more than one synodic month so the most recent full AND new
    # moon are both captured even if their offset pushes the window forward.
    search_start = min(last_date, today) - _dt.timedelta(days=40)
    end = max(last_date, today) + _dt.timedelta(days=horizon_days)
    rows = []

    for phase, stats, kind in (
        ("full", top_stats, "Top"),
        ("new", bottom_stats, "Bottom"),
    ):
        if stats.n == 0:
            continue
        for m in moon_phases(search_start, end, phase=phase):
            center = pd.Timestamp(m) + pd.Timedelta(days=round(stats.mean))
            lo = pd.Timestamp(m) + pd.Timedelta(days=round(stats.mean - stats.std))
            hi = pd.Timestamp(m) + pd.Timedelta(days=round(stats.mean + stats.std))
            # drop predictions whose window is already entirely in the past.
            if hi.normalize() < today_ts:
                continue
            rows.append(
                {
                    "kind": kind,
                    "moon_type": "Full" if phase == "full" else "New",
                    "moon_date": pd.Timestamp(m).normalize(),
                    "predicted_date": center.normalize(),
                    "window_start": lo.normalize(),
                    "window_end": hi.normalize(),
                    "status": "active" if lo.normalize() <= today_ts <= hi.normalize()
                    else ("upcoming" if center.normalize() >= today_ts else "passed"),
                }
            )

    out = pd.DataFrame(rows)
    if not out.empty:
        out = out.sort_values("predicted_date").reset_index(drop=True)
    return out


# ---------------------------------------------------------------------------
# 7) One-call orchestration
# ---------------------------------------------------------------------------
@dataclass
class AnalysisResult:
    price: pd.DataFrame
    full_moons: list[_dt.date]
    new_moons: list[_dt.date]
    swing_highs: pd.DatetimeIndex
    swing_lows: pd.DatetimeIndex
    top_matches: pd.DataFrame
    bottom_matches: pd.DataFrame
    top_stats: OffsetStats
    bottom_stats: OffsetStats
    predictions: pd.DataFrame = field(default_factory=pd.DataFrame)


def run_analysis(
    start: str = "2014-09-17",
    end: str | None = None,
    distance: int = 30,
    prominence_pct: float = 15.0,
    max_lag: int = 14,
    horizon_days: int = 120,
    price_df: pd.DataFrame | None = None,
) -> AnalysisResult:
    """Run the full pipeline and return a bundled result.

    Pass a pre-fetched `price_df` (from fetch_btc) to avoid re-downloading.
    """
    df = price_df if price_df is not None else fetch_btc(start=start, end=end)

    start_date = df.index.min().date()
    end_date = df.index.max().date()

    full = moon_phases(start_date, end_date, "full")
    new = moon_phases(start_date, end_date, "new")

    highs, lows = detect_pivots(df, distance=distance, prominence_pct=prominence_pct)

    top_matches = match_moons_to_pivots(full, highs, df, max_lag, "Full")
    bottom_matches = match_moons_to_pivots(new, lows, df, max_lag, "New")

    t_stats = offset_stats(top_matches, "Top vs Full Moon")
    b_stats = offset_stats(bottom_matches, "Bottom vs New Moon")

    preds = predict_future(end_date, horizon_days, t_stats, b_stats, today=_dt.date.today())

    return AnalysisResult(
        price=df,
        full_moons=full,
        new_moons=new,
        swing_highs=highs,
        swing_lows=lows,
        top_matches=top_matches,
        bottom_matches=bottom_matches,
        top_stats=t_stats,
        bottom_stats=b_stats,
        predictions=preds,
    )


if __name__ == "__main__":
    res = run_analysis()
    print(res.top_stats.summary)
    print(res.bottom_stats.summary)
    print(f"\nSwing highs: {len(res.swing_highs)}, swing lows: {len(res.swing_lows)}")
    print(f"Matched tops: {len(res.top_matches)}, matched bottoms: {len(res.bottom_matches)}")
    print("\nNext predicted turning points:")
    print(res.predictions.head(10).to_string(index=False))
