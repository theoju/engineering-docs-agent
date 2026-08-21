from __future__ import annotations
import importlib
import json, subprocess, sys
import sys as _sys
from pathlib import Path

import pytest

RUNNER = Path(__file__).parent.parent.parent / "scripts" / "orchestrator_runner.py"
FAKES = Path(__file__).parent / "fakes"
FAKES_BLOCK = Path(__file__).parent / "fakes_block"
FAKES_UNSAFE = Path(__file__).parent / "fakes_unsafe"
FAKES_SC_ERROR = Path(__file__).parent / "fakes_sc_error"
FAKES_EMPTY = Path(__file__).parent / "fakes_empty"
FAKES_MULTI = Path(__file__).parent / "fakes_multi"
FAKES_BAD_JSON = Path(__file__).parent / "fakes_bad_json"
FAKES_COLLISION = Path(__file__).parent / "fakes_collision"


def _run_inproc(tmp_path: Path, fakes_dir: Path):
    """In-process run for monkeypatch-driven tests.

    Does NOT reload the module so monkeypatches applied by the caller survive.
    """
    _sys.path.insert(0, str(Path(__file__).parent.parent.parent / "scripts"))
    import orchestrator_runner as runner

    return runner.run(tmp_path, dry_run_dir=fakes_dir, no_pr=True)


# Variant of the conftest CONFIG_YAML: extra trigger/gap_detection blocks and
# explicit (empty) tier2/tier3 lint maps — kept local so these tests keep
# running under the exact config they were written against.
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


@pytest.fixture
def init_pipeline_host(init_host):
    """Thin wrapper over the conftest ``init_host`` factory: every test in this
    file runs under the local variant CONFIG_YAML above and a state seeded with
    dismissed_gap_flags/cursors."""

    def _make(*, seed_files: dict[str, str] | None = None) -> Path:
        return init_host(
            {"version": "1", "dismissed_gap_flags": {}, "cursors": {}},
            config_yaml=CONFIG_YAML,
            seed_files=seed_files,
        )

    return _make


def _run(tmp_path: Path, fakes_dir: Path) -> subprocess.CompletedProcess:
    return subprocess.run(
        [
            sys.executable,
            str(RUNNER),
            "--repo-root",
            str(tmp_path),
            "--dry-run-subagents",
            str(fakes_dir),
            "--no-pr",
        ],
        capture_output=True,
        text=True,
    )


def test_pipeline_dry_run(tmp_path, init_pipeline_host, read_current_run):
    state = init_pipeline_host()
    r = _run(tmp_path, FAKES)
    assert r.returncode == 0, r.stderr
    cr = read_current_run(state)
    assert cr is not None
    whats_new = tmp_path / "docs" / "site-src" / "whats-new.md"
    assert whats_new.exists(), "What's New file should be created"
    content = whats_new.read_text()
    assert "PR #1" in content
    assert "Gaps flagged" in content


def test_lint_block_unlinks_newly_created_file(
    tmp_path, init_pipeline_host, read_current_run
):
    """Create case: page-author writes a new file, validator blocks → unlink."""
    state = init_pipeline_host()
    target = tmp_path / "docs" / "site-src" / "core" / "connectors" / "foo.md"
    assert not target.exists(), "foo.md must not be in HEAD for the create-case"

    r = _run(tmp_path, FAKES_BLOCK)
    assert r.returncode == 0, r.stderr
    assert not target.exists(), "blocked create should be unlinked"

    cr = read_current_run(state)
    reasons = cr["partial_reasons"]
    assert cr["partial"] is True
    assert any("lint_block" in reason for reason in reasons), reasons


def test_orchestrator_hard_fails_on_bad_config(tmp_path, init_pipeline_host):
    """An invalid config (missing required keys + bad enum) → exit 2 (hard fail)."""
    _sys.path.insert(0, str(Path(__file__).parent.parent.parent / "scripts"))
    import orchestrator_runner as runner

    importlib.reload(runner)

    init_pipeline_host()
    cfg = tmp_path / ".engineering-docs-agent" / "config.yml"
    cfg.write_text("docs:\n  framework: vuepress\n")  # missing required + bad enum

    rc = runner.run(tmp_path, dry_run_dir=FAKES, no_pr=True)
    assert rc == 2, "exit 2 on invalid config (hard fail)"


def test_same_page_targets_batched_into_single_dispatch(
    tmp_path, monkeypatch, init_pipeline_host
):
    """3 PRs that all target the same (lens, page_hint) → ONE page-author dispatch
    with all 3 summaries."""
    _sys.path.insert(0, str(Path(__file__).parent.parent.parent / "scripts"))
    import orchestrator_runner as runner

    importlib.reload(runner)

    captured: list[dict] = []
    real = runner.dispatch_subagent

    def spying(name, inputs, *, dry_run_dir, cwd=None, out_reasons=None):
        if name == "page-author":
            captured.append(inputs)
        return real(name, inputs, dry_run_dir=dry_run_dir, out_reasons=out_reasons)

    monkeypatch.setattr(runner, "dispatch_subagent", spying)

    init_pipeline_host()
    rc = runner.run(tmp_path, dry_run_dir=FAKES_COLLISION, no_pr=True)
    assert rc == 0

    # 3 PRs, same target → ONE dispatch with all 3 summaries
    assert len(captured) == 1, f"expected 1 page-author dispatch, got {len(captured)}"
    assert len(captured[0]["summaries"]) == 3


