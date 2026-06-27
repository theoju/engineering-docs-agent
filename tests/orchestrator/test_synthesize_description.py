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
    )
    assert len(out.split()) >= 6
    assert not out.endswith(":")


def test_not_equal_to_slug_title():
    # description_quality compares against the page H1 (`# {hint}`), parsed to
    # the hint string. The synthesized description must differ from it.
    hint = "connectors/foo.md"
    out = _syn([{"what_changed": "Adds a foo connector"}], hint=hint)
    assert out.strip().lower() != hint.strip().lower()


def test_trailing_colon_stripped_even_if_source_ends_in_colon():
    out = _syn([{"what_changed": "Refactors the loader:"}], hint="loader.md")
    assert not out.endswith(":")
    assert len(out.split()) >= 6


def test_empty_summaries_fall_back_and_still_pass_min_words():
    out = _syn([], hint="orchestrator/state-advancement.md")
    assert len(out.split()) >= 6
    assert not out.endswith(":")


def test_deterministic():
    args = ([{"what_changed": "Adds a foo connector"}],)
    a = _syn(*args, hint="connectors/foo.md")
    b = _syn(*args, hint="connectors/foo.md")
    assert a == b


def test_tolerates_malformed_entries():
    out = _syn(
        ["not-a-dict", {"what_changed": None}, {"why": "Because reasons here"}],
        hint="x.md",
    )
    assert isinstance(out, str) and len(out.split()) >= 6
