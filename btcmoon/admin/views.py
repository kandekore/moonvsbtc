"""The private laboratory: dashboard, Companion, editorial CRUD, cost control.

Every route here is admin-only, checked server-side on each request.
"""
from __future__ import annotations

import datetime as dt
import json

from flask import (
    Blueprint, abort, flash, redirect, render_template, request, url_for,
)
from flask_login import current_user
from sqlalchemy import desc

from ..ai import (
    TASK_MODEL_TIER, average_cost_for_task, budget_status, model_for_task,
    spend_by, spend_this_month, spend_today,
)
from ..auth.decorators import admin_required
from ..db import Session
from ..editorial import (
    EditorialError, append_outlook_review, archive, create_hypothesis,
    create_observation, create_prediction, draft_article, publish,
    record_result, unpublish,
)
from ..models import (
    AiUsage, AppSetting, Article, Conversation, Experiment, ExperimentStatus,
    Hypothesis, ImmutableAfterPublishError, NewsItem, Observation, Outcome,
    Outlook, Prediction, Provenance, ResearchBriefing, ResearchProtocol, Result,
    ScheduledJobRun, Source, Status, TriageLevel, User, Visibility, utcnow,
)
from ..news import ingest_all
from . import companion as comp

bp = Blueprint("admin", __name__)


@bp.before_request
@admin_required
def _guard():
    """Belt and braces: every admin route is authorised before dispatch."""
    return None


# ---------------------------------------------------------------------------
# Dashboard
# ---------------------------------------------------------------------------
@bp.route("/")
def dashboard():
    s = Session
    status = budget_status(s)
    return render_template(
        "admin/dashboard.html", title="Research laboratory", noindex=True,
        budget=status,
        briefings=s.query(ResearchBriefing)
        .order_by(desc(ResearchBriefing.generated_at)).limit(6).all(),
        pending_triage=s.query(ResearchBriefing)
        .filter(ResearchBriefing.reviewed_at.is_(None),
                ResearchBriefing.triage != TriageLevel.NOTHING_MATERIAL)
        .count(),
        drafts={
            "articles": s.query(Article).filter(Article.status == Status.DRAFT).count(),
            "observations": s.query(Observation).filter(Observation.status == Status.DRAFT).count(),
            "predictions": s.query(Prediction).filter(Prediction.status == Status.DRAFT).count(),
            "results": s.query(Result).filter(Result.status == Status.DRAFT).count(),
            "outlooks": s.query(Outlook).filter(Outlook.status == Status.DRAFT).count(),
        },
        experiments=s.query(Experiment)
        .filter(Experiment.experiment_status.in_(
            (ExperimentStatus.ACTIVE, ExperimentStatus.OBSERVING)))
        .all(),
        jobs=s.query(ScheduledJobRun).order_by(desc(ScheduledJobRun.started_at)).limit(8).all(),
        news_count=s.query(NewsItem).count(),
    )


# ---------------------------------------------------------------------------
# Private Companion
# ---------------------------------------------------------------------------
@bp.route("/companion/", methods=["GET", "POST"])
@bp.route("/companion/<int:conversation_id>/", methods=["GET", "POST"])
def companion(conversation_id: int | None = None):
    s = Session
    convo = None
    if conversation_id:
        convo = s.query(Conversation).filter_by(
            id=conversation_id, user_id=current_user.id
        ).one_or_none()
        if not convo:
            abort(404)

    if request.method == "POST":
        text = (request.form.get("message") or "").strip()
        if not text:
            flash("Write something first.", "error")
        else:
            convo = comp.get_or_create_conversation(
                s, current_user.id, convo.id if convo else None
            )
            comp.ask(s, convo, text)
            s.commit()
            return redirect(url_for("admin.companion", conversation_id=convo.id))

    return render_template(
        "admin/companion.html", title="Companion", noindex=True,
        conversation=convo,
        conversations=s.query(Conversation)
        .filter_by(user_id=current_user.id, is_archived=False)
        .order_by(desc(Conversation.last_message_at)).limit(30).all(),
        budget=budget_status(s),
    )