def test_blocked_create_cleans_up_empty_parent_dirs(tmp_path, init_pipeline_host):
    """Blocked create unlinks the file; empty parent dir(s) should also be removed."""
    _sys.path.insert(0, str(Path(__file__).parent.parent.parent / "scripts"))
    import orchestrator_runner as runner

    importlib.reload(runner)

    init_pipeline_host()
    rc = runner.run(tmp_path, dry_run_dir=FAKES_BLOCK, no_pr=True)
    assert rc == 0

    # The page-author created docs/site-src/core/connectors/foo.md;
    # validator blocked → file unlinked → connectors/ directory empty → should be removed.
    connectors = tmp_path / "docs" / "site-src" / "core" / "connectors"
    assert not connectors.exists(), "empty parent dir should be removed after cleanup"


def test_lint_block_restores_edited_file_from_head(
    tmp_path, init_pipeline_host, read_current_run
):
    """Edit case: file in HEAD with original content, working tree modified,
    validator blocks → git checkout HEAD -- restores original content."""
    rel = "docs/site-src/core/connectors/foo.md"
    original = "---\nstatus: published\n---\n# Original\n"
    state = init_pipeline_host(seed_files={rel: original})
    target = tmp_path / rel
    assert target.read_text() == original

    # Simulate page-author editing the file in the working tree.
    target.write_text("---\nstatus: draft\n---\n# Mutated by page-author\n")
    assert target.read_text() != original

    r = _run(tmp_path, FAKES_BLOCK)
    assert r.returncode == 0, r.stderr
    assert target.read_text() == original, "blocked edit should be restored from HEAD"

    cr = read_current_run(state)
    assert cr["partial"] is True
    assert any("lint_block" in reason for reason in cr["partial_reasons"])


def test_jira_input_forwarded_to_source_collector(
    tmp_path, monkeypatch, init_pipeline_host
):
    """When config has sources.jira, orchestrator passes it under the `jira` key."""
    import sys as _sys

    _sys.path.insert(0, str(Path(__file__).parent.parent.parent / "scripts"))
    import orchestrator_runner

    captured_inputs: dict[str, dict] = {}
    real_dispatch = orchestrator_runner.dispatch_subagent

    def spying_dispatch(name, inputs, *, dry_run_dir, cwd=None, out_reasons=None):
        captured_inputs[name] = inputs
        return real_dispatch(
            name, inputs, dry_run_dir=dry_run_dir, out_reasons=out_reasons
        )

    monkeypatch.setattr(orchestrator_runner, "dispatch_subagent", spying_dispatch)

    state = init_pipeline_host()
    cfg = tmp_path / ".engineering-docs-agent" / "config.yml"
    cfg.write_text(
        cfg.read_text().replace(
            "sources:\n  git: { host: github }",
            "sources:\n  git: { host: github }\n  jira:\n    enabled: true\n    project_keys: [ADIS]\n    base_url: https://acme.atlassian.net",
        )
    )

    rc = _run_inproc(tmp_path, FAKES)
    assert rc == 0

    sc_inputs = captured_inputs.get("source-collector", {})
    assert sc_inputs.get("jira") == {
        "enabled": True,
        "project_keys": ["ADIS"],
        "base_url": "https://acme.atlassian.net",
    }


def test_jira_context_threaded_to_pr_summarizer(
    tmp_path, monkeypatch, init_pipeline_host
):
    _sys.path.insert(0, str(Path(__file__).parent.parent.parent / "scripts"))
    import orchestrator_runner as runner

    importlib.reload(runner)

    captured: dict[str, list] = {"summarizer_inputs": []}
    real_dispatch = runner.dispatch_subagent

    def spying(name, inputs, *, dry_run_dir, cwd=None, out_reasons=None):
        if name == "pr-summarizer":
            captured["summarizer_inputs"].append(inputs)
        return real_dispatch(
            name, inputs, dry_run_dir=dry_run_dir, out_reasons=out_reasons
        )

    monkeypatch.setattr(runner, "dispatch_subagent", spying)

    init_pipeline_host()
    runner.run(tmp_path, dry_run_dir=FAKES, no_pr=True)

    assert len(captured["summarizer_inputs"]) == 1
    jc = captured["summarizer_inputs"][0]["jira_context"]
    assert len(jc) == 1
    assert jc[0]["key"] == "ADIS-235"


def test_voice_samples_loaded_and_passed_to_authoring(
    tmp_path, monkeypatch, init_pipeline_host
):
    _sys.path.insert(0, str(Path(__file__).parent.parent.parent / "scripts"))
    import orchestrator_runner as runner

    importlib.reload(runner)

    captured: list[dict] = []
    real_dispatch = runner.dispatch_subagent

    def spying(name, inputs, *, dry_run_dir, cwd=None, out_reasons=None):
        if name in ("page-author", "content-validator"):
            captured.append(
                {"name": name, "voice_samples": inputs.get("voice_samples")}
            )
        return real_dispatch(
            name, inputs, dry_run_dir=dry_run_dir, out_reasons=out_reasons
        )

    monkeypatch.setattr(runner, "dispatch_subagent", spying)

    init_pipeline_host(
        seed_files={
            "voice/tone.md": "Use second person.",
            "CLAUDE.md": "Project voice notes.",
        },
    )
    cfg = tmp_path / ".engineering-docs-agent" / "config.yml"
    cfg.write_text(cfg.read_text() + "\nvoice:\n  sample_paths: [voice/tone.md]\n")

    runner.run(tmp_path, dry_run_dir=FAKES, no_pr=True)

    assert captured, "expected page-author/content-validator dispatches"
    for entry in captured:
        assert entry["voice_samples"], f"voice_samples missing for {entry['name']}"
        paths = [s["path"] for s in entry["voice_samples"]]
        assert "voice/tone.md" in paths
        assert "CLAUDE.md" in paths


