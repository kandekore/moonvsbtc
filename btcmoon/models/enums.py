"""Vocabulary used across the data model.

These are plain string constants stored in VARCHAR columns rather than native
DB enums, so adding a value never requires an ALTER TABLE.
"""
from __future__ import annotations


class Provenance:
    """Where a record came from. Spec s10 - never fake historical publication."""

    LIVE_SITE = "live_site"                        # published by this site at the time
    CONTEMPORANEOUS_CHAT = "contemporaneous_chat"  # private chat, recorded as it happened
    RESEARCH_PAPER = "research_paper"              # from the exploratory paper
    RECONSTRUCTED_ARCHIVE = "reconstructed_archive"  # written up later, from records
    AUTOMATED_RESEARCH = "automated_research"      # produced by a scheduled job
    EDITOR = "editor"                              # hand-written by the Editor

    ALL = (
        LIVE_SITE, CONTEMPORANEOUS_CHAT, RESEARCH_PAPER,
        RECONSTRUCTED_ARCHIVE, AUTOMATED_RESEARCH, EDITOR,
    )
    #: Provenances that must carry a visible "reconstructed" notice publicly.
    RETROSPECTIVE = (RESEARCH_PAPER, RECONSTRUCTED_ARCHIVE)


class Status:
    """Publication lifecycle. Nothing reaches the public site except PUBLISHED."""

    DRAFT = "draft"
    REVIEW = "review"
    PUBLISHED = "published"
    ARCHIVED = "archived"
    REJECTED = "rejected"

    ALL = (DRAFT, REVIEW, PUBLISHED, ARCHIVED, REJECTED)
    PUBLIC = (PUBLISHED,)


class RecordKind:
    """The label a visitor sees. Spec s15 - forward-looking vs retrospective."""

    OBSERVATION = "observation"
    HYPOTHESIS = "hypothesis"
    PREDICTION = "prediction"
    RESULT = "result"
    RESEARCH_UPDATE = "research_update"
    EXPERIMENTAL = "experimental"

    ALL = (OBSERVATION, HYPOTHESIS, PREDICTION, RESULT, RESEARCH_UPDATE, EXPERIMENTAL)


class Outcome:
    """Spec s16 - deliberately not a win/loss percentage."""

    CONSISTENT = "consistent"
    PARTIALLY_CONSISTENT = "partially_consistent"
    INCONSISTENT = "inconsistent"
    INVALIDATED = "invalidated"
    INCONCLUSIVE = "inconclusive"
    PENDING = "pending"

    ALL = (
        CONSISTENT, PARTIALLY_CONSISTENT, INCONSISTENT,
        INVALIDATED, INCONCLUSIVE, PENDING,
    )


class ExperimentStatus:
    PLANNED = "planned"
    ACTIVE = "active"
    OBSERVING = "observing"
    CONCLUDED = "concluded"
    ABANDONED = "abandoned"

    ALL = (PLANNED, ACTIVE, OBSERVING, CONCLUDED, ABANDONED)


class ArticleType:
    ARTICLE = "article"
    RESEARCH_UPDATE = "research_update"
    EXPERIMENT_LOG = "experiment_log"
    METHODOLOGY = "methodology"
    NEWS_ROUNDUP = "news_roundup"

    ALL = (ARTICLE, RESEARCH_UPDATE, EXPERIMENT_LOG, METHODOLOGY, NEWS_ROUNDUP)


class OutlookKind:
    DAILY = "daily"
    MONTHLY = "monthly"
    YEARLY = "yearly"
    NATAL_EXPLAINED = "natal_explained"
    TRANSIT_CALENDAR = "transit_calendar"

    ALL = (DAILY, MONTHLY, YEARLY, NATAL_EXPLAINED, TRANSIT_CALENDAR)


class NewsCategory:
    MACRO_FED = "macro_fed"
    REGULATION = "regulation"
    ETF_INSTITUTIONAL = "etf_institutional"
    ONCHAIN = "onchain"
    LIQUIDATIONS_DERIVATIVES = "liquidations_derivatives"
    TECHNICAL = "technical"
    SECURITY_EXCHANGE = "security_exchange"
    GEOPOLITICAL = "geopolitical"
    BITCOIN_SPECIFIC = "bitcoin_specific"
    OTHER = "other"

    ALL = (
        MACRO_FED, REGULATION, ETF_INSTITUTIONAL, ONCHAIN,
        LIQUIDATIONS_DERIVATIVES, TECHNICAL, SECURITY_EXCHANGE,
        GEOPOLITICAL, BITCOIN_SPECIFIC, OTHER,
    )

    LABELS = {
        MACRO_FED: "Macro / Fed",
        REGULATION: "Regulation",
        ETF_INSTITUTIONAL: "ETF / Institutional",
        ONCHAIN: "On-chain",
        LIQUIDATIONS_DERIVATIVES: "Liquidations / Derivatives",
        TECHNICAL: "Technical",
        SECURITY_EXCHANGE: "Security / Exchange",
        GEOPOLITICAL: "Geopolitical",
        BITCOIN_SPECIFIC: "Bitcoin-specific",
        OTHER: "Other",
    }


class BriefingKind:
    MORNING = "morning"
    EVENING = "evening"
    ADHOC = "adhoc"

    ALL = (MORNING, EVENING, ADHOC)


class TriageLevel:
    """Spec s12 - every briefing ends with one of these."""

    NOTHING_MATERIAL = "nothing_material"
    WATCH = "watch"
    POSSIBLE_STORY = "possible_story"
    EXPERIMENT_UPDATE_REQUIRED = "experiment_update_required"
    PREDICTION_OR_RESULT_REVIEW = "prediction_or_result_review"

    ALL = (
        NOTHING_MATERIAL, WATCH, POSSIBLE_STORY,
        EXPERIMENT_UPDATE_REQUIRED, PREDICTION_OR_RESULT_REVIEW,
    )

    LABELS = {
        NOTHING_MATERIAL: "Nothing material",
        WATCH: "Watch",
        POSSIBLE_STORY: "Possible story",
        EXPERIMENT_UPDATE_REQUIRED: "Experiment update required",
        PREDICTION_OR_RESULT_REVIEW: "Prediction or result requires review",
    }


class Role:
    ADMIN = "admin"        # the Editor / Chief Scientist
    SUBSCRIBER = "subscriber"
    READER = "reader"

    ALL = (ADMIN, SUBSCRIBER, READER)


class JobStatus:
    RUNNING = "running"
    SUCCESS = "success"
    ERROR = "error"
    SKIPPED = "skipped"

    ALL = (RUNNING, SUCCESS, ERROR, SKIPPED)


class Visibility:
    """The privacy boundary. PRIVATE material never renders on a public page."""

    PRIVATE = "private"
    INTERNAL = "internal"
    PUBLIC = "public"

    ALL = (PRIVATE, INTERNAL, PUBLIC)
