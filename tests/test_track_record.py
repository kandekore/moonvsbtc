"""The retrospective track record.

Two invariants are protected here:

1. The "local extreme" measure is ALWAYS decidable when the window is covered by
   data. A moon with no *significant* pivot is not missing data - it simply had
   no large swing - and must still carry a timing measurement.
2. Nothing is scored as a hit or a miss unless an expectation existed AND a
   measurement was possible. Undecidable never collapses into "miss".
"""
from __future__ import annotations

import datetime as dt

import pytest

from btcmoon.research.legacy import legacy_analysis
from btcmoon.research.track_record import (
    MIN_PRIOR_MATCHES, build_track_record, placebo_baseline,
    track_record_frame, track_record_summary, window_extreme,
)

TODAY = dt.date(2026, 9, 21)          # last bar in the frozen fixture
MAX_LAG = 14


@pytest.fixture(scope="module")
def analysis(request):
    df = request.getfixturevalue("ohlc_df")
    return legacy_analysis(price_df=df, start="2014-09-17")


@pytest.fixture(scope="module")
def entries(analysis):
    return build_track_record(analysis, basis="walk_forward", today=TODAY,
                              max_lag=MAX_LAG)


# ---------------------------------------------------------------------------
# The extreme always exists - the point of the rework
# ---------------------------------------------------------------------------
def test_every_covered_moon_gets_an_extreme(entries):
    """A missing significant pivot must NOT leave the row empty."""
    missing = [e for e in entries if e.extreme_date is None]
    # Only edge-of-history moons may lack one.
    assert len(missing) <= 2, [e.moon_date for e in missing]
    assert len(entries) - len(missing) > 250


def test_moons_without_a_pivot_are_still_measured(entries):
    """The exact complaint: rows showed no high/low at all."""
    no_pivot = [e for e in entries if e.pivot_date is None]
    assert len(no_pivot) > 150, "fixture should have many unmatched moons"
    measured = [e for e in no_pivot if e.extreme_date is not None]
    assert len(measured) / len(no_pivot) > 0.95
    assert all(e.extreme_offset_days is not None for e in measured)


def test_extreme_is_the_true_window_extreme(analysis, entries):
    """Spot-check the extreme against a direct pandas computation."""
    close = analysis.price["close"].astype(float)
    import pandas as pd
    for e in [x for x in entries if x.extreme_date is not None][:40]:
        lo = pd.Timestamp(e.moon_date) - pd.Timedelta(days=MAX_LAG)
        hi = pd.Timestamp(e.moon_date) + pd.Timedelta(days=MAX_LAG)
        w = close.loc[lo:hi]
        expected = w.max() if e.kind == "Top" else w.min()
        assert e.extreme_close == pytest.approx(expected, abs=0.01)


def test_extreme_offset_never_exceeds_the_lag(entries):
    for e in entries:
        if e.extreme_offset_days is not None:
            assert abs(e.extreme_offset_days) <= MAX_LAG


def test_window_extreme_returns_none_outside_coverage(analysis):
    close = analysis.price["close"].astype(float)
    first = close.index.min().date()
    assert window_extreme(close, first, "Top", MAX_LAG) is None


# ---------------------------------------------------------------------------
# Turning point vs trending through
# ---------------------------------------------------------------------------
def test_boundary_extremes_are_flagged_as_trending(entries):
    flagged = [e for e in entries if e.extreme_at_window_edge]
    assert flagged, "a trending series must produce boundary extremes"
    for e in flagged:
        assert abs(e.extreme_offset_days) >= MAX_LAG - 1
        assert "boundary" in e.note


def test_turning_point_flag_matches_the_frozen_detector(analysis, entries):
    highs = {d.date() for d in analysis.swing_highs}
    lows = {d.date() for d in analysis.swing_lows}
    for e in entries:
        if e.extreme_date is None:
            continue
        expected = e.extreme_date in (highs if e.kind == "Top" else lows)
        assert e.extreme_is_turning_point is expected


def test_most_extremes_are_not_significant_pivots(entries):
    """Significance is rare; that is a property of the detector, not a bug."""
    measured = [e for e in entries if e.extreme_date is not None]
    turns = [e for e in measured if e.extreme_is_turning_point]
    assert 0 < len(turns) < len(measured) / 2


