"""Lunar, natal, Pattern Fit and frozen-protocol evaluation."""
from __future__ import annotations

import datetime as dt

import pytest

from btcmoon.astrology.natal import (
    BTC_NATAL_MOMENT, NATAL_CHART_ASSUMPTIONS, natal_chart, transits_for,
)
from btcmoon.lunar.phases import lunar_context, new_moon_strength, scored_events
from btcmoon.research.pattern_fit import PATTERN_FIT_WEIGHTS, pattern_fit_score
from btcmoon.research.protocols import SEPTEMBER_2026_PROTOCOL, evaluate_nm_low_test


# --- lunar ----------------------------------------------------------------
def test_frozen_protocol_moon_instants_are_exact():
    """The September protocol names 11 Sep 03:27 UTC and 26 Sep 16:49 UTC."""
    events = scored_events(dt.date(2026, 9, 1), dt.date(2026, 9, 30))
    by_type = {e.event_type: e for e in events}

    nm = by_type["new_moon"].exact_at
    assert (nm.date(), nm.hour, nm.minute) == (dt.date(2026, 9, 11), 3, 26)

    fm = by_type["full_moon"].exact_at
    assert (fm.date(), fm.hour, fm.minute) == (dt.date(2026, 9, 26), 16, 48)


def test_august_full_moon_was_nodally_aligned():
    """The archive claims the 28 Aug 2026 Full Moon was strongly nodally aligned."""
    events = scored_events(dt.date(2026, 8, 20), dt.date(2026, 8, 31), "full_moon")
    fm = events[0]
    assert fm.exact_at.date() == dt.date(2026, 8, 28)
    assert fm.nodal_distance_deg < 10.0, "expected tight nodal alignment"


def test_strength_score_is_bounded_and_decomposed():
    for e in scored_events(dt.date(2026, 1, 1), dt.date(2026, 12, 31)):
        assert 0.0 <= e.strength_score <= 100.0
        assert set(e.strength_components) >= {
            "nodal_alignment", "perigee_proximity", "eclipse_geometry",
        }


def test_strength_is_context_not_part_of_pattern_fit(price_df):
    """Nodal strength must never inflate the Pattern Fit Score (spec s8)."""
    fit = pattern_fit_score(price_df, dt.date(2026, 8, 12), dt.date(2026, 8, 28),
                            dt.date(2026, 9, 11))
    assert set(fit.components) == set(PATTERN_FIT_WEIGHTS)
    assert "nodal" not in " ".join(fit.components).lower()
    assert "strength" not in " ".join(fit.components).lower()


def test_lunar_context_offsets_are_consistent():
    ctx = lunar_context(dt.datetime(2026, 9, 21, 12, 0))
    assert ctx.days_since_new_moon > 0
    assert ctx.days_to_next_full_moon > 0
    assert ctx.last_new_moon < ctx.as_of < ctx.next_new_moon


# --- pattern fit ----------------------------------------------------------
def test_pattern_fit_weights_total_one_hundred():
    assert sum(PATTERN_FIT_WEIGHTS.values()) == 100.0


def test_pattern_fit_weights_are_four_equal_quarters():
    assert set(PATTERN_FIT_WEIGHTS.values()) == {25.0}


def test_pattern_fit_score_is_bounded(price_df):
    fit = pattern_fit_score(price_df, dt.date(2026, 8, 12), dt.date(2026, 8, 28),
                            dt.date(2026, 9, 11))
    assert 0.0 <= fit.score <= 100.0
    assert fit.score == pytest.approx(sum(fit.components.values()), abs=0.01)


def test_waxing_component_rewards_a_rise_only(price_df):
    """August 2026 rose 22.8% from New Moon to Full Moon - full marks."""
    fit = pattern_fit_score(price_df, dt.date(2026, 8, 12), dt.date(2026, 8, 28),
                            dt.date(2026, 9, 11))
    assert fit.components["waxing_appreciation"] == 25.0
    assert fit.detail["waxing"]["change_pct"] > 0


# --- frozen September protocol -------------------------------------------
def test_september_protocol_records_both_strength_figures():
    """79/100 was recorded in advance; the code computes 69.2. Both are kept."""
    rules = SEPTEMBER_2026_PROTOCOL["rules"]
    assert rules["new_moon_strength_recorded_in_advance"] == 79
    assert "69.2" in rules["strength_caveat"]
    assert "breach the research constitution" in rules["strength_caveat"]


def test_september_protocol_forbids_amendment():
    assert SEPTEMBER_2026_PROTOCOL["rules"]["amendment_policy"].startswith("None")


def test_september_nm_low_test_failed_honestly(price_df):
    """The pre-registered T0:T+3 test did NOT pass, and must report that.

    The lowest close in 11-14 Sep was 13 Sep at $76,838 (NM+2), but a lower
    close came on 15 Sep at $75,613 (NM+4), outside the window.
    """
    result = evaluate_nm_low_test(price_df, dt.date(2026, 9, 11))
    assert result.strict_low_formed is False
    assert result.low_date == dt.date(2026, 9, 13)
    assert result.low_price == pytest.approx(76838.16, abs=0.5)
    assert result.offset_days == 2
    assert "not strictly lower" in result.note


def test_nm_low_test_measures_upside_at_exact_horizons(price_df):
    result = evaluate_nm_low_test(price_df, dt.date(2026, 9, 11))
    assert result.upside_7d_pct is not None
    assert result.high_7d is not None
    # 14 and 21 day horizons extend beyond the fixture; they stay None, not faked.
    assert result.upside_21d_pct is None


def test_august_shows_the_same_nm2_then_nm4_shape(price_df):
    """August's low also came at NM+4, not the NM+2 first reaction."""
    result = evaluate_nm_low_test(price_df, dt.date(2026, 8, 12))
    assert result.low_date is not None
    # The true cycle low was 16 Aug = NM+4.
    low = price_df["close"].loc["2026-08-08":"2026-08-20"].idxmin().date()
    assert low == dt.date(2026, 8, 16)
    assert (low - dt.date(2026, 8, 12)).days == 4


# --- natal ----------------------------------------------------------------
def test_natal_moment_is_the_genesis_block():
    assert BTC_NATAL_MOMENT == dt.datetime(2009, 1, 3, 18, 15, 5)


def test_natal_chart_states_that_houses_are_not_calculated():
    assert "NOT calculated" in NATAL_CHART_ASSUMPTIONS["location"]
    assert "no established causal mechanism" in " ".join(NATAL_CHART_ASSUMPTIONS["caveats"])


def test_natal_positions_are_stable():
    """The natal chart never changes; pin it so a library upgrade cannot move it."""
    chart = natal_chart()["positions"]
    assert chart["Sun"]["sign"] == "Capricorn"
    assert chart["Moon"]["sign"] == "Aries"
    assert chart["Saturn"]["sign"] == "Virgo"
    assert chart["Neptune"]["sign"] == "Aquarius"


def test_transits_are_sorted_strongest_first():
    hits = transits_for(dt.date(2026, 9, 22))
    assert hits
    weights = [t.weight for t in hits]
    assert weights == sorted(weights, reverse=True)


def test_transit_orbs_respect_the_configured_limits():
    from btcmoon.astrology.natal import ASPECTS

    for t in transits_for(dt.date(2026, 9, 22)):
        assert t.orb_deg <= ASPECTS[t.aspect][1]
