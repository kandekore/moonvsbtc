"""OpenAI adapter with budget enforcement and graceful degradation.

If ``OPENAI_API_KEY`` is absent, or the budget ceiling has been reached, or the
provider errors, ``complete()`` returns an ``AiResponse`` with ``ok=False`` and
an explanatory ``fallback_reason``. Callers must handle that - the jobs in this
repository all fall back to a deterministic, non-AI briefing so that a missing
credential degrades the output rather than breaking the pipeline.
"""
from __future__ import annotations

import datetime as dt
from dataclasses import dataclass, field

from ..config import Config
from .ledger import BudgetExceeded, BudgetGuard, record_usage

#: Logical task names -> config attribute holding the model for that task.
#: Cheap work must never silently use the expensive model (spec s19).
TASK_MODEL_TIER = {
    "news_classify": "AI_MODEL_CHEAP",
    "news_summarise": "AI_MODEL_CHEAP",
    "briefing_morning": "AI_MODEL_STANDARD",
    "briefing_evening": "AI_MODEL_STANDARD",
    "outlook_daily": "AI_MODEL_STANDARD",
    "outlook_monthly": "AI_MODEL_STRONG",
    "outlook_yearly": "AI_MODEL_STRONG",
    "companion_chat": "AI_MODEL_STANDARD",
    "experiment_analysis": "AI_MODEL_STRONG",
    "article_draft": "AI_MODEL_STRONG",
}


def model_for_task(task: str, session=None) -> str:
    """Resolve the model for a task: app setting first, then env/config tier."""
    if session is not None:
        from ..models import AppSetting

        row = session.query(AppSetting).filter_by(key=f"ai_model_{task}").one_or_none()
        if row and row.value.strip():
            return row.value.strip()
    tier = TASK_MODEL_TIER.get(task, "AI_MODEL_STANDARD")
    return getattr(Config, tier)


@dataclass
class AiResponse:
    ok: bool
    text: str = ""
    model: str = ""
    task: str = ""
    input_tokens: int = 0
    output_tokens: int = 0
    cached_input_tokens: int = 0
    estimated_cost_usd: float = 0.0
    usage_id: int | None = None
    fallback_reason: str = ""
    raw: dict = field(default_factory=dict)


class AiClient:
    """Thin wrapper over the OpenAI SDK.

    Construct with a DB session so usage is always ledgered; without one it
    still works but records nothing (used only in tests).
    """

    def __init__(self, session=None):
        self.session = session
        self._client = None

    # -- availability ----------------------------------------------------
    @property
    def configured(self) -> bool:
        return bool(Config.OPENAI_API_KEY) and Config.AI_ENABLED

    def _get_client(self):
        if self._client is not None:
            return self._client
        from openai import OpenAI

        kwargs = {"api_key": Config.OPENAI_API_KEY}
        if Config.OPENAI_BASE_URL:
            kwargs["base_url"] = Config.OPENAI_BASE_URL
        self._client = OpenAI(**kwargs)
        return self._client

    def availability(self) -> tuple[bool, str]:
        """(can we call the AI, why not)."""
        if not Config.AI_ENABLED:
            return False, "AI generation is disabled by configuration (AI_ENABLED=false)."
        if not Config.OPENAI_API_KEY:
            return False, (
                "OPENAI_API_KEY is not set. The integration is wired up and will "
                "activate as soon as the key is provided; until then briefings, "
                "outlooks and Companion replies fall back to the deterministic "
                "non-AI summary."
            )
        if self.session is not None:
            try:
                BudgetGuard(self.session).check("probe", raise_on_block=True)
            except BudgetExceeded as exc:
                return False, str(exc)
        return True, ""

    # -- the one call everything goes through ----------------------------
    def complete(
        self,
        task: str,
        system: str,
        user: str,
        *,
        model: str | None = None,
        max_output_tokens: int | None = None,
        temperature: float = 0.4,
        **usage_links,
    ) -> AiResponse:
        model = model or model_for_task(task, self.session)
        available, why = self.availability()
        if not available:
            return AiResponse(ok=False, model=model, task=task, fallback_reason=why)

        try:
            client = self._get_client()
            resp = client.chat.completions.create(
                model=model,
                messages=[
                    {"role": "system", "content": system},
                    {"role": "user", "content": user},
                ],
                temperature=temperature,
                max_tokens=max_output_tokens or Config.AI_MAX_OUTPUT_TOKENS,
            )
        except Exception as exc:                  # provider/network/auth failure
            return AiResponse(
                ok=False, model=model, task=task,
                fallback_reason=f"AI provider call failed: {type(exc).__name__}: {exc}",
            )

        text = (resp.choices[0].message.content or "").strip()
        usage = getattr(resp, "usage", None)
        in_tok = int(getattr(usage, "prompt_tokens", 0) or 0)
        out_tok = int(getattr(usage, "completion_tokens", 0) or 0)
        cached = 0
        details = getattr(usage, "prompt_tokens_details", None)
        if details is not None:
            cached = int(getattr(details, "cached_tokens", 0) or 0)

        out = AiResponse(
            ok=True, text=text, model=model, task=task,
            input_tokens=in_tok, output_tokens=out_tok, cached_input_tokens=cached,
        )
        if self.session is not None:
            row = record_usage(
                self.session, model=model, task=task,
                input_tokens=in_tok, output_tokens=out_tok,
                cached_input_tokens=cached,
                cache_status="hit" if cached else "none",
                commit=False, **usage_links,
            )
            out.usage_id = row.id
            out.estimated_cost_usd = row.estimated_cost_usd
        return out
