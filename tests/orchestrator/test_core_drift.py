from __future__ import annotations

import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "scripts"))
import orchestrator_runner as runner  # noqa: E402


def _write_manifest(tmp_path: Path, manifest) -> None:
    docs = tmp_path / "docs" / "site-src"
    docs.mkdir(parents=True, exist_ok=True)
    (docs / ".doc-core-manifest.json").write_text(json.dumps(manifest))


def test_load_core_manifest_pages_returns_pages(tmp_path):
    _write_manifest(
        tmp_path,
        {"version": 1, "pages": [{"key": "api", "page": "core/api.md"}]},
    )
    pages = runner._load_core_manifest_pages(tmp_path, "docs/site-src")
    assert pages == [{"key": "api", "page": "core/api.md"}]


def test_load_core_manifest_pages_absent_returns_empty(tmp_path):
    assert runner._load_core_manifest_pages(tmp_path, "docs/site-src") == []


def test_load_core_manifest_pages_corrupt_returns_empty(tmp_path):
    docs = tmp_path / "docs" / "site-src"
    docs.mkdir(parents=True)
    (docs / ".doc-core-manifest.json").write_text("{not valid json")
    assert runner._load_core_manifest_pages(tmp_path, "docs/site-src") == []


def test_load_core_manifest_pages_no_pages_key_returns_empty(tmp_path):
    _write_manifest(tmp_path, {"version": 1})
    assert runner._load_core_manifest_pages(tmp_path, "docs/site-src") == []


_CONFIG = {"site": {"docs_dir": "docs/site-src"}}
_EMPTY_LEDGER = {"gone": [], "ambiguous": []}


def _manifest_two(tmp_path):
    _write_manifest(
        tmp_path,
        {
            "version": 1,
            "pages": [
                {"key": "api", "page": "core/api.md", "source_files": ["a"]},
                {"key": "storage", "page": "core/storage.md", "source_files": ["b"]},
            ],
        },
    )


def test_compute_core_drift_source_and_citation(tmp_path):
    _manifest_two(tmp_path)
    drifted = [{"page": "core/api.md", "changed_sources": ["a.py"]}]
    ledger = {
        "gone": [{"page": "core/storage.md", "path": "b.py", "token": "t"}],
        "ambiguous": [],
    }
    out = runner.compute_core_drift(tmp_path, _CONFIG, drifted, ledger)
    assert out == [
        {"page": "core/api.md", "reasons": ["source"]},
        {"page": "core/storage.md", "reasons": ["citation"]},
    ]


def test_compute_core_drift_both_reasons_on_one_page(tmp_path):
    _manifest_two(tmp_path)
    drifted = [{"page": "core/api.md", "changed_sources": ["a.py"]}]
    ledger = {
        "gone": [],
        "ambiguous": [
            {"page": "core/api.md", "path": "a.py", "token": "t", "lines": [1, 2]}
        ],
    }
    out = runner.compute_core_drift(tmp_path, _CONFIG, drifted, ledger)
    assert out == [{"page": "core/api.md", "reasons": ["source", "citation"]}]


def test_compute_core_drift_ignores_non_core_drift(tmp_path):
    _manifest_two(tmp_path)
    # A drifted page that is NOT in the manifest must not surface.
    drifted = [{"page": "guides/setup.md", "changed_sources": ["x.py"]}]
    assert runner.compute_core_drift(tmp_path, _CONFIG, drifted, _EMPTY_LEDGER) == []


def test_compute_core_drift_no_intersection_is_empty(tmp_path):
    _manifest_two(tmp_path)
    assert runner.compute_core_drift(tmp_path, _CONFIG, [], _EMPTY_LEDGER) == []


def test_compute_core_drift_no_docs_dir_is_empty(tmp_path):
    drifted = [{"page": "core/api.md", "changed_sources": ["a.py"]}]
    assert runner.compute_core_drift(tmp_path, {}, drifted, _EMPTY_LEDGER) == []


def test_compute_core_drift_no_manifest_is_empty(tmp_path):
    drifted = [{"page": "core/api.md", "changed_sources": ["a.py"]}]
    assert runner.compute_core_drift(tmp_path, _CONFIG, drifted, _EMPTY_LEDGER) == []


def test_compute_core_drift_corrupt_manifest_is_empty(tmp_path):
    docs = tmp_path / "docs" / "site-src"
    docs.mkdir(parents=True)
    (docs / ".doc-core-manifest.json").write_text("{bad")
    drifted = [{"page": "core/api.md", "changed_sources": ["a.py"]}]
    assert runner.compute_core_drift(tmp_path, _CONFIG, drifted, _EMPTY_LEDGER) == []


def test_compute_core_drift_writes_nothing_byte_identical(tmp_path):
    # A real draft core page on disk; the stage must leave it byte-identical.
    page = tmp_path / "docs" / "site-src" / "core" / "api.md"
    page.parent.mkdir(parents=True)
    page.write_text("---\nstatus: draft\n---\n# API\nhand-written rationale\n")
    before = page.read_bytes()
    _write_manifest(
        tmp_path,
        {
            "version": 1,
            "pages": [{"key": "api", "page": "core/api.md", "source_files": ["a"]}],
        },
    )
    drifted = [{"page": "core/api.md", "changed_sources": ["a.py"]}]
    out = runner.compute_core_drift(tmp_path, _CONFIG, drifted, _EMPTY_LEDGER)
    assert out == [{"page": "core/api.md", "reasons": ["source"]}]
    assert page.read_bytes() == before  # flag-only: byte-identical


def test_compute_core_drift_reviewed_page_surfaced_and_unedited(tmp_path):
    # status does not filter surfacing; reviewed pages are never auto-edited.
    page = tmp_path / "docs" / "site-src" / "core" / "api.md"
    page.parent.mkdir(parents=True)
    page.write_text("---\nstatus: reviewed\n---\n# API\naccreted rules\n")
    before = page.read_bytes()
    _write_manifest(
        tmp_path,
        {
            "version": 1,
            "pages": [{"key": "api", "page": "core/api.md", "source_files": ["a"]}],
        },
    )
    ledger = {
        "gone": [{"page": "core/api.md", "path": "a.py", "token": "t"}],
        "ambiguous": [],
    }
    out = runner.compute_core_drift(tmp_path, _CONFIG, [], ledger)
    assert out == [{"page": "core/api.md", "reasons": ["citation"]}]
    assert page.read_bytes() == before


def test_core_drift_whats_new_lines_empty():
    assert runner._core_drift_whats_new_lines([]) == []


def test_core_drift_whats_new_lines_renders_block():
    lines = runner._core_drift_whats_new_lines(
        [
            {"page": "core/api.md", "reasons": ["source", "citation"]},
            {"page": "core/storage.md", "reasons": ["citation"]},
        ]
    )
    assert lines[0] == "### Core pages to review (drift)"
    assert "- core/api.md (source, citation)" in lines
    assert "- core/storage.md (citation)" in lines
