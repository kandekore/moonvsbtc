"""Immutable published predictions and frozen protocols (spec s10, s16, Appendix)."""
from __future__ import annotations

import datetime as dt

import pytest

from btcmoon.editorial import create_prediction, publish, record_result
from btcmoon.models import (
    ImmutableAfterPublishError, Outcome, Prediction, ResearchProtocol, Status,
    Visibility, utcnow,
)


@pytest.fixture()
def published_prediction(db_session):
    pred = create_prediction(
        db_session,
        title="BTC forms a local low in T0:T+3",
        prediction_text="A strict local low forms between 11 and 14 September.",
        test_criteria="Lowest daily close in the window, strictly lower than the guard window.",
        invalidation_criteria="No such low, or a lower low afterwards.",
        confidence="moderate",
        evidence_snapshot={"price": 77173.80, "moon": "new"},
        horizon_end=dt.datetime(2026, 9, 14, 23, 59),
    )
    publish(db_session, pred)
    db_session.flush()
    return pred


def test_publishing_locks_the_prediction(published_prediction):
    assert published_prediction.is_locked
    assert published_prediction.status == Status.PUBLISHED
    assert published_prediction.visibility == Visibility.PUBLIC
    assert published_prediction.published_at is not None


def test_prediction_text_cannot_be_rewritten(published_prediction):
    with pytest.raises(ImmutableAfterPublishError, match="immutable once published"):
        published_prediction.prediction_text = "Actually, I meant something else."


def test_test_criteria_cannot_be_moved(published_prediction):
    """The single most important rule: goalposts cannot move after the fact."""
    with pytest.raises(ImmutableAfterPublishError):
        published_prediction.test_criteria = "Any low at all, any time, counts."


def test_evidence_snapshot_cannot_be_edited(published_prediction):
    with pytest.raises(ImmutableAfterPublishError):
        published_prediction.evidence_snapshot_json = '{"price": 999999}'


def test_invalidation_criteria_and_horizon_are_locked(published_prediction):
    with pytest.raises(ImmutableAfterPublishError):
        published_prediction.invalidation_criteria = "Nothing invalidates it."
    with pytest.raises(ImmutableAfterPublishError):
        published_prediction.horizon_end = dt.datetime(2027, 1, 1)


def test_republishing_is_refused(published_prediction):
    with pytest.raises(ImmutableAfterPublishError, match="already published"):
        published_prediction.publish()


def test_outcome_is_a_derived_field_and_may_be_updated(published_prediction):
    """The outcome summary is not part of the locked evidence box."""
    published_prediction.outcome = Outcome.INCONSISTENT
    assert published_prediction.outcome == Outcome.INCONSISTENT


def test_corrections_are_appended_as_results(db_session, published_prediction):
    res = record_result(
        db_session,
        title="Result: the T0:T+3 low test failed",
        body="A lower close came at NM+4, outside the window.",
        prediction=published_prediction,
        outcome=Outcome.INCONSISTENT,
        timing_error_days=2.0,
    )
    db_session.flush()
    assert res.prediction_id == published_prediction.id
    assert published_prediction.outcome == Outcome.INCONSISTENT
    # The original text is untouched.
    assert "strict local low forms between 11 and 14 September" in published_prediction.prediction_text


def test_a_draft_prediction_is_still_editable(db_session):
    pred = create_prediction(
        db_session, title="Draft", prediction_text="original",
        test_criteria="some criteria",
    )
    pred.prediction_text = "revised before publication"
    assert pred.prediction_text == "revised before publication"


def test_prediction_requires_test_criteria(db_session):
    from btcmoon.editorial import EditorialError

    with pytest.raises(EditorialError, match="objective test criteria"):
        create_prediction(db_session, title="Vague", prediction_text="number go up",
                          test_criteria="   ")


# --- frozen protocols -----------------------------------------------------
def test_frozen_protocol_rules_cannot_be_edited(db_session):
    proto = ResearchProtocol(
        slug="p-test", version="1.0", title="Test protocol",
        rules_json='{"max_lag_days": 14}', summary="Summary",
    )
    db_session.add(proto)
    db_session.flush()
    proto.freeze()

    with pytest.raises(ImmutableAfterPublishError, match="frozen"):
        proto.rules_json = '{"max_lag_days": 30}'
    with pytest.raises(ImmutableAfterPublishError):
        proto.title = "Retitled after the fact"


def test_unfrozen_protocol_is_editable(db_session):
    proto = ResearchProtocol(slug="p-draft", version="0.1", title="Draft protocol",
                             rules_json="{}")
    db_session.add(proto)
    db_session.flush()
    proto.rules_json = '{"max_lag_days": 14}'
    assert proto.rules_json == '{"max_lag_days": 14}'


def test_seeded_september_protocol_is_frozen(db_session):
    from btcmoon.research.protocols import seed_protocols

    seed_protocols(db_session)
    proto = db_session.query(ResearchProtocol).filter_by(
        slug="september-2026-new-moon-test"
    ).one()
    assert proto.is_frozen
    with pytest.raises(ImmutableAfterPublishError):
        proto.rules_json = '{"primary_test": "whatever fits"}'
