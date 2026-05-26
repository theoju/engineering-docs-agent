from __future__ import annotations
import json, subprocess, sys
from pathlib import Path

SCRIPT = (
    Path(__file__).parent.parent.parent / "scripts" / "lint" / "frontmatter_schema.py"
)
FIX = Path(__file__).parent.parent / "fixtures" / "frontmatter_schema"


def _run(paths, cfg):
    r = subprocess.run(
        [
            sys.executable,
            str(SCRIPT),
            "--config",
            str(cfg),
            "--paths",
            *[str(p) for p in paths],
            "--json",
        ],
        capture_output=True,
        text=True,
    )
    return r.returncode, json.loads(r.stdout)


def test_good(tmp_path):
    cfg = tmp_path / "c.yml"
    cfg.write_text("{}")
    rc, out = _run([FIX / "good.md"], cfg)
    assert rc == 0
    assert out["rule"] == "frontmatter_schema"
    assert out["severity"] == "block"
    assert all(r["ok"] for r in out["results"])


def test_missing_field(tmp_path):
    cfg = tmp_path / "c.yml"
    cfg.write_text("{}")
    rc, out = _run([FIX / "bad_missing_field.md"], cfg)
    assert rc == 1
    msg = out["results"][0]["message"]
    assert "synthesized_into" in msg


def test_no_frontmatter(tmp_path):
    cfg = tmp_path / "c.yml"
    cfg.write_text("{}")
    rc, out = _run([FIX / "bad_no_frontmatter.md"], cfg)
    assert rc == 1
    assert "frontmatter" in out["results"][0]["message"].lower()


def test_agent_authored_page_passes_with_new_fields(tmp_path):
    cfg = tmp_path / "c.yml"
    cfg.write_text(
        "site:\n"
        "  docs_dir: docs/site-src\n"
        "  sections:\n"
        "    - key: core\n"
        "      path: core/\n"
        "      title: Core\n"
        "      generator: agent-authored\n"
    )
    page = tmp_path / "docs/site-src/core/api.md"
    page.parent.mkdir(parents=True)
    page.write_text(
        "---\n"
        "description: The API layer\n"
        "source_files: [backend/app/api/router.py]\n"
        "last_reviewed: 2026-05-26\n"
        "status: draft\n"
        "---\n\n# API\n"
    )
    rc, out = _run([page], cfg)
    assert rc == 0
    assert all(r["ok"] for r in out["results"])


def test_agent_authored_page_missing_source_files_fails(tmp_path):
    cfg = tmp_path / "c.yml"
    cfg.write_text(
        "site:\n  docs_dir: docs/site-src\n  sections:\n"
        "    - {key: core, path: core/, title: Core, generator: agent-authored}\n"
    )
    page = tmp_path / "docs/site-src/core/api.md"
    page.parent.mkdir(parents=True)
    page.write_text(
        "---\ndescription: x\nlast_reviewed: 2026-05-26\nstatus: draft\n---\n\n# API\n"
    )
    rc, out = _run([page], cfg)
    assert rc == 1
    assert "source_files" in out["results"][0]["message"]


def test_agent_authored_rejects_old_default_fields(tmp_path):
    cfg = tmp_path / "c.yml"
    cfg.write_text(
        "site:\n  docs_dir: docs/site-src\n  sections:\n"
        "    - {key: core, path: core/, title: Core, generator: agent-authored}\n"
    )
    page = tmp_path / "docs/site-src/core/api.md"
    page.parent.mkdir(parents=True)
    page.write_text(
        "---\nstatus: draft\nsources: []\nsynthesized_into: []\n---\n\n# API\n"
    )
    rc, out = _run([page], cfg)
    assert rc == 1
    msg = out["results"][0]["message"]
    assert "description" in msg and "source_files" in msg and "last_reviewed" in msg


def test_non_agent_authored_page_keeps_default_set(tmp_path):
    cfg = tmp_path / "c.yml"
    cfg.write_text(
        "site:\n  docs_dir: docs/site-src\n  sections:\n"
        "    - {key: ops, path: operations/, title: Ops}\n"
    )
    page = tmp_path / "docs/site-src/operations/run.md"
    page.parent.mkdir(parents=True)
    page.write_text("---\nstatus: accepted\nsources: [a]\n---\n\n# Run\n")
    rc, out = _run([page], cfg)
    assert rc == 1
    assert "synthesized_into" in out["results"][0]["message"]


