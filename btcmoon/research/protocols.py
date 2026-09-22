"""Frozen research protocols.

A protocol states, in advance and in machine-readable form, exactly how a test
will be judged. Once frozen it is never edited - a genuine change is a new
version with a ``supersedes`` link (spec s8, s9, Appendix).
"""
from __future__ import annotations

import datetime as dt
import json
from dataclasses import dataclass, field

import numpy as np
import pandas as pd

from ..models import Provenance, ResearchProtocol, Status
from .legacy import WEBSITE_METHODOLOGY
from .pivots import check_day, find_strict_local_lows, is_strict_local_low

# ---------------------------------------------------------------------------
# Protocol 1 - the legacy website methodology, recorded so it can be cited.
# ---------------------------------------------------------------------------
WEBSITE_METHODOLOGY_PROTOCOL = {
    "slug": "website-methodology-v1",
    "version": "1.0",
    "title": "Legacy website methodology (Full Moon / New Moon pivot matching)",
    "summary": (
        "The method the original site used to produce the published Full-Moon lag "
        "figures. Reproduced exactly by moon_engine.py and pinned by regression "
        "tests. Recorded here so any future change is a new protocol version "
        "rather than a silent edit."
    ),
    "rules": {
        **WEBSITE_METHODOLOGY,
        "published_benchmarks": {
            "recent_two_year_full_moon": {
                "mean_days": 4.4, "median_days": 4, "sd_days": 4.2, "n": 5,
                "window_from": "2024-09-21",
            },
            "2017_2026_full_moon": {
                "pct_high_after_full_moon": 71.0, "mean_days": 3.2,
                "median_days": 6.0, "n": 31,
            },
        },
        "caveats": [
            "Phase-shift and null controls weaken any claim that the astronomical "
            "Full Moon uniquely causes the high.",
            "The New-Moon / local-low correspondence is the stronger empirical lead.",
            "Nodal strength is not a reliable timing predictor.",
        ],
    },
}

