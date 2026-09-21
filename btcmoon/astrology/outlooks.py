"""Build BTC natal-chart outlooks (spec s14).

Daily outlooks are generated for TOMORROW, as drafts. They are never
auto-published - the Editor reviews and publishes them.
"""
from __future__ import annotations

import calendar
import datetime as dt
import json

from ..ai import AiClient
from ..ai.prompts import OUTLOOK_SYSTEM
from ..editorial.slugs import unique_slug
from ..lunar import lunar_context
from ..market_data import MarketError, technical_context
from ..models import (
    Outlook, OutlookKind, Provenance, ResearchProtocol, Status, Visibility, utcnow,
)
from .natal import natal_context, transit_calendar

#: Entitlement key reserved for outlooks. Not enforced while the paywall is off.
OUTLOOK_ENTITLEMENT = "outlooks"


def _period_bounds(kind: str, start: dt.date) -> tuple[dt.date, dt.date]:
    if kind == OutlookKind.DAILY:
        return start, start
    if kind == OutlookKind.MONTHLY:
        first = start.replace(day=1)
        return first, first.replace(day=calendar.monthrange(first.year, first.month)[1])
    if kind == OutlookKind.YEARLY:
        return dt.date(start.year, 1, 1), dt.date(start.year, 12, 31)
    return start, start


def gather_outlook_context(period_start: dt.date, kind: str) -> dict:
    """Deterministic context for the outlook. No AI call."""
    noon = dt.datetime.combine(period_start, dt.time(12, 0))
    ctx: dict = {"kind": kind, "period_start": period_start.isoformat()}

    try:
        ctx["technical"] = technical_context()
    except MarketError as exc:
        ctx["technical"] = {"error": str(exc)}

    ctx["lunar"] = lunar_context(noon).to_dict()
    ctx["natal"] = natal_context(period_start, top_n=6)

    if kind == OutlookKind.DAILY:
        ctx["transits_ahead"] = transit_calendar(period_start, days=3)
    elif kind == OutlookKind.MONTHLY:
        ctx["transits_ahead"] = transit_calendar(period_start, days=31, top_n=2, min_weight=1.2)
    else:
        ctx["transits_ahead"] = transit_calendar(period_start, days=365, top_n=1, min_weight=1.5)
    return ctx


def _deterministic_outlook_body(ctx: dict, protocol_note: str = "") -> tuple[str, str]:
    """(summary, markdown body) built with no AI call."""
    tech = ctx.get("technical") or {}
    lunar = ctx.get("lunar") or {}
    natal = ctx.get("natal") or {}
    out: list[str] = []

    if tech.get("error"):
        summary = "Market data was unavailable when this outlook was generated."
        out.append(f"*Market data unavailable: {tech['error']}*")
    else:
        summary = (
            f"BTC is at ${tech['price']:,.0f} in a {tech['regime']} with RSI "
            f"{tech['rsi14']}. The Moon is {lunar.get('phase_name','')} "
            f"({lunar.get('illumination_pct')}% illuminated), "
            f"{lunar.get('days_since_full_moon')} days past the last Full Moon."
        )

    out.append("## Where the market actually is")
    if not tech.get("error"):
        out.append(
            f"[FACT] BTC last traded at ${tech['price']:,.0f}, "
            f"{tech['change_24h_pct']:+.2f}% over 24 hours and "
            f"{tech['change_7d_pct']:+.2f}% over seven days. "
            f"The 50-day mean sits at ${tech['ma50']:,.0f} and the 200-day at "
            f"${tech['ma200']:,.0f}, putting price {tech['pct_from_ath']:+.1f}% from "
            f"the all-time high."
        )
        out.append(f"[TECHNICAL] Structure reads as {tech['regime']}. "
                   f"RSI(14) is {tech['rsi14']}; 30-day annualised volatility is "
                   f"{tech['annualised_volatility_30d_pct']}%. Technical analysis is "
                   f"probabilistic, not predictive.")
        if tech.get("support"):
            out.append("[TECHNICAL] Observable support: "
                       + ", ".join(f"${v:,.0f}" for v in tech["support"]) + ".")
        if tech.get("resistance"):
            out.append("[TECHNICAL] Observable resistance: "
                       + ", ".join(f"${v:,.0f}" for v in tech["resistance"]) + ".")

    out.append("\n## Lunar position")
    out.append(
        f"[LUNAR] {lunar.get('phase_name')}, {lunar.get('illumination_pct')}% illuminated, "
        f"day {lunar.get('age_days')} of the synodic cycle. "
        f"{lunar.get('days_since_full_moon')} days since the last Full Moon and "
        f"{lunar.get('days_since_new_moon')} days since the last New Moon. "
        f"The next Full Moon is in {lunar.get('days_to_next_full_moon')} days."
    )
    out.append(
        "[LUNAR] Across 2017-2026 roughly 70% of matched major highs fell after the "
        "Full Moon, mean about +3.2 days. That is a weak, regime-dependent skew on a "
        "small sample, and phase-shift controls weaken any causal reading of it."
    )

    if protocol_note:
        out.append(f"\n## Frozen experiment window\n{protocol_note}")

    out.append("\n## Natal transits")
    if natal.get("notable_transits"):
        for t in natal["notable_transits"][:5]:
            out.append(
                f"- [ASTRO] {t['label']} — orb {t['orb_deg']}°, "
                f"{'applying' if t['is_applying'] else 'separating'}."
            )
        out.append(
            "\n[ASTRO] These are recorded in advance so the interpretation can be "
            "checked afterwards. Astrology has no established causal mechanism in "
            "financial markets and is reported alongside the price structure above, "
            "never instead of it."
        )
    else:
        out.append("- [ASTRO] No transits within orb for this period.")

    out.append("\n## What would support the thesis, and what would weaken it")
    if not tech.get("error"):
        sup = tech.get("support") or []
        res = tech.get("resistance") or []
        if res:
            out.append(f"- **Supporting:** a daily close above ${res[0]:,.0f} would "
                       f"confirm the constructive reading.")
        if sup:
            out.append(f"- **Weakening:** a daily close below ${sup[0]:,.0f} would "
                       f"invalidate it.")
        out.append(
            "- **Neutral:** ranging between those levels leaves the period inconclusive, "
            "which is a legitimate outcome and will be recorded as one."
        )
    return summary, "\n\n".join(out)