def test_unsafe_page_path_filtered_logs_partial(
    tmp_path, init_pipeline_host, read_current_run
):
    """page_hint containing .. should not touch the filesystem."""
    _sys.path.insert(0, str(Path(__file__).parent.parent.parent / "scripts"))
    import orchestrator_runner as runner

    importlib.reload(runner)

    state_path = init_pipeline_host()
    rc = runner.run(tmp_path, dry_run_dir=FAKES_UNSAFE, no_pr=True)
    assert rc == 0

    # Filesystem outside the lens path was not touched
    assert not (tmp_path.parent.parent / "etc" / "passwd.md").exists()
    # No "etc" dir was created at any level
    assert not (tmp_path / ".." / "etc").exists()

    cr = read_current_run(state_path)
    reasons = cr["partial_reasons"]
    assert any("unsafe_page_path" in r for r in reasons)


def test_gap_detector_receives_constructed_pr_id(
    tmp_path, monkeypatch, init_pipeline_host
):
    _sys.path.insert(0, str(Path(__file__).parent.parent.parent / "scripts"))
    import orchestrator_runner as runner

    importlib.reload(runner)

    captured: list[dict] = []
    real = runner.dispatch_subagent

    def spying(name, inputs, *, dry_run_dir, cwd=None, out_reasons=None):
        if name == "gap-detector":
            captured.append(inputs)
        return real(name, inputs, dry_run_dir=dry_run_dir, out_reasons=out_reasons)

    monkeypatch.setattr(runner, "dispatch_subagent", spying)
    monkeypatch.setenv("GITHUB_REPOSITORY", "myorg/myrepo")

    init_pipeline_host()
    runner.run(tmp_path, dry_run_dir=FAKES, no_pr=True)

    assert captured
    assert captured[0].get("pr_id") == "myorg/myrepo#1"


def test_archive_index_regenerated_after_authoring(tmp_path, init_pipeline_host):
    _sys.path.insert(0, str(Path(__file__).parent.parent.parent / "scripts"))
    import orchestrator_runner as runner

    importlib.reload(runner)

    init_pipeline_host(
        seed_files={
            "docs/site-src/archive/2025/old.md": "---\nstatus: archived\n---\n# Old",
        },
    )
    cfg = tmp_path / ".engineering-docs-agent" / "config.yml"
    cfg.write_text(
        cfg.read_text().replace(
            "    core: docs/site-src/core",
            "    core: docs/site-src/core\n    archive:\n      path: docs/site-src/archive\n      archive_index: true",
        )
    )

    runner.run(tmp_path, dry_run_dir=FAKES, no_pr=True)

    index = tmp_path / "docs" / "site-src" / "archive" / "2025" / "index.md"
    assert index.exists(), "archive_indexes should regenerate per-year index.md"
    assert "old" in index.read_text()


def test_archive_index_empty_subdir_emits_placeholder(tmp_path):
    _sys.path.insert(0, str(Path(__file__).parent.parent.parent / "scripts"))
    import archive_indexes

    (tmp_path / "empty").mkdir()
    archive_indexes.regenerate(tmp_path)

    index = tmp_path / "empty" / "index.md"
    assert index.exists()
    assert "_No entries yet._" in index.read_text()


def test_dispatch_subagent_handles_bad_json_in_production_branch(monkeypatch, tmp_path):
    _sys.path.insert(0, str(Path(__file__).parent.parent.parent / "scripts"))
    import orchestrator_runner as runner

    importlib.reload(runner)

    class FakeCP:
        def __init__(self, stdout, stderr="", returncode=0):
            self.stdout = stdout
            self.stderr = stderr
            self.returncode = returncode

    monkeypatch.setattr(
        runner.subprocess,
        "run",
        lambda *a, **kw: FakeCP(stdout="not json at all\n"),
    )

    # Call dispatch_subagent directly with dry_run_dir=None (production path)
    result = runner.dispatch_subagent("source-collector", {}, dry_run_dir=None)
    assert result is None


def test_dispatch_subagent_handles_empty_stdout(monkeypatch, tmp_path):
    _sys.path.insert(0, str(Path(__file__).parent.parent.parent / "scripts"))
    import orchestrator_runner as runner

    importlib.reload(runner)

    class FakeCP:
        stdout = ""
        stderr = ""
        returncode = 0

    monkeypatch.setattr(runner.subprocess, "run", lambda *a, **kw: FakeCP())
    result = runner.dispatch_subagent("source-collector", {}, dry_run_dir=None)
    assert result is None


def test_dispatch_subagent_handles_claude_not_installed(monkeypatch, tmp_path):
    _sys.path.insert(0, str(Path(__file__).parent.parent.parent / "scripts"))
    import orchestrator_runner as runner

    importlib.reload(runner)

    def raise_fnf(*a, **kw):
        raise FileNotFoundError()

    monkeypatch.setattr(runner.subprocess, "run", raise_fnf)
    result = runner.dispatch_subagent("source-collector", {}, dry_run_dir=None)
    assert result is None


