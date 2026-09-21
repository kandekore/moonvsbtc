"""Builds the twice-daily private research briefing (spec s12).

Evidence is gathered deterministically and for free FIRST. The AI is asked only
to prioritise and write it up. If the AI is unavailable - no key, budget ceiling,
provider error - a complete deterministic briefing is produced anyway, so the
Editor is never left with nothing.
"""
from __future__ import annotations

import datetime as dt
import json
import re

from btcmoon.ai import AiClient
from btcmoon.ai.prompts import BRIEFING_SYSTEM
from btcmoon.astrology import natal_context
from btcmoon.lunar import lunar_context
from btcmoon.market_data import MarketError, get_price_history, technical_context
from btcmoon.models import (
    BriefingKind, Experiment, ExperimentStatus, Prediction, ResearchBriefing,
    ResearchProtocol, Status, TriageLevel, Visibility, utcnow,
)
from btcmoon.news import top_stories
from btcmoon.research import evaluate_nm_low_test, legacy_offset_summary
from btcmoon.research.legacy import legacy_analysis

#: Maps the model's TRIAGE: line back onto a stored value.
TRIAGE_FROM_TEXT = {
    "nothing material": TriageLevel.NOTHING_MATERIAL,
    "watch": TriageLevel.WATCH,
    "possible story": TriageLevel.POSSIBLE_STORY,
    "experiment update required": TriageLevel.EXPERIMENT_UPDATE_REQUIRED,
    "prediction or result requires review": TriageLevel.PREDICTION_OR_RESULT_REVIEW,
}


def gather_context(session, when: dt.datetime | None = None) -> dict:
    """Everything the briefing needs, collected without a single AI call."""
    when = when or utcnow()
    ctx: dict = {"generated_at": when.isoformat(), "date": when.date().isoformat()}

    price = None
    try:
        price = get_price_history()
        ctx["market"] = technical_context(price)
    except MarketError as exc:
        ctx["market"] = {"error": str(exc)}

    ctx["lunar"] = lunar_context(when).to_dict()
    ctx["natal"] = natal_context(when.date())

    # Active experiments and their live status against real data.
    experiments = (
        session.query(Experiment)
        .filter(Experiment.experiment_status.in_(
            (ExperimentStatus.ACTIVE, ExperimentStatus.OBSERVING)))
        .all()
    )
    ctx["active_experiments"] = [
        {
            "id": e.id, "ref": e.ref, "title": e.title,
            "status": e.experiment_status, "outcome": e.outcome,
            "test_criteria": e.test_criteria,
            "invalidation_criteria": e.invalidation_criteria,
            "ends_at": e.ends_at.isoformat() if e.ends_at else None,
            "days_remaining": (e.ends_at.date() - when.date()).days if e.ends_at else None,
        }
        for e in experiments
    ]

    # Frozen protocol windows, re-evaluated against the latest market data.
    ctx["protocol_status"] = []
    if price is not None:
        for proto in session.query(ResearchProtocol).filter(
            ResearchProtocol.is_frozen.is_(True)
        ).all():
            rules = json.loads(proto.rules_json or "{}")
            nm_raw = rules.get("new_moon_utc")
            if not nm_raw:
                continue
            nm_date = dt.datetime.fromisoformat(nm_raw.replace("Z", "")).date()
            test = evaluate_nm_low_test(price, nm_date)
            ctx["protocol_status"].append({
                "protocol": proto.slug, "version": proto.version,
                "window_open": bool(
                    proto.window_start and proto.window_end
                    and proto.window_start <= when <= proto.window_end
                ),
                "test": test.to_dict(),
            })

    # Open predictions whose horizon has passed and now need a result.
    ctx["predictions_awaiting_result"] = [
        {"id": p.id, "title": p.title, "horizon_end": p.horizon_end.isoformat(),
         "outcome": p.outcome}
        for p in session.query(Prediction).filter(
            Prediction.outcome == "pending",
            Prediction.horizon_end.isnot(None),
            Prediction.horizon_end <= when,
        ).all()
    ]

    ctx["news"] = [
        {"headline": n.headline, "publisher": n.publisher, "url": n.canonical_url,
         "category": n.category, "relevance": n.relevance_score,
         "published": n.source_published_at.isoformat() if n.source_published_at else None}
        for n in top_stories(session, limit=10, hours=24, min_score=25.0)
    ]

    # Scheduled ahead: the lunar events we already know are coming.
    ctx["scheduled_ahead"] = [
        {"label": e["label"], "exact_at": e["exact_at"],
         "strength_score": e["strength_score"],
         "days_away": round(
             (dt.datetime.fromisoformat(e["exact_at"]) - when).total_seconds() / 86400.0, 1
         )}
        for e in ctx["lunar"].get("upcoming", [])
    ]

    if price is not None:
        try:
            ctx["legacy_benchmarks"] = legacy_offset_summary(legacy_analysis(price_df=price))
        except Exception as exc:
            ctx["legacy_benchmarks"] = {"error": str(exc)}
    return ctx


