# C2 sub-plan 3 — `run_bootstrap_core` Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add a dedicated, idempotent `run_bootstrap_core` entry that reads the `.doc-core-manifest.json` artifact (from C2 sub-plan 2) and authors the still-missing canonical-core pages — C2 agent-authored frontmatter, a `source_files`-backed skeleton, and `TODO(human)` rationale stubs — diagram-free, create-missing only.

**Architecture:** A new `--bootstrap-core` CLI mode dispatches to `run_bootstrap_core(repo_root, *, dry_run_dir, today=None)` — a sibling of the nightly `run()`, **not** a flag threaded into it. It resolves `docs_dir`, loads the manifest, and for each declared page that has no file yet, dispatches the unchanged `page-author` agent. In dry-run (the unit/e2e seam) a manifest-aware synthesizer writes a deterministic stand-in: agent-authored frontmatter built from the manifest's `source_files` + an injected `today`, plus a diagram-free body with human stubs. Real C1 citation pins are the production agent's job (out of dry-run scope), exactly as the nightly dry-run synth writes a canned body. The frontmatter shape lives in `frontmatter_contract.py` (the single source of truth that sub-plan 1 established), and the editability guard is factored into a tiny shared helper reused by both the nightly loop and bootstrap.

**Tech Stack:** Python 3.9 stdlib-first; pytest (TDD, fixture-driven, production CLI dispatch monkeypatched); `python3 -m pytest` (bare `pytest` may not resolve locally).

**Branch:** `feat/CCE-28-run-bootstrap-core` (already created off `main`; this plan is committed to it). References **CCE-28**.

---

## Context the implementer needs (read once)

