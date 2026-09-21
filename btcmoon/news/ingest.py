"""RSS ingestion: fetch -> dedupe -> rule-based classify/score -> MySQL.

Deliberately deterministic and free. No AI runs per item (spec s19): the
expensive model is reserved for scheduled briefs and editor-approved writing.
"""
from __future__ import annotations

import datetime as dt
import hashlib
import os
import re
import time
from dataclasses import dataclass, field
from urllib.parse import urlparse, urlunparse

from ..config import Config
from ..models import NewsCategory as C
from ..models import NewsItem, Source

#: keyword -> category. First match by weight order wins.
CATEGORY_KEYWORDS: list[tuple[str, tuple[str, ...]]] = [
    (C.MACRO_FED, (
        "fomc", "federal reserve", "fed chair", "powell", "rate cut", "rate hike",
        "interest rate", "cpi", "inflation", "pce", "nonfarm", "payroll", "jobs report",
        "gdp", "treasury yield", "quantitative", "dot plot", "jackson hole", "basis point",
    )),
    (C.REGULATION, (
        "sec ", "cftc", "regulator", "regulation", "lawsuit", "enforcement", "subpoena",
        "congress", "senate", "bill", "legislation", "mica", "compliance", "sanction",
        "court", "judge", "settlement", "fincen", "treasury department",
    )),
    (C.ETF_INSTITUTIONAL, (
        "etf", "spot bitcoin etf", "blackrock", "ishares", "fidelity", "grayscale",
        "institutional", "inflow", "outflow", "custody", "microstrategy", "strategy inc",
        "treasury company", "pension", "sovereign wealth", "allocation",
    )),
    (C.LIQUIDATIONS_DERIVATIVES, (
        "liquidat", "open interest", "funding rate", "futures", "perpetual", "options expiry",
        "options expiration", "leverage", "basis trade", "cme", "deribit", "gamma",
    )),
    (C.ONCHAIN, (
        "on-chain", "onchain", "hashrate", "hash rate", "mining difficulty", "miner",
        "halving", "utxo", "whale", "dormant", "exchange reserve", "mempool", "mvrv",
        "realized cap", "sopr",
    )),
    (C.SECURITY_EXCHANGE, (
        "hack", "exploit", "breach", "stolen", "outage", "insolven", "bankrupt",
        "withdrawal halt", "proof of reserves", "rug pull", "phishing",
    )),
    (C.GEOPOLITICAL, (
        "war", "conflict", "sanctions", "tariff", "election", "geopolit", "middle east",
        "ukraine", "taiwan", "opec", "central bank of",
    )),
    (C.TECHNICAL, (
        "resistance", "support level", "breakout", "head and shoulders", "cup and handle",
        "moving average", "death cross", "golden cross", "rsi", "chart pattern",
    )),
]

#: Terms that make an item relevant to THIS project at all.
BITCOIN_TERMS = ("bitcoin", "btc", "satoshi", "crypto", "digital asset")

#: High-impact terms that lift an item toward the homepage.
HIGH_IMPACT = (
    "fomc", "rate cut", "rate hike", "cpi", "etf approval", "spot bitcoin etf",
    "all-time high", "record high", "crash", "liquidat", "hack", "halving",
    "sec approves", "sec sues", "emergency", "bankrupt",
)

TRACKING_PARAMS = re.compile(r"^(utm_|fbclid|gclid|ref|source|mc_cid|mc_eid)", re.I)


def canonicalise_url(url: str) -> str:
    """Strip tracking params and fragments so syndicated copies collapse."""
    if not url:
        return ""
    try:
        p = urlparse(url.strip())
    except ValueError:
        return url.strip()
    query = "&".join(
        part for part in (p.query or "").split("&")
        if part and not TRACKING_PARAMS.match(part.split("=")[0])
    )
    return urlunparse((p.scheme.lower(), p.netloc.lower(), p.path.rstrip("/"), "", query, ""))


def normalise_title(title: str) -> str:
    """Lowercase, strip punctuation and publisher suffixes for fingerprinting."""
    t = (title or "").lower()
    t = re.sub(r"\s*[|\-–—]\s*[^|\-–—]{0,40}$", "", t)   # trailing " - Publisher"
    t = re.sub(r"[^a-z0-9 ]+", " ", t)
    return re.sub(r"\s+", " ", t).strip()


def fingerprint(title: str, url: str) -> str:
    """Stable dedupe key. Title-led, so the same story from two wires collapses."""
    basis = normalise_title(title) or canonicalise_url(url)
    return hashlib.sha1(basis.encode("utf-8")).hexdigest()


def classify(title: str, summary: str = "", default: str = C.OTHER) -> str:
    text = f"{title} {summary}".lower()
    for category, keywords in CATEGORY_KEYWORDS:
        if any(k in text for k in keywords):
            return category
    return default


def relevance_score(title: str, summary: str, category: str, source_weight: float = 1.0) -> float:
    """Cheap rule-based 0-100 relevance. No AI, no per-item cost."""
    text = f"{title} {summary}".lower()
    score = 10.0

    if any(t in text for t in BITCOIN_TERMS):
        score += 30.0
    if category in (C.MACRO_FED, C.REGULATION, C.ETF_INSTITUTIONAL):
        score += 20.0
    elif category in (C.LIQUIDATIONS_DERIVATIVES, C.ONCHAIN, C.SECURITY_EXCHANGE):
        score += 12.0
    elif category == C.OTHER:
        score -= 5.0

    hits = sum(1 for t in HIGH_IMPACT if t in text)
    score += min(25.0, hits * 12.0)

    if re.search(r"\bprice prediction\b|\bcould hit\b|\bmoon\b|\bto the moon\b", text):
        score -= 15.0        # clickbait price-target pieces are not evidence

    return round(max(0.0, min(100.0, score * source_weight)), 2)


