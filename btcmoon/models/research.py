"""The scientific record: protocols, experiments, observations, hypotheses,
predictions and results.

Two rules are enforced here rather than left to convention (spec Appendix):

* A published prediction is immutable. ``Prediction.__setattr__`` refuses to
  change its locked fields once ``published_at`` is set; corrections are new
  ``Result`` rows appended underneath.
* A frozen ``ResearchProtocol`` cannot be edited after it is frozen. Protocol
  changes are new versions, never silent edits.
"""
from __future__ import annotations

import datetime as dt

from sqlalchemy import (
    Boolean, Date, DateTime, Float, ForeignKey, Integer, String, Text,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from ..db import Base
from .enums import ExperimentStatus, Outcome, Provenance, Status, Visibility
from .mixins import TimestampMixin, utcnow


class ImmutableAfterPublishError(RuntimeError):
    """Raised when code tries to rewrite a published, locked record."""


class ResearchProtocol(Base, TimestampMixin):
    """A versioned, frozen statement of how a test will be judged.

    Spec s8/s9: never silently alter lag windows, pivot definitions, scoring
    weights or the strength formula because recent price action did not fit.
    """

    __tablename__ = "research_protocols"

    _LOCKED = (
        "slug", "version", "title", "rules_json", "summary",
        "window_start", "window_end", "frozen_at",
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    slug: Mapped[str] = mapped_column(String(191), unique=True, nullable=False)
    version: Mapped[str] = mapped_column(String(32), default="1.0", nullable=False)
    title: Mapped[str] = mapped_column(String(255), nullable=False)
    summary: Mapped[str] = mapped_column(Text, default="", nullable=False)
    #: Machine-readable rules (JSON): lag windows, thresholds, scoring weights.
    rules_json: Mapped[str] = mapped_column(Text, default="{}", nullable=False)
    window_start: Mapped[dt.datetime | None] = mapped_column(DateTime)
    window_end: Mapped[dt.datetime | None] = mapped_column(DateTime)
    is_frozen: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    frozen_at: Mapped[dt.datetime | None] = mapped_column(DateTime)
    supersedes_id: Mapped[int | None] = mapped_column(ForeignKey("research_protocols.id"))
    status: Mapped[str] = mapped_column(String(32), default=Status.DRAFT, nullable=False)
    provenance: Mapped[str] = mapped_column(
        String(48), default=Provenance.EDITOR, nullable=False
    )

    experiments: Mapped[list["Experiment"]] = relationship(back_populates="protocol")

    def freeze(self) -> None:
        self.is_frozen = True
        self.frozen_at = utcnow()

    def __setattr__(self, name, value):
        if (
            name in self._LOCKED
            and getattr(self, "is_frozen", False)
            and getattr(self, name, None) not in (None, "")
            and value != getattr(self, name)
        ):
            raise ImmutableAfterPublishError(
                f"ResearchProtocol.{name} is frozen; publish a new version instead."
            )
        super().__setattr__(name, value)


class Experiment(Base, TimestampMixin):
    """A public experiment record (spec s16)."""

    __tablename__ = "experiments"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    slug: Mapped[str] = mapped_column(String(191), unique=True, nullable=False)
    ref: Mapped[str] = mapped_column(String(64), default="", nullable=False)  # e.g. EXP-2026-09-NM
    title: Mapped[str] = mapped_column(String(255), nullable=False)
    summary: Mapped[str] = mapped_column(Text, default="", nullable=False)
    protocol_id: Mapped[int | None] = mapped_column(ForeignKey("research_protocols.id"))

    observed_at: Mapped[dt.datetime | None] = mapped_column(DateTime, index=True)
    starts_at: Mapped[dt.datetime | None] = mapped_column(DateTime)
    ends_at: Mapped[dt.datetime | None] = mapped_column(DateTime)

    # Context captured at creation, as JSON blobs so later statistics can use them.
    moon_context_json: Mapped[str] = mapped_column(Text, default="{}", nullable=False)
    btc_snapshot_json: Mapped[str] = mapped_column(Text, default="{}", nullable=False)
    natal_context_json: Mapped[str] = mapped_column(Text, default="{}", nullable=False)
    technical_context: Mapped[str] = mapped_column(Text, default="", nullable=False)
    market_news_context: Mapped[str] = mapped_column(Text, default="", nullable=False)

    hypothesis_text: Mapped[str] = mapped_column(Text, default="", nullable=False)
    prediction_text: Mapped[str] = mapped_column(Text, default="", nullable=False)
    confidence: Mapped[str] = mapped_column(String(64), default="", nullable=False)
    test_criteria: Mapped[str] = mapped_column(Text, default="", nullable=False)
    invalidation_criteria: Mapped[str] = mapped_column(Text, default="", nullable=False)

    experiment_status: Mapped[str] = mapped_column(
        String(32), default=ExperimentStatus.PLANNED, nullable=False, index=True
    )
    outcome: Mapped[str] = mapped_column(
        String(32), default=Outcome.PENDING, nullable=False, index=True
    )
    result_text: Mapped[str] = mapped_column(Text, default="", nullable=False)
    timing_error_days: Mapped[float | None] = mapped_column(Float)
    subsequent_high: Mapped[float | None] = mapped_column(Float)
    subsequent_low: Mapped[float | None] = mapped_column(Float)
    lessons: Mapped[str] = mapped_column(Text, default="", nullable=False)

    status: Mapped[str] = mapped_column(
        String(32), default=Status.DRAFT, nullable=False, index=True
    )
    visibility: Mapped[str] = mapped_column(
        String(16), default=Visibility.PRIVATE, nullable=False
    )
    provenance: Mapped[str] = mapped_column(
        String(48), default=Provenance.EDITOR, nullable=False, index=True
    )
    published_at: Mapped[dt.datetime | None] = mapped_column(DateTime, index=True)
    result_recorded_at: Mapped[dt.datetime | None] = mapped_column(DateTime)
    conversation_id: Mapped[int | None] = mapped_column(Integer)  # origin, if promoted from chat

    protocol: Mapped[ResearchProtocol | None] = relationship(back_populates="experiments")
    observations: Mapped[list["Observation"]] = relationship(back_populates="experiment")
    hypotheses: Mapped[list["Hypothesis"]] = relationship(back_populates="experiment")
    predictions: Mapped[list["Prediction"]] = relationship(back_populates="experiment")
    results: Mapped[list["Result"]] = relationship(back_populates="experiment")


class Observation(Base, TimestampMixin):
    """Something noticed and recorded, with its observation time kept separate
    from its import/publication time (spec s10)."""

    __tablename__ = "observations"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    slug: Mapped[str] = mapped_column(String(191), unique=True, nullable=False)
    title: Mapped[str] = mapped_column(String(255), nullable=False)
    body: Mapped[str] = mapped_column(Text, default="", nullable=False)
    experiment_id: Mapped[int | None] = mapped_column(ForeignKey("experiments.id"), index=True)

    #: When the thing was actually observed (may be historical).
    observed_at: Mapped[dt.datetime] = mapped_column(DateTime, nullable=False, index=True)
    #: When this row entered the database.
    imported_at: Mapped[dt.datetime] = mapped_column(DateTime, default=utcnow, nullable=False)
    published_at: Mapped[dt.datetime | None] = mapped_column(DateTime, index=True)

    btc_snapshot_json: Mapped[str] = mapped_column(Text, default="{}", nullable=False)
    moon_context_json: Mapped[str] = mapped_column(Text, default="{}", nullable=False)
    sources_json: Mapped[str] = mapped_column(Text, default="[]", nullable=False)

    status: Mapped[str] = mapped_column(
        String(32), default=Status.DRAFT, nullable=False, index=True
    )
    visibility: Mapped[str] = mapped_column(
        String(16), default=Visibility.PRIVATE, nullable=False
    )
    provenance: Mapped[str] = mapped_column(
        String(48), default=Provenance.EDITOR, nullable=False, index=True
    )
    conversation_id: Mapped[int | None] = mapped_column(Integer)  # origin, if promoted from chat

    experiment: Mapped[Experiment | None] = relationship(back_populates="observations")


class Hypothesis(Base, TimestampMixin):
    __tablename__ = "hypotheses"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    slug: Mapped[str] = mapped_column(String(191), unique=True, nullable=False)
    title: Mapped[str] = mapped_column(String(255), nullable=False)
    body: Mapped[str] = mapped_column(Text, default="", nullable=False)
    experiment_id: Mapped[int | None] = mapped_column(ForeignKey("experiments.id"), index=True)
    rationale: Mapped[str] = mapped_column(Text, default="", nullable=False)
    test_criteria: Mapped[str] = mapped_column(Text, default="", nullable=False)
    observed_at: Mapped[dt.datetime] = mapped_column(DateTime, default=utcnow, nullable=False)
    published_at: Mapped[dt.datetime | None] = mapped_column(DateTime)
    status: Mapped[str] = mapped_column(String(32), default=Status.DRAFT, nullable=False, index=True)
    visibility: Mapped[str] = mapped_column(String(16), default=Visibility.PRIVATE, nullable=False)
    provenance: Mapped[str] = mapped_column(String(48), default=Provenance.EDITOR, nullable=False)
    conversation_id: Mapped[int | None] = mapped_column(Integer)

    experiment: Mapped[Experiment | None] = relationship(back_populates="hypotheses")


class Prediction(Base, TimestampMixin):
    """A forward-looking, falsifiable statement.

    Once published the prediction text, criteria and evidence snapshot are
    locked. Any later correction is appended as a ``Result``.
    """

    __tablename__ = "predictions"

    #: Fields frozen at publication (spec s10, s16).
    _LOCKED = (
        "prediction_text", "test_criteria", "invalidation_criteria",
        "evidence_snapshot_json", "horizon_end", "made_at", "published_at",
        "confidence", "slug",
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    slug: Mapped[str] = mapped_column(String(191), unique=True, nullable=False)
    title: Mapped[str] = mapped_column(String(255), nullable=False)
    experiment_id: Mapped[int | None] = mapped_column(ForeignKey("experiments.id"), index=True)
    protocol_id: Mapped[int | None] = mapped_column(ForeignKey("research_protocols.id"))

    prediction_text: Mapped[str] = mapped_column(Text, nullable=False)
    test_criteria: Mapped[str] = mapped_column(Text, default="", nullable=False)
    invalidation_criteria: Mapped[str] = mapped_column(Text, default="", nullable=False)
    confidence: Mapped[str] = mapped_column(String(64), default="", nullable=False)
    #: Everything known at the moment of prediction, frozen as JSON.
    evidence_snapshot_json: Mapped[str] = mapped_column(Text, default="{}", nullable=False)

    #: When the prediction was made (may precede publication).
    made_at: Mapped[dt.datetime] = mapped_column(DateTime, default=utcnow, nullable=False, index=True)
    horizon_end: Mapped[dt.datetime | None] = mapped_column(DateTime, index=True)
    published_at: Mapped[dt.datetime | None] = mapped_column(DateTime, index=True)

    status: Mapped[str] = mapped_column(String(32), default=Status.DRAFT, nullable=False, index=True)
    visibility: Mapped[str] = mapped_column(String(16), default=Visibility.PRIVATE, nullable=False)
    provenance: Mapped[str] = mapped_column(String(48), default=Provenance.EDITOR, nullable=False, index=True)
    outcome: Mapped[str] = mapped_column(String(32), default=Outcome.PENDING, nullable=False, index=True)
    conversation_id: Mapped[int | None] = mapped_column(Integer)

    experiment: Mapped[Experiment | None] = relationship(back_populates="predictions")
    results: Mapped[list["Result"]] = relationship(
        back_populates="prediction", order_by="Result.recorded_at"
    )

    @property
    def is_locked(self) -> bool:
        return self.published_at is not None and self.status == Status.PUBLISHED

    def publish(self) -> None:
        """Publish and lock. Called once; further edits raise."""
        if self.is_locked:
            raise ImmutableAfterPublishError("Prediction is already published.")
        self.status = Status.PUBLISHED
        self.visibility = Visibility.PUBLIC
        self.published_at = utcnow()

    def __setattr__(self, name, value):
        if name in self._LOCKED and self.__dict__.get("published_at") is not None:
            if self.__dict__.get("status") == Status.PUBLISHED and value != getattr(self, name, None):
                raise ImmutableAfterPublishError(
                    f"Prediction.{name} is immutable once published; append a Result instead."
                )
        super().__setattr__(name, value)


class Result(Base, TimestampMixin):
    """Appended underneath a prediction/experiment. Never overwrites it."""

    __tablename__ = "results"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    slug: Mapped[str] = mapped_column(String(191), unique=True, nullable=False)
    title: Mapped[str] = mapped_column(String(255), nullable=False)
    prediction_id: Mapped[int | None] = mapped_column(ForeignKey("predictions.id"), index=True)
    experiment_id: Mapped[int | None] = mapped_column(ForeignKey("experiments.id"), index=True)

    body: Mapped[str] = mapped_column(Text, default="", nullable=False)
    outcome: Mapped[str] = mapped_column(String(32), default=Outcome.PENDING, nullable=False, index=True)
    #: Numeric fields kept for later statistical testing (spec s16).
    timing_error_days: Mapped[float | None] = mapped_column(Float)
    price_at_prediction: Mapped[float | None] = mapped_column(Float)
    price_at_result: Mapped[float | None] = mapped_column(Float)
    subsequent_high: Mapped[float | None] = mapped_column(Float)
    subsequent_low: Mapped[float | None] = mapped_column(Float)
    max_upside_pct: Mapped[float | None] = mapped_column(Float)
    max_downside_pct: Mapped[float | None] = mapped_column(Float)
    metrics_json: Mapped[str] = mapped_column(Text, default="{}", nullable=False)
    lessons: Mapped[str] = mapped_column(Text, default="", nullable=False)
    sources_json: Mapped[str] = mapped_column(Text, default="[]", nullable=False)

    recorded_at: Mapped[dt.datetime] = mapped_column(DateTime, default=utcnow, nullable=False, index=True)
    result_recorded_at: Mapped[dt.datetime | None] = mapped_column(DateTime)
    published_at: Mapped[dt.datetime | None] = mapped_column(DateTime, index=True)
    status: Mapped[str] = mapped_column(String(32), default=Status.DRAFT, nullable=False, index=True)
    visibility: Mapped[str] = mapped_column(String(16), default=Visibility.PRIVATE, nullable=False)
    provenance: Mapped[str] = mapped_column(String(48), default=Provenance.EDITOR, nullable=False)

    prediction: Mapped[Prediction | None] = relationship(back_populates="results")
    experiment: Mapped[Experiment | None] = relationship(back_populates="results")


class TechnicalPattern(Base, TimestampMixin):
    """Chart structures under observation (cup & handle, H&S, ...).

    Failures are first-class records: a pattern that fails is kept, not deleted.
    """

    __tablename__ = "technical_patterns"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    slug: Mapped[str] = mapped_column(String(191), unique=True, nullable=False)
    name: Mapped[str] = mapped_column(String(191), nullable=False)
    pattern_type: Mapped[str] = mapped_column(String(64), default="", nullable=False)
    timeframe: Mapped[str] = mapped_column(String(32), default="daily", nullable=False)
    identified_at: Mapped[dt.datetime] = mapped_column(DateTime, nullable=False, index=True)
    description: Mapped[str] = mapped_column(Text, default="", nullable=False)
    trigger_level: Mapped[float | None] = mapped_column(Float)
    confirmation_low: Mapped[float | None] = mapped_column(Float)
    confirmation_high: Mapped[float | None] = mapped_column(Float)
    target_low: Mapped[float | None] = mapped_column(Float)
    target_high: Mapped[float | None] = mapped_column(Float)
    invalidation_level: Mapped[float | None] = mapped_column(Float)
    pattern_status: Mapped[str] = mapped_column(String(32), default="forming", nullable=False)
    outcome: Mapped[str] = mapped_column(String(32), default=Outcome.PENDING, nullable=False)
    resolution_note: Mapped[str] = mapped_column(Text, default="", nullable=False)
    experiment_id: Mapped[int | None] = mapped_column(ForeignKey("experiments.id"))
    status: Mapped[str] = mapped_column(String(32), default=Status.DRAFT, nullable=False, index=True)
    visibility: Mapped[str] = mapped_column(String(16), default=Visibility.PRIVATE, nullable=False)
    provenance: Mapped[str] = mapped_column(String(48), default=Provenance.EDITOR, nullable=False)
    published_at: Mapped[dt.datetime | None] = mapped_column(DateTime)
