"""CCE-120: the orchestrator injects its own pr_id into the gap-detector
verdict, so a gap-detector response missing pr_id no longer flips the nightly
run to `partial` (which would block CCE-101 auto-merge). A verdict missing
`needs_spec` — the agent's real judgment — still flips partial.

Integration via the real run(): a custom dry_run_dir copies every fake_*.json
from tests/orchestrator/fakes/ verbatim, then overwrites fake_gap_detector.json
so it omits pr_id. No monkeypatching — the inject merge lives in
dispatch_validated on the ordinary dry-run path.
"""

from __future__ import annotations

import json
import shutil
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent.parent / "scripts"))

FAKES = Path(__file__).parent / "fakes"

# A full-pipeline config that reaches the gap loop (source-collector returns a
# PR; the gap loop iterates every PR). Mirrors the CCE-118 integration config.
GAP_CONFIG = """
docs:
  framework: mkdocs
  source_dir: docs/site-src
  whats_new_file: docs/site-src/whats-new.md
  agent_editable_paths: ["docs/site-src/**"]
  lens_paths:
    core: docs/site-src/core
# site:/sections is copied wholesale for CCE-118 parity; the gap loop under
# test never reads it (it needs only sources.git, gap_detection, and the PR
# from source-collector). Kept verbatim so run() behaves identically.
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


def test_missing_prid_does_not_flip_partial_and_prid_flows_downstream(
    tmp_path, init_host, read_current_run
):
    state_path = init_host(_SEED_STATE, config_yaml=GAP_CONFIG)
    # gap-detector verdict OMITS pr_id (the CCE-120 failure); needs_spec True
    # so the flagged gap surfaces in What's-New with its pr_id.
    dry = _fakes_with_gap(
        tmp_path,
        {"needs_spec": True, "reasoning": "allowlist hit", "tier": "allowlist"},
    )
    import orchestrator_runner as runner

    rc = runner.run(tmp_path, dry_run_dir=dry, no_pr=True)
    assert rc == 0

    cr = read_current_run(state_path)
    # The whole point: a missing pr_id is injected, so no schema_invalid, so
    # the run is NOT partial on account of the gap detector.
    assert not any("gap-detector" in r for r in cr["partial_reasons"]), cr[
        "partial_reasons"
    ]
    assert cr["partial"] is False, cr["partial_reasons"]

    # Downstream proof: the injected pr_id reached the verdict and rendered
    # into the What's-New "Gaps flagged" block. In a remote-less test host the
    # orchestrator resolves pr_id to "unknown/unknown#1".
    whats_new = (tmp_path / "docs" / "site-src" / "whats-new.md").read_text()
    assert "unknown/unknown#1" in whats_new, whats_new


def test_missing_needs_spec_still_flips_partial(tmp_path, init_host, read_current_run):
    state_path = init_host(_SEED_STATE, config_yaml=GAP_CONFIG)
    # needs_spec is the agent's real judgment. Omitting it is a genuine
    # failure that MUST still flip partial (Fix A must not swallow it).
    # pr_id present so ONLY the needs_spec gap is under test.
    dry = _fakes_with_gap(tmp_path, {"pr_id": "unknown/unknown#1", "reasoning": "x"})
    import orchestrator_runner as runner

    rc = runner.run(tmp_path, dry_run_dir=dry, no_pr=True)
    assert rc == 0

    cr = read_current_run(state_path)
    assert any(
        "schema_invalid: gap-detector" in r and "needs_spec" in r
        for r in cr["partial_reasons"]
    ), cr["partial_reasons"]
    assert cr["partial"] is True
