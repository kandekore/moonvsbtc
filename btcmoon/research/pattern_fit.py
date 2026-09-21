"""Pattern Fit Score - how well one lunar cycle matched the hypothesis.

The score is 100 points, in four equal parts (spec s8):

    25  New-Moon low alignment    - did a local low form near the New Moon?
    25  waxing appreciation       - did price rise from New Moon to Full Moon?
    25  Full-Moon high alignment  - did a local high form near the Full Moon?
    25  waning weakening          - did price fall from Full Moon to next New Moon?

Nodal strength and market state are stored SEPARATELY and never inflate the
score. The weights are frozen: a change is a new protocol version, not an edit.
"""
from __future__ import annotations

import datetime as dt
from dataclasses import dataclass, field

import numpy as np
import pandas as pd

#: Frozen. Changing a weight is a new versioned protocol (spec s8).
PATTERN_FIT_WEIGHTS = {
    "new_moon_low_alignment": 25.0,
    "waxing_appreciation": 25.0,
    "full_moon_high_alignment": 25.0,
    "waning_weakening": 25.0,
}

#: A pivot this many days from the moon still earns partial credit.
ALIGNMENT_TOLERANCE_DAYS = 7.0
#: Move (in %) at which the appreciation/weakening components max out.
FULL_CREDIT_MOVE_PCT = 10.0


@dataclass
class PatternFit:
    score: float
    components: dict = field(default_factory=dict)
    detail: dict = field(default_factory=dict)

    def to_dict(self) -> dict:
        return {"score": self.score, "components": self.components, "detail": self.detail}


def _alignment_points(offset_days: float | None, weight: float) -> float:
    """Full marks on the moon itself, decaying linearly to zero at the tolerance."""
    if offset_days is None:
        return 0.0
    return round(weight * max(0.0, 1.0 - abs(offset_days) / ALIGNMENT_TOLERANCE_DAYS), 2)


def _move_points(pct: float | None, weight: float, want_up: bool) -> float:
    """Credit a move in the hypothesised direction, capped at FULL_CREDIT_MOVE_PCT."""
    if pct is None:
        return 0.0
    signed = pct if want_up else -pct
    if signed <= 0:
        return 0.0
    return round(weight * min(1.0, signed / FULL_CREDIT_MOVE_PCT), 2)


def _close_on(series: pd.Series, when: dt.date) -> float | None:
    try:
        val = series.asof(pd.Timestamp(when))
    except (KeyError, TypeError):
        return None
    return None if val is None or pd.isna(val) else float(val)


def _extreme_in_window(
    series: pd.Series, start: dt.date, end: dt.date, kind: str
) -> tuple[dt.date, float] | None:
    win = series.loc[pd.Timestamp(start): pd.Timestamp(end)]
    if win.empty:
        return None
    idx = int(np.argmin(win.to_numpy())) if kind == "low" else int(np.argmax(win.to_numpy()))
    return win.index[idx].date(), float(win.iloc[idx])


def pattern_fit_score(
    price: pd.DataFrame,
    new_moon: dt.date,
    full_moon: dt.date,
    next_new_moon: dt.date,
    tolerance_days: float = ALIGNMENT_TOLERANCE_DAYS,
) -> PatternFit:
    """Score one lunar cycle (New Moon -> Full Moon -> next New Moon).

    ``price`` is the legacy tidy frame: a ``close`` column on a DatetimeIndex.
    """
    series = price["close"]
    detail: dict = {}

    # 1) New-Moon low alignment: nearest local low around the New Moon.
    nm_window = _extreme_in_window(
        series, new_moon - dt.timedelta(days=int(tolerance_days)),
        new_moon + dt.timedelta(days=int(tolerance_days)), "low",
    )
    nm_offset = None
    if nm_window:
        low_date, low_price = nm_window
        nm_offset = (low_date - new_moon).days
        detail["new_moon_low"] = {
            "date": low_date.isoformat(), "price": round(low_price, 2),
            "offset_days": nm_offset,
        }

    # 2) Waxing appreciation: New Moon close -> Full Moon close.
    nm_close = _close_on(series, new_moon)
    fm_close = _close_on(series, full_moon)
    waxing_pct = None
    if nm_close and fm_close:
        waxing_pct = round((fm_close - nm_close) / nm_close * 100.0, 3)
        detail["waxing"] = {
            "new_moon_close": round(nm_close, 2), "full_moon_close": round(fm_close, 2),
            "change_pct": waxing_pct,
        }

    # 3) Full-Moon high alignment.
    fm_window = _extreme_in_window(
        series, full_moon - dt.timedelta(days=int(tolerance_days)),
        full_moon + dt.timedelta(days=int(tolerance_days)), "high",
    )
    fm_offset = None
    if fm_window:
        high_date, high_price = fm_window
        fm_offset = (high_date - full_moon).days
        detail["full_moon_high"] = {
            "date": high_date.isoformat(), "price": round(high_price, 2),
            "offset_days": fm_offset,
        }

    # 4) Waning weakening: Full Moon close -> next New Moon close.
    next_nm_close = _close_on(series, next_new_moon)
    waning_pct = None
    if fm_close and next_nm_close:
        waning_pct = round((next_nm_close - fm_close) / fm_close * 100.0, 3)
        detail["waning"] = {
            "full_moon_close": round(fm_close, 2),
            "next_new_moon_close": round(next_nm_close, 2),
            "change_pct": waning_pct,
        }

    components = {
        "new_moon_low_alignment": _alignment_points(
            nm_offset, PATTERN_FIT_WEIGHTS["new_moon_low_alignment"]
        ),
        "waxing_appreciation": _move_points(
            waxing_pct, PATTERN_FIT_WEIGHTS["waxing_appreciation"], want_up=True
        ),
        "full_moon_high_alignment": _alignment_points(
            fm_offset, PATTERN_FIT_WEIGHTS["full_moon_high_alignment"]
        ),
        "waning_weakening": _move_points(
            waning_pct, PATTERN_FIT_WEIGHTS["waning_weakening"], want_up=False
        ),
    }
    detail["cycle"] = {
        "new_moon": new_moon.isoformat(),
        "full_moon": full_moon.isoformat(),
        "next_new_moon": next_new_moon.isoformat(),
    }
    return PatternFit(
        score=round(sum(components.values()), 2), components=components, detail=detail
    )