This is the third of four C2 sub-plans. Sub-plan 1 (PR #33, merged) made `frontmatter_schema` generator-aware via `scripts/frontmatter_contract.py`. Sub-plan 2 (PR #34, merged) added `scripts/core_manifest.py` (`detect_core_manifest` / `write_core_manifest`) which writes `<docs_dir>/.doc-core-manifest.json`. **This sub-plan consumes that artifact.** Defer the drift-update stage to sub-plan 4.

**Real symbols this plan builds on (verified current):**

- `scripts/frontmatter_contract.py:13-14` — `DEFAULT_REQUIRED = ("status", "sources", "synthesized_into")` and `AGENT_AUTHORED_REQUIRED = ("description", "source_files", "last_reviewed", "status")`.
- `scripts/frontmatter_contract.py:87-94` — `default_frontmatter_dict(...)` and `default_frontmatter_text()` (the patterns the new helpers mirror; the module is **yaml-free by design** — build text by hand).
- `scripts/orchestrator_runner.py:615` — `def run(repo_root: Path, *, dry_run_dir: Path | None, no_pr: bool) -> int`.
- `scripts/orchestrator_runner.py:53-59` — `load_json(p)` → `{}` if missing, `None` on bad JSON, else dict.
- `scripts/orchestrator_runner.py:486-519` — `dispatch_validated(name, inputs, *, dry_run_dir, cwd=None) -> tuple[dict|None, list[str]]` (in dry-run, returns the parsed `<dry_run_dir>/fake_<name>.json` or `None` if missing).
- `scripts/orchestrator_runner.py:746-808` — the nightly authoring loop (the containment + `agent_editable_paths` guards at 764-773, and the dry-run synth at 804-808).
- `scripts/orchestrator_runner.py:1158-1164` — `main()` (flag-based; `--repo-root`, `--dry-run-subagents`, `--no-pr`).
- `scripts/state_io.py:161-176` — `load_config_validated(path) -> dict` (raises `ConfigError`); both are imported into `orchestrator_runner`'s namespace and used at `run()` lines 622-627.
- `scripts/state_io.py:222-248` — `load_voice_samples(repo_root, config) -> list[dict]`.
- `templates/config.schema.json:93-136` — the `site:` block schema. `site` is **optional**; when present it requires `docs_dir` + `sections`; each section requires `key`/`path`/`title` with `additionalProperties: false`; `generator` ∈ {`archive-index`, `api-extract`, `changelog`, `agent-authored`}.
- `templates/site.default.yaml:1-31` — the default site YAML; its agent-authored section is keyed `architecture` (the template) while the dogfood config uses `core` — **never hardcode either name**; locate by `generator: agent-authored`.

**Manifest artifact shape** (`<docs_dir>/.doc-core-manifest.json`, written by sub-plan 2):

```json
{
  "version": 1,
  "pages": [
    {
      "key": "api",
      "title": "Api",
      "page": "core/api.md",
      "source_files": ["backend/api/**/*.py"]
    }
  ]
}
```

`page` is `"<section_path>/<key>.md"`, relative to `docs_dir`. The on-disk target is `repo_root / docs_dir / page["page"]`.

**Design decisions locked for this sub-plan:**

1. **Read-only manifest consumer.** Bootstrap never re-detects or re-writes the manifest (that is setup's seam). Missing manifest → no-op (return 0). Empty `pages` → no-op.
2. **`docs_dir` resolution is defensive and generic.** Prefer `config["site"]["docs_dir"]`; fall back to `config["docs"]["source_dir"]`. (The runtime `site:` block is optional; some hosts only set `docs.source_dir`.)
3. **Idempotent create-missing.** A page whose file already exists is skipped (recorded under `skipped_existing`) — never overwritten, never re-dispatched.
4. **Best-effort per page.** A per-page dispatch failure records a reason and continues (mirrors the nightly loop); bootstrap never aborts mid-manifest.
5. **No diagrams.** The synthesized body contains no ` ```mermaid ` fences (waits on C3).
6. **C1 pins are production-only.** The dry-run synth writes no fabricated `<!--pin:-->` tokens (a fake pin would trip the C1 verifier); real pins come from the `page-author` agent, which is reused unchanged.
7. **`page-author` agent unchanged.** Only caller-supplied inputs differ; no `agents/*.md` edits.

---

## File structure

- **Modify** `scripts/frontmatter_contract.py` — add `agent_authored_frontmatter_dict(...)` and `agent_authored_frontmatter_text(...)` (the C2 frontmatter shape; single source of truth).
- **Modify** `scripts/orchestrator_runner.py` — add module-level `import fnmatch`; add `_page_target_is_editable(...)` (shared editability rule) and refactor the nightly second guard to use it; add `_core_page_skeleton(...)`, `_synthesize_core_page(...)`, `_resolve_docs_dir(...)`, and `run_bootstrap_core(...)`; wire `--bootstrap-core` + `--today` into `main()`.
- **Modify** `tests/lint/test_frontmatter_contract.py` — tests for the two new frontmatter helpers.
- **Modify** `tests/lint/test_frontmatter_schema.py` — round-trip: a page written with the new synth frontmatter passes the block rule under an agent-authored section.
- **Create** `tests/orchestrator/test_bootstrap_core.py` — unit tests for the synth, the editable helper, `_resolve_docs_dir`, and the `run_bootstrap_core` loop (monkeypatched dispatch spy), plus the e2e subprocess test.
- **Create** `tests/orchestrator/fakes_bootstrap/fake_page_author.json` — a schema-valid `page-author` dry-run fixture (copy the shape from `tests/orchestrator/fakes/fake_page_author.json`).

---

### Task 1: C2 frontmatter helpers in `frontmatter_contract`

**Files:**

- Modify: `scripts/frontmatter_contract.py` (add two functions after `default_frontmatter_text` at line 94)
- Test: `tests/lint/test_frontmatter_contract.py`

- [ ] **Step 1: Write the failing tests**

Append to `tests/lint/test_frontmatter_contract.py`:

```python
def test_agent_authored_frontmatter_dict_shape():
    d = fc.agent_authored_frontmatter_dict(
        description="API layer",
        source_files=["a/b.py", "a/c.py"],
        last_reviewed="2026-05-26",
    )
    assert d == {
        "description": "API layer",
        "source_files": ["a/b.py", "a/c.py"],
        "last_reviewed": "2026-05-26",
        "status": "draft",
    }
    assert set(fc.AGENT_AUTHORED_REQUIRED) <= set(d)


def test_agent_authored_frontmatter_dict_copies_source_files():
    src = ["a/b.py"]
    d = fc.agent_authored_frontmatter_dict(
        description="x", source_files=src, last_reviewed="2026-05-26"
    )
    src.append("mutated")
    assert d["source_files"] == ["a/b.py"]  # not aliased to caller's list


def test_agent_authored_frontmatter_text_valid_and_complete():
    import yaml as _yaml

    text = fc.agent_authored_frontmatter_text(
        description="API layer",
        source_files=["a/b.py", "a/c.py"],
        last_reviewed="2026-05-26",
    )
    assert text.startswith("---\n") and text.endswith("---\n")
    body = _yaml.safe_load(text.split("---", 2)[1])
    assert set(fc.AGENT_AUTHORED_REQUIRED) <= set(body)
    assert body["description"] == "API layer"
    assert body["source_files"] == ["a/b.py", "a/c.py"]
    assert body["last_reviewed"] == "2026-05-26"
    assert body["status"] == "draft"


def test_agent_authored_frontmatter_text_empty_source_files():
    import yaml as _yaml

    text = fc.agent_authored_frontmatter_text(
        description="x", source_files=[], last_reviewed="2026-05-26"
    )
    body = _yaml.safe_load(text.split("---", 2)[1])
    assert body["source_files"] == []


def test_agent_authored_frontmatter_text_custom_status():
    import yaml as _yaml

    text = fc.agent_authored_frontmatter_text(
        description="x", source_files=["a.py"], last_reviewed="2026-05-26",
        status="reviewed",
    )
    body = _yaml.safe_load(text.split("---", 2)[1])
    assert body["status"] == "reviewed"
```

- [ ] **Step 2: Run to verify they fail**

Run: `python3 -m pytest tests/lint/test_frontmatter_contract.py -q`
Expected: FAIL — `AttributeError: module 'frontmatter_contract' has no attribute 'agent_authored_frontmatter_dict'`.

- [ ] **Step 3: Implement the helpers**

In `scripts/frontmatter_contract.py`, after `default_frontmatter_text()` (line 94), add:

```python
def agent_authored_frontmatter_dict(
    *,
    description: str,
    source_files: list[str],
    last_reviewed: str,
    status: str = "draft",
) -> dict:
    """The agent-authored (C2 core) frontmatter the bootstrap entry authors.

    Field set is AGENT_AUTHORED_REQUIRED; ``source_files`` is copied so the
    caller's list cannot be mutated through the returned dict.
    """
    return {
        "description": description,
        "source_files": list(source_files or []),
        "last_reviewed": last_reviewed,
        "status": status,
    }


def agent_authored_frontmatter_text(
    *,
    description: str,
    source_files: list[str],
    last_reviewed: str,
    status: str = "draft",
) -> str:
    """YAML frontmatter block for a C2 agent-authored core page (dry-run synth).

    Fields are emitted in AGENT_AUTHORED_REQUIRED order. ``description`` must be
    a single plain-text line (callers pass a slug-derived title), so no YAML
    escaping is needed — keeping this module yaml-free like its siblings.
    """
    lines = ["---", f"description: {description}"]
    if source_files:
        lines.append("source_files:")
        lines.extend(f"  - {p}" for p in source_files)
    else:
        lines.append("source_files: []")
    lines.append(f"last_reviewed: {last_reviewed}")
    lines.append(f"status: {status}")
    lines.append("---")
    return "\n".join(lines) + "\n"
```

- [ ] **Step 4: Run to verify they pass**

Run: `python3 -m pytest tests/lint/test_frontmatter_contract.py -q`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add scripts/frontmatter_contract.py tests/lint/test_frontmatter_contract.py
git commit -m "feat(CCE-28): agent-authored frontmatter helpers (C2 sub-plan 3)

Co-Authored-By: Claude Opus 4.7 <noreply@anthropic.com>"
```

---

### Task 2: Shared editability guard `_page_target_is_editable`

This factors the nightly loop's `agent_editable_paths` rule into one pure helper both the nightly loop and bootstrap call — the "reuse the existing guard, no second path-safety check" the spec requires. It is a shared-helper extraction: it must preserve the nightly loop's existing reason strings byte-for-byte.

**Files:**

- Modify: `scripts/orchestrator_runner.py` (add module-level `import fnmatch`; add helper; refactor `746-808` second guard)
- Test: `tests/orchestrator/test_bootstrap_core.py` (create with this test; later tasks append)

- [ ] **Step 1: Grep callers first (shared-helper discipline)**

Run: `grep -rn "agent_editable_paths\|fnmatch.fnmatch\|import fnmatch" scripts/`
Expected: the only `fnmatch`-based editability check is the nightly loop in `orchestrator_runner.py` (≈750, 769-771) plus the local `import fnmatch` at ≈747. Confirm no other module re-implements this rule before changing it.

- [ ] **Step 2: Write the failing test**

Create `tests/orchestrator/test_bootstrap_core.py`:

```python
from __future__ import annotations

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
```

- [ ] **Step 3: Run to verify it fails**

Run: `python3 -m pytest tests/orchestrator/test_bootstrap_core.py -q`
Expected: FAIL — `AttributeError: module 'orchestrator_runner' has no attribute '_page_target_is_editable'`.

- [ ] **Step 4: Add the module-level import and helper**

In `scripts/orchestrator_runner.py`, add `import fnmatch` to the top-of-file stdlib import block (next to the existing `import os`, `import json`, etc.). Then add this helper near the other small module helpers (e.g. just above `compute_source_drift` at line 522):

```python
def _page_target_is_editable(rel_posix: str, editable_globs: list[str]) -> bool:
    """True if a repo-relative page path may be authored: it matches at least
    one ``agent_editable_paths`` glob, or no globs are configured (permissive).
    Shared by the nightly authoring loop and ``run_bootstrap_core``.
    """
    return not editable_globs or any(
        fnmatch.fnmatch(rel_posix, g) for g in editable_globs
    )
```

- [ ] **Step 5: Refactor the nightly loop to use it (preserve reason strings)**

In the authoring loop, delete the now-redundant local `import fnmatch` (line ≈747) and replace the second guard (lines ≈769-773):

```python
        if editable_globs and not any(
            fnmatch.fnmatch(str(rel), g) for g in editable_globs
        ):
            add_partial(state, f"unsafe_page_path: {rel}")
            continue
```

with:

```python
        if not _page_target_is_editable(str(rel), editable_globs):
            add_partial(state, f"unsafe_page_path: {rel}")
            continue
```

Leave the first guard (the `.relative_to()` `ValueError` branch at 764-768, reason `f"unsafe_page_path: {hint}"`) **unchanged** — only the glob check moves. The `add_partial` reason string is identical, so existing tests stay green.

- [ ] **Step 6: Run the helper test and the full nightly suite**

Run: `python3 -m pytest tests/orchestrator/test_bootstrap_core.py tests/orchestrator/ -q`
Expected: PASS — the new helper test passes and every existing orchestrator/pipeline test (including any asserting `unsafe_page_path:` reasons) still passes.

- [ ] **Step 7: Commit**

```bash
git add scripts/orchestrator_runner.py tests/orchestrator/test_bootstrap_core.py
git commit -m "refactor(CCE-28): extract _page_target_is_editable shared guard (C2 sub-plan 3)

Co-Authored-By: Claude Opus 4.7 <noreply@anthropic.com>"
```

---

### Task 3: Manifest-aware dry-run synthesizer

`_core_page_skeleton` builds a deterministic, diagram-free body; `_synthesize_core_page` writes the agent-authored frontmatter (from the manifest entry + injected `today`) plus that body. This is the dry-run stand-in for the production `page-author`.

**Files:**

- Modify: `scripts/orchestrator_runner.py` (add both functions near `_page_target_is_editable`)
- Test: `tests/orchestrator/test_bootstrap_core.py`; `tests/lint/test_frontmatter_schema.py`

- [ ] **Step 1: Write the failing tests**

Append to `tests/orchestrator/test_bootstrap_core.py`:

````python
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
````

- [ ] **Step 2: Run to verify they fail**

Run: `python3 -m pytest tests/orchestrator/test_bootstrap_core.py -q`
Expected: FAIL — `_synthesize_core_page` not defined.

- [ ] **Step 3: Implement the synthesizer**

In `scripts/orchestrator_runner.py`, near `_page_target_is_editable`, add:

```python
def _core_page_skeleton(page: dict) -> str:
    """A deterministic, diagram-free Markdown body for a bootstrapped core page:
    a rationale stub the human must fill, a source-file inventory, and a
    gotchas/layering stub. No mermaid (waits on C3); no fabricated C1 pins
    (the production page-author emits verified pins).
    """
    title = page.get("title") or page.get("key") or "Component"
    src = page.get("source_files") or []
    lines = [
        f"# {title}",
        "",
        "TODO(human): rationale — why this component exists and its role in the system.",
        "",
        "## Source files",
        "",
    ]
    if src:
        lines.extend(f"- `{p}`" for p in src)
    else:
        lines.append("_No source files mapped._")
    lines += [
        "",
        "## Gotchas & layering rules",
        "",
        "TODO(human): rationale — accreted rules and constraints not derivable "
        "from current source.",
        "",
    ]
    return "\n".join(lines)


def _synthesize_core_page(target_path: Path, page: dict, today: str) -> None:
    """Dry-run stand-in for the production page-author: write a C2 core page
    (agent-authored frontmatter built from the manifest entry + injected
    ``today``, then the diagram-free skeleton). Mirrors the nightly dry-run
    synth but is manifest-aware.
    """
    import frontmatter_contract as fmc

    fm = fmc.agent_authored_frontmatter_text(
        description=page.get("title") or page.get("key") or "",
        source_files=page.get("source_files") or [],
        last_reviewed=today,
        status="draft",
    )
    target_path.write_text(fm + _core_page_skeleton(page))
```

- [ ] **Step 4: Run to verify they pass**

Run: `python3 -m pytest tests/orchestrator/test_bootstrap_core.py -q`
Expected: PASS.

- [ ] **Step 5: Add the lint round-trip test**

Append to `tests/lint/test_frontmatter_schema.py` (this proves the synth output survives the Tier-1 block rule under an agent-authored section — the failure mode sub-plan 1 was built to prevent):

```python
def test_synthesized_core_page_passes_block_rule(tmp_path):
    """A page written by _synthesize_core_page passes frontmatter_schema when its
    section's generator is agent-authored (absolute-path frame, as the
    orchestrator dispatches)."""
    import sys

    scripts = Path(__file__).resolve().parents[2] / "scripts"
    sys.path.insert(0, str(scripts))
    import orchestrator_runner as runner  # noqa: E402

    docs_dir = "docs/site-src"
    page = {
        "key": "api",
        "title": "API layer",
        "page": "core/api.md",
        "source_files": ["backend/api/**/*.py"],
    }
    target = tmp_path / docs_dir / "core" / "api.md"
    target.parent.mkdir(parents=True)
    runner._synthesize_core_page(target, page, today="2026-05-26")

    config = {
        "site": {
            "docs_dir": docs_dir,
            "sections": [
                {"key": "core", "path": "core/", "title": "Core",
                 "generator": "agent-authored"},
            ],
        }
    }
    ok, msg = check_path(target, config)
    assert ok, msg
```

Confirm `check_path` is imported at the top of `tests/lint/test_frontmatter_schema.py`; if the existing tests call it via a module alias, match that style.

- [ ] **Step 6: Run the schema test**

Run: `python3 -m pytest tests/lint/test_frontmatter_schema.py -q`
Expected: PASS.

- [ ] **Step 7: Commit**

```bash
git add scripts/orchestrator_runner.py tests/orchestrator/test_bootstrap_core.py tests/lint/test_frontmatter_schema.py
git commit -m "feat(CCE-28): manifest-aware dry-run core-page synthesizer (C2 sub-plan 3)

Co-Authored-By: Claude Opus 4.7 <noreply@anthropic.com>"
```

---

### Task 4: `_resolve_docs_dir` + `run_bootstrap_core`

**Files:**

- Modify: `scripts/orchestrator_runner.py` (add `_resolve_docs_dir` near the helpers; add `run_bootstrap_core` immediately after `run()` ends — find the `return` that closes `run()` near line 1035)
- Test: `tests/orchestrator/test_bootstrap_core.py`

- [ ] **Step 1: Write the failing tests**

Append to `tests/orchestrator/test_bootstrap_core.py`. First a small host-builder and a list-accumulating dispatch spy, then the cases:

```python
import json as _json

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
        {"key": "api", "title": "Api", "page": "core/api.md",
         "source_files": ["backend/api/**/*.py"]},
        {"key": "storage", "title": "Storage", "page": "core/storage.md",
         "source_files": ["backend/storage/**/*.py"]},
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
    assert runner._resolve_docs_dir({"site": {"docs_dir": "a"}, "docs": {"source_dir": "b"}}) == "a"
    assert runner._resolve_docs_dir({"docs": {"source_dir": "b"}}) == "b"
    assert runner._resolve_docs_dir({}) is None


def test_bootstrap_authors_missing_pages(tmp_path, monkeypatch):
    _host(tmp_path)
    calls = []
    monkeypatch.setattr(runner, "dispatch_validated", _spy(calls))
    rc = runner.run_bootstrap_core(tmp_path, dry_run_dir=tmp_path / "fakes", today="2026-05-26")
    assert rc == 0
    api = tmp_path / "docs/site-src/core/api.md"
    storage = tmp_path / "docs/site-src/core/storage.md"
    assert api.exists() and storage.exists()
    import yaml
    fm = yaml.safe_load(api.read_text().split("---", 2)[1])
    assert fm["source_files"] == ["backend/api/**/*.py"]
    assert fm["last_reviewed"] == "2026-05-26"
    assert fm["status"] == "draft"
    # one dispatch per missing page
    assert [c["inputs"]["target_path"].endswith("core/api.md") for c in calls].count(True) == 1
    assert len(calls) == 2


def test_bootstrap_is_idempotent_skips_existing(tmp_path, monkeypatch):
    _host(tmp_path)
    existing = tmp_path / "docs/site-src/core/api.md"
    existing.parent.mkdir(parents=True, exist_ok=True)
    existing.write_text("PRE-EXISTING\n")
    calls = []
    monkeypatch.setattr(runner, "dispatch_validated", _spy(calls))
    rc = runner.run_bootstrap_core(tmp_path, dry_run_dir=tmp_path / "fakes", today="2026-05-26")
    assert rc == 0
    assert existing.read_text() == "PRE-EXISTING\n"  # untouched
    # only the missing page (storage) is dispatched
    assert len(calls) == 1
    assert calls[0]["inputs"]["target_path"].endswith("core/storage.md")


def test_bootstrap_dispatch_failure_records_reason_and_continues(tmp_path, monkeypatch, capsys):
    _host(tmp_path)
    seq = [(None, ["boom"]), ({"ok": True}, [])]

    def fake(name, inputs, *, dry_run_dir, cwd=None):
        return seq.pop(0)

    monkeypatch.setattr(runner, "dispatch_validated", fake)
    rc = runner.run_bootstrap_core(tmp_path, dry_run_dir=tmp_path / "fakes", today="2026-05-26")
    assert rc == 0
    ledger = _json.loads(capsys.readouterr().out)
    assert "boom" in ledger["reasons"]
    assert len(ledger["authored"]) == 1  # the second page still authored


def test_bootstrap_no_manifest_is_noop(tmp_path, monkeypatch):
    _host(tmp_path, manifest=None)
    calls = []
    monkeypatch.setattr(runner, "dispatch_validated", _spy(calls))
    rc = runner.run_bootstrap_core(tmp_path, dry_run_dir=tmp_path / "fakes", today="2026-05-26")
    assert rc == 0
    assert calls == []
    assert not (tmp_path / "docs/site-src/core/api.md").exists()


def test_bootstrap_empty_manifest_is_noop(tmp_path, monkeypatch):
    _host(tmp_path, manifest={"version": 1, "pages": []})
    calls = []
    monkeypatch.setattr(runner, "dispatch_validated", _spy(calls))
    rc = runner.run_bootstrap_core(tmp_path, dry_run_dir=tmp_path / "fakes", today="2026-05-26")
    assert rc == 0
    assert calls == []


def test_bootstrap_rejects_non_editable_page(tmp_path, monkeypatch, capsys):
    # editable scope excludes the manifest's page path -> guard rejects, no dispatch
    cfg = _CONFIG_WITH_SITE.replace(
        'agent_editable_paths: ["docs/site-src/**"]',
        'agent_editable_paths: ["docs/site-src/sandbox/**"]',
    ).replace("core: docs/site-src/core", "core: docs/site-src/sandbox")
    _host(tmp_path, config=cfg)
    calls = []
    monkeypatch.setattr(runner, "dispatch_validated", _spy(calls))
    rc = runner.run_bootstrap_core(tmp_path, dry_run_dir=tmp_path / "fakes", today="2026-05-26")
    assert rc == 0
    assert calls == []
    ledger = _json.loads(capsys.readouterr().out)
    assert any(r.startswith("unsafe_page_path:") for r in ledger["reasons"])
```

- [ ] **Step 2: Run to verify they fail**

Run: `python3 -m pytest tests/orchestrator/test_bootstrap_core.py -q`
Expected: FAIL — `_resolve_docs_dir` / `run_bootstrap_core` not defined.

- [ ] **Step 3: Implement `_resolve_docs_dir`**

Near the other helpers in `scripts/orchestrator_runner.py`:

```python
def _resolve_docs_dir(config: dict) -> str | None:
    """The docs root for core pages: prefer ``site.docs_dir`` (what the manifest
    code and the source-map stage use), fall back to ``docs.source_dir`` for
    hosts that set no ``site:`` block. None when neither is a non-empty string.
    """
    site = config.get("site") if isinstance(config, dict) else None
    if isinstance(site, dict):
        d = site.get("docs_dir")
        if isinstance(d, str) and d.strip("/"):
            return d
    docs = config.get("docs") if isinstance(config, dict) else None
    if isinstance(docs, dict):
        d = docs.get("source_dir")
        if isinstance(d, str) and d.strip("/"):
            return d
    return None
```

- [ ] **Step 4: Implement `run_bootstrap_core`**

Add immediately after `run()` ends:

```python
def run_bootstrap_core(
    repo_root: Path,
    *,
    dry_run_dir: Path | None,
    today: str | None = None,
) -> int:
    """C2 bootstrap authoring entry. Reads <docs_dir>/.doc-core-manifest.json and
    authors each declared core page that has no file yet, via the unchanged
    page-author agent. Idempotent (create-missing only), diagram-free, best-effort
    per page (a dispatch failure records a reason and continues). No-op when there
    is no config docs_dir, no manifest, or an empty manifest. Returns 0 on
    success/no-op, 2 on unreadable config. Prints a JSON ledger to stdout.
    """
    import frontmatter_contract as fmc

    cfg_path = repo_root / ".engineering-docs-agent" / "config.yml"
    if not cfg_path.exists():
        print("no config", file=sys.stderr)
        return 2
    try:
        config = load_config_validated(cfg_path)
    except ConfigError as e:
        print(f"config invalid: {e}", file=sys.stderr)
        return 2

    docs_dir = _resolve_docs_dir(config)
    if docs_dir is None:
        print("no docs_dir; nothing to bootstrap", file=sys.stderr)
        return 0

    manifest_path = repo_root / docs_dir / ".doc-core-manifest.json"
    if not manifest_path.exists():
        print("no core manifest; run setup first", file=sys.stderr)
        return 0
    manifest = load_json(manifest_path)
    pages = manifest.get("pages") if isinstance(manifest, dict) else None
    if not isinstance(pages, list) or not pages:
        return 0

    today = today or datetime.now(timezone.utc).date().isoformat()
    voice_samples = load_voice_samples(repo_root, config)
    editable_globs = config.get("docs", {}).get("agent_editable_paths", [])
    section = next(
        (
            s
            for s in ((config.get("site") or {}).get("sections") or [])
            if isinstance(s, dict) and s.get("generator") == "agent-authored"
        ),
        None,
    )
    lens = (section or {}).get("key") or "core"

    ledger: dict = {"authored": [], "skipped_existing": [], "reasons": []}
    for page in pages:
        if not isinstance(page, dict) or "page" not in page:
            ledger["reasons"].append("manifest_page_invalid")
            continue
        target_path = repo_root / docs_dir / page["page"]
        try:
            rel = target_path.resolve().relative_to(repo_root.resolve())
        except ValueError:
            ledger["reasons"].append(f"unsafe_page_path: {page['page']}")
            continue
        if not _page_target_is_editable(str(rel), editable_globs):
            ledger["reasons"].append(f"unsafe_page_path: {rel}")
            continue
        if target_path.exists():
            ledger["skipped_existing"].append(str(rel))
            continue
        target_path.parent.mkdir(parents=True, exist_ok=True)
        out, reasons = dispatch_validated(
            "page-author",
            {
                "target_path": str(target_path),
                "action": "create",
                "lens": lens,
                "summaries": [],
                "voice_samples": voice_samples,
                "frontmatter_template": fmc.agent_authored_frontmatter_dict(
                    description=page.get("title") or page.get("key") or "",
                    source_files=page.get("source_files") or [],
                    last_reviewed=today,
                    status="draft",
                ),
                "manifest_page": page,
            },
            dry_run_dir=dry_run_dir,
            cwd=repo_root,
        )
        ledger["reasons"].extend(reasons)
        if out is None:
            if not reasons:
                ledger["reasons"].append(f"page_author_invalid: {rel}")
            continue
        if out.get("ok"):
            if dry_run_dir and not target_path.exists():
                _synthesize_core_page(target_path, page, today)
            ledger["authored"].append(str(rel))

    print(json.dumps(ledger, indent=2))
    return 0
```

Note: `load_config_validated`, `ConfigError`, `load_voice_samples`, `load_json`, `dispatch_validated`, `datetime`, `timezone`, `json`, `sys` are already in the module namespace (used by `run()`). The `manifest_page` input key is forwarded data only — `page-author`'s output schema is unaffected, and dispatch does not validate inputs.

- [ ] **Step 5: Run to verify they pass**

Run: `python3 -m pytest tests/orchestrator/test_bootstrap_core.py -q`
Expected: PASS (all Task 4 cases).

- [ ] **Step 6: Commit**

```bash
git add scripts/orchestrator_runner.py tests/orchestrator/test_bootstrap_core.py
git commit -m "feat(CCE-28): run_bootstrap_core authoring entry (C2 sub-plan 3)

Co-Authored-By: Claude Opus 4.7 <noreply@anthropic.com>"
```

---

### Task 5: CLI wiring — `--bootstrap-core` + `--today`

**Files:**

- Modify: `scripts/orchestrator_runner.py:1158-1164` (`main()`)
- Test: `tests/orchestrator/test_bootstrap_core.py`

- [ ] **Step 1: Write the failing test**

Append to `tests/orchestrator/test_bootstrap_core.py`:

```python
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
        sys, "argv",
        ["prog", "--repo-root", "/x", "--bootstrap-core",
         "--dry-run-subagents", "/fakes", "--today", "2026-05-26"],
    )
    rc = runner.main()
    assert rc == 0
    assert seen["today"] == "2026-05-26"
    assert str(seen["repo_root"]) == "/x"
    assert "run_called" not in seen  # nightly run() not invoked


