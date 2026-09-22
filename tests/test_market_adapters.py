"""OHLC fetching must degrade, not vanish.

`.cache/` is git-ignored, so a fresh deployment has no cached OHLC and must
fetch live. Two things previously turned a recoverable situation into a total
failure, and both silently downgraded the track record to closing prices:

  * the fetch demanded a ``Volume`` column, so a provider response that the
    close-only path handled perfectly well aborted the whole OHLC fetch;
  * ``_cache_path`` created the cache directory eagerly and let ``OSError``
    escape, so a non-writable working directory stopped a live fetch that had
    no need to touch disk at all.
"""
from __future__ import annotations

import pathlib

import pandas as pd
import pytest

from btcmoon.market_data import adapters


@pytest.fixture()
def raw_ohlc(ohlc_df):
    """A provider-shaped response: title-case columns, DatetimeIndex."""
    return ohlc_df.rename(columns=str.title).copy()


def _patch_yf(monkeypatch, frame):
    """Install a fake yfinance whose download() returns ``frame``."""
    import sys
    import types

    fake = types.ModuleType("yfinance")
    fake.download = lambda *a, **k: frame
    monkeypatch.setitem(sys.modules, "yfinance", fake)


def test_volume_is_not_required(monkeypatch, tmp_path, raw_ohlc):
    """The exact failure that forced the app onto closing prices."""
    monkeypatch.setattr(adapters, "CACHE_DIR", tmp_path / "cache")
    _patch_yf(monkeypatch, raw_ohlc.drop(columns=["Volume"]))

    df = adapters.get_ohlc_history(force_refresh=True)
    assert {"high", "low", "close"} <= set(df.columns)
    assert "volume" not in df.columns
    assert len(df) > 100


def test_volume_is_kept_when_present(monkeypatch, tmp_path, raw_ohlc):
    monkeypatch.setattr(adapters, "CACHE_DIR", tmp_path / "cache")
    _patch_yf(monkeypatch, raw_ohlc)
    df = adapters.get_ohlc_history(force_refresh=True)
    assert {"open", "high", "low", "close", "volume"} <= set(df.columns)


def test_missing_high_low_is_reported_clearly(monkeypatch, tmp_path, raw_ohlc):
    monkeypatch.setattr(adapters, "CACHE_DIR", tmp_path / "cache")
    _patch_yf(monkeypatch, raw_ohlc[["Close"]])
    with pytest.raises(adapters.MarketError, match=r"lacks"):
        adapters.get_ohlc_history(force_refresh=True)


def test_unwritable_cache_directory_does_not_block_a_fetch(
    monkeypatch, tmp_path, raw_ohlc
):
    """A service whose working directory is read-only must still get data."""
    blocked = tmp_path / "no-write"
    blocked.write_text("I am a file, not a directory")
    monkeypatch.setattr(adapters, "CACHE_DIR", blocked / "cache")
    _patch_yf(monkeypatch, raw_ohlc)

    df = adapters.get_ohlc_history(force_refresh=True)
    assert {"high", "low"} <= set(df.columns)
    assert len(df) > 100


def test_cache_path_never_raises(monkeypatch, tmp_path):
    blocked = tmp_path / "afile"
    blocked.write_text("x")
    monkeypatch.setattr(adapters, "CACHE_DIR", blocked / "nested")
    path = adapters._cache_path("BTC-USD")
    assert isinstance(path, pathlib.Path)


def test_stale_cache_is_used_when_the_fetch_fails(monkeypatch, tmp_path, raw_ohlc):
    """Degrade to yesterday's OHLC rather than to closing prices."""
    cache = tmp_path / "cache"
    monkeypatch.setattr(adapters, "CACHE_DIR", cache)
    _patch_yf(monkeypatch, raw_ohlc)
    first = adapters.get_ohlc_history(force_refresh=True)
    assert not first.empty

    def boom(*a, **k):
        raise RuntimeError("outbound HTTPS blocked")

    import sys
    import types

    fake = types.ModuleType("yfinance")
    fake.download = boom
    monkeypatch.setitem(sys.modules, "yfinance", fake)

    again = adapters.get_ohlc_history(force_refresh=True)
    assert {"high", "low"} <= set(again.columns)
    assert len(again) == len(first)


def test_rows_with_a_missing_high_are_dropped(monkeypatch, tmp_path, raw_ohlc):
    frame = raw_ohlc.copy()
    frame.iloc[5, frame.columns.get_loc("High")] = None
    monkeypatch.setattr(adapters, "CACHE_DIR", tmp_path / "cache")
    _patch_yf(monkeypatch, frame)
    df = adapters.get_ohlc_history(force_refresh=True)
    assert df["high"].notna().all()
    assert len(df) == len(frame) - 1