# ---------------------------------------------------------------------------
# Protocol 2 - the frozen September 2026 prospective test (spec s9).
# ---------------------------------------------------------------------------
SEPTEMBER_2026_PROTOCOL = {
    "slug": "september-2026-new-moon-test",
    "version": "1.1",
    "supersedes": "september-2026-new-moon-test v1.0",
    "title": "Frozen protocol: September 2026 New-Moon low test",
    "summary": (
        "A prospective, pre-registered test of the New-Moon / local-low lead. "
        "Registered before the window opened and not modified in response to any "
        "outcome. v1.1 corrects a TRANSCRIPTION ERROR in this repository's copy of "
        "the rule - see 'correction' below. The rule itself is unchanged from the "
        "paper and no result was ever published under v1.0."
    ),
    "window_start": "2026-09-11T03:26:55",
    "window_end": "2026-09-30T23:59:59",
    "rules": {
        "new_moon_utc": "2026-09-11T03:27:00",
        "full_moon_utc": "2026-09-26T16:49:00",
        "primary_test": (
            "Does a strict local low form in the window T0:T+3 "
            "(11-14 September 2026 inclusive)?"
        ),
        "strict_local_low_definition": (
            "A strict 7-day pivot on the daily LOW: a day t qualifies when "
            "LOW[t] < LOW[t-1], LOW[t-2], LOW[t-3] AND "
            "LOW[t] < LOW[t+1], LOW[t+2], LOW[t+3]. "
            "The test is on INTRADAY LOWS, not closing prices."
        ),
        "price_basis": "Daily OHLC. The LOW column only. Closing prices are NOT used.",
        "equality_handling": (
            "Strictly less-than on both sides, as written. A low that merely ties a "
            "neighbouring low does not qualify. Applied identically on both sides, so "
            "a flat double bottom yields no pivot rather than two."
        ),
        "decidability": (
            "A day cannot be judged until 3 subsequent daily bars exist. Until then "
            "the result is UNDETERMINED - never 'failed'."
        ),
        "invalidation": (
            "A qualifying pivot is NOT invalidated by a lower low occurring later, "
            "inside or outside the window. The test asks whether a strict local low "
            "FORMED in T0:T+3, not whether it was the cycle's lowest price. The "
            "deepest low of the cycle is a separate, separately reported measure."
        ),
        "new_moon_strength_recorded_in_advance": 79,
        "strength_caveat": (
            "The 79/100 figure was recorded in advance as context only. It is NOT "
            "evidence that a low must occur, and it does not enter the Pattern Fit "
            "Score. The strength formula implemented in btcmoon.lunar.phases scores "
            "this same New Moon 69.2/100; the two numbers are kept separate rather "
            "than reconciled, because tuning a formula to reproduce a historical "
            "figure would breach the research constitution."
        ),
        "if_low_forms": (
            "Measure maximum upside at exactly 7, 14 and 21 days from the pivot date."
        ),
        "secondary_tests": [
            "Waxing return from the New-Moon low to the Full Moon (26 Sep).",
            "Cycle-high alignment relative to the Full Moon.",
            "Relationship to a website-defined major high (see website-methodology-v1).",
        ],
        "distinct_concepts": {
            "qualifying_strict_local_low": "The formal pre-registered test. LOW-based 7-day pivot in T0:T+3.",
            "lowest_price_in_a_wider_window": "Descriptive only. Not the test.",
            "absolute_cycle_low": "The deepest low between consecutive New Moons. Reported separately.",
            "informal_nm_plus_0_4": (
                "A private, never-pre-registered intraday timing idea. Requires hourly "
                "data. Must never stand in for, or be conflated with, the formal test."
            ),
            "legacy_website_new_moon_pivot": (
                "CLOSE-based scipy.signal.find_peaks major pivot, spacing 30, prominence "
                "15% of median close, matched within +/-14 days. A different measure "
                "entirely - see website-methodology-v1."
            ),
        },
        "final_review": "After 30 September 2026.",
        "amendment_policy": (
            "None. Lag windows, pivot definitions, scoring weights and the strength "
            "formula are fixed for the duration of this test."
        ),
    },
    "correction": {
        "corrected_on": "2026-09-21",
        "what_was_wrong": (
            "v1.0 of THIS REPOSITORY'S protocol record stated the strict local low as "
            "'a daily CLOSE in [T0, T+3] strictly lower than every other close in "
            "[T0-2, T+8]'. That definition was written by the implementer and was "
            "never the paper's rule. The paper defines a strict 7-day pivot on the "
            "daily LOW."
        ),
        "why_this_is_a_correction_not_an_amendment": (
            "The research protocol did not change. The repository's transcription of "
            "it was wrong and has been corrected to match the paper. No result was "
            "published under v1.0; all records were drafts."
        ),
        "evidence_the_corrected_rule_is_the_right_one": (
            "The paper states that in 2026, 7 of the first 8 New Moons had a strict "
            "local low in T0:T+3 and all 8 were within +/-7 days. The LOW-based 7-day "
            "pivot rule reproduces that exactly (7/8, all 8 within +/-7). The erroneous "
            "CLOSE-based rule reproduces 1/8."
        ),
    },
}

# ---------------------------------------------------------------------------
# Protocol 3 - exact intraday lunar offset. NEW, PROSPECTIVE, QUARANTINED.
#
# This is a separate protocol, not a new version of website-methodology-v1. It
# measures a different quantity (elapsed hours, not calendar days) and its
# results are never merged with, or substituted for, the legacy figures.
# ---------------------------------------------------------------------------
INTRADAY_OFFSET_PROTOCOL = {
    "slug": "intraday-lunar-offset-v1",
    "version": "1.0",
    "title": "Exact intraday lunar offset (hours from syzygy to pivot)",
    "summary": (
        "Measures the interval from the exact UTC instant of a Full or New Moon "
        "to the exact UTC timestamp of the corresponding BTC pivot, in hours. "
        "Collected prospectively from 2026-09-22. It does NOT reinterpret, "
        "replace or recompute the legacy calendar-day methodology or its "
        "published +4.4 d / +3.2 d / 71% figures."
    ),
    "window_start": "2026-09-22T00:00:00",
    "rules": {
        "measured_quantity": "pivot_instant_utc - syzygy_instant_utc",
        "units": "hours (fractional days reported for readability only)",
        "moon_instant_source": (
            "PyEphem next_full_moon / next_new_moon, exact UTC instant. NOT "
            "reduced to a calendar date - that reduction is what this metric "
            "exists to avoid."
        ),
        "price_basis": (
            "Intraday bars, hourly or finer. Pivot = highest HIGH (Full Moon) or "
            "lowest LOW (New Moon) in the window. Closing prices are not used."
        ),
        "window": "T0 to T0+14 days, forward only (no look-back into the prior phase).",
        "minimum_bar_resolution": "60 minutes; daily bars are rejected outright.",
        "effective_from": "2026-09-22",
        "earliest_reliable_hourly_data": "2024-09-01",
        "back_fitting": (
            "FORBIDDEN. This metric is never applied to the historical sample "
            "that produced the published calendar-day statistics. Hourly history "
            "does not reach far enough back, and re-specifying the measurement "
            "that generated a published claim would invalidate the claim rather "
            "than refine it."
        ),
        "relationship_to_legacy": {
            "website-methodology-v1": (
                "Untouched. Its +4.4 d recent mean, +3.2 d 2017-2026 mean, 71% "
                "after-full-moon share and 6.0 d median remain the reproduced "
                "figures of the historical calendar-day sample."
            ),
            "comparability": (
                "NONE at the value level. A fractional-hour offset and an integer "
                "calendar-day lag are different measurements. They may be "
                "reported side by side; they must never be averaged, differenced "
                "or presented as the same series."
            ),
        },
        "worked_example": {
            "event": "Full Moon 2026-08-28 04:18:26 UTC",
            "calendar_day_result": "FM+6 (high printed during 3 September 2026)",
            "intraday_result": (
                "Not measured - precedes effective_from, and is recorded under "
                "the legacy calendar-day methodology only."
            ),
        },
    },
}

