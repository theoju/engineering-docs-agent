from __future__ import annotations
import re
import sys
from pathlib import Path

import pytest
import yaml

sys.path.insert(0, str(Path(__file__).parent.parent.parent / "scripts"))
sys.path.insert(0, str(Path(__file__).parent.parent.parent / "scripts" / "lint"))

FAKES = Path(__file__).parent / "fakes"

# A host whose `core` lens maps into an `agent-authored` site section, so the
# fake summary's `core/connectors/foo.md` create resolves to agent-authored.
CONFIG_AGENT_AUTHORED = """
docs:
  framework: mkdocs
  source_dir: docs/site-src
  whats_new_file: docs/site-src/whats-new.md
  agent_editable_paths: ["docs/site-src/**"]
  lens_paths:
    core: docs/site-src/core
site:
  docs_dir: docs/site-src
  sections:
    - {key: core, path: core/, title: Core, generator: agent-authored}
sources:
  git: { host: github }
trigger: { cron: "0 7 * * *", on_pr_merge: false }
gap_detection:
  allowlist_paths: ["backend/connectors/**"]
  size_filter: { min_loc: 50, min_files: 3 }
lint: { tier1: default, tier2: {}, tier3: {} }
publishing:
  base_url: https://example.com
  build_workflow: deploy.yml
  url_map_rule: standard
  verify_timeout_seconds: 60
notifications:
  slack: { enabled: false }
  email: { enabled: false }
"""

_SEED_STATE = {"version": "1", "dismissed_gap_flags": {}, "cursors": {}}


def test_agent_authored_create_uses_agent_template(tmp_path, init_host, monkeypatch):
    """The frontmatter_template handed to page-author for a create in an
    agent-authored section carries the agent-authored field set, not default."""
    init_host(_SEED_STATE, config_yaml=CONFIG_AGENT_AUTHORED)
    import orchestrator_runner as runner

    captured: dict = {}
    orig = runner.dispatch_validated

    def spy(name, payload, **kw):
        if name == "page-author":
            captured["fm"] = payload.get("frontmatter_template")
            captured["source_paths"] = payload.get("source_paths")
        return orig(name, payload, **kw)

    monkeypatch.setattr(runner, "dispatch_validated", spy)
    rc = runner.run(tmp_path, dry_run_dir=FAKES, no_pr=True)
    assert rc == 0
    fm = captured["fm"]
    assert set(fm) >= {"description", "source_files", "last_reviewed", "status"}, fm
    assert "sources" not in fm and "synthesized_into" not in fm, fm
    assert isinstance(fm["description"], str) and len(fm["description"].split()) >= 6
    # the cited source_files are exactly the PR grounding handed to the author
    assert fm["source_files"] == captured["source_paths"]


def _run_subprocess(tmp_path: Path):
    import subprocess

    runner_path = (
        Path(__file__).parent.parent.parent / "scripts" / "orchestrator_runner.py"
    )
    return subprocess.run(
        [
            sys.executable,
            str(runner_path),
            "--repo-root",
            str(tmp_path),
            "--dry-run-subagents",
            str(FAKES),
            "--no-pr",
        ],
        capture_output=True,
        text=True,
    )


def test_created_agent_authored_page_passes_tier1_lint(tmp_path, init_host):
    """End-to-end: the dry-run synth writes a page that the REAL lint
    consumers accept (verify with the consumer, not test -f)."""
    init_host(_SEED_STATE, config_yaml=CONFIG_AGENT_AUTHORED)
    r = _run_subprocess(tmp_path)
    assert r.returncode == 0, r.stderr
    page = tmp_path / "docs" / "site-src" / "core" / "connectors" / "foo.md"
    assert page.exists(), "agent-authored create should land in dry-run"

    text = page.read_text()
    # Lock that the YAML single-quoting path is genuinely exercised: the
    # synthesized description always contains a colon, which is only valid
    # YAML because agent_authored_frontmatter_text single-quotes the field.
    assert "description: '" in text, "description must be single-quoted in YAML"
    assert re.search(r"description: '.*:.*'", text), (
        "colon inside single-quoted description"
    )

    import frontmatter_schema
    import description_quality

    config = yaml.safe_load(CONFIG_AGENT_AUTHORED)
    ok_fs, msg_fs = frontmatter_schema.check_path(page, config)
    ok_dq, msg_dq = description_quality.check_path(page, config)
    assert ok_fs, f"frontmatter_schema: {msg_fs}"
    assert ok_dq, f"description_quality: {msg_dq}"


def test_callsite_passes_resolved_min_words(tmp_path, init_host, monkeypatch):
    """The authoring callsite resolves description_quality.min_words from the
    host config and threads it into the synthesizer (CCE-119 Item B)."""
    cfg = CONFIG_AGENT_AUTHORED.replace(
        "lint: { tier1: default, tier2: {}, tier3: {} }",
        "lint: { tier1: { description_quality: { min_words: 12 } }, tier2: {}, tier3: {} }",
    )
    init_host(_SEED_STATE, config_yaml=cfg)
    import orchestrator_runner as runner

    captured: dict = {}
    orig = runner._synthesize_agent_description

    def spy(summaries, *, hint, min_words):
        captured["min_words"] = min_words
        return orig(summaries, hint=hint, min_words=min_words)

    monkeypatch.setattr(runner, "_synthesize_agent_description", spy)
    rc = runner.run(tmp_path, dry_run_dir=FAKES, no_pr=True)
    assert rc == 0
    assert captured["min_words"] == 12


def test_default_section_create_unaffected(tmp_path, init_host):
    """Regression: a host with NO agent-authored section still gets the default
    template and its page passes its own (default) required-field set."""
    default_cfg = CONFIG_AGENT_AUTHORED.replace(
        "    - {key: core, path: core/, title: Core, generator: agent-authored}\n",
        "    - {key: core, path: core/, title: Core}\n",
    )
    init_host(_SEED_STATE, config_yaml=default_cfg)
    r = _run_subprocess(tmp_path)
    assert r.returncode == 0, r.stderr
    page = tmp_path / "docs" / "site-src" / "core" / "connectors" / "foo.md"
    assert page.exists()
    text = page.read_text()
    assert "status:" in text and "sources:" in text and "synthesized_into:" in text
    assert "source_files:" not in text  # not the agent-authored set
