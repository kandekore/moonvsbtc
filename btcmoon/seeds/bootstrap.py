"""First-run bootstrap: protocols, news sources, default settings."""
from __future__ import annotations

from ..config import Config
from ..models import AppSetting
from ..news.feeds import seed_sources
from ..research.protocols import seed_protocols


def seed_settings(session) -> int:
    defaults = [
        ("ai_monthly_budget_usd", str(Config.AI_MONTHLY_BUDGET_USD),
         "Hard monthly AI ceiling in USD. At this figure all non-essential AI generation stops."),
        ("ai_daily_budget_usd", str(Config.AI_DAILY_BUDGET_USD), "Daily AI ceiling in USD."),
        ("ai_pricing_overrides", "",
         'JSON price overrides, per 1M tokens: {"model": {"input": 0.15, "output": 0.60}}'),
    ]
    added = 0
    for key, value, desc in defaults:
        if session.query(AppSetting).filter_by(key=key).one_or_none():
            continue
        session.add(AppSetting(key=key, value=value, description=desc))
        added += 1
    session.flush()
    return added


def bootstrap(session) -> dict:
    """Idempotent: safe to run on every deploy."""
    result = {
        "protocols": len(seed_protocols(session)),
        "sources": seed_sources(session),
        "settings": seed_settings(session),
    }
    session.commit()
    return result
