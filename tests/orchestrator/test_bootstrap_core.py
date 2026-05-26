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
