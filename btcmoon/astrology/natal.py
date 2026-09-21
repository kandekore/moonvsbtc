"""Bitcoin's natal chart and transits to it.

Chart assumptions are stated explicitly and surfaced on the public page, because
the choice of birth moment is itself an assumption and different choices give
different charts.

This is an EXPERIMENTAL interpretive layer. Astrology is not established
financial forecasting, and nothing here is presented as a causal mechanism -
see ``NATAL_CHART_ASSUMPTIONS`` and the public disclaimer.
"""
from __future__ import annotations

import datetime as dt
import math
from dataclasses import dataclass, field

import ephem

#: The genesis block was mined at 2009-01-03 18:15:05 UTC. We use that instant.
#: Timestamp is from the block header itself, so it is the least arbitrary
#: choice available - but it is still a choice, and it is stated as one.
BTC_NATAL_MOMENT = dt.datetime(2009, 1, 3, 18, 15, 5)

NATAL_CHART_ASSUMPTIONS = {
    "birth_moment_utc": BTC_NATAL_MOMENT.isoformat(),
    "basis": "Genesis block timestamp recorded in the Bitcoin block header.",
    "location": (
        "No birth location is assumed. Houses and angles (Ascendant, Midheaven) "
        "therefore are NOT calculated - they require a place as well as a time, "
        "and Bitcoin has no location. Only planetary positions and aspects are used."
    ),
    "zodiac": "Tropical zodiac, geocentric, ecliptic longitude.",
    "caveats": [
        "Alternative birth moments exist (whitepaper publication 31 Oct 2008, "
        "first transaction 12 Jan 2009). A different moment gives a different chart.",
        "Astrology has no established causal mechanism in financial markets.",
        "This layer is recorded and tested publicly like every other input, and "
        "is reported alongside price structure, volume, regime and real catalysts.",
    ],
}

#: Bodies used for the natal chart. The fast Moon is included but weighted low.
BODIES = {
    "Sun": ephem.Sun,
    "Moon": ephem.Moon,
    "Mercury": ephem.Mercury,
    "Venus": ephem.Venus,
    "Mars": ephem.Mars,
    "Jupiter": ephem.Jupiter,
    "Saturn": ephem.Saturn,
    "Uranus": ephem.Uranus,
    "Neptune": ephem.Neptune,
    "Pluto": ephem.Pluto,
}

#: Slow bodies make the durable transits; fast ones are day-scale colour.
TRANSITING_BODIES = ("Sun", "Mercury", "Venus", "Mars", "Jupiter", "Saturn", "Uranus", "Neptune", "Pluto")

SIGNS = (
    "Aries", "Taurus", "Gemini", "Cancer", "Leo", "Virgo",
    "Libra", "Scorpio", "Sagittarius", "Capricorn", "Aquarius", "Pisces",
)

#: name -> (exact angle, default orb in degrees)
ASPECTS = {
    "conjunction": (0.0, 6.0),
    "sextile": (60.0, 3.0),
    "square": (90.0, 5.0),
    "trine": (120.0, 5.0),
    "opposition": (180.0, 6.0),
}

#: Relative weights, so a Saturn square is not reported next to a Moon sextile
#: as though they carry the same significance.
BODY_WEIGHT = {
    "Sun": 1.0, "Moon": 0.4, "Mercury": 0.6, "Venus": 0.6, "Mars": 0.9,
    "Jupiter": 1.3, "Saturn": 1.5, "Uranus": 1.4, "Neptune": 1.2, "Pluto": 1.5,
}

ASPECT_WEIGHT = {
    "conjunction": 1.3, "opposition": 1.2, "square": 1.1, "trine": 0.9, "sextile": 0.7,
}


def _longitude(body_name: str, when: dt.datetime) -> float:
    """Geocentric ecliptic longitude in degrees."""
    body = BODIES[body_name](ephem.Date(when))
    return math.degrees(float(ephem.Ecliptic(body).lon)) % 360.0


