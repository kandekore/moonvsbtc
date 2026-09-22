"""Deterministic fact-checking of the Editor's own turn.

The Companion previously took whatever the Editor said at face value. When the
Editor wrote "the coming new moon" during a waxing gibbous - with a Full Moon
four days out and the next New Moon nineteen - the model answered about a New
Moon that was not the next event, and the error propagated into a drafted
experiment.

Asking the model to "be careful about dates" does not fix that reliably. So the
check is done in Python against ``lunar_context`` BEFORE the model is called,
and any discrepancy is injected into the prompt as a fact the model must resolve
with the Editor. The model's job is only to phrase the question; noticing is not
left to it.

Every check here is conservative: it fires only on an unambiguous contradiction
between what the Editor wrote and what the ephemeris says. A silent false
positive is worse than a missed catch, because it trains the Editor to ignore
the queries.
"""
from __future__ import annotations

import datetime as dt
import re
from dataclasses import dataclass

from ..lunar import LunarContext

#: "the coming new moon", "next full moon", "this new moon"
_UPCOMING_EVENT = re.compile(
    r"\b(?:the\s+)?(coming|next|upcoming|this)\s+(new|full)\s+moon\b", re.I
)

#: "NM+4.4", "FM +5", "nm+0.4d"
_OFFSET_TAG = re.compile(r"\b(NM|FM)\s*([+-])\s*(\d+(?:\.\d+)?)\s*d?\b", re.I)

#: A bare mention of either phase, used to detect NM/FM label confusion.
_PHASE_WORD = re.compile(r"\b(new|full)\s+moon\b", re.I)

#: An explicit ISO-ish or "12 September" date the Editor attaches to an event.
_DATE = re.compile(
    r"\b(\d{4}-\d{2}-\d{2})\b"
    r"|\b(\d{1,2})(?:st|nd|rd|th)?\s+"
    r"(January|February|March|April|May|June|July|August|September|October|November|December)\b",
    re.I,
)

_MONTHS = {
    m.lower(): i
    for i, m in enumerate(
        ("January", "February", "March", "April", "May", "June", "July",
         "August", "September", "October", "November", "December"), start=1
    )
}


@dataclass
class Discrepancy:
    """One contradiction between the Editor's text and the ephemeris."""

    kind: str           # "phase_mismatch" | "offset_label" | "date_mismatch"
    editor_said: str
    ephemeris_says: str
    question: str

    def to_dict(self) -> dict:
        return {
            "kind": self.kind,
            "editor_said": self.editor_said,
            "ephemeris_says": self.ephemeris_says,
            "suggested_question": self.question,
        }


def _fmt(when: dt.datetime | None) -> str:
    return when.strftime("%Y-%m-%d %H:%M UTC") if when else "unknown"


def _next_event(ctx: LunarContext) -> tuple[str, dt.datetime | None]:
    """Which syzygy actually comes next, and when."""
    nn, nf = ctx.next_new_moon, ctx.next_full_moon
    if nn and nf:
        return ("new", nn) if nn <= nf else ("full", nf)
    if nn:
        return "new", nn
    if nf:
        return "full", nf
    return "unknown", None


def _check_upcoming_phase(text: str, ctx: LunarContext) -> list[Discrepancy]:
    """Did the Editor call the next event by the wrong name?"""
    out: list[Discrepancy] = []
    actual_kind, actual_when = _next_event(ctx)
    if actual_when is None:
        return out

    for match in _UPCOMING_EVENT.finditer(text):
        qualifier, said = match.group(1).lower(), match.group(2).lower()
        if said == actual_kind:
            continue

        said_when = ctx.next_new_moon if said == "new" else ctx.next_full_moon
        days = (
            round((said_when - ctx.as_of).total_seconds() / 86400.0, 1)
            if said_when else None
        )
        actual_days = round((actual_when - ctx.as_of).total_seconds() / 86400.0, 1)
        out.append(
            Discrepancy(
                kind="phase_mismatch",
                editor_said=f'"{match.group(0)}"',
                ephemeris_says=(
                    f"the next syzygy is the {actual_kind.upper()} MOON at "
                    f"{_fmt(actual_when)} (in {actual_days} d). The next "
                    f"{said} moon is {_fmt(said_when)}"
                    + (f" (in {days} d)" if days is not None else "")
                ),
                question=(
                    f'You wrote "{match.group(0)}", but the next event is the '
                    f"{actual_kind} moon on {actual_when:%d %b} "
                    f"({actual_days} days away); the next {said} moon is not until "
                    f"{said_when:%d %b}. Did you mean the {actual_kind} moon?"
                    if said_when else
                    f'You wrote "{match.group(0)}", but the next event is the '
                    f"{actual_kind} moon on {actual_when:%d %b}. Did you mean that one?"
                ),
            )
        )
        break  # one query per turn is enough; do not nag.
    return out


