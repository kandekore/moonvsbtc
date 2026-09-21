"""Scheduled jobs: idempotency, error capture and graceful AI degradation."""
from __future__ import annotations

import datetime as dt

import pytest

from btcmoon.models import BriefingKind, JobStatus, ScheduledJobRun, TriageLevel, Visibility
from jobs.base import JobSkipped, job_run, run_job


def test_job_records_a_successful_run(db_session):
    with job_run("test_job_ok", key_suffix="k1") as (session, run):
        run.detail = "did the thing"
    row = db_session.query(ScheduledJobRun).filter_by(
        idempotency_key="test_job_ok:k1"
    ).one()
    assert row.status == JobStatus.SUCCESS
    assert row.finished_at is not None
    assert row.duration_seconds is not None


def test_second_run_with_the_same_key_is_skipped(db_session):
    with job_run("test_job_idem", key_suffix="k2"):
        pass
    with pytest.raises(JobSkipped):
        with job_run("test_job_idem", key_suffix="k2"):
            pytest.fail("the job body must not run twice for one key")


def test_force_allows_a_rerun(db_session):
    with job_run("test_job_force", key_suffix="k3"):
        pass
    with job_run("test_job_force", key_suffix="k3", force=True) as (_s, run):
        run.detail = "second attempt"
    row = db_session.query(ScheduledJobRun).filter_by(
        idempotency_key="test_job_force:k3"
    ).one()
    assert row.attempt == 2
    assert row.status == JobStatus.SUCCESS


def test_failure_is_recorded_and_reraised(db_session):
    with pytest.raises(ValueError, match="boom"):
        with job_run("test_job_fail", key_suffix="k4"):
            raise ValueError("boom")

    row = db_session.query(ScheduledJobRun).filter_by(
        idempotency_key="test_job_fail:k4"
    ).one()
    assert row.status == JobStatus.ERROR
    assert "ValueError: boom" in row.error
    assert row.finished_at is not None


def test_a_failed_job_can_be_retried_without_force(db_session):
    """Only SUCCESS blocks a rerun; a failure must be retryable by cron."""
    with pytest.raises(ValueError):
        with job_run("test_job_retry", key_suffix="k5"):
            raise ValueError("first attempt failed")

    with job_run("test_job_retry", key_suffix="k5") as (_s, run):
        run.detail = "recovered"

    row = db_session.query(ScheduledJobRun).filter_by(
        idempotency_key="test_job_retry:k5"
    ).one()
    assert row.status == JobStatus.SUCCESS
    assert row.attempt == 2


def test_run_job_returns_zero_on_success():
    assert run_job("test_exit_ok", lambda s, r: "fine", key_suffix="e1") == 0


def test_run_job_returns_nonzero_on_failure():
    def explode(_s, _r):
        raise RuntimeError("nope")

    assert run_job("test_exit_fail", explode, key_suffix="e2") == 1


def test_run_job_returns_zero_when_skipped():
    """A skipped job is not an error - cron must not alert on it."""
    run_job("test_exit_skip", lambda s, r: "first", key_suffix="e3")
    assert run_job("test_exit_skip", lambda s, r: "second", key_suffix="e3") == 0


# --- briefings ------------------------------------------------------------
def test_briefing_is_produced_without_an_api_key(db_session, monkeypatch, price_df, ohlc_df):
    """A missing credential degrades the briefing; it never breaks the pipeline."""
    from jobs import briefing as b

    monkeypatch.setattr(b, "get_price_history", lambda *a, **k: price_df)
    monkeypatch.setattr(b, "get_ohlc_history", lambda *a, **k: ohlc_df)
    monkeypatch.setattr(b, "technical_context", lambda p=None: _fake_tech(price_df))

    from btcmoon.config import Config

    # AI enabled, but no credential: the exact situation on first deploy.
    monkeypatch.setattr(Config, "AI_ENABLED", True)
    monkeypatch.setattr(Config, "OPENAI_API_KEY", "")

    result = b.generate_briefing(db_session, BriefingKind.MORNING)
    assert result.ai_generated is False
    assert result.estimated_cost_usd == 0.0
    assert result.visibility == Visibility.PRIVATE
    assert "OPENAI_API_KEY is not set" in result.body_markdown
    assert "produced without an AI call" in result.body_markdown
    # It still contains real, computed evidence.
    assert "## Market" in result.body_markdown
    assert "## Editorial triage" in result.body_markdown
    assert "[FACT]" in result.body_markdown
    assert result.triage in TriageLevel.ALL


def test_briefing_is_private_by_default(db_session, monkeypatch, price_df, ohlc_df):
    from jobs import briefing as b

    monkeypatch.setattr(b, "get_price_history", lambda *a, **k: price_df)
    monkeypatch.setattr(b, "get_ohlc_history", lambda *a, **k: ohlc_df)
    monkeypatch.setattr(b, "technical_context", lambda p=None: _fake_tech(price_df))
    result = b.generate_briefing(db_session, BriefingKind.EVENING)
    assert result.visibility == Visibility.PRIVATE


def test_triage_parsing_recognises_every_level():
    from jobs.briefing import parse_triage

    cases = {
        "TRIAGE: Nothing material": TriageLevel.NOTHING_MATERIAL,
        "TRIAGE: Watch": TriageLevel.WATCH,
        "TRIAGE: Possible story": TriageLevel.POSSIBLE_STORY,
        "TRIAGE: Experiment update required": TriageLevel.EXPERIMENT_UPDATE_REQUIRED,
        "TRIAGE: Prediction or result requires review":
            TriageLevel.PREDICTION_OR_RESULT_REVIEW,
    }
    for text, expected in cases.items():
        level, _note = parse_triage(text + "\nBecause reasons.")
        assert level == expected


def test_briefing_flags_a_live_protocol_window(db_session, monkeypatch, price_df, ohlc_df):
    """A frozen protocol inside its window must escalate the triage."""
    from btcmoon.research.protocols import seed_protocols
    from jobs import briefing as b

    seed_protocols(db_session)
    monkeypatch.setattr(b, "get_price_history", lambda *a, **k: price_df)
    monkeypatch.setattr(b, "get_ohlc_history", lambda *a, **k: ohlc_df)
    monkeypatch.setattr(b, "technical_context", lambda p=None: _fake_tech(price_df))

    when = dt.datetime(2026, 9, 21, 7, 0)
    result = b.generate_briefing(db_session, BriefingKind.MORNING, when=when)
    assert result.triage == TriageLevel.EXPERIMENT_UPDATE_REQUIRED
    assert "september-2026-new-moon-test" in result.body_markdown
    # It reports the qualifying pivot AND, separately, the deeper lows that
    # followed - without letting the latter overturn the former.
    assert "qualifying strict local low DID form" in result.body_markdown
    assert "does NOT invalidate the qualifying pivot" in result.body_markdown
    assert "Absolute cycle low" in result.body_markdown


def _fake_tech(price_df):
    from btcmoon.market_data.adapters import technical_context

    return technical_context(price_df)