def sign_of(longitude: float) -> tuple[str, float]:
    """(zodiac sign, degrees into that sign)."""
    idx = int(longitude // 30) % 12
    return SIGNS[idx], round(longitude % 30.0, 2)


def natal_chart(moment: dt.datetime | None = None) -> dict:
    """Bitcoin's natal planetary positions."""
    moment = moment or BTC_NATAL_MOMENT
    chart = {}
    for name in BODIES:
        lon = _longitude(name, moment)
        sign, deg = sign_of(lon)
        chart[name] = {
            "longitude": round(lon, 3), "sign": sign, "degrees_in_sign": deg,
            "display": f"{deg:.1f}° {sign}",
        }
    return {
        "moment_utc": moment.isoformat(),
        "positions": chart,
        "assumptions": NATAL_CHART_ASSUMPTIONS,
    }


#: Cached at import; the natal chart never changes.
NATAL_POSITIONS = {k: v["longitude"] for k, v in natal_chart()["positions"].items()}


@dataclass
class Transit:
    transiting_body: str
    natal_point: str
    aspect: str
    orb_deg: float
    exact_angle: float
    is_applying: bool
    weight: float
    event_date: dt.date

    @property
    def label(self) -> str:
        return f"transiting {self.transiting_body} {self.aspect} natal {self.natal_point}"

    def to_dict(self) -> dict:
        return {
            "transiting_body": self.transiting_body,
            "natal_point": self.natal_point,
            "aspect": self.aspect,
            "orb_deg": self.orb_deg,
            "is_applying": self.is_applying,
            "weight": self.weight,
            "event_date": self.event_date.isoformat(),
            "label": self.label,
        }


def _separation(a: float, b: float) -> float:
    """Smallest absolute angular separation, 0-180."""
    return abs((a - b + 180.0) % 360.0 - 180.0)


def transits_for(
    when: dt.date | dt.datetime | None = None,
    orb_scale: float = 1.0,
    min_weight: float = 0.0,
) -> list[Transit]:
    """Aspects from transiting bodies to Bitcoin's natal positions on a date.

    Sorted strongest-first: a tight Saturn square outranks a wide Venus sextile.
    """
    when = when or dt.date.today()
    if isinstance(when, dt.date) and not isinstance(when, dt.datetime):
        moment = dt.datetime(when.year, when.month, when.day, 12, 0)
        day = when
    else:
        moment = when
        day = when.date()

    later = moment + dt.timedelta(hours=24)
    out: list[Transit] = []

    for t_body in TRANSITING_BODIES:
        t_lon = _longitude(t_body, moment)
        t_lon_later = _longitude(t_body, later)
        for n_point, n_lon in NATAL_POSITIONS.items():
            sep = _separation(t_lon, n_lon)
            sep_later = _separation(t_lon_later, n_lon)
            for aspect, (angle, base_orb) in ASPECTS.items():
                orb = abs(sep - angle)
                if orb > base_orb * orb_scale:
                    continue
                applying = abs(sep_later - angle) < orb
                tightness = 1.0 - (orb / (base_orb * orb_scale))
                weight = round(
                    BODY_WEIGHT.get(t_body, 1.0)
                    * ASPECT_WEIGHT.get(aspect, 1.0)
                    * (0.5 + 0.5 * tightness),
                    3,
                )
                if weight < min_weight:
                    continue
                out.append(
                    Transit(
                        transiting_body=t_body, natal_point=n_point, aspect=aspect,
                        orb_deg=round(orb, 2), exact_angle=angle,
                        is_applying=applying, weight=weight, event_date=day,
                    )
                )
    out.sort(key=lambda t: (-t.weight, t.orb_deg))
    return out


def transit_calendar(
    start: dt.date, days: int = 30, top_n: int = 3, min_weight: float = 1.0
) -> list[dict]:
    """The most significant transits on each of ``days`` consecutive days."""
    cal = []
    for i in range(days):
        day = start + dt.timedelta(days=i)
        hits = [t for t in transits_for(day) if t.weight >= min_weight][:top_n]
        if hits:
            cal.append({"date": day.isoformat(), "transits": [t.to_dict() for t in hits]})
    return cal


def natal_context(when: dt.date | None = None, top_n: int = 5) -> dict:
    """Natal context for a briefing or outlook."""
    when = when or dt.date.today()
    hits = transits_for(when)
    notable = [t for t in hits if t.weight >= 1.0][:top_n] or hits[:top_n]
    return {
        "date": when.isoformat(),
        "natal_moment_utc": BTC_NATAL_MOMENT.isoformat(),
        "notable_transits": [t.to_dict() for t in notable],
        "transit_count": len(hits),
        "disclaimer": (
            "Experimental interpretive layer. Astrology is not established "
            "financial forecasting and is reported here alongside price "
            "structure, volume, regime and real catalysts - never instead of them."
        ),
    }
