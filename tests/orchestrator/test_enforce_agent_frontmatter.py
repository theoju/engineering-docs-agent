"""CCE-119 Item A: _enforce_agent_frontmatter makes the orchestrator's
deterministic agent_fields the authoritative frontmatter of a freshly-created
agent-authored page, regardless of what the page-author (the real LLM on the
production path) actually wrote. Verified with the real description_quality
consumer, not test -f.
"""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent.parent / "scripts"))
sys.path.insert(0, str(Path(__file__).parent.parent.parent / "scripts" / "lint"))

import orchestrator_runner as runner  # noqa: E402
import frontmatter_contract as fmc  # noqa: E402
import description_quality  # noqa: E402
from archive_indexes import parse_frontmatter  # noqa: E402

_GOOD = fmc.agent_authored_frontmatter_dict(
    description="Documents the foo connector and its retry semantics in detail",
    source_files=["backend/connectors/foo.py"],
    last_reviewed="2026-07-14",
)


def test_enforce_overwrites_deviating_frontmatter(tmp_path):
    page = tmp_path / "foo.md"
    # A deviating production write: description under the floor, source_files dropped.
    page.write_text(
        "---\ndescription: short\nstatus: draft\n---\n"
        "# Foo\n\nReal body the author wrote about the foo connector.\n"
    )
    runner._enforce_agent_frontmatter(page, _GOOD)

    text = page.read_text()
    fm = parse_frontmatter(text)
    # Real consumer, not test -f: the description now passes description_quality.
    ok, msg = description_quality.check_fm(fm, title="Foo", config={})
    assert ok, msg
    # Authoritative fields present with the orchestrator's values.
    assert fm["source_files"] == ["backend/connectors/foo.py"]
    assert fm["last_reviewed"] == "2026-07-14"
    # Body preserved; deviation gone.
    assert "Real body the author wrote about the foo connector." in text
    assert "description: short" not in text


def test_enforce_is_idempotent(tmp_path):
    page = tmp_path / "foo.md"
    page.write_text("---\ndescription: short\n---\n# Foo\n\nBody.\n")
    runner._enforce_agent_frontmatter(page, _GOOD)
    once = page.read_text()
    runner._enforce_agent_frontmatter(page, _GOOD)
    assert page.read_text() == once


def test_enforce_handles_file_without_frontmatter(tmp_path):
    page = tmp_path / "foo.md"
    page.write_text("# Foo\n\nBody with no frontmatter at all.\n")
    runner._enforce_agent_frontmatter(page, _GOOD)
    text = page.read_text()
    assert text.startswith("---\n")
    assert "Body with no frontmatter at all." in text
    fm = parse_frontmatter(text)
    ok, msg = description_quality.check_fm(fm, title="Foo", config={})
    assert ok, msg
