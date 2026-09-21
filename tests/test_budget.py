"""AI cost tracking and hard budget ceiling (spec s19 - mandatory)."""
from __future__ import annotations

import datetime as dt

import pytest

from btcmoon.ai import AiClient, budget_status, record_usage, spend_by, spend_today
from btcmoon.ai.ledger import BudgetExceeded, BudgetGuard
from btcmoon.ai.pricing import estimate_cost, pricing_for
from btcmoon.models import AiUsage, AppSetting


def _set_budget(session, monthly: float, daily: float = 1000.0):
    for key, val in (("ai_monthly_budget_usd", monthly), ("ai_daily_budget_usd", daily)):
        row = session.query(AppSetting).filter_by(key=key).one_or_none()
        if row is None:
            row = AppSetting(key=key)
            session.add(row)
        row.value = str(val)
    session.flush()


def test_known_model_is_priced(db_session):
    cost, known = estimate_cost("gpt-4o-mini", 1_000_000, 1_000_000)
    assert known is True
    assert cost == pytest.approx(0.75, abs=0.001)   # 0.15 in + 0.60 out


def test_cached_input_is_cheaper(db_session):
    plain, _ = estimate_cost("gpt-4o", 100_000, 0)
    cached, _ = estimate_cost("gpt-4o", 100_000, 0, cached_input_tokens=100_000)
    assert cached < plain


def test_unknown_model_falls_back_and_is_flagged(db_session):
    cost, known = estimate_cost("some-model-that-does-not-exist", 1_000_000, 0)
    assert known is False
    assert cost > 0, "an unpriced model must never report zero spend"


def test_dated_snapshot_ids_resolve_to_the_base_model():
    price, known = pricing_for("gpt-4o-mini-2024-07-18")
    assert known is True
    assert price["input"] == 0.15


def test_usage_is_recorded_with_a_cost(db_session):
    usage = record_usage(
        db_session, model="gpt-4o-mini", task="briefing_morning",
        input_tokens=10_000, output_tokens=2_000, commit=False,
    )
    assert usage.estimated_cost_usd > 0
    assert usage.task == "briefing_morning"
    assert spend_today(db_session) >= usage.estimated_cost_usd


def test_unpriced_model_is_noted_in_the_ledger(db_session):
    usage = record_usage(db_session, model="mystery-model-9", task="companion_chat",
                         input_tokens=1000, output_tokens=100, commit=False)
    assert "unpriced model" in usage.note


def test_warning_thresholds_fire_at_50_75_and_90_percent(db_session):
    _set_budget(db_session, monthly=1.0)
    assert budget_status(db_session).warning_level is None

    record_usage(db_session, model="gpt-4o", task="t", input_tokens=200_000,
                 output_tokens=0, commit=False)          # $0.50
    assert budget_status(db_session).warning_level == 0.50

    record_usage(db_session, model="gpt-4o", task="t", input_tokens=100_000,
                 output_tokens=0, commit=False)          # $0.75 total
    assert budget_status(db_session).warning_level == 0.75

    record_usage(db_session, model="gpt-4o", task="t", input_tokens=60_000,
                 output_tokens=0, commit=False)          # $0.90 total
    assert budget_status(db_session).warning_level == 0.90


def test_hard_ceiling_blocks_further_generation(db_session):
    _set_budget(db_session, monthly=0.10)
    record_usage(db_session, model="gpt-4o", task="t", input_tokens=100_000,
                 output_tokens=0, commit=False)          # $0.25 > $0.10
    status = budget_status(db_session)
    assert status.is_over_month
    assert status.blocked

    with pytest.raises(BudgetExceeded, match="budget reached"):
        BudgetGuard(db_session).check("briefing_morning", raise_on_block=True)


def test_daily_ceiling_blocks_independently(db_session):
    _set_budget(db_session, monthly=1000.0, daily=0.05)
    record_usage(db_session, model="gpt-4o", task="t", input_tokens=100_000,
                 output_tokens=0, commit=False)
    status = budget_status(db_session)
    assert status.is_over_day
    assert status.blocked
    assert not status.is_over_month


def test_ai_client_refuses_when_over_budget(db_session, monkeypatch):
    """With a key present and AI enabled, the budget alone must stop the call."""
    from btcmoon.config import Config

    monkeypatch.setattr(Config, "AI_ENABLED", True)
    monkeypatch.setattr(Config, "OPENAI_API_KEY", "sk-test-not-a-real-key")

    _set_budget(db_session, monthly=0.01)
    record_usage(db_session, model="gpt-4o", task="t", input_tokens=100_000,
                 output_tokens=0, commit=False)

    ok, why = AiClient(db_session).availability()
    assert ok is False
    assert "budget reached" in why
    # The site and data jobs are explicitly unaffected.
    assert "site and data jobs continue" in why


def test_ai_client_degrades_gracefully_without_a_key(db_session):
    """A missing credential must never raise - it returns a usable fallback."""
    resp = AiClient(db_session).complete("briefing_morning", "sys", "user")
    assert resp.ok is False
    assert resp.fallback_reason
    assert resp.text == ""


def test_spend_grouping_by_task(db_session):
    record_usage(db_session, model="gpt-4o-mini", task="news_summarise",
                 input_tokens=5000, output_tokens=500, commit=False)
    record_usage(db_session, model="gpt-4o", task="article_draft",
                 input_tokens=5000, output_tokens=500, commit=False)
    grouped = dict((t, c) for t, c, _ in spend_by(db_session, AiUsage.task))
    assert "news_summarise" in grouped
    assert grouped["article_draft"] > grouped["news_summarise"]


def test_cheap_tasks_do_not_use_the_expensive_model():
    """Model selection per task is explicit, never one expensive default."""
    from btcmoon.ai.client import TASK_MODEL_TIER

    assert TASK_MODEL_TIER["news_classify"] == "AI_MODEL_CHEAP"
    assert TASK_MODEL_TIER["news_summarise"] == "AI_MODEL_CHEAP"
    assert TASK_MODEL_TIER["article_draft"] == "AI_MODEL_STRONG"


def test_public_site_still_works_at_the_ceiling(db_session, client):
    """At the ceiling, AI stops but the site keeps serving (spec s19)."""
    _set_budget(db_session, monthly=0.01)
    record_usage(db_session, model="gpt-4o", task="t", input_tokens=100_000,
                 output_tokens=0, commit=True)
    assert budget_status(db_session).blocked
    for path in ("/", "/methodology/", "/predictions/", "/news/"):
        assert client.get(path).status_code == 200
