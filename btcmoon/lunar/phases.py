"""Lunar phase calculations.

``moon_engine.moon_phases`` (the legacy, provenance-sensitive function) reduces
phases to calendar dates because that is what the published website methodology
did. This module keeps that function untouched and adds the *exact UTC instants*
plus the contextual measures the experiment protocol needs - without changing
any number the legacy methodology produces.
"""
from __future__ import annotations

import datetime as dt
import math
from dataclasses import dataclass, field

import ephem

#: Mean synodic month, days.
SYNODIC_MONTH = 29.530588853

PHASE_NAMES = (
    "New Moon", "Waxing Crescent", "First Quarter", "Waxing Gibbous",
    "Full Moon", "Waning Gibbous", "Last Quarter", "Waning Crescent",
)


@dataclass
class MoonEvent:
    """A new or full moon with its exact instant and research context."""

    event_type: str                 # "new_moon" | "full_moon"
    exact_at: dt.datetime           # UTC, tz-naive
    ecliptic_longitude_deg: float | None = None
    nodal_distance_deg: float | None = None
    distance_km: float | None = None
    strength_score: float | None = None
    strength_components: dict = field(default_factory=dict)

    @property
    def event_date(self) -> dt.date:
        return self.exact_at.date()

    @property
    def label(self) -> str:
        return "New Moon" if self.event_type == "new_moon" else "Full Moon"


def _to_datetime(ed: "ephem.Date") -> dt.datetime:
    return ed.datetime().replace(microsecond=0)


def moon_events(
    start: dt.date, end: dt.date, event_type: str = "both"
) -> list[MoonEvent]:
    """Every new/full moon whose exact instant falls in [start, end]."""
    wanted = (
        ("new_moon", "full_moon") if event_type == "both" else (event_type,)
    )
    out: list[MoonEvent] = []
    for kind in wanted:
        step = ephem.next_new_moon if kind == "new_moon" else ephem.next_full_moon
        cursor = step(dt.datetime(start.year, start.month, start.day) - dt.timedelta(days=1))
        while True:
            when = _to_datetime(cursor)
            if when.date() > end:
                break
            if when.date() >= start:
                out.append(_enrich(MoonEvent(event_type=kind, exact_at=when)))
            cursor = step(cursor)
    out.sort(key=lambda e: e.exact_at)
    return out


def _enrich(event: MoonEvent) -> MoonEvent:
    """Attach ecliptic longitude, lunar-node distance and geocentric distance."""
    when = ephem.Date(event.exact_at)
    moon = ephem.Moon(when)
    ecl = ephem.Ecliptic(moon)
    event.ecliptic_longitude_deg = round(math.degrees(float(ecl.lon)) % 360.0, 3)
    event.distance_km = round(float(moon.earth_distance) * ephem.meters_per_au / 1000.0, 1)
    event.nodal_distance_deg = round(_nodal_distance(when), 3)
    return event


def _lunar_node_longitude(when: "ephem.Date") -> float:
    """Mean ascending lunar node longitude (degrees), standard low-order series.

    Good to a few arc-minutes, which is far finer than the +/-15 deg bands the
    protocol uses for "nodally aligned".
    """
    jd = float(when) + 2415020.0          # ephem epoch -> Julian Day
    t = (jd - 2451545.0) / 36525.0        # Julian centuries from J2000.0
    omega = 125.04452 - 1934.136261 * t + 0.0020708 * t * t + (t ** 3) / 450000.0
    return omega % 360.0


def _nodal_distance(when: "ephem.Date") -> float:
    """Angular distance from the Moon to the nearest lunar node, 0-90 degrees.

    0 means the syzygy sits exactly on the node (eclipse geometry); 90 means it
    is as far from the nodal axis as possible.
    """
    moon_lon = math.degrees(float(ephem.Ecliptic(ephem.Moon(when)).lon)) % 360.0
    node = _lunar_node_longitude(when)
    diff = abs((moon_lon - node + 180.0) % 360.0 - 180.0)   # 0-180 to ascending node
    return min(diff, 180.0 - diff)                          # fold onto nearest node


def new_moon_strength(event: MoonEvent) -> tuple[float, dict]:
    """Score a new/full moon 0-100 on how "strong" its geometry is.

    Components (documented so the formula can never drift silently - spec s8
    forbids changing the strength formula because recent price action did not
    fit):

      * nodal alignment  (0-50): 50 at an exact node, 0 at 90 degrees away.
      * perigee proximity (0-35): 35 at perigee (~356,500 km), 0 at apogee
        (~406,700 km).
      * eclipse bonus     (0-15): full marks inside 12 degrees of a node, where
        eclipse geometry actually occurs.

    IMPORTANT: this score is recorded in advance as context. It is NOT evidence
    that a pivot must occur, and it never feeds the Pattern Fit Score.
    """
    nodal = event.nodal_distance_deg if event.nodal_distance_deg is not None else 90.0
    dist = event.distance_km or 384400.0

    nodal_component = 50.0 * max(0.0, 1.0 - (nodal / 90.0))

    perigee, apogee = 356500.0, 406700.0
    span = apogee - perigee
    perigee_component = 35.0 * max(0.0, min(1.0, (apogee - dist) / span))

    eclipse_component = 15.0 if nodal <= 12.0 else (
        15.0 * max(0.0, 1.0 - (nodal - 12.0) / 18.0) if nodal <= 30.0 else 0.0
    )

    components = {
        "nodal_alignment": round(nodal_component, 2),
        "perigee_proximity": round(perigee_component, 2),
        "eclipse_geometry": round(eclipse_component, 2),
        "nodal_distance_deg": round(nodal, 3),
        "distance_km": round(dist, 1),
    }
    total = round(nodal_component + perigee_component + eclipse_component, 1)
    return total, components