def test_orchestrator_uses_gh_client_for_pr_create(
    tmp_path, monkeypatch, init_pipeline_host
):
    _sys.path.insert(0, str(Path(__file__).parent.parent.parent / "scripts"))
    import orchestrator_runner as runner
    import gh_client

    importlib.reload(runner)

    fake = gh_client.FakeGhClient(
        pr_list_for_branch=gh_client.GhResult(ok=True, value=None),
        pr_create=gh_client.GhResult(ok=True, value=321),
    )
    monkeypatch.setattr(runner, "GhClient", lambda *a, **kw: fake)

    init_pipeline_host()
    # CCE-101: this test's subject is pr_create, not the merge gate —
    # opt out so the default-auto gate doesn't real-sleep through its
    # 120s check-grace window (the gate has its own wiring test).
    cfg = tmp_path / ".engineering-docs-agent" / "config.yml"
    cfg.write_text(cfg.read_text() + "\nmerge: { policy: manual }\n")

    # Have to make git work for commit/push: stub push to succeed.
    # The fake mirrors subprocess's own contract — bytes unless the caller
    # asked for text. A str-always fake silently lied to every bytes-mode
    # caller in the runner (CCE-141's _prior_page_text is one).
    def _fake_run(*a, **kw):
        decoded = bool(
            kw.get("text") or kw.get("universal_newlines") or kw.get("encoding")
        )
        empty = "" if decoded else b""
        return type("R", (), {"returncode": 0, "stdout": empty, "stderr": empty})()

    monkeypatch.setattr(runner.subprocess, "run", _fake_run)
    rc = runner.run(tmp_path, dry_run_dir=FAKES, no_pr=False)
    assert any(c[0] == "pr_create" for c in fake.calls)


def test_stale_current_run_cleared_on_next_run(
    tmp_path, init_pipeline_host, read_current_run
):
    _sys.path.insert(0, str(Path(__file__).parent.parent.parent / "scripts"))
    import orchestrator_runner as runner

    importlib.reload(runner)

    state_path = init_pipeline_host()
    # Inject a 48h-old current_run
    state = json.loads(state_path.read_text())
    from datetime import datetime, timedelta, timezone

    stale_iso = (datetime.now(timezone.utc) - timedelta(hours=48)).isoformat()
    state["current_run"] = {
        "started_at": stale_iso,
        "head_sha": "olddeadbeef",
        "partial": False,
        "partial_reasons": [],
    }
    state_path.write_text(json.dumps(state))

    rc = runner.run(tmp_path, dry_run_dir=FAKES, no_pr=True)
    assert rc == 0

    cr = read_current_run(state_path)
    assert "stale_current_run_cleared" in cr["partial_reasons"]
    # New current_run replaces the old; the old head_sha is gone
    assert cr["head_sha"] != "olddeadbeef"


def test_zero_pr_run_does_not_write_whats_new(tmp_path, init_pipeline_host):
    _sys.path.insert(0, str(Path(__file__).parent.parent.parent / "scripts"))
    import orchestrator_runner as runner

    importlib.reload(runner)

    init_pipeline_host()
    rc = runner.run(tmp_path, dry_run_dir=FAKES_EMPTY, no_pr=True)
    assert rc == 0

    whats_new = tmp_path / "docs" / "site-src" / "whats-new.md"
    assert not whats_new.exists(), "no PRs => no whats_new write"


def test_git_push_failure_adds_partial(
    tmp_path, monkeypatch, init_pipeline_host, read_current_run
):
    _sys.path.insert(0, str(Path(__file__).parent.parent.parent / "scripts"))
    import orchestrator_runner as runner
    import gh_client

    importlib.reload(runner)

    fake = gh_client.FakeGhClient()
    monkeypatch.setattr(runner, "GhClient", lambda *a, **kw: fake)

    real_run = runner.subprocess.run

    def selective(cmd, *a, **kw):
        if cmd[:2] == ["git", "-C"] and "push" in cmd:
            return type(
                "R", (), {"returncode": 1, "stdout": "", "stderr": "remote rejected"}
            )()
        return real_run(cmd, *a, **kw)

    monkeypatch.setattr(runner.subprocess, "run", selective)

    state_path = init_pipeline_host()
    rc = runner.run(tmp_path, dry_run_dir=FAKES, no_pr=False)
    assert rc == 1

    cr = read_current_run(state_path)
    reasons = cr["partial_reasons"]
    assert any("push_failed" in r for r in reasons)


def test_invalid_subagent_json_logs_partial_continues(
    tmp_path, init_pipeline_host, read_current_run
):
    _sys.path.insert(0, str(Path(__file__).parent.parent.parent / "scripts"))
    import orchestrator_runner as runner

    importlib.reload(runner)

    state_path = init_pipeline_host()
    rc = runner.run(tmp_path, dry_run_dir=FAKES_BAD_JSON, no_pr=True)
    assert rc == 1  # pr_summarizer_invalid is blind (blocking reason)

    cr = read_current_run(state_path)
    reasons = cr["partial_reasons"]
    assert any("pr_summarizer_invalid" in r for r in reasons)


