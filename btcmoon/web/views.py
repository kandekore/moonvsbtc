"""Public, server-rendered, crawlable pages.

Navigation (spec s15): Home, Experiment, Observations, Predictions & Results,
BTC Natal Chart, Outlooks, Research/Methodology, Important BTC News, About.
"""
from __future__ import annotations

import datetime as dt
import json

from flask import Blueprint, abort, render_template, request

from ..astrology import NATAL_CHART_ASSUMPTIONS, natal_chart, transit_calendar
from ..auth.decorators import entitlement_required
from ..db import Session
from ..models import (
    ArticleType, NewsCategory, NewsItem, OutlookKind, ResearchProtocol, Result,
    Status, Visibility,
)
from ..news import top_stories
from ..research import SEPTEMBER_2026_PROTOCOL, WEBSITE_METHODOLOGY
from . import context as live
from . import queries as q
from .seo import article_schema, claim_review_schema

bp = Blueprint("public", __name__)

PAGE_SIZE = 12


def _loads(raw, default):
    try:
        return json.loads(raw) if raw else default
    except (json.JSONDecodeError, TypeError):
        return default


def _pretty_json(raw):
    data = _loads(raw, None)
    return json.dumps(data, indent=2, default=str) if data else ""


@bp.route("/")
def home():
    """Homepage order is specified (spec s15) and deliberate: the experiment
    leads, news is last and small."""
    s = Session
    pred, res = q.latest_prediction_or_result(s)
    return render_template(
        "public/home.html",
        title=None,
        btc=live.btc_now(),
        moon=live.moon_now(),
        experiment=q.current_experiment(s),
        tomorrow_outlook=q.next_daily_outlook(s),
        today_outlook=q.todays_daily_outlook(s),
        latest_prediction=pred,
        latest_result=res,
        journal=q.research_journal(s, limit=6),
        news=top_stories(s, limit=5),
        benchmarks=SEPTEMBER_2026_PROTOCOL,
    )


# ---------------------------------------------------------------------------
# The experiment
# ---------------------------------------------------------------------------
@bp.route("/experiment/")
def experiments():
    s = Session
    return render_template(
        "public/experiments.html",
        title="The Experiment",
        meta_description=(
            "An ongoing public test of whether lunar cycles show any useful "
            "relationship with Bitcoin price behaviour - recorded before the "
            "event, reviewed afterwards, failures included."
        ),
        current=q.current_experiment(s),
        experiments=q.published_experiments(s),
        protocols=s.query(ResearchProtocol)
        .filter(ResearchProtocol.status == Status.PUBLISHED)
        .order_by(ResearchProtocol.created_at.desc()).all(),
    )


@bp.route("/experiment/<slug>/")
def experiment(slug):
    exp = q.experiment_by_slug(Session, slug)
    if not exp:
        abort(404)
    results = [r for r in exp.results if r.status == Status.PUBLISHED
               and r.visibility == Visibility.PUBLIC]
    preds = [p for p in exp.predictions if p.status == Status.PUBLISHED
             and p.visibility == Visibility.PUBLIC]
    return render_template(
        "public/experiment.html", title=exp.title, experiment=exp,
        results=results, predictions=preds,
        meta_description=(exp.summary or exp.title)[:300],
    )


# ---------------------------------------------------------------------------
# Observations / predictions / results
# ---------------------------------------------------------------------------
@bp.route("/observations/")
def observations():
    return render_template(
        "public/observations.html", title="Observations",
        meta_description="Recorded observations from the Bitcoin vs The Moon experiment.",
        observations=q.published_observations(Session),
    )


@bp.route("/observations/<slug>/")
def observation(slug):
    obs = q.observation_by_slug(Session, slug)
    if not obs:
        abort(404)
    return render_template(
        "public/observation.html", title=obs.title, observation=obs,
        meta_description=(obs.body or obs.title)[:300],
    )


@bp.route("/predictions/")
def predictions():
    s = Session
    return render_template(
        "public/predictions.html", title="Predictions & Results",
        meta_description=(
            "Every prediction made by the Bitcoin vs The Moon experiment, locked "
            "at publication, with results appended afterwards - including the misses."
        ),
        predictions=q.published_predictions(s),
        results=q.published_results(s, limit=20),
    )


@bp.route("/predictions/<slug>/")
def prediction(slug):
    pred = q.prediction_by_slug(Session, slug)
    if not pred:
        abort(404)
    results = [r for r in pred.results
               if r.status == Status.PUBLISHED and r.visibility == Visibility.PUBLIC]
    return render_template(
        "public/prediction.html", title=pred.title, prediction=pred, results=results,
        evidence=_pretty_json(pred.evidence_snapshot_json),
        schema=claim_review_schema(pred),
        og_type="article",
        meta_description=(pred.prediction_text or pred.title)[:300],
    )


