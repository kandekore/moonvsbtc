"""The retrospective track record: what we expected, and what actually happened.

``moon_engine.predict_future`` deliberately drops any window that has already
fully elapsed, because its job is to say what to watch next. That leaves the
experiment with no memory: the app could show that the August Full Moon implied
a high around FM+2.7, but not that the high actually landed on FM+6.

Two different questions, measured separately
--------------------------------------------
The first version of this module scored only the frozen significant-pivot match,
and reported "no pivot matched" for two thirds of all moons. That conflated two
questions that deserve separate answers:

  A. **Where was the local extreme?**  There is always a highest close and a
     lowest close inside a +/-14 day window, so this is ALWAYS decidable. It
     measures timing: did the turn, such as it was, land where we expected?

  B. **Was it a significant turning point?**  The frozen website detector
     (``scipy.signal.find_peaks``, spacing 30, prominence 15% of median close)
     finds roughly one pivot per 91 days, against a moon every 14.8 days. Most
     moons cannot match one, by construction. This measures significance.

Reporting only B made a *rarity of significant pivots* look like missing data.
Reporting only A would be worse - it would count every wobble as a turn. Each
entry therefore carries both, and the caller chooses which to read.

Chance baseline
---------------
Because the extreme in A always exists, its hit rate is NOT interpretable on its
own. With sigma near 9 days the expected window spans much of the lunar month,
so a high hit rate is close to guaranteed. ``placebo_baseline`` scores
pseudo-moons on random dates through the same pipeline; the honest result is the
*gap* between the real hit rate and that baseline, and it is usually small.

Everything here reads what ``moon_engine`` already computed with the frozen
website parameters. No protocol parameter is changed (spec s8).

Close-based throughout
----------------------
The website methodology - and therefore every number in this module - is defined
on the daily **CLOSE**. The strict low-based rule in ``pivots.py`` belongs to the
New-Moon protocol and must not be mixed in here; doing so is exactly the error
recorded in the PROJECT_CONTEXT correction log.
"""
from __future__ import annotations

import datetime as dt
import math
from dataclasses import asdict, dataclass

import numpy as np
import pandas as pd

import moon_engine as me

from .legacy import WEBSITE_METHODOLOGY

#: Fewest prior observations before an expectation is formed. Below this the
#: mean is noise, and the entry is reported as undecidable rather than scored.
MIN_PRIOR_MATCHES = 3

BASES = ("walk_forward", "full_sample")
MEASURES = ("extreme", "pivot")


@dataclass
class TrackRecordEntry:
    """One historical moon, scored on both measures."""

    moon_type: str                      # "Full" | "New"
    kind: str                           # "Top" | "Bottom"
    moon_date: dt.date

    # --- A. the local extreme in the window (always decidable) -------------
    extreme_date: dt.date | None
    extreme_offset_days: int | None
    extreme_close: float | None
    #: Is that extreme also a significant pivot per the frozen detector?
    extreme_is_turning_point: bool | None
    #: True when the extreme sits ON the window boundary, which means the real
    #: extreme almost certainly lies outside it - price trended through rather
    #: than turned. These are NOT evidence of a lunar turning point.
    extreme_at_window_edge: bool | None
    expected_extreme_offset: float | None
    expected_extreme_date: dt.date | None
    extreme_window_start: dt.date | None
    extreme_window_end: dt.date | None
    extreme_error_days: float | None
    extreme_hit: bool | None
    n_prior_extremes: int

    # --- B. the frozen significant-pivot match (often absent) --------------
    pivot_date: dt.date | None
    pivot_offset_days: int | None
    pivot_close: float | None
    expected_pivot_offset: float | None
    expected_pivot_date: dt.date | None
    pivot_window_start: dt.date | None
    pivot_window_end: dt.date | None
    pivot_error_days: float | None
    pivot_hit: bool | None
    n_prior_pivots: int

    basis: str
    note: str = ""

    def to_dict(self) -> dict:
        d = asdict(self)
        for key, value in list(d.items()):
            if isinstance(value, dt.date):
                d[key] = value.isoformat()
        return d


def _as_date(value) -> dt.date | None:
    if value is None or (isinstance(value, float) and np.isnan(value)):
        return None
    if isinstance(value, pd.Timestamp):
        return value.date()
    if isinstance(value, dt.datetime):
        return value.date()
    return value