def test_main_default_routes_nightly_run(monkeypatch):
    seen = {}
    monkeypatch.setattr(runner, "run", lambda *a, **k: seen.setdefault("run", True) or 0)
    monkeypatch.setattr(
        runner, "run_bootstrap_core",
        lambda *a, **k: seen.setdefault("bootstrap", True) or 0,
    )
    monkeypatch.setattr(sys, "argv", ["prog", "--repo-root", "/x"])
    rc = runner.main()
    assert rc == 0
    assert seen == {"run": True}
```

- [ ] **Step 2: Run to verify it fails**

Run: `python3 -m pytest tests/orchestrator/test_bootstrap_core.py -q -k main_routes`
Expected: FAIL — `--bootstrap-core` is an unrecognized argument (argparse SystemExit).

- [ ] **Step 3: Wire the flags**

Replace `main()` (lines 1158-1164) with:

```python
def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--repo-root", type=Path, required=True)
    parser.add_argument("--dry-run-subagents", type=Path, default=None)
    parser.add_argument("--no-pr", action="store_true")
    parser.add_argument(
        "--bootstrap-core",
        action="store_true",
        help="C2: author missing canonical-core pages from the manifest, then exit.",
    )
    parser.add_argument(
        "--today", default=None, help="ISO date for last_reviewed (bootstrap-core)."
    )
    args = parser.parse_args()
    if args.bootstrap_core:
        return run_bootstrap_core(
            args.repo_root, dry_run_dir=args.dry_run_subagents, today=args.today
        )
    return run(args.repo_root, dry_run_dir=args.dry_run_subagents, no_pr=args.no_pr)