def test_multi_pr_runs_lists_all_in_whats_new(tmp_path, init_pipeline_host):
    _sys.path.insert(0, str(Path(__file__).parent.parent.parent / "scripts"))
    import orchestrator_runner as runner

    importlib.reload(runner)

    init_pipeline_host()
    rc = runner.run(tmp_path, dry_run_dir=FAKES_MULTI, no_pr=True)
    assert rc == 0

    whats_new = (tmp_path / "docs" / "site-src" / "whats-new.md").read_text()
    assert "PR #1" in whats_new
    assert "PR #2" in whats_new
    assert "PR #3" in whats_new


def test_compose_whats_new_preserves_frontmatter():
    """A leading YAML frontmatter block and the title H1 stay on top; the new
    entry sorts above older dated entries (reverse chronological)."""
    _sys.path.insert(0, str(Path(__file__).parent.parent.parent / "scripts"))
    import orchestrator_runner as runner

    existing = (
        "---\n"
        "title: What's New\n"
        "status: draft\n"
        "---\n\n"
        "# What's New\n\n"
        "## 2026-05-20\n"
        "- PR #99: earlier entry\n"
    )
    entry = "## 2026-05-27\n- PR #1: new entry\n\n"

    out = runner._compose_whats_new(existing, entry)

    assert out.startswith("---\n"), out[:80]
    assert (
        out.index("# What's New")
        < out.index("## 2026-05-27")
        < out.index("## 2026-05-20")
    )


def test_compose_whats_new_no_frontmatter_prepends():
    """Without frontmatter, behavior is the prior simple prepend; empty file
    yields just the entry."""
    _sys.path.insert(0, str(Path(__file__).parent.parent.parent / "scripts"))
    import orchestrator_runner as runner

    assert (
        runner._compose_whats_new("## old\n- x\n", "## new\n- y\n\n")
        == "## new\n- y\n\n## old\n- x\n"
    )
    assert runner._compose_whats_new("", "## new\n- y\n\n") == "## new\n- y\n\n"


def test_whats_new_prepend_preserves_frontmatter(tmp_path, init_pipeline_host):
    """run() must not push YAML frontmatter below the new entry. Reproduces the
    dry-run finding: the entry landed above the frontmatter, breaking parsing."""
    _sys.path.insert(0, str(Path(__file__).parent.parent.parent / "scripts"))
    import orchestrator_runner as runner
    import archive_indexes

    importlib.reload(runner)

    seeded = (
        "---\n"
        "title: What's New\n"
        "status: draft\n"
        "---\n\n"
        "# What's New\n\n"
        "## 2026-05-20\n"
        "- PR #99: earlier entry\n"
    )
    init_pipeline_host(seed_files={"docs/site-src/whats-new.md": seeded})

    rc = runner.run(tmp_path, dry_run_dir=FAKES, no_pr=True)
    assert rc == 0

    content = (tmp_path / "docs" / "site-src" / "whats-new.md").read_text()
    # Frontmatter must remain at line 1 so it still parses.
    assert content.startswith("---\n"), content[:80]
    assert archive_indexes.parse_frontmatter(content).get("title") == "What's New"
    # New entry present, below the title, above the older entry.
    assert "PR #1" in content
    assert (
        content.index("# What's New") < content.index("PR #1") < content.index("PR #99")
    )


def test_source_collector_error_propagates_partial(
    tmp_path, init_pipeline_host, read_current_run
):
    _sys.path.insert(0, str(Path(__file__).parent.parent.parent / "scripts"))
    import orchestrator_runner as runner

    importlib.reload(runner)

    state_path = init_pipeline_host()
    rc = runner.run(tmp_path, dry_run_dir=FAKES_SC_ERROR, no_pr=True)
    assert rc == 1  # source_collector_error is blind (blocking reason)

    cr = read_current_run(state_path)
    reasons = cr["partial_reasons"]
    assert any("source_collector_error" in r for r in reasons)
    assert any("source_collector_partial" in r for r in reasons)
    assert cr["partial"] is True


def test_run_surfaces_source_drift_in_whats_new_and_state(
    tmp_path, init_pipeline_host, read_current_run
):
    """Source-map stage wiring: run() must record drift in run state AND emit
    the 'Pages to review (source drift)' block in the What's-New entry.

    Closes spec-strategy gap (spec line 104): prior tests only exercised
    helper functions; this pins the orchestrator run() wiring end-to-end.
    """
    # Seed a page whose source_files glob matches the fake PR's changed file.
    # The fake source collector (FAKES) returns PR #1 with
    # files: [{"path": "backend/connectors/foo.py", ...}].
    connectors_page = "docs/site-src/core/connectors.md"
    connectors_content = (
        "---\nsource_files:\n  - backend/connectors/*.py\n---\n# Connectors\n"
    )
    state_path = init_pipeline_host(seed_files={connectors_page: connectors_content})

    # Overwrite the config with a site: block so compute_source_drift is active.
    site_block = (
        "site:\n"
        "  docs_dir: docs/site-src\n"
        "  sections:\n"
        "    - {key: core, path: core, title: Core}\n"
    )
    cfg = tmp_path / ".engineering-docs-agent" / "config.yml"
    cfg.write_text(CONFIG_YAML + site_block)

    rc = _run_inproc(tmp_path, FAKES)
    assert rc == 0, "run() must exit 0"

    # --- What's-New assertions ---
    whats_new = tmp_path / "docs" / "site-src" / "whats-new.md"
    assert whats_new.exists(), "whats-new.md must be written"
    content = whats_new.read_text()
    assert "### Pages to review (source drift)" in content, (
        "What's-New must contain the drift heading"
    )
    assert "core/connectors.md" in content, "What's-New must name the drifted page"
    assert "backend/connectors/foo.py" in content, (
        "What's-New must name the changed source file"
    )

    # --- Run-state assertion ---
    cr = read_current_run(state_path)
    expected_drift = [
        {"page": "core/connectors.md", "changed_sources": ["backend/connectors/foo.py"]}
    ]
    assert cr["source_drift"] == expected_drift, (
        f"source_drift run state mismatch: {cr.get('source_drift')}"
    )


