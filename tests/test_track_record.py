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
def ohlc(request):
    return request.getfixturevalue("ohlc_df")


@pytest.fixture(scope="module")
def analysis(ohlc):
    # The legacy engine is CLOSE-based; feed it closes only, exactly as the
    # live app does, so the frozen path is unchanged by these tests.
    return legacy_analysis(price_df=ohlc[["close"]].copy(), start="2014-09-17")


@pytest.fixture(scope="module")
def entries(analysis, ohlc):
    return build_track_record(analysis, basis="walk_forward", today=TODAY,
                              max_lag=MAX_LAG, ohlc=ohlc)


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


def test_extreme_is_the_true_intraday_extreme(ohlc, entries):
    """The extreme must be the highest HIGH / lowest LOW, not a close."""
    import pandas as pd
    for e in [x for x in entries if x.extreme_date is not None][:60]:
        lo = pd.Timestamp(e.moon_date) - pd.Timedelta(days=MAX_LAG)
        hi = pd.Timestamp(e.moon_date) + pd.Timedelta(days=MAX_LAG)
        w = ohlc.loc[lo:hi]
        if e.kind == "Top":
            assert e.extreme_source == "high"
            assert e.extreme_price == pytest.approx(w["high"].max(), abs=0.01)
            assert e.extreme_date == w["high"].idxmax().date()
        else:
            assert e.extreme_source == "low"
            assert e.extreme_price == pytest.approx(w["low"].min(), abs=0.01)
            assert e.extreme_date == w["low"].idxmin().date()


def test_intraday_extreme_differs_from_close_based(analysis, ohlc):
    """The whole point: a close can put the extreme on the wrong day."""
    close_run = build_track_record(analysis, today=TODAY, max_lag=MAX_LAG)
    intra_run = build_track_record(analysis, today=TODAY, max_lag=MAX_LAG, ohlc=ohlc)
    assert {e.extreme_source for e in close_run if e.extreme_source} == {"close"}
    by_date = {e.moon_date: e for e in close_run}
    moved = [
        e for e in intra_run
        if e.extreme_offset_days is not None
        and by_date[e.moon_date].extreme_offset_days != e.extreme_offset_days
    ]
    # Roughly half of all moons shift; assert it is substantial, not incidental.
    assert len(moved) > len(intra_run) // 4


def test_extreme_price_brackets_the_close(ohlc, entries):
    """A high must be >= that day's close; a low must be <= it."""
    for e in entries:
        if e.extreme_date is None:
            continue
        import pandas as pd
        bar = ohlc.loc[pd.Timestamp(e.extreme_date)]
        if e.kind == "Top":
            assert e.extreme_price >= float(bar["close"]) - 0.01
        else:
            assert e.extreme_price <= float(bar["close"]) + 0.01


def test_extreme_offset_never_exceeds_the_lag(entries):
    for e in entries:
        if e.extreme_offset_days is not None:
            assert abs(e.extreme_offset_days) <= MAX_LAG


def test_window_extreme_returns_none_outside_coverage(ohlc):
    first = ohlc.index.min().date()
    assert window_extreme(ohlc, first, "Top", MAX_LAG) is None


def test_extreme_column_falls_back_to_close(ohlc):
    from btcmoon.research.track_record import extreme_column
    assert extreme_column(ohlc, "Top") == "high"
    assert extreme_column(ohlc, "Bottom") == "low"
    closes = ohlc[["close"]]
    assert extreme_column(closes, "Top") == "close"
    assert extreme_column(closes, "Bottom") == "close"


# ---------------------------------------------------------------------------
# Turning point vs trending through
# ---------------------------------------------------------------------------
def test_boundary_extremes_are_flagged_as_trending(entries):
    flagged = [e for e in entries if e.extreme_at_window_edge]
    assert flagged, "a trending series must produce boundary extremes"
    for e in flagged:
        assert abs(e.extreme_offset_days) >= MAX_LAG - 1
        assert "boundary" in e.note


def test_turning_point_uses_the_strict_intraday_rule(ohlc, entries):
    """Tested on the same price basis as the extreme, not against close pivots."""
    from btcmoon.research.pivots import is_strict_local_high, is_strict_local_low
    for e in entries:
        if e.extreme_date is None or e.extreme_is_turning_point is None:
            continue
        expected = (is_strict_local_high(ohlc, e.extreme_date) if e.kind == "Top"
                    else is_strict_local_low(ohlc, e.extreme_date))
        assert e.extreme_is_turning_point is expected


