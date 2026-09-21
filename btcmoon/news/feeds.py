"""Default RSS/Atom sources.

News is CONTEXT for the experiment, not the site's identity (spec s13). Primary
and authoritative sources are marked so factual macro/regulatory claims can
prefer them over aggregators.
"""
from __future__ import annotations

from ..models import NewsCategory as C

DEFAULT_SOURCES = [
    # --- primary / authoritative -----------------------------------------
    {
        "slug": "federalreserve-press",
        "name": "Federal Reserve Board - Press Releases",
        "homepage": "https://www.federalreserve.gov",
        "feed_url": "https://www.federalreserve.gov/feeds/press_all.xml",
        "default_category": C.MACRO_FED,
        "is_authoritative": True,
        "weight": 1.6,
    },
    {
        "slug": "sec-press",
        "name": "U.S. SEC - Press Releases",
        "homepage": "https://www.sec.gov",
        "feed_url": "https://www.sec.gov/news/pressreleases.rss",
        "default_category": C.REGULATION,
        "is_authoritative": True,
        "weight": 1.6,
    },
    {
        "slug": "cftc-press",
        "name": "CFTC - Press Releases",
        "homepage": "https://www.cftc.gov",
        "feed_url": "https://www.cftc.gov/RSS/RSSGP/rssgp.xml",
        "default_category": C.REGULATION,
        "is_authoritative": True,
        "weight": 1.5,
    },
    {
        "slug": "bls-news",
        "name": "U.S. Bureau of Labor Statistics",
        "homepage": "https://www.bls.gov",
        "feed_url": "https://www.bls.gov/feed/bls_latest.rss",
        "default_category": C.MACRO_FED,
        "is_authoritative": True,
        "weight": 1.5,
    },
    # --- crypto trade press ----------------------------------------------
    {
        "slug": "coindesk",
        "name": "CoinDesk",
        "homepage": "https://www.coindesk.com",
        "feed_url": "https://www.coindesk.com/arc/outboundfeeds/rss/",
        "default_category": C.BITCOIN_SPECIFIC,
        "weight": 1.1,
    },
    {
        "slug": "cointelegraph",
        "name": "Cointelegraph",
        "homepage": "https://cointelegraph.com",
        "feed_url": "https://cointelegraph.com/rss",
        "default_category": C.BITCOIN_SPECIFIC,
        "weight": 0.9,
    },
    {
        "slug": "theblock",
        "name": "The Block",
        "homepage": "https://www.theblock.co",
        "feed_url": "https://www.theblock.co/rss.xml",
        "default_category": C.BITCOIN_SPECIFIC,
        "weight": 1.1,
    },
    {
        "slug": "bitcoinmagazine",
        "name": "Bitcoin Magazine",
        "homepage": "https://bitcoinmagazine.com",
        "feed_url": "https://bitcoinmagazine.com/feed",
        "default_category": C.BITCOIN_SPECIFIC,
        "weight": 0.9,
    },
    {
        "slug": "decrypt",
        "name": "Decrypt",
        "homepage": "https://decrypt.co",
        "feed_url": "https://decrypt.co/feed",
        "default_category": C.BITCOIN_SPECIFIC,
        "weight": 0.8,
    },
]


def seed_sources(session) -> int:
    """Insert any missing default sources. Existing rows are left alone."""
    from ..models import Source

    added = 0
    for spec in DEFAULT_SOURCES:
        if session.query(Source).filter_by(slug=spec["slug"]).one_or_none():
            continue
        session.add(Source(source_type="rss", is_enabled=True, **spec))
        added += 1
    session.flush()
    return added