def test_available_sections_passed_to_pr_summarizer(
    tmp_path, monkeypatch, init_pipeline_host
):
    _sys.path.insert(0, str(Path(__file__).parent.parent.parent / "scripts"))
    import orchestrator_runner as runner

    importlib.reload(runner)

    captured: list[dict] = []
    real = runner.dispatch_subagent

    def spying(name, inputs, *, dry_run_dir, cwd=None, out_reasons=None):
        if name == "pr-summarizer":
            captured.append(inputs)
        return real(name, inputs, dry_run_dir=dry_run_dir, out_reasons=out_reasons)

    monkeypatch.setattr(runner, "dispatch_subagent", spying)

    init_pipeline_host()
    # Create subdirs inside the lens root after git init (scan is filesystem-only)
    (tmp_path / "docs" / "site-src" / "core" / "architecture").mkdir()
    (tmp_path / "docs" / "site-src" / "core" / "operations").mkdir()

    runner.run(tmp_path, dry_run_dir=FAKES, no_pr=True)

    assert captured, "expected at least one pr-summarizer dispatch"
    sections = captured[0].get("available_sections", {})
    assert sections.get("core") == ["architecture", "operations"]


def test_available_sections_empty_when_no_subdirs(
    tmp_path, monkeypatch, init_pipeline_host
):
    _sys.path.insert(0, str(Path(__file__).parent.parent.parent / "scripts"))
    import orchestrator_runner as runner

    importlib.reload(runner)

    captured: list[dict] = []
    real = runner.dispatch_subagent

    def spying(name, inputs, *, dry_run_dir, cwd=None, out_reasons=None):
        if name == "pr-summarizer":
            captured.append(inputs)
        return real(name, inputs, dry_run_dir=dry_run_dir, out_reasons=out_reasons)

    monkeypatch.setattr(runner, "dispatch_subagent", spying)

    init_pipeline_host()  # core/ dir exists but has no subdirs
    runner.run(tmp_path, dry_run_dir=FAKES, no_pr=True)

    assert captured
    assert captured[0]["available_sections"] == {"core": []}


def test_available_sections_empty_when_lens_root_missing(
    tmp_path, monkeypatch, init_pipeline_host
):
    """Lens root that does not exist on disk → empty list, no crash."""
    _sys.path.insert(0, str(Path(__file__).parent.parent.parent / "scripts"))
    import orchestrator_runner as runner

    importlib.reload(runner)

    captured: list[dict] = []
    real = runner.dispatch_subagent

    def spying(name, inputs, *, dry_run_dir, cwd=None, out_reasons=None):
        if name == "pr-summarizer":
            captured.append(inputs)
        return real(name, inputs, dry_run_dir=dry_run_dir, out_reasons=out_reasons)

    monkeypatch.setattr(runner, "dispatch_subagent", spying)

    init_pipeline_host()
    # Add a second lens pointing to a dir that does not exist
    cfg = tmp_path / ".engineering-docs-agent" / "config.yml"
    cfg.write_text(
        cfg.read_text().replace(
            "    core: docs/site-src/core",
            "    core: docs/site-src/core\n    extra: docs/site-src/missing-dir",
        )
    )

    runner.run(tmp_path, dry_run_dir=FAKES, no_pr=True)

    assert captured
    assert captured[0]["available_sections"]["extra"] == []


def test_available_sections_excludes_hidden_dirs(
    tmp_path, monkeypatch, init_pipeline_host
):
    """Dot-prefixed dirs (e.g. .git in a broad lens root) are never routing targets."""
    _sys.path.insert(0, str(Path(__file__).parent.parent.parent / "scripts"))
    import orchestrator_runner as runner

    importlib.reload(runner)

    captured: list[dict] = []
    real = runner.dispatch_subagent

    def spying(name, inputs, *, dry_run_dir, cwd=None, out_reasons=None):
        if name == "pr-summarizer":
            captured.append(inputs)
        return real(name, inputs, dry_run_dir=dry_run_dir, out_reasons=out_reasons)

    monkeypatch.setattr(runner, "dispatch_subagent", spying)

    init_pipeline_host()
    # A hidden dir alongside a real section must not surface as a routing target.
    (tmp_path / "docs" / "site-src" / "core" / "operations").mkdir()
    (tmp_path / "docs" / "site-src" / "core" / ".hidden").mkdir()

    runner.run(tmp_path, dry_run_dir=FAKES, no_pr=True)

    assert captured
    assert captured[0]["available_sections"]["core"] == ["operations"]


