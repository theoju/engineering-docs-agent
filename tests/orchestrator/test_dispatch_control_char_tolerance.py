# tests/orchestrator/test_dispatch_control_char_tolerance.py
"""CCE-187: raw control characters inside a string value must not blind a run.

## What happened

Nightly run 36080301431 (2026-09-25 01:11Z) classified **blind** on
``source_collector_invalid: returned None``. The subagent had succeeded —
returncode 0, empty stderr, 655-byte prompt, 28 tool calls — and its 93,015
bytes of stdout were structurally complete, ending in a properly closed ``}]}``.
It simply would not parse.

``jira_issues[CCE-75].description`` carried **two independent escaping faults**:
six raw ``U+000A`` bytes, and an unescaped ``"`` around
``"explicitly mentioned"``. Full measurement in
``docs/superpowers/specs/2026-09-24-cce187-evidence.md``.

The failure is stochastic, not a property of the content: run 36007491599
collected the same window one day earlier, chose a shorter description for the
same issue, and parsed cleanly. So no amount of self-checked pre-flight in the
agent contract closes this — the contract already bounds ``description`` to
1,000 characters and re-verifies that bound three times, and it was obeyed. The
failing value ends in the mandated truncation marker. Every guard enforced
*bounded*; none enforced *well-formed*.

## What this module pins

JSON's prohibition on raw control characters inside strings is a **wire-format**
rule, not a semantic one. Accepting a real newline where ``\\n`` was meant loses
no information, so the tolerance tier converts a control-character-only
corruption from **blind** to **clean** — for every field of every agent, not
just Jira.

The tier is deliberately narrow. It does **not** attempt to repair an unescaped
quote: ``_rescue_json_object``'s brace-walk desynchronises on a stray quote
(``scripts/orchestrator_runner.py:151-168``), and rebalancing quotes inside
string values can silently alter content. That half of the class stays open for
``prs[].body``/``title`` and is tracked separately — see
``test_the_two_fault_production_payload_still_fails`` below, which pins the
residual so it cannot be mistaken for fixed.

Ordering matters and is asserted: the lenient tier runs **after** a strict parse
and **before** the prose rescue, so a prose-contaminated payload still reports
its own reason rather than being mislabelled as a control-character case.
"""

from __future__ import annotations
import json
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).parent.parent.parent / "scripts"))
import orchestrator_runner as runner  # noqa: E402

FIXTURE = (
    Path(__file__).parent
    / "fixtures"
    / "cce187_invalid_escaping_source_collector.json"
)


def _two_fault_payload() -> str:
    """The production payload, byte-for-byte: raw newlines AND a stray quote."""
    return FIXTURE.read_text(encoding="utf-8")


def _control_char_only_payload() -> str:
    """The same payload with ONLY the quote fault repaired.

    Derived from the committed artifact rather than hand-written, so the raw
    ``U+000A`` bytes and their surrounding prose are the real ones. Repairing
    the quote isolates the fault the tolerance tier is allowed to fix.
    """
    raw = _two_fault_payload()
    repaired = raw.replace('"explicitly mentioned"', '\\"explicitly mentioned\\"')
    assert repaired != raw, "fixture no longer contains the unescaped-quote passage"
    assert sum(1 for c in repaired if ord(c) < 0x20) == 6, (
        "the six raw control characters must survive the quote repair — they "
        "are the fault under test"
    )
    return repaired


def test_the_fixture_is_the_real_two_fault_artifact():
    """Guard the evidence itself: both faults present, neither parser accepts it."""
    raw = _two_fault_payload()
    assert sum(1 for c in raw if ord(c) < 0x20) == 6
    with pytest.raises(json.JSONDecodeError, match="Invalid control character"):
        json.loads(raw)
    with pytest.raises(json.JSONDecodeError, match="Expecting ',' delimiter"):
        json.loads(raw, strict=False)


