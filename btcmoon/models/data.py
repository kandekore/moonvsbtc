"""Ingested and computed data: news sources, market snapshots, lunar and
natal events."""
from __future__ import annotations

import datetime as dt

from sqlalchemy import (
    Boolean, Date, DateTime, Float, ForeignKey, Index, Integer, String, Text,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from ..db import Base
from .enums import NewsCategory, Status, Visibility
from .mixins import TimestampMixin, utcnow


class Source(Base, TimestampMixin):
    """A feed or publication we ingest from and attribute to."""

    __tablename__ = "sources"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    slug: Mapped[str] = mapped_column(String(191), unique=True, nullable=False)
    name: Mapped[str] = mapped_column(String(191), nullable=False)
    homepage: Mapped[str] = mapped_column(String(500), default="", nullable=False)
    feed_url: Mapped[str] = mapped_column(String(500), default="", nullable=False)
    source_type: Mapped[str] = mapped_column(String(32), default="rss", nullable=False)
    default_category: Mapped[str] = mapped_column(String(48), default=NewsCategory.OTHER, nullable=False)
    #: Primary/authoritative sources are preferred for factual macro claims.
    is_authoritative: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    is_enabled: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False, index=True)
    weight: Mapped[float] = mapped_column(Float, default=1.0, nullable=False)
    last_fetched_at: Mapped[dt.datetime | None] = mapped_column(DateTime)
    last_error: Mapped[str] = mapped_column(Text, default="", nullable=False)

    items: Mapped[list["NewsItem"]] = relationship(back_populates="source")


class NewsItem(Base, TimestampMixin):
    """One ingested story. We store a link, attribution and our own short
    summary - never a full copyrighted article body (spec s13)."""

    __tablename__ = "news_items"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    source_id: Mapped[int | None] = mapped_column(ForeignKey("sources.id"), index=True)
    headline: Mapped[str] = mapped_column(String(500), nullable=False)
    canonical_url: Mapped[str] = mapped_column(String(700), default="", nullable=False)
    publisher: Mapped[str] = mapped_column(String(191), default="", nullable=False)
    #: When the publisher published it (from the feed).
    source_published_at: Mapped[dt.datetime | None] = mapped_column(DateTime, index=True)
    #: When we retrieved it.
    retrieved_at: Mapped[dt.datetime] = mapped_column(DateTime, default=utcnow, nullable=False, index=True)
    category: Mapped[str] = mapped_column(String(48), default=NewsCategory.OTHER, nullable=False, index=True)
    summary: Mapped[str] = mapped_column(Text, default="", nullable=False)
    #: Cheap, rule-based score computed at ingestion; AI is not used per item.
    relevance_score: Mapped[float] = mapped_column(Float, default=0.0, nullable=False, index=True)
    #: sha1 of normalised title+url, used to drop syndicated duplicates.
    fingerprint: Mapped[str] = mapped_column(String(64), unique=True, nullable=False)
    is_featured: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False, index=True)
    is_hidden: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    editor_note: Mapped[str] = mapped_column(Text, default="", nullable=False)

    source: Mapped[Source | None] = relationship(back_populates="items")

    __table_args__ = (Index("ix_news_cat_relevance", "category", "relevance_score"),)


class MarketSnapshot(Base, TimestampMixin):
    """A point-in-time BTC snapshot, frozen into evidence records."""

    __tablename__ = "market_snapshots"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    captured_at: Mapped[dt.datetime] = mapped_column(DateTime, default=utcnow, nullable=False, index=True)
    snapshot_date: Mapped[dt.date] = mapped_column(Date, nullable=False, index=True)
    symbol: Mapped[str] = mapped_column(String(32), default="BTC-USD", nullable=False)
    price: Mapped[float | None] = mapped_column(Float)
    open_price: Mapped[float | None] = mapped_column(Float)
    high: Mapped[float | None] = mapped_column(Float)
    low: Mapped[float | None] = mapped_column(Float)
    close: Mapped[float | None] = mapped_column(Float)
    volume: Mapped[float | None] = mapped_column(Float)
    change_24h_pct: Mapped[float | None] = mapped_column(Float)
    change_7d_pct: Mapped[float | None] = mapped_column(Float)
    volatility_30d: Mapped[float | None] = mapped_column(Float)
    ma50: Mapped[float | None] = mapped_column(Float)
    ma200: Mapped[float | None] = mapped_column(Float)
    rsi14: Mapped[float | None] = mapped_column(Float)
    support_levels_json: Mapped[str] = mapped_column(Text, default="[]", nullable=False)
    resistance_levels_json: Mapped[str] = mapped_column(Text, default="[]", nullable=False)
    provider: Mapped[str] = mapped_column(String(64), default="yfinance", nullable=False)
    raw_json: Mapped[str] = mapped_column(Text, default="{}", nullable=False)


class LunarEvent(Base, TimestampMixin):
    """A computed lunar event (new/full moon, quarter) with its research context."""

    __tablename__ = "lunar_events"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    event_type: Mapped[str] = mapped_column(String(32), nullable=False, index=True)  # new_moon|full_moon|...
    exact_at: Mapped[dt.datetime] = mapped_column(DateTime, nullable=False, index=True)
    event_date: Mapped[dt.date] = mapped_column(Date, nullable=False, index=True)
    #: Strength score (0-100) recorded in advance; NOT evidence an event must occur.
    strength_score: Mapped[float | None] = mapped_column(Float)
    strength_components_json: Mapped[str] = mapped_column(Text, default="{}", nullable=False)
    nodal_distance_deg: Mapped[float | None] = mapped_column(Float)
    ecliptic_longitude_deg: Mapped[float | None] = mapped_column(Float)
    distance_km: Mapped[float | None] = mapped_column(Float)
    is_eclipse: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    notes: Mapped[str] = mapped_column(Text, default="", nullable=False)

    __table_args__ = (Index("ix_lunar_type_date", "event_type", "event_date"),)


class NatalEvent(Base, TimestampMixin):
    """A transit to Bitcoin's natal chart (spec s14)."""

    __tablename__ = "natal_events"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    transiting_body: Mapped[str] = mapped_column(String(48), nullable=False, index=True)
    natal_point: Mapped[str] = mapped_column(String(48), nullable=False)
    aspect: Mapped[str] = mapped_column(String(32), nullable=False)  # conjunction|opposition|square|trine|sextile
    exact_at: Mapped[dt.datetime | None] = mapped_column(DateTime, index=True)
    event_date: Mapped[dt.date] = mapped_column(Date, nullable=False, index=True)
    orb_deg: Mapped[float | None] = mapped_column(Float)
    is_applying: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)
    weight: Mapped[float] = mapped_column(Float, default=1.0, nullable=False)
    interpretation: Mapped[str] = mapped_column(Text, default="", nullable=False)

    __table_args__ = (Index("ix_natal_date_body", "event_date", "transiting_body"),)