def test_run_surfaces_core_drift_in_whats_new_and_state(
    tmp_path, init_pipeline_host, read_current_run
):
    """C2 drift-update stage wiring: a manifest core page that M flags as
    source-drifted is surfaced under 'Core pages to review (drift)' in the
    What's-New entry AND recorded in run state. Flag-only — pinned at the helper
    level (test_core_drift.py); here we pin the run() wiring end-to-end.

    The fake source collector (FAKES) returns PR #1 with a changed file
    backend/connectors/foo.py, so the seeded core page (source_files glob
    backend/connectors/*.py) drifts under M and, being in the manifest, surfaces
    under C2.
    """
    connectors_page = "docs/site-src/core/connectors.md"
    connectors_content = (
        "---\nsource_files:\n  - backend/connectors/*.py\n---\n# Connectors\n"
    )
    state_path = init_pipeline_host(seed_files={connectors_page: connectors_content})

    site_block = (
        "site:\n"
        "  docs_dir: docs/site-src\n"
        "  sections:\n"
        "    - {key: core, path: core, title: Core, generator: agent-authored}\n"
    )
    cfg = tmp_path / ".engineering-docs-agent" / "config.yml"
    cfg.write_text(CONFIG_YAML + site_block)

    manifest = {
        "version": 1,
        "pages": [
            {
                "key": "connectors",
                "title": "Connectors",
                "page": "core/connectors.md",
                "source_files": ["backend/connectors/*.py"],
            }
        ],
    }
    (tmp_path / "docs" / "site-src" / ".doc-core-manifest.json").write_text(
        json.dumps(manifest)
    )

    rc = _run_inproc(tmp_path, FAKES)
    assert rc == 0, "run() must exit 0"

    whats_new = (tmp_path / "docs" / "site-src" / "whats-new.md").read_text()
    assert "### Core pages to review (drift)" in whats_new
    assert "- core/connectors.md (source)" in whats_new

    cr = read_current_run(state_path)
    assert cr["core_drift"] == [{"page": "core/connectors.md", "reasons": ["source"]}]


def test_content_validator_dispatch_includes_plugin_root(
    tmp_path, monkeypatch, init_pipeline_host
):
    """CCE-67: orchestrator must pass plugin_root in content-validator inputs
    so the subagent can locate scripts/lint/lint_runner.py at the absolute
    plugin path (the plugin is vendored at .docs-agent-plugin/ in CI, not the
    host repo root)."""
    _sys.path.insert(0, str(Path(__file__).parent.parent.parent / "scripts"))
    import orchestrator_runner as runner

    importlib.reload(runner)

    captured: list[dict] = []
    real_dispatch = runner.dispatch_subagent

    def spying(name, inputs, *, dry_run_dir, cwd=None, out_reasons=None):
        if name == "content-validator":
            captured.append(dict(inputs))
        return real_dispatch(
            name, inputs, dry_run_dir=dry_run_dir, out_reasons=out_reasons
        )

    monkeypatch.setattr(runner, "dispatch_subagent", spying)

    init_pipeline_host()
    runner.run(tmp_path, dry_run_dir=FAKES, no_pr=True)

    assert captured, "expected at least one content-validator dispatch"
    payload = captured[0]
    assert "plugin_root" in payload, "content-validator payload missing plugin_root"
    plugin_root = Path(payload["plugin_root"])
    assert plugin_root.is_absolute(), f"plugin_root must be absolute, got {plugin_root}"
    lint_runner = plugin_root / "scripts" / "lint" / "lint_runner.py"
    assert lint_runner.exists(), (
        f"plugin_root does not resolve to a real lint_runner.py: {lint_runner}"
    )


def test_content_validator_payload_plugin_root_is_str_not_path(
    tmp_path, monkeypatch, init_pipeline_host
):
    """CCE-67: plugin_root must be passed as str, not Path, to remain
    JSON-serializable. Path objects round-trip through the dispatcher's JSON
    serialization differently across platforms (POSIX vs Windows)."""
    _sys.path.insert(0, str(Path(__file__).parent.parent.parent / "scripts"))
    import orchestrator_runner as runner

    importlib.reload(runner)

    captured: list[dict] = []
    real_dispatch = runner.dispatch_subagent

    def spying(name, inputs, *, dry_run_dir, cwd=None, out_reasons=None):
        if name == "content-validator":
            captured.append(dict(inputs))
        return real_dispatch(
            name, inputs, dry_run_dir=dry_run_dir, out_reasons=out_reasons
        )

    monkeypatch.setattr(runner, "dispatch_subagent", spying)

    init_pipeline_host()
    runner.run(tmp_path, dry_run_dir=FAKES, no_pr=True)

    assert captured
    plugin_root_value = captured[0]["plugin_root"]
    assert isinstance(plugin_root_value, str), (
        f"plugin_root must be a str for JSON, got {type(plugin_root_value).__name__}"
    )


FAKES_ROUTING = Path(__file__).parent / "fakes_routing"

# lens path `docs/site-src/` (trailing slash) mirrors the real dogfood config,
# which is proven to satisfy the lens-paths-covered-by-agent_editable_paths
# invariant against the "docs/site-src/**" glob.
CONFIG_YAML_ROUTING = """
docs:
  framework: mkdocs
  source_dir: docs/site-src
  whats_new_file: docs/site-src/whats-new.md
  agent_editable_paths: ["docs/site-src/**"]
  lens_paths:
    core: docs/site-src/
sources:
  git: { host: github }
trigger: { cron: "0 7 * * *", on_pr_merge: false }
gap_detection:
  allowlist_paths: ["scripts/**"]
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
site:
  docs_dir: docs/site-src
  theme: material
  sections:
    - { key: architecture, path: "architecture/", title: Architecture, generator: agent-authored }
    - { key: archive, path: "archive/", title: Decision Archive, generator: archive-index }
"""


