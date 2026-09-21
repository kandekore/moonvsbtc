"""Accounts, entitlements, scheduled jobs and the AI cost ledger."""
from __future__ import annotations

import datetime as dt
import secrets

from sqlalchemy import (
    Boolean, Date, DateTime, Float, ForeignKey, Index, Integer, String, Text,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship
from werkzeug.security import check_password_hash, generate_password_hash

from ..db import Base
from .enums import JobStatus, Role
from .mixins import TimestampMixin, utcnow


class User(Base, TimestampMixin):
    """Admins (the Editor) and, later, subscribers.

    Subscriber roles are deliberately separate from admin permissions (spec s20):
    a subscriber can never reach admin or Companion routes.
    """

    __tablename__ = "users"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    email: Mapped[str] = mapped_column(String(191), unique=True, nullable=False)
    display_name: Mapped[str] = mapped_column(String(120), default="", nullable=False)
    password_hash: Mapped[str] = mapped_column(String(255), default="", nullable=False)
    role: Mapped[str] = mapped_column(String(32), default=Role.READER, nullable=False, index=True)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)
    last_login_at: Mapped[dt.datetime | None] = mapped_column(DateTime)

    subscriptions: Mapped[list["Subscription"]] = relationship(
        back_populates="user", cascade="all, delete-orphan"
    )

    # -- password ---------------------------------------------------------
    def set_password(self, raw: str) -> None:
        self.password_hash = generate_password_hash(raw)

    def check_password(self, raw: str) -> bool:
        if not self.password_hash:
            return False
        return check_password_hash(self.password_hash, raw)

    # -- roles ------------------------------------------------------------
    @property
    def is_admin(self) -> bool:
        return self.role == Role.ADMIN and self.is_active

    # -- Flask-Login ------------------------------------------------------
    @property
    def is_authenticated(self) -> bool:
        return True

    @property
    def is_anonymous(self) -> bool:
        return False

    def get_id(self) -> str:
        return str(self.id)

    def __repr__(self) -> str:
        return f"<User {self.email} {self.role}>"


class Subscription(Base, TimestampMixin):
    """Entitlement record. Everything is free through FREE_UNTIL; this table
    exists so the paywall can be switched on later without a migration."""

    __tablename__ = "subscriptions"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), index=True)
    plan: Mapped[str] = mapped_column(String(64), default="free", nullable=False)
    status: Mapped[str] = mapped_column(String(32), default="active", nullable=False)
    entitlements: Mapped[str] = mapped_column(Text, default="", nullable=False)  # CSV of feature keys
    starts_on: Mapped[dt.date] = mapped_column(Date, default=dt.date.today, nullable=False)
    ends_on: Mapped[dt.date | None] = mapped_column(Date)
    external_ref: Mapped[str] = mapped_column(String(191), default="", nullable=False)

    user: Mapped[User] = relationship(back_populates="subscriptions")


class ScheduledJobRun(Base, TimestampMixin):
    """Idempotency + audit for cron-driven jobs (spec s6, s20).

    ``idempotency_key`` is unique, so a second run of the same logical job on
    the same day is refused rather than duplicated.
    """

    __tablename__ = "scheduled_job_runs"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    job_name: Mapped[str] = mapped_column(String(120), nullable=False, index=True)
    idempotency_key: Mapped[str] = mapped_column(String(191), unique=True, nullable=False)
    status: Mapped[str] = mapped_column(String(32), default=JobStatus.RUNNING, nullable=False)
    started_at: Mapped[dt.datetime] = mapped_column(DateTime, default=utcnow, nullable=False)
    finished_at: Mapped[dt.datetime | None] = mapped_column(DateTime)
    attempt: Mapped[int] = mapped_column(Integer, default=1, nullable=False)
    detail: Mapped[str] = mapped_column(Text, default="", nullable=False)
    error: Mapped[str] = mapped_column(Text, default="", nullable=False)

    @property
    def duration_seconds(self) -> float | None:
        if not self.finished_at:
            return None
        return (self.finished_at - self.started_at).total_seconds()


class AiUsage(Base, TimestampMixin):
    """Every AI call is logged here before its result is used (spec s19)."""

    __tablename__ = "ai_usage"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    provider: Mapped[str] = mapped_column(String(64), default="openai", nullable=False, index=True)
    model: Mapped[str] = mapped_column(String(120), nullable=False, index=True)
    task: Mapped[str] = mapped_column(String(64), nullable=False, index=True)
    input_tokens: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    output_tokens: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    cached_input_tokens: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    estimated_cost_usd: Mapped[float] = mapped_column(Float, default=0.0, nullable=False)
    cache_status: Mapped[str] = mapped_column(String(32), default="none", nullable=False)
    occurred_at: Mapped[dt.datetime] = mapped_column(
        DateTime, default=utcnow, nullable=False, index=True
    )
    # Loose back-references: a usage row must survive its subject being deleted.
    briefing_id: Mapped[int | None] = mapped_column(Integer)
    article_id: Mapped[int | None] = mapped_column(Integer)
    conversation_id: Mapped[int | None] = mapped_column(Integer)
    outlook_id: Mapped[int | None] = mapped_column(Integer)
    note: Mapped[str] = mapped_column(Text, default="", nullable=False)

    __table_args__ = (Index("ix_ai_usage_task_time", "task", "occurred_at"),)


class AppSetting(Base, TimestampMixin):
    """Admin-editable runtime settings (model choices, budget, feed toggles).

    Environment variables provide the defaults; a row here overrides one.
    """

    __tablename__ = "app_settings"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    key: Mapped[str] = mapped_column(String(120), unique=True, nullable=False)
    value: Mapped[str] = mapped_column(Text, default="", nullable=False)
    description: Mapped[str] = mapped_column(String(255), default="", nullable=False)


def new_token(nbytes: int = 24) -> str:
    return secrets.token_urlsafe(nbytes)
