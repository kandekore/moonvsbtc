"""Public serializers.

Everything the public site renders passes through here. The rules are enforced
in code rather than left to template discipline:

* Only PUBLISHED records with PUBLIC visibility are ever emitted.
* Conversations and messages have NO public serializer at all - asking for one
  raises. That is the privacy boundary (spec s3, s20).
* Private/trading fields are never in the emitted dict, even for a record that
  is otherwise public.
"""
from __future__ import annotations

import datetime as dt
import json

from ..models import (
    Article, Conversation, Message, Observation, Outlook, Prediction,
    Provenance, Result, Status, Visibility,
)


class PrivateDataLeak(RuntimeError):
    """Raised when code attempts to publicly serialize private material."""


#: Never emitted publicly under any circumstance.
FORBIDDEN_PUBLIC_FIELDS = frozenset({
    "password_hash", "context_json", "conversation_id", "editor_note",
    "position_size", "leverage", "pnl", "stop_loss", "take_profit",
    "exchange_balance", "entry_price",
})


def assert_public(obj) -> None:
    """Guard: refuse anything not explicitly published and public."""
    if isinstance(obj, (Conversation, Message)):
        raise PrivateDataLeak(
            f"{type(obj).__name__} is private laboratory material and has no "
            f"public representation."
        )
    status = getattr(obj, "status", None)
    visibility = getattr(obj, "visibility", None)
    if status is not None and status != Status.PUBLISHED:
        raise PrivateDataLeak(
            f"{type(obj).__name__} id={getattr(obj, 'id', '?')} has status "
            f"{status!r}; only published records may be served publicly."
        )
    if visibility is not None and visibility != Visibility.PUBLIC:
        raise PrivateDataLeak(
            f"{type(obj).__name__} id={getattr(obj, 'id', '?')} has visibility "
            f"{visibility!r}; only public records may be served publicly."
        )


def is_publicly_visible(obj) -> bool:
    try:
        assert_public(obj)
    except PrivateDataLeak:
        return False
    return True


def _iso(value):
    return value.isoformat() if isinstance(value, (dt.datetime, dt.date)) else value


def _loads(raw, default):
    try:
        return json.loads(raw) if raw else default
    except (json.JSONDecodeError, TypeError):
        return default


def _scrub(payload: dict) -> dict:
    leaked = FORBIDDEN_PUBLIC_FIELDS & payload.keys()
    if leaked:
        raise PrivateDataLeak(f"Private fields would be exposed: {sorted(leaked)}")
    return payload


def provenance_notice(obj) -> str | None:
    """The visible label a reconstructed record must carry (spec s10)."""
    prov = getattr(obj, "provenance", None)
    if prov not in Provenance.RETROSPECTIVE:
        return None
    observed = getattr(obj, "observed_at", None)
    published = getattr(obj, "published_at", None)
    when = f" describing {observed.date().isoformat()}" if observed else ""
    pub = f", published here on {published.date().isoformat()}" if published else ""
    label = (
        "Reconstructed archive entry" if prov == Provenance.RECONSTRUCTED_ARCHIVE
        else "From the exploratory research paper"
    )
    return (
        f"{label}{when}{pub}. This was written up from contemporaneous records "
        f"after the fact - it was not published on this site at the time."
    )


def public_article(article: Article) -> dict:
    assert_public(article)
    return _scrub({
        "slug": article.slug,
        "title": article.title,
        "subtitle": article.subtitle,
        "summary": article.summary,
        "body_markdown": article.body_markdown,
        "article_type": article.article_type,
        "record_kind": article.record_kind,
        "observed_at": _iso(article.observed_at),
        "published_at": _iso(article.published_at),
        "provenance": article.provenance,
        "is_reconstructed": article.is_reconstructed,
        "provenance_notice": provenance_notice(article),
        "sources": _loads(article.sources_json, []),
        "meta_description": article.meta_description,
        "canonical_url": article.canonical_url,
        "og_image": article.og_image,
        "ai_generated": article.ai_generated,
    })


def public_prediction(prediction: Prediction, include_results: bool = True) -> dict:
    assert_public(prediction)
    payload = {
        "slug": prediction.slug,
        "title": prediction.title,
        # The locked box. Immutable once published.
        "prediction_text": prediction.prediction_text,
        "test_criteria": prediction.test_criteria,
        "invalidation_criteria": prediction.invalidation_criteria,
        "confidence": prediction.confidence,
        "evidence_snapshot": _loads(prediction.evidence_snapshot_json, {}),
        "made_at": _iso(prediction.made_at),
        "horizon_end": _iso(prediction.horizon_end),
        "published_at": _iso(prediction.published_at),
        "outcome": prediction.outcome,
        "provenance": prediction.provenance,
        "provenance_notice": provenance_notice(prediction),
        "is_locked": prediction.is_locked,
    }
    if include_results:
        payload["results"] = [
            public_result(r, include_prediction=False)
            for r in prediction.results if is_publicly_visible(r)
        ]
    return _scrub(payload)


def public_result(result: Result, include_prediction: bool = True) -> dict:
    assert_public(result)
    payload = {
        "slug": result.slug,
        "title": result.title,
        "body": result.body,
        "outcome": result.outcome,
        "timing_error_days": result.timing_error_days,
        "price_at_prediction": result.price_at_prediction,
        "price_at_result": result.price_at_result,
        "subsequent_high": result.subsequent_high,
        "subsequent_low": result.subsequent_low,
        "max_upside_pct": result.max_upside_pct,
        "max_downside_pct": result.max_downside_pct,
        "metrics": _loads(result.metrics_json, {}),
        "lessons": result.lessons,
        "sources": _loads(result.sources_json, []),
        "recorded_at": _iso(result.recorded_at),
        "published_at": _iso(result.published_at),
        "provenance_notice": provenance_notice(result),
    }
    if include_prediction and result.prediction and is_publicly_visible(result.prediction):
        payload["prediction"] = public_prediction(result.prediction, include_results=False)
    return _scrub(payload)


def public_observation(observation: Observation) -> dict:
    assert_public(observation)
    return _scrub({
        "slug": observation.slug,
        "title": observation.title,
        "body": observation.body,
        "observed_at": _iso(observation.observed_at),
        "published_at": _iso(observation.published_at),
        "provenance": observation.provenance,
        "provenance_notice": provenance_notice(observation),
        "btc_snapshot": _loads(observation.btc_snapshot_json, {}),
        "moon_context": _loads(observation.moon_context_json, {}),
        "sources": _loads(observation.sources_json, []),
    })


def public_outlook(outlook: Outlook) -> dict:
    assert_public(outlook)
    return _scrub({
        "slug": outlook.slug,
        "kind": outlook.kind,
        "title": outlook.title,
        "summary": outlook.summary,
        "body_markdown": outlook.body_markdown,
        "period_start": _iso(outlook.period_start),
        "period_end": _iso(outlook.period_end),
        "natal_context": _loads(outlook.natal_context_json, {}),
        "lunar_context": _loads(outlook.lunar_context_json, {}),
        "technical_context": _loads(outlook.technical_context_json, {}),
        "levels": _loads(outlook.levels_json, {}),
        "events": _loads(outlook.events_json, []),
        "review_markdown": outlook.review_markdown,
        "review_recorded_at": _iso(outlook.review_recorded_at),
        "published_at": _iso(outlook.published_at),
        "ai_generated": outlook.ai_generated,
    })