# ---------------------------------------------------------------------------
# Deterministic write-up (the no-AI fallback, and the AI's evidence base)
# ---------------------------------------------------------------------------
def deterministic_body(ctx: dict, kind: str) -> tuple[str, str, str, str]:
    """(headline, markdown body, triage, triage note) with no AI involved."""
    m = ctx.get("market") or {}
    lunar = ctx.get("lunar") or {}
    lines: list[str] = []

    lines.append("## Market")
    if m.get("error"):
        lines.append(f"- [FACT] Market data unavailable: {m['error']}")
    else:
        lines.append(
            f"- [FACT] BTC ${m.get('price'):,.0f} "
            f"({m.get('change_24h_pct'):+.2f}% 24h, {m.get('change_7d_pct'):+.2f}% 7d)."
        )
        lines.append(
            f"- [TECHNICAL] Regime: {m.get('regime')}. RSI(14) {m.get('rsi14')}, "
            f"30d annualised volatility {m.get('annualised_volatility_30d_pct')}%."
        )
        lines.append(
            f"- [FACT] 50d MA ${m.get('ma50'):,.0f}, 200d MA ${m.get('ma200'):,.0f}, "
            f"{m.get('pct_from_ath'):+.1f}% from the all-time high."
        )
        if m.get("support"):
            lines.append(f"- [TECHNICAL] Nearby support: {', '.join(f'${v:,.0f}' for v in m['support'])}.")
        if m.get("resistance"):
            lines.append(f"- [TECHNICAL] Nearby resistance: {', '.join(f'${v:,.0f}' for v in m['resistance'])}.")

    lines.append("\n## Lunar & experiment status")
    lines.append(
        f"- [FACT] {lunar.get('phase_name')}, {lunar.get('illumination_pct')}% illuminated, "
        f"day {lunar.get('age_days')} of the synodic cycle."
    )
    lines.append(
        f"- [FACT] {lunar.get('days_since_full_moon')} days since the last Full Moon; "
        f"{lunar.get('days_since_new_moon')} days since the last New Moon."
    )

    triage = TriageLevel.NOTHING_MATERIAL
    triage_note = "Routine briefing; nothing requiring an editorial decision."

    for proto in ctx.get("protocol_status", []):
        t = proto["test"]
        state = "a strict local low DID form" if t["strict_low_formed"] else "NO strict local low formed"
        lines.append(
            f"- [FACT] Frozen protocol `{proto['protocol']}` v{proto['version']}: "
            f"in window {t['window']}, {state}. Lowest close {t['low_date']} at "
            f"${t['low_price']:,.2f} (NM{t['offset_days']:+d})."
        )
        if t.get("note"):
            lines.append(f"  - {t['note']}")
        for horizon in (7, 14, 21):
            val = t.get(f"upside_{horizon}d_pct")
            if val is not None:
                lines.append(f"  - [FACT] Maximum upside {horizon} days from the pivot: {val:+.2f}%.")
        if proto["window_open"]:
            triage = TriageLevel.EXPERIMENT_UPDATE_REQUIRED
            triage_note = f"Frozen protocol {proto['protocol']} is inside its live window."

    for exp in ctx.get("active_experiments", []):
        remaining = exp.get("days_remaining")
        lines.append(
            f"- [FACT] Experiment {exp.get('ref') or exp['id']} — {exp['title']} "
            f"({exp['status']}"
            + (f", {remaining} days remaining" if remaining is not None else "")
            + ")."
        )
        if remaining is not None and remaining <= 0:
            triage = TriageLevel.EXPERIMENT_UPDATE_REQUIRED
            triage_note = f"Experiment '{exp['title']}' has reached the end of its window."

    awaiting = ctx.get("predictions_awaiting_result") or []
    if awaiting:
        triage = TriageLevel.PREDICTION_OR_RESULT_REVIEW
        triage_note = f"{len(awaiting)} prediction(s) past their horizon and awaiting a result."
        lines.append("\n## Predictions awaiting a result")
        for p in awaiting:
            lines.append(f"- [PREDICTION] #{p['id']} {p['title']} — horizon ended {p['horizon_end'][:10]}.")

    natal = ctx.get("natal") or {}
    if natal.get("notable_transits"):
        lines.append("\n## Natal transits")
        for t in natal["notable_transits"][:4]:
            lines.append(
                f"- [ASTRO] {t['label']} (orb {t['orb_deg']}°, "
                f"{'applying' if t['is_applying'] else 'separating'}). Experimental."
            )

    news = ctx.get("news") or []
    if news:
        lines.append("\n## News & catalysts")
        for n in news[:6]:
            lines.append(f"- [SOURCE] {n['headline']} — {n['publisher']} ({n['url']})")
        if any(n["relevance"] >= 60 for n in news) and triage == TriageLevel.NOTHING_MATERIAL:
            triage = TriageLevel.WATCH
            triage_note = "A high-relevance development was ingested in the last 24 hours."
    else:
        lines.append("\n## News & catalysts")
        lines.append("- No tracked developments in the last 24 hours.")

    ahead = ctx.get("scheduled_ahead") or []
    if ahead:
        lines.append("\n## Scheduled ahead")
        for e in ahead[:4]:
            lines.append(
                f"- [FACT] {e['label']} in {e['days_away']} days "
                f"({e['exact_at'][:16].replace('T', ' ')} UTC), "
                f"geometry strength {e['strength_score']}/100 (context only, not a signal)."
            )

    lines.append("\n## Editorial triage")
    lines.append(f"TRIAGE: {TriageLevel.LABELS[triage]}")
    lines.append(triage_note)

    price_str = f"BTC ${m['price']:,.0f}" if m.get("price") else "BTC price unavailable"
    headline = f"{kind.title()} brief — {price_str}, {lunar.get('phase_name', 'moon')}"
    return headline, "\n".join(lines), triage, triage_note