def _protocol_note(session, period_start: dt.date) -> str:
    notes = []
    when = dt.datetime.combine(period_start, dt.time(12, 0))
    for proto in session.query(ResearchProtocol).filter(
        ResearchProtocol.is_frozen.is_(True),
        ResearchProtocol.status != Status.ARCHIVED,
    ).all():
        if proto.window_start and proto.window_end and proto.window_start <= when <= proto.window_end:
            notes.append(
                f"[FACT] The frozen protocol **{proto.title}** (v{proto.version}) is "
                f"inside its live window ({proto.window_start.date()} to "
                f"{proto.window_end.date()}). Its rules were registered in advance and "
                f"cannot be changed in response to what happens."
            )
    return "\n\n".join(notes)


def build_outlook(
    session, period_start: dt.date, kind: str = OutlookKind.DAILY,
    use_ai: bool = True,
) -> Outlook:
    """Create (or return the existing) DRAFT outlook for a period."""
    start, end = _period_bounds(kind, period_start)
    existing = (
        session.query(Outlook)
        .filter_by(kind=kind, period_start=start)
        .one_or_none()
    )
    if existing:
        return existing

    ctx = gather_outlook_context(start, kind)
    proto_note = _protocol_note(session, start)
    summary, body = _deterministic_outlook_body(ctx, proto_note)

    label = {
        OutlookKind.DAILY: start.strftime("BTC Outlook for %-d %B %Y"),
        OutlookKind.MONTHLY: start.strftime("BTC Outlook for %B %Y"),
        OutlookKind.YEARLY: start.strftime("BTC Outlook for %Y"),
    }.get(kind, f"BTC Outlook {start.isoformat()}")

    outlook = Outlook(
        slug=unique_slug(session, Outlook, label),
        kind=kind, period_start=start, period_end=end,
        title=label, summary=summary, body_markdown=body,
        natal_context_json=json.dumps(ctx.get("natal", {}), default=str),
        lunar_context_json=json.dumps(ctx.get("lunar", {}), default=str),
        technical_context_json=json.dumps(ctx.get("technical", {}), default=str),
        events_json=json.dumps(ctx.get("transits_ahead", []), default=str),
        levels_json=json.dumps(
            {"support": (ctx.get("technical") or {}).get("support", []),
             "resistance": (ctx.get("technical") or {}).get("resistance", [])}
        ),
        status=Status.DRAFT, visibility=Visibility.PRIVATE,
        provenance=Provenance.AUTOMATED_RESEARCH,
        required_entitlement=OUTLOOK_ENTITLEMENT,
        meta_description=summary[:320],
    )
    session.add(outlook)
    session.flush()

    if use_ai:
        task = {
            OutlookKind.DAILY: "outlook_daily",
            OutlookKind.MONTHLY: "outlook_monthly",
            OutlookKind.YEARLY: "outlook_yearly",
        }.get(kind, "outlook_daily")
        resp = AiClient(session).complete(
            task=task, system=OUTLOOK_SYSTEM,
            user=(
                f"Draft the {kind} outlook for {start.isoformat()}"
                + (f" to {end.isoformat()}" if end != start else "")
                + ".\n\nDETERMINISTIC CONTEXT (JSON - do not contradict it, do not "
                "invent figures that are not here):\n\n"
                + json.dumps(ctx, indent=2, default=str)
                + "\n\nA deterministic draft follows. Keep every factual claim "
                "identical; improve the prose and the ordering.\n\n" + body
            ),
            outlook_id=outlook.id,
        )
        if resp.ok and resp.text.strip():
            outlook.body_markdown = resp.text
            outlook.ai_generated = True
            outlook.ai_model = resp.model
            outlook.estimated_cost_usd = resp.estimated_cost_usd
        session.flush()
    return outlook
