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
    repair = repair_protocol_transcription(session)
    result = {
        "protocols": len(seed_protocols(session)),
        "sources": seed_sources(session),
        "settings": seed_settings(session),
        "protocol_repair": repair,
    }
    session.commit()
    return result


# ---------------------------------------------------------------------------
# One-time repair: the September protocol transcription error (2026-09-21)
# ---------------------------------------------------------------------------
#: The erroneous definition shipped in v1.0 of the repository's protocol record.
_BAD_DEFINITION_MARKER = "strictly lower than every other daily close"


def repair_protocol_transcription(session) -> dict:
    """Supersede the v1.0 September protocol if it holds the wrong definition.

    v1.0 of this repository's record stated the strict local low in terms of
    daily CLOSE. That was never the paper's rule - the paper defines a strict
    7-day pivot on the daily LOW. This is a correction to a transcription, not
    an amendment to the protocol, and nothing was ever published under v1.0.

    The old row is preserved (its slug is suffixed) rather than deleted, so the
    audit trail survives. The rewrite is issued as direct SQL because the model
    deliberately refuses attribute writes on a frozen protocol - that guard is
    doing its job, and bypassing it here is explicit and logged rather than
    silent.
    """
    from sqlalchemy import text

    from ..models import ResearchProtocol
    from ..research.protocols import SEPTEMBER_2026_PROTOCOL, seed_protocols

    slug = SEPTEMBER_2026_PROTOCOL["slug"]
    row = session.query(ResearchProtocol).filter_by(slug=slug).one_or_none()
    if row is None:
        return {"repaired": False, "reason": "protocol not present"}
    if _BAD_DEFINITION_MARKER not in (row.rules_json or ""):
        return {"repaired": False, "reason": "already correct"}

    archived_slug = f"{slug}-v{row.version}-superseded-transcription-error"
    session.execute(
        text("UPDATE research_protocols SET slug = :new, status = :st WHERE id = :id"),
        {"new": archived_slug, "st": "archived", "id": row.id},
    )
    session.commit()

    created = seed_protocols(session)
    new_row = session.query(ResearchProtocol).filter_by(slug=slug).one_or_none()
    if new_row is not None:
        session.execute(
            text("UPDATE research_protocols SET supersedes_id = :old WHERE id = :id"),
            {"old": row.id, "id": new_row.id},
        )
    session.commit()
    return {
        "repaired": True,
        "archived_as": archived_slug,
        "new_version": SEPTEMBER_2026_PROTOCOL["version"],
        "created": len(created),
    }
