"""Adapter over the legacy research engine.

``moon_engine.py`` stays at the repository root, unchanged, as the canonical
implementation of the published website methodology. Nothing in this package
reimplements its calculations - we only call it with the documented parameters
and wrap the result.

The parameters below ARE the methodology (spec s8). Changing one is a new
versioned ResearchProtocol, never an edit here.
"""
from __future__ import annotations

import datetime as dt
from dataclasses import asdict, dataclass

import pandas as pd

import moon_engine as me

#: The exact parameters the legacy website used. Do not tune these.
WEBSITE_METHODOLOGY = {
    "price_source": "Yahoo Finance BTC-USD daily Close (auto-adjusted)",
    "phase_source": "PyEphem next_full_moon / next_new_moon, reduced to calendar dates",
    "pivot_detector": "scipy.signal.find_peaks",
    "min_pivot_spacing_days": 30,
    "prominence_pct_of_median_close": 15.0,
    "max_lag_days": 14,
    "signed_lag": "pivot_date - moon_date (positive = pivot AFTER the moon)",
    "full_moon_matches": "nearest significant swing HIGH within +/-14 days",
    "new_moon_matches": "nearest significant swing LOW within +/-14 days",
}


def website_params() -> dict:
    """Keyword arguments that reproduce the published website methodology."""
    return {
        "distance": WEBSITE_METHODOLOGY["min_pivot_spacing_days"],
        "prominence_pct": WEBSITE_METHODOLOGY["prominence_pct_of_median_close"],
        "max_lag": WEBSITE_METHODOLOGY["max_lag_days"],
    }


def legacy_analysis(
    price_df: pd.DataFrame | None = None,
    start: str = "2014-09-17",
    end: str | None = None,
    horizon_days: int = 120,
) -> me.AnalysisResult:
    """Run the legacy pipeline with the frozen website parameters."""
    return me.run_analysis(
        start=start, end=end, horizon_days=horizon_days,
        price_df=price_df, **website_params(),
    )


@dataclass
class OffsetSummary:
    label: str
    n: int
    mean: float
    median: float
    std: float
    min: int
    max: int
    pct_after_moon: float | None = None

    def to_dict(self) -> dict:
        return asdict(self)


def legacy_offset_summary(res: me.AnalysisResult) -> dict:
    """Both offset distributions in a JSON-friendly shape."""
    out = {}
    for key, stats, matched in (
        ("full_moon_to_high", res.top_stats, res.top_matches),
        ("new_moon_to_low", res.bottom_stats, res.bottom_matches),
    ):
        pct_after = None
        if not matched.empty:
            pct_after = round(float((matched["offset_days"] > 0).mean()) * 100.0, 1)
        out[key] = OffsetSummary(
            label=stats.label, n=stats.n, mean=round(stats.mean, 3),
            median=round(stats.median, 3), std=round(stats.std, 3),
            min=stats.min, max=stats.max, pct_after_moon=pct_after,
        ).to_dict()
    return out
