from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "scripts"))
import verify_diagrams as vd  # noqa: E402


def test_scan_counts_mermaid_fences(tmp_path):
    (tmp_path / "core").mkdir()
    (tmp_path / "core" / "api.md").write_text(
        "# API\n\n```mermaid\ngraph TD\nA-->B\n```\n\ntext\n\n```mermaid\nflowchart LR\n```\n"
    )
    (tmp_path / "plain.md").write_text("# Plain\n\n```python\nx = 1\n```\n")
    assert vd.scan_mermaid_sources(tmp_path) == {"core/api.md": 2}


def test_scan_ignores_indented_and_nonmermaid(tmp_path):
    (tmp_path / "a.md").write_text("```mermaid\ngraph TD\n```\n")
    (tmp_path / "b.md").write_text(
        "    ```mermaid\n    graph TD\n    ```\n"
    )  # indented code, not a fence
    assert vd.scan_mermaid_sources(tmp_path) == {"a.md": 1}


def test_scan_empty_dir_is_empty(tmp_path):
    assert vd.scan_mermaid_sources(tmp_path) == {}


def test_scan_missing_dir_is_empty(tmp_path):
    assert vd.scan_mermaid_sources(tmp_path / "nope") == {}


def test_source_to_built_urls_directory_and_flat():
    assert vd.source_to_built_urls("core/api.md") == [
        "core/api/index.html",
        "core/api.html",
    ]


def test_source_to_built_urls_index_page():
    assert vd.source_to_built_urls("index.md") == ["index.html"]
    assert vd.source_to_built_urls("core/index.md") == ["core/index.html"]