ALL_PROTOCOLS = (
    WEBSITE_METHODOLOGY_PROTOCOL,
    SEPTEMBER_2026_PROTOCOL,
    INTRADAY_OFFSET_PROTOCOL,
)


def seed_protocols(session, freeze: bool = True) -> list[ResearchProtocol]:
    """Insert the protocols if absent. Existing frozen rows are never touched."""
    created = []
    for spec in ALL_PROTOCOLS:
        existing = (
            session.query(ResearchProtocol)
            .filter_by(slug=spec["slug"], version=spec["version"])
            .one_or_none()
        )
        if existing:
            continue
        proto = ResearchProtocol(
            slug=spec["slug"],
            version=spec["version"],
            title=spec["title"],
            summary=spec["summary"],
            rules_json=json.dumps(spec["rules"], indent=2),
            status=Status.PUBLISHED,
            provenance=Provenance.EDITOR,
        )
        if spec.get("window_start"):
            proto.window_start = dt.datetime.fromisoformat(spec["window_start"])
        if spec.get("window_end"):
            proto.window_end = dt.datetime.fromisoformat(spec["window_end"])
        if freeze:
            proto.freeze()
        session.add(proto)
        created.append(proto)
    session.flush()
    return created


# ---------------------------------------------------------------------------
# Evaluating the frozen September test against real market data
# ---------------------------------------------------------------------------
@dataclass
class NewMoonLowTest:
    """The result of the frozen T0:T+3 test, with every distinct measure kept apart."""

    new_moon_utc: dt.datetime
    window_start: dt.date
    window_end: dt.date
    #: True / False / None. None means "not yet decidable", never "failed".
    strict_low_formed: bool | None
    #: The qualifying pivot, if one formed.
    pivot_date: dt.date | None
    pivot_low: float | None
    lag_days: int | None
    #: Full working for each candidate day, so the result can be audited.
    candidates: list = field(default_factory=list)
    #: Descriptive extras - explicitly NOT part of the pass/fail decision.
    lower_lows_within_7d: list = field(default_factory=list)
    cycle_low_date: dt.date | None = None
    cycle_low: float | None = None
    upside_7d_pct: float | None = None
    upside_14d_pct: float | None = None
    upside_21d_pct: float | None = None
    high_7d: float | None = None
    high_14d: float | None = None
    high_21d: float | None = None
    note: str = ""

    def to_dict(self) -> dict:
        return {
            "new_moon_utc": self.new_moon_utc.isoformat(),
            "window": f"{self.window_start.isoformat()}..{self.window_end.isoformat()}",
            "strict_low_formed": self.strict_low_formed,
            "pivot_date": self.pivot_date.isoformat() if self.pivot_date else None,
            "pivot_low": self.pivot_low,
            "lag_days": self.lag_days,
            "candidates": [c.to_dict() for c in self.candidates],
            "lower_lows_within_7d": self.lower_lows_within_7d,
            "cycle_low_date": self.cycle_low_date.isoformat() if self.cycle_low_date else None,
            "cycle_low": self.cycle_low,
            "upside_7d_pct": self.upside_7d_pct,
            "upside_14d_pct": self.upside_14d_pct,
            "upside_21d_pct": self.upside_21d_pct,
            "high_7d": self.high_7d,
            "high_14d": self.high_14d,
            "high_21d": self.high_21d,
            "note": self.note,
        }


