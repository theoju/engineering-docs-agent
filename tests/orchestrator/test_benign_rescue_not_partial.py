"""CCE-118: a benign prose-contamination rescue on a blocking-pipeline dispatch
must NOT flip the run to `partial` (that would block CCE-101 auto-merge and force
a manual merge — the recurring nightly toil). A genuine dispatch failure still
flips partial.

The dry-run dispatch path returns the fixture JSON directly and cannot produce a
`prose_contamination_rescued` reason, so we inject the reason at the
`dispatch_validated` boundary — simulating a page-author that emitted valid JSON
wrapped in prose — and assert the public `partial` flag through the real run().
"""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent.parent / "scripts"))

FAKES = Path(__file__).parent / "fakes"

# A host whose `core` lens maps into an `agent-authored` site section, so the
# fake summary's `core/connectors/foo.md` create resolves to a page-author create.
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
_RESCUE = "prose_contamination_rescued: page-author"


def test_benign_page_author_rescue_does_not_flip_partial(
    tmp_path, init_host, read_current_run, monkeypatch
):
    state_path = init_host(_SEED_STATE, config_yaml=CONFIG_AGENT_AUTHORED)
    import orchestrator_runner as runner

    orig = runner.dispatch_validated

    def spy(name, payload, **kw):
        out, reasons = orig(name, payload, **kw)
        if name == "page-author":
            # page-author succeeded (out is not None) but its JSON arrived
            # prose-wrapped: dispatch_validated surfaces a benign rescue reason.
            reasons = reasons + [_RESCUE]
        return out, reasons

    monkeypatch.setattr(runner, "dispatch_validated", spy)
    rc = runner.run(tmp_path, dry_run_dir=FAKES, no_pr=True)
    assert rc == 0

    cr = read_current_run(state_path)
    assert _RESCUE in cr["partial_reasons"], cr["partial_reasons"]
    assert cr["partial"] is False, cr["partial_reasons"]


def test_genuine_page_author_failure_still_flips_partial(
    tmp_path, init_host, read_current_run, monkeypatch
):
    state_path = init_host(_SEED_STATE, config_yaml=CONFIG_AGENT_AUTHORED)
    import orchestrator_runner as runner

    orig = runner.dispatch_validated
    fail_reason = "schema_invalid: page-author: 'ok' is a required property"

    def spy(name, payload, **kw):
        out, reasons = orig(name, payload, **kw)
        if name == "page-author":
            # Genuine failure: no usable output. The reason describes dropped
            # work and MUST still flip partial.
            return None, reasons + [fail_reason]
        return out, reasons

    monkeypatch.setattr(runner, "dispatch_validated", spy)
    rc = runner.run(tmp_path, dry_run_dir=FAKES, no_pr=True)
    assert rc == 0

    cr = read_current_run(state_path)
    assert fail_reason in cr["partial_reasons"], cr["partial_reasons"]
    assert cr["partial"] is True
