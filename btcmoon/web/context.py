"""Live "BTC Now / Moon Now" context for the public site.

Cached in-process for a few minutes so a traffic spike does not hammer the
market provider, and degrading to a cached/stale value rather than a 500 if the
provider is unreachable.
"""
from __future__ import annotations

import datetime as dt
import threading

from ..astrology import natal_context
from ..lunar import lunar_context
from ..market_data import MarketError, technical_context

_CACHE: dict = {}
_LOCK = threading.Lock()
_TTL = dt.timedelta(minutes=5)


def _cached(key: str, producer):
    now = dt.datetime.now()
    with _LOCK:
        hit = _CACHE.get(key)
        if hit and now - hit[0] < _TTL:
            return hit[1]
    try:
        value = producer()
    except Exception:
        with _LOCK:
            hit = _CACHE.get(key)
        return hit[1] if hit else None
    with _LOCK:
        _CACHE[key] = (now, value)
    return value


def btc_now() -> dict | None:
    return _cached("btc", technical_context)


def moon_now() -> dict | None:
    return _cached("moon", lambda: lunar_context().to_dict())


def natal_now(when: dt.date | None = None) -> dict | None:
    when = when or dt.date.today()
    return _cached(f"natal:{when.isoformat()}", lambda: natal_context(when))


def clear_cache() -> None:
    with _LOCK:
        _CACHE.clear()
