"""sitemap.xml, robots.txt and structured data.

Only genuinely published pages enter the sitemap - no thin SEO spam (spec s15).
"""
from __future__ import annotations

import datetime as dt
import json

from flask import Blueprint, Response, url_for

from ..config import Config
from ..db import Session
from . import queries as q

bp = Blueprint("seo", __name__)


def _abs(endpoint: str, **values) -> str:
    return Config.SITE_URL + url_for(endpoint, **values)


@bp.route("/sitemap.xml")
def sitemap():
    s = Session
    urls: list[tuple[str, dt.date | None, str, str]] = [
        (_abs("public.home"), dt.date.today(), "daily", "1.0"),
        (_abs("public.experiments"), dt.date.today(), "daily", "0.9"),
        (_abs("public.predictions"), dt.date.today(), "daily", "0.9"),
        (_abs("public.natal"), None, "monthly", "0.8"),
        (_abs("public.outlooks"), dt.date.today(), "daily", "0.8"),
        (_abs("public.methodology"), None, "monthly", "0.8"),
        (_abs("public.observations"), dt.date.today(), "weekly", "0.7"),
        (_abs("public.research"), dt.date.today(), "daily", "0.7"),
        (_abs("public.transits"), dt.date.today(), "weekly", "0.6"),
        (_abs("public.news"), dt.date.today(), "hourly", "0.5"),
        (_abs("public.about"), None, "yearly", "0.4"),
    ]

    def add(items, endpoint, date_attr, freq, prio):
        for item in items:
            when = getattr(item, date_attr, None)
            when = when.date() if isinstance(when, dt.datetime) else when
            urls.append((_abs(endpoint, slug=item.slug), when, freq, prio))

    add(q.published_articles(s), "public.article", "published_at", "monthly", "0.7")
    add(q.published_predictions(s), "public.prediction", "published_at", "weekly", "0.8")
    add(q.published_results(s), "public.result", "published_at", "monthly", "0.7")
    add(q.published_observations(s), "public.observation", "published_at", "monthly", "0.6")
    add(q.published_experiments(s), "public.experiment", "published_at", "weekly", "0.8")
    add(q.published_outlooks(s), "public.outlook", "period_start", "weekly", "0.6")

    body = ['<?xml version="1.0" encoding="UTF-8"?>',
            '<urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">']
    for loc, when, freq, prio in urls:
        body.append("  <url>")
        body.append(f"    <loc>{loc}</loc>")
        if when:
            body.append(f"    <lastmod>{when.isoformat()}</lastmod>")
        body.append(f"    <changefreq>{freq}</changefreq>")
        body.append(f"    <priority>{prio}</priority>")
        body.append("  </url>")
    body.append("</urlset>")
    return Response("\n".join(body), mimetype="application/xml")


@bp.route("/robots.txt")
def robots():
    lines = [
        "User-agent: *",
        "Allow: /",
        "",
        "# Private research laboratory and account pages - never indexed.",
        "Disallow: /admin/",
        "Disallow: /account/",
    ]
    if Config.EXPLORER_URL.startswith("/"):
        # The explorer recomputes the whole analysis per request. It is linked
        # from the nav for humans, but a crawler working through it would cost
        # far more than it is worth, and it has no indexable content.
        lines += [
            "",
            "# Interactive tool - recomputed per request, nothing to index.",
            f"Disallow: {Config.EXPLORER_URL}",
        ]
    lines += [
        "",
        f"Sitemap: {Config.SITE_URL}/sitemap.xml",
        "",
    ]
    return Response("\n".join(lines), mimetype="text/plain")


# ---------------------------------------------------------------------------
# JSON-LD builders, used by the templates
# ---------------------------------------------------------------------------
def article_schema(article) -> str:
    data = {
        "@context": "https://schema.org",
        "@type": "Article",
        "headline": article.title,
        "description": article.meta_description or article.summary,
        "datePublished": article.published_at.isoformat() if article.published_at else None,
        "dateModified": article.updated_at.isoformat() if article.updated_at else None,
        "author": {"@type": "Person", "name": Config.EDITOR_NAME},
        "publisher": {"@type": "Organization", "name": Config.SITE_NAME},
        "mainEntityOfPage": Config.SITE_URL + url_for("public.article", slug=article.slug),
        "isAccessibleForFree": True,
    }
    return json.dumps({k: v for k, v in data.items() if v is not None}, indent=2)


def claim_review_schema(prediction) -> str:
    """A published prediction is a dated, falsifiable claim."""
    data = {
        "@context": "https://schema.org",
        "@type": "Claim",
        "text": prediction.prediction_text,
        "datePublished": prediction.published_at.isoformat() if prediction.published_at else None,
        "author": {"@type": "Person", "name": Config.EDITOR_NAME},
        "url": Config.SITE_URL + url_for("public.prediction", slug=prediction.slug),
    }
    return json.dumps({k: v for k, v in data.items() if v is not None}, indent=2)