def _check_offset_labels(text: str) -> list[Discrepancy]:
    """Catch an NM+ offset used while discussing a Full Moon, and vice versa.

    This is the "we expected NM+4.4 at August's full moon" slip. The offsets are
    defined per phase, so the prefix is not cosmetic - NM+4.4 and FM+4.4 point at
    different days and different pivot types.
    """
    out: list[Discrepancy] = []
    phases = {m.group(1).lower() for m in _PHASE_WORD.finditer(text)}
    if len(phases) != 1:
        return out                      # ambiguous or absent - do not guess
    discussed = phases.pop()            # "new" | "full"
    expected_tag = "NM" if discussed == "new" else "FM"

    for match in _OFFSET_TAG.finditer(text):
        tag = match.group(1).upper()
        if tag == expected_tag:
            continue
        out.append(
            Discrepancy(
                kind="offset_label",
                editor_said=f'"{match.group(0)}"',
                ephemeris_says=(
                    f"the message discusses the {discussed} moon, whose offsets are "
                    f"written {expected_tag}+n. {tag}+n is measured from the "
                    f"{'new' if tag == 'NM' else 'full'} moon instead"
                ),
                question=(
                    f'You wrote "{match.group(0)}" while discussing the {discussed} '
                    f"moon. Offsets from a {discussed} moon are written "
                    f'{expected_tag}+n. Did you mean "{expected_tag}'
                    f'{match.group(2)}{match.group(3)}"?'
                ),
            )
        )
        break
    return out


def _parse_dates(text: str, reference: dt.date) -> list[dt.date]:
    found: list[dt.date] = []
    for m in _DATE.finditer(text):
        try:
            if m.group(1):
                found.append(dt.date.fromisoformat(m.group(1)))
            else:
                day, month = int(m.group(2)), _MONTHS[m.group(3).lower()]
                year = reference.year
                candidate = dt.date(year, month, day)
                # Nearest plausible year, so "12 September" in December means
                # this year, not next.
                if (candidate - reference).days > 300:
                    candidate = dt.date(year - 1, month, day)
                elif (candidate - reference).days < -300:
                    candidate = dt.date(year + 1, month, day)
                found.append(candidate)
        except (ValueError, KeyError):
            continue
    return found


def _check_event_dates(text: str, ctx: LunarContext) -> list[Discrepancy]:
    """If the Editor pins a named event to a date, check the date."""
    out: list[Discrepancy] = []
    match = _PHASE_WORD.search(text)
    if not match:
        return out
    phase = match.group(1).lower()

    known = [
        w for w in (
            ctx.last_new_moon if phase == "new" else ctx.last_full_moon,
            ctx.next_new_moon if phase == "new" else ctx.next_full_moon,
        ) if w
    ] + [
        e.exact_at for e in ctx.upcoming
        if e.event_type == (f"{phase}_moon")
    ]
    if not known:
        return out

    for said in _parse_dates(text, ctx.as_of.date()):
        nearest = min(known, key=lambda w: abs((w.date() - said).days))
        delta = (said - nearest.date()).days
        if 1 <= abs(delta) <= 5:        # close enough to be a slip, not another event
            out.append(
                Discrepancy(
                    kind="date_mismatch",
                    editor_said=f"{phase} moon on {said:%Y-%m-%d}",
                    ephemeris_says=(
                        f"the nearest {phase} moon is {_fmt(nearest)} - "
                        f"{abs(delta)} day(s) {'earlier' if delta > 0 else 'later'}"
                    ),
                    question=(
                        f"You dated the {phase} moon to {said:%d %b}, but the exact "
                        f"instant is {nearest:%d %b %H:%M} UTC. Should the record use "
                        f"{nearest:%d %b}?"
                    ),
                )
            )
            break
    return out


def reconcile(text: str, ctx: LunarContext) -> list[Discrepancy]:
    """Every unambiguous contradiction between ``text`` and the ephemeris."""
    if not text or not text.strip():
        return []
    return (
        _check_upcoming_phase(text, ctx)
        + _check_offset_labels(text)
        + _check_event_dates(text, ctx)
    )


def render_for_prompt(discrepancies: list[Discrepancy]) -> str:
    """The block injected into the Companion prompt."""
    if not discrepancies:
        return ""
    lines = [
        "DISCREPANCIES DETECTED IN THE EDITOR'S MESSAGE.",
        "These were computed from the ephemeris in Python, not by you, and they "
        "are correct. The Editor has very likely made a slip.",
        "",
        "Before answering the substance, you MUST open your reply by pointing out "
        "the discrepancy and asking the Editor which they meant. Ask it as a short, "
        "direct question. Do NOT silently pick an interpretation and carry on, and "
        "do NOT draft a record from the contradictory reading.",
        "",
    ]
    for i, d in enumerate(discrepancies, 1):
        lines += [
            f"{i}. Editor wrote: {d.editor_said}",
            f"   Ephemeris:    {d.ephemeris_says}",
            f"   Ask:          {d.question}",
        ]
    return "\n".join(lines)
