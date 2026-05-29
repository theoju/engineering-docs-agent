from __future__ import annotations

import json as _json
import subprocess
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "scripts"))
import orchestrator_runner as runner  # noqa: E402


def test_page_target_is_editable():
    globs = ["docs/site-src/**"]
    assert runner._page_target_is_editable("docs/site-src/core/api.md", globs) is True
    assert runner._page_target_is_editable("scripts/x.py", globs) is False
    # No globs configured -> permissive (matches the nightly loop's behavior).
    assert runner._page_target_is_editable("anything/at/all.md", []) is True


def test_synthesize_core_page_writes_c2_frontmatter(tmp_path):
    import yaml

    page = {
        "key": "api",
        "title": "API layer",
        "page": "core/api.md",
        "source_files": ["backend/api/**/*.py", "backend/api/router.py"],
    }
    target = tmp_path / "core" / "api.md"
    target.parent.mkdir(parents=True)
    runner._synthesize_core_page(target, page, today="2026-05-26")

    text = target.read_text()
    fm = yaml.safe_load(text.split("---", 2)[1])
    assert fm["description"] == "API layer"
    assert fm["source_files"] == ["backend/api/**/*.py", "backend/api/router.py"]
    assert fm["last_reviewed"] == "2026-05-26"
    assert fm["status"] == "draft"


def test_synthesize_core_page_body_is_diagram_free_with_human_stub(tmp_path):
    page = {"key": "x", "title": "X", "page": "core/x.md", "source_files": ["a.py"]}
    target = tmp_path / "x.md"
    runner._synthesize_core_page(target, page, today="2026-05-26")
    text = target.read_text()
    assert "TODO(human)" in text
    assert "```mermaid" not in text
    assert "`a.py`" in text  # source inventory rendered