def _expectation(sample: np.ndarray, moon_date: dt.date):
    """Mean offset, projected date and +/-1 sigma window, or Nones."""
    if sample.size < MIN_PRIOR_MATCHES:
        return None, None, None, None
    offset = round(float(np.mean(sample)), 2)
    sd = float(np.std(sample, ddof=1)) if sample.size > 1 else 0.0
    return (
        offset,
        moon_date + dt.timedelta(days=int(round(offset))),
        moon_date + dt.timedelta(days=int(round(offset - sd))),
        moon_date + dt.timedelta(days=int(round(offset + sd))),
    )


def window_extreme(
    close: pd.Series, moon_date: dt.date, kind: str, max_lag: int
) -> tuple[dt.date, float] | None:
    """Highest (Top) or lowest (Bottom) CLOSE within +/-``max_lag`` of the moon.

    Returns ``None`` only when the window is not fully covered by data - at the
    very start or end of the series - because a truncated window biases the
    result toward whichever side has bars.
    """
    lo = pd.Timestamp(moon_date) - pd.Timedelta(days=max_lag)
    hi = pd.Timestamp(moon_date) + pd.Timedelta(days=max_lag)
    if lo < close.index.min() or hi > close.index.max():
        return None
    window = close.loc[lo:hi]
    if window.empty:
        return None
    stamp = window.idxmax() if kind == "Top" else window.idxmin()
    return stamp.date(), float(window.loc[stamp])


def _entries_for_phase(
    moons: list[dt.date],
    matched: pd.DataFrame,
    close: pd.Series,
    pivot_dates: set[dt.date],
    moon_type: str,
    kind: str,
    basis: str,
    max_lag: int,
) -> list[TrackRecordEntry]:
    """Score every moon of one phase on both measures."""
    by_moon: dict[dt.date, dict] = {}
    if not matched.empty:
        for row in matched.itertuples(index=False):
            by_moon[_as_date(row.moon_date)] = {
                "pivot_date": _as_date(row.pivot_date),
                "offset_days": int(row.offset_days),
                "pivot_price": float(row.pivot_price),
            }

    # Pass 1: measure the extreme for every moon, in date order, so a
    # walk-forward mean can be accumulated from prior moons only.
    extremes: dict[dt.date, tuple[dt.date, float, int]] = {}
    for moon_date in sorted(moons):
        found = window_extreme(close, moon_date, kind, max_lag)
        if found:
            ex_date, ex_close = found
            extremes[moon_date] = (ex_date, ex_close, (ex_date - moon_date).days)

    ordered_ex = sorted(extremes.items(), key=lambda kv: kv[0])
    all_ex = np.array([v[2] for _, v in ordered_ex], dtype=float)

    ordered_pv = sorted(by_moon.items(), key=lambda kv: kv[0])
    all_pv = np.array([v["offset_days"] for _, v in ordered_pv], dtype=float)

    out: list[TrackRecordEntry] = []
    for moon_date in sorted(moons):
        notes: list[str] = []

        # ---- A. extreme ---------------------------------------------------
        ex = extremes.get(moon_date)
        prior_ex = np.array(
            [v[2] for m, v in ordered_ex if m < moon_date], dtype=float
        )
        sample_ex = all_ex if basis == "full_sample" else prior_ex
        n_prior_ex = int(sample_ex.size)
        exp_ex_off, exp_ex_date, ex_lo, ex_hi = _expectation(sample_ex, moon_date)

        ex_date = ex_close = ex_off = ex_err = ex_hit = is_tp = at_edge = None
        if ex is None:
            notes.append(
                f"window extends beyond the price history, so the +/-{max_lag} d "
                "extreme would be biased"
            )
        else:
            ex_date, ex_close, ex_off = ex
            is_tp = ex_date in pivot_dates
            at_edge = abs(ex_off) >= max_lag - 1
            if at_edge:
                notes.append(
                    "extreme sits on the window boundary - price trended through "
                    "rather than turned, so the true extreme is probably outside"
                )
            if exp_ex_off is not None:
                ex_err = round(float(ex_off) - exp_ex_off, 2)
                ex_hit = ex_lo <= ex_date <= ex_hi
            else:
                notes.append(
                    f"only {n_prior_ex} prior extreme(s); fewer than "
                    f"{MIN_PRIOR_MATCHES}, so no expectation was formed"
                )

        # ---- B. significant pivot ------------------------------------------
        pv = by_moon.get(moon_date)
        prior_pv = np.array(
            [v["offset_days"] for m, v in ordered_pv if m < moon_date], dtype=float
        )
        sample_pv = all_pv if basis == "full_sample" else prior_pv
        n_prior_pv = int(sample_pv.size)
        exp_pv_off, exp_pv_date, pv_lo, pv_hi = _expectation(sample_pv, moon_date)

        pv_date = pv_close = pv_off = pv_err = pv_hit = None
        if pv is None:
            notes.append(
                f"no swing {kind.lower()} significant enough to match within "
                f"+/-{max_lag} d (the detector finds ~1 per 91 d)"
            )
        else:
            pv_date, pv_off = pv["pivot_date"], pv["offset_days"]
            pv_close = round(pv["pivot_price"], 2)
            if exp_pv_off is not None:
                pv_err = round(float(pv_off) - exp_pv_off, 2)
                pv_hit = pv_lo <= pv_date <= pv_hi

        out.append(
            TrackRecordEntry(
                moon_type=moon_type, kind=kind, moon_date=moon_date,
                extreme_date=ex_date,
                extreme_offset_days=ex_off,
                extreme_close=round(ex_close, 2) if ex_close is not None else None,
                extreme_is_turning_point=is_tp,
                extreme_at_window_edge=at_edge,
                expected_extreme_offset=exp_ex_off,
                expected_extreme_date=exp_ex_date,
                extreme_window_start=ex_lo, extreme_window_end=ex_hi,
                extreme_error_days=ex_err, extreme_hit=ex_hit,
                n_prior_extremes=n_prior_ex,
                pivot_date=pv_date, pivot_offset_days=pv_off, pivot_close=pv_close,
                expected_pivot_offset=exp_pv_off, expected_pivot_date=exp_pv_date,
                pivot_window_start=pv_lo, pivot_window_end=pv_hi,
                pivot_error_days=pv_err, pivot_hit=pv_hit,
                n_prior_pivots=n_prior_pv,
                basis=basis,
                note="; ".join(notes),
            )
        )
    return out


