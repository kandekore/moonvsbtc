"""The retrospective track record: what we expected, and what actually happened.

``moon_engine.predict_future`` deliberately drops any window that has already
fully elapsed, because its job is to say what to watch next. That leaves the
experiment with no memory: the app could show that the August Full Moon implied
a high around FM+4.4, but not that the high actually landed on FM+5.

This module supplies the missing half. For every *historical* moon event it
records the target that was implied at the time, the pivot that actually formed,
and the signed error between them.

Look-ahead bias
---------------
The published site quotes a single headline offset (Full Moon -> high, +4.4 d)
computed over the whole sample. Scoring a 2026 moon against an average that was
itself computed using 2026 data is hindsight, not a track record, and would
flatter the method.

So the default basis here is ``walk_forward``: the expected offset for a given
moon is the mean of the offsets observed at *earlier* moons only, exactly the
number that would have been on the screen beforehand. ``full_sample`` reproduces
the published headline figure instead, and is offered for comparison - the gap
between the two is itself a finding worth publishing.

Neither basis changes any frozen protocol parameter. This module only reads what
``moon_engine`` already computed (spec s8).
"""
from __future__ import annotations

import datetime as dt
from dataclasses import asdict, dataclass

import numpy as np
import pandas as pd

import moon_engine as me

from .legacy import WEBSITE_METHODOLOGY

#: Fewest prior matched pairs before a walk-forward expectation is meaningful.
#: Below this the mean is noise, and the entry is reported as "not yet decidable"
#: rather than scored - an undecidable case must never be recorded as a miss.
MIN_PRIOR_MATCHES = 3

BASES = ("walk_forward", "full_sample")


@dataclass
class TrackRecordEntry:
    """One historical moon event, scored against what was expected of it."""

    moon_type: str                      # "Full" | "New"
    kind: str                           # "Top" | "Bottom"
    moon_date: dt.date

    #: The offset that was expected *before* this event, and where it pointed.
    expected_offset_days: float | None
    expected_date: dt.date | None
    window_start: dt.date | None
    window_end: dt.date | None
    #: How many earlier matched pairs the expectation was built from.
    n_prior: int

    #: What actually formed, per the frozen matching rule.
    actual_pivot_date: dt.date | None
    actual_offset_days: int | None
    actual_pivot_price: float | None

    #: actual - expected. Positive means the pivot came LATER than expected.
    error_days: float | None
    hit_window: bool | None
    basis: str
    note: str = ""

    def to_dict(self) -> dict:
        d = asdict(self)
        for key in ("moon_date", "expected_date", "window_start", "window_end",
                    "actual_pivot_date"):
            if isinstance(d[key], dt.date):
                d[key] = d[key].isoformat()
        return d


def _as_date(value) -> dt.date | None:
    if value is None or (isinstance(value, float) and np.isnan(value)):
        return None
    if isinstance(value, pd.Timestamp):
        return value.date()
    if isinstance(value, dt.datetime):
        return value.date()
    return value


def _entries_for_phase(
    moons: list[dt.date],
    matched: pd.DataFrame,
    moon_type: str,
    kind: str,
    basis: str,
) -> list[TrackRecordEntry]:
    """Score every moon of one phase against the expectation of its time."""
    by_moon: dict[dt.date, dict] = {}
    if not matched.empty:
        for row in matched.itertuples(index=False):
            by_moon[_as_date(row.moon_date)] = {
                "pivot_date": _as_date(row.pivot_date),
                "offset_days": int(row.offset_days),
                "pivot_price": float(row.pivot_price),
            }

    # Offsets in chronological order, so a walk-forward mean can be accumulated.
    ordered = sorted(by_moon.items(), key=lambda kv: kv[0])
    full_sample = np.array([v["offset_days"] for _, v in ordered], dtype=float)

    out: list[TrackRecordEntry] = []
    for moon_date in sorted(moons):
        actual = by_moon.get(moon_date)

        prior = np.array(
            [v["offset_days"] for m, v in ordered if m < moon_date], dtype=float
        )
        if basis == "full_sample":
            sample, n_prior = full_sample, int(full_sample.size)
        else:
            sample, n_prior = prior, int(prior.size)

        expected_offset = expected_date = win_start = win_end = None
        note = ""
        if sample.size >= MIN_PRIOR_MATCHES:
            expected_offset = round(float(np.mean(sample)), 2)
            sd = float(np.std(sample, ddof=1)) if sample.size > 1 else 0.0
            expected_date = moon_date + dt.timedelta(days=int(round(expected_offset)))
            win_start = moon_date + dt.timedelta(days=int(round(expected_offset - sd)))
            win_end = moon_date + dt.timedelta(days=int(round(expected_offset + sd)))
        else:
            note = (
                f"only {sample.size} prior matched pair(s); fewer than "
                f"{MIN_PRIOR_MATCHES}, so no expectation was formed"
            )

        error = hit = None
        if actual is None:
            if not note:
                note = f"no swing {kind.lower()} matched this moon within the lag window"
        elif expected_offset is not None:
            error = round(float(actual["offset_days"]) - expected_offset, 2)
            if win_start and win_end:
                hit = win_start <= actual["pivot_date"] <= win_end

        out.append(
            TrackRecordEntry(
                moon_type=moon_type,
                kind=kind,
                moon_date=moon_date,
                expected_offset_days=expected_offset,
                expected_date=expected_date,
                window_start=win_start,
                window_end=win_end,
                n_prior=n_prior,
                actual_pivot_date=actual["pivot_date"] if actual else None,
                actual_offset_days=actual["offset_days"] if actual else None,
                actual_pivot_price=round(actual["pivot_price"], 2) if actual else None,
                error_days=error,
                hit_window=hit,
                basis=basis,
                note=note,
            )
        )
    return out


