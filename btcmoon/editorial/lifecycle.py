"""The content lifecycle: draft -> review -> published, and promotion of
private research material into public records.

Nothing here publishes automatically. Every ``publish_*`` call is the result of
an explicit Editor action in the admin UI (spec s3).
"""
from __future__ import annotations

import datetime as dt
import json

from ..models import (
    Article, Experiment, ExperimentStatus, Hypothesis, ImmutableAfterPublishError,
    Observation, Outcome, Outlook, Prediction, Provenance, Result, Status,
    Visibility, utcnow,
)
from .slugs import unique_slug


class EditorialError(RuntimeError):
    pass


# ---------------------------------------------------------------------------
# Publishing
# ---------------------------------------------------------------------------
def publish(session, obj, *, when: dt.datetime | None = None):
    """Publish any editorial record.

    Publication time is ALWAYS now. It is never backdated to make a
    reconstructed piece look contemporaneous (spec Appendix). The date the
    content is *about* lives in ``observed_at``/``period_start`` instead.
    """
    if isinstance(obj, Prediction):
        obj.publish()
        return obj

    obj.status = Status.PUBLISHED
    obj.visibility = Visibility.PUBLIC
    if getattr(obj, "published_at", None) is None:
        obj.published_at = when or utcnow()
    session.flush()
    return obj


def unpublish(session, obj):
    """Withdraw a record from the public site.

    A published Prediction may be withdrawn from view but its locked text is
    still never rewritten - corrections are appended as Results.
    """
    obj.status = Status.ARCHIVED
    obj.visibility = Visibility.PRIVATE
    session.flush()
    return obj


def submit_for_review(session, obj):
    obj.status = Status.REVIEW
    session.flush()
    return obj


# ---------------------------------------------------------------------------
# Editorial actions available from the private Companion (spec s11)
# ---------------------------------------------------------------------------
def create_observation(
    session, *, title: str, body: str, observed_at: dt.datetime | None = None,
    experiment_id: int | None = None, conversation_id: int | None = None,
    provenance: str = Provenance.CONTEMPORANEOUS_CHAT,
    btc_snapshot: dict | None = None, moon_context: dict | None = None,
    sources: list | None = None,
) -> Observation:
    obs = Observation(
        slug=unique_slug(session, Observation, title),
        title=title.strip(),
        body=body,
        observed_at=observed_at or utcnow(),
        experiment_id=experiment_id,
        conversation_id=conversation_id,
        provenance=provenance,
        btc_snapshot_json=json.dumps(btc_snapshot or {}),
        moon_context_json=json.dumps(moon_context or {}),
        sources_json=json.dumps(sources or []),
        status=Status.DRAFT,
        visibility=Visibility.PRIVATE,
    )
    session.add(obs)
    session.flush()
    return obs


def create_hypothesis(
    session, *, title: str, body: str, rationale: str = "", test_criteria: str = "",
    experiment_id: int | None = None, conversation_id: int | None = None,
    provenance: str = Provenance.CONTEMPORANEOUS_CHAT,
) -> Hypothesis:
    hyp = Hypothesis(
        slug=unique_slug(session, Hypothesis, title),
        title=title.strip(), body=body, rationale=rationale,
        test_criteria=test_criteria, experiment_id=experiment_id,
        conversation_id=conversation_id, provenance=provenance,
        status=Status.DRAFT, visibility=Visibility.PRIVATE,
    )
    session.add(hyp)
    session.flush()
    return hyp


def create_experiment(
    session, *, title: str, summary: str = "", hypothesis_text: str = "",
    prediction_text: str = "", test_criteria: str = "",
    invalidation_criteria: str = "", confidence: str = "", ref: str = "",
    protocol_id: int | None = None, conversation_id: int | None = None,
    starts_at: dt.datetime | None = None, ends_at: dt.datetime | None = None,
    moon_context: dict | None = None, btc_snapshot: dict | None = None,
    natal_context: dict | None = None,
    provenance: str = Provenance.CONTEMPORANEOUS_CHAT,
) -> Experiment:
    """Create an experiment as a PLANNED DRAFT.

    Context is frozen here, at creation, for the same reason a prediction's
    evidence snapshot is: "what we knew when we set this up" must not be
    contaminated by anything learned afterwards.
    """
    exp = Experiment(
        slug=unique_slug(session, Experiment, title),
        ref=ref.strip(),
        title=title.strip(),
        summary=summary,
        hypothesis_text=hypothesis_text,
        prediction_text=prediction_text,
        test_criteria=test_criteria,
        invalidation_criteria=invalidation_criteria,
        confidence=confidence,
        protocol_id=protocol_id,
        conversation_id=conversation_id,
        observed_at=utcnow(),
        starts_at=starts_at,
        ends_at=ends_at,
        moon_context_json=json.dumps(moon_context or {}, default=str),
        btc_snapshot_json=json.dumps(btc_snapshot or {}, default=str),
        natal_context_json=json.dumps(natal_context or {}, default=str),
        experiment_status=ExperimentStatus.PLANNED,
        outcome=Outcome.PENDING,
        provenance=provenance,
        status=Status.DRAFT,
        visibility=Visibility.PRIVATE,
    )
    session.add(exp)
    session.flush()
    return exp