def _parsed_time(entry) -> dt.datetime | None:
    for key in ("published_parsed", "updated_parsed"):
        val = getattr(entry, key, None) or (entry.get(key) if hasattr(entry, "get") else None)
        if val:
            try:
                return dt.datetime.fromtimestamp(time.mktime(val), dt.timezone.utc).replace(tzinfo=None)
            except (TypeError, ValueError, OverflowError):
                continue
    return None


def _clean_summary(raw: str, limit: int = 400) -> str:
    """Short plain-text excerpt. We never store a full copyrighted article."""
    import bleach

    text = bleach.clean(raw or "", tags=[], strip=True)
    text = re.sub(r"\s+", " ", text).strip()
    return text[:limit].rstrip() + ("…" if len(text) > limit else "")


@dataclass
class IngestReport:
    fetched: int = 0
    inserted: int = 0
    duplicates: int = 0
    errors: list[str] = field(default_factory=list)
    per_source: dict = field(default_factory=dict)

    def to_dict(self) -> dict:
        return {
            "fetched": self.fetched, "inserted": self.inserted,
            "duplicates": self.duplicates, "errors": self.errors,
            "per_source": self.per_source,
        }


#: Fetched with requests rather than feedparser's own urllib opener, so we get
#: certifi's CA bundle, a real timeout and redirect handling.
FETCH_TIMEOUT = int(os.getenv("NEWS_FETCH_TIMEOUT", "20"))


def fetch_feed_bytes(url: str) -> bytes:
    import requests

    resp = requests.get(
        url,
        timeout=FETCH_TIMEOUT,
        headers={
            "User-Agent": Config.NEWS_USER_AGENT,
            "Accept": (
                "application/rss+xml, application/atom+xml, "
                "application/xml;q=0.9, text/xml;q=0.9, */*;q=0.8"
            ),
        },
    )
    resp.raise_for_status()
    return resp.content


def ingest_source(session, source: Source, max_items: int | None = None) -> tuple[int, int]:
    """Fetch one feed. Returns (inserted, duplicates)."""
    import feedparser

    max_items = max_items or Config.NEWS_MAX_ITEMS_PER_FEED
    parsed = feedparser.parse(fetch_feed_bytes(source.feed_url))
    if getattr(parsed, "bozo", 0) and not parsed.entries:
        raise RuntimeError(str(getattr(parsed, "bozo_exception", "feed parse failed")))

    inserted = duplicates = 0
    for entry in parsed.entries[:max_items]:
        title = (entry.get("title") or "").strip()
        link = canonicalise_url(entry.get("link") or "")
        if not title:
            continue
        fp = fingerprint(title, link)
        if session.query(NewsItem.id).filter_by(fingerprint=fp).first():
            duplicates += 1
            continue

        summary = _clean_summary(entry.get("summary") or entry.get("description") or "")
        category = classify(title, summary, source.default_category)
        session.add(
            NewsItem(
                source_id=source.id,
                headline=title[:500],
                canonical_url=link[:700],
                publisher=source.name,
                source_published_at=_parsed_time(entry),
                category=category,
                summary=summary,
                relevance_score=relevance_score(title, summary, category, source.weight),
                fingerprint=fp,
            )
        )
        inserted += 1

    source.last_fetched_at = dt.datetime.now(dt.timezone.utc).replace(tzinfo=None)
    source.last_error = ""
    session.flush()
    return inserted, duplicates


def ingest_all(session, only_enabled: bool = True) -> IngestReport:
    """Ingest every configured feed. One bad feed never stops the rest."""
    report = IngestReport()
    q = session.query(Source).filter(Source.source_type == "rss")
    if only_enabled:
        q = q.filter(Source.is_enabled.is_(True))

    for source in q.all():
        report.fetched += 1
        try:
            ins, dup = ingest_source(session, source)
            report.inserted += ins
            report.duplicates += dup
            report.per_source[source.slug] = {"inserted": ins, "duplicates": dup}
            session.commit()
        except Exception as exc:
            session.rollback()
            msg = f"{source.slug}: {type(exc).__name__}: {exc}"
            report.errors.append(msg)
            report.per_source[source.slug] = {"error": str(exc)}
            source.last_error = msg[:2000]
            session.commit()
    return report


def top_stories(session, limit: int = 5, hours: int = 48, min_score: float = 40.0):
    """The 3-5 genuinely important developments for the homepage (spec s13)."""
    since = dt.datetime.now(dt.timezone.utc).replace(tzinfo=None) - dt.timedelta(hours=hours)
    return (
        session.query(NewsItem)
        .filter(
            NewsItem.is_hidden.is_(False),
            NewsItem.retrieved_at >= since,
            NewsItem.relevance_score >= min_score,
        )
        .order_by(NewsItem.is_featured.desc(), NewsItem.relevance_score.desc(),
                  NewsItem.source_published_at.desc())
        .limit(limit)
        .all()
    )
