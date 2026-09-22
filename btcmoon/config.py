"""Application configuration, driven entirely by environment variables.

Nothing secret is ever hard-coded here. See .env.example for the full list.
"""
from __future__ import annotations

import os
from datetime import date

from dotenv import load_dotenv

load_dotenv()

_TRUE = {"1", "true", "yes", "on"}


def _bool(name: str, default: bool = False) -> bool:
    raw = os.getenv(name)
    if raw is None:
        return default
    return raw.strip().lower() in _TRUE


def _float(name: str, default: float) -> float:
    try:
        return float(os.getenv(name, "") or default)
    except ValueError:
        return default


def _int(name: str, default: int) -> int:
    try:
        return int(os.getenv(name, "") or default)
    except ValueError:
        return default


class Config:
    # --- core ---------------------------------------------------------------
    SECRET_KEY = os.getenv("SECRET_KEY", "dev-only-insecure-key-change-me")
    ENV = os.getenv("FLASK_ENV", "production")
    DEBUG = _bool("FLASK_DEBUG", False)

    # --- database -----------------------------------------------------------
    # Production: mysql+pymysql://user:pass@host/db?charset=utf8mb4
    # Local dev fallback: SQLite file in the repo root.
    DATABASE_URL = os.getenv("DATABASE_URL", "sqlite:///btcmoon.db")
    SQLALCHEMY_ECHO = _bool("SQLALCHEMY_ECHO", False)

    # --- site ---------------------------------------------------------------
    SITE_NAME = os.getenv("SITE_NAME", "Bitcoin vs The Moon")
    SITE_URL = os.getenv("SITE_URL", "https://bitcoinvsthemoon.com").rstrip("/")
    SITE_TAGLINE = os.getenv(
        "SITE_TAGLINE",
        "A public longitudinal experiment: can lunar cycles tell us anything useful about Bitcoin?",
    )
    EDITOR_NAME = os.getenv("EDITOR_NAME", "Darren Kandekore")
    #: The interactive Streamlit pivot explorer (app.py), proxied alongside the
    #: site. Set to an empty string to drop it from the navigation entirely.
    EXPLORER_URL = os.getenv("EXPLORER_URL", "/app/").strip()
    TIMEZONE = os.getenv("TIMEZONE", "Europe/London")

    # --- entitlements -------------------------------------------------------
    # Everything is free through 31 Dec 2026. The paywall machinery exists but
    # stays disabled by configuration until this flag flips.
    PAYWALL_ENABLED = _bool("PAYWALL_ENABLED", False)
    FREE_UNTIL = os.getenv("FREE_UNTIL", "2026-12-31")

    # --- AI providers -------------------------------------------------------
    OPENAI_API_KEY = os.getenv("OPENAI_API_KEY", "")
    OPENAI_BASE_URL = os.getenv("OPENAI_BASE_URL", "") or None
    # Model tiers: cheap work must never silently use the expensive model.
    AI_MODEL_CHEAP = os.getenv("AI_MODEL_CHEAP", "gpt-4o-mini")
    AI_MODEL_STANDARD = os.getenv("AI_MODEL_STANDARD", "gpt-4o-mini")
    AI_MODEL_STRONG = os.getenv("AI_MODEL_STRONG", "gpt-4o")
    AI_ENABLED = _bool("AI_ENABLED", True)
    AI_MAX_OUTPUT_TOKENS = _int("AI_MAX_OUTPUT_TOKENS", 2000)

    # --- AI budget controls (mandatory, spec s19) ---------------------------
    AI_MONTHLY_BUDGET_USD = _float("AI_MONTHLY_BUDGET_USD", 25.0)
    AI_BUDGET_WARN_LEVELS = (0.50, 0.75, 0.90)
    AI_DAILY_BUDGET_USD = _float("AI_DAILY_BUDGET_USD", 5.0)

    # --- market data --------------------------------------------------------
    MARKET_PROVIDER = os.getenv("MARKET_PROVIDER", "yfinance")
    COINGECKO_API_KEY = os.getenv("COINGECKO_API_KEY", "")

    # --- news ---------------------------------------------------------------
    NEWS_MAX_ITEMS_PER_FEED = _int("NEWS_MAX_ITEMS_PER_FEED", 25)
    NEWS_USER_AGENT = os.getenv(
        "NEWS_USER_AGENT", "BitcoinVsTheMoon/1.0 (+https://bitcoinvsthemoon.com)"
    )

    # --- briefings ----------------------------------------------------------
    MORNING_BRIEF_HOUR = _int("MORNING_BRIEF_HOUR", 7)
    EVENING_BRIEF_HOUR = _int("EVENING_BRIEF_HOUR", 18)

    # --- security -----------------------------------------------------------
    SESSION_COOKIE_HTTPONLY = True
    SESSION_COOKIE_SAMESITE = "Lax"
    SESSION_COOKIE_SECURE = _bool("SESSION_COOKIE_SECURE", False)
    WTF_CSRF_TIME_LIMIT = None
    RATELIMIT_STORAGE_URI = os.getenv("RATELIMIT_STORAGE_URI", "memory://")

    @classmethod
    def free_until_date(cls) -> date:
        try:
            return date.fromisoformat(cls.FREE_UNTIL)
        except ValueError:
            return date(2026, 12, 31)
