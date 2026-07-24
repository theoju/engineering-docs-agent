"""CCE-125: a gap-detector verdict of needs_spec=null ("couldn't judge") is
advisory. The orchestrator records an info-only ``gap_detector_unjudged`` reason
and skips the verdict, so the nightly run stays non-partial (CCE-101 auto-merge
stays unblocked) and the null verdict never surfaces in "Gaps flagged".

A verdict that OMITS needs_spec is a genuine structural failure and still flips
partial — that case is locked by
``test_gap_detector_prid_injection.py::test_missing_needs_spec_still_flips_partial``.

Integration via the real run() on the ordinary dry-run path (no monkeypatching),
mirroring the CCE-120 harness.
"""

from __future__ import annotations

import json
import shutil
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent.parent / "scripts"))

FAKES = Path(__file__).parent / "fakes"

# Full-pipeline config that reaches the gap loop (verbatim from the CCE-120
# harness so run() behaves identically); inlined to keep this test independent.
GAP_CONFIG = """
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


def _fakes_with_gap(tmp_path: Path, gap_payload: dict) -> Path:
    """Copy all fixtures into tmp, overriding fake_gap_detector.json."""
    d = tmp_path / "fakes"
    shutil.copytree(FAKES, d)
    (d / "fake_gap_detector.json").write_text(json.dumps(gap_payload))
    return d


def test_null_needs_spec_is_unjudged_not_partial(tmp_path, init_host, read_current_run):
    state_path = init_host(_SEED_STATE, config_yaml=GAP_CONFIG)
    # The agent's documented malformed-input fallback: present-null needs_spec.
    dry = _fakes_with_gap(
        tmp_path,
        {
            "pr_id": "unknown/unknown#1",
            "needs_spec": None,
            "error": "malformed_input",
            "reasoning": "could not judge",
        },
    )
    import orchestrator_runner as runner

    rc = runner.run(tmp_path, dry_run_dir=dry, no_pr=True)
    assert rc == 0

    cr = read_current_run(state_path)
    # Advisory: the run stays non-partial (auto-merge unblocked)...
    assert cr["partial"] is False, cr["partial_reasons"]
    # ...but the skip is observable as an info-only reason (the dropped `error`
    # field would otherwise leave no record of *why* the PR was unjudged).
    assert any("gap_detector_unjudged: pr_id=" in r for r in cr["partial_reasons"]), cr[
        "partial_reasons"
    ]
    # null is valid now — no schema_invalid for the gap detector.
    assert not any(
        "schema_invalid: gap-detector" in r for r in cr["partial_reasons"]
    ), cr["partial_reasons"]
    # The null verdict is skipped, never appended — no "Gaps flagged" entry.
    whats_new = (tmp_path / "docs" / "site-src" / "whats-new.md").read_text()
    assert "Gaps flagged" not in whats_new, whats_new
