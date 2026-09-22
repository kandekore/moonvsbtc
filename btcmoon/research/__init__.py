"""Research services.

Imports are resolved lazily (PEP 562). ``protocols`` reaches the ORM, and
therefore SQLAlchemy, but ``legacy``, ``pivots``, ``pattern_fit`` and
``track_record`` are pure pandas/numpy over ``moon_engine``.

Importing this package eagerly would drag the whole database layer in behind any
one of them, which is how the Streamlit dashboard - a chart tool that never
touches the database - came to fail with ``No module named 'sqlalchemy'``. Doing
it on attribute access keeps ``import btcmoon.research.track_record`` as cheap as
its own dependencies, while every existing ``from btcmoon.research import X``
call site keeps working unchanged.
"""
from __future__ import annotations

from typing import TYPE_CHECKING

#: Public name -> the submodule that defines it.
_EXPORTS = {
    "WEBSITE_METHODOLOGY": "legacy",
    "legacy_analysis": "legacy",
    "legacy_offset_summary": "legacy",
    "website_params": "legacy",
    "PATTERN_FIT_WEIGHTS": "pattern_fit",
    "PatternFit": "pattern_fit",
    "pattern_fit_score": "pattern_fit",
    "SEPTEMBER_2026_PROTOCOL": "protocols",
    "WEBSITE_METHODOLOGY_PROTOCOL": "protocols",
    "evaluate_nm_low_test": "protocols",
    "seed_protocols": "protocols",
    "MIN_PRIOR_MATCHES": "track_record",
    "TrackRecordEntry": "track_record",
    "build_track_record": "track_record",
    "track_record_frame": "track_record",
    "track_record_summary": "track_record",
}

__all__ = sorted(_EXPORTS)


def __getattr__(name: str):
    """Import the defining submodule on first access (PEP 562)."""
    module_name = _EXPORTS.get(name)
    if module_name is None:
        raise AttributeError(f"module {__name__!r} has no attribute {name!r}")
    import importlib

    module = importlib.import_module(f".{module_name}", __name__)
    value = getattr(module, name)
    globals()[name] = value          # cache, so this runs once per name
    return value


def __dir__() -> list[str]:
    return sorted(set(globals()) | set(_EXPORTS))


if TYPE_CHECKING:                    # for type checkers and IDEs only
    from .legacy import (
        WEBSITE_METHODOLOGY, legacy_analysis, legacy_offset_summary,
        website_params,
    )
    from .pattern_fit import PATTERN_FIT_WEIGHTS, PatternFit, pattern_fit_score
    from .protocols import (
        SEPTEMBER_2026_PROTOCOL, WEBSITE_METHODOLOGY_PROTOCOL,
        evaluate_nm_low_test, seed_protocols,
    )
    from .track_record import (
        MIN_PRIOR_MATCHES, TrackRecordEntry, build_track_record,
        track_record_frame, track_record_summary,
    )