def test_decision_target_routed_to_archive(tmp_path, monkeypatch):
    import importlib
    import json
    import subprocess

    _sys.path.insert(0, str(Path(__file__).parent.parent.parent / "scripts"))
    import orchestrator_runner as runner

    importlib.reload(runner)

    # Spy on the page-author dispatch so we can assert doc_kind is injected
    # into the frontmatter_template (the secondary spec requirement; the dry-run
    # write path uses default_frontmatter_text(), so the template only surfaces
    # in the dispatch payload, not in the written file).
    page_author_payloads: list[dict] = []
    real_dispatch = runner.dispatch_subagent

    def spying(name, inputs, *, dry_run_dir, cwd=None, out_reasons=None):
        if name == "page-author":
            page_author_payloads.append(inputs)
        return real_dispatch(
            name, inputs, dry_run_dir=dry_run_dir, cwd=cwd, out_reasons=out_reasons
        )

    eda = tmp_path / ".engineering-docs-agent"
    eda.mkdir(parents=True)
    (eda / "config.yml").write_text(CONFIG_YAML_ROUTING)
    (eda / "state.json").write_text(
        json.dumps({"version": "1", "dismissed_gap_flags": {}, "cursors": {}})
    )
    (tmp_path / "docs/site-src/architecture").mkdir(parents=True)
    (tmp_path / "docs/site-src/archive").mkdir(parents=True)
    subprocess.run(["git", "-C", str(tmp_path), "init", "-q"], check=True)
    subprocess.run(["git", "-C", str(tmp_path), "add", "."], check=True)
    subprocess.run(
        [
            "git",
            "-C",
            str(tmp_path),
            "-c",
            "user.email=t@t",
            "-c",
            "user.name=t",
            "commit",
            "-q",
            "-m",
            "init",
        ],
        check=True,
    )

    monkeypatch.setattr(runner, "dispatch_subagent", spying)
    runner.run(tmp_path, dry_run_dir=FAKES_ROUTING, no_pr=True)

    # The decision-kind create target must land under archive/, not architecture/.
    assert (tmp_path / "docs/site-src/archive/root-cause-sweep.md").exists()
    assert not (tmp_path / "docs/site-src/architecture/root-cause-sweep.md").exists()

    # doc_kind must be injected into the page-author frontmatter_template.
    routed = [
        p
        for p in page_author_payloads
        if str(p.get("target_path", "")).endswith("archive/root-cause-sweep.md")
    ]
    assert routed, "expected a page-author dispatch for the routed archive page"
    assert routed[0]["frontmatter_template"].get("doc_kind") == "decision"


# ---------------------------------------------------------------------------
# CCE-127: DOCS_AGENT_APP_TOKEN_STATUS degrades the run instead of killing it
#
# The workflow's App-token step now runs under continue-on-error and exports
# steps.app-token.outcome. Only the literal "failure" is a degradation: the
# run fell back to secrets.GITHUB_TOKEN, whose PRs never fire host CI, so the
# run must go partial to stop _maybe_auto_merge from merging unvalidated docs.
# "skipped" is the documented bare-host path (no DOCS_AGENT_APP_CLIENT_ID) and
# must stay silent, as must "success" and unset.
#
# The partial -> no-auto-merge interlock this rests on is already locked by
# tests/orchestrator/test_auto_merge.py::test_partial_run_skips_with_info_reason,
# which asserts the same outcome plus the absence of any pr_merge call.
# ---------------------------------------------------------------------------


def _seeded():
    return {"version": "1", "last_successful_run": {}}


def test_app_token_failure_flips_partial(
    tmp_path, monkeypatch, init_host, read_current_run
):
    """A failed App-token step degrades the run rather than killing the job."""
    state_path = init_host(_seeded(), CONFIG_YAML)
    monkeypatch.setenv("DOCS_AGENT_APP_TOKEN_STATUS", "failure")

    _run_inproc(tmp_path, FAKES)

    cr = read_current_run(state_path)
    assert cr["partial"] is True
    assert any(r.startswith("app_token_unavailable:") for r in cr["partial_reasons"])


def test_app_token_skipped_is_silent(
    tmp_path, monkeypatch, init_host, read_current_run
):
    """The bare-host path: no App configured is normal, not a degradation."""
    state_path = init_host(_seeded(), CONFIG_YAML)
    monkeypatch.setenv("DOCS_AGENT_APP_TOKEN_STATUS", "skipped")

    _run_inproc(tmp_path, FAKES)

    cr = read_current_run(state_path)
    # Asserts absence of this reason, not `partial is False` — a dry run may be
    # partial for unrelated causes, and asserting the flag would fail wrongly.
    assert not any(r.startswith("app_token_unavailable") for r in cr["partial_reasons"])


def test_app_token_unset_is_silent(tmp_path, monkeypatch, init_host, read_current_run):
    """Unset behaves identically to skipped — local shell runs set nothing."""
    state_path = init_host(_seeded(), CONFIG_YAML)
    monkeypatch.delenv("DOCS_AGENT_APP_TOKEN_STATUS", raising=False)

    _run_inproc(tmp_path, FAKES)

    cr = read_current_run(state_path)
    assert not any(r.startswith("app_token_unavailable") for r in cr["partial_reasons"])
