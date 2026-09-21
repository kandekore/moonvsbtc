"""Read queries for the public site.

Every query here filters to PUBLISHED + PUBLIC at the database level, so a
template can never accidentally render a draft or a private record.
"""
from __future__ import annotations

import datetime as dt

from sqlalchemy import or_

from ..models import (
    Article, Experiment, ExperimentStatus, Observation, Outlook, OutlookKind,
    Prediction, Result, Status, Visibility,
)


def _public(query, model):
    return query.filter(model.status == Status.PUBLISHED,
                        model.visibility == Visibility.PUBLIC)


def published_articles(session, limit: int | None = None, article_type: str | None = None):
    q = _public(session.query(Article), Article)
    if article_type:
        q = q.filter(Article.article_type == article_type)
    q = q.order_by(Article.published_at.desc())
    return q.limit(limit).all() if limit else q.all()


def article_by_slug(session, slug: str):
    return _public(session.query(Article).filter(Article.slug == slug), Article).one_or_none()


def published_predictions(session, limit: int | None = None):
    q = _public(session.query(Prediction), Prediction).order_by(Prediction.published_at.desc())
    return q.limit(limit).all() if limit else q.all()


def prediction_by_slug(session, slug: str):
    return _public(
        session.query(Prediction).filter(Prediction.slug == slug), Prediction
    ).one_or_none()


def published_results(session, limit: int | None = None):
    q = _public(session.query(Result), Result).order_by(Result.published_at.desc())
    return q.limit(limit).all() if limit else q.all()


def published_observations(session, limit: int | None = None):
    q = _public(session.query(Observation), Observation).order_by(Observation.observed_at.desc())
    return q.limit(limit).all() if limit else q.all()


def observation_by_slug(session, slug: str):
    return _public(
        session.query(Observation).filter(Observation.slug == slug), Observation
    ).one_or_none()


def published_experiments(session, limit: int | None = None):
    q = _public(session.query(Experiment), Experiment).order_by(Experiment.observed_at.desc())
    return q.limit(limit).all() if limit else q.all()


def experiment_by_slug(session, slug: str):
    return _public(
        session.query(Experiment).filter(Experiment.slug == slug), Experiment
    ).one_or_none()


def current_experiment(session):
    """The experiment currently running, else the most recent published one."""
    active = _public(
        session.query(Experiment).filter(
            Experiment.experiment_status.in_(
                (ExperimentStatus.ACTIVE, ExperimentStatus.OBSERVING)
            )
        ),
        Experiment,
    ).order_by(Experiment.observed_at.desc()).first()
    return active or _public(session.query(Experiment), Experiment).order_by(
        Experiment.observed_at.desc()
    ).first()


def published_outlooks(session, kind: str | None = None, limit: int | None = None):
    q = _public(session.query(Outlook), Outlook)
    if kind:
        q = q.filter(Outlook.kind == kind)
    q = q.order_by(Outlook.period_start.desc())
    return q.limit(limit).all() if limit else q.all()


def outlook_by_slug(session, slug: str):
    return _public(session.query(Outlook).filter(Outlook.slug == slug), Outlook).one_or_none()


def next_daily_outlook(session, today: dt.date | None = None):
    """Tomorrow's daily outlook - the homepage's return-visit hook (spec s14)."""
    today = today or dt.date.today()
    return _public(
        session.query(Outlook).filter(
            Outlook.kind == OutlookKind.DAILY, Outlook.period_start > today
        ),
        Outlook,
    ).order_by(Outlook.period_start.asc()).first()


def todays_daily_outlook(session, today: dt.date | None = None):
    today = today or dt.date.today()
    return _public(
        session.query(Outlook).filter(
            Outlook.kind == OutlookKind.DAILY, Outlook.period_start == today
        ),
        Outlook,
    ).first()


def latest_prediction_or_result(session):
    pred = published_predictions(session, limit=1)
    res = published_results(session, limit=1)
    return (pred[0] if pred else None), (res[0] if res else None)


def research_journal(session, limit: int = 10):
    """Articles, observations and results interleaved, newest first."""
    entries = []
    for art in published_articles(session, limit=limit):
        entries.append({
            "kind": art.record_kind or "research_update", "type": "article",
            "title": art.title, "summary": art.summary,
            "url_slug": art.slug, "endpoint": "public.article",
            "published_at": art.published_at, "observed_at": art.observed_at,
            "provenance": art.provenance, "obj": art,
        })
    for obs in published_observations(session, limit=limit):
        entries.append({
            "kind": "observation", "type": "observation",
            "title": obs.title, "summary": (obs.body or "")[:240],
            "url_slug": obs.slug, "endpoint": "public.observation",
            "published_at": obs.published_at, "observed_at": obs.observed_at,
            "provenance": obs.provenance, "obj": obs,
        })
    for res in published_results(session, limit=limit):
        entries.append({
            "kind": "result", "type": "result",
            "title": res.title, "summary": (res.body or "")[:240],
            "url_slug": res.slug, "endpoint": "public.result",
            "published_at": res.published_at, "observed_at": res.recorded_at,
            "provenance": res.provenance, "obj": res,
        })
    entries.sort(key=lambda e: e["published_at"] or dt.datetime.min, reverse=True)
    return entries[:limit]
