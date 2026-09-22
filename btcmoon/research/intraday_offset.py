"""Exact intraday lunar offset - a NEW, PROSPECTIVE metric (spec: protocol 3).

What this measures
------------------
The interval from the **exact UTC instant of a Full or New Moon** to the **exact
UTC timestamp of the corresponding BTC pivot**, in hours. Not calendar days.

  offset_hours = pivot_instant - moon_instant

The legacy website methodology reduces both sides to calendar dates before
subtracting, which quantises every measurement to whole days and discards up to
+/-23 hours of real information. The August 2026 Full Moon is the worked example:
the moon was exact at 04:18 UTC on 28 Aug and the high printed during 3 Sep, so
the calendar-day answer is FM+6 while the true elapsed interval is somewhere
between 5.0 and 6.8 days depending on the hour the high actually printed.

This module exists to capture that hour. It does NOT reinterpret anything.

Separation from the legacy experiment - read this before using it
-----------------------------------------------------------------
This metric is deliberately quarantined:

* It is a **separate frozen protocol** (``intraday-lunar-offset-v1``), not a new
  version of ``website-methodology-v1``. The legacy protocol is untouched.
* It **must never** be used to recompute the published +4.4 d / +3.2 d / 71%
  figures. Those are the reproduced means of the historical calendar-day sample
  and they stay exactly as they are. ``LEGACY_FIGURES_ARE_FROZEN`` records that,
  and ``assert_not_backfitting`` enforces it for callers that might be tempted.
* It is **prospective only**. Hourly BTC history is not available far enough
  back to reconstruct the historical sample even if we wanted to - see
  ``EARLIEST_RELIABLE_HOURLY`` - and back-fitting a new, finer metric onto the
  sample that produced the original claim would be exactly the kind of silent
  re-specification the amendment policy forbids.
* Its numbers are never averaged with, substituted for, or compared
  like-for-like against calendar-day offsets. A fractional-day figure from here
  and an integer-day figure from there are different measurements.

Recording an observation under this metric therefore says nothing about whether
the historical +4.4 d mean was right. It starts a new, cleaner series.
"""
from __future__ import annotations

import datetime as dt
from dataclasses import asdict, dataclass

import pandas as pd

#: Hourly crypto history from the usual free providers reaches back roughly two
#: years. Anything earlier cannot be measured this way, which is the practical
#: reason - on top of the methodological one - that this metric runs forward
#: only.
EARLIEST_RELIABLE_HOURLY = dt.date(2024, 9, 1)

#: The date from which this metric is collected. Observations before it are not
#: part of the series.
EFFECTIVE_FROM = dt.date(2026, 9, 22)

#: Figures that this module must never recompute, reinterpret or "improve".
LEGACY_FIGURES_ARE_FROZEN = {
    "recent_two_year_full_moon_mean_days": 4.4,
    "recent_two_year_full_moon_median_days": 4,
    "recent_two_year_full_moon_sd_days": 4.2,
    "recent_two_year_full_moon_n": 5,
    "2017_2026_full_moon_mean_days": 3.2,
    "2017_2026_full_moon_median_days": 6.0,
    "2017_2026_pct_high_after_full_moon": 71.0,
    "basis": "calendar-day signed lag, daily CLOSE, website-methodology-v1",
    "status": "FROZEN - reproduced historical sample, never to be back-fitted",
}

#: Largest gap between bars, in minutes, still accepted as "hourly".
_MAX_BAR_GAP_MINUTES = 90


class NotIntradayData(ValueError):
    """Raised when a frame is too coarse to carry an exact pivot timestamp."""


class BackfitRefused(ValueError):
    """Raised on an attempt to apply this metric to the historical sample."""


@dataclass
class IntradayOffset:
    """One moon-to-pivot interval, measured to the hour."""

    moon_type: str                  # "Full" | "New"
    kind: str                       # "Top" | "Bottom"
    moon_instant: dt.datetime       # exact UTC
    pivot_instant: dt.datetime | None
    pivot_price: float | None
    offset_hours: float | None
    #: Fractional days. NOT comparable with a calendar-day lag - see module docs.
    offset_days_exact: float | None
    #: The calendar-day figure the legacy method would report, for reference
    #: only. Recorded so the two can be seen side by side, never merged.
    calendar_day_offset: int | None
    bars_in_window: int
    note: str = ""

    def to_dict(self) -> dict:
        d = asdict(self)
        for key in ("moon_instant", "pivot_instant"):
            if isinstance(d[key], dt.datetime):
                d[key] = d[key].isoformat()
        return d


def assert_intraday(frame: pd.DataFrame) -> None:
    """Refuse daily data - it cannot carry an exact pivot timestamp."""
    if frame is None or frame.empty:
        raise NotIntradayData("no data supplied")
    missing = {"high", "low"} - set(frame.columns)
    if missing:
        raise NotIntradayData(
            f"intraday high/low required; missing {sorted(missing)}"
        )
    if len(frame) < 2:
        raise NotIntradayData("need at least two bars to infer the interval")
    gap = frame.index.to_series().diff().dropna().median()
    if gap > pd.Timedelta(minutes=_MAX_BAR_GAP_MINUTES):
        raise NotIntradayData(
            f"median bar interval is {gap}, which is not intraday. This metric is "
            "defined on hourly (or finer) bars; daily bars only carry a date, so "
            "using them here would silently reproduce the calendar-day method."
        )