```

- [ ] **Step 4: Run to verify they pass**

Run: `python3 -m pytest tests/orchestrator/test_bootstrap_core.py -q`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add scripts/orchestrator_runner.py tests/orchestrator/test_bootstrap_core.py
git commit -m "feat(CCE-28): --bootstrap-core CLI mode + --today injection (C2 sub-plan 3)

Co-Authored-By: Claude Opus 4.7 <noreply@anthropic.com>"
```

---

### Task 6: End-to-end subprocess test

Exercises the real CLI path (argparse → `run_bootstrap_core` → real `dispatch_validated` dry-run fixture → synth), proving the create + idempotent re-run behavior end to end.

**Files:**

- Create: `tests/orchestrator/fakes_bootstrap/fake_page_author.json`
- Test: `tests/orchestrator/test_bootstrap_core.py`

- [ ] **Step 1: Create the dry-run fixture**

Copy the shape of `tests/orchestrator/fakes/fake_page_author.json` (so it is valid against the `page-author` output schema) into `tests/orchestrator/fakes_bootstrap/fake_page_author.json`. Inspect the existing file first:

Run: `cat tests/orchestrator/fakes/fake_page_author.json`

Then create `tests/orchestrator/fakes_bootstrap/fake_page_author.json` with the same keys (at minimum `{"ok": true, ...}` plus whatever the schema requires). If the existing fixture is exactly `{"ok": true, "path": "...", "action": "create"}`, mirror that.