@bp.route("/companion/<int:conversation_id>/promote/", methods=["POST"])
def promote(conversation_id: int):
    """Editorial actions from chat (spec s11).

    Promotion always produces a DRAFT. Nothing from the private laboratory is
    ever published by this route.
    """
    s = Session
    convo = s.query(Conversation).filter_by(
        id=conversation_id, user_id=current_user.id
    ).one_or_none()
    if not convo:
        abort(404)

    action = request.form.get("action") or ""
    title = (request.form.get("title") or "").strip()
    body = (request.form.get("body") or "").strip()

    if not title:
        flash("A title is required.", "error")
        return redirect(url_for("admin.companion", conversation_id=convo.id))

    try:
        if action == "observation":
            obj = create_observation(
                s, title=title, body=body, conversation_id=convo.id,
                provenance=Provenance.CONTEMPORANEOUS_CHAT,
            )
            where = "observations"
        elif action == "hypothesis":
            obj = create_hypothesis(
                s, title=title, body=body, conversation_id=convo.id,
                rationale=request.form.get("rationale") or "",
                test_criteria=request.form.get("test_criteria") or "",
            )
            where = "hypotheses"
        elif action == "prediction":
            obj = create_prediction(
                s, title=title, prediction_text=body,
                test_criteria=request.form.get("test_criteria") or "",
                invalidation_criteria=request.form.get("invalidation_criteria") or "",
                confidence=request.form.get("confidence") or "",
                conversation_id=convo.id,
                evidence_snapshot=comp.build_context(s),
            )
            where = "predictions"
        elif action == "article":
            obj = draft_article(
                s, title=title, body_markdown=body, conversation_id=convo.id,
                summary=(body or "")[:300],
            )
            where = "articles"
        elif action == "archive":
            convo.is_archived = True
            s.commit()
            flash("Conversation archived.", "success")
            return redirect(url_for("admin.companion"))
        else:
            flash("Unknown action.", "error")
            return redirect(url_for("admin.companion", conversation_id=convo.id))
    except EditorialError as exc:
        flash(str(exc), "error")
        return redirect(url_for("admin.companion", conversation_id=convo.id))

    s.commit()
    flash(
        f"Created as a DRAFT in {where}. Nothing is public until you publish it.",
        "success",
    )
    return redirect(url_for("admin.content", kind=where))


# ---------------------------------------------------------------------------
# Editorial queues
# ---------------------------------------------------------------------------
MODEL_MAP = {
    "articles": Article, "observations": Observation, "predictions": Prediction,
    "results": Result, "outlooks": Outlook, "experiments": Experiment,
    "hypotheses": Hypothesis,
}


@bp.route("/content/<kind>/")
def content(kind: str):
    model = MODEL_MAP.get(kind)
    if not model:
        abort(404)
    s = Session
    status_filter = request.args.get("status")
    q = s.query(model)
    if status_filter in Status.ALL:
        q = q.filter(model.status == status_filter)
    order = getattr(model, "published_at", None) or model.created_at
    items = q.order_by(desc(model.created_at)).limit(100).all()
    return render_template(
        "admin/content_list.html", title=kind.title(), noindex=True,
        kind=kind, items=items, statuses=Status.ALL, active_status=status_filter,
    )


@bp.route("/content/<kind>/<int:item_id>/", methods=["GET", "POST"])
def content_edit(kind: str, item_id: int):
    model = MODEL_MAP.get(kind)
    if not model:
        abort(404)
    s = Session
    item = s.get(model, item_id)
    if not item:
        abort(404)

    if request.method == "POST":
        action = request.form.get("action")
        try:
            if action == "save":
                _apply_edits(item, request.form)
                flash("Saved.", "success")
            elif action == "publish":
                publish(s, item)
                flash("Published. It is now live on the public site.", "success")
            elif action == "unpublish":
                unpublish(s, item)
                flash("Withdrawn from the public site.", "success")
            elif action == "archive":
                archive(s, item)
                flash("Archived.", "success")
            elif action == "append_review" and isinstance(item, Outlook):
                append_outlook_review(s, item, request.form.get("review") or "")
                flash("Review appended beneath the original. The original is unchanged.", "success")
            s.commit()
        except ImmutableAfterPublishError as exc:
            s.rollback()
            flash(str(exc), "error")
        except EditorialError as exc:
            s.rollback()
            flash(str(exc), "error")
        return redirect(url_for("admin.content_edit", kind=kind, item_id=item_id))

    return render_template(
        "admin/content_edit.html", title=f"Edit: {getattr(item, 'title', kind)}",
        noindex=True, kind=kind, item=item,
        outcomes=Outcome.ALL, provenances=Provenance.ALL, statuses=Status.ALL,
        is_locked=getattr(item, "is_locked", False),
    )