def scored_events(start: dt.date, end: dt.date, event_type: str = "both") -> list[MoonEvent]:
    """``moon_events`` with the strength score filled in."""
    events = moon_events(start, end, event_type)
    for e in events:
        e.strength_score, e.strength_components = new_moon_strength(e)
    return events


def phase_name(when: dt.datetime | dt.date | None = None) -> str:
    """Name the Moon's current phase."""
    when = when or dt.datetime.now(dt.timezone.utc).replace(tzinfo=None)
    if isinstance(when, dt.date) and not isinstance(when, dt.datetime):
        when = dt.datetime(when.year, when.month, when.day)
    prev_new = _to_datetime(ephem.previous_new_moon(when))
    age = (when - prev_new).total_seconds() / 86400.0
    idx = int(((age / SYNODIC_MONTH) * 8 + 0.5) % 8)
    return PHASE_NAMES[idx]


def current_phase(when: dt.datetime | None = None) -> dict:
    """Illumination, age and phase name for a moment in time."""
    when = when or dt.datetime.now(dt.timezone.utc).replace(tzinfo=None)
    moon = ephem.Moon(ephem.Date(when))
    prev_new = _to_datetime(ephem.previous_new_moon(when))
    age_days = (when - prev_new).total_seconds() / 86400.0
    return {
        "phase_name": phase_name(when),
        "illumination_pct": round(float(moon.phase), 2),
        "age_days": round(age_days, 2),
        "is_waxing": age_days < SYNODIC_MONTH / 2,
    }


def next_events(after: dt.datetime | None = None, count: int = 4) -> list[MoonEvent]:
    """The next ``count`` new/full moons after ``after``."""
    after = after or dt.datetime.now(dt.timezone.utc).replace(tzinfo=None)
    horizon = (after + dt.timedelta(days=int(SYNODIC_MONTH * count / 2) + 40)).date()
    events = scored_events(after.date(), horizon)
    return [e for e in events if e.exact_at > after][:count]


@dataclass
class LunarContext:
    """Everything the briefing and outlook writers need about the Moon right now."""

    as_of: dt.datetime
    phase_name: str
    illumination_pct: float
    age_days: float
    is_waxing: bool
    last_new_moon: dt.datetime | None
    last_full_moon: dt.datetime | None
    days_since_new_moon: float | None
    days_since_full_moon: float | None
    next_new_moon: dt.datetime | None
    next_full_moon: dt.datetime | None
    days_to_next_new_moon: float | None
    days_to_next_full_moon: float | None
    upcoming: list[MoonEvent] = field(default_factory=list)

    def to_dict(self) -> dict:
        def iso(v):
            return v.isoformat() if isinstance(v, dt.datetime) else v

        return {
            "as_of": iso(self.as_of),
            "phase_name": self.phase_name,
            "illumination_pct": self.illumination_pct,
            "age_days": self.age_days,
            "is_waxing": self.is_waxing,
            "last_new_moon": iso(self.last_new_moon),
            "last_full_moon": iso(self.last_full_moon),
            "days_since_new_moon": self.days_since_new_moon,
            "days_since_full_moon": self.days_since_full_moon,
            "next_new_moon": iso(self.next_new_moon),
            "next_full_moon": iso(self.next_full_moon),
            "days_to_next_new_moon": self.days_to_next_new_moon,
            "days_to_next_full_moon": self.days_to_next_full_moon,
            "upcoming": [
                {
                    "event_type": e.event_type,
                    "label": e.label,
                    "exact_at": iso(e.exact_at),
                    "strength_score": e.strength_score,
                    "nodal_distance_deg": e.nodal_distance_deg,
                }
                for e in self.upcoming
            ],
        }


def lunar_context(when: dt.datetime | None = None) -> LunarContext:
    """The current lunar picture, including the FM/NM day offsets the
    experiment tracks."""
    when = when or dt.datetime.now(dt.timezone.utc).replace(tzinfo=None)
    cur = current_phase(when)

    prev_new = _to_datetime(ephem.previous_new_moon(when))
    prev_full = _to_datetime(ephem.previous_full_moon(when))
    nxt_new = _to_datetime(ephem.next_new_moon(when))
    nxt_full = _to_datetime(ephem.next_full_moon(when))

    def days(a, b):
        return round((a - b).total_seconds() / 86400.0, 2)

    return LunarContext(
        as_of=when,
        phase_name=cur["phase_name"],
        illumination_pct=cur["illumination_pct"],
        age_days=cur["age_days"],
        is_waxing=cur["is_waxing"],
        last_new_moon=prev_new,
        last_full_moon=prev_full,
        days_since_new_moon=days(when, prev_new),
        days_since_full_moon=days(when, prev_full),
        next_new_moon=nxt_new,
        next_full_moon=nxt_full,
        days_to_next_new_moon=days(nxt_new, when),
        days_to_next_full_moon=days(nxt_full, when),
        upcoming=next_events(when, count=4),
    )