def build_track_record(
    res: "me.AnalysisResult",
    basis: str = "walk_forward",
    today: dt.date | None = None,
    max_lag: int | None = None,
) -> list[TrackRecordEntry]:
    """Score every resolved historical moon in ``res`` on both measures."""
    if basis not in BASES:
        raise ValueError(f"basis must be one of {BASES}, got {basis!r}")
    today = today or dt.date.today()
    if max_lag is None:
        max_lag = int(WEBSITE_METHODOLOGY["max_lag_days"])

    # A moon inside the lag window has not finished resolving; scoring it now
    # would record a result for a turn that may still be forming.
    cutoff = today - dt.timedelta(days=max_lag)
    close = res.price["close"].astype(float)
    highs = {_as_date(d) for d in res.swing_highs}
    lows = {_as_date(d) for d in res.swing_lows}

    entries = _entries_for_phase(
        [m for m in res.full_moons if m <= cutoff], res.top_matches,
        close, highs, "Full", "Top", basis, max_lag,
    ) + _entries_for_phase(
        [m for m in res.new_moons if m <= cutoff], res.bottom_matches,
        close, lows, "New", "Bottom", basis, max_lag,
    )
    entries.sort(key=lambda e: e.moon_date)
    return entries


def track_record_frame(entries: list[TrackRecordEntry]) -> pd.DataFrame:
    """The entries as a DataFrame, newest first - display order."""
    if not entries:
        return pd.DataFrame(
            columns=list(TrackRecordEntry.__dataclass_fields__)
        )
    df = pd.DataFrame([asdict(e) for e in entries])
    return df.sort_values("moon_date", ascending=False).reset_index(drop=True)


def track_record_summary(
    entries: list[TrackRecordEntry], measure: str = "extreme"
) -> dict:
    """Aggregate accuracy for one measure, split by phase."""
    if measure not in MEASURES:
        raise ValueError(f"measure must be one of {MEASURES}, got {measure!r}")
    err_attr = f"{measure}_error_days"
    hit_attr = f"{measure}_hit"

    out: dict = {}
    for label, kind in (("full_moon_to_high", "Top"), ("new_moon_to_low", "Bottom")):
        subset = [e for e in entries if e.kind == kind]
        scored = [e for e in subset if getattr(e, err_attr) is not None]
        errors = np.array([getattr(e, err_attr) for e in scored], dtype=float)
        hits = [getattr(e, hit_attr) for e in scored
                if getattr(e, hit_attr) is not None]
        turning = [e for e in subset if e.extreme_is_turning_point]
        at_edge = [e for e in subset if e.extreme_at_window_edge]
        out[label] = {
            "measure": measure,
            "n_moons": len(subset),
            "n_scored": len(scored),
            "n_undecidable": len(subset) - len(scored),
            "n_extreme_was_turning_point": len(turning),
            "n_extreme_at_window_edge": len(at_edge),
            "mean_error_days": round(float(np.mean(errors)), 2) if errors.size else None,
            "mean_absolute_error_days": (
                round(float(np.mean(np.abs(errors))), 2) if errors.size else None
            ),
            "median_absolute_error_days": (
                round(float(np.median(np.abs(errors))), 2) if errors.size else None
            ),
            "hit_rate_pct": round(100.0 * sum(hits) / len(hits), 1) if hits else None,
            "basis": subset[0].basis if subset else None,
        }
    return out


