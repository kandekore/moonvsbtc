"""News ingestion: classification, dedupe, scoring and copyright discipline."""
from __future__ import annotations

import datetime as dt

import pytest

from btcmoon.models import NewsCategory as C
from btcmoon.models import NewsItem, Source
from btcmoon.news.ingest import (
    canonicalise_url, classify, fingerprint, normalise_title, relevance_score,
    top_stories,
)


@pytest.mark.parametrize("headline,expected", [
    ("Fed holds rates steady as Powell signals a December cut", C.MACRO_FED),
    ("CPI comes in hotter than expected", C.MACRO_FED),
    ("SEC sues major exchange over unregistered securities", C.REGULATION),
    ("BlackRock spot Bitcoin ETF sees record inflow", C.ETF_INSTITUTIONAL),
    ("$1.2B in liquidations as open interest unwinds", C.LIQUIDATIONS_DERIVATIVES),
    ("Bitcoin hashrate hits an all-time high as miners expand", C.ONCHAIN),
    ("Exchange halts withdrawals after a security breach", C.SECURITY_EXCHANGE),
    ("New tariffs announced amid escalating conflict", C.GEOPOLITICAL),
])
def test_classification(headline, expected):
    assert classify(headline) == expected


def test_unmatched_headline_falls_back_to_the_source_default():
    assert classify("A completely unrelated story", default=C.BITCOIN_SPECIFIC) == C.BITCOIN_SPECIFIC


def test_tracking_params_are_stripped():
    url = "https://www.CoinDesk.com/markets/story/?utm_source=twitter&id=5&fbclid=x#top"
    assert canonicalise_url(url) == "https://www.coindesk.com/markets/story?id=5"


def test_syndicated_duplicates_share_a_fingerprint():
    a = fingerprint("Fed holds rates steady - CoinDesk", "https://coindesk.com/a")
    b = fingerprint("Fed holds rates steady | Reuters", "https://reuters.com/b")
    assert a == b


def test_different_stories_do_not_collide():
    a = fingerprint("Fed holds rates steady", "https://x.com/1")
    b = fingerprint("Fed cuts rates by 50bp", "https://x.com/2")
    assert a != b


def test_title_normalisation_removes_publisher_suffix():
    assert normalise_title("Bitcoin rallies — The Block") == "bitcoin rallies"


def test_clickbait_price_targets_are_demoted():
    clickbait = "Bitcoin price prediction: BTC could hit $1 million by Friday"
    real = "SEC approves spot Bitcoin ETF options trading"
    assert relevance_score(clickbait, "", classify(clickbait)) < \
           relevance_score(real, "", classify(real))


def test_macro_and_regulation_score_above_generic_crypto_news():
    macro = relevance_score("Fed cuts rates, Bitcoin rallies", "", C.MACRO_FED)
    generic = relevance_score("A new Bitcoin wallet launches", "", C.OTHER)
    assert macro > generic


def test_authoritative_sources_are_weighted_up():
    plain = relevance_score("Federal Reserve issues FOMC statement", "", C.MACRO_FED, 1.0)
    primary = relevance_score("Federal Reserve issues FOMC statement", "", C.MACRO_FED, 1.6)
    assert primary > plain


def test_scores_stay_within_bounds():
    for weight in (0.5, 1.0, 2.0):
        s = relevance_score("Bitcoin ETF FOMC CPI liquidations hack halving record high",
                            "", C.MACRO_FED, weight)
        assert 0.0 <= s <= 100.0


def test_default_sources_include_primary_regulators():
    from btcmoon.news.feeds import DEFAULT_SOURCES

    authoritative = {s["slug"] for s in DEFAULT_SOURCES if s.get("is_authoritative")}
    assert {"federalreserve-press", "sec-press"} <= authoritative


def test_summaries_are_truncated_not_republished():
    """We store a short excerpt and a link, never a full copyrighted article."""
    from btcmoon.news.ingest import _clean_summary

    long_article = "Lorem ipsum dolor sit amet. " * 200
    summary = _clean_summary(long_article)
    assert len(summary) <= 401
    assert summary.endswith("…")


def test_html_is_stripped_from_summaries():
    from btcmoon.news.ingest import _clean_summary

    assert "<script>" not in _clean_summary("<p>Text</p><script>alert(1)</script>")


def test_top_stories_respects_the_relevance_floor(db_session):
    src = Source(slug=f"t-{dt.datetime.now().timestamp()}", name="Test wire")
    db_session.add(src)
    db_session.flush()

    now = dt.datetime.now()
    db_session.add_all([
        NewsItem(source_id=src.id, headline="Important", fingerprint=f"fp-hi-{now.timestamp()}",
                 relevance_score=85.0, retrieved_at=now, publisher="Test wire"),
        NewsItem(source_id=src.id, headline="Trivial", fingerprint=f"fp-lo-{now.timestamp()}",
                 relevance_score=5.0, retrieved_at=now, publisher="Test wire"),
    ])
    db_session.flush()

    heads = {n.headline for n in top_stories(db_session, limit=5, min_score=40.0)}
    assert "Important" in heads
    assert "Trivial" not in heads


def test_hidden_items_never_surface(db_session):
    src = Source(slug=f"h-{dt.datetime.now().timestamp()}", name="Wire")
    db_session.add(src)
    db_session.flush()
    db_session.add(NewsItem(
        source_id=src.id, headline="Editorially hidden", relevance_score=99.0,
        fingerprint=f"fp-hidden-{dt.datetime.now().timestamp()}",
        retrieved_at=dt.datetime.now(), is_hidden=True, publisher="Wire",
    ))
    db_session.flush()
    assert "Editorially hidden" not in {n.headline for n in top_stories(db_session)}


def test_homepage_shows_only_a_handful(db_session):
    """Spec s13: only 3-5 genuinely important developments appear prominently."""
    src = Source(slug=f"m-{dt.datetime.now().timestamp()}", name="Wire")
    db_session.add(src)
    db_session.flush()
    now = dt.datetime.now()
    for i in range(20):
        db_session.add(NewsItem(
            source_id=src.id, headline=f"Story {i}", relevance_score=90.0,
            fingerprint=f"fp-many-{i}-{now.timestamp()}", retrieved_at=now,
            publisher="Wire",
        ))
    db_session.flush()
    assert len(top_stories(db_session, limit=5)) == 5
