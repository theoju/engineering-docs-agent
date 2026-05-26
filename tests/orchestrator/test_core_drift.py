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