def parse_triage(text: str) -> tuple[str, str]:
    """Pull the TRIAGE: line out of an AI-written briefing."""
    match = re.search(r"^TRIAGE:\s*(.+)$", text, re.MULTILINE | re.IGNORECASE)
    if not match:
        return TriageLevel.WATCH, ""
    raw = match.group(1).strip().rstrip(".")
    level = TRIAGE_FROM_TEXT.get(raw.lower(), TriageLevel.WATCH)
    tail = text[match.end():].strip().split("\n")[0]
    return level, tail


def generate_briefing(session, kind: str, when: dt.datetime | None = None,
                      job_run_id: int | None = None) -> ResearchBriefing:
    """Build, optionally AI-write, and store one private briefing."""
    when = when or utcnow()
    ctx = gather_context(session, when)
    headline, body, triage, note = deterministic_body(ctx, kind)

    briefing = ResearchBriefing(
        kind=kind, briefing_date=when.date(), generated_at=when,
        headline=headline, body_markdown=body,
        context_json=json.dumps(ctx, default=str),
        triage=triage, triage_note=note,
        visibility=Visibility.PRIVATE, job_run_id=job_run_id,
    )
    session.add(briefing)
    session.flush()

    task = "briefing_morning" if kind == BriefingKind.MORNING else "briefing_evening"
    client = AiClient(session)
    resp = client.complete(
        task=task,
        system=BRIEFING_SYSTEM,
        user=(
            f"Today is {when.date().isoformat()}. Write the {kind} briefing.\n\n"
            "EVIDENCE (JSON, gathered deterministically - do not contradict it and "
            "do not add figures that are not here):\n\n"
            + json.dumps(ctx, indent=2, default=str)
            + "\n\nA deterministic draft is below. Improve its prioritisation and "
            "readability; keep every factual claim identical.\n\n"
            + body
        ),
        briefing_id=briefing.id,
    )

    if resp.ok and resp.text.strip():
        ai_triage, ai_note = parse_triage(resp.text)
        briefing.body_markdown = resp.text
        briefing.triage = ai_triage
        briefing.triage_note = ai_note or note
        briefing.ai_generated = True
        briefing.model = resp.model
        briefing.estimated_cost_usd = resp.estimated_cost_usd
        first_line = resp.text.strip().split("\n")[0].lstrip("# ").strip()
        if first_line and len(first_line) < 200:
            briefing.headline = first_line
    else:
        briefing.body_markdown = (
            body
            + "\n\n---\n*This briefing was produced without an AI call: "
            + (resp.fallback_reason or "AI unavailable")
            + " Every figure above was computed directly from market, lunar and "
            "protocol data.*"
        )

    session.flush()
    return briefing
