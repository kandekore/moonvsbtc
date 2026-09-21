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


def test_protocol_definition_is_low_based_not_close_based():
    """Guards against the exact bug that shipped in v1.0 of this record.

    The New-Moon test is defined on intraday LOWS. If this ever reads 'close'
    again, the test is measuring the wrong thing.
    """
    rules = SEPTEMBER_2026_PROTOCOL["rules"]
    definition = rules["strict_local_low_definition"]
    assert "LOW[t] < LOW[t-1], LOW[t-2], LOW[t-3]" in definition
    assert "LOW[t] < LOW[t+1], LOW[t+2], LOW[t+3]" in definition
    assert "not closing prices" in definition.lower() or "NOT used" in rules["price_basis"]
    assert "close" not in definition.lower().replace("closing prices", "")


def test_protocol_states_a_later_lower_low_does_not_invalidate():
    assert "NOT invalidated by a lower low" in SEPTEMBER_2026_PROTOCOL["rules"]["invalidation"]


def test_protocol_keeps_the_five_concepts_distinct():
    """The conflation that caused the original error is now named explicitly."""
    distinct = SEPTEMBER_2026_PROTOCOL["rules"]["distinct_concepts"]
    assert set(distinct) == {
        "qualifying_strict_local_low", "lowest_price_in_a_wider_window",
        "absolute_cycle_low", "informal_nm_plus_0_4",
        "legacy_website_new_moon_pivot",
    }


def test_protocol_carries_the_correction_record():
    c = SEPTEMBER_2026_PROTOCOL["correction"]
    assert "never the paper's rule" in c["what_was_wrong"]
    assert "did not change" in c["why_this_is_a_correction_not_an_amendment"]


# --- the strict 7-day LOW pivot rule --------------------------------------
def test_strict_pivot_rule_is_low_based_and_raises_on_close_only(price_df):
    """Passing a close-only frame must fail loudly, not answer the wrong question."""
    from btcmoon.research.pivots import check_day

    with pytest.raises(KeyError, match="required for strict pivot detection"):
        check_day(price_df, dt.date(2026, 9, 11))


def test_strict_pivot_rule_exact_comparisons(ohlc_df):
    """Verify the rule against hand-checked numbers for 11 September 2026."""
    from btcmoon.research.pivots import check_day

    c = check_day(ohlc_df, dt.date(2026, 9, 11))
    assert c.qualifies is True
    assert c.low == pytest.approx(76162.91, abs=0.01)
    assert c.back == pytest.approx([76470.64, 77768.15, 77635.69], abs=0.01)
    assert c.forward == pytest.approx([77045.00, 76498.38, 76367.38], abs=0.01)


def test_strict_pivot_requires_strict_inequality(ohlc_df):
    """A tie must not qualify. Equality is handled identically on both sides."""
    import pandas as pd

    from btcmoon.research.pivots import is_strict_local_low

    df = ohlc_df.copy()
    # Force a tie between the candidate and its t+1 neighbour.
    df.loc[pd.Timestamp("2026-09-12"), "low"] = df.loc[pd.Timestamp("2026-09-11"), "low"]
    assert is_strict_local_low(df, dt.date(2026, 9, 11), strict=True) is False
    assert is_strict_local_low(df, dt.date(2026, 9, 11), strict=False) is True


def test_undecidable_days_return_none_not_false(ohlc_df):
    """A day without three subsequent bars is UNDETERMINED, never 'failed'."""
    from btcmoon.research.pivots import is_strict_local_low

    last = ohlc_df.index.max().date()
    assert is_strict_local_low(ohlc_df, last) is None