def assert_not_backfitting(moon_instant: dt.datetime) -> None:
    """Guard the prospective-only rule."""
    if moon_instant.date() < EFFECTIVE_FROM:
        raise BackfitRefused(
            f"{moon_instant:%Y-%m-%d} precedes EFFECTIVE_FROM "
            f"({EFFECTIVE_FROM}). This metric is prospective: applying it to the "
            "historical sample would re-specify the measurement that produced the "
            "published +4.4 d figure. Record the calendar-day observation instead."
        )


def find_pivot_instant(
    frame: pd.DataFrame,
    window_start: dt.datetime,
    window_end: dt.datetime,
    kind: str,
) -> tuple[dt.datetime, float, int] | None:
    """Exact timestamp of the highest HIGH (Top) or lowest LOW (Bottom).

    Returns ``(instant, price, bars_examined)``, or ``None`` when the window is
    not fully covered by data - a truncated window biases the answer toward
    whichever side has bars.
    """
    assert_intraday(frame)
    if window_start < frame.index.min() or window_end > frame.index.max():
        return None
    window = frame.loc[window_start:window_end]
    if window.empty:
        return None
    column = "high" if kind == "Top" else "low"
    series = window[column].astype(float)
    stamp = series.idxmax() if kind == "Top" else series.idxmin()
    return stamp.to_pydatetime(), float(series.loc[stamp]), len(window)


def measure(
    frame: pd.DataFrame,
    moon_instant: dt.datetime,
    kind: str,
    max_lag_hours: int = 14 * 24,
    forward_only: bool = True,
    allow_historical: bool = False,
) -> IntradayOffset:
    """Measure one moon-to-pivot interval to the hour.

    ``forward_only`` matches the pre-registered protocol's T0-onwards framing. A
    symmetric window can attribute a pivot from the preceding phase to this moon.

    ``allow_historical`` exists only for tests and for explicitly-labelled
    exploratory work; leaving it False enforces the prospective-only rule.
    """
    if not allow_historical:
        assert_not_backfitting(moon_instant)
    assert_intraday(frame)

    moon_type = "Full" if kind == "Top" else "New"
    start = (moon_instant if forward_only
             else moon_instant - dt.timedelta(hours=max_lag_hours))
    end = moon_instant + dt.timedelta(hours=max_lag_hours)

    found = find_pivot_instant(frame, start, end, kind)
    if not found:
        return IntradayOffset(
            moon_type=moon_type, kind=kind, moon_instant=moon_instant,
            pivot_instant=None, pivot_price=None, offset_hours=None,
            offset_days_exact=None, calendar_day_offset=None, bars_in_window=0,
            note="window not fully covered by intraday data",
        )

    instant, price, bars = found
    hours = (instant - moon_instant).total_seconds() / 3600.0
    return IntradayOffset(
        moon_type=moon_type, kind=kind, moon_instant=moon_instant,
        pivot_instant=instant, pivot_price=round(price, 2),
        offset_hours=round(hours, 2),
        offset_days_exact=round(hours / 24.0, 3),
        calendar_day_offset=(instant.date() - moon_instant.date()).days,
        bars_in_window=bars,
    )


def measure_series(
    frame: pd.DataFrame,
    events,
    max_lag_hours: int = 14 * 24,
    forward_only: bool = True,
    allow_historical: bool = False,
) -> list[IntradayOffset]:
    """Measure every supplied ``MoonEvent``. Skips those outside the data."""
    out = []
    for event in events:
        kind = "Top" if event.event_type == "full_moon" else "Bottom"
        try:
            out.append(measure(frame, event.exact_at, kind,
                               max_lag_hours=max_lag_hours,
                               forward_only=forward_only,
                               allow_historical=allow_historical))
        except BackfitRefused:
            continue
    return out


def summarise(offsets: list[IntradayOffset]) -> dict:
    """Descriptive statistics, clearly labelled as a separate series.

    Deliberately returns nothing that could be mistaken for the legacy figures:
    the units are hours, the key names say ``exact``, and the payload carries the
    frozen legacy block so the two can never be confused in a report.
    """
    import numpy as np

    out: dict = {
        "metric": "intraday-lunar-offset-v1",
        "units": "hours from exact syzygy to exact pivot",
        "effective_from": EFFECTIVE_FROM.isoformat(),
        "comparable_with_calendar_day_lag": False,
        "legacy_figures": dict(LEGACY_FIGURES_ARE_FROZEN),
    }
    for label, moon_type in (("full_moon_to_high", "Full"),
                             ("new_moon_to_low", "New")):
        measured = [o for o in offsets
                    if o.moon_type == moon_type and o.offset_hours is not None]
        hours = np.array([o.offset_hours for o in measured], dtype=float)
        out[label] = {
            "n": len(measured),
            "mean_hours_exact": round(float(np.mean(hours)), 2) if hours.size else None,
            "median_hours_exact": round(float(np.median(hours)), 2) if hours.size else None,
            "sd_hours_exact": (
                round(float(np.std(hours, ddof=1)), 2) if hours.size > 1 else None
            ),
            "mean_days_exact": round(float(np.mean(hours)) / 24.0, 3) if hours.size else None,
        }
    return out
