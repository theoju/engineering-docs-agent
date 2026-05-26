from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "scripts"))
import orchestrator_runner as runner  # noqa: E402


def test_page_target_is_editable():
    globs = ["docs/site-src/**"]
    assert runner._page_target_is_editable("docs/site-src/core/api.md", globs) is True
    assert runner._page_target_is_editable("scripts/x.py", globs) is False
    # No globs configured -> permissive (matches the nightly loop's behavior).
    assert runner._page_target_is_editable("anything/at/all.md", []) is True


def test_synthesize_core_page_writes_c2_frontmatter(tmp_path):
    import yaml

    page = {
        "key": "api",
        "title": "API layer",
        "page": "core/api.md",
        "source_files": ["backend/api/**/*.py", "backend/api/router.py"],
    }
    target = tmp_path / "core" / "api.md"
    target.parent.mkdir(parents=True)
    runner._synthesize_core_page(target, page, today="2026-05-26")

    text = target.read_text()
    fm = yaml.safe_load(text.split("---", 2)[1])
    assert fm["description"] == "API layer"
    assert fm["source_files"] == ["backend/api/**/*.py", "backend/api/router.py"]
    assert fm["last_reviewed"] == "2026-05-26"
    assert fm["status"] == "draft"


def test_synthesize_core_page_body_is_diagram_free_with_human_stub(tmp_path):
    page = {"key": "x", "title": "X", "page": "core/x.md", "source_files": ["a.py"]}
    target = tmp_path / "x.md"
    runner._synthesize_core_page(target, page, today="2026-05-26")
    text = target.read_text()
    assert "TODO(human)" in text
    assert "```mermaid" not in text
    assert "`a.py`" in text  # source inventory rendered
