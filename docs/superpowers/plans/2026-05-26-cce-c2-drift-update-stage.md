# C2 Sub-Plan 4 — Drift-Update Stage Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add a flag-only nightly orchestrator stage that surfaces canonical-core pages (from `.doc-core-manifest.json`) which M flagged as source-drifted or C1 flagged as citation `gone`/`ambiguous`, under a "Core pages to review (drift)" block in the What's-New entry and the notifier digest — never editing a page or dispatching authoring.

**Architecture:** A third deterministic sibling next to `compute_source_drift` (M) and `compute_citation_drift` (C1). `compute_core_drift(repo_root, config, drifted_pages, citation_ledger)` intersects the manifest's core-page set with the already-computed M/C1 drift results — a pure read that opens no page for writing and takes no dispatch callable. It is wired into `run()` immediately after the C1 verify-citations stage, mirroring the best-effort try/except posture of its siblings. Status is irrelevant to surfacing: a `reviewed` page that drifts is still flagged so a human re-reviews; the never-auto-edit-`reviewed` safety property holds because the stage edits _no_ page.

**Tech Stack:** Python 3.9, stdlib-only (`json`, `pathlib`), pytest, fixture-driven dry-run with monkeypatched dispatch. Run tests with `python3 -m pytest` (bare `pytest` may not resolve on the local interpreter).

---

## Background the implementer needs (read before starting)

You are extending `scripts/orchestrator_runner.py`, the nightly docs-PR runner. Two existing "drift" stages already run inside `run()`:

- **M (source drift):** `compute_source_drift(repo_root, config, prs)` (line ~598) returns a list of `{"page", "changed_sources"}` dicts. `_drift_whats_new_lines(drifted_pages)` (line ~623) renders its What's-New block. Wired at line ~975 into local `drifted_pages`; recorded at `state["current_run"]["source_drift"]`.
- **C1 (citation drift):** `compute_citation_drift(repo_root, config, prs)` (line ~661) returns a ledger dict with `gone`, `ambiguous`, `pages_review_needed` lists (each `gone`/`ambiguous` entry is `{"page", "path", "token", ...}`). `_citation_drift_whats_new_lines(ledger)` (line ~678) renders its block. Wired at line ~983 into local `citation_ledger`; recorded at `state["current_run"]["citation_drift"]`.

**Page-path frame (critical, already verified):** all three sources speak the **same frame** — docs_dir-relative POSIX. M's `page` comes from `source_map._collect_page_patterns` → `md.relative_to(docs_dir).as_posix()`. C1's `page` comes from `verify_citations` → `md.relative_to(docs_dir).as_posix()`. The manifest's `page` field is `f"{section_path}/{key}.md"` (e.g. `"core/api.md"`), also docs_dir-relative. So set-intersection on the `page` strings is sound — **do not** re-root or normalize them.

**The core manifest** (built by sub-plan 2, `scripts/core_manifest.py`) lives at `<docs_dir>/.doc-core-manifest.json`:

```json
{
  "version": 1,
  "pages": [
    {
      "key": "api",
      "title": "API layer",
      "page": "core/api.md",
      "source_files": ["backend/api/**/*.py"]
    }
  ]
}
```

`run_bootstrap_core` (line ~1110) already reads it via `load_json` + an `isinstance(manifest, dict)` guard (because `load_json` returns `{}` for an absent file and `None` for invalid JSON). `_resolve_docs_dir(config)` (line ~580) returns `site.docs_dir` else `docs.source_dir` else `None`.

**Why flag-only (do not deviate):** per the C2 spec, a regenerate/refine pass cannot re-derive a core page's hard-won accreted rules from a diff and would delete them. The stage therefore _flags, never edits_. Re-authoring a drifted page is a deliberate human act, never a nightly side effect.

---

## File Structure

