"""The Companion checks the Editor's claims, and drafts records it can act on.

Two behaviours are covered:

1. ``reconcile`` catches an unambiguous contradiction between what the Editor
   wrote and what the ephemeris says, and stays silent otherwise. A false
   positive is the worse failure - it trains the Editor to ignore the queries -
   so the silence cases are tested as carefully as the catches.

2. ``extract_proposals`` turns a model's ```record blocks into one-click drafts,
   treating the JSON as untrusted input.
"""
from __future__ import annotations

import datetime as dt

import pytest

from btcmoon.admin.proposals import (
    FIELDS, extract_proposals, strip_proposal_blocks,
)
from btcmoon.admin.reconcile import reconcile, render_for_prompt
from btcmoon.lunar import lunar_context

#: A moment with a Full Moon 3 days out and the New Moon a fortnight later, so
#: "the coming new moon" is unambiguously wrong.
BEFORE_FULL = dt.datetime(2026, 8, 25, 12, 0)


@pytest.fixture(scope="module")
def ctx():
    c = lunar_context(BEFORE_FULL)
    assert c.next_full_moon < c.next_new_moon, "fixture assumption broken"
    return c


# ---------------------------------------------------------------------------
# 1. Catching the Editor's slips
# ---------------------------------------------------------------------------
def test_catches_wrong_phase_for_the_next_event(ctx):
    found = reconcile("Let's set up an experiment for the coming new moon.", ctx)
    assert len(found) == 1
    d = found[0]
    assert d.kind == "phase_mismatch"
    assert "full moon" in d.question.lower()
    assert "did you mean" in d.question.lower()


@pytest.mark.parametrize("text", [
    "Let's set up an experiment for the coming full moon.",
    "What does the next full moon window look like?",
    "The new moon test used NM+0.4 as the informal idea.",
    "How did the August full moon resolve versus FM+4.4?",
    "",
    "   ",
])
def test_stays_silent_when_the_editor_is_right(ctx, text):
    assert reconcile(text, ctx) == []


def test_catches_an_offset_labelled_against_the_wrong_phase(ctx):
    found = reconcile(
        "in augusts full moon we expected nm+4.4 but it was actually nm+5", ctx
    )
    kinds = [d.kind for d in found]
    assert "offset_label" in kinds
    d = next(d for d in found if d.kind == "offset_label")
    assert "FM+4.4" in d.question


def test_offset_check_ignores_messages_naming_both_phases(ctx):
    """With both phases present the intended one is ambiguous, so do not guess."""
    text = "Compare the full moon highs against the new moon lows using NM+0.4."
    assert [d for d in reconcile(text, ctx) if d.kind == "offset_label"] == []


def test_only_one_phase_question_per_turn(ctx):
    text = ("the coming new moon matters, and the coming new moon window "
            "overlaps the coming new moon test")
    assert sum(1 for d in reconcile(text, ctx) if d.kind == "phase_mismatch") == 1


def test_prompt_block_instructs_the_model_to_ask_first(ctx):
    found = reconcile("plan for the coming new moon", ctx)
    block = render_for_prompt(found)
    assert "DISCREPANCIES DETECTED" in block
    assert "MUST" in block
    assert found[0].question in block


def test_prompt_block_is_empty_when_nothing_is_wrong():
    assert render_for_prompt([]) == ""


# ---------------------------------------------------------------------------
# 2. Turning a reply into one-click drafts
# ---------------------------------------------------------------------------
GOOD_REPLY = """Here is the record.

```record
{
  "kind": "experiment",
  "title": "August 2026 Full-Moon high timing test",
  "body": "[PREDICTION] A strict local high forms within FM+0 to FM+6.",
  "test_criteria": "Daily HIGH strictly above the 3 bars either side.",
  "invalidation_criteria": "No qualifying high by FM+7.",
  "confidence": "Low."
}
```
"""


def test_extracts_a_complete_proposal():
    (p,) = extract_proposals(GOOD_REPLY)
    assert p.kind == "experiment"
    assert p.title == "August 2026 Full-Moon high timing test"
    assert p.test_criteria.startswith("Daily HIGH")
    assert p.is_complete
    assert p.warnings == []


def test_prediction_without_criteria_is_flagged_not_dropped():
    (p,) = extract_proposals(
        '```record\n{"kind":"prediction","title":"T","body":"B"}\n```'
    )
    assert not p.is_complete
    assert any("test criteria" in w for w in p.warnings)


@pytest.mark.parametrize("block", [
    "```record\n{not json at all}\n```",
    '```record\n{"kind":"nonsense","title":"x"}\n```',   # unknown kind
    '```record\n{"kind":"observation"}\n```',            # no title
    '```record\n["a string", 42]\n```',                  # not objects
    "no fenced block here at all",
    "",
])
def test_malformed_blocks_are_skipped_silently(block):
    assert extract_proposals(block) == []


def test_multiple_proposals_get_distinct_indices():
    reply = (
        '```record\n{"kind":"observation","title":"One"}\n```\n'
        '```record json\n{"kind":"hypothesis","title":"Two"}\n```'
    )
    a, b = extract_proposals(reply)
    assert (a.index, b.index) == (0, 1)
    assert (a.kind, b.kind) == ("observation", "hypothesis")


def test_oversized_fields_are_truncated_not_rejected():
    long_title = "x" * (FIELDS["title"] + 500)
    (p,) = extract_proposals(
        '```record\n{"kind":"observation","title":"%s"}\n```' % long_title
    )
    assert len(p.title) == FIELDS["title"]


def test_non_string_fields_are_coerced():
    (p,) = extract_proposals(
        '```record\n{"kind":"observation","title":"T","body":["a","b"],'
        '"confidence":0.4}\n```'
    )
    assert p.body == "a\nb"
    assert p.confidence == "0.4"


def test_raw_json_is_stripped_from_the_displayed_transcript():
    shown = strip_proposal_blocks(GOOD_REPLY)
    assert "Here is the record." in shown
    assert "```record" not in shown
    assert "test_criteria" not in shown