#: Fields the admin form may write, per model.
EDITABLE = {
    "title", "subtitle", "summary", "body", "body_markdown", "meta_description",
    "record_kind", "article_type", "lessons", "confidence", "test_criteria",
    "invalidation_criteria", "rationale", "provenance", "outcome",
    "hypothesis_text", "prediction_text", "technical_context",
    "market_news_context", "result_text", "experiment_status", "ref",
    "prediction_text", "editor_note",
}


def _apply_edits(item, form) -> None:
    for field in EDITABLE:
        if field in form and hasattr(item, field):
            setattr(item, field, form.get(field))
    for field in ("timing_error_days", "subsequent_high", "subsequent_low",
                  "max_upside_pct", "max_downside_pct", "price_at_prediction",
                  "price_at_result"):
        if field in form and hasattr(item, field):
            raw = (form.get(field) or "").strip()
            setattr(item, field, float(raw) if raw else None)


@bp.route("/content/<kind>/new/", methods=["GET", "POST"])
def content_new(kind: str):
    s = Session
    if request.method == "POST":
        title = (request.form.get("title") or "").strip()
        body = request.form.get("body") or ""
        if not title:
            flash("A title is required.", "error")
        else:
            try:
                if kind == "observations":
                    obj = create_observation(
                        s, title=title, body=body, provenance=Provenance.EDITOR,
                        observed_at=_parse_dt(request.form.get("observed_at")),
                    )
                elif kind == "predictions":
                    obj = create_prediction(
                        s, title=title, prediction_text=body,
                        test_criteria=request.form.get("test_criteria") or "",
                        invalidation_criteria=request.form.get("invalidation_criteria") or "",
                        confidence=request.form.get("confidence") or "",
                        provenance=Provenance.EDITOR,
                        evidence_snapshot=comp.build_context(s),
                    )
                elif kind == "articles":
                    obj = draft_article(
                        s, title=title, body_markdown=body,
                        summary=request.form.get("summary") or "",
                        provenance=Provenance.EDITOR,
                        observed_at=_parse_dt(request.form.get("observed_at")),
                    )
                else:
                    flash(f"Creating {kind} from here is not supported yet.", "error")
                    return redirect(url_for("admin.content", kind=kind))
                s.commit()
                return redirect(url_for("admin.content_edit", kind=kind, item_id=obj.id))
            except EditorialError as exc:
                s.rollback()
                flash(str(exc), "error")
    return render_template(
        "admin/content_new.html", title=f"New {kind[:-1]}", noindex=True, kind=kind,
    )


def _parse_dt(raw: str | None):
    if not raw:
        return None
    try:
        return dt.datetime.fromisoformat(raw)
    except ValueError:
        return None


# ---------------------------------------------------------------------------
# Results
# ---------------------------------------------------------------------------
@bp.route("/predictions/<int:prediction_id>/result/", methods=["GET", "POST"])
def new_result(prediction_id: int):
    s = Session
    pred = s.get(Prediction, prediction_id)
    if not pred:
        abort(404)
    if request.method == "POST":
        try:
            res = record_result(
                s, title=(request.form.get("title") or f"Result: {pred.title}"),
                body=request.form.get("body") or "",
                prediction=pred,
                outcome=request.form.get("outcome") or Outcome.INCONCLUSIVE,
                lessons=request.form.get("lessons") or "",
                timing_error_days=_num(request.form.get("timing_error_days")),
                price_at_result=_num(request.form.get("price_at_result")),
                max_upside_pct=_num(request.form.get("max_upside_pct")),
                max_downside_pct=_num(request.form.get("max_downside_pct")),
            )
            s.commit()
            flash("Result recorded as a draft, appended beneath the locked prediction.", "success")
            return redirect(url_for("admin.content_edit", kind="results", item_id=res.id))
        except EditorialError as exc:
            s.rollback()
            flash(str(exc), "error")
    return render_template(
        "admin/new_result.html", title="Record a result", noindex=True,
        prediction=pred, outcomes=Outcome.ALL,
    )


def _num(raw):
    try:
        return float(raw) if raw not in (None, "") else None
    except (TypeError, ValueError):
        return None


