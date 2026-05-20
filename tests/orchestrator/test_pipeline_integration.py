from __future__ import annotations
import importlib
import json, subprocess, sys
import sys as _sys
from pathlib import Path

RUNNER = Path(__file__).parent.parent.parent / "scripts" / "orchestrator_runner.py"
FAKES = Path(__file__).parent / "fakes"
FAKES_BLOCK = Path(__file__).parent / "fakes_block"
FAKES_UNSAFE = Path(__file__).parent / "fakes_unsafe"
FAKES_SC_ERROR = Path(__file__).parent / "fakes_sc_error"


def _run_inproc(tmp_path: Path, fakes_dir: Path):
    """In-process run for monkeypatch-driven tests.

    Does NOT reload the module so monkeypatches applied by the caller survive.
    """
    _sys.path.insert(0, str(Path(__file__).parent.parent.parent / "scripts"))
    import orchestrator_runner as runner

    return runner.run(tmp_path, dry_run_dir=fakes_dir, no_pr=True)


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


def _init_host(tmp_path: Path, *, seed_files: dict[str, str] | None = None) -> Path:
    """Create a docs site skeleton, config, state, and initial git commit.

    `seed_files` is a mapping of repo-relative path → content for files that
    must exist in the initial commit (so they're in HEAD before the runner runs).
    """
    (tmp_path / "docs" / "site-src" / "core").mkdir(parents=True)
    (tmp_path / ".engineering-docs-agent").mkdir()
    (tmp_path / ".engineering-docs-agent" / "config.yml").write_text(CONFIG_YAML)
    state = tmp_path / ".engineering-docs-agent" / "state.json"
    state.write_text(
        json.dumps({"version": "1", "dismissed_gap_flags": {}, "cursors": {}})
    )
    for rel, body in (seed_files or {}).items():
        p = tmp_path / rel
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(body)

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
    return state


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


def test_pipeline_dry_run(tmp_path):
    state = _init_host(tmp_path)
    r = _run(tmp_path, FAKES)
    assert r.returncode == 0, r.stderr
    updated = json.loads(state.read_text())
    assert "current_run" in updated
    whats_new = tmp_path / "docs" / "site-src" / "whats-new.md"
    assert whats_new.exists(), "What's New file should be created"
    content = whats_new.read_text()
    assert "PR #1" in content
    assert "Gaps flagged" in content


def test_lint_block_unlinks_newly_created_file(tmp_path):
    """Create case: page-author writes a new file, validator blocks → unlink."""
    state = _init_host(tmp_path)
    target = tmp_path / "docs" / "site-src" / "core" / "connectors" / "foo.md"
    assert not target.exists(), "foo.md must not be in HEAD for the create-case"

    r = _run(tmp_path, FAKES_BLOCK)
    assert r.returncode == 0, r.stderr
    assert not target.exists(), "blocked create should be unlinked"

    updated = json.loads(state.read_text())
    reasons = updated["current_run"]["partial_reasons"]
    assert updated["current_run"]["partial"] is True
    assert any("lint_block" in reason for reason in reasons), reasons


def test_lint_block_restores_edited_file_from_head(tmp_path):
    """Edit case: file in HEAD with original content, working tree modified,
    validator blocks → git checkout HEAD -- restores original content."""
    rel = "docs/site-src/core/connectors/foo.md"
    original = "---\nstatus: published\n---\n# Original\n"
    state = _init_host(tmp_path, seed_files={rel: original})
    target = tmp_path / rel
    assert target.read_text() == original

    # Simulate page-author editing the file in the working tree.
    target.write_text("---\nstatus: draft\n---\n# Mutated by page-author\n")
    assert target.read_text() != original

    r = _run(tmp_path, FAKES_BLOCK)
    assert r.returncode == 0, r.stderr
    assert target.read_text() == original, "blocked edit should be restored from HEAD"

    updated = json.loads(state.read_text())
    assert updated["current_run"]["partial"] is True
    assert any(
        "lint_block" in reason for reason in updated["current_run"]["partial_reasons"]
    )


def test_jira_input_forwarded_to_source_collector(tmp_path, monkeypatch):
    """When config has sources.jira, orchestrator passes it under the `jira` key."""
    import sys as _sys

    _sys.path.insert(0, str(Path(__file__).parent.parent.parent / "scripts"))
    import orchestrator_runner

    captured_inputs: dict[str, dict] = {}
    real_dispatch = orchestrator_runner.dispatch_subagent

    def spying_dispatch(name, inputs, *, dry_run_dir):
        captured_inputs[name] = inputs
        return real_dispatch(name, inputs, dry_run_dir=dry_run_dir)

    monkeypatch.setattr(orchestrator_runner, "dispatch_subagent", spying_dispatch)

    state = _init_host(tmp_path)
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


def test_jira_context_threaded_to_pr_summarizer(tmp_path, monkeypatch):
    _sys.path.insert(0, str(Path(__file__).parent.parent.parent / "scripts"))
    import orchestrator_runner as runner

    importlib.reload(runner)

    captured: dict[str, list] = {"summarizer_inputs": []}
    real_dispatch = runner.dispatch_subagent

    def spying(name, inputs, *, dry_run_dir):
        if name == "pr-summarizer":
            captured["summarizer_inputs"].append(inputs)
        return real_dispatch(name, inputs, dry_run_dir=dry_run_dir)

    monkeypatch.setattr(runner, "dispatch_subagent", spying)

    _init_host(tmp_path)
    runner.run(tmp_path, dry_run_dir=FAKES, no_pr=True)

    assert len(captured["summarizer_inputs"]) == 1
    jc = captured["summarizer_inputs"][0]["jira_context"]
    assert len(jc) == 1
    assert jc[0]["key"] == "ADIS-235"


