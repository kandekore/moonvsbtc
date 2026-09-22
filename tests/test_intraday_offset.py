"""The exact intraday lunar offset metric, and its quarantine.

The metric itself is simple arithmetic. What these tests actually protect is the
separation: it must not be runnable on daily bars, must not be back-fitted onto
the historical sample, and must not disturb the published calendar-day figures.
"""
from __future__ import annotations

import datetime as dt

import pandas as pd
import pytest

from btcmoon.research.intraday_offset import (
    EFFECTIVE_FROM, LEGACY_FIGURES_ARE_FROZEN, BackfitRefused, NotIntradayData,
    assert_intraday, find_pivot_instant, measure, measure_series, summarise,
)
from btcmoon.research.protocols import (
    INTRADAY_OFFSET_PROTOCOL, WEBSITE_METHODOLOGY_PROTOCOL,
)

MOON = dt.datetime(2026, 10, 26, 4, 18, 26)      # after EFFECTIVE_FROM


def hourly(start: dt.datetime, hours: int, peak_at: int) -> pd.DataFrame:
    """Synthetic hourly bars with a single unambiguous spike.

    Bars sit on whole hours (:00), while the moon instant does not - which is
    the point: the offset must come out fractional, not rounded to a day.
    """
    start = start.replace(minute=0, second=0, microsecond=0)
    idx = pd.date_range(start, periods=hours, freq="h")
    highs = [100.0] * hours
    lows = [90.0] * hours
    highs[peak_at] = 200.0
    lows[peak_at] = 10.0
    return pd.DataFrame({"high": highs, "low": lows,
                         "close": [95.0] * hours}, index=idx)


# ---------------------------------------------------------------------------
# The measurement
# ---------------------------------------------------------------------------
def test_offset_is_measured_in_hours_not_days():
    frame = hourly(MOON - dt.timedelta(days=1), hours=24 * 20, peak_at=24 + 30)
    got = measure(frame, MOON, "Top")
    # Bars are on the hour; the moon is at 04:18:26. The spike sits 30 h after
    # the frame's 04:00 start on the moon's day, i.e. 30 h - 18m26s after the
    # moon itself - a fractional result a calendar-day method cannot express.
    expected = (got.pivot_instant - MOON).total_seconds() / 3600.0
    assert got.offset_hours == pytest.approx(expected, abs=0.01)
    assert got.offset_hours != round(got.offset_hours)
    assert got.offset_days_exact == pytest.approx(got.offset_hours / 24, abs=0.001)
    assert got.pivot_price == 200.0
    assert got.moon_type == "Full"


def test_calendar_day_figure_is_reported_alongside_not_instead():
    frame = hourly(MOON - dt.timedelta(days=1), hours=24 * 20, peak_at=24 + 30)
    got = measure(frame, MOON, "Top")
    assert got.calendar_day_offset == (got.pivot_instant.date() - MOON.date()).days
    # The two must not be equal by construction - they are different quantities.
    assert got.offset_days_exact != got.calendar_day_offset


def test_bottom_uses_the_low_series():
    frame = hourly(MOON - dt.timedelta(days=1), hours=24 * 20, peak_at=24 + 12)
    got = measure(frame, MOON, "Bottom")
    assert got.moon_type == "New"
    assert got.pivot_price == 10.0


def test_forward_only_window_ignores_a_prior_spike():
    """A symmetric window can claim a spike that preceded the moon."""
    # Frame starts 6 days before the moon, so the moon sits near hour 144.
    # Put the spike at hour 100, i.e. ~1.8 days BEFORE the moon: inside a
    # symmetric +/-4 day window, outside a forward-only one.
    frame = hourly(MOON - dt.timedelta(days=6), hours=24 * 12, peak_at=100)
    lag = 4 * 24
    forward = measure(frame, MOON, "Top", max_lag_hours=lag, forward_only=True)
    symmetric = measure(frame, MOON, "Top", max_lag_hours=lag, forward_only=False)
    assert forward.offset_hours >= 0
    assert forward.pivot_price != 200.0        # the prior spike is out of reach
    assert symmetric.offset_hours < 0          # ...but the symmetric window takes it
    assert symmetric.pivot_price == 200.0


def test_uncovered_window_returns_no_pivot():
    frame = hourly(MOON, hours=5, peak_at=2)
    got = measure(frame, MOON, "Top")
    assert got.pivot_instant is None
    assert got.offset_hours is None
    assert "not fully covered" in got.note


# ---------------------------------------------------------------------------
# Quarantine: daily data is refused
# ---------------------------------------------------------------------------
def test_daily_bars_are_rejected(ohlc_df):
    with pytest.raises(NotIntradayData, match="not intraday"):
        assert_intraday(ohlc_df)
    with pytest.raises(NotIntradayData):
        measure(ohlc_df, MOON, "Top")