def test_control_char_only_payload_parses_and_reports_the_tolerance():
    """The tier's whole purpose: blind becomes clean, and says so."""
    reasons: list[str] = []
    parsed = runner._parse_agent_payload(
        _control_char_only_payload(), "source-collector", reasons
    )

    assert parsed is not None, (
        "a payload whose ONLY defect is a raw control character inside a string "
        "must parse — this is the blind-to-clean conversion CCE-187 buys"
    )
    issue = parsed["jira_issues"][0]
    assert issue["key"] == "CCE-75"
    assert "\n" in issue["description"], (
        "the raw newline is preserved as a real newline; nothing is repaired, "
        "only accepted"
    )
    assert reasons == ["control_chars_tolerated: source-collector"], (
        f"expected exactly the tolerance reason, got {reasons}"
    )


def test_the_two_fault_production_payload_still_fails():
    """The documented residual. If this ever passes, the quote half was fixed
    too — which is a real change in scope and must be a deliberate one, not a
    side effect. Re-read the design's §0.2 before touching this assertion.
    """
    reasons: list[str] = []
    assert (
        runner._parse_agent_payload(_two_fault_payload(), "source-collector", reasons)
        is None
    ), (
        "an unescaped quote inside a string value is NOT in scope for the "
        "tolerance tier; repairing it can silently alter content"
    )
    assert reasons == [], "a total parse failure records no tolerance reason"


def test_clean_payload_records_no_reason():
    """No false positives: the tier must be invisible on well-formed output."""
    reasons: list[str] = []
    parsed = runner._parse_agent_payload(
        '{"prs": [], "jira_issues": []}', "source-collector", reasons
    )
    assert parsed == {"prs": [], "jira_issues": []}
    assert reasons == []


def test_fenced_payload_still_strips_without_a_tolerance_reason():
    """CCE-55's fence strip is upstream of the tier and must stay silent."""
    reasons: list[str] = []
    parsed = runner._parse_agent_payload(
        '```json\n{"prs": [], "jira_issues": []}\n```', "source-collector", reasons
    )
    assert parsed == {"prs": [], "jira_issues": []}
    assert reasons == []


def test_prose_contamination_reports_its_own_reason_not_the_tolerance():
    """Ordering assertion: strict -> lenient -> rescue.

    A prose preamble is not a control-character fault. If the lenient tier ran
    last, or if it swallowed this case, the digest would misattribute a known
    contamination class (CCE-14/CCE-15) to a new one.
    """
    reasons: list[str] = []
    contaminated = (
        "`★ Insight ─────`\n"
        "I invoked gh pr list and identified PR #9.\n\n"
        '{"prs": [{"number": 9}], "jira_issues": []}'
    )
    parsed = runner._parse_agent_payload(contaminated, "source-collector", reasons)
    assert parsed == {"prs": [{"number": 9}], "jira_issues": []}
    assert reasons == ["prose_contamination_rescued: source-collector"]


def test_prose_preamble_plus_control_chars_is_still_rescued():
    """Both known contamination classes at once — the rescue's own terminal
    parse must tolerate control characters too, or this combination stays blind.
    """
    reasons: list[str] = []
    contaminated = (
        "some preamble prose\n\n"
        '{"prs": [], "jira_issues": [{"key": "CCE-1", "description": "a\nb"}]}'
    )
    parsed = runner._parse_agent_payload(contaminated, "source-collector", reasons)
    assert parsed is not None, (
        "prose preamble + a raw newline inside a string must still be rescued; "
        "_rescue_json_object's terminal json.loads needs the same tolerance"
    )
    assert parsed["jira_issues"][0]["description"] == "a\nb"
    assert reasons == ["prose_contamination_rescued: source-collector"]


def test_rescue_helper_tolerates_control_chars_directly():
    """Pinned at the helper too, since _rescue_json_object is public surface
    with its own test module (test_dispatch_rescue.py) that predates this.
    """
    assert runner._rescue_json_object('prefix\n{"a": "x\ny"}\nsuffix') == {"a": "x\ny"}


def test_tolerance_accepts_none_out_reasons():
    """dispatch_subagent passes out_reasons=None on some paths; the tier must
    not require a list to do its job.
    """
    assert (
        runner._parse_agent_payload(_control_char_only_payload(), "x", None)
        is not None
    )
