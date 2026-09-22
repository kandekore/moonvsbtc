"""Market data behind an adapter, so the provider can change without touching
the research or editorial code (spec s7).

The default provider is yfinance - the same source the legacy methodology used,
which matters for reproducibility. Price history is cached on disk so briefings,
outlooks and the public site do not each re-download twelve years of candles.
"""
from __future__ import annotations

import datetime as dt
import json
import os
import pathlib

import numpy as np
import pandas as pd

from ..config import Config

CACHE_DIR = pathlib.Path(os.getenv("BTCMOON_CACHE_DIR", ".cache"))
CACHE_TTL_MINUTES = int(os.getenv("MARKET_CACHE_TTL_MINUTES", "30"))
HISTORY_START = "2014-09-17"


class MarketError(RuntimeError):
    """Raised when no usable price data could be obtained."""


def _cache_path(symbol: str) -> pathlib.Path:
    """Where this symbol is cached. Never raises.

    CACHE_DIR is relative by default, so it resolves against the process's
    working directory - which for a service is not necessarily the app root. If
    it cannot be created, caching is simply unavailable; that must not stop a
    live fetch from succeeding.
    """
    try:
        CACHE_DIR.mkdir(parents=True, exist_ok=True)
    except OSError:
        pass
    return CACHE_DIR / f"{symbol.replace('/', '_')}_daily.csv"


def _cache_is_fresh(path: pathlib.Path) -> bool:
    if not path.exists():
        return False
    age = dt.datetime.now() - dt.datetime.fromtimestamp(path.stat().st_mtime)
    return age < dt.timedelta(minutes=CACHE_TTL_MINUTES)


def get_price_history(
    symbol: str = "BTC-USD",
    start: str = HISTORY_START,
    force_refresh: bool = False,
    allow_cache: bool = True,
) -> pd.DataFrame:
    """Daily close history as the legacy tidy frame (``close`` on a DatetimeIndex).

    Falls back to a stale cache if the network is unavailable, so a cron job on
    a flaky connection degrades rather than fails.
    """
    path = _cache_path(symbol)
    if allow_cache and not force_refresh and _cache_is_fresh(path):
        return _read_cache(path)

    try:
        import moon_engine as me

        df = me.fetch_btc(start=start) if symbol == "BTC-USD" else _fetch_generic(symbol, start)
        df.to_csv(path)
        return df
    except Exception as exc:                      # network down, provider change, ...
        if path.exists():
            return _read_cache(path)
        raise MarketError(f"Could not fetch {symbol}: {exc}") from exc


def get_ohlc_history(
    symbol: str = "BTC-USD",
    start: str = HISTORY_START,
    force_refresh: bool = False,
) -> pd.DataFrame:
    """Daily OHLCV history: ``open, high, low, close, volume`` on a DatetimeIndex.

    REQUIRED by the New-Moon / local-low protocol, which is defined on intraday
    extremes (daily LOW), not on closing prices. ``get_price_history`` returns
    close only and is for the legacy website methodology - do not substitute one
    for the other.
    """
    path = _cache_path(symbol + "_ohlc")
    if not force_refresh and _cache_is_fresh(path):
        return _read_cache(path)

    try:
        import yfinance as yf

        raw = yf.download(symbol, start=start, progress=False, auto_adjust=True)
        if raw is None or raw.empty:
            raise MarketError(f"No OHLC data for {symbol}")
        df = raw.copy()
        if isinstance(df.columns, pd.MultiIndex):
            df.columns = [c[0] for c in df.columns]
        df.columns = [str(c).lower() for c in df.columns]
        required = ["high", "low", "close"]
        missing = [c for c in required if c not in df.columns]
        if missing:
            raise MarketError(
                f"{symbol} response lacks {missing}; got {sorted(df.columns)}"
            )
        # Volume and open are kept when present but are NOT required - insisting
        # on them made this fail where the close-only fetch succeeded.
        keep = [c for c in ("open", "high", "low", "close", "volume")
                if c in df.columns]
        df = df[keep]
        df.index = pd.to_datetime(df.index).tz_localize(None).normalize()
        df = df[~df.index.duplicated(keep="last")].sort_index()
        df = df.dropna(subset=required)
        try:
            df.to_csv(path)
        except OSError:
            pass                       # cache unavailable; the data is still good
        return df
    except Exception as exc:
        if path.exists():
            return _read_cache(path)
        raise MarketError(f"Could not fetch OHLC for {symbol}: {exc}") from exc


def _read_cache(path: pathlib.Path) -> pd.DataFrame:
    df = pd.read_csv(path, index_col=0, parse_dates=True)
    df.index.name = "Date"
    return df