def test_synthesized_core_page_passes_block_rule(tmp_path):
    """A page written by _synthesize_core_page passes frontmatter_schema when its
    section's generator is agent-authored (absolute-path frame, as the
    orchestrator dispatches)."""
    import sys

    scripts = Path(__file__).resolve().parents[2] / "scripts"
    sys.path.insert(0, str(scripts))
    import orchestrator_runner as runner  # noqa: E402

    docs_dir = "docs/site-src"
    page_entry = {
        "key": "api",
        "title": "API layer",
        "page": "core/api.md",
        "source_files": ["backend/api/**/*.py"],
    }
    target = tmp_path / docs_dir / "core" / "api.md"
    target.parent.mkdir(parents=True)
    runner._synthesize_core_page(target, page_entry, today="2026-05-26")

    cfg = tmp_path / "config.yml"
    cfg.write_text(
        "site:\n"
        f"  docs_dir: {docs_dir}\n"
        "  sections:\n"
        "    - key: core\n"
        "      path: core/\n"
        "      title: Core\n"
        "      generator: agent-authored\n"
    )
    rc, out = _run([target], cfg)
    assert rc == 0, out["results"][0].get("message", "")
    assert all(r["ok"] for r in out["results"])


def test_orchestrator_absolute_path_frame_resolves_agent_authored(tmp_path):
    """Pin the orchestrator's real frame: pages are authored at the absolute
    path repo_root/lens_path/hint (orchestrator_runner.py:763) and handed to
    the frontmatter_schema block rule (lint_runner.run_rule, subprocess). A C2
    page under an agent-authored section must resolve agent-authored and PASS;
    missing a C2 field must FAIL (rule fired, not silently defaulted)."""
    config = tmp_path / "config.yml"
    config.write_text(
        "site:\n"
        "  docs_dir: docs/site-src\n"
        "  sections:\n"
        "    - key: architecture\n"
        "      path: architecture/\n"
        "      title: Architecture\n"
        "      generator: agent-authored\n"
    )
    # Page at the orchestrator's real frame: repo_root / docs_dir / section / file
    page = tmp_path / "docs" / "site-src" / "architecture" / "system-overview.md"
    page.parent.mkdir(parents=True)
    page.write_text(
        "---\n"
        "description: System overview\n"
        "source_files:\n"
        "  - scripts/**/*.py\n"
        "last_reviewed: 2026-05-26\n"
        "status: draft\n"
        "---\n\n# System overview\n"
    )
    rc, out = _run([page], config)
    assert out["results"][0]["ok"] is True, out["results"][0]["message"]

    # Negative: drop a C2-required field -> rule must block at this same frame.
    page.write_text(
        "---\n"
        "source_files:\n"
        "  - scripts/**/*.py\n"
        "last_reviewed: 2026-05-26\n"
        "status: draft\n"
        "---\n\n# System overview\n"
    )
    rc, out = _run([page], config)
    assert out["results"][0]["ok"] is False
    assert "description" in out["results"][0]["message"]


def test_agent_authored_status_reviewed_passes_block_rule(tmp_path):
    """The draft -> reviewed lifecycle (C2 sub-plan 4): an agent-authored page
    with status: reviewed still satisfies the block rule — the rule checks field
    presence, not the status value, so a human-reviewed core page is never
    deleted by the pipeline."""
    cfg = tmp_path / "c.yml"
    cfg.write_text(
        "site:\n  docs_dir: docs/site-src\n  sections:\n"
        "    - {key: core, path: core/, title: Core, generator: agent-authored}\n"
    )
    page = tmp_path / "docs/site-src/core/api.md"
    page.parent.mkdir(parents=True)
    page.write_text(
        "---\n"
        "description: The API layer\n"
        "source_files: [backend/app/api/router.py]\n"
        "last_reviewed: 2026-05-26\n"
        "status: reviewed\n"
        "---\n\n# API\n"
    )
    rc, out = _run([page], cfg)
    assert rc == 0
    assert all(r["ok"] for r in out["results"])