_CONFIG_WITH_SITE = """
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
    - key: home
      path: index.md
      title: Home
    - key: core
      path: core/
      title: Core
      generator: agent-authored
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

_MANIFEST = {
    "version": 1,
    "pages": [
        {
            "key": "api",
            "title": "Api",
            "page": "core/api.md",
            "source_files": ["backend/api/**/*.py"],
        },
        {
            "key": "storage",
            "title": "Storage",
            "page": "core/storage.md",
            "source_files": ["backend/storage/**/*.py"],
        },
    ],
}


def _host(tmp_path: Path, *, config: str = _CONFIG_WITH_SITE, manifest=_MANIFEST):
    (tmp_path / ".engineering-docs-agent").mkdir(parents=True, exist_ok=True)
    (tmp_path / ".engineering-docs-agent" / "config.yml").write_text(config)
    docs = tmp_path / "docs" / "site-src"
    docs.mkdir(parents=True, exist_ok=True)
    if manifest is not None:
        (docs / ".doc-core-manifest.json").write_text(_json.dumps(manifest))
    return tmp_path


def _spy(calls, result=({"ok": True}, [])):
    def fake(name, inputs, *, dry_run_dir, cwd=None):
        calls.append({"name": name, "inputs": inputs})
        return result

    return fake


def test_resolve_docs_dir_prefers_site_then_source_dir():
    assert (
        runner._resolve_docs_dir(
            {"site": {"docs_dir": "a"}, "docs": {"source_dir": "b"}}
        )
        == "a"
    )
    assert runner._resolve_docs_dir({"docs": {"source_dir": "b"}}) == "b"
    assert runner._resolve_docs_dir({}) is None


def test_bootstrap_authors_missing_pages(tmp_path, monkeypatch):
    _host(tmp_path)
    calls = []
    monkeypatch.setattr(runner, "dispatch_validated", _spy(calls))
    rc = runner.run_bootstrap_core(
        tmp_path, dry_run_dir=tmp_path / "fakes", today="2026-05-26"
    )
    assert rc == 0
    api = tmp_path / "docs/site-src/core/api.md"
    storage = tmp_path / "docs/site-src/core/storage.md"
    assert api.exists() and storage.exists()
    import yaml

    fm = yaml.safe_load(api.read_text().split("---", 2)[1])
    assert fm["source_files"] == ["backend/api/**/*.py"]
    assert fm["last_reviewed"] == "2026-05-26"
    assert fm["status"] == "draft"
    assert len(calls) == 2


def test_bootstrap_is_idempotent_skips_existing(tmp_path, monkeypatch):
    _host(tmp_path)
    existing = tmp_path / "docs/site-src/core/api.md"
    existing.parent.mkdir(parents=True, exist_ok=True)
    existing.write_text("PRE-EXISTING\n")
    calls = []
    monkeypatch.setattr(runner, "dispatch_validated", _spy(calls))
    rc = runner.run_bootstrap_core(
        tmp_path, dry_run_dir=tmp_path / "fakes", today="2026-05-26"
    )
    assert rc == 0
    assert existing.read_text() == "PRE-EXISTING\n"
    assert len(calls) == 1
    assert calls[0]["inputs"]["target_path"].endswith("core/storage.md")


def test_bootstrap_dispatch_failure_records_reason_and_continues(
    tmp_path, monkeypatch, capsys
):
    _host(tmp_path)
    seq = [(None, ["boom"]), ({"ok": True}, [])]

    def fake(name, inputs, *, dry_run_dir, cwd=None):
        return seq.pop(0)

    monkeypatch.setattr(runner, "dispatch_validated", fake)
    rc = runner.run_bootstrap_core(
        tmp_path, dry_run_dir=tmp_path / "fakes", today="2026-05-26"
    )
    assert rc == 0
    ledger = _json.loads(capsys.readouterr().out)
    assert "boom" in ledger["reasons"]
    assert len(ledger["authored"]) == 1


def test_bootstrap_no_manifest_is_noop(tmp_path, monkeypatch):
    _host(tmp_path, manifest=None)
    calls = []
    monkeypatch.setattr(runner, "dispatch_validated", _spy(calls))
    rc = runner.run_bootstrap_core(
        tmp_path, dry_run_dir=tmp_path / "fakes", today="2026-05-26"
    )
    assert rc == 0
    assert calls == []
    assert not (tmp_path / "docs/site-src/core/api.md").exists()


def test_bootstrap_empty_manifest_is_noop(tmp_path, monkeypatch):
    _host(tmp_path, manifest={"version": 1, "pages": []})
    calls = []
    monkeypatch.setattr(runner, "dispatch_validated", _spy(calls))
    rc = runner.run_bootstrap_core(
        tmp_path, dry_run_dir=tmp_path / "fakes", today="2026-05-26"
    )
    assert rc == 0
    assert calls == []


def test_bootstrap_corrupt_manifest_is_noop(tmp_path, monkeypatch):
    # A corrupt manifest must degrade to a clean no-op, never crash.
    _host(tmp_path, manifest=None)
    (tmp_path / "docs/site-src/.doc-core-manifest.json").write_text("{ not valid json")
    calls = []
    monkeypatch.setattr(runner, "dispatch_validated", _spy(calls))
    rc = runner.run_bootstrap_core(
        tmp_path, dry_run_dir=tmp_path / "fakes", today="2026-05-26"
    )
    assert rc == 0
    assert calls == []
    assert not (tmp_path / "docs/site-src/core/api.md").exists()


def test_bootstrap_ok_false_payload_is_recorded(tmp_path, monkeypatch, capsys):
    _host(tmp_path)

    def fake(name, inputs, *, dry_run_dir, cwd=None):
        return ({"ok": False, "error": "validator rejected"}, [])

    monkeypatch.setattr(runner, "dispatch_validated", fake)
    rc = runner.run_bootstrap_core(
        tmp_path, dry_run_dir=tmp_path / "fakes", today="2026-05-26"
    )
    assert rc == 0
    ledger = _json.loads(capsys.readouterr().out)
    assert ledger["authored"] == []
    assert any(
        "page_author_error" in r and "validator rejected" in r
        for r in ledger["reasons"]
    )
    # the page must NOT have been written
    assert not (tmp_path / "docs/site-src/core/api.md").exists()


def test_bootstrap_rejects_non_editable_page(tmp_path, monkeypatch, capsys):
    cfg = _CONFIG_WITH_SITE.replace(
        'agent_editable_paths: ["docs/site-src/**"]',
        'agent_editable_paths: ["docs/site-src/sandbox/**"]',
    ).replace("core: docs/site-src/core", "core: docs/site-src/sandbox")
    _host(tmp_path, config=cfg)
    calls = []
    monkeypatch.setattr(runner, "dispatch_validated", _spy(calls))
    rc = runner.run_bootstrap_core(
        tmp_path, dry_run_dir=tmp_path / "fakes", today="2026-05-26"
    )
    assert rc == 0
    assert calls == []
    ledger = _json.loads(capsys.readouterr().out)
    assert any(r.startswith("unsafe_page_path:") for r in ledger["reasons"])


def test_main_routes_bootstrap_core(monkeypatch):
    seen = {}

    def fake_bootstrap(repo_root, *, dry_run_dir, today=None):
        seen["repo_root"] = repo_root
        seen["dry_run_dir"] = dry_run_dir
        seen["today"] = today
        return 0

    def fake_run(*a, **k):
        seen["run_called"] = True
        return 0

    monkeypatch.setattr(runner, "run_bootstrap_core", fake_bootstrap)
    monkeypatch.setattr(runner, "run", fake_run)
    monkeypatch.setattr(
        sys,
        "argv",
        [
            "prog",
            "--repo-root",
            "/x",
            "--bootstrap-core",
            "--dry-run-subagents",
            "/fakes",
            "--today",
            "2026-05-26",
        ],
    )
    rc = runner.main()
    assert rc == 0
    assert seen["today"] == "2026-05-26"
    assert str(seen["repo_root"]) == "/x"
    assert "run_called" not in seen  # nightly run() not invoked


def test_main_default_routes_nightly_run(monkeypatch):
    seen = {}
    monkeypatch.setattr(runner, "run", lambda *a, **k: seen.update({"run": True}) or 0)
    monkeypatch.setattr(
        runner,
        "run_bootstrap_core",
        lambda *a, **k: seen.update({"bootstrap": True}) or 0,
    )
    monkeypatch.setattr(sys, "argv", ["prog", "--repo-root", "/x"])
    rc = runner.main()
    assert rc == 0
    assert seen == {"run": True}


_RUNNER = Path(__file__).resolve().parents[2] / "scripts" / "orchestrator_runner.py"
_FAKES_BOOTSTRAP = Path(__file__).parent / "fakes_bootstrap"


def _run_bootstrap_cli(repo_root: Path):
    return subprocess.run(
        [
            sys.executable,
            str(_RUNNER),
            "--repo-root",
            str(repo_root),
            "--bootstrap-core",
            "--dry-run-subagents",
            str(_FAKES_BOOTSTRAP),
            "--today",
            "2026-05-26",
        ],
        capture_output=True,
        text=True,
    )


def test_bootstrap_core_e2e_creates_then_idempotent(tmp_path):
    _host(tmp_path)
    r = _run_bootstrap_cli(tmp_path)
    assert r.returncode == 0, r.stderr
    api = tmp_path / "docs/site-src/core/api.md"
    storage = tmp_path / "docs/site-src/core/storage.md"
    assert api.exists() and storage.exists()
    text = api.read_text()
    assert "last_reviewed: '2026-05-26'" in text
    assert "status: draft" in text
    assert "TODO(human)" in text
    assert "```mermaid" not in text

    before = api.read_text()
    r2 = _run_bootstrap_cli(tmp_path)
    assert r2.returncode == 0, r2.stderr
    ledger = _json.loads(r2.stdout)
    assert api.read_text() == before  # idempotent: not rewritten
    assert sorted(ledger["skipped_existing"]) == [
        "docs/site-src/core/api.md",
        "docs/site-src/core/storage.md",
    ]
    assert ledger["authored"] == []


def _spy_with_body_writer(calls, body_writer, result=({"ok": True}, [])):
    """A fake dispatch_validated that ALSO writes the page body, mimicking
    the production page-author (which uses its Write tool before returning).
    ``body_writer(target_path: Path, inputs: dict) -> str`` writes the text to
    disk; the spy returns the same ok=True payload regardless.
    """

    def fake(name, inputs, *, dry_run_dir, cwd=None):
        calls.append({"name": name, "inputs": inputs})
        target = Path(inputs["target_path"])
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(body_writer(target, inputs))
        return result

    return fake


def _body_with_bad_yaml(target: Path, inputs: dict) -> str:
    # The CCE-15-style failure: an unescaped colon inside a backticked value.
    return (
        "---\n"
        "description: `additionalProperties: false`\n"
        "source_files: []\n"
        "last_reviewed: '2026-05-26'\n"
        "status: draft\n"
        "---\n"
        "# Body\n"
    )


def _body_with_thin_description(target: Path, inputs: dict) -> str:
    return (
        "---\n"
        "description: API\n"
        "source_files: []\n"
        "last_reviewed: '2026-05-26'\n"
        "status: draft\n"
        "---\n"
        "# Body\n"
    )


def _body_ok(target: Path, inputs: dict) -> str:
    return (
        "---\n"
        "description: Routes HTTP requests to handlers and serialises responses.\n"
        "source_files: []\n"
        "last_reviewed: '2026-05-26'\n"
        "status: draft\n"
        "---\n"
        "# Body\n"
    )


def _body_no_frontmatter(target: Path, inputs: dict) -> str:
    return "# Body without a frontmatter block\n\nSome prose.\n"


def test_bootstrap_rejects_and_deletes_bad_yaml(tmp_path, monkeypatch, capsys):
    _host(
        tmp_path,
        manifest={
            "version": 1,
            "pages": [
                {
                    "key": "api",
                    "title": "Api",
                    "page": "core/api.md",
                    "source_files": [],
                },
            ],
        },
    )
    calls = []
    monkeypatch.setattr(
        runner,
        "dispatch_validated",
        _spy_with_body_writer(calls, _body_with_bad_yaml),
    )
    rc = runner.run_bootstrap_core(tmp_path, dry_run_dir=None, today="2026-05-26")
    assert rc == 0
    ledger = _json.loads(capsys.readouterr().out)
    assert ledger["authored"] == []
    assert any("frontmatter_parse_error" in r for r in ledger["reasons"]), ledger
    # The file the spy wrote was deleted so re-run will retry.
    assert not (tmp_path / "docs/site-src/core/api.md").exists()


def test_bootstrap_rejects_and_deletes_thin_description(tmp_path, monkeypatch, capsys):
    _host(
        tmp_path,
        manifest={
            "version": 1,
            "pages": [
                {
                    "key": "api",
                    "title": "Api",
                    "page": "core/api.md",
                    "source_files": [],
                },
            ],
        },
    )
    calls = []
    monkeypatch.setattr(
        runner,
        "dispatch_validated",
        _spy_with_body_writer(calls, _body_with_thin_description),
    )
    rc = runner.run_bootstrap_core(tmp_path, dry_run_dir=None, today="2026-05-26")
    assert rc == 0
    ledger = _json.loads(capsys.readouterr().out)
    assert ledger["authored"] == []
    assert any("description_quality" in r for r in ledger["reasons"]), ledger
    assert not (tmp_path / "docs/site-src/core/api.md").exists()


def test_bootstrap_rejects_and_deletes_missing_frontmatter(
    tmp_path, monkeypatch, capsys
):
    _host(
        tmp_path,
        manifest={
            "version": 1,
            "pages": [
                {
                    "key": "api",
                    "title": "Api",
                    "page": "core/api.md",
                    "source_files": [],
                },
            ],
        },
    )
    calls = []
    monkeypatch.setattr(
        runner,
        "dispatch_validated",
        _spy_with_body_writer(calls, _body_no_frontmatter),
    )
    rc = runner.run_bootstrap_core(tmp_path, dry_run_dir=None, today="2026-05-26")
    assert rc == 0
    ledger = _json.loads(capsys.readouterr().out)
    assert ledger["authored"] == []
    assert any("frontmatter_missing" in r for r in ledger["reasons"]), ledger
    assert not (tmp_path / "docs/site-src/core/api.md").exists()


def test_bootstrap_accepts_substantial_description(tmp_path, monkeypatch, capsys):
    _host(
        tmp_path,
        manifest={
            "version": 1,
            "pages": [
                {
                    "key": "api",
                    "title": "Api",
                    "page": "core/api.md",
                    "source_files": [],
                },
            ],
        },
    )
    calls = []
    monkeypatch.setattr(
        runner,
        "dispatch_validated",
        _spy_with_body_writer(calls, _body_ok),
    )
    rc = runner.run_bootstrap_core(tmp_path, dry_run_dir=None, today="2026-05-26")
    assert rc == 0
    ledger = _json.loads(capsys.readouterr().out)
    assert ledger["authored"] == ["docs/site-src/core/api.md"]
    assert not any("description_quality" in r for r in ledger["reasons"])
    assert (tmp_path / "docs/site-src/core/api.md").exists()


def test_bootstrap_rerun_retries_only_rejected_pages(tmp_path, monkeypatch, capsys):
    _host(
        tmp_path,
        manifest={
            "version": 1,
            "pages": [
                {
                    "key": "api",
                    "title": "Api",
                    "page": "core/api.md",
                    "source_files": [],
                },
                {
                    "key": "storage",
                    "title": "Storage",
                    "page": "core/storage.md",
                    "source_files": [],
                },
            ],
        },
    )
    # First run: api gets thin desc, storage gets ok.
    state = {
        "page_to_body": {
            "core/api.md": _body_with_thin_description,
            "core/storage.md": _body_ok,
        }
    }

    def fake1(name, inputs, *, dry_run_dir, cwd=None):
        # docs_dir is docs/site-src; everything after it is the manifest page
        # key (e.g. core/api.md) which is also the key in state["page_to_body"].
        # Use the suffix directly rather than reconstructing a flat "core/<leaf>"
        # so this stays correct for any nesting depth.
        rel = (
            Path(inputs["target_path"])
            .relative_to(tmp_path)
            .as_posix()
            .split("docs/site-src/", 1)[-1]
        )
        body = state["page_to_body"][rel](Path(inputs["target_path"]), inputs)
        Path(inputs["target_path"]).parent.mkdir(parents=True, exist_ok=True)
        Path(inputs["target_path"]).write_text(body)
        return ({"ok": True}, [])

    monkeypatch.setattr(runner, "dispatch_validated", fake1)
    rc = runner.run_bootstrap_core(tmp_path, dry_run_dir=None, today="2026-05-26")
    assert rc == 0
    ledger_1 = _json.loads(capsys.readouterr().out)
    assert ledger_1["authored"] == ["docs/site-src/core/storage.md"]
    assert any("description_quality" in r for r in ledger_1["reasons"])
    assert not (tmp_path / "docs/site-src/core/api.md").exists()
    assert (tmp_path / "docs/site-src/core/storage.md").exists()

    # Second run: api retries with a substantial description; storage is
    # skipped_existing (idempotency).
    state["page_to_body"]["core/api.md"] = _body_ok
    calls2: list = []
    monkeypatch.setattr(
        runner, "dispatch_validated", _spy_with_body_writer(calls2, _body_ok)
    )
    rc = runner.run_bootstrap_core(tmp_path, dry_run_dir=None, today="2026-05-26")
    assert rc == 0
    ledger_2 = _json.loads(capsys.readouterr().out)
    assert ledger_2["authored"] == ["docs/site-src/core/api.md"]
    assert ledger_2["skipped_existing"] == ["docs/site-src/core/storage.md"]
    # Only the previously-rejected page was retried.
    assert len(calls2) == 1
    assert calls2[0]["inputs"]["target_path"].endswith("core/api.md")


def test_bootstrap_progress_file_is_removed_at_end_of_run(tmp_path, monkeypatch):
    _host(
        tmp_path,
        manifest={
            "version": 1,
            "pages": [
                {
                    "key": "api",
                    "title": "Api",
                    "page": "core/api.md",
                    "source_files": [],
                },
            ],
        },
    )
    calls = []
    monkeypatch.setattr(
        runner,
        "dispatch_validated",
        _spy_with_body_writer(calls, _body_ok),
    )
    runner.run_bootstrap_core(tmp_path, dry_run_dir=None, today="2026-05-26")
    assert not (
        tmp_path / ".engineering-docs-agent" / "bootstrap.progress.json"
    ).exists()


def test_bootstrap_progress_file_records_inflight_state(tmp_path, monkeypatch):
    """During a run, capture the progress file's state at the moment of dispatch
    so we can assert current_page reflects live state.
    """
    _host(
        tmp_path,
        manifest={
            "version": 1,
            "pages": [
                {
                    "key": "api",
                    "title": "Api",
                    "page": "core/api.md",
                    "source_files": [],
                },
                {
                    "key": "storage",
                    "title": "Storage",
                    "page": "core/storage.md",
                    "source_files": [],
                },
            ],
        },
    )
    captured: list = []

    def fake_capture(name, inputs, *, dry_run_dir, cwd=None):
        progress_path = tmp_path / ".engineering-docs-agent" / "bootstrap.progress.json"
        captured.append(_json.loads(progress_path.read_text()))
        target = Path(inputs["target_path"])
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(_body_ok(target, inputs))
        return ({"ok": True}, [])

    monkeypatch.setattr(runner, "dispatch_validated", fake_capture)
    runner.run_bootstrap_core(tmp_path, dry_run_dir=None, today="2026-05-26")
    assert captured[0]["current_index"] == 1
    assert captured[0]["current_page"] == "docs/site-src/core/api.md"
    assert captured[1]["current_index"] == 2
    assert captured[1]["current_page"] == "docs/site-src/core/storage.md"
    # Final state after the run is gone (test above covers it).


def test_bootstrap_progress_advances_through_invalid_and_unsafe_entries(
    tmp_path, monkeypatch
):
    """Stage 4 Important: invalid manifest entries and unsafe paths must still
    advance current_index so the in-flight progress count matches the manifest
    length. Without the fix, the three early-exit ``continue`` branches in
    run_bootstrap_core skip ``progress.begin_page()`` and current_index lags
    behind the actual manifest position seen by the operator."""
    _host(
        tmp_path,
        manifest={
            "version": 1,
            "pages": [
                "not-a-dict",
                {"page": "../../../outside.md"},
                {"page": "../../scripts/escape.md"},
                {
                    "key": "ok",
                    "title": "Ok",
                    "page": "core/ok.md",
                    "source_files": [],
                },
            ],
        },
    )
    captured: list = []

    def fake_capture(name, inputs, *, dry_run_dir, cwd=None):
        progress_path = tmp_path / ".engineering-docs-agent" / "bootstrap.progress.json"
        captured.append(_json.loads(progress_path.read_text()))
        target = Path(inputs["target_path"])
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(_body_ok(target, inputs))
        return ({"ok": True}, [])

    monkeypatch.setattr(runner, "dispatch_validated", fake_capture)
    runner.run_bootstrap_core(tmp_path, dry_run_dir=None, today="2026-05-26")
    assert len(captured) == 1
    snap = captured[0]
    # The valid page is the 4th entry; its dispatch sees current_index=4
    # because the three early-exit branches each advanced the counter past
    # their invalid/unsafe entry.
    assert snap["current_index"] == 4
    assert snap["current_page"] == "docs/site-src/core/ok.md"
    failed_reasons = [f["reason"] for f in snap["failed"]]
    assert len(snap["failed"]) == 3
    assert any("manifest_page_invalid" in r for r in failed_reasons)
    assert sum("unsafe_page_path" in r for r in failed_reasons) == 2