- [ ] **Step 2: Write the failing e2e test**

Append to `tests/orchestrator/test_bootstrap_core.py`:

````python
import subprocess

_RUNNER = Path(__file__).resolve().parents[2] / "scripts" / "orchestrator_runner.py"
_FAKES_BOOTSTRAP = Path(__file__).parent / "fakes_bootstrap"


def _run_bootstrap_cli(repo_root: Path):
    return subprocess.run(
        [
            sys.executable, str(_RUNNER),
            "--repo-root", str(repo_root),
            "--bootstrap-core",
            "--dry-run-subagents", str(_FAKES_BOOTSTRAP),
            "--today", "2026-05-26",
        ],
        capture_output=True, text=True,
    )


def test_bootstrap_core_e2e_creates_then_idempotent(tmp_path):
    _host(tmp_path)
    r = _run_bootstrap_cli(tmp_path)
    assert r.returncode == 0, r.stderr
    api = tmp_path / "docs/site-src/core/api.md"
    storage = tmp_path / "docs/site-src/core/storage.md"
    assert api.exists() and storage.exists()
    text = api.read_text()
    assert "last_reviewed: 2026-05-26" in text
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
````

- [ ] **Step 3: Run to verify it fails, then passes**

Run: `python3 -m pytest tests/orchestrator/test_bootstrap_core.py -q -k e2e`
Expected first run: FAIL if the fixture is missing/invalid (dispatch returns `None` → no page written). Once `fakes_bootstrap/fake_page_author.json` is valid: PASS.