- **Modify** `scripts/orchestrator_runner.py`
  - Add `_load_core_manifest_pages(repo_root, docs_dir) -> list[dict]` — the single manifest-pages reader; also adopted by `run_bootstrap_core` (DRY).
  - Add `compute_core_drift(repo_root, config, drifted_pages, citation_ledger) -> list[dict]` — the stage helper (pure intersection, writes nothing, dispatches nothing).
  - Add `_core_drift_whats_new_lines(core_drifted) -> list[str]` — the What's-New block renderer.
  - Wire the stage into `run()`: a best-effort block after the C1 stage; one `entry_lines.extend(...)` in the What's-New assembly; one `core_drift` key in the notifier digest.
- **Modify** `agents/notifier.md` — document the new `core_drift` digest field.
- **Create** `tests/orchestrator/test_core_drift.py` — unit tests for the three helpers, including the two safety properties (byte-identical / no edit, `reviewed` still surfaced).
- **Modify** `tests/orchestrator/test_pipeline_integration.py` — one e2e `run()` wiring test, mirroring `test_run_surfaces_source_drift_in_whats_new_and_state`.
- **Modify** `tests/lint/test_frontmatter_schema.py` — one lifecycle-tolerance test: `status: reviewed` passes the agent-authored block rule.

---

### Task 1: `_load_core_manifest_pages` shared reader + adopt it in `run_bootstrap_core`

**Files:**

- Modify: `scripts/orchestrator_runner.py` (add helper near `_resolve_docs_dir`, ~line 596; refactor `run_bootstrap_core` ~lines 1144-1147)
- Test: `tests/orchestrator/test_core_drift.py`

This is a shared-helper change. `run_bootstrap_core` currently inlines the manifest read; extracting it gives `compute_core_drift` (Task 2) one contract to depend on. Per CLAUDE.md, before changing a cross-capability helper, grep its callers — there are none yet (it is new); the only _adopter_ is `run_bootstrap_core`, refactored here in the same change. The existing bootstrap tests (`tests/orchestrator/test_bootstrap_core.py`) are the regression net.

- [ ] **Step 1: Write the failing tests**

Create `tests/orchestrator/test_core_drift.py` with the header and the loader tests:

```python
from __future__ import annotations

import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "scripts"))
import orchestrator_runner as runner  # noqa: E402


def _write_manifest(tmp_path: Path, manifest) -> None:
    docs = tmp_path / "docs" / "site-src"
    docs.mkdir(parents=True, exist_ok=True)
    (docs / ".doc-core-manifest.json").write_text(json.dumps(manifest))


def test_load_core_manifest_pages_returns_pages(tmp_path):
    _write_manifest(
        tmp_path,
        {"version": 1, "pages": [{"key": "api", "page": "core/api.md"}]},
    )
    pages = runner._load_core_manifest_pages(tmp_path, "docs/site-src")
    assert pages == [{"key": "api", "page": "core/api.md"}]


def test_load_core_manifest_pages_absent_returns_empty(tmp_path):
    assert runner._load_core_manifest_pages(tmp_path, "docs/site-src") == []


def test_load_core_manifest_pages_corrupt_returns_empty(tmp_path):
    docs = tmp_path / "docs" / "site-src"
    docs.mkdir(parents=True)
    (docs / ".doc-core-manifest.json").write_text("{not valid json")
    assert runner._load_core_manifest_pages(tmp_path, "docs/site-src") == []


def test_load_core_manifest_pages_no_pages_key_returns_empty(tmp_path):
    _write_manifest(tmp_path, {"version": 1})
    assert runner._load_core_manifest_pages(tmp_path, "docs/site-src") == []
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `python3 -m pytest tests/orchestrator/test_core_drift.py -v`
Expected: FAIL with `AttributeError: module 'orchestrator_runner' has no attribute '_load_core_manifest_pages'`

- [ ] **Step 3: Add the helper**

Insert after `_resolve_docs_dir` (after line ~595, before `compute_source_drift`):

```python
def _load_core_manifest_pages(repo_root: Path, docs_dir: str) -> list[dict]:
    """The validated ``pages`` list from ``<docs_dir>/.doc-core-manifest.json``,
    or ``[]`` when the manifest is absent, unreadable, or carries no pages list.
    Never raises. Shared by ``run_bootstrap_core`` and ``compute_core_drift`` so
    both read the manifest through one contract.
    """
    manifest_path = repo_root / docs_dir / ".doc-core-manifest.json"
    if not manifest_path.exists():
        return []
    manifest = load_json(manifest_path)
    pages = manifest.get("pages") if isinstance(manifest, dict) else None
    return pages if isinstance(pages, list) else []
