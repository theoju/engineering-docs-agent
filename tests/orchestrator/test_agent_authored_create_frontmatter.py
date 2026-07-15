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

    # Spec B5: close the loop end-to-end — the produced page must pass the REAL
    # description_quality consumer AT the raised floor, not merely thread the
    # value. A synthesizer that ignored the floor would land at 6-11 words and
    # be rejected here (verify with the consumer tool, not test -f).
    page = tmp_path / "docs" / "site-src" / "core" / "connectors" / "foo.md"
    assert page.exists()
    import description_quality
    import frontmatter_schema

    cfg_dict = yaml.safe_load(cfg)
    ok_dq, msg_dq = description_quality.check_path(page, cfg_dict)
    assert ok_dq, f"description_quality at min_words=12: {msg_dq}"
    fm = frontmatter_schema.parse_frontmatter(page.read_text())
    assert fm is not None and len(fm["description"].split()) >= 12, fm


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


def test_reconciliation_overwrites_production_frontmatter_deviation(
    tmp_path, init_host, monkeypatch
):
    """Production-seam proof (not only dry-run): the file is ABSENT before the run
    (so `action == "create"`), then the page-author dispatch — standing in for the
    real LLM — WRITES a deviating frontmatter file during dispatch (description
    under the floor, `source_files` dropped). Because the file now exists, the
    dry-run synth is skipped, and reconciliation still makes the deterministic
    frontmatter authoritative, so the page passes REAL Tier-1 lint.
    (CCE-119 Item A / AC2.)"""
    init_host(_SEED_STATE, config_yaml=CONFIG_AGENT_AUTHORED)
    target = tmp_path / "docs" / "site-src" / "core" / "connectors" / "foo.md"
    assert not target.exists()  # production create: file absent before dispatch
    import orchestrator_runner as runner

    orig = runner.dispatch_validated

    def fake_llm_create(name, payload, **kw):
        if name == "page-author" and payload.get("action") == "create":
            # Stand in for the real page-author LLM: write a DEVIATING
            # frontmatter file during dispatch (ignoring the template's
            # lint-guarded fields), as a create the orchestrator must reconcile.
            p = Path(payload["target_path"])
            p.parent.mkdir(parents=True, exist_ok=True)
            p.write_text(
                "---\ndescription: short\nstatus: draft\n---\n"
                "# foo\n\nBody the author wrote about the foo connector.\n"
            )
            return {"ok": True, "path": payload["target_path"], "action": "create"}, []
        return orig(name, payload, **kw)

    monkeypatch.setattr(runner, "dispatch_validated", fake_llm_create)

    rc = runner.run(tmp_path, dry_run_dir=FAKES, no_pr=True)
    assert rc == 0
    assert target.exists()

    text = target.read_text()
    assert "Body the author wrote about the foo connector." in text  # body preserved
    assert "description: short" not in text  # deviation overwritten

    import frontmatter_schema
    import description_quality

    config = yaml.safe_load(CONFIG_AGENT_AUTHORED)
    ok_fs, msg_fs = frontmatter_schema.check_path(target, config)
    ok_dq, msg_dq = description_quality.check_path(target, config)
    assert ok_fs, f"frontmatter_schema: {msg_fs}"
    assert ok_dq, f"description_quality: {msg_dq}"


def test_edit_of_agent_authored_page_is_not_clobbered(tmp_path, init_host):
    """Regression: an EDIT of an existing agent-authored page with valid, RICHER
    curated frontmatter (extra accumulated `source_files`, `status: published`)
    must NOT be reconciled — reconciliation is create-only by design (spec
    degradation table: `action == edit -> reconciliation skipped`). Clobbering an
    edit would drop accumulated citations and silently revert a published page.
    (CCE-119 Item A scope guard.)"""
    init_host(_SEED_STATE, config_yaml=CONFIG_AGENT_AUTHORED)
    target = tmp_path / "docs" / "site-src" / "core" / "connectors" / "foo.md"
    target.parent.mkdir(parents=True, exist_ok=True)
    # Curated, richer-than-a-fresh-create frontmatter: two accumulated citations
    # (only one is in this run's grounding) and a published status.
    curated = (
        "---\n"
        "description: 'Documents the foo connector and its retry semantics in "
        "full detail'\n"
        "source_files:\n"
        "  - backend/connectors/foo.py\n"
        "  - backend/connectors/legacy_foo.py\n"
        "last_reviewed: '2026-01-01'\n"
        "status: published\n"
        "---\n"
        "# foo\n\nCurated body a human polished about the foo connector.\n"
    )
    target.write_text(curated)
    import orchestrator_runner as runner

    rc = runner.run(tmp_path, dry_run_dir=FAKES, no_pr=True)
    assert rc == 0

    text = target.read_text()
    # The edit path leaves the curated frontmatter untouched: accumulated
    # citations survive, the published status is not reverted to draft, and the
    # curated description/last_reviewed are intact.
    assert text == curated, "an edit of an agent-authored page must not be clobbered"
    assert "legacy_foo.py" in text  # accumulated citation not dropped
    assert "status: published" in text  # not reverted to draft
    assert "2026-01-01" in text  # curated last_reviewed preserved
