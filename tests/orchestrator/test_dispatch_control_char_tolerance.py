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

The tier is deliberately narrow: it tolerates the control character and nothing
else. The quote half of the class is closed separately by CCE-189's tier 4, and
the two are kept apart on purpose — a control-character-only payload must still
report ``control_chars_tolerated`` and must NOT be rewritten, because tier 2 is
non-destructive and tier 4 is not. ``test_the_two_fault_production_payload_...``
below tracks that boundary; see ``test_dispatch_quote_repair.py`` for the repair
itself.

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


def test_the_two_fault_production_payload_is_now_recovered_by_tier_4_not_tier_2():
    """This assertion was inverted, deliberately, by CCE-189.

    It previously pinned the residual: the two-fault payload returned None and
    recorded nothing. Its docstring said that if it ever passed, the quote half
    had been fixed and that had to be a deliberate scope change rather than a
    side effect. CCE-189 is that deliberate change, so the test now pins the
    new contract instead of being deleted — the point it guards is unchanged.

    What still matters, and is what this now asserts: the payload is recovered
    by the QUOTE REPAIR, not by the control-character tolerance. Tier 2 is
    non-destructive and must not be credited with a byte rewrite. If this
    reason ever reads ``control_chars_tolerated``, the tiers have been
    reordered and tier 2 has silently become destructive.
    """
    reasons: list[str] = []
    parsed = runner._parse_agent_payload(
        _two_fault_payload(), "source-collector", reasons
    )

    assert parsed is not None, "CCE-189 tier 4 must recover the two-fault payload"
    assert reasons == ["unescaped_quotes_repaired: source-collector"], (
        "the repair tier owns this recovery; tier 2 alone cannot parse an "
        f"unescaped quote, got {reasons!r}"
    )
    # The whole point of collecting it: the Jira record survives intact.
    assert [i["key"] for i in parsed["jira_issues"]] == ["CCE-75"]


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
