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

Which price defines "the high"?
-------------------------------
The *actual* high or low of a period is an intraday extreme: the highest price
traded (daily HIGH) or the lowest (daily LOW). A closing price can miss a spike
entirely - on 2026-08-03 BTC traded down to 62,227, the lowest price in the whole
window, yet its close was higher than 2026-08-01's, so a close-based search put
the low on the wrong day.

So measure A uses **HIGH for tops and LOW for bottoms**, and falls back to close
only when no OHLC frame is supplied (``extreme_source`` records which was used).

This does NOT contaminate the frozen methodology. Measure B - the matched
significant pivot, the published +4.4 d benchmark and every ``OffsetStats``
figure - stays exactly as ``moon_engine`` computes it, on CLOSE. The two are
reported side by side and never averaged together. Keeping that boundary
explicit is the lesson of the PROJECT_CONTEXT correction log, which records the
opposite error: applying a close-based rule where a low-based one was required.
"""
from __future__ import annotations

import datetime as dt
import math
from dataclasses import asdict, dataclass

import numpy as np
import pandas as pd

import moon_engine as me

from .legacy import WEBSITE_METHODOLOGY
from .pivots import is_strict_local_high, is_strict_local_low

#: Fewest prior observations before an expectation is formed. Below this the
#: mean is noise, and the entry is reported as undecidable rather than scored.
MIN_PRIOR_MATCHES = 3

BASES = ("walk_forward", "full_sample")
MEASURES = ("extreme", "pivot")

#: How the search window is placed around the moon.
#:   "symmetric" - moon +/- max_lag. This is what the legacy website matcher
#:                 does, and it allows a NEGATIVE lag: the turn may precede the
#:                 moon. It also reaches roughly half a synodic month back, so
#:                 it can pick up an extreme that belongs to the PREVIOUS cycle
#:                 and attribute it to this moon.
#:   "forward"   - moon .. moon + max_lag only. This is how the pre-registered
#:                 New-Moon protocol is stated (T0:T+3) and it cannot borrow a
#:                 turn from the preceding phase.
WINDOW_MODES = ("symmetric", "forward")


@dataclass
class TrackRecordEntry:
    """One historical moon, scored on both measures."""

    moon_type: str                      # "Full" | "New"
    kind: str                           # "Top" | "Bottom"
    moon_date: dt.date

    # --- A. the local extreme in the window (always decidable) -------------
    extreme_date: dt.date | None
    extreme_offset_days: int | None
    #: The extreme price itself - the intraday HIGH (tops) or LOW (bottoms).
    extreme_price: float | None
    #: Which column it came from: "high", "low", or "close" when no OHLC frame
    #: was available. A close-based extreme can sit on the wrong day.
    extreme_source: str | None
    #: Is the extreme a genuine turn? Tested with the strict 7-day intraday
    #: rule - HIGH strictly above (or LOW strictly below) the 3 bars either
    #: side. ``None`` when the bars needed to decide are not present.
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


def extreme_column(frame: pd.DataFrame, kind: str) -> str:
    """The column that defines the actual extreme for this phase.

    HIGH for tops, LOW for bottoms; ``close`` only if the frame has no OHLC.
    """
    wanted = "high" if kind == "Top" else "low"
    return wanted if wanted in frame.columns else "close"


def window_extreme(
    frame: pd.DataFrame, moon_date: dt.date, kind: str, max_lag: int,
    window_mode: str = "symmetric",
) -> tuple[dt.date, float, str] | None:
    """The actual high (Top) or low (Bottom) in the window around the moon.

    ``window_mode`` decides where the window sits - see ``WINDOW_MODES``. The
    symmetric window spans nearly a full synodic month and can therefore return
    an extreme that belongs to the previous cycle; the forward window cannot.

    Returns ``(date, price, source_column)``, or ``None`` when the window is not
    fully covered by data - at the very start or end of the series - because a
    truncated window biases the result toward whichever side has bars.
    """
    lo = (pd.Timestamp(moon_date) - pd.Timedelta(days=max_lag)
          if window_mode == "symmetric" else pd.Timestamp(moon_date))
    hi = pd.Timestamp(moon_date) + pd.Timedelta(days=max_lag)
    if lo < frame.index.min() or hi > frame.index.max():
        return None
    column = extreme_column(frame, kind)
    series = frame.loc[lo:hi, column].astype(float)
    if series.empty:
        return None
    stamp = series.idxmax() if kind == "Top" else series.idxmin()
    return stamp.date(), float(series.loc[stamp]), column


def is_turning_point(frame: pd.DataFrame, day: dt.date, kind: str) -> bool | None:
    """Is ``day`` a strict local extreme on intraday prices?

    Uses the protocol's own strict 7-day rule (``pivots``), mirrored onto HIGH
    for tops. Tested on the SAME price basis as the extreme itself - comparing
    an intraday extreme against close-based pivots would put the two measures on
    different definitions and understate real turns.

    ``None`` means undecidable (missing bars), never ``False``.
    """
    column = "high" if kind == "Top" else "low"
    if column not in frame.columns:
        return None
    try:
        if kind == "Top":
            return is_strict_local_high(frame, day)
        return is_strict_local_low(frame, day)
    except (KeyError, ValueError):
        return None


def _entries_for_phase(
    moons: list[dt.date],
    matched: pd.DataFrame,
    frame: pd.DataFrame,
    pivot_dates: set[dt.date],
    moon_type: str,
    kind: str,
    basis: str,
    max_lag: int,
    window_mode: str,
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
    extremes: dict[dt.date, tuple[dt.date, float, int, str]] = {}
    for moon_date in sorted(moons):
        found = window_extreme(frame, moon_date, kind, max_lag, window_mode)
        if found:
            ex_date, ex_price, source = found
            extremes[moon_date] = (
                ex_date, ex_price, (ex_date - moon_date).days, source,
            )

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

        ex_date = ex_price = ex_off = ex_err = ex_hit = is_tp = at_edge = None
        ex_source = None
        if ex is None:
            notes.append(
                f"window extends beyond the price history, so the +/-{max_lag} d "
                "extreme would be biased"
            )
        else:
            ex_date, ex_price, ex_off, ex_source = ex
            is_tp = is_turning_point(frame, ex_date, kind)
            if is_tp is None:
                # Fall back to coincidence with the frozen close-based detector
                # only when intraday bars cannot decide it.
                is_tp = ex_date in pivot_dates if ex_source == "close" else None
            at_edge = (abs(ex_off) >= max_lag - 1 if window_mode == "symmetric"
                       else ex_off >= max_lag - 1)
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
                extreme_price=round(ex_price, 2) if ex_price is not None else None,
                extreme_source=ex_source,
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
    ohlc: pd.DataFrame | None = None,
    window_mode: str = "symmetric",
) -> list[TrackRecordEntry]:
    """Score every resolved historical moon in ``res`` on both measures.

    ``ohlc`` should carry daily ``high``/``low`` columns so measure A finds the
    ACTUAL intraday extreme. Without it the measurement falls back to close,
    which can place the extreme on the wrong day; ``extreme_source`` on each
    entry records which was used.
    """
    if basis not in BASES:
        raise ValueError(f"basis must be one of {BASES}, got {basis!r}")
    if window_mode not in WINDOW_MODES:
        raise ValueError(
            f"window_mode must be one of {WINDOW_MODES}, got {window_mode!r}")
    today = today or dt.date.today()
    if max_lag is None:
        max_lag = int(WEBSITE_METHODOLOGY["max_lag_days"])

    # A moon inside the lag window has not finished resolving; scoring it now
    # would record a result for a turn that may still be forming.
    cutoff = today - dt.timedelta(days=max_lag)
    frame = ohlc if ohlc is not None and not ohlc.empty else res.price
    highs = {_as_date(d) for d in res.swing_highs}
    lows = {_as_date(d) for d in res.swing_lows}

    entries = _entries_for_phase(
        [m for m in res.full_moons if m <= cutoff], res.top_matches,
        frame, highs, "Full", "Top", basis, max_lag, window_mode,
    ) + _entries_for_phase(
        [m for m in res.new_moons if m <= cutoff], res.bottom_matches,
        frame, lows, "New", "Bottom", basis, max_lag, window_mode,
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
        not_turning = [e for e in subset if e.extreme_is_turning_point is False]
        at_edge = [e for e in subset if e.extreme_at_window_edge]
        out[label] = {
            "measure": measure,
            "n_moons": len(subset),
            "n_scored": len(scored),
            "n_undecidable": len(subset) - len(scored),
            "n_extreme_was_turning_point": len(turning),
            "n_extreme_not_a_turn": len(not_turning),
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
    ohlc: pd.DataFrame | None = None,
    window_mode: str = "symmetric",
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
    frame = ohlc if ohlc is not None and not ohlc.empty else res.price
    rng = np.random.default_rng(seed)
    cutoff = today - dt.timedelta(days=max_lag)

    eligible = [
        d.date() for d in frame.index
        if (d - pd.Timedelta(days=max_lag if window_mode == "symmetric" else 0))
        >= frame.index.min()
        and (d + pd.Timedelta(days=max_lag)) <= frame.index.max()
        and d.date() <= cutoff
    ]

    def _offsets(dates: list[dt.date], kind: str) -> list[tuple[dt.date, int]]:
        out = []
        for d in dates:
            found = window_extreme(frame, d, kind, max_lag, window_mode)
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
