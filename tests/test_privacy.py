"""Privacy boundary tests (spec s3, s20 - non-negotiable).

Private Companion conversations and trading information must never reach a
public page or a public serializer.
"""
from __future__ import annotations

import datetime as dt

import pytest

from btcmoon.editorial.serializers import (
    FORBIDDEN_PUBLIC_FIELDS, PrivateDataLeak, assert_public, is_publicly_visible,
    public_article, public_observation, public_prediction,
)
from btcmoon.models import (
    Article, Conversation, Message, Observation, Prediction, Provenance, Status,
    User, Visibility, utcnow,
)


def test_conversation_has_no_public_serializer(db_session):
    convo = Conversation(user_id=1, title="Long BTC 3x from 74k, stop 71.2k")
    with pytest.raises(PrivateDataLeak, match="private laboratory material"):
        assert_public(convo)


def test_message_has_no_public_serializer(db_session):
    msg = Message(conversation_id=1, role="user",
                  content="Opened 0.5 BTC at 76,100 with 5x leverage, stop 71,200.")
    with pytest.raises(PrivateDataLeak, match="private laboratory material"):
        assert_public(msg)


def test_conversations_and_messages_default_to_private(db_session):
    """The default must be private. A new thread is never public by omission."""
    user = User(email=f"priv-{utcnow().timestamp()}@example.com", role="admin")
    user.set_password("a-very-long-password")
    db_session.add(user)
    db_session.flush()

    convo = Conversation(user_id=user.id)
    db_session.add(convo)
    db_session.flush()
    assert convo.visibility == Visibility.PRIVATE

    msg = Message(conversation_id=convo.id, role="assistant", content="x")
    db_session.add(msg)
    db_session.flush()
    assert msg.visibility == Visibility.PRIVATE


def test_draft_records_are_never_publicly_serialized(db_session):
    art = Article(slug="draft-piece", title="A draft", status=Status.DRAFT,
                  visibility=Visibility.PRIVATE)
    with pytest.raises(PrivateDataLeak, match="only published records"):
        public_article(art)
    assert is_publicly_visible(art) is False


def test_published_but_private_record_is_refused(db_session):
    """Both flags must agree. A mis-set visibility is caught, not trusted."""
    art = Article(slug="mixed", title="Mixed flags", status=Status.PUBLISHED,
                  visibility=Visibility.PRIVATE, published_at=utcnow())
    with pytest.raises(PrivateDataLeak, match="only public records"):
        public_article(art)


def test_public_article_payload_carries_no_private_fields(db_session):
    art = Article(
        slug="ok", title="Fine", status=Status.PUBLISHED,
        visibility=Visibility.PUBLIC, published_at=utcnow(),
        conversation_id=42,          # origin thread - must NOT be emitted
    )
    payload = public_article(art)
    assert not (FORBIDDEN_PUBLIC_FIELDS & payload.keys())
    assert "conversation_id" not in payload


def test_prediction_payload_excludes_origin_conversation(db_session):
    pred = Prediction(
        slug="p1", title="P", prediction_text="text", test_criteria="criteria",
        status=Status.PUBLISHED, visibility=Visibility.PUBLIC,
        published_at=utcnow(), conversation_id=7,
    )
    payload = public_prediction(pred, include_results=False)
    assert "conversation_id" not in payload
    assert not (FORBIDDEN_PUBLIC_FIELDS & payload.keys())


def test_private_observation_not_leaked_by_list_helper(db_session):
    obs = Observation(slug="o1", title="Private note", observed_at=utcnow(),
                      status=Status.DRAFT, visibility=Visibility.PRIVATE)
    assert is_publicly_visible(obs) is False
    with pytest.raises(PrivateDataLeak):
        public_observation(obs)


def test_public_queries_exclude_unpublished(db_session):
    from btcmoon.web import queries as q

    db_session.add_all([
        Article(slug="pub-1", title="Published", status=Status.PUBLISHED,
                visibility=Visibility.PUBLIC, published_at=utcnow()),
        Article(slug="draft-1", title="Draft", status=Status.DRAFT,
                visibility=Visibility.PRIVATE),
        Article(slug="review-1", title="In review", status=Status.REVIEW,
                visibility=Visibility.PRIVATE),
    ])
    db_session.flush()
    slugs = {a.slug for a in q.published_articles(db_session)}
    assert "pub-1" in slugs
    assert "draft-1" not in slugs
    assert "review-1" not in slugs
    assert q.article_by_slug(db_session, "draft-1") is None


def test_password_hash_never_public():
    user = User(email="a@b.com")
    user.set_password("a-very-long-password")
    assert user.password_hash and user.password_hash != "a-very-long-password"
    assert "password_hash" in FORBIDDEN_PUBLIC_FIELDS