# ---------------------------------------------------------------------------
# Scoring discipline
# ---------------------------------------------------------------------------
def test_no_expectation_below_the_minimum_sample(entries):
    for e in entries:
        if e.n_prior_extremes < MIN_PRIOR_MATCHES:
            assert e.expected_extreme_offset is None
            assert e.extreme_error_days is None
            assert e.extreme_hit is None


def test_unmatched_pivot_is_never_scored_as_a_miss(entries):
    for e in entries:
        if e.pivot_date is None:
            assert e.pivot_error_days is None
            assert e.pivot_hit is None


def test_error_is_actual_minus_expected(entries):
    for e in entries:
        if e.extreme_error_days is not None:
            assert e.extreme_error_days == pytest.approx(
                e.extreme_offset_days - e.expected_extreme_offset, abs=0.01)
        if e.pivot_error_days is not None:
            assert e.pivot_error_days == pytest.approx(
                e.pivot_offset_days - e.expected_pivot_offset, abs=0.01)


def test_walk_forward_never_uses_future_observations(entries):
    seen: dict[str, int] = {}
    for e in sorted(entries, key=lambda e: e.moon_date):
        n = seen.get(e.kind, 0)
        if e.expected_extreme_offset is not None:
            assert e.n_prior_extremes == n
        if e.extreme_date is not None:
            seen[e.kind] = n + 1


def test_open_moons_are_excluded(analysis):
    got = build_track_record(analysis, today=TODAY, max_lag=MAX_LAG)
    assert all(e.moon_date <= TODAY - dt.timedelta(days=MAX_LAG) for e in got)


def test_rejects_unknown_basis_and_measure(analysis, entries):
    with pytest.raises(ValueError, match="basis must be one of"):
        build_track_record(analysis, basis="hindsight", today=TODAY)
    with pytest.raises(ValueError, match="measure must be one of"):
        track_record_summary(entries, measure="vibes")


# ---------------------------------------------------------------------------
# Summary + placebo
# ---------------------------------------------------------------------------
def test_summary_counts_only_scored_entries(entries):
    for measure in ("extreme", "pivot"):
        summary = track_record_summary(entries, measure=measure)
        for key, kind in (("full_moon_to_high", "Top"), ("new_moon_to_low", "Bottom")):
            block = summary[key]
            subset = [e for e in entries if e.kind == kind]
            scored = [e for e in subset
                      if getattr(e, f"{measure}_error_days") is not None]
            assert block["n_moons"] == len(subset)
            assert block["n_scored"] == len(scored)
            assert block["n_undecidable"] == len(subset) - len(scored)


def test_extreme_measure_scores_far_more_than_pivot(entries):
    ex = track_record_summary(entries, "extreme")["full_moon_to_high"]
    pv = track_record_summary(entries, "pivot")["full_moon_to_high"]
    assert ex["n_scored"] > 3 * pv["n_scored"]


def test_placebo_uses_the_same_window_for_real_and_random(analysis):
    base = placebo_baseline(analysis, max_lag=MAX_LAG, n_trials=500, seed=0,
                            today=TODAY)
    for key in ("full_moon_to_high", "new_moon_to_low"):
        b = base[key]
        assert b["window_days"] is not None
        assert b["n_real"] > 100 and b["n_trials"] > 100
        assert 0 <= b["real_hit_rate_pct"] <= 100
        assert 0 <= b["placebo_hit_rate_pct"] <= 100
        assert b["edge_pct"] == pytest.approx(
            b["real_hit_rate_pct"] - b["placebo_hit_rate_pct"], abs=0.11)
        assert b["edge_se_pct"] > 0


def test_placebo_is_deterministic_for_a_seed(analysis):
    a = placebo_baseline(analysis, max_lag=MAX_LAG, n_trials=300, seed=7, today=TODAY)
    c = placebo_baseline(analysis, max_lag=MAX_LAG, n_trials=300, seed=7, today=TODAY)
    assert a == c


def test_frame_is_newest_first(entries):
    df = track_record_frame(entries)
    assert list(df["moon_date"]) == sorted(df["moon_date"], reverse=True)
