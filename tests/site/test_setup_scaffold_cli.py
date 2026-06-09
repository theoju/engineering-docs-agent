from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

_REPO_ROOT = Path(__file__).resolve().parents[2]
_CLI = _REPO_ROOT / "scripts" / "setup_scaffold.py"


def test_cli_scaffolds_default_template(tmp_path: Path):
    # a detectable python source dir → mkdocstrings wired + gen-script scoped to it
    (tmp_path / "scripts").mkdir()
    (tmp_path / "scripts" / "thing.py").write_text("x = 1\n")
    proc = subprocess.run(
        [
            sys.executable,
            str(_CLI),
            "--repo-root",
            str(tmp_path),
            "--site-name",
            "Demo",
        ],
        capture_output=True,
        text=True,
    )
    assert proc.returncode == 0, proc.stderr
    assert (tmp_path / "docs/site-src/index.md").exists()
    assert (tmp_path / "docs/site-src/archive/index.md").exists()
    assert (tmp_path / "mkdocs.yml").exists()
    assert "mkdocstrings" in (tmp_path / "mkdocs.yml").read_text()
    # detection threaded through: gen-script scoped to the detected dir, not "."
    gen = (tmp_path / "gen_ref_pages.py").read_text()
    assert 'SCAN_DIR = "scripts"' in gen


def test_cli_rerun_is_idempotent(tmp_path: Path):
    cmd = [
        sys.executable,
        str(_CLI),
        "--repo-root",
        str(tmp_path),
        "--site-name",
        "Demo",
    ]
    # First run: scaffold creates the initial index.md with managed-block markers.
    subprocess.run(cmd, capture_output=True, text=True, check=True)
    # Simulate an author adding prose BEFORE the managed block (outside markers).
    # generate_overviews upserts into the managed region; text outside markers
    # must survive byte-for-byte. We prepend author prose to the existing file
    # (which already has markers from the first run) so the second run's upsert
    # leaves the author zone unchanged.
    existing = (tmp_path / "docs/site-src/index.md").read_text(encoding="utf-8")
    authored = "# My custom heading\n\n" + existing
    (tmp_path / "docs/site-src/index.md").write_text(authored, encoding="utf-8")
    subprocess.run(cmd, capture_output=True, text=True, check=True)
    result = (tmp_path / "docs/site-src/index.md").read_text(encoding="utf-8")
    # Author prose outside the markers must survive unchanged.
    assert result.startswith("# My custom heading\n")


def test_cli_non_python_repo_omits_mkdocstrings(tmp_path: Path):
    # no .py and no pyproject.toml → python_detected False → no mkdocstrings.
    subprocess.run(
        [
            sys.executable,
            str(_CLI),
            "--repo-root",
            str(tmp_path),
            "--site-name",
            "Demo",
        ],
        capture_output=True,
        text=True,
        check=True,
    )
    assert "mkdocstrings" not in (tmp_path / "mkdocs.yml").read_text()


def test_cli_missing_config_exits_nonzero_with_message(tmp_path: Path):
    proc = subprocess.run(
        [
            sys.executable,
            str(_CLI),
            "--repo-root",
            str(tmp_path),
            "--config",
            str(tmp_path / "nope.yml"),
        ],
        capture_output=True,
        text=True,
    )
    assert proc.returncode == 1
    assert "not found" in proc.stderr


def test_cli_generates_json_schema_contracts(tmp_path: Path):
    (tmp_path / "schemas").mkdir()
    (tmp_path / "schemas" / "widget.json").write_text(
        '{"title": "Widget", "type": "object"}'
    )
    cfg = tmp_path / "site.yml"
    cfg.write_text(
        "docs_dir: docs/site-src\n"
        "theme: material\n"
        "sections:\n"
        "  - key: home\n"
        "    path: index.md\n"
        "    title: Home\n"
        "  - key: api\n"
        "    path: api/\n"
        "    title: API\n"
        "    generator: api-extract\n"
        "    extractors: [json-schema]\n"
        "    sources: [schemas]\n"
    )
    proc = subprocess.run(
        [sys.executable, str(_CLI), "--repo-root", str(tmp_path), "--config", str(cfg)],
        capture_output=True,
        text=True,
    )
    assert proc.returncode == 0, proc.stderr
    assert (tmp_path / "docs/site-src/api/contracts/widget.md").exists()
    # the contracts ledger is surfaced in the CLI's JSON output
    assert "api/contracts/widget.md" in proc.stdout


def test_cli_wires_openapi_from_config(tmp_path: Path):
    (tmp_path / "openapi.json").write_text(
        '{"openapi": "3.0.0", "info": {"title": "X", "version": "1"}, "paths": {}}'
    )
    cfg = tmp_path / "site.yml"
    cfg.write_text(
        "docs_dir: docs/site-src\n"
        "theme: material\n"
        "sections:\n"
        "  - key: home\n"
        "    path: index.md\n"
        "    title: Home\n"
        "  - key: api\n"
        "    path: api/\n"
        "    title: API\n"
        "    generator: api-extract\n"
        "    extractors: [openapi]\n"
        "    openapi: openapi.json\n"
    )
    proc = subprocess.run(
        [sys.executable, str(_CLI), "--repo-root", str(tmp_path), "--config", str(cfg)],
        capture_output=True,
        text=True,
    )
    assert proc.returncode == 0, proc.stderr
    assert (tmp_path / "docs/site-src/api/http.md").exists()
    assert "render_swagger" in (tmp_path / "mkdocs.yml").read_text()


def test_cli_surfaces_overviews_ledger(tmp_path: Path):
    """After scaffold, the JSON output includes an overviews ledger with written/skipped lists."""
    cfg = tmp_path / "site.yml"
    cfg.write_text(
        "docs_dir: docs/site-src\n"
        "theme: material\n"
        "sections:\n"
        "  - key: home\n"
        "    path: index.md\n"
        "    title: Home\n"
        "  - key: topics\n"
        "    path: topics/\n"
        "    title: Topics\n"
    )
    proc = subprocess.run(
        [sys.executable, str(_CLI), "--repo-root", str(tmp_path), "--config", str(cfg)],
        capture_output=True,
        text=True,
    )
    assert proc.returncode == 0, proc.stderr
    out = json.loads(proc.stdout)
    assert "overviews" in out, (
        f"'overviews' key missing from scaffold output: {list(out)}"
    )
    assert isinstance(out["overviews"].get("written"), list)
    assert isinstance(out["overviews"].get("skipped"), list)