def evaluate_nm_low_test(
    price: pd.DataFrame,
    new_moon: dt.date | dt.datetime,
    t_plus: int = 3,
) -> NewMoonLowTest:
    """Apply the frozen T0:T+3 strict-local-low test to real daily OHLC data.

    The rule is the pre-registered one and is defined on the daily **LOW**:

        LOW[t] < LOW[t-1], LOW[t-2], LOW[t-3]
        AND LOW[t] < LOW[t+1], LOW[t+2], LOW[t+3]

    A qualifying pivot is NOT invalidated by a later lower low. Lower lows and
    the absolute cycle low are reported separately, as descriptive context.

    ``price`` must be an OHLC frame (``market_data.get_ohlc_history``). Passing a
    close-only frame raises rather than silently answering the wrong question.
    """
    if isinstance(new_moon, dt.datetime):
        nm_dt, t0 = new_moon, new_moon.date()
    else:
        nm_dt, t0 = dt.datetime.combine(new_moon, dt.time()), new_moon

    win_end = t0 + dt.timedelta(days=t_plus)
    low = price["low"] if "low" in price.columns else None
    if low is None:
        raise KeyError(
            "evaluate_nm_low_test requires daily OHLC with a 'low' column. The "
            "New-Moon protocol is defined on intraday lows, not closing prices."
        )

    result = NewMoonLowTest(
        new_moon_utc=nm_dt, window_start=t0, window_end=win_end,
        strict_low_formed=None, pivot_date=None, pivot_low=None, lag_days=None,
    )

    # 1) The formal test: evaluate every candidate day, keeping the working.
    undecidable = False
    for i in range(t_plus + 1):
        day = t0 + dt.timedelta(days=i)
        check = check_day(price, day)
        result.candidates.append(check)
        if check.qualifies is None:
            undecidable = True
        elif check.qualifies and result.pivot_date is None:
            result.pivot_date = day
            result.pivot_low = check.low
            result.lag_days = i

    if result.pivot_date is not None:
        result.strict_low_formed = True
    elif undecidable:
        result.strict_low_formed = None
        result.note = (
            "UNDETERMINED: at least one candidate day does not yet have three "
            "subsequent daily bars, so the rule cannot be applied. Not a failure."
        )
    else:
        result.strict_low_formed = False
        result.note = (
            "No day in T0:T+3 satisfied the strict 7-day low pivot. See "
            "'candidates' for the exact comparison that failed on each day."
        )

    # 2) Descriptive context - deliberately separate from the pass/fail decision.
    if result.pivot_date is not None:
        near = low.loc[pd.Timestamp(t0 - dt.timedelta(days=7)):
                       pd.Timestamp(t0 + dt.timedelta(days=7))]
        # Compare against the UNROUNDED pivot low, and never list the pivot
        # itself: rounding to 2dp would otherwise make a bar look lower than
        # its own recorded value.
        pivot_raw = float(low.loc[pd.Timestamp(result.pivot_date)])
        result.lower_lows_within_7d = [
            {"date": ts.date().isoformat(), "low": round(float(v), 2),
             "lag_days": (ts.date() - t0).days}
            for ts, v in near.items()
            if ts.date() != result.pivot_date and float(v) < pivot_raw
        ]

    cycle_end = t0 + dt.timedelta(days=29)
    cycle = low.loc[pd.Timestamp(t0): pd.Timestamp(cycle_end)]
    if not cycle.empty:
        result.cycle_low_date = cycle.idxmin().date()
        result.cycle_low = round(float(cycle.min()), 2)

    # 3) Upside from the qualifying pivot, at exactly 7 / 14 / 21 days.
    if result.pivot_date and result.pivot_low:
        high = price["high"] if "high" in price.columns else price["close"]
        for days in (7, 14, 21):
            end = result.pivot_date + dt.timedelta(days=days)
            if pd.Timestamp(end) > high.index.max():
                continue
            leg = high.loc[pd.Timestamp(result.pivot_date): pd.Timestamp(end)]
            if leg.empty:
                continue
            peak = float(leg.max())
            setattr(result, f"high_{days}d", round(peak, 2))
            setattr(result, f"upside_{days}d_pct",
                    round((peak - result.pivot_low) / result.pivot_low * 100.0, 2))
    return result
