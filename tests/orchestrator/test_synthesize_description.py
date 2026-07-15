from __future__ import annotations
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent.parent / "scripts"))
import orchestrator_runner as runner  # noqa: E402

_syn = runner._synthesize_agent_description


def test_uses_what_changed_and_clears_min_words():
    out = _syn(
        [{"pr_number": 1, "what_changed": "Adds a foo connector"}],
        hint="connectors/foo.md",
        min_words=6,
    )
    assert len(out.split()) >= 6
    assert not out.endswith(":")


def test_not_equal_to_slug_title():
    # description_quality compares against the page H1 (`# {hint}`), parsed to
    # the hint string. The synthesized description must differ from it.
    hint = "connectors/foo.md"
    out = _syn([{"what_changed": "Adds a foo connector"}], hint=hint, min_words=6)
    assert out.strip().lower() != hint.strip().lower()


def test_trailing_colon_stripped_even_if_source_ends_in_colon():
    out = _syn(
        [{"what_changed": "Refactors the loader:"}], hint="loader.md", min_words=6
    )
    assert not out.endswith(":")
    assert len(out.split()) >= 6


def test_empty_summaries_fall_back_and_still_pass_min_words():
    out = _syn([], hint="orchestrator/state-advancement.md", min_words=6)
    assert len(out.split()) >= 6
    assert not out.endswith(":")


def test_deterministic():
    args = ([{"what_changed": "Adds a foo connector"}],)
    a = _syn(*args, hint="connectors/foo.md", min_words=6)
    b = _syn(*args, hint="connectors/foo.md", min_words=6)
    assert a == b


def test_tolerates_malformed_entries():
    out = _syn(
        ["not-a-dict", {"what_changed": None}, {"why": "Because reasons here"}],
        hint="x.md",
        min_words=6,
    )
    assert isinstance(out, str) and len(out.split()) >= 6


def test_what_changed_beats_why_when_both_present():
    out = _syn(
        [{"what_changed": "Adds foo connector logic", "why": "backward compat"}],
        hint="connectors/foo.md",
        min_words=6,
    )
    assert "Adds foo connector logic" in out
    assert "backward compat" not in out


def test_no_padding_when_description_already_long():
    out = _syn(
        [{"what_changed": "Refactors the loader module for clarity"}],
        hint="loader.md",
        min_words=6,
    )
    assert "agent-authored reference for" not in out


def test_pads_to_higher_min_words_floor():
    # A host raising description_quality.min_words must still get a description
    # that clears the raised floor — deterministically.
    out = _syn([{"what_changed": "Adds foo"}], hint="loader.md", min_words=12)
    assert len(out.split()) >= 12
    assert not out.endswith(":")
    assert out.strip().lower() != "loader.md".strip().lower()
    # determinism holds at the raised floor
    again = _syn([{"what_changed": "Adds foo"}], hint="loader.md", min_words=12)
    assert out == again
