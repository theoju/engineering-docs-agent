# tests/orchestrator/test_dispatch_quote_repair.py
"""CCE-189: an unescaped quote inside a string value must not blind a run.

## What this closes

CCE-187 shipped tier 2 of the parse ladder — tolerance for raw control
characters — and explicitly left the other half of the same production fault
open, on the stated grounds that "rebalancing quotes inside string values can
silently change content".

That reasoning holds for a repair that rebalances or deletes. It does not hold
for the rule ``_repair_unescaped_quotes`` actually applies. In valid JSON a
string's closing quote is always followed, past whitespace, by one of
``, } ] :`` or end-of-input. A quote inside a string followed by anything else
CANNOT be a terminator — there is no competing valid parse to choose wrongly
between — and escaping it only ever INSERTS a backslash, so no original
character is lost.

## The two properties that matter

1. **It recovers the real payload, with content intact.** Asserted against the
   committed production bytes, checking the offending passage survives with its
   real quotes rather than just that a dict came back.
2. **It never returns a WRONG dict.** The rule has a residual: an interior
   quote that happens to be followed by a structural token is indistinguishable
   from a terminator. Those cases must fail closed, returning None exactly as
   before tier 4 existed. A silently mis-parsed payload would be far worse than
   a blind run, because a blind run is loud.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent.parent / "scripts"))

import orchestrator_runner as runner  # noqa: E402

FIXTURE = (
    Path(__file__).parent
    / "fixtures"
    / "cce187_invalid_escaping_source_collector.json"
)


def _production_payload() -> str:
    """The CCE-75 source-collector record, lifted byte-for-byte from run
    36080301431. Carries BOTH faults: 6 raw U+000A and an unescaped quote."""
    return FIXTURE.read_text()


# ---------------------------------------------------------------- the real bytes


def test_the_fixture_still_carries_both_faults():
    """Guard the guard: if the fixture is ever normalised, every assertion in
    this module becomes vacuous while still passing."""
    raw = _production_payload()
    assert sum(1 for c in raw if ord(c) < 0x20) == 6, "control-char fault gone"
    with_tolerance_only = None
    try:
        with_tolerance_only = json.loads(raw, strict=False)
    except json.JSONDecodeError:
        pass
    assert with_tolerance_only is None, (
        "the quote fault is gone — strict=False alone now parses it, so this "
        "module no longer tests the repair"
    )


def test_production_payload_parses_and_preserves_the_offending_passage():
    """The headline case, asserted on content rather than on truthiness."""
    reasons: list[str] = []
    parsed = runner._parse_agent_payload(
        _production_payload(), "source-collector", reasons
    )

    assert reasons == ["unescaped_quotes_repaired: source-collector"]
    description = parsed["jira_issues"][0]["description"]
    assert 'as "explicitly mentioned"' in description, (
        "the repair must insert a backslash, not drop or move the quotes"
    )


def test_production_payload_keeps_its_raw_newlines_too():
    """Tier 4 retries through the strict=False loader, so the control-character
    half of the same value must survive the repair rather than being lost."""
    parsed = runner._parse_agent_payload(_production_payload(), "source-collector", None)
    assert parsed["jira_issues"][0]["description"].count("\n") == 12


# ------------------------------------------------------- never a wrong answer


def test_interior_quote_followed_by_comma_fails_closed():
    """The documented residual. ``"he said "hi", bye"`` — the quote after `hi`
    is followed by a comma, so the rule cannot tell it from a terminator.

    This MUST return None. Returning a truncated-but-plausible dict would be
    the silent-corruption failure the repair is designed never to produce.
    """
    reasons: list[str] = []
    assert runner._parse_agent_payload('{"d": "he said "hi", bye"}', "t", reasons) is None
    assert reasons == [], "a total parse failure records no repair reason"


def test_interior_quote_followed_by_colon_fails_closed():
    """The same residual via `:`, which is in the structural set because a
    key's terminator is always followed by it. That necessity is what creates
    the hole; it is accepted, not overlooked."""
    reasons: list[str] = []
    assert runner._parse_agent_payload('{"d": "see "key": v here"}', "t", reasons) is None
    assert reasons == []


# ------------------------------------------------------------- no false positives


def test_clean_payload_is_untouched_and_silent():
    reasons: list[str] = []
    assert runner._parse_agent_payload('{"a": 1}', "t", reasons) == {"a": 1}
    assert reasons == []


def test_already_escaped_quotes_are_not_double_escaped():
    """A correct `\\"` must not be rewritten into `\\\\"`."""
    reasons: list[str] = []
    parsed = runner._parse_agent_payload('{"d": "he said \\"hi\\" ok"}', "t", reasons)
    assert parsed == {"d": 'he said "hi" ok'}
    assert reasons == [], "valid input must never reach the repair tier"


def test_key_terminators_survive():
    """Every key's closing quote is followed by `:`. If `:` were dropped from
    the structural set, this payload would be mangled beyond recovery."""
    reasons: list[str] = []
    assert runner._parse_agent_payload('{"key": "val"}', "t", reasons) == {"key": "val"}
    assert reasons == []


def test_repair_helper_returns_none_when_nothing_changed():
    """The helper signals 'no repair needed' with None so the caller can tell a
    no-op from a rewrite."""
    assert runner._repair_unescaped_quotes('{"a": "b"}') is None
    assert runner._repair_unescaped_quotes('{"a": "b "c" d"}') is not None


# --------------------------------------------------------------- tier ordering


def test_control_char_only_payload_still_credits_tier_2_not_the_repair():
    """Ordering is the contract. A payload with ONLY a raw newline must be
    handled non-destructively by tier 2; crediting the repair would mean the
    bytes were rewritten when they did not need to be."""
    reasons: list[str] = []
    parsed = runner._parse_agent_payload('{"d": "line1\nline2"}', "t", reasons)
    assert parsed == {"d": "line1\nline2"}
    assert reasons == ["control_chars_tolerated: t"]


def test_prose_only_payload_still_credits_the_prose_rescue():
    reasons: list[str] = []
    parsed = runner._parse_agent_payload('Sure!\n{"a": 1}', "t", reasons)
    assert parsed == {"a": 1}
    assert reasons == ["prose_contamination_rescued: t"]


def test_prose_plus_bad_quote_reports_both_classes():
    """Both faults are real on this branch and the operator should see both.
    Reporting only the repair would hide that the agent also emitted prose."""
    reasons: list[str] = []
    parsed = runner._parse_agent_payload('Sure!\n{"d": "as "q" done"}', "t", reasons)
    assert parsed == {"d": 'as "q" done'}
    assert reasons == [
        "unescaped_quotes_repaired: t",
        "prose_contamination_rescued: t",
    ]


def test_control_chars_plus_bad_quote_is_recovered():
    """The production shape, minimised: both faults in one value."""
    reasons: list[str] = []
    parsed = runner._parse_agent_payload('{"d": "line1\nline2 as "q" x"}', "t", reasons)
    assert parsed == {"d": 'line1\nline2 as "q" x'}
    assert reasons == ["unescaped_quotes_repaired: t"]


def test_repair_accepts_none_out_reasons():
    """dispatch_subagent may pass None; the tier must not crash on it."""
    assert runner._parse_agent_payload('{"d": "as "q" x"}', "t", None) == {
        "d": 'as "q" x'
    }