def test_a_turn_is_strictly_beyond_its_neighbours(ohlc, entries):
    """Verify the rule directly on the bars, not via the helper."""
    import pandas as pd
    checked = 0
    for e in entries:
        if not e.extreme_is_turning_point:
            continue
        pos = ohlc.index.get_loc(pd.Timestamp(e.extreme_date))
        if pos < 3 or pos + 3 >= len(ohlc):
            continue
        col = "high" if e.kind == "Top" else "low"
        value = float(ohlc.iloc[pos][col])
        neighbours = [float(ohlc.iloc[pos + k][col])
                      for k in range(-3, 4) if k != 0]
        assert all(value > n for n in neighbours) if e.kind == "Top" \
            else all(value < n for n in neighbours)
        checked += 1
    assert checked > 50


def test_both_turns_and_non_turns_are_present(entries):
    """The flag must discriminate, not label everything the same way."""
    turns = [e for e in entries if e.extreme_is_turning_point is True]
    flat = [e for e in entries if e.extreme_is_turning_point is False]
    assert len(turns) > 50 and len(flat) > 20


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


def test_open_moons_are_excluded(analysis, ohlc):
    got = build_track_record(analysis, today=TODAY, max_lag=MAX_LAG, ohlc=ohlc)
    assert all(e.moon_date <= TODAY - dt.timedelta(days=MAX_LAG) for e in got)


def test_rejects_unknown_basis_measure_and_window(analysis, entries):
    with pytest.raises(ValueError, match="basis must be one of"):
        build_track_record(analysis, basis="hindsight", today=TODAY)
    with pytest.raises(ValueError, match="measure must be one of"):
        track_record_summary(entries, measure="vibes")
    with pytest.raises(ValueError, match="window_mode must be one of"):
        build_track_record(analysis, today=TODAY, window_mode="sideways")


# ---------------------------------------------------------------------------
# Symmetric vs forward search window
# ---------------------------------------------------------------------------
def test_forward_window_never_looks_back(analysis, ohlc):
    fwd = build_track_record(analysis, today=TODAY, max_lag=MAX_LAG, ohlc=ohlc,
                             window_mode="forward")
    for e in fwd:
        if e.extreme_offset_days is not None:
            assert 0 <= e.extreme_offset_days <= MAX_LAG


def test_symmetric_window_can_borrow_from_the_previous_cycle(analysis, ohlc):
    """The 12 Aug 2026 New Moon is the worked example of the failure mode."""
    sym = {e.moon_date: e for e in build_track_record(
        analysis, today=TODAY, max_lag=MAX_LAG, ohlc=ohlc, window_mode="symmetric")}
    fwd = {e.moon_date: e for e in build_track_record(
        analysis, today=TODAY, max_lag=MAX_LAG, ohlc=ohlc, window_mode="forward")}
    moon = dt.date(2026, 8, 12)
    assert sym[moon].extreme_offset_days == -9      # belongs to the prior phase
    assert fwd[moon].extreme_offset_days == 2       # matches the T0:T+3 protocol


def test_forward_window_lowers_mean_absolute_error(analysis, ohlc):
    """Not a tuning knob - it removes extremes credited to the wrong cycle."""
    def mae(mode):
        entries = build_track_record(analysis, today=TODAY, max_lag=MAX_LAG,
                                      ohlc=ohlc, window_mode=mode)
        return track_record_summary(entries)["new_moon_to_low"][
            "mean_absolute_error_days"]
    assert mae("forward") < mae("symmetric")


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


def test_placebo_uses_the_same_window_for_real_and_random(analysis, ohlc):
    base = placebo_baseline(analysis, max_lag=MAX_LAG, n_trials=500, seed=0,
                            today=TODAY, ohlc=ohlc)
    for key in ("full_moon_to_high", "new_moon_to_low"):
        b = base[key]
        assert b["window_days"] is not None
        assert b["n_real"] > 100 and b["n_trials"] > 100
        assert 0 <= b["real_hit_rate_pct"] <= 100
        assert 0 <= b["placebo_hit_rate_pct"] <= 100
        assert b["edge_pct"] == pytest.approx(
            b["real_hit_rate_pct"] - b["placebo_hit_rate_pct"], abs=0.11)
        assert b["edge_se_pct"] > 0


def test_placebo_is_deterministic_for_a_seed(analysis, ohlc):
    kw = dict(max_lag=MAX_LAG, n_trials=300, seed=7, today=TODAY, ohlc=ohlc)
    assert placebo_baseline(analysis, **kw) == placebo_baseline(analysis, **kw)


def test_frame_is_newest_first(entries):
    df = track_record_frame(entries)
    assert list(df["moon_date"]) == sorted(df["moon_date"], reverse=True)