```

- [ ] **Step 4: Run the tests to verify they pass**

Run: `python3 -m pytest tests/orchestrator/test_core_drift.py -v`
Expected: PASS (4 tests)

- [ ] **Step 5: Adopt the helper in `run_bootstrap_core` (preserve behavior)**

`run_bootstrap_core` keeps its own `.exists()` guard so its distinct `"no core manifest; run setup first"` stderr message survives. Replace only the load+validate lines (currently ~1144-1147):

Old:

```python
    manifest = load_json(manifest_path)
    pages = manifest.get("pages") if isinstance(manifest, dict) else None
    if not isinstance(pages, list) or not pages:
        return 0
```

New:

```python
    pages = _load_core_manifest_pages(repo_root, docs_dir)
    if not pages:
        return 0
```

The `manifest_path = repo_root / docs_dir / ".doc-core-manifest.json"` line and the `if not manifest_path.exists(): print(...); return 0` guard directly above stay exactly as they are.

- [ ] **Step 6: Run the bootstrap regression suite**

Run: `python3 -m pytest tests/orchestrator/test_bootstrap_core.py -v`
Expected: PASS (all existing bootstrap tests still green — idempotency, missing-page authoring, corrupt-manifest no-op).

- [ ] **Step 7: Commit**

```bash
git add scripts/orchestrator_runner.py tests/orchestrator/test_core_drift.py
git commit -m "feat(CCE-28): _load_core_manifest_pages shared manifest reader