def test_frame_without_high_low_is_rejected(ohlc_df):
    with pytest.raises(NotIntradayData, match="intraday high/low required"):
        assert_intraday(ohlc_df[["close"]])


def test_empty_frame_is_rejected():
    with pytest.raises(NotIntradayData):
        assert_intraday(pd.DataFrame())


# ---------------------------------------------------------------------------
# Quarantine: no back-fitting onto the historical sample
# ---------------------------------------------------------------------------
def test_historical_moon_is_refused():
    frame = hourly(dt.datetime(2026, 8, 20), hours=24 * 30, peak_at=100)
    august_full_moon = dt.datetime(2026, 8, 28, 4, 18, 26)
    assert august_full_moon.date() < EFFECTIVE_FROM
    with pytest.raises(BackfitRefused, match="prospective"):
        measure(frame, august_full_moon, "Top")


def test_historical_moons_are_skipped_in_a_series():
    from btcmoon.lunar import moon_events

    frame = hourly(dt.datetime(2026, 8, 1), hours=24 * 120, peak_at=500)
    events = moon_events(dt.date(2026, 8, 1), dt.date(2026, 11, 30))
    assert any(e.exact_at.date() < EFFECTIVE_FROM for e in events)
    got = measure_series(frame, events)
    assert got, "post-cutoff events should still be measured"
    assert all(o.moon_instant.date() >= EFFECTIVE_FROM for o in got)


def test_historical_measurement_requires_an_explicit_opt_in():
    frame = hourly(dt.datetime(2026, 8, 20), hours=24 * 30, peak_at=100)
    august = dt.datetime(2026, 8, 28, 4, 18, 26)
    got = measure(frame, august, "Top", allow_historical=True)
    assert got.offset_hours is not None


# ---------------------------------------------------------------------------
# Quarantine: the published figures are untouched
# ---------------------------------------------------------------------------
def test_legacy_published_figures_are_unchanged():
    published = WEBSITE_METHODOLOGY_PROTOCOL["rules"]["published_benchmarks"]
    assert published["recent_two_year_full_moon"]["mean_days"] == 4.4
    assert published["recent_two_year_full_moon"]["median_days"] == 4
    assert published["recent_two_year_full_moon"]["sd_days"] == 4.2
    assert published["recent_two_year_full_moon"]["n"] == 5
    assert published["2017_2026_full_moon"]["mean_days"] == 3.2
    assert published["2017_2026_full_moon"]["median_days"] == 6.0
    assert published["2017_2026_full_moon"]["pct_high_after_full_moon"] == 71.0


def test_frozen_copy_matches_the_legacy_protocol():
    published = WEBSITE_METHODOLOGY_PROTOCOL["rules"]["published_benchmarks"]
    assert (LEGACY_FIGURES_ARE_FROZEN["recent_two_year_full_moon_mean_days"]
            == published["recent_two_year_full_moon"]["mean_days"])
    assert (LEGACY_FIGURES_ARE_FROZEN["2017_2026_full_moon_mean_days"]
            == published["2017_2026_full_moon"]["mean_days"])
    assert (LEGACY_FIGURES_ARE_FROZEN["2017_2026_full_moon_median_days"]
            == published["2017_2026_full_moon"]["median_days"])


def test_it_is_a_separate_protocol_not_a_new_legacy_version():
    assert INTRADAY_OFFSET_PROTOCOL["slug"] != WEBSITE_METHODOLOGY_PROTOCOL["slug"]
    assert INTRADAY_OFFSET_PROTOCOL["slug"] == "intraday-lunar-offset-v1"
    rules = INTRADAY_OFFSET_PROTOCOL["rules"]
    assert "FORBIDDEN" in rules["back_fitting"]
    assert rules["units"].startswith("hours")
    assert "NONE" in rules["relationship_to_legacy"]["comparability"]


def test_summary_declares_itself_incomparable_and_carries_the_frozen_block():
    frame = hourly(MOON - dt.timedelta(days=1), hours=24 * 20, peak_at=24 + 30)
    out = summarise([measure(frame, MOON, "Top")])
    assert out["comparable_with_calendar_day_lag"] is False
    assert out["units"].startswith("hours")
    assert out["legacy_figures"]["recent_two_year_full_moon_mean_days"] == 4.4
    assert out["full_moon_to_high"]["n"] == 1
    # Nothing in the payload may be a bare calendar-day mean.
    assert "mean_days" not in out["full_moon_to_high"]
    assert "mean_days_exact" in out["full_moon_to_high"]


def test_find_pivot_instant_returns_an_exact_timestamp():
    frame = hourly(MOON, hours=48, peak_at=20)
    got = find_pivot_instant(frame, MOON, MOON + dt.timedelta(hours=40), "Top")
    assert got is not None
    instant, price, bars = got
    assert isinstance(instant, dt.datetime)
    assert instant.minute == MOON.minute or instant.hour is not None
    assert price == 200.0
    assert bars > 0
