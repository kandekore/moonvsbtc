"""The retrospective track record.

The invariant these tests protect: an entry is scored ONLY when both an
expectation existed beforehand and a pivot actually matched. Anything else is
reported as undecidable, never as a miss - the same rule the New-Moon protocol
applies to an unresolved bar.
"""
from __future__ import annotations

import datetime as dt

import pytest

from btcmoon.research.legacy import legacy_analysis
from btcmoon.research.track_record import (
    MIN_PRIOR_MATCHES, build_track_record, track_record_frame,
    track_record_summary,
)

TODAY = dt.date(2026, 9, 21)          # last bar in the frozen fixture


@pytest.fixture(scope="module")
def analysis(request):
    df = request.getfixturevalue("ohlc_df")
    return legacy_analysis(price_df=df, start="2014-09-17")


def test_walk_forward_never_uses_future_offsets(analysis):
    """The expectation for a moon must come only from EARLIER moons."""
    entries = build_track_record(analysis, basis="walk_forward", today=TODAY)
    scored = [e for e in entries if e.expected_offset_days is not None]
    assert scored, "fixture should produce scored entries"

    by_kind: dict[str, list] = {}
    for e in sorted(entries, key=lambda e: e.moon_date):
        seen = by_kind.setdefault(e.kind, [])
        if e.expected_offset_days is not None:
            # n_prior counts matched pairs strictly before this moon.
            assert e.n_prior == len(seen), (
                f"{e.moon_date} claimed {e.n_prior} prior pairs, {len(seen)} exist"
            )
        if e.actual_offset_days is not None:
            seen.append(e.actual_offset_days)


def test_no_expectation_below_the_minimum_sample(analysis):
    entries = build_track_record(analysis, basis="walk_forward", today=TODAY)
    for e in entries:
        if e.n_prior < MIN_PRIOR_MATCHES:
            assert e.expected_offset_days is None
            assert e.error_days is None
            assert e.hit_window is None
            assert "prior matched pair" in e.note


def test_unmatched_moon_is_undecidable_not_a_miss(analysis):
    entries = build_track_record(analysis, basis="walk_forward", today=TODAY)
    unmatched = [e for e in entries if e.actual_pivot_date is None]
    assert unmatched, "the fixture should contain moons with no matching pivot"
    for e in unmatched:
        assert e.error_days is None
        assert e.hit_window is None, "an unmatched moon must never be scored False"


def test_summary_counts_only_fully_scored_entries(analysis):
    entries = build_track_record(analysis, basis="walk_forward", today=TODAY)
    summary = track_record_summary(entries)
    for key in ("full_moon_to_high", "new_moon_to_low"):
        block = summary[key]
        kind = "Top" if key == "full_moon_to_high" else "Bottom"
        subset = [e for e in entries if e.kind == kind]
        assert block["n_moons"] == len(subset)
        assert block["n_scored"] == sum(1 for e in subset if e.error_days is not None)
        assert block["n_scored"] <= block["n_moons"]


def test_error_is_actual_minus_expected(analysis):
    entries = build_track_record(analysis, basis="walk_forward", today=TODAY)
    for e in entries:
        if e.error_days is not None:
            assert e.error_days == pytest.approx(
                e.actual_offset_days - e.expected_offset_days, abs=0.01
            )


def test_open_moons_are_excluded(analysis):
    """A moon inside the lag window has not resolved yet and must not appear."""
    max_lag = 14
    entries = build_track_record(analysis, basis="walk_forward", today=TODAY,
                                 max_lag=max_lag)
    cutoff = TODAY - dt.timedelta(days=max_lag)
    assert entries
    assert all(e.moon_date <= cutoff for e in entries)


def test_full_sample_basis_differs_from_walk_forward(analysis):
    """The two bases must not silently agree - the gap is the hindsight premium."""
    wf = track_record_summary(build_track_record(analysis, "walk_forward", TODAY))
    fs = track_record_summary(build_track_record(analysis, "full_sample", TODAY))
    assert fs["full_moon_to_high"]["basis"] == "full_sample"
    assert wf["full_moon_to_high"]["basis"] == "walk_forward"
    # full_sample sees every offset for every moon, so more entries get an
    # expectation at all.
    assert (fs["full_moon_to_high"]["n_scored"]
            >= wf["full_moon_to_high"]["n_scored"])


def test_rejects_unknown_basis(analysis):
    with pytest.raises(ValueError, match="basis must be one of"):
        build_track_record(analysis, basis="hindsight", today=TODAY)


def test_frame_is_newest_first(analysis):
    entries = build_track_record(analysis, basis="walk_forward", today=TODAY)
    df = track_record_frame(entries)
    assert list(df["moon_date"]) == sorted(df["moon_date"], reverse=True)
