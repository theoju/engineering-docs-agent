from __future__ import annotations

import json
import sys
from pathlib import Path

_REPO_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(_REPO_ROOT / "scripts"))

import contracts_doc  # noqa: E402

SITE = {
    "docs_dir": "docs/site-src",
    "sections": [
        {
            "key": "api",
            "path": "api/",
            "title": "API reference",
            "generator": "api-extract",
            "extractors": ["json-schema"],
            "sources": ["schemas"],
        }
    ],
}


def _seed_schemas(repo: Path):
    d = repo / "schemas"
    d.mkdir(parents=True)
    (d / "page_author.json").write_text(
        json.dumps(
            {
                "title": "Page Author",
                "type": "object",
                "properties": {"page_path": {"type": "string"}},
                "required": ["page_path"],
            }
        )
    )
    (d / "notifier.json").write_text(
        json.dumps({"title": "Notifier", "type": "object"})
    )


def test_generate_writes_pages_and_index(tmp_path):
    _seed_schemas(tmp_path)
    result = contracts_doc.generate_contracts(tmp_path, SITE)
    base = tmp_path / "docs/site-src/api/contracts"
    assert (base / "page_author.md").exists()
    assert (base / "notifier.md").exists()
    assert (base / "index.md").exists()
    assert "docs/site-src/api/contracts/page_author.md" in result["written"]
    assert "Page Author" in (base / "page_author.md").read_text()


def test_generate_skips_when_no_json_schema_extractor(tmp_path):
    site = {
        "docs_dir": "docs/site-src",
        "sections": [
            {
                "key": "api",
                "path": "api/",
                "title": "API",
                "generator": "api-extract",
                "extractors": ["python-mkdocstrings"],
            }
        ],
    }
    assert contracts_doc.generate_contracts(tmp_path, site) == {
        "written": [],
        "skipped": [],
    }


def test_generate_skips_missing_source_dir(tmp_path):
    result = contracts_doc.generate_contracts(tmp_path, SITE)  # no schemas/ dir
    assert result["written"] == []
    assert "schemas" in result["skipped"][0]
    assert not (tmp_path / "docs/site-src/api/contracts").exists()


def test_generate_skips_empty_source_dir(tmp_path):
    (tmp_path / "schemas").mkdir()
    result = contracts_doc.generate_contracts(tmp_path, SITE)
    assert result["written"] == []
    assert result["skipped"]  # recorded, no empty page set


def test_generate_skips_malformed_schema_keeps_others(tmp_path):
    _seed_schemas(tmp_path)
    (tmp_path / "schemas" / "broken.json").write_text("{ not json ")
    result = contracts_doc.generate_contracts(tmp_path, SITE)
    base = tmp_path / "docs/site-src/api/contracts"
    assert (base / "page_author.md").exists()
    assert not (base / "broken.md").exists()
    assert any("broken.json" in s for s in result["skipped"])


def test_generate_overwrites_stale_page(tmp_path):
    _seed_schemas(tmp_path)
    base = tmp_path / "docs/site-src/api/contracts"
    base.mkdir(parents=True)
    (base / "page_author.md").write_text("STALE\n")
    contracts_doc.generate_contracts(tmp_path, SITE)
    assert "STALE" not in (base / "page_author.md").read_text()


def test_generate_skips_non_dict_schema(tmp_path):
    d = tmp_path / "schemas"
    d.mkdir()
    (d / "arr.json").write_text("[1, 2, 3]")  # valid JSON, not an object
    (d / "ok.json").write_text(json.dumps({"title": "OK", "type": "object"}))
    result = contracts_doc.generate_contracts(tmp_path, SITE)
    base = tmp_path / "docs/site-src/api/contracts"
    assert (base / "ok.md").exists()
    assert not (base / "arr.md").exists()
    assert any("arr.json" in s for s in result["skipped"])


def test_generate_dedupes_stem_across_sources(tmp_path):
    for name in ("schemas", "more"):
        d = tmp_path / name
        d.mkdir()
        (d / "dup.json").write_text(json.dumps({"title": name, "type": "object"}))
    site = {
        "docs_dir": "docs/site-src",
        "sections": [
            {
                "key": "api",
                "path": "api/",
                "title": "API",
                "generator": "api-extract",
                "extractors": ["json-schema"],
                "sources": ["schemas", "more"],
            }
        ],
    }
    result = contracts_doc.generate_contracts(tmp_path, site)
    page = (tmp_path / "docs/site-src/api/contracts/dup.md").read_text()
    assert "schemas" in page  # first source wins
    idx = (tmp_path / "docs/site-src/api/contracts/index.md").read_text()
    assert idx.count("[dup](dup.md)") == 1
    assert any("more/dup.json" in s for s in result["skipped"])
