"""Editorial output and the private laboratory record.

``Conversation``/``Message`` are the private Companion. They are PRIVATE by
default and have no public serializer anywhere in the codebase - see
``btcmoon/editorial/serializers.py`` and the privacy tests.
"""
from __future__ import annotations

import datetime as dt

from sqlalchemy import (
    Boolean, Date, DateTime, Float, ForeignKey, Integer, String, Text,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from ..db import Base
from .enums import (
    ArticleType, BriefingKind, OutlookKind, Provenance, Status, TriageLevel, Visibility,
)
from .mixins import TimestampMixin, utcnow


class Conversation(Base, TimestampMixin):
    """A private research conversation. Never public, ever."""

    __tablename__ = "conversations"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), index=True)
    title: Mapped[str] = mapped_column(String(255), default="New research thread", nullable=False)
    #: Hard-wired private. Present so a mis-set value is detectable, not so it can be relaxed.
    visibility: Mapped[str] = mapped_column(String(16), default=Visibility.PRIVATE, nullable=False)
    is_archived: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    last_message_at: Mapped[dt.datetime | None] = mapped_column(DateTime, index=True)

    messages: Mapped[list["Message"]] = relationship(
        back_populates="conversation", cascade="all, delete-orphan", order_by="Message.created_at"
    )


class Message(Base, TimestampMixin):
    """One turn of private chat. May contain trades, P&L, screenshots - private."""

    __tablename__ = "messages"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    conversation_id: Mapped[int] = mapped_column(
        ForeignKey("conversations.id", ondelete="CASCADE"), index=True
    )
    role: Mapped[str] = mapped_column(String(16), nullable=False)  # user | assistant | system
    content: Mapped[str] = mapped_column(Text, default="", nullable=False)
    #: Structured evidence the AI used, so a promoted record can carry provenance.
    context_json: Mapped[str] = mapped_column(Text, default="{}", nullable=False)
    model: Mapped[str] = mapped_column(String(120), default="", nullable=False)
    ai_usage_id: Mapped[int | None] = mapped_column(Integer)
    visibility: Mapped[str] = mapped_column(String(16), default=Visibility.PRIVATE, nullable=False)

    conversation: Mapped[Conversation] = relationship(back_populates="messages")


class ResearchBriefing(Base, TimestampMixin):
    """Twice-daily private research briefing (spec s12). Private by default."""

    __tablename__ = "research_briefings"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    kind: Mapped[str] = mapped_column(String(16), default=BriefingKind.MORNING, nullable=False, index=True)
    briefing_date: Mapped[dt.date] = mapped_column(Date, nullable=False, index=True)
    generated_at: Mapped[dt.datetime] = mapped_column(DateTime, default=utcnow, nullable=False)
    headline: Mapped[str] = mapped_column(String(255), default="", nullable=False)
    body_markdown: Mapped[str] = mapped_column(Text, default="", nullable=False)
    #: Deterministic evidence gathered before any AI call (cheap-first pipeline).
    context_json: Mapped[str] = mapped_column(Text, default="{}", nullable=False)
    triage: Mapped[str] = mapped_column(
        String(48), default=TriageLevel.NOTHING_MATERIAL, nullable=False, index=True
    )
    triage_note: Mapped[str] = mapped_column(Text, default="", nullable=False)
    ai_generated: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    model: Mapped[str] = mapped_column(String(120), default="", nullable=False)
    estimated_cost_usd: Mapped[float] = mapped_column(Float, default=0.0, nullable=False)
    visibility: Mapped[str] = mapped_column(String(16), default=Visibility.PRIVATE, nullable=False)
    job_run_id: Mapped[int | None] = mapped_column(Integer)
    reviewed_at: Mapped[dt.datetime | None] = mapped_column(DateTime)


