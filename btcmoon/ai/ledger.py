"""AI spend ledger and hard budget enforcement (spec s19 - mandatory).

Every AI call goes through ``BudgetGuard.check()`` first and ``record_usage()``
after. At the monthly ceiling non-essential generation stops, while the public
site, data collection and admin stay fully operational.
"""
from __future__ import annotations

import calendar
import datetime as dt
from dataclasses import dataclass

from sqlalchemy import func, select

from ..config import Config
from ..models import AiUsage, AppSetting
from .pricing import estimate_cost, load_overrides


class BudgetExceeded(RuntimeError):
    """Raised when a call would breach the hard ceiling."""


#: Tasks that must keep working even when the budget is exhausted is an empty
#: set by design: at the ceiling ALL AI generation stops. Deterministic
#: pipelines (RSS, market data, lunar/natal maths) never call the AI at all,
#: so the site and jobs continue regardless.
ESSENTIAL_TASKS: frozenset[str] = frozenset()


def _month_bounds(when: dt.date) -> tuple[dt.datetime, dt.datetime]:
    first = dt.datetime(when.year, when.month, 1)
    last_day = calendar.monthrange(when.year, when.month)[1]
    return first, dt.datetime(when.year, when.month, last_day, 23, 59, 59)


def _setting(session, key: str, default: float) -> float:
    row = session.query(AppSetting).filter_by(key=key).one_or_none()
    if row and row.value.strip():
        try:
            return float(row.value)
        except ValueError:
            pass
    return default


def monthly_budget(session) -> float:
    return _setting(session, "ai_monthly_budget_usd", Config.AI_MONTHLY_BUDGET_USD)


def daily_budget(session) -> float:
    return _setting(session, "ai_daily_budget_usd", Config.AI_DAILY_BUDGET_USD)


def spend_between(session, start: dt.datetime, end: dt.datetime) -> float:
    total = session.execute(
        select(func.coalesce(func.sum(AiUsage.estimated_cost_usd), 0.0)).where(
            AiUsage.occurred_at >= start, AiUsage.occurred_at <= end
        )
    ).scalar_one()
    return round(float(total or 0.0), 6)


def spend_today(session, when: dt.date | None = None) -> float:
    when = when or dt.date.today()
    return spend_between(
        session,
        dt.datetime(when.year, when.month, when.day),
        dt.datetime(when.year, when.month, when.day, 23, 59, 59),
    )


def spend_this_month(session, when: dt.date | None = None) -> float:
    start, end = _month_bounds(when or dt.date.today())
    return spend_between(session, start, end)


def spend_by(session, column, when: dt.date | None = None) -> list[tuple[str, float, int]]:
    """Month-to-date spend grouped by a column (task or model)."""
    start, end = _month_bounds(when or dt.date.today())
    rows = session.execute(
        select(column, func.sum(AiUsage.estimated_cost_usd), func.count(AiUsage.id))
        .where(AiUsage.occurred_at >= start, AiUsage.occurred_at <= end)
        .group_by(column)
        .order_by(func.sum(AiUsage.estimated_cost_usd).desc())
    ).all()
    return [(r[0], round(float(r[1] or 0.0), 6), int(r[2])) for r in rows]


def average_cost_for_task(session, task: str, limit: int = 30) -> float:
    rows = session.execute(
        select(AiUsage.estimated_cost_usd)
        .where(AiUsage.task == task)
        .order_by(AiUsage.occurred_at.desc())
        .limit(limit)
    ).scalars().all()
    return round(sum(rows) / len(rows), 6) if rows else 0.0


@dataclass
class BudgetStatus:
    month_spend: float
    month_budget: float
    day_spend: float
    day_budget: float
    #: Highest warning threshold crossed: None, 0.50, 0.75 or 0.90.
    warning_level: float | None
    is_over_month: bool
    is_over_day: bool

    @property
    def month_pct(self) -> float:
        return round(self.month_spend / self.month_budget * 100.0, 1) if self.month_budget else 0.0

    @property
    def day_pct(self) -> float:
        return round(self.day_spend / self.day_budget * 100.0, 1) if self.day_budget else 0.0

    @property
    def remaining_month(self) -> float:
        return round(max(0.0, self.month_budget - self.month_spend), 4)

    @property
    def blocked(self) -> bool:
        return self.is_over_month or self.is_over_day

    def to_dict(self) -> dict:
        return {
            "month_spend": self.month_spend, "month_budget": self.month_budget,
            "month_pct": self.month_pct, "day_spend": self.day_spend,
            "day_budget": self.day_budget, "day_pct": self.day_pct,
            "warning_level": self.warning_level, "blocked": self.blocked,
            "remaining_month": self.remaining_month,
        }


def budget_status(session, when: dt.date | None = None) -> BudgetStatus:
    when = when or dt.date.today()
    m_spend, m_budget = spend_this_month(session, when), monthly_budget(session)
    d_spend, d_budget = spend_today(session, when), daily_budget(session)

    warning = None
    if m_budget > 0:
        ratio = m_spend / m_budget
        for level in sorted(Config.AI_BUDGET_WARN_LEVELS):
            if ratio >= level:
                warning = level
    return BudgetStatus(
        month_spend=m_spend, month_budget=m_budget,
        day_spend=d_spend, day_budget=d_budget, warning_level=warning,
        is_over_month=m_budget > 0 and m_spend >= m_budget,
        is_over_day=d_budget > 0 and d_spend >= d_budget,
    )


class BudgetGuard:
    """Gatekeeper consulted before every AI call."""

    def __init__(self, session):
        self.session = session

    def check(self, task: str, raise_on_block: bool = False) -> BudgetStatus:
        status = budget_status(self.session)
        if status.blocked and task not in ESSENTIAL_TASKS and raise_on_block:
            which = "monthly" if status.is_over_month else "daily"
            raise BudgetExceeded(
                f"AI {which} budget reached "
                f"(${status.month_spend:.4f} of ${status.month_budget:.2f} this month). "
                f"Non-essential AI generation is paused; the site and data jobs "
                f"continue to run."
            )
        return status

    def allows(self, task: str) -> bool:
        return not self.check(task).blocked or task in ESSENTIAL_TASKS


def record_usage(
    session,
    *,
    model: str,
    task: str,
    input_tokens: int = 0,
    output_tokens: int = 0,
    cached_input_tokens: int = 0,
    provider: str = "openai",
    cache_status: str = "none",
    note: str = "",
    briefing_id: int | None = None,
    article_id: int | None = None,
    conversation_id: int | None = None,
    outlook_id: int | None = None,
    commit: bool = True,
) -> AiUsage:
    """Write one row to the cost ledger. Called after every AI response."""
    cost, known = estimate_cost(
        model, input_tokens, output_tokens, cached_input_tokens,
        overrides=load_overrides(session),
    )
    if not known:
        note = (note + f" [unpriced model '{model}'; fallback rate applied]").strip()

    usage = AiUsage(
        provider=provider, model=model, task=task,
        input_tokens=input_tokens, output_tokens=output_tokens,
        cached_input_tokens=cached_input_tokens,
        estimated_cost_usd=cost, cache_status=cache_status, note=note,
        briefing_id=briefing_id, article_id=article_id,
        conversation_id=conversation_id, outlook_id=outlook_id,
    )
    session.add(usage)
    session.flush()
    if commit:
        session.commit()
    return usage
