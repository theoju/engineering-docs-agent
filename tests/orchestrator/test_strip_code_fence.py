"""CCE-55: _strip_code_fence — normalize the markdown code-fence wrap
the LLM emits ~19% of the time despite explicit "no fences" instructions.

Whole-string match only. Any contamination that isn't exactly a fence
wrap falls through to _rescue_json_object unchanged.
"""

from __future__ import annotations
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent.parent / "scripts"))
import orchestrator_runner as runner  # noqa: E402


def test_strip_unwraps_json_lang_fence():
    """The most common observed case: ```json\\n<obj>\\n```."""
    text = '```json\n{"a": 1}\n```'
    assert runner._strip_code_fence(text) == '{"a": 1}'


def test_strip_unwraps_no_lang_fence():
    """No language tag — bare triple-backtick fence."""
    text = '```\n{"a": 1}\n```'
    assert runner._strip_code_fence(text) == '{"a": 1}'


def test_strip_unwraps_trailing_whitespace():
    """Trailing newlines/spaces after the closing fence — common in
    LLM output that adds a final newline.
    """
    text = '```json\n{"a": 1}\n```\n\n  '
    assert runner._strip_code_fence(text) == '{"a": 1}'


def test_strip_unwraps_leading_whitespace():
    """Leading whitespace before the opening fence."""
    text = '\n  ```json\n{"a": 1}\n```'
    assert runner._strip_code_fence(text) == '{"a": 1}'


def test_strip_preserves_clean_json():
    """Already-clean JSON is returned unchanged (pure pass-through)."""
    text = '{"a": 1, "b": [2, 3]}'
    assert runner._strip_code_fence(text) == text


def test_strip_does_not_match_prose_around_fence():
    """Prose before OR after the fence breaks the whole-string match.
    These cases fall through to _rescue_json_object as anomalous
    contamination (and still emit prose_contamination_rescued).
    """
    text_prefix = 'preamble\n```json\n{"a": 1}\n```'
    assert runner._strip_code_fence(text_prefix) == text_prefix
    text_suffix = '```json\n{"a": 1}\n```\nepilogue'
    assert runner._strip_code_fence(text_suffix) == text_suffix


def test_strip_does_not_match_mid_string_backticks():
    """Stray backticks inside a string literal aren't a fence wrap."""
    text = '{"note": "see `code` block"}'
    assert runner._strip_code_fence(text) == text


def test_strip_real_pr69_fixture_round_trips_to_valid_pr_summarizer_json():
    """Integration check: the actual fence-wrapped output captured from
    PR #69's forensics strips cleanly AND the result is valid JSON
    matching the pr-summarizer schema's required top-level keys.
    """
    fixture = (
        Path(__file__).parent.parent
        / "fixtures"
        / "cce55"
        / "pr_summarizer_fence_wrap.stdout.txt"
    )
    raw = fixture.read_text()
    stripped = runner._strip_code_fence(raw)
    assert stripped != raw, "strip should have removed the fence wrap"
    parsed = json.loads(stripped)
    assert "pr_number" in parsed
    assert "doc_targets" in parsed
