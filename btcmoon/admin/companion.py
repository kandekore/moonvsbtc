"""The private AI Companion.

Before answering, it retrieves the material the spec requires (s11): active
experiments, prior predictions and results, frozen protocols, lunar and natal
context, market snapshots and recent ingested news.

Everything here is PRIVATE. Nothing written in a conversation reaches the public
site unless the Editor explicitly promotes it with an editorial action.
"""
from __future__ import annotations

import datetime as dt
import json

from ..ai import AiClient
from ..ai.prompts import COMPANION_SYSTEM
from ..astrology import natal_context
from ..lunar import lunar_context
from ..market_data import technical_context
from ..models import (
    Conversation, Experiment, ExperimentStatus, Message, NewsItem, Prediction,
    ResearchProtocol, Result, Status, Visibility, utcnow,
)
from ..news import top_stories

#: How much history to send back to the model.
MAX_HISTORY_TURNS = 12


def build_context(session, limit_news: int = 8) -> dict:
    """Retrieve everything relevant before the model is asked anything."""
    ctx: dict = {"as_of": utcnow().isoformat()}

    try:
        ctx["market"] = technical_context()
    except Exception as exc:
        ctx["market"] = {"error": f"market data unavailable: {exc}"}

    ctx["lunar"] = lunar_context().to_dict()
    ctx["natal"] = natal_context()

    ctx["active_experiments"] = [
        {
            "id": e.id, "ref": e.ref, "title": e.title, "status": e.experiment_status,
            "summary": e.summary, "hypothesis": e.hypothesis_text,
            "prediction": e.prediction_text, "test_criteria": e.test_criteria,
            "invalidation_criteria": e.invalidation_criteria,
            "outcome": e.outcome,
            "starts_at": e.starts_at.isoformat() if e.starts_at else None,
            "ends_at": e.ends_at.isoformat() if e.ends_at else None,
        }
        for e in session.query(Experiment)
        .filter(Experiment.experiment_status.in_(
            (ExperimentStatus.ACTIVE, ExperimentStatus.OBSERVING, ExperimentStatus.PLANNED)))
        .order_by(Experiment.observed_at.desc()).limit(5).all()
    ]

    ctx["recent_predictions"] = [
        {
            "id": p.id, "title": p.title, "text": p.prediction_text,
            "criteria": p.test_criteria, "outcome": p.outcome,
            "status": p.status, "made_at": p.made_at.isoformat() if p.made_at else None,
            "is_locked": p.is_locked,
        }
        for p in session.query(Prediction).order_by(Prediction.made_at.desc()).limit(6).all()
    ]

    ctx["recent_results"] = [
        {
            "id": r.id, "title": r.title, "outcome": r.outcome,
            "timing_error_days": r.timing_error_days, "lessons": r.lessons,
            "recorded_at": r.recorded_at.isoformat() if r.recorded_at else None,
        }
        for r in session.query(Result).order_by(Result.recorded_at.desc()).limit(6).all()
    ]

    ctx["frozen_protocols"] = [
        {
            "slug": p.slug, "version": p.version, "title": p.title,
            "is_frozen": p.is_frozen, "rules": json.loads(p.rules_json or "{}"),
        }
        for p in session.query(ResearchProtocol)
        .filter(ResearchProtocol.is_frozen.is_(True)).all()
    ]

    ctx["recent_news"] = [
        {
            "headline": n.headline, "publisher": n.publisher, "url": n.canonical_url,
            "category": n.category, "relevance": n.relevance_score,
            "published": n.source_published_at.isoformat() if n.source_published_at else None,
        }
        for n in top_stories(session, limit=limit_news, hours=96, min_score=25.0)
    ]
    return ctx


def _render_context(ctx: dict) -> str:
    return (
        "RETRIEVED CONTEXT (JSON). Ground your answer in this; if something you "
        "need is not here, say so rather than inventing it.\n\n"
        + json.dumps(ctx, indent=2, default=str)
    )


def get_or_create_conversation(session, user_id: int, conversation_id: int | None = None):
    if conversation_id:
        convo = (
            session.query(Conversation)
            .filter_by(id=conversation_id, user_id=user_id)   # ownership enforced
            .one_or_none()
        )
        if convo:
            return convo
    convo = Conversation(user_id=user_id, visibility=Visibility.PRIVATE)
    session.add(convo)
    session.flush()
    return convo


def ask(session, conversation: Conversation, user_text: str) -> Message:
    """Record the Editor's turn, call the AI, record and return the reply.

    Returns an assistant Message either way: if the AI is unavailable the reply
    explains why rather than failing, so the laboratory stays usable.
    """
    conversation.messages.append(
        Message(role="user", content=user_text, visibility=Visibility.PRIVATE)
    )
    conversation.last_message_at = utcnow()
    if conversation.title in ("", "New research thread"):
        conversation.title = user_text.strip()[:120] or "New research thread"
    session.flush()

    ctx = build_context(session)
    history = conversation.messages[-MAX_HISTORY_TURNS:]
    transcript = "\n\n".join(
        f"{m.role.upper()}: {m.content}" for m in history if m.role in ("user", "assistant")
    )

    client = AiClient(session)
    resp = client.complete(
        task="companion_chat",
        system=COMPANION_SYSTEM,
        user=f"{_render_context(ctx)}\n\n---\n\nCONVERSATION SO FAR:\n{transcript}",
        conversation_id=conversation.id,
    )

    if resp.ok:
        content = resp.text
    else:
        content = (
            "**The AI Companion is not available right now.**\n\n"
            f"{resp.fallback_reason}\n\n"
            "The retrieved research context below is still accurate and was gathered "
            "without any AI call:\n\n```json\n"
            + json.dumps(
                {
                    "market": ctx.get("market"),
                    "lunar": {
                        k: ctx["lunar"].get(k) for k in
                        ("phase_name", "illumination_pct", "days_since_new_moon",
                         "days_since_full_moon", "next_full_moon", "next_new_moon")
                    } if isinstance(ctx.get("lunar"), dict) else None,
                    "active_experiments": ctx.get("active_experiments"),
                    "recent_news": ctx.get("recent_news", [])[:5],
                },
                indent=2, default=str,
            )
            + "\n```"
        )

    reply = Message(
        role="assistant", content=content, model=resp.model,
        context_json=json.dumps(ctx, default=str),
        ai_usage_id=resp.usage_id, visibility=Visibility.PRIVATE,
    )
    conversation.messages.append(reply)
    conversation.last_message_at = utcnow()
    session.flush()
    return reply