If it still fails, debug with the runner's stderr (printed via `r.stderr` in the assert) and confirm the fixture validates against the `page-author` schema (check `agents/schemas/` for the exact required keys).

- [ ] **Step 4: Commit**

```bash
git add tests/orchestrator/fakes_bootstrap/fake_page_author.json tests/orchestrator/test_bootstrap_core.py
git commit -m "test(CCE-28): end-to-end --bootstrap-core create + idempotent re-run (C2 sub-plan 3)

Co-Authored-By: Claude Opus 4.7 <noreply@anthropic.com>"
```

---

### Task 7: Full-suite verification

**Files:** none (verification only)

- [ ] **Step 1: Run the entire suite**

Run: `python3 -m pytest -q`
Expected: all green (prior baseline was 463 passed, 3 skipped; this sub-plan adds ~20 tests and 0 regressions — expect ~483 passed, 3 skipped).

- [ ] **Step 2: Lint/format check (match repo convention)**

Run: `python3 -m pyflakes scripts/orchestrator_runner.py scripts/frontmatter_contract.py` (or the repo's configured linter, if any) and confirm no unused-import / undefined-name findings — in particular that the local `import fnmatch` removed in Task 2 left no dangling reference, and the module-level `import fnmatch` is present.

- [ ] **Step 3: Confirm no diagrams and no fabricated pins shipped**

Run: `grep -rn "mermaid\|<!--pin:" scripts/orchestrator_runner.py`
Expected: no matches in the new synth code (C1 pins are production-agent output; diagrams wait on C3).

---

## Self-Review (completed during planning)

**Spec coverage** (against `…c2-canonical-core-authoring-design.md`):

- "Dedicated `run_bootstrap_core()` entry … its own `--bootstrap-core`, not threaded into `run()`" → Task 4 + Task 5. ✅
- "Manifest-aware dry-run synthesis" → Task 3 (`_synthesize_core_page` reads `source_files` from the manifest entry). ✅
- "Idempotent create-missing" → Task 4 (`skipped_existing`, no overwrite, no re-dispatch). ✅
- "Reuses the authoring path guards (no second path-safety check)" → Task 2 (`_page_target_is_editable` shared by both). ✅
- "C2 frontmatter (`description, source_files, last_reviewed, status: draft`)" → Tasks 1+3, with the lint round-trip in Task 3 Step 5. ✅
- "`TODO(human)` rationale stubs; no diagrams" → Task 3 (`_core_page_skeleton`; Task 7 grep guard). ✅
- "Inject `today` so `last_reviewed` is pinnable" → Tasks 4 (`today=` param) + 5 (`--today`). ✅
- "List-accumulating dispatch spy so per-page dispatch can be asserted" → Task 4 `_spy`. ✅
- "Best-effort: a per-page dispatch failure records a partial reason and continues" → Task 4 (`test_bootstrap_dispatch_failure_records_reason_and_continues`). ✅
- "Bootstrap with an empty manifest → no-op"; "no detectable sources → skip" → Task 4 no-op cases. ✅
- "page-author reused unchanged" → no `agents/*.md` edits in any task. ✅

**Deferred (out of this sub-plan, by design):**

- Drift-update stage + `draft → reviewed` lifecycle → **sub-plan 4**.
- The dogfood `.engineering-docs-agent/config.yml` migration (core editable, specs read-only, lens re-point) → tracked separately; not required for this generic, fixture-tested unit and risks destabilizing the live config. Note for the reviewer.
- Real C1 pin emission and content quality → production `page-author` behavior, not unit-tested (spec §"Error handling & verification").

**Placeholder scan:** every code step contains complete code; no TBD/stub-prose steps. ✅
**Type consistency:** `agent_authored_frontmatter_dict/_text`, `_page_target_is_editable`, `_core_page_skeleton`, `_synthesize_core_page`, `_resolve_docs_dir`, `run_bootstrap_core` names and signatures are identical across the tasks that define and call them. ✅

---

## Execution coda

**Sub-skill:** Execute with **superpowers:subagent-driven-development** — a fresh implementer subagent per task, two-stage review (spec-compliance then code-quality) after each. Model selection: Tasks 1, 3, 5 are mechanical (sonnet); Task 2 is a **shared-helper contract change** and Tasks 4, 6 are integration (standard model). After all seven tasks, dispatch a **final whole-branch code review** (most capable model).

**Then:** surface **/ship** (base `main`) for authorization — push `feat/CCE-28-run-bootstrap-core` and open a PR with base `main`, title prefixed `feat(CCE-28):`, body footer `🤖 Generated with [Claude Code](https://claude.com/claude-code)`. Comment the PR link on **CCE-28**. **Do not merge and do not transition Jira without explicit user approval.** CCE-28 stays In Progress (sub-plan 4 remains).