class Article(Base, TimestampMixin):
    """Public editorial. Draft until the Editor publishes it."""

    __tablename__ = "articles"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    slug: Mapped[str] = mapped_column(String(191), unique=True, nullable=False)
    title: Mapped[str] = mapped_column(String(255), nullable=False)
    subtitle: Mapped[str] = mapped_column(String(500), default="", nullable=False)
    summary: Mapped[str] = mapped_column(Text, default="", nullable=False)
    body_markdown: Mapped[str] = mapped_column(Text, default="", nullable=False)
    article_type: Mapped[str] = mapped_column(String(48), default=ArticleType.ARTICLE, nullable=False, index=True)
    record_kind: Mapped[str] = mapped_column(String(32), default="", nullable=False)  # OBSERVATION/RESULT/... label

    experiment_id: Mapped[int | None] = mapped_column(ForeignKey("experiments.id"), index=True)
    prediction_id: Mapped[int | None] = mapped_column(ForeignKey("predictions.id"))
    observation_id: Mapped[int | None] = mapped_column(ForeignKey("observations.id"))
    result_id: Mapped[int | None] = mapped_column(ForeignKey("results.id"))

    #: The date the content is *about* - may be historical for archive rebuilds.
    observed_at: Mapped[dt.datetime | None] = mapped_column(DateTime, index=True)
    #: When this site actually published it. Never backdated (spec Appendix).
    published_at: Mapped[dt.datetime | None] = mapped_column(DateTime, index=True)
    imported_at: Mapped[dt.datetime] = mapped_column(DateTime, default=utcnow, nullable=False)
    result_recorded_at: Mapped[dt.datetime | None] = mapped_column(DateTime)

    status: Mapped[str] = mapped_column(String(32), default=Status.DRAFT, nullable=False, index=True)
    visibility: Mapped[str] = mapped_column(String(16), default=Visibility.PRIVATE, nullable=False)
    provenance: Mapped[str] = mapped_column(String(48), default=Provenance.EDITOR, nullable=False, index=True)
    sources_json: Mapped[str] = mapped_column(Text, default="[]", nullable=False)

    # SEO
    meta_description: Mapped[str] = mapped_column(String(320), default="", nullable=False)
    canonical_url: Mapped[str] = mapped_column(String(500), default="", nullable=False)
    og_image: Mapped[str] = mapped_column(String(500), default="", nullable=False)
    noindex: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)

    # entitlement (paywall machinery, disabled by config until 2027)
    required_entitlement: Mapped[str] = mapped_column(String(64), default="", nullable=False)

    ai_generated: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    ai_model: Mapped[str] = mapped_column(String(120), default="", nullable=False)
    conversation_id: Mapped[int | None] = mapped_column(Integer)

    @property
    def is_reconstructed(self) -> bool:
        """True when the piece describes a past date but was written later."""
        return self.provenance in Provenance.RETROSPECTIVE


class Outlook(Base, TimestampMixin):
    """BTC natal-chart outlook: daily, monthly, yearly (spec s14).

    Daily outlooks are published one day ahead. Historical outlooks stay
    accessible and can gain an appended retrospective review.
    """

    __tablename__ = "outlooks"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    slug: Mapped[str] = mapped_column(String(191), unique=True, nullable=False)
    kind: Mapped[str] = mapped_column(String(32), default=OutlookKind.DAILY, nullable=False, index=True)
    #: The day/month/year the outlook covers.
    period_start: Mapped[dt.date] = mapped_column(Date, nullable=False, index=True)
    period_end: Mapped[dt.date] = mapped_column(Date, nullable=False)
    title: Mapped[str] = mapped_column(String(255), nullable=False)
    summary: Mapped[str] = mapped_column(Text, default="", nullable=False)
    body_markdown: Mapped[str] = mapped_column(Text, default="", nullable=False)

    natal_context_json: Mapped[str] = mapped_column(Text, default="{}", nullable=False)
    lunar_context_json: Mapped[str] = mapped_column(Text, default="{}", nullable=False)
    technical_context_json: Mapped[str] = mapped_column(Text, default="{}", nullable=False)
    events_json: Mapped[str] = mapped_column(Text, default="[]", nullable=False)
    levels_json: Mapped[str] = mapped_column(Text, default="{}", nullable=False)

    #: Appended after the fact - never replaces the original body.
    review_markdown: Mapped[str] = mapped_column(Text, default="", nullable=False)
    review_recorded_at: Mapped[dt.datetime | None] = mapped_column(DateTime)

    status: Mapped[str] = mapped_column(String(32), default=Status.DRAFT, nullable=False, index=True)
    visibility: Mapped[str] = mapped_column(String(16), default=Visibility.PRIVATE, nullable=False)
    provenance: Mapped[str] = mapped_column(String(48), default=Provenance.AUTOMATED_RESEARCH, nullable=False)
    published_at: Mapped[dt.datetime | None] = mapped_column(DateTime, index=True)
    required_entitlement: Mapped[str] = mapped_column(String(64), default="", nullable=False)
    meta_description: Mapped[str] = mapped_column(String(320), default="", nullable=False)
    ai_generated: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    ai_model: Mapped[str] = mapped_column(String(120), default="", nullable=False)
    estimated_cost_usd: Mapped[float] = mapped_column(Float, default=0.0, nullable=False)
