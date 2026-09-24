"""CCE-177: pin the detector to the REAL Claude CLI event shape.

Every test in `test_output_token_limit_split.py` builds its own `isSynthetic`
dicts. They agree with each other about a shape that was never checked against
the actual CLI output, so a field rename or a reworded resume prompt would
leave all of them green while `_detect_output_token_limit_split` silently
stopped firing in production. This file closes that: the fixtures are trimmed
captures of three real `docs-agent-nightly` runs, and they are parsed exactly
the way `dispatch_subagent` parses a stream — one `json.loads` per line.

This is the repo's "verify against the actual consumer tool, not `test -f`"
rule applied to a data format: the consumer here is the CLI's event stream,
and a hand-written dict is not it.

The production forensics these were cut from expire ~2026-10-02 (14 days after
each run). See `tests/fixtures/cce177/README.md` for what was dropped and
truncated.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest

_REPO_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(_REPO_ROOT / "scripts"))

import orchestrator_runner as orun  # noqa: E402

FIXTURES = Path(__file__).resolve().parents[1] / "fixtures" / "cce177"

FAIL_MARKER_LAST = "run-35862057776-fail-marker-last.stream.jsonl"
FAIL_MARKER_MIDSTREAM = "run-35343242932-fail-marker-midstream.stream.jsonl"
PASS_NO_MARKER = "run-35727627405-pass-no-marker.stream.jsonl"


def _events(name: str) -> list[dict]:
    """Parse a fixture the way `dispatch_subagent` parses a live stream:
    strip, skip blanks, one `json.loads` per line."""
    out: list[dict] = []
    for line in (FIXTURES / name).read_text().splitlines():
        line = line.strip()
        if not line:
            continue
        out.append(json.loads(line))
    return out


def _assistants_with_text(events: list[dict]) -> int:
    return sum(
        1 for e in events if e.get("type") == "assistant" and orun._has_text_block(e)
    )


def _marker_index(events: list[dict]) -> int | None:
    return next((i for i, e in enumerate(events) if e.get("isSynthetic")), None)


def _tool_use_names_after(events: list[dict], idx: int) -> list[str]:
    """Names of every `tool_use` block in assistant turns after `idx`.

    Shared by the two tests that record where the marker falls relative to
    tool use, so the pair reads as one measurement taken twice — which is
    what it is: the rejected "marker must follow the last tool_use"
    refinement fires on 2 of the 3 failing runs, not 3.
    """
    return [
        b.get("name")
        for e in events[idx + 1 :]
        if e.get("type") == "assistant"
        for b in e["message"]["content"]
        if b.get("type") == "tool_use"
    ]


# --------------------------------------------------------------------------
# The verdict on each real run
# --------------------------------------------------------------------------


@pytest.mark.parametrize(
    "name, expected",
    [
        (FAIL_MARKER_LAST, True),
        (FAIL_MARKER_MIDSTREAM, True),
        (PASS_NO_MARKER, False),
    ],
    ids=["fail_09_23", "fail_09_18", "pass_09_22"],
)
def test_the_detector_agrees_with_the_production_outcome(name: str, expected: bool):
    """Two nights that failed, one that passed, judged from their own
    streams. If the CLI renames `isSynthetic`, moves it under `message`, or
    rewords the resume prompt, this is where it shows up."""
    assert orun._detect_output_token_limit_split(_events(name)) is expected


# --------------------------------------------------------------------------
# The shape itself — field names, nesting, block types
# --------------------------------------------------------------------------


@pytest.mark.parametrize(
    "name", [FAIL_MARKER_LAST, FAIL_MARKER_MIDSTREAM], ids=["fail_09_23", "fail_09_18"]
)
def test_the_real_synthetic_turn_has_the_shape_the_detector_reads(name: str):
    """Each field the detector touches, asserted against production bytes.

    `isSynthetic` is a TOP-LEVEL key on the event, not a member of `message`
    — the single most likely thing to be assumed wrongly from the synthetic
    fixtures, and the reason this test exists.
    """
    events = _events(name)
    idx = _marker_index(events)
    assert idx is not None, "no synthetic turn in a stream that had one"
    ev = events[idx]

    assert ev["type"] == "user"
    assert ev["isSynthetic"] is True
    assert "isSynthetic" not in ev["message"]
    assert ev["message"]["role"] == "user"
    assert isinstance(ev["message"]["content"], list)
    assert ev["message"]["content"][0]["type"] == "text"


@pytest.mark.parametrize(
    "name", [FAIL_MARKER_LAST, FAIL_MARKER_MIDSTREAM], ids=["fail_09_23", "fail_09_18"]
)
def test_the_real_resume_prompt_still_starts_with_the_matched_prefix(name: str):
    """`_OUTPUT_TOKEN_LIMIT_PREFIX` is matched against the CLI's own wording.

    Kept verbatim in the fixtures (it is 183 characters) precisely so a
    reworded prompt fails here rather than in production. The detector
    lowercases and strips before comparing, so this mirrors that.
    """
    events = _events(name)
    ev = events[_marker_index(events)]
    text = orun._message_text(ev).strip()

    assert text.lower().startswith(orun._OUTPUT_TOKEN_LIMIT_PREFIX)
    assert text.startswith("Output token limit hit."), text[:60]
    assert len(text) == 183, f"the marker was trimmed; it must be verbatim: {len(text)}"


def test_the_real_assistant_turns_carry_text_in_the_block_shape_has_text_block_reads():
    """`_has_text_block` looks for `message.content[].type == "text"`. That
    nesting is asserted here against real events rather than assumed."""
    events = _events(FAIL_MARKER_LAST)
    texts = [
        b
        for e in events
        if e.get("type") == "assistant"
        for b in e["message"]["content"]
        if b.get("type") == "text"
    ]
    assert texts, "no text blocks at all in a real assistant stream"
    assert all(isinstance(b["text"], str) for b in texts)
    assert _assistants_with_text(events) > 1


def test_the_streams_carry_event_types_the_detector_must_walk_past():
    """A real stream is not just assistant/user turns. `system`,
    `rate_limit_event` and `result` events are interleaved, and the detector
    iterates all of them."""
    kinds = {e.get("type") for e in _events(FAIL_MARKER_LAST)}
    assert {"system", "assistant", "user", "result"} <= kinds
    assert "rate_limit_event" in kinds


# --------------------------------------------------------------------------
# What the negative control actually controls for
# --------------------------------------------------------------------------


def test_the_passing_run_has_no_synthetic_turn_of_any_kind():
    events = _events(PASS_NO_MARKER)
    assert _marker_index(events) is None
    assert not any("isSynthetic" in e for e in events)


def test_the_passing_run_also_has_more_than_one_assistant_turn_with_text():
    """The negative control is a control, not a degenerate case.

    It would prove nothing if it were False merely for want of a second text
    turn. It has three, so condition 2 is satisfied and the marker's absence
    is the only thing separating it from the two failures — which is also the
    measured finding recorded in the spec: condition 2 is TRUE on all seven
    runs measured and discriminates nothing.
    """
    events = _events(PASS_NO_MARKER)
    assert _assistants_with_text(events) > 1
    assert orun._detect_output_token_limit_split(events) is False


# --------------------------------------------------------------------------
# The rejected refinement, pinned by the run that falsifies it
# --------------------------------------------------------------------------


def test_the_09_18_marker_is_followed_by_real_tool_use_blocks():
    """Why "the marker must come after the last `tool_use`" was rejected.

    The proposal was that a ceiling hit mid-conversation is benign — the
    agent resumes and still emits a complete answer — so only a marker after
    the final tool call should count. On run 35343242932 the marker is
    followed by four more `tool_use` blocks, so that predicate would have
    ACCEPTED a night whose `prs` array was entirely in the discarded head
    half. Accepting it advances the watermark past 15 PRs the run never
    documented: the CCE-151 harm this change exists to prevent.

    If someone adds that condition, this test goes red and the spec's
    "Measured findings" subsection says why.
    """
    events = _events(FAIL_MARKER_MIDSTREAM)
    after = _tool_use_names_after(events, _marker_index(events))
    assert len(after) == 4, after
    assert set(after) == {"Bash", "Read"}
    assert orun._detect_output_token_limit_split(events) is True


def test_the_09_23_marker_has_no_tool_use_after_it():
    """The contrasting real shape: on 09-23 the marker sits between the final
    two text-carrying turns. Recorded so the pair reads as a measurement —
    the refinement fires on 2 of 3 failing runs, not 3."""
    events = _events(FAIL_MARKER_LAST)
    after = _tool_use_names_after(events, _marker_index(events))
    assert after == []


# --------------------------------------------------------------------------
# Fixture hygiene
# --------------------------------------------------------------------------


def test_every_fixture_line_parses_and_the_files_stay_small():
    """A captured fixture that grows back toward its 0.6–1.2 MB original has
    stopped being a fixture. Also proves no line was corrupted by trimming."""
    for name in (FAIL_MARKER_LAST, FAIL_MARKER_MIDSTREAM, PASS_NO_MARKER):
        path = FIXTURES / name
        events = _events(name)
        assert events, name
        assert all(isinstance(e, dict) for e in events)
        assert path.stat().st_size < 64 * 1024, (
            f"{name} is {path.stat().st_size} bytes; trim it further rather "
            f"than committing a production-sized stream"
        )