def build_track_record(
    res: "me.AnalysisResult",
    basis: str = "walk_forward",
    today: dt.date | None = None,
    max_lag: int | None = None,
) -> list[TrackRecordEntry]:
    """Score every historical moon in ``res`` against what was expected of it.

    Only moons whose outcome is already decidable are returned - a moon whose
    pivot could still form is not a miss, it is simply not yet scored, and is
    left to ``moon_engine.predict_future``.
    """
    if basis not in BASES:
        raise ValueError(f"basis must be one of {BASES}, got {basis!r}")
    today = today or dt.date.today()
    if max_lag is None:
        max_lag = int(WEBSITE_METHODOLOGY["max_lag_days"])

    # The matcher may claim a pivot up to max_lag days after the moon, so a moon
    # inside that window has not finished resolving. Scoring it now would record
    # a miss for a pivot that has simply not formed yet.
    cutoff = today - dt.timedelta(days=max_lag)

    entries = _entries_for_phase(
        [m for m in res.full_moons if m <= cutoff], res.top_matches,
        "Full", "Top", basis,
    ) + _entries_for_phase(
        [m for m in res.new_moons if m <= cutoff], res.bottom_matches,
        "New", "Bottom", basis,
    )
    entries.sort(key=lambda e: e.moon_date)
    return entries


def track_record_frame(entries: list[TrackRecordEntry]) -> pd.DataFrame:
    """The entries as a DataFrame, newest first - display order."""
    if not entries:
        return pd.DataFrame(
            columns=[f.name for f in TrackRecordEntry.__dataclass_fields__.values()]
        )
    df = pd.DataFrame([asdict(e) for e in entries])
    return df.sort_values("moon_date", ascending=False).reset_index(drop=True)


def track_record_summary(entries: list[TrackRecordEntry]) -> dict:
    """Aggregate accuracy, split by phase.

    ``scored`` counts only entries where an expectation existed AND a pivot
    matched. Everything else is reported separately rather than being folded in
    as a success or a failure.
    """
    out: dict = {}
    for label, kind in (("full_moon_to_high", "Top"), ("new_moon_to_low", "Bottom")):
        subset = [e for e in entries if e.kind == kind]
        scored = [e for e in subset if e.error_days is not None]
        errors = np.array([e.error_days for e in scored], dtype=float)
        hits = [e.hit_window for e in scored if e.hit_window is not None]
        out[label] = {
            "n_moons": len(subset),
            "n_scored": len(scored),
            "n_unmatched": sum(1 for e in subset if e.actual_pivot_date is None),
            "n_no_expectation": sum(1 for e in subset if e.expected_offset_days is None),
            "mean_error_days": round(float(np.mean(errors)), 2) if errors.size else None,
            "mean_absolute_error_days": (
                round(float(np.mean(np.abs(errors))), 2) if errors.size else None
            ),
            "median_absolute_error_days": (
                round(float(np.median(np.abs(errors))), 2) if errors.size else None
            ),
            "hit_rate_pct": (
                round(100.0 * sum(hits) / len(hits), 1) if hits else None
            ),
            "basis": subset[0].basis if subset else None,
        }
    return out
