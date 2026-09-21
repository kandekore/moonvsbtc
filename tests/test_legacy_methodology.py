"""Regression tests around the legacy lunar/Bitcoin research methodology.

These lock in the exact numbers the published research rests on. If a refactor
changes any of them the suite fails - which is the point. Per the research
constitution, a genuine methodology change is a NEW versioned protocol, never
an edit that quietly moves these goalposts.

Reference figures come from the build specification, section 8:

  * Recent two-year Full-Moon benchmark: mean +4.4 d, median +4 d, SD ~4.2, n=5
  * 2017-2026: ~70% of matched major highs after the Full Moon,
    mean ~+3.2 d, median ~+6 d
  * Website parameters: yfinance BTC-USD daily Close, PyEphem phases reduced to
    calendar dates, scipy find_peaks, distance=30, prominence=15% of median
    close, max lag +/-14 days, signed lag = pivot date - moon date.
"""
from __future__ import annotations

import datetime as dt

import pandas as pd
import pytest

import moon_engine as me


# --- website methodology parameters (spec s8) -----------------------------
DISTANCE = 30
PROMINENCE_PCT = 15.0
MAX_LAG = 14


def test_price_fixture_is_intact(price_df):
    assert len(price_df) == 4388
    assert price_df.index.min() == pd.Timestamp("2014-09-17")
    assert price_df.index.max() == pd.Timestamp("2026-09-21")
    assert list(price_df.columns) == ["close"]


def test_moon_phases_match_known_events():
    """The frozen September 2026 protocol hinges on these two dates."""
    new_moons = me.moon_phases(dt.date(2026, 9, 1), dt.date(2026, 9, 30), "new")
    full_moons = me.moon_phases(dt.date(2026, 9, 1), dt.date(2026, 9, 30), "full")
    assert dt.date(2026, 9, 11) in new_moons
    assert dt.date(2026, 9, 26) in full_moons


def test_pivot_detection_is_stable(price_df):
    highs, lows = me.detect_pivots(
        price_df, distance=DISTANCE, prominence_pct=PROMINENCE_PCT
    )
    assert len(highs) == 48
    assert len(lows) == 46


def test_full_history_offsets_are_stable(price_df):
    res = me.run_analysis(
        price_df=price_df, distance=DISTANCE,
        prominence_pct=PROMINENCE_PCT, max_lag=MAX_LAG,
    )
    assert res.top_stats.n == 47
    assert res.bottom_stats.n == 45
    assert res.top_stats.mean == pytest.approx(2.766, abs=0.01)
    assert res.top_stats.median == pytest.approx(5.0)
    assert res.bottom_stats.mean == pytest.approx(-0.022, abs=0.01)


def test_recent_two_year_full_moon_benchmark(price_df):
    """The headline +4.4-day result the legacy website published.

    This is the single most provenance-sensitive number in the project.
    """
    window = price_df[price_df.index >= pd.Timestamp("2024-09-21")]
    res = me.run_analysis(
        price_df=window, distance=DISTANCE,
        prominence_pct=PROMINENCE_PCT, max_lag=MAX_LAG,
    )
    t = res.top_stats
    assert t.n == 5
    assert t.mean == pytest.approx(4.4, abs=0.05)
    assert t.median == pytest.approx(4.0)
    assert t.std == pytest.approx(4.2, abs=0.1)


def test_2017_2026_full_moon_skew(price_df):
    """~70% of matched major highs fall after the Full Moon; mean ~+3.2, median ~+6."""
    window = price_df[price_df.index >= pd.Timestamp("2017-01-01")]
    res = me.run_analysis(
        price_df=window, distance=DISTANCE,
        prominence_pct=PROMINENCE_PCT, max_lag=MAX_LAG,
    )
    t = res.top_matches
    pct_after = (t["offset_days"] > 0).mean()
    assert 0.65 <= pct_after <= 0.75
    assert res.top_stats.mean == pytest.approx(3.2, abs=0.15)
    assert res.top_stats.median == pytest.approx(6.0)


def test_signed_lag_convention_is_pivot_minus_moon(price_df):
    """Positive offset = pivot AFTER the moon. Flipping this sign would
    silently invert every published result."""
    moons = [dt.date(2025, 8, 9)]
    highs, _ = me.detect_pivots(price_df, distance=DISTANCE, prominence_pct=PROMINENCE_PCT)
    matched = me.match_moons_to_pivots(moons, highs, price_df, MAX_LAG, "Full")
    row = matched.iloc[0]
    assert row["offset_days"] == (row["pivot_date"] - row["moon_date"]).days
    assert row["offset_days"] == 4  # 2025-08-13 high, four days after the full moon


def test_match_respects_max_lag(price_df):
    """No pivot beyond +/-max_lag may ever be claimed by a moon."""
    highs, _ = me.detect_pivots(price_df, distance=DISTANCE, prominence_pct=PROMINENCE_PCT)
    full = me.moon_phases(dt.date(2014, 9, 17), dt.date(2026, 9, 21), "full")
    matched = me.match_moons_to_pivots(full, highs, price_df, MAX_LAG, "Full")
    assert matched["offset_days"].abs().max() <= MAX_LAG