# ---------------------------------------------------------------------------
# Briefings
# ---------------------------------------------------------------------------
@bp.route("/briefings/")
def briefings():
    s = Session
    return render_template(
        "admin/briefings.html", title="Research briefings", noindex=True,
        briefings=s.query(ResearchBriefing)
        .order_by(desc(ResearchBriefing.generated_at)).limit(60).all(),
        triage_labels=TriageLevel.LABELS,
    )


@bp.route("/briefings/<int:briefing_id>/", methods=["GET", "POST"])
def briefing(briefing_id: int):
    s = Session
    b = s.get(ResearchBriefing, briefing_id)
    if not b:
        abort(404)
    if request.method == "POST":
        b.reviewed_at = utcnow()
        s.commit()
        flash("Marked as reviewed.", "success")
        return redirect(url_for("admin.briefings"))
    return render_template(
        "admin/briefing.html", title=b.headline or "Briefing", noindex=True,
        briefing=b, triage_labels=TriageLevel.LABELS,
        context=json.loads(b.context_json or "{}"),
    )


# ---------------------------------------------------------------------------
# AI cost dashboard (spec s19)
# ---------------------------------------------------------------------------
@bp.route("/costs/")
def costs():
    s = Session
    status = budget_status(s)
    return render_template(
        "admin/costs.html", title="AI spend", noindex=True,
        budget=status,
        today=spend_today(s),
        month=spend_this_month(s),
        by_task=spend_by(s, AiUsage.task),
        by_model=spend_by(s, AiUsage.model),
        averages={
            task: average_cost_for_task(s, task)
            for task in TASK_MODEL_TIER
        },
        models={task: model_for_task(task, s) for task in TASK_MODEL_TIER},
        recent=s.query(AiUsage).order_by(desc(AiUsage.occurred_at)).limit(40).all(),
        warn_levels=(0.50, 0.75, 0.90),
    )


@bp.route("/settings/", methods=["GET", "POST"])
def settings():
    s = Session
    if request.method == "POST":
        for key, value in request.form.items():
            if key == "csrf_token" or not key.startswith(("ai_", "news_", "site_")):
                continue
            row = s.query(AppSetting).filter_by(key=key).one_or_none()
            if row is None:
                row = AppSetting(key=key)
                s.add(row)
            row.value = value.strip()
        s.commit()
        flash("Settings saved.", "success")
        return redirect(url_for("admin.settings"))

    rows = {r.key: r.value for r in s.query(AppSetting).all()}
    return render_template(
        "admin/settings.html", title="Settings", noindex=True,
        settings=rows, tasks=TASK_MODEL_TIER,
        effective={task: model_for_task(task, s) for task in TASK_MODEL_TIER},
        budget=budget_status(s),
    )


# ---------------------------------------------------------------------------
# News
# ---------------------------------------------------------------------------
@bp.route("/news/", methods=["GET", "POST"])
def news():
    s = Session
    if request.method == "POST":
        if request.form.get("action") == "ingest":
            report = ingest_all(s)
            flash(
                f"Ingested {report.inserted} new items from {report.fetched} feeds "
                f"({report.duplicates} duplicates skipped)."
                + (f" Errors: {'; '.join(report.errors[:3])}" if report.errors else ""),
                "success" if not report.errors else "warning",
            )
        elif request.form.get("action") == "feature":
            item = s.get(NewsItem, int(request.form.get("item_id", 0)))
            if item:
                item.is_featured = not item.is_featured
                s.commit()
        elif request.form.get("action") == "hide":
            item = s.get(NewsItem, int(request.form.get("item_id", 0)))
            if item:
                item.is_hidden = not item.is_hidden
                s.commit()
        return redirect(url_for("admin.news"))

    return render_template(
        "admin/news.html", title="News ingestion", noindex=True,
        sources=s.query(Source).order_by(Source.name).all(),
        items=s.query(NewsItem)
        .order_by(desc(NewsItem.relevance_score), desc(NewsItem.retrieved_at))
        .limit(80).all(),
    )


# ---------------------------------------------------------------------------
# Jobs
# ---------------------------------------------------------------------------
@bp.route("/jobs/")
def jobs():
    s = Session
    return render_template(
        "admin/jobs.html", title="Scheduled jobs", noindex=True,
        runs=s.query(ScheduledJobRun).order_by(desc(ScheduledJobRun.started_at)).limit(80).all(),
    )
