"""CCE-139: the four-site sentinel.

ONE test that goes red if ANY of the four resolution sites named in the spec is
left un-widened. It lives under tests/orchestrator/ because that is the only
directory whose conftest provides `init_host`, and because block E has to drive
the real orchestrator to reach the fact-checker's admission gate.

Blocks, and the site each one pins:
  A  _resolves() + the check_path paths-loop call site   (spec items 1, 2a)
  B  the check_path stale-exemption call site            (spec item 2b)
  C  the symbol loop's target resolution                 (spec item 3)
  D  resolve_cited_sources()                             (spec item 4a)
  E  the orchestrator call site                          (spec item 4b)

Task 6 Step 5 of the plan runs a six-way mutation proof against this file: each
site is reverted in turn and the sentinel is observed to go red with the named
message. Do not weaken an assertion here without redoing that proof.
"""

from __future__ import annotations
import json
import sys
from pathlib import Path

import yaml

sys.path.insert(0, str(Path(__file__).parent.parent.parent / "scripts"))

import orchestrator_runner  # noqa: E402

from scripts.lint import citation_exists  # noqa: E402

CONFIG_YAML = """
docs:
  framework: mkdocs
  source_dir: docs/site-src
  whats_new_file: docs/site-src/whats-new.md
  agent_editable_paths: ["docs/site-src/**"]
  lens_paths:
    core: docs/site-src/core
sources:
  git: { host: github }
lint:
  tier1: default
  citation_source_roots: [backend]
  citation_exempt_tokens: ["app/core/legacy.py"]
publishing:
  base_url: https://example.com
  build_workflow: deploy.yml
  url_map_rule: standard
  verify_timeout_seconds: 60
notifications:
  slack: { enabled: false }
  email: { enabled: false }
"""

SEED = {
    "backend/app/core/real_module.py": "def real_fn():\n    return 1\n",
    "backend/app/core/legacy.py": "LEGACY = 1\n",
}

CITED_PAGE = """\
---
status: draft
sources: []
synthesized_into: null
---
# Page

This page cites `app/core/real_module.py` in prose.
"""


def _write_fakes(fakes: Path) -> None:
    """Minimal dry-run fixture set: one PR -> one core page, plus a fact-checker
    that returns a contradiction so a dispatch is observable."""
    fakes.mkdir(parents=True, exist_ok=True)
    (fakes / "fake_source_collector.json").write_text(
        json.dumps(
            {
                "prs": [
                    {
                        "number": 1,
                        "url": "https://example.test/pr/1",
                        "merge_sha": "",
                        "files": [{"path": "backend/app/core/real_module.py"}],
                        "jira_keys": [],
                    }
                ],
                "jira_issues": [],
            }
        )
    )
    (fakes / "fake_pr_summarizer.json").write_text(
        json.dumps(
            {
                "pr_number": 1,
                "what_changed": "module behavior",
                "doc_targets": [
                    {"lens": "core", "page_hint": "page.md", "action": "edit"}
                ],
            }
        )
    )
    (fakes / "fake_page_author.json").write_text(
        json.dumps({"ok": True, "path": "docs/site-src/core/page.md", "action": "edit"})
    )
    (fakes / "fake_content_validator.json").write_text(
        json.dumps({"passed": [], "failed": []})
    )
    (fakes / "fake_gap_detector.json").write_text(
        json.dumps({"pr_id": "o/r#1", "needs_spec": False})
    )
    (fakes / "fake_notifier.json").write_text(
        json.dumps({"slack_ok": True, "email_ok": True})
    )
    (fakes / "fake_fact_checker.json").write_text(
        json.dumps(
            {
                "ok": True,
                "verdict": "contradiction",
                "page": "docs/site-src/core/page.md",
                "findings": [
                    {
                        "claim": "page says X but code does Y",
                        "source_path": "backend/app/core/real_module.py",
                        "evidence": "real_fn returns 1",
                    }
                ],
            }
        )
    )


def test_source_roots_threaded_through_all_four_resolution_sites(
    init_host, tmp_path, read_current_run
):
    state_path = init_host({"version": "1"}, CONFIG_YAML, SEED)
    repo = tmp_path
    config = yaml.safe_load(CONFIG_YAML)
    files = citation_exists.tracked_files(repo)
    roots = citation_exists.source_roots(config)
    assert roots == ("backend",), "site 0: source_roots() must read the config"

    # A probe page at the repo root, outside docs/site-src, so nothing the
    # orchestrator stages can see it. Removed before block E runs.
    probe = repo / "probe.md"

    # --- Block A: sites 1 + 2a. An import-relative path resolves under a root.
    probe.write_text("The entry point is `app/core/real_module.py`.\n")
    ok, msg = citation_exists.check_path(probe, repo, files, config)
    assert ok is True, f"block A (sites 1+2a) not widened: {msg}"

    # --- Block A control: an invented path under the SAME root still blocks.
    probe.write_text("See `app/core/nonexistent_module.py`.\n")
    ok, msg = citation_exists.check_path(probe, repo, files, config)
    assert ok is False, "block A control: invented path must still block"
    assert "cites nonexistent path 'app/core/nonexistent_module.py'" in msg

    # --- Block B: site 2b. An exempt token now resolving under a root drifts.
    probe.write_text("The retired shim `app/core/legacy.py` is gone.\n")
    ok, msg = citation_exists.check_path(probe, repo, files, config)
    assert ok is True, msg
    assert "stale exemption: 'app/core/legacy.py' now resolves" in msg, (
        f"block B (site 2b, the stale-exemption call site) not widened: {msg}"
    )

    # --- Block C: site 3. The SILENT SKIP: with A widened and C not, this
    # returns ok=True / 'ok' and the confabulated symbol ships unreported.
    probe.write_text("See `app/core/real_module.py:ghost_fn` for the logic.\n")
    ok, msg = citation_exists.check_path(probe, repo, files, config)
    assert ok is False, f"block C (site 3, symbol loop) silently skipped: {msg}"
    assert "cites nonexistent symbol 'ghost_fn' in 'app/core/real_module.py'" in msg

    # --- Block D: site 4a. The fact-checker's second resolver, resolved form.
    resolved = citation_exists.resolve_cited_sources(
        "The entry point is `app/core/real_module.py`.\n", repo, roots
    )
    assert resolved == ["backend/app/core/real_module.py"], (
        f"block D (site 4a, resolve_cited_sources) not widened: {resolved}"
    )

    # --- Block D control: an invented path is never handed to the fact-checker.
    assert (
        citation_exists.resolve_cited_sources(
            "See `app/core/nonexistent_module.py`.\n", repo, roots
        )
        == []
    )

    probe.unlink()

    # --- Block E: site 4b. The orchestrator call site. With it un-threaded,
    # resolve_cited_sources returns [] for this page, the admission gate
    # `if not cited_sources: continue` fires, and no fact-checker runs.
    page = repo / "docs" / "site-src" / "core" / "page.md"
    page.write_text(CITED_PAGE)
    fakes = tmp_path / "fakes"
    _write_fakes(fakes)

    rc = orchestrator_runner.run(repo, dry_run_dir=fakes, no_pr=True)
    assert rc == 0
    cr = read_current_run(state_path)
    assert len(cr["fact_check_warnings"]) == 1, (
        "block E (site 4b, the orchestrator call site) not threaded: the "
        f"fact-checker never ran. warnings={cr['fact_check_warnings']}"
    )
    assert "page says X but code does Y" in cr["fact_check_warnings"][0]