Co-Authored-By: Claude Opus 4.7 <noreply@anthropic.com>"
```

---

### Task 2: `compute_core_drift` + `_core_drift_whats_new_lines`

**Files:**

- Modify: `scripts/orchestrator_runner.py` (add both functions after `_citation_drift_whats_new_lines`, ~line 688, before `def run(`)
- Test: `tests/orchestrator/test_core_drift.py`

`compute_core_drift` is the stage's pure core. **It takes no dispatch callable and never opens a page for writing** — the spec's "no dispatch" and "byte-identical before/after" properties hold by construction. Steps 1/8 pin them as tests. Surfacing is status-independent (the manifest, not the page, decides what is "core"; drift, not status, decides what surfaced).

- [ ] **Step 1: Write the failing tests** (append to `tests/orchestrator/test_core_drift.py`)

```python
_CONFIG = {"site": {"docs_dir": "docs/site-src"}}
_EMPTY_LEDGER = {"gone": [], "ambiguous": []}


def _manifest_two(tmp_path):
    _write_manifest(
        tmp_path,
        {
            "version": 1,
            "pages": [
                {"key": "api", "page": "core/api.md", "source_files": ["a"]},
                {"key": "storage", "page": "core/storage.md", "source_files": ["b"]},
            ],
        },
    )


def test_compute_core_drift_source_and_citation(tmp_path):
    _manifest_two(tmp_path)
    drifted = [{"page": "core/api.md", "changed_sources": ["a.py"]}]
    ledger = {"gone": [{"page": "core/storage.md", "path": "b.py", "token": "t"}],
              "ambiguous": []}
    out = runner.compute_core_drift(tmp_path, _CONFIG, drifted, ledger)
    assert out == [
        {"page": "core/api.md", "reasons": ["source"]},
        {"page": "core/storage.md", "reasons": ["citation"]},
    ]


def test_compute_core_drift_both_reasons_on_one_page(tmp_path):
    _manifest_two(tmp_path)
    drifted = [{"page": "core/api.md", "changed_sources": ["a.py"]}]
    ledger = {"gone": [], "ambiguous": [{"page": "core/api.md", "path": "a.py",
                                        "token": "t", "lines": [1, 2]}]}
    out = runner.compute_core_drift(tmp_path, _CONFIG, drifted, ledger)
    assert out == [{"page": "core/api.md", "reasons": ["source", "citation"]}]


def test_compute_core_drift_ignores_non_core_drift(tmp_path):
    _manifest_two(tmp_path)
    # A drifted page that is NOT in the manifest must not surface.
    drifted = [{"page": "guides/setup.md", "changed_sources": ["x.py"]}]
    assert runner.compute_core_drift(tmp_path, _CONFIG, drifted, _EMPTY_LEDGER) == []


def test_compute_core_drift_no_intersection_is_empty(tmp_path):
    _manifest_two(tmp_path)
    assert runner.compute_core_drift(tmp_path, _CONFIG, [], _EMPTY_LEDGER) == []


def test_compute_core_drift_no_docs_dir_is_empty(tmp_path):
    drifted = [{"page": "core/api.md", "changed_sources": ["a.py"]}]
    assert runner.compute_core_drift(tmp_path, {}, drifted, _EMPTY_LEDGER) == []


def test_compute_core_drift_no_manifest_is_empty(tmp_path):
    drifted = [{"page": "core/api.md", "changed_sources": ["a.py"]}]
    assert runner.compute_core_drift(tmp_path, _CONFIG, drifted, _EMPTY_LEDGER) == []


def test_compute_core_drift_corrupt_manifest_is_empty(tmp_path):
    docs = tmp_path / "docs" / "site-src"
    docs.mkdir(parents=True)
    (docs / ".doc-core-manifest.json").write_text("{bad")
    drifted = [{"page": "core/api.md", "changed_sources": ["a.py"]}]
    assert runner.compute_core_drift(tmp_path, _CONFIG, drifted, _EMPTY_LEDGER) == []


def test_compute_core_drift_writes_nothing_byte_identical(tmp_path):
    # A real draft core page on disk; the stage must leave it byte-identical.
    page = tmp_path / "docs" / "site-src" / "core" / "api.md"
    page.parent.mkdir(parents=True)
    page.write_text("---\nstatus: draft\n---\n# API\nhand-written rationale\n")
    before = page.read_bytes()
    _write_manifest(
        tmp_path,
        {"version": 1, "pages": [{"key": "api", "page": "core/api.md",
                                  "source_files": ["a"]}]},
    )
    drifted = [{"page": "core/api.md", "changed_sources": ["a.py"]}]
    out = runner.compute_core_drift(tmp_path, _CONFIG, drifted, _EMPTY_LEDGER)
    assert out == [{"page": "core/api.md", "reasons": ["source"]}]
    assert page.read_bytes() == before  # flag-only: byte-identical


def test_compute_core_drift_reviewed_page_surfaced_and_unedited(tmp_path):
    # status does not filter surfacing; reviewed pages are never auto-edited.
    page = tmp_path / "docs" / "site-src" / "core" / "api.md"
    page.parent.mkdir(parents=True)
    page.write_text("---\nstatus: reviewed\n---\n# API\naccreted rules\n")
    before = page.read_bytes()
    _write_manifest(
        tmp_path,
        {"version": 1, "pages": [{"key": "api", "page": "core/api.md",
                                  "source_files": ["a"]}]},
    )
    ledger = {"gone": [{"page": "core/api.md", "path": "a.py", "token": "t"}],
              "ambiguous": []}
    out = runner.compute_core_drift(tmp_path, _CONFIG, [], ledger)
    assert out == [{"page": "core/api.md", "reasons": ["citation"]}]
    assert page.read_bytes() == before


def test_core_drift_whats_new_lines_empty():
    assert runner._core_drift_whats_new_lines([]) == []


def test_core_drift_whats_new_lines_renders_block():
    lines = runner._core_drift_whats_new_lines(
        [
            {"page": "core/api.md", "reasons": ["source", "citation"]},
            {"page": "core/storage.md", "reasons": ["citation"]},
        ]
    )
    assert lines[0] == "### Core pages to review (drift)"
    assert "- core/api.md (source, citation)" in lines
    assert "- core/storage.md (citation)" in lines
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `python3 -m pytest tests/orchestrator/test_core_drift.py -v`
Expected: FAIL — `compute_core_drift` / `_core_drift_whats_new_lines` not defined.

- [ ] **Step 3: Implement both functions**

Insert after `_citation_drift_whats_new_lines` (after line ~688, before `def run(`):

```python
def compute_core_drift(
    repo_root: Path,
    config: dict,
    drifted_pages: list[dict],
    citation_ledger: dict,
) -> list[dict]:
    """Canonical-core pages (from ``.doc-core-manifest.json``) that M flagged as
    source-drifted or C1 flagged as citation ``gone``/``ambiguous``. Flag-only:
    reads the manifest and the already-computed M/C1 results, **writes nothing to
    any page and dispatches nothing**. Surfacing is independent of page status —
    a ``reviewed`` page that drifts is still surfaced so a human re-reviews.

    Returns a deterministically sorted list of ``{"page", "reasons"}`` where
    ``reasons`` is an ordered subset of ``["source", "citation"]``. Empty list
    when there is no docs_dir, no manifest, or no core page drifted.
    """
    docs_dir = _resolve_docs_dir(config)
    if docs_dir is None:
        return []
    core_pages = {
        p["page"]
        for p in _load_core_manifest_pages(repo_root, docs_dir)
        if isinstance(p, dict) and isinstance(p.get("page"), str)
    }
    if not core_pages:
        return []
    source_drifted = {
        d["page"]
        for d in (drifted_pages or [])
        if isinstance(d, dict) and isinstance(d.get("page"), str)
    }
    citation_drifted = {
        e["page"]
        for key in ("gone", "ambiguous")
        for e in ((citation_ledger or {}).get(key) or [])
        if isinstance(e, dict) and isinstance(e.get("page"), str)
    }
    out: list[dict] = []
    for page in sorted(core_pages & (source_drifted | citation_drifted)):
        reasons = []
        if page in source_drifted:
            reasons.append("source")
        if page in citation_drifted:
            reasons.append("citation")
        out.append({"page": page, "reasons": reasons})
    return out


def _core_drift_whats_new_lines(core_drifted: list[dict]) -> list[str]:
    """What's-New block for drifted canonical-core pages (empty list -> no block)."""
    if not core_drifted:
        return []
    lines = ["### Core pages to review (drift)"]
    for d in core_drifted:
        lines.append(f"- {d['page']} ({', '.join(d['reasons'])})")
    return lines
```

- [ ] **Step 4: Run the tests to verify they pass**

Run: `python3 -m pytest tests/orchestrator/test_core_drift.py -v`
Expected: PASS (all Task 1 + Task 2 tests).

- [ ] **Step 5: Commit**

```bash
git add scripts/orchestrator_runner.py tests/orchestrator/test_core_drift.py
git commit -m "feat(CCE-28): compute_core_drift flag-only stage helper

Co-Authored-By: Claude Opus 4.7 <noreply@anthropic.com>"
```

---

### Task 3: Wire the stage into `run()` + e2e pipeline test

**Files:**

- Modify: `scripts/orchestrator_runner.py` (`run()`: stage block after C1 ~line 997; What's-New extend ~line 1047; digest key ~line 1088)
- Test: `tests/orchestrator/test_pipeline_integration.py`

- [ ] **Step 1: Write the failing e2e test** (append to `tests/orchestrator/test_pipeline_integration.py`)

```python
def test_run_surfaces_core_drift_in_whats_new_and_state(tmp_path):
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
    state_path = _init_host(tmp_path, seed_files={connectors_page: connectors_content})

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

    state = json.loads(state_path.read_text())
    assert state["current_run"]["core_drift"] == [
        {"page": "core/connectors.md", "reasons": ["source"]}
    ]
```

- [ ] **Step 2: Run the test to verify it fails**

Run: `python3 -m pytest tests/orchestrator/test_pipeline_integration.py::test_run_surfaces_core_drift_in_whats_new_and_state -v`
Expected: FAIL — the `core_drift` key is absent from run state and the block is missing from What's-New.

- [ ] **Step 3: Add the stage block in `run()`**

Immediately after the C1 citation stage's `state["current_run"]["citation_drift"] = citation_ledger` (line ~997), insert:

```python
    # Canonical-core drift (C2) — flag-only sibling after M/C1. Intersects the
    # core manifest with the M/C1 drift results; never edits a page or dispatches.
    try:
        core_drifted = compute_core_drift(
            repo_root, config, drifted_pages, citation_ledger
        )
    except Exception as exc:  # noqa: BLE001 - advisory stage, never block the PR
        core_drifted = []
        add_partial(state, f"core_drift_failed: {exc}", info_only=True)
    state["current_run"]["core_drift"] = core_drifted
```

- [ ] **Step 4: Extend the What's-New assembly**

In the `if prs:` block, immediately after the line `entry_lines.extend(_citation_drift_whats_new_lines(citation_ledger))` (line ~1047), add:

```python
        entry_lines.extend(_core_drift_whats_new_lines(core_drifted))
```

- [ ] **Step 5: Add the digest key**

In the `digest = { ... }` dict, immediately after the `"citation_drift": citation_ledger,` line (line ~1088), add:

```python
        "core_drift": core_drifted,
```

- [ ] **Step 6: Run the e2e test to verify it passes**

Run: `python3 -m pytest tests/orchestrator/test_pipeline_integration.py::test_run_surfaces_core_drift_in_whats_new_and_state -v`
Expected: PASS

- [ ] **Step 7: Run the full orchestrator suite (no regressions)**

Run: `python3 -m pytest tests/orchestrator/ -q`
Expected: PASS (all green, including the M/C1 stage tests and the existing `test_run_surfaces_source_drift_in_whats_new_and_state`).

- [ ] **Step 8: Commit**

```bash
git add scripts/orchestrator_runner.py tests/orchestrator/test_pipeline_integration.py
git commit -m "feat(CCE-28): wire core drift-update stage into nightly run()

Co-Authored-By: Claude Opus 4.7 <noreply@anthropic.com>"
```

---

### Task 4: `draft → reviewed` lifecycle tolerance test + notifier digest doc

**Files:**

- Modify: `tests/lint/test_frontmatter_schema.py` (add one test)
- Modify: `agents/notifier.md` (digest field list, line ~18)

The C2 spec (line 168) requires the lint/validator to tolerate the new `status: reviewed` value the lifecycle introduces. `frontmatter_schema.check_path` checks field _presence_ only (never the `status` value), so this is already true — this test _pins_ it so a future change can't regress the lifecycle. The notifier doc update keeps `agents/notifier.md` honest about the digest shape (the digest now carries `core_drift`).

- [ ] **Step 1: Write the failing-then-passing tolerance test** (append to `tests/lint/test_frontmatter_schema.py`)

```python
def test_agent_authored_status_reviewed_passes_block_rule(tmp_path):
    """The draft -> reviewed lifecycle (C2 sub-plan 4): an agent-authored page
    with status: reviewed still satisfies the block rule — the rule checks field
    presence, not the status value, so a human-reviewed core page is never
    deleted by the pipeline."""
    cfg = tmp_path / "c.yml"
    cfg.write_text(
        "site:\n  docs_dir: docs/site-src\n  sections:\n"
        "    - {key: core, path: core/, title: Core, generator: agent-authored}\n"
    )
    page = tmp_path / "docs/site-src/core/api.md"
    page.parent.mkdir(parents=True)
    page.write_text(
        "---\n"
        "description: The API layer\n"
        "source_files: [backend/app/api/router.py]\n"
        "last_reviewed: 2026-05-26\n"
        "status: reviewed\n"
        "---\n\n# API\n"
    )
    rc, out = _run([page], cfg)
    assert rc == 0
    assert all(r["ok"] for r in out["results"])
```

- [ ] **Step 2: Run it**

Run: `python3 -m pytest tests/lint/test_frontmatter_schema.py::test_agent_authored_status_reviewed_passes_block_rule -v`
Expected: PASS immediately (the behavior already holds; this pins it). If it FAILS, stop — that means a status-enum constraint exists that the spec did not account for; escalate before changing the rule.

- [ ] **Step 3: Update the notifier digest doc**

In `agents/notifier.md`, the digest field list currently ends `..., source_drift, citation_drift }`. Update that one line to include `core_drift`:

Old:

```
- `digest`: `{ pr_url, run_summary_bullets, gap_flags, lint_failures, build_status, verified, failed_urls, partial_reasons, source_drift, citation_drift }`
```

New:

```
- `digest`: `{ pr_url, run_summary_bullets, gap_flags, lint_failures, build_status, verified, failed_urls, partial_reasons, source_drift, citation_drift, core_drift }`
```

If `agents/notifier.md` has a prose section describing the drift blocks, add one sentence there: `core_drift` lists canonical-core pages (manifest-declared) that M or C1 flagged as drifted, surfaced under a "Core pages to review (drift)" heading; it is advisory and flag-only. If no such prose section exists, the field-list line is sufficient — do not invent a new section.

- [ ] **Step 4: Commit**

```bash
git add tests/lint/test_frontmatter_schema.py agents/notifier.md
git commit -m "test(CCE-28): pin reviewed-status tolerance; doc core_drift digest field

Co-Authored-By: Claude Opus 4.7 <noreply@anthropic.com>"
```

---

### Task 5: Full-suite verification

**Files:** none (verification only)

- [ ] **Step 1: Run the entire suite**

Run: `python3 -m pytest -q`
Expected: PASS — all prior tests plus the new `test_core_drift.py`, the new pipeline-integration test, and the new schema-tolerance test. Baseline before this sub-plan was 484 passed, 3 skipped; expect the passed count to rise by the number of new tests (≈15) with skips unchanged.

- [ ] **Step 2: If anything fails**

Use `superpowers:systematic-debugging` — find the root cause before any fix. Do not patch a test to make it pass; a red test here means the wiring or a helper contract is wrong.

---

## Execution Coda

- **Sub-skill:** Use `superpowers:subagent-driven-development` — fresh implementer per task, two-stage review (spec compliance, then code quality) after each. Tasks 1 and 3 touch merged code and the live `run()` flow → use a standard model and split the two reviews. Tasks 2, 4, 5 are mechanical/isolated → a cheaper model with the two reviews combined is acceptable.
- **Final whole-branch review:** after all five tasks, dispatch one final code-reviewer (opus) over the full branch diff (`main..HEAD`) before shipping.
- **Ship:** `/ship`, base `main`. PR base `main`. Title and body reference **CCE-28** (this is the final C2 sub-plan).
- **Do not** merge to `main` or transition Jira (CCE-28 → Done) without explicit user authorization. After this sub-plan merges, CCE-28's four sub-plans are all complete — surface the Done transition for approval; do not perform it unprompted.
- **Guardrails:** never use `-f`/`--force`/`--force-with-lease`/`--no-verify`/`--amend`; no direct commits to `main`; commit trailer `Co-Authored-By: Claude Opus 4.7 <noreply@anthropic.com>`; PR body footer `🤖 Generated with [Claude Code](https://claude.com/claude-code)`.
