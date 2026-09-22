"""Structured record proposals parsed out of a Companion reply.

Previously the Companion wrote prose and the Editor retyped the title, body and
criteria into the promote form by hand. The content was already there; only its
shape was wrong.

Now the model is asked to append a fenced ```record block of JSON whenever it has
drafted something publishable. This module extracts those blocks so the UI can
render a filled-in card with one-click "Create as Observation / Prediction /
Experiment" buttons.

The JSON is model output, so it is treated as untrusted: every field is coerced
to a string, length-capped, and unknown keys are dropped. A malformed block is
skipped rather than raising - a bad proposal must never break the chat, because
the prose answer above it is still useful.

Creating a record from a proposal still produces a DRAFT and still requires the
Editor to click. Nothing here publishes anything.
"""
from __future__ import annotations

import json
import re
from dataclasses import dataclass, field

#: ```record  { ... }  ```   (the language tag may be "record" or "record json")
_BLOCK = re.compile(
    r"```record(?:\s+json)?\s*\n(.*?)\n```",
    re.S | re.I,
)

#: Record types the Editor may create in one click. These map onto the existing
#: promote actions, so no new editorial path is introduced.
KINDS = ("observation", "hypothesis", "prediction", "experiment", "article")

#: Field -> max length. Anything longer is truncated rather than rejected.
FIELDS = {
    "title": 255,
    "body": 20000,
    "test_criteria": 2000,
    "invalidation_criteria": 2000,
    "confidence": 200,
    "rationale": 4000,
    "summary": 1000,
}


@dataclass
class Proposal:
    """One record the Companion has drafted, ready for a single click."""

    kind: str
    title: str
    body: str = ""
    test_criteria: str = ""
    invalidation_criteria: str = ""
    confidence: str = ""
    rationale: str = ""
    summary: str = ""
    #: Index within the message, used to build stable form field names.
    index: int = 0
    warnings: list[str] = field(default_factory=list)

    @property
    def is_complete(self) -> bool:
        """A prediction without objective criteria is not publishable."""
        if self.kind == "prediction":
            return bool(self.title and self.body and self.test_criteria)
        return bool(self.title)

    def to_dict(self) -> dict:
        return {
            "kind": self.kind, "title": self.title, "body": self.body,
            "test_criteria": self.test_criteria,
            "invalidation_criteria": self.invalidation_criteria,
            "confidence": self.confidence, "rationale": self.rationale,
            "summary": self.summary, "index": self.index,
            "warnings": list(self.warnings),
        }


def _clean(value, limit: int) -> str:
    if value is None:
        return ""
    if isinstance(value, (list, tuple)):
        value = "\n".join(str(v) for v in value)
    elif not isinstance(value, str):
        value = str(value)
    return value.strip()[:limit]


def _coerce(raw: dict, index: int) -> Proposal | None:
    kind = _clean(raw.get("kind") or raw.get("type"), 40).lower()
    if kind not in KINDS:
        return None
    title = _clean(raw.get("title"), FIELDS["title"])
    if not title:
        return None

    proposal = Proposal(
        kind=kind,
        title=title,
        body=_clean(raw.get("body") or raw.get("prediction_text"), FIELDS["body"]),
        test_criteria=_clean(raw.get("test_criteria"), FIELDS["test_criteria"]),
        invalidation_criteria=_clean(
            raw.get("invalidation_criteria"), FIELDS["invalidation_criteria"]
        ),
        confidence=_clean(raw.get("confidence"), FIELDS["confidence"]),
        rationale=_clean(raw.get("rationale"), FIELDS["rationale"]),
        summary=_clean(raw.get("summary"), FIELDS["summary"]),
        index=index,
    )
    if proposal.kind == "prediction" and not proposal.test_criteria:
        proposal.warnings.append(
            "No objective test criteria - a prediction cannot be published without them."
        )
    if not proposal.body:
        proposal.warnings.append("Body is empty; add the detail before publishing.")
    return proposal


def extract_proposals(content: str) -> list[Proposal]:
    """Every well-formed ```record block in an assistant message."""
    if not content:
        return []
    out: list[Proposal] = []
    for raw_block in _BLOCK.findall(content):
        try:
            parsed = json.loads(raw_block)
        except (ValueError, TypeError):
            continue
        items = parsed if isinstance(parsed, list) else [parsed]
        for item in items:
            if not isinstance(item, dict):
                continue
            proposal = _coerce(item, index=len(out))
            if proposal:
                out.append(proposal)
    return out


def strip_proposal_blocks(content: str) -> str:
    """The message with the raw JSON removed, for display.

    The Editor sees the rendered cards instead; showing both is noise.
    """
    return _BLOCK.sub("", content or "").strip()
