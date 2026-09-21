"""Strict intraday swing pivots, defined on daily LOW / HIGH.

This is a DIFFERENT pivot definition from the legacy website methodology and
must never be confused with it:

  * Legacy website methodology (``btcmoon/research/legacy.py`` -> ``moon_engine``):
    daily **CLOSE**, ``scipy.signal.find_peaks``, spacing 30, prominence 15% of
    the median close, matched within +/-14 days. Used for the published
    Full-Moon lag benchmarks (+4.4 d, +3.2 d / 71%).

  * The New-Moon / local-low protocol (this module): a strict 7-day pivot on the
    daily **LOW**:

        LOW[t] < LOW[t-1], LOW[t-2], LOW[t-3]
        AND
        LOW[t] < LOW[t+1], LOW[t+2], LOW[t+3]

Both are correct. They answer different questions. Using close-based pivots for
the New-Moon test - or low-based pivots for the website benchmark - produces
wrong answers, and did (see PROJECT_CONTEXT.md, "Correction log").

Equality handling
-----------------
The comparison is **strict** (``<``), exactly as written in the protocol. A bar
whose low merely *ties* the lowest neighbouring low does NOT qualify. This is
deliberate and is applied identically on both sides, so a flat double-bottom
produces no pivot rather than two. ``LOOKBACK``/``LOOKFORWARD`` are 3 by
definition and are not parameters of the protocol - the keyword arguments exist
only so the rule can be exercised in tests.
"""
from __future__ import annotations

import datetime as dt
from dataclasses import dataclass

import pandas as pd

#: Fixed by the protocol. Do not tune.
SPAN = 3


class InsufficientData(ValueError):
    """Not enough bars on one side to decide the rule."""


def _require_ohlc(df: pd.DataFrame, column: str) -> pd.Series:
    if column not in df.columns:
        raise KeyError(
            f"Column {column!r} is required for strict pivot detection. This test "
            f"is defined on intraday extremes, not on closing prices - pass a frame "
            f"from market_data.get_ohlc_history()."
        )
    return df[column].astype(float)


def is_strict_local_low(
    df: pd.DataFrame, day: dt.date, span: int = SPAN, strict: bool = True
) -> bool | None:
    """Does ``day`` satisfy the strict 7-day local-low rule?

    Returns ``None`` when the answer cannot be determined - the bar is missing,
    or there are fewer than ``span`` bars on one side. ``None`` is not ``False``:
    an undecidable day must never be recorded as a failure.
    """
    low = _require_ohlc(df, "low")
    ts = pd.Timestamp(day)
    if ts not in low.index:
        return None
    pos = low.index.get_loc(ts)
    if pos < span or pos + span >= len(low):
        return None

    value = float(low.iloc[pos])
    neighbours = [float(low.iloc[pos + k]) for k in range(-span, span + 1) if k != 0]
    if strict:
        return all(value < n for n in neighbours)
    return all(value <= n for n in neighbours)


def is_strict_local_high(
    df: pd.DataFrame, day: dt.date, span: int = SPAN, strict: bool = True
) -> bool | None:
    """The mirror rule on daily HIGH, for Full-Moon work."""
    high = _require_ohlc(df, "high")
    ts = pd.Timestamp(day)
    if ts not in high.index:
        return None
    pos = high.index.get_loc(ts)
    if pos < span or pos + span >= len(high):
        return None
    value = float(high.iloc[pos])
    neighbours = [float(high.iloc[pos + k]) for k in range(-span, span + 1) if k != 0]
    if strict:
        return all(value > n for n in neighbours)
    return all(value >= n for n in neighbours)


@dataclass
class PivotCheck:
    """The full working for one candidate day, so a reader can audit it."""

    date: dt.date
    low: float | None
    back: list[float]
    forward: list[float]
    qualifies: bool | None
    reason: str = ""

    def to_dict(self) -> dict:
        return {
            "date": self.date.isoformat(),
            "low": self.low,
            "lows_t_minus_1_2_3": self.back,
            "lows_t_plus_1_2_3": self.forward,
            "qualifies": self.qualifies,
            "reason": self.reason,
        }


def check_day(df: pd.DataFrame, day: dt.date, span: int = SPAN) -> PivotCheck:
    """Evaluate one day and show every number the rule looked at."""
    low = _require_ohlc(df, "low")
    ts = pd.Timestamp(day)
    if ts not in low.index:
        return PivotCheck(day, None, [], [], None, "no daily bar for this date")
    pos = low.index.get_loc(ts)
    if pos < span:
        return PivotCheck(day, float(low.iloc[pos]), [], [], None,
                          f"fewer than {span} bars before this date")
    if pos + span >= len(low):
        return PivotCheck(day, float(low.iloc[pos]), [], [], None,
                          f"fewer than {span} bars after this date - not yet decidable")

    value = float(low.iloc[pos])
    back = [round(float(low.iloc[pos - k]), 2) for k in range(1, span + 1)]
    fwd = [round(float(low.iloc[pos + k]), 2) for k in range(1, span + 1)]
    qualifies = all(value < b for b in back) and all(value < f for f in fwd)

    reason = ""
    if not qualifies:
        failed_back = [f"LOW[t-{k}]={back[k-1]:,.2f}" for k in range(1, span + 1)
                       if not value < back[k - 1]]
        failed_fwd = [f"LOW[t+{k}]={fwd[k-1]:,.2f}" for k in range(1, span + 1)
                      if not value < fwd[k - 1]]
        reason = (
            f"LOW={value:,.2f} is not strictly below "
            + ", ".join(failed_back + failed_fwd)
        )
    return PivotCheck(day, round(value, 2), back, fwd, qualifies, reason)


def find_strict_local_lows(
    df: pd.DataFrame, start: dt.date, end: dt.date, span: int = SPAN
) -> list[dt.date]:
    """Every qualifying strict local low in [start, end] inclusive."""
    low = _require_ohlc(df, "low")
    out: list[dt.date] = []
    for ts in low.loc[pd.Timestamp(start): pd.Timestamp(end)].index:
        if is_strict_local_low(df, ts.date(), span) is True:
            out.append(ts.date())
    return out