def test_voice_samples_loaded_and_passed_to_authoring(tmp_path, monkeypatch):
    _sys.path.insert(0, str(Path(__file__).parent.parent.parent / "scripts"))
    import orchestrator_runner as runner

    importlib.reload(runner)

    captured: list[dict] = []
    real_dispatch = runner.dispatch_subagent

    def spying(name, inputs, *, dry_run_dir):
        if name in ("page-author", "content-validator"):
            captured.append(
                {"name": name, "voice_samples": inputs.get("voice_samples")}
            )
        return real_dispatch(name, inputs, dry_run_dir=dry_run_dir)

    monkeypatch.setattr(runner, "dispatch_subagent", spying)

    _init_host(
        tmp_path,
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


def test_unsafe_page_path_filtered_logs_partial(tmp_path):
    """page_hint containing .. should not touch the filesystem."""
    _sys.path.insert(0, str(Path(__file__).parent.parent.parent / "scripts"))
    import orchestrator_runner as runner

    importlib.reload(runner)

    state_path = _init_host(tmp_path)
    rc = runner.run(tmp_path, dry_run_dir=FAKES_UNSAFE, no_pr=True)
    assert rc == 0

    # Filesystem outside the lens path was not touched
    assert not (tmp_path.parent.parent / "etc" / "passwd.md").exists()
    # No "etc" dir was created at any level
    assert not (tmp_path / ".." / "etc").exists()

    state = json.loads(state_path.read_text())
    reasons = state["current_run"]["partial_reasons"]
    assert any("unsafe_page_path" in r for r in reasons)


def test_gap_detector_receives_constructed_pr_id(tmp_path, monkeypatch):
    _sys.path.insert(0, str(Path(__file__).parent.parent.parent / "scripts"))
    import orchestrator_runner as runner

    importlib.reload(runner)

    captured: list[dict] = []
    real = runner.dispatch_subagent

    def spying(name, inputs, *, dry_run_dir):
        if name == "gap-detector":
            captured.append(inputs)
        return real(name, inputs, dry_run_dir=dry_run_dir)

    monkeypatch.setattr(runner, "dispatch_subagent", spying)
    monkeypatch.setenv("GITHUB_REPOSITORY", "myorg/myrepo")

    _init_host(tmp_path)
    runner.run(tmp_path, dry_run_dir=FAKES, no_pr=True)

    assert captured
    assert captured[0].get("pr_id") == "myorg/myrepo#1"


def test_archive_index_regenerated_after_authoring(tmp_path):
    _sys.path.insert(0, str(Path(__file__).parent.parent.parent / "scripts"))
    import orchestrator_runner as runner

    importlib.reload(runner)

    _init_host(
        tmp_path,
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


def test_orchestrator_uses_gh_client_for_pr_create(tmp_path, monkeypatch):
    _sys.path.insert(0, str(Path(__file__).parent.parent.parent / "scripts"))
    import orchestrator_runner as runner
    import gh_client

    importlib.reload(runner)

    fake = gh_client.FakeGhClient(
        pr_list_for_branch=gh_client.GhResult(ok=True, value=None),
        pr_create=gh_client.GhResult(ok=True, value=321),
    )
    monkeypatch.setattr(runner, "GhClient", lambda *a, **kw: fake)

    _init_host(tmp_path)
    # Have to make git work for commit/push: stub push to succeed
    monkeypatch.setattr(
        runner.subprocess,
        "run",
        lambda *a, **kw: type("R", (), {"returncode": 0, "stdout": "", "stderr": ""})(),
    )
    rc = runner.run(tmp_path, dry_run_dir=FAKES, no_pr=False)
    assert any(c[0] == "pr_create" for c in fake.calls)


def test_stale_current_run_cleared_on_next_run(tmp_path):
    _sys.path.insert(0, str(Path(__file__).parent.parent.parent / "scripts"))
    import orchestrator_runner as runner

    importlib.reload(runner)

    state_path = _init_host(tmp_path)
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

    state = json.loads(state_path.read_text())
    assert "stale_current_run_cleared" in state["current_run"]["partial_reasons"]
    # New current_run replaces the old; the old head_sha is gone
    assert state["current_run"]["head_sha"] != "olddeadbeef"


def test_source_collector_error_propagates_partial(tmp_path):
    _sys.path.insert(0, str(Path(__file__).parent.parent.parent / "scripts"))
    import orchestrator_runner as runner

    importlib.reload(runner)

    state_path = _init_host(tmp_path)
    rc = runner.run(tmp_path, dry_run_dir=FAKES_SC_ERROR, no_pr=True)
    assert rc == 0

    state = json.loads(state_path.read_text())
    reasons = state["current_run"]["partial_reasons"]
    assert any("source_collector_error" in r for r in reasons)
    assert any("source_collector_partial" in r for r in reasons)
    assert state["current_run"]["partial"] is True
