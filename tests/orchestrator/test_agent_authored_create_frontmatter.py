from __future__ import annotations
import sys
from pathlib import Path

import pytest
import yaml

sys.path.insert(0, str(Path(__file__).parent.parent.parent / "scripts"))

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
