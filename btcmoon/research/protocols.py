"""Frozen research protocols.

A protocol states, in advance and in machine-readable form, exactly how a test
will be judged. Once frozen it is never edited - a genuine change is a new
version with a ``supersedes`` link (spec s8, s9, Appendix).
"""
from __future__ import annotations

import datetime as dt
import json
from dataclasses import dataclass

import numpy as np
import pandas as pd

from ..models import Provenance, ResearchProtocol, Status
from .legacy import WEBSITE_METHODOLOGY

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
    "version": "1.0",
    "title": "Frozen protocol: September 2026 New-Moon low test",
    "summary": (
        "A prospective, pre-registered test of the New-Moon / local-low lead. "
        "Registered before the window opened and not modified in response to "
        "any outcome."
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
            "A daily close on day D in [T0, T+3] that is strictly lower than every "
            "other daily close in [T0-2, T+5]. Fixed in advance so the answer "
            "cannot be argued after the fact."
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
        "final_review": "After 30 September 2026.",
        "amendment_policy": (
            "None. Lag windows, pivot definitions, scoring weights and the strength "
            "formula are fixed for the duration of this test."
        ),
    },
}

ALL_PROTOCOLS = (WEBSITE_METHODOLOGY_PROTOCOL, SEPTEMBER_2026_PROTOCOL)


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
    new_moon_date: dt.date
    window_start: dt.date
    window_end: dt.date
    strict_low_formed: bool
    low_date: dt.date | None
    low_price: float | None
    offset_days: int | None
    upside_7d_pct: float | None = None
    upside_14d_pct: float | None = None
    upside_21d_pct: float | None = None
    high_7d: float | None = None
    high_14d: float | None = None
    high_21d: float | None = None
    note: str = ""

    def to_dict(self) -> dict:
        return {
            "new_moon_date": self.new_moon_date.isoformat(),
            "window": f"{self.window_start.isoformat()}..{self.window_end.isoformat()}",
            "strict_low_formed": self.strict_low_formed,
            "low_date": self.low_date.isoformat() if self.low_date else None,
            "low_price": self.low_price,
            "offset_days": self.offset_days,
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
    new_moon_date: dt.date,
    t_plus: int = 3,
    guard_before: int = 2,
    guard_after: int = 5,
) -> NewMoonLowTest:
    """Apply the frozen T0:T+3 strict-local-low test to real price data.

    The definition is the one registered in the protocol: the candidate close
    must be strictly lower than every other close in [T0-guard_before,
    T0+t_plus+guard_after]. Upside is then measured at exactly 7, 14 and 21
    days from the pivot.
    """
    series = price["close"]
    t0 = new_moon_date
    win_end = t0 + dt.timedelta(days=t_plus)
    guard_lo = t0 - dt.timedelta(days=guard_before)
    guard_hi = win_end + dt.timedelta(days=guard_after)

    guard = series.loc[pd.Timestamp(guard_lo): pd.Timestamp(guard_hi)]
    window = series.loc[pd.Timestamp(t0): pd.Timestamp(win_end)]
    if window.empty or guard.empty:
        return NewMoonLowTest(t0, t0, win_end, False, None, None, None,
                              note="No price data covering the window.")

    cand_pos = int(np.argmin(window.to_numpy()))
    cand_date = window.index[cand_pos].date()
    cand_price = float(window.iloc[cand_pos])

    others = guard.drop(index=window.index[cand_pos], errors="ignore")
    strict = bool(others.empty or cand_price < float(others.min()))

    result = NewMoonLowTest(
        new_moon_date=t0, window_start=t0, window_end=win_end,
        strict_low_formed=strict, low_date=cand_date, low_price=round(cand_price, 2),
        offset_days=(cand_date - t0).days,
    )
    if not strict:
        result.note = (
            "Lowest close in T0:T+3 was not strictly lower than the surrounding "
            f"guard window [{guard_lo} .. {guard_hi}]; the test records this as "
            "NOT a strict local low."
        )

    # Upside from the pivot, measured at exactly 7/14/21 days.
    for days in (7, 14, 21):
        end = cand_date + dt.timedelta(days=days)
        leg = series.loc[pd.Timestamp(cand_date): pd.Timestamp(end)]
        if leg.empty or pd.Timestamp(end) > series.index.max():
            continue
        high = float(leg.max())
        setattr(result, f"high_{days}d", round(high, 2))
        setattr(
            result, f"upside_{days}d_pct",
            round((high - cand_price) / cand_price * 100.0, 2),
        )
    return result
