"""Model price table, in USD per 1,000,000 tokens.

Prices change; this table is the single place to correct them, and it can be
overridden at runtime without a deploy via the ``ai_pricing_overrides`` app
setting (JSON: {"model": {"input": 0.15, "output": 0.60, "cached_input": 0.075}}).

An unknown model falls back to FALLBACK_PRICING and is flagged, so an unpriced
model can never silently report a $0.00 spend.
"""
from __future__ import annotations

import json

#: USD per 1M tokens.
PRICING: dict[str, dict[str, float]] = {
    "gpt-4o-mini":      {"input": 0.15,  "output": 0.60,  "cached_input": 0.075},
    "gpt-4o":           {"input": 2.50,  "output": 10.00, "cached_input": 1.25},
    "gpt-4.1":          {"input": 2.00,  "output": 8.00,  "cached_input": 0.50},
    "gpt-4.1-mini":     {"input": 0.40,  "output": 1.60,  "cached_input": 0.10},
    "gpt-4.1-nano":     {"input": 0.10,  "output": 0.40,  "cached_input": 0.025},
    "o3-mini":          {"input": 1.10,  "output": 4.40,  "cached_input": 0.55},
    "o4-mini":          {"input": 1.10,  "output": 4.40,  "cached_input": 0.275},
}

#: Deliberately pessimistic, so an unknown model over- rather than under-reports.
FALLBACK_PRICING = {"input": 3.00, "output": 12.00, "cached_input": 1.50}


def pricing_for(model: str, overrides: dict | None = None) -> tuple[dict, bool]:
    """(price dict, is_known). ``is_known`` is False when falling back."""
    if overrides and model in overrides:
        return {**FALLBACK_PRICING, **overrides[model]}, True
    if model in PRICING:
        return PRICING[model], True
    # Tolerate dated snapshot ids like "gpt-4o-mini-2024-07-18".
    for known, price in PRICING.items():
        if model.startswith(known):
            return price, True
    return FALLBACK_PRICING, False


def estimate_cost(
    model: str,
    input_tokens: int,
    output_tokens: int,
    cached_input_tokens: int = 0,
    overrides: dict | None = None,
) -> tuple[float, bool]:
    """Estimated USD cost for one call, plus whether the model was priced."""
    price, known = pricing_for(model, overrides)
    fresh_input = max(0, input_tokens - cached_input_tokens)
    cost = (
        fresh_input * price["input"]
        + cached_input_tokens * price.get("cached_input", price["input"])
        + output_tokens * price["output"]
    ) / 1_000_000.0
    return round(cost, 6), known


def load_overrides(session) -> dict:
    from ..models import AppSetting

    row = session.query(AppSetting).filter_by(key="ai_pricing_overrides").one_or_none()
    if not row or not row.value.strip():
        return {}
    try:
        return json.loads(row.value)
    except json.JSONDecodeError:
        return {}
