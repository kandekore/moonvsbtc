"""Jinja filters and helpers."""
from __future__ import annotations

import datetime as dt

import bleach
import markdown as md

#: Markdown is authored by the Editor (or AI output the Editor approved), but we
#: still sanitise: AI output is never trusted into the DOM unescaped.
ALLOWED_TAGS = [
    "p", "br", "hr", "h1", "h2", "h3", "h4", "h5", "h6",
    "strong", "em", "b", "i", "u", "s", "code", "pre", "blockquote",
    "ul", "ol", "li", "a", "img", "table", "thead", "tbody", "tr", "th", "td",
    "sup", "sub", "span", "div", "figure", "figcaption",
]
ALLOWED_ATTRS = {
    "a": ["href", "title", "rel", "target"],
    "img": ["src", "alt", "title", "width", "height", "loading"],
    "span": ["class"], "div": ["class"], "code": ["class"],
    "th": ["align"], "td": ["align"],
}

RECORD_LABELS = {
    "observation": "OBSERVATION",
    "hypothesis": "HYPOTHESIS",
    "prediction": "PREDICTION",
    "result": "RESULT",
    "research_update": "RESEARCH UPDATE",
    "experimental": "EXPERIMENTAL",
}

OUTCOME_LABELS = {
    "consistent": "Consistent",
    "partially_consistent": "Partially consistent",
    "inconsistent": "Inconsistent",
    "invalidated": "Invalidated",
    "inconclusive": "Inconclusive",
    "pending": "Pending",
}


def render_markdown(text: str) -> str:
    if not text:
        return ""
    html = md.markdown(
        text, extensions=["extra", "sane_lists", "tables", "nl2br", "toc"]
    )
    cleaned = bleach.clean(html, tags=ALLOWED_TAGS, attributes=ALLOWED_ATTRS, strip=True)
    return bleach.linkify(cleaned, callbacks=[_external_link])


def _external_link(attrs, new=False):
    href = attrs.get((None, "href"), "")
    if href.startswith("http"):
        attrs[(None, "rel")] = "noopener noreferrer nofollow"
        attrs[(None, "target")] = "_blank"
    return attrs


def money(value, places: int = 0) -> str:
    if value is None:
        return "—"
    try:
        return f"${float(value):,.{places}f}"
    except (TypeError, ValueError):
        return "—"


def pct(value, places: int = 2, signed: bool = True) -> str:
    if value is None:
        return "—"
    try:
        v = float(value)
    except (TypeError, ValueError):
        return "—"
    return f"{v:+.{places}f}%" if signed else f"{v:.{places}f}%"


def days(value, places: int = 1) -> str:
    if value is None:
        return "—"
    try:
        return f"{float(value):+.{places}f} d"
    except (TypeError, ValueError):
        return "—"


def datefmt(value, fmt: str = "%d %B %Y") -> str:
    if value is None:
        return "—"
    if isinstance(value, str):
        try:
            value = dt.datetime.fromisoformat(value)
        except ValueError:
            return value
    return value.strftime(fmt)


def datetimefmt(value, fmt: str = "%d %B %Y, %H:%M UTC") -> str:
    return datefmt(value, fmt)


def record_label(kind: str) -> str:
    return RECORD_LABELS.get((kind or "").lower(), (kind or "").upper())


def outcome_label(outcome: str) -> str:
    return OUTCOME_LABELS.get((outcome or "").lower(), (outcome or "").title())


def register_filters(app) -> None:
    app.jinja_env.filters["markdown"] = render_markdown
    app.jinja_env.filters["money"] = money
    app.jinja_env.filters["pct"] = pct
    app.jinja_env.filters["days"] = days
    app.jinja_env.filters["datefmt"] = datefmt
    app.jinja_env.filters["datetimefmt"] = datetimefmt
    app.jinja_env.filters["record_label"] = record_label
    app.jinja_env.filters["outcome_label"] = outcome_label