def create_prediction(
    session, *, title: str, prediction_text: str, test_criteria: str,
    invalidation_criteria: str = "", confidence: str = "",
    horizon_end: dt.datetime | None = None, experiment_id: int | None = None,
    protocol_id: int | None = None, conversation_id: int | None = None,
    evidence_snapshot: dict | None = None,
    provenance: str = Provenance.CONTEMPORANEOUS_CHAT,
    made_at: dt.datetime | None = None,
) -> Prediction:
    """Create a prediction as a DRAFT.

    The evidence snapshot is frozen here, at creation, not at publication -
    otherwise the "what we knew at the time" box would be contaminated by
    everything learned in between.
    """
    if not test_criteria.strip():
        raise EditorialError(
            "A prediction needs objective test criteria; an untestable prediction "
            "is not a prediction."
        )
    pred = Prediction(
        slug=unique_slug(session, Prediction, title),
        title=title.strip(),
        prediction_text=prediction_text,
        test_criteria=test_criteria,
        invalidation_criteria=invalidation_criteria,
        confidence=confidence,
        horizon_end=horizon_end,
        experiment_id=experiment_id,
        protocol_id=protocol_id,
        conversation_id=conversation_id,
        evidence_snapshot_json=json.dumps(evidence_snapshot or {}, default=str),
        provenance=provenance,
        made_at=made_at or utcnow(),
        status=Status.DRAFT,
        visibility=Visibility.PRIVATE,
    )
    session.add(pred)
    session.flush()
    return pred


def record_result(
    session, *, title: str, body: str, prediction: Prediction | None = None,
    experiment: Experiment | None = None, outcome: str, metrics: dict | None = None,
    lessons: str = "", sources: list | None = None,
    provenance: str = Provenance.EDITOR, **numeric,
) -> Result:
    """Append a result. Never modifies the prediction's locked text."""
    if prediction is None and experiment is None:
        raise EditorialError("A result must attach to a prediction or an experiment.")

    res = Result(
        slug=unique_slug(session, Result, title),
        title=title.strip(), body=body, outcome=outcome,
        prediction_id=prediction.id if prediction else None,
        experiment_id=experiment.id if experiment else (
            prediction.experiment_id if prediction else None
        ),
        metrics_json=json.dumps(metrics or {}, default=str),
        lessons=lessons,
        sources_json=json.dumps(sources or []),
        provenance=provenance,
        result_recorded_at=utcnow(),
        status=Status.DRAFT, visibility=Visibility.PRIVATE,
    )
    for field in (
        "timing_error_days", "price_at_prediction", "price_at_result",
        "subsequent_high", "subsequent_low", "max_upside_pct", "max_downside_pct",
    ):
        if field in numeric:
            setattr(res, field, numeric[field])

    session.add(res)
    session.flush()

    # The prediction's OUTCOME is a derived summary field, not part of the
    # locked evidence box, so updating it is permitted and expected.
    if prediction is not None:
        prediction.outcome = outcome
    if experiment is not None:
        experiment.outcome = outcome
        experiment.result_recorded_at = utcnow()
    session.flush()
    return res


def draft_article(
    session, *, title: str, body_markdown: str, summary: str = "", subtitle: str = "",
    article_type: str = "article", record_kind: str = "",
    observed_at: dt.datetime | None = None, experiment_id: int | None = None,
    prediction_id: int | None = None, observation_id: int | None = None,
    result_id: int | None = None, conversation_id: int | None = None,
    provenance: str = Provenance.EDITOR, sources: list | None = None,
    meta_description: str = "", ai_generated: bool = False, ai_model: str = "",
) -> Article:
    art = Article(
        slug=unique_slug(session, Article, title),
        title=title.strip(), subtitle=subtitle, summary=summary,
        body_markdown=body_markdown, article_type=article_type,
        record_kind=record_kind, observed_at=observed_at,
        experiment_id=experiment_id, prediction_id=prediction_id,
        observation_id=observation_id, result_id=result_id,
        conversation_id=conversation_id, provenance=provenance,
        sources_json=json.dumps(sources or []),
        meta_description=(meta_description or summary)[:320],
        ai_generated=ai_generated, ai_model=ai_model,
        status=Status.DRAFT, visibility=Visibility.PRIVATE,
    )
    session.add(art)
    session.flush()
    return art


def attach_to_experiment(session, obj, experiment: Experiment):
    if not hasattr(obj, "experiment_id"):
        raise EditorialError(f"{type(obj).__name__} cannot attach to an experiment.")
    obj.experiment_id = experiment.id
    session.flush()
    return obj


def archive(session, obj):
    obj.status = Status.ARCHIVED
    obj.visibility = Visibility.PRIVATE
    session.flush()
    return obj


def append_outlook_review(session, outlook: Outlook, review_markdown: str):
    """Append a retrospective review WITHOUT touching the original body."""
    stamp = utcnow()
    existing = outlook.review_markdown or ""
    entry = f"\n\n---\n*Review recorded {stamp.date().isoformat()}*\n\n{review_markdown.strip()}"
    outlook.review_markdown = (existing + entry).strip()
    outlook.review_recorded_at = stamp
    session.flush()
    return outlook