@bp.route("/results/<slug>/")
def result(slug):
    res = (
        Session.query(Result)
        .filter(Result.slug == slug, Result.status == Status.PUBLISHED,
                Result.visibility == Visibility.PUBLIC)
        .one_or_none()
    )
    if not res:
        abort(404)
    return render_template(
        "public/result.html", title=res.title, result=res,
        meta_description=(res.body or res.title)[:300],
    )


# ---------------------------------------------------------------------------
# BTC natal chart + outlooks
# ---------------------------------------------------------------------------
@bp.route("/btc-natal-chart/")
def natal():
    chart = natal_chart()
    return render_template(
        "public/natal.html", title="Bitcoin's Natal Chart",
        meta_description=(
            "Bitcoin's natal chart, cast for the genesis block on 3 January 2009 - "
            "the chart assumptions, what is and is not calculated, and how this "
            "experimental layer is tested publicly."
        ),
        chart=chart, assumptions=NATAL_CHART_ASSUMPTIONS,
        transits=live.natal_now(),
        explainer=q.published_outlooks(Session, kind=OutlookKind.NATAL_EXPLAINED, limit=1),
    )


@bp.route("/transit-calendar/")
def transits():
    start = dt.date.today()
    return render_template(
        "public/transits.html", title="BTC Transit Calendar",
        meta_description="Upcoming transits to Bitcoin's natal chart over the next 30 days.",
        calendar=transit_calendar(start, days=30),
        start=start,
    )


@bp.route("/outlooks/")
def outlooks():
    s = Session
    return render_template(
        "public/outlooks.html", title="BTC Outlooks",
        meta_description=(
            "Daily, monthly and yearly Bitcoin outlooks combining natal-chart "
            "transits, lunar phase, technical structure and scheduled events."
        ),
        daily=q.published_outlooks(s, kind=OutlookKind.DAILY, limit=30),
        monthly=q.published_outlooks(s, kind=OutlookKind.MONTHLY, limit=12),
        yearly=q.published_outlooks(s, kind=OutlookKind.YEARLY, limit=5),
        tomorrow=q.next_daily_outlook(s),
    )


@bp.route("/outlooks/<slug>/")
@entitlement_required("outlooks")
def outlook(slug):
    o = q.outlook_by_slug(Session, slug)
    if not o:
        abort(404)
    return render_template(
        "public/outlook.html", title=o.title, outlook=o,
        lunar=_loads(o.lunar_context_json, {}),
        og_type="article",
        meta_description=(o.meta_description or o.summary or o.title)[:300],
    )


# ---------------------------------------------------------------------------
# Research journal / methodology / news / about
# ---------------------------------------------------------------------------
@bp.route("/research/")
def research():
    return render_template(
        "public/research.html", title="Research Journal",
        meta_description="Research updates, observations and results from the experiment.",
        journal=q.research_journal(Session, limit=50),
    )


@bp.route("/research/<slug>/")
def article(slug):
    art = q.article_by_slug(Session, slug)
    if not art:
        abort(404)
    return render_template(
        "public/article.html", title=art.title, article=art,
        sources=_loads(art.sources_json, []),
        schema=article_schema(art),
        og_type="article",
        meta_description=(art.meta_description or art.summary or art.title)[:300],
    )


@bp.route("/methodology/")
def methodology():
    s = Session
    return render_template(
        "public/methodology.html", title="Research & Methodology",
        meta_description=(
            "How Bitcoin vs The Moon measures lunar/price relationships: the exact "
            "pivot definitions, lag windows, scoring weights and the frozen "
            "protocols that stop the rules moving after the fact."
        ),
        methodology=WEBSITE_METHODOLOGY,
        protocols=s.query(ResearchProtocol)
        .filter(ResearchProtocol.status == Status.PUBLISHED)
        .order_by(ResearchProtocol.created_at.asc()).all(),
        papers=q.published_articles(s, article_type=ArticleType.METHODOLOGY),
    )


@bp.route("/news/")
def news():
    s = Session
    category = request.args.get("category") or None
    query = s.query(NewsItem).filter(NewsItem.is_hidden.is_(False))
    if category in NewsCategory.ALL:
        query = query.filter(NewsItem.category == category)
    items = (
        query.order_by(NewsItem.relevance_score.desc(),
                       NewsItem.source_published_at.desc())
        .limit(60).all()
    )
    return render_template(
        "public/news.html", title="Important Bitcoin News",
        meta_description=(
            "The Bitcoin and macro developments that matter to the experiment - "
            "linked and attributed, never republished."
        ),
        items=items, categories=NewsCategory, active_category=category,
    )


@bp.route("/about/")
def about():
    return render_template(
        "public/about.html", title="About",
        meta_description=(
            "Who runs Bitcoin vs The Moon, what it is testing, how the private "
            "research laboratory relates to the public record, and why nothing "
            "here is investment advice."
        ),
    )