def placebo_baseline(
    res: "me.AnalysisResult",
    max_lag: int | None = None,
    n_trials: int = 1000,
    seed: int = 0,
    today: dt.date | None = None,
) -> dict:
    """Does the Moon beat a random date at the same task?

    The extreme in a +/-``max_lag`` window always exists, so the "extreme" hit
    rate carries a large floor that has nothing to do with the Moon. This scores
    pseudo-moons on uniformly random dates through the identical measurement.

    To keep the comparison honest, real moons and pseudo-moons are scored
    against the SAME fixed window: mean +/- 1 sd of the real moons' extreme
    offsets over the whole sample. Using a walk-forward window for one and a
    fixed window for the other would compare two different tests.

    ``edge_pct`` is the real rate minus the placebo rate. ``edge_se_pct`` is the
    standard error of that difference; an edge smaller than about twice its
    standard error is not distinguishable from chance, and saying so plainly is
    the point of this experiment.
    """
    if max_lag is None:
        max_lag = int(WEBSITE_METHODOLOGY["max_lag_days"])
    today = today or dt.date.today()
    close = res.price["close"].astype(float)
    rng = np.random.default_rng(seed)
    cutoff = today - dt.timedelta(days=max_lag)

    eligible = [
        d.date() for d in close.index
        if (d - pd.Timedelta(days=max_lag)) >= close.index.min()
        and (d + pd.Timedelta(days=max_lag)) <= close.index.max()
        and d.date() <= cutoff
    ]

    def _offsets(dates: list[dt.date], kind: str) -> list[tuple[dt.date, int]]:
        out = []
        for d in dates:
            found = window_extreme(close, d, kind, max_lag)
            if found:
                out.append((d, (found[0] - d).days))
        return out

    result: dict = {}
    for label, kind, moons in (
        ("full_moon_to_high", "Top", res.full_moons),
        ("new_moon_to_low", "Bottom", res.new_moons),
    ):
        real = _offsets([m for m in moons if m <= cutoff], kind)
        if len(real) < MIN_PRIOR_MATCHES or not eligible:
            result[label] = {
                "real_hit_rate_pct": None, "placebo_hit_rate_pct": None,
                "edge_pct": None, "edge_se_pct": None,
                "n_real": len(real), "n_trials": 0, "window_days": None,
            }
            continue

        arr = np.array([o for _, o in real], dtype=float)
        mean, sd = float(np.mean(arr)), float(np.std(arr, ddof=1))
        lo_d, hi_d = int(round(mean - sd)), int(round(mean + sd))

        real_hits = sum(1 for _, o in real if lo_d <= o <= hi_d)
        real_rate = real_hits / len(real)

        picks = rng.choice(len(eligible), size=min(n_trials, len(eligible)),
                           replace=False)
        placebo = _offsets([eligible[int(i)] for i in picks], kind)
        placebo_hits = sum(1 for _, o in placebo if lo_d <= o <= hi_d)
        placebo_rate = placebo_hits / len(placebo) if placebo else None

        edge = se = None
        if placebo_rate is not None:
            edge = real_rate - placebo_rate
            se = math.sqrt(
                real_rate * (1 - real_rate) / len(real)
                + placebo_rate * (1 - placebo_rate) / len(placebo)
            )

        result[label] = {
            "real_hit_rate_pct": round(100 * real_rate, 1),
            "placebo_hit_rate_pct": (
                round(100 * placebo_rate, 1) if placebo_rate is not None else None
            ),
            "edge_pct": round(100 * edge, 1) if edge is not None else None,
            "edge_se_pct": round(100 * se, 1) if se is not None else None,
            "significant": (
                bool(edge is not None and se and abs(edge) > 2 * se)
            ),
            "n_real": len(real),
            "n_trials": len(placebo),
            "window_days": [lo_d, hi_d],
        }
    return result
