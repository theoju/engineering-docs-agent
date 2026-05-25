from __future__ import annotations
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "scripts"))
import orchestrator_runner as orun  # noqa: E402


def test_compute_source_drift_flags_changed_page(tmp_path):
    page = tmp_path / "docs/site-src/architecture/auth.md"
    page.parent.mkdir(parents=True)
    page.write_text("---\nsource_files:\n  - scripts/auth/**/*.py\n---\n# Auth\n")
    config = {"site": {"docs_dir": "docs/site-src"}}
    prs = [
        {
            "number": 1,
            "files": [{"path": "scripts/auth/session.py"}, {"path": "README.md"}],
        }
    ]
    drifted = orun.compute_source_drift(tmp_path, config, prs)
    assert drifted == [
        {"page": "architecture/auth.md", "changed_sources": ["scripts/auth/session.py"]}
    ]


def test_compute_source_drift_no_site_is_empty(tmp_path):
    assert orun.compute_source_drift(tmp_path, {}, []) == []


def test_compute_source_drift_handles_string_file_entries(tmp_path):
    page = tmp_path / "docs/site-src/a.md"
    page.parent.mkdir(parents=True)
    page.write_text("---\nsource_files:\n  - src/*.py\n---\n# A\n")
    config = {"site": {"docs_dir": "docs/site-src"}}
    prs = [{"number": 2, "files": ["src/x.py"]}]  # plain-string file entries
    assert orun.compute_source_drift(tmp_path, config, prs) == [
        {"page": "a.md", "changed_sources": ["src/x.py"]}
    ]


def test_drift_whats_new_lines():
    assert orun._drift_whats_new_lines([]) == []
    lines = orun._drift_whats_new_lines(
        [{"page": "a.md", "changed_sources": ["x.py", "y.py"]}]
    )
    assert lines[0] == "### Pages to review (source drift)"
    assert "- a.md — changed: x.py, y.py" in lines