def test_rule_reproduces_the_papers_2026_claim(ohlc_df):
    """The paper: 7 of the first 8 New Moons of 2026 had a strict local low in
    T0:T+3, and all 8 were within +/-7 days.

    Reproducing this is the evidence that the LOW-based rule is the right one.
    The close-based rule that shipped in v1.0 reproduces 1/8.
    """
    from btcmoon.lunar.phases import moon_events
    from btcmoon.research.pivots import find_strict_local_lows

    new_moons = moon_events(dt.date(2026, 1, 1), dt.date(2026, 9, 30), "new_moon")[:8]
    in_window = 0
    within_7 = 0
    for e in new_moons:
        t0 = e.exact_at.date()
        if find_strict_local_lows(ohlc_df, t0, t0 + dt.timedelta(days=3)):
            in_window += 1
        if find_strict_local_lows(ohlc_df, t0 - dt.timedelta(days=7),
                                  t0 + dt.timedelta(days=7)):
            within_7 += 1
    assert in_window == 7, "the paper's 7-of-8 claim must reproduce exactly"
    assert within_7 == 8, "all 8 should have a strict local low within +/-7 days"


# --- the two frozen New-Moon tests ----------------------------------------
def test_september_nm_low_test_passed(ohlc_df):
    """A qualifying strict local low DID form, on 11 September, at NM+0."""
    result = evaluate_nm_low_test(ohlc_df, dt.datetime(2026, 9, 11, 3, 26, 55))
    assert result.strict_low_formed is True
    assert result.pivot_date == dt.date(2026, 9, 11)
    assert result.pivot_low == pytest.approx(76162.91, abs=0.01)
    assert result.lag_days == 0


def test_august_nm_low_test_passed_at_nm_plus_2(ohlc_df):
    """The contemporaneous note - '12 Aug New Moon -> 14 Aug local low' - was right."""
    result = evaluate_nm_low_test(ohlc_df, dt.datetime(2026, 8, 12, 17, 36, 39))
    assert result.strict_low_formed is True
    assert result.pivot_date == dt.date(2026, 8, 14)
    assert result.pivot_low == pytest.approx(62487.70, abs=0.01)
    assert result.lag_days == 2


def test_later_lower_lows_are_reported_but_do_not_invalidate(ohlc_df):
    """The distinction the original implementation got wrong."""
    result = evaluate_nm_low_test(ohlc_df, dt.datetime(2026, 9, 11, 3, 26, 55))
    assert result.strict_low_formed is True          # still passes ...
    assert result.lower_lows_within_7d               # ... despite deeper lows later
    lags = {d["lag_days"] for d in result.lower_lows_within_7d}
    assert 4 in lags, "the NM+4 lower low must be recorded as context"


def test_cycle_low_is_reported_separately(ohlc_df):
    """The absolute cycle low is a different measure from the qualifying pivot."""
    result = evaluate_nm_low_test(ohlc_df, dt.datetime(2026, 9, 11, 3, 26, 55))
    assert result.cycle_low_date == dt.date(2026, 9, 15)
    assert result.cycle_low == pytest.approx(74944.59, abs=0.01)
    assert result.cycle_low < result.pivot_low
    assert result.cycle_low_date != result.pivot_date


def test_candidate_working_is_recorded_for_every_day(ohlc_df):
    """Every candidate day's comparison is auditable, pass or fail."""
    result = evaluate_nm_low_test(ohlc_df, dt.datetime(2026, 9, 11, 3, 26, 55))
    assert len(result.candidates) == 4
    for c in result.candidates:
        assert c.low is not None
        assert len(c.back) == 3 and len(c.forward) == 3
        if c.qualifies is False:
            assert c.reason, "a failing day must say which comparison failed"


def test_upside_measured_from_the_qualifying_pivot(ohlc_df):
    result = evaluate_nm_low_test(ohlc_df, dt.datetime(2026, 9, 11, 3, 26, 55))
    assert result.upside_7d_pct == pytest.approx(6.79, abs=0.05)
    # 14 and 21 day horizons extend beyond the fixture: pending, never faked.
    assert result.upside_14d_pct is None
    assert result.upside_21d_pct is None


def test_evaluator_rejects_a_close_only_frame(price_df):
    with pytest.raises(KeyError, match="requires daily OHLC"):
        evaluate_nm_low_test(price_df, dt.date(2026, 9, 11))


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