def _fetch_generic(symbol: str, start: str) -> pd.DataFrame:
    import yfinance as yf

    raw = yf.download(symbol, start=start, progress=False, auto_adjust=True)
    if raw is None or raw.empty:
        raise MarketError(f"No data for {symbol}")
    close = raw["Close"]
    if isinstance(close, pd.DataFrame):
        close = close.iloc[:, 0]
    df = pd.DataFrame({"close": close.astype(float)})
    df.index = pd.to_datetime(df.index).tz_localize(None).normalize()
    return df[~df.index.duplicated(keep="last")].sort_index().dropna()


# ---------------------------------------------------------------------------
# Derived technical context
# ---------------------------------------------------------------------------
def _rsi(series: pd.Series, period: int = 14) -> float | None:
    if len(series) < period + 1:
        return None
    delta = series.diff().dropna()
    gain = delta.clip(lower=0).rolling(period).mean()
    loss = (-delta.clip(upper=0)).rolling(period).mean()
    last_gain, last_loss = float(gain.iloc[-1]), float(loss.iloc[-1])
    if last_loss == 0:
        return 100.0
    rs = last_gain / last_loss
    return round(100.0 - (100.0 / (1.0 + rs)), 2)


def _swing_levels(series: pd.Series, lookback_days: int = 180, count: int = 4) -> dict:
    """Recent swing highs/lows as candidate support and resistance."""
    from scipy.signal import find_peaks

    recent = series.tail(lookback_days)
    if len(recent) < 30:
        return {"support": [], "resistance": []}
    arr = recent.to_numpy(dtype=float)
    prom = float(np.median(arr)) * 0.03
    hi_idx, _ = find_peaks(arr, distance=5, prominence=prom)
    lo_idx, _ = find_peaks(-arr, distance=5, prominence=prom)
    last = float(arr[-1])

    highs = sorted({round(float(arr[i]), 2) for i in hi_idx if arr[i] > last})
    lows = sorted({round(float(arr[i]), 2) for i in lo_idx if arr[i] < last}, reverse=True)
    return {"support": lows[:count], "resistance": highs[:count]}


def technical_context(price: pd.DataFrame | None = None) -> dict:
    """Deterministic, cheap technical context. No AI involved (spec s19)."""
    df = price if price is not None else get_price_history()
    s = df["close"].astype(float)
    last = float(s.iloc[-1])

    def pct_change(days: int) -> float | None:
        if len(s) <= days:
            return None
        prior = float(s.iloc[-1 - days])
        return round((last - prior) / prior * 100.0, 2)

    returns = s.pct_change().dropna()
    vol30 = (
        round(float(returns.tail(30).std()) * (365 ** 0.5) * 100.0, 2)
        if len(returns) >= 30 else None
    )
    ma50 = round(float(s.tail(50).mean()), 2) if len(s) >= 50 else None
    ma200 = round(float(s.tail(200).mean()), 2) if len(s) >= 200 else None

    regime = "undetermined"
    if ma50 and ma200:
        if last > ma50 > ma200:
            regime = "uptrend (price > 50d > 200d)"
        elif last < ma50 < ma200:
            regime = "downtrend (price < 50d < 200d)"
        else:
            regime = "mixed / transitional"

    levels = _swing_levels(s)
    return {
        "as_of": s.index[-1].date().isoformat(),
        "price": round(last, 2),
        "change_24h_pct": pct_change(1),
        "change_7d_pct": pct_change(7),
        "change_30d_pct": pct_change(30),
        "annualised_volatility_30d_pct": vol30,
        "ma50": ma50,
        "ma200": ma200,
        "rsi14": _rsi(s),
        "regime": regime,
        "support": levels["support"],
        "resistance": levels["resistance"],
        "all_time_high": round(float(s.max()), 2),
        "pct_from_ath": round((last - float(s.max())) / float(s.max()) * 100.0, 2),
    }


def snapshot_dict(price: pd.DataFrame | None = None) -> dict:
    """Alias kept explicit: the JSON blob frozen into evidence records."""
    return technical_context(price)


def latest_snapshot(session, price: pd.DataFrame | None = None, persist: bool = True):
    """Build (and optionally store) a ``MarketSnapshot`` row."""
    from ..models import MarketSnapshot

    ctx = technical_context(price)
    snap = MarketSnapshot(
        snapshot_date=dt.date.fromisoformat(ctx["as_of"]),
        symbol="BTC-USD",
        price=ctx["price"],
        close=ctx["price"],
        change_24h_pct=ctx["change_24h_pct"],
        change_7d_pct=ctx["change_7d_pct"],
        volatility_30d=ctx["annualised_volatility_30d_pct"],
        ma50=ctx["ma50"],
        ma200=ctx["ma200"],
        rsi14=ctx["rsi14"],
        support_levels_json=json.dumps(ctx["support"]),
        resistance_levels_json=json.dumps(ctx["resistance"]),
        provider=Config.MARKET_PROVIDER,
        raw_json=json.dumps(ctx),
    )
    if persist:
        session.add(snap)
        session.flush()
    return snap
