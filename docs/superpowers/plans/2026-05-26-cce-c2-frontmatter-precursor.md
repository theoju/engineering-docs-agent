# C2 Frontmatter Precursor — generator-aware `frontmatter_schema`

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Make the Tier-1 `frontmatter_schema` lint rule require fields _by the authoring generator of the section a page belongs to_, so Capability C2's `agent-authored` core pages (`{description, source_files, last_reviewed, status}`) pass the same block rule that today hardcodes `{status, sources, synthesized_into}` — without that rule deleting them on first run.

**Architecture:** Introduce one shared single-source-of-truth module, `scripts/frontmatter_contract.py` (stdlib only), holding the two required-field sets, a `required_fields(generator)` selector, and a `section_generator_for(page, config)` resolver that maps a page path to its `site.sections[].generator` via the optional `site:` config block. `frontmatter_schema.py` consumes the contract; the orchestrator's two hardcoded `synthesized_into` literals are routed through the same module so no two code paths can disagree on frontmatter shape. Behavior is **unchanged** for every page that is not under an `agent-authored` section (which is all pages today and the entire dogfood config, since it has no `site:` block) — the default set is preserved.

**Tech Stack:** Python 3 stdlib + PyYAML (already a dependency); pytest; fixture-driven tests representing arbitrary hosts; production CLI dispatch is not involved (this is a pure lint-rule + helper change).

---

## Context the implementer must know

- **The rule today** (`scripts/lint/frontmatter_schema.py:9-39`): module constants `RULE_NAME`, `SEVERITY = "block"`, `REQUIRED_FIELDS = ("status", "sources", "synthesized_into")`; `parse_frontmatter(text) -> dict | None`; `check_path(path, config) -> (bool, str)` which currently ignores `config` for field selection and checks `REQUIRED_FIELDS`. It is invoked as a subprocess by `scripts/lint/lint_runner.py:100-109` as `python3 frontmatter_schema.py --config <cfg> --paths <p...> --json`, and is in `TIER1_DEFAULT` (`lint_runner.py:21-29`). A `block`-severity failure makes the orchestrator delete the offending page (`git checkout HEAD` / unlink), so a wrong required-field set is destructive.
- **The `site:` block is OPTIONAL.** The live `.engineering-docs-agent/config.yml` has **no `site:` block** — only `docs.lens_paths`. `state_io.py:83-84` returns early when `site` is absent. So `section_generator_for` must return `None` (→ default field set) whenever there is no `site:` block, no `docs_dir`, or no matching section. This is what preserves all existing behavior.
- **The `site:` shape** (`templates/site.default.yaml`, schema in `templates/config.schema.json`): `site.docs_dir` (string, e.g. `docs/site-src`) and `site.sections` (list of `{key, path, title, generator?, ...}`). `generator` enum: `archive-index | api-extract | changelog | agent-authored`. Section `path` is relative to `docs_dir` (e.g. `core/`, `architecture/`, or a file like `whats-new.md`). `state_io.py:99-104` resolves a section's full path as `PurePosixPath(docs_dir) / path`.
- **The orchestrator's two literals** (`scripts/orchestrator_runner.py`): line **791** inside the `page-author` dispatch `frontmatter_template` dict (`"synthesized_into": []`), and line **807** the dry-run synthesis string `"---\nstatus: draft\nsources: []\nsynthesized_into: []\n---\n"`. Both produce the **default** frontmatter for the existing summary-driven authoring path (lenses `core`/`superpowers`, which have no `agent-authored` section today → default set). They must keep producing the default set, but routed through the shared module so the field list lives in exactly one place.
- **Sibling-import pattern:** `orchestrator_runner.py` already imports siblings under `scripts/` (e.g. `import source_map`, `import verify_citations`). A new `import frontmatter_contract as fmc` works the same way. Lint rules live in `scripts/lint/`; to import `scripts/frontmatter_contract.py` from the rule, add `scripts/` to `sys.path` via `Path(__file__).resolve().parents[1]`.
- **Test conventions:** tests live under `tests/`; lint tests shell out to the rule as a subprocess (see `tests/lint/test_frontmatter_schema.py`); helper-module tests import directly with `sys.path.insert(0, str(Path(__file__).resolve().parents[N] / "scripts"))`. Run the suite with `python3 -m pytest`.

## File Structure

- **Create** `scripts/frontmatter_contract.py` — the single source of truth: field-set constants, `required_fields(generator)`, `section_generator_for(page, config)`. One responsibility: "given a page and config, what frontmatter does it owe?"
- **Create** `tests/lint/test_frontmatter_contract.py` — unit tests for the contract module (selector + resolver).
- **Modify** `scripts/lint/frontmatter_schema.py` — `check_path` consults the contract instead of the module constant.
- **Modify** `tests/lint/test_frontmatter_schema.py` — add agent-authored cases; keep existing default cases green.
- **Create** fixtures under `tests/fixtures/frontmatter_schema/` — an agent-authored good page and a config that declares an `agent-authored` section.
- **Modify** `scripts/orchestrator_runner.py` — route the two default-frontmatter literals through `frontmatter_contract`.
- **Modify** `agents/page-author.md:29` — generalize the documented required-keys line.

---

### Task 1: The contract module — field-set constants + selector

**Files:**

- Create: `scripts/frontmatter_contract.py`
- Test: `tests/lint/test_frontmatter_contract.py`

- [ ] **Step 1: Write the failing test**

```python
# tests/lint/test_frontmatter_contract.py
from __future__ import annotations
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "scripts"))
import frontmatter_contract as fc  # noqa: E402


def test_required_fields_default_for_none_and_unknown():
    assert fc.required_fields(None) == ("status", "sources", "synthesized_into")
    assert fc.required_fields("changelog") == ("status", "sources", "synthesized_into")
    assert fc.required_fields("archive-index") == (
        "status",
        "sources",
        "synthesized_into",
    )


def test_required_fields_agent_authored():
    assert fc.required_fields("agent-authored") == (
        "description",
        "source_files",
        "last_reviewed",
        "status",
    )
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python3 -m pytest tests/lint/test_frontmatter_contract.py -q`
Expected: FAIL — `ModuleNotFoundError: No module named 'frontmatter_contract'`.

- [ ] **Step 3: Write the minimal implementation**

```python
# scripts/frontmatter_contract.py
"""Single source of truth for required frontmatter fields, keyed by the
authoring generator of the site section a page belongs to.

Default (changelog / archive / api / no section / no site block) keeps the
historical set. Only ``agent-authored`` sections (Capability C2 core pages)
use the citation-bearing set. Pure stdlib; never raises on bad input.
"""

from __future__ import annotations

from pathlib import Path, PurePosixPath

DEFAULT_REQUIRED = ("status", "sources", "synthesized_into")
AGENT_AUTHORED_REQUIRED = ("description", "source_files", "last_reviewed", "status")


def required_fields(generator: str | None) -> tuple[str, ...]:
    """Return the required frontmatter field names for a section generator."""
    if generator == "agent-authored":
        return AGENT_AUTHORED_REQUIRED
    return DEFAULT_REQUIRED
```

- [ ] **Step 4: Run test to verify it passes**

Run: `python3 -m pytest tests/lint/test_frontmatter_contract.py -q`
Expected: PASS (2 passed).

- [ ] **Step 5: Commit**

```bash
git add scripts/frontmatter_contract.py tests/lint/test_frontmatter_contract.py
git commit -m "feat(CCE-26): frontmatter_contract — generator-keyed required-field sets (C2 precursor)"
```

---

### Task 2: The resolver — map a page to its section generator

**Files:**

- Modify: `scripts/frontmatter_contract.py`
- Test: `tests/lint/test_frontmatter_contract.py`

- [ ] **Step 1: Write the failing test**

```python
# append to tests/lint/test_frontmatter_contract.py

_CONFIG = {
    "site": {
        "docs_dir": "docs/site-src",
        "sections": [
            {"key": "core", "path": "core/", "title": "Core", "generator": "agent-authored"},
            {"key": "api", "path": "api/", "title": "API", "generator": "api-extract"},
            {"key": "whats-new", "path": "whats-new.md", "title": "WN", "generator": "changelog"},
            {"key": "ops", "path": "operations/", "title": "Ops"},
        ],
    }
}


def test_section_generator_for_dir_section():
    page = Path("/repo/docs/site-src/core/api.md")
    assert fc.section_generator_for(page, _CONFIG) == "agent-authored"


def test_section_generator_for_file_section():
    page = Path("/repo/docs/site-src/whats-new.md")
    assert fc.section_generator_for(page, _CONFIG) == "changelog"


def test_section_generator_for_section_without_generator_is_none():
    page = Path("/repo/docs/site-src/operations/runbook.md")
    assert fc.section_generator_for(page, _CONFIG) is None


def test_section_generator_for_no_match_is_none():
    page = Path("/repo/docs/site-src/elsewhere/x.md")
    assert fc.section_generator_for(page, _CONFIG) is None


def test_section_generator_for_no_site_block_is_none():
    assert fc.section_generator_for(Path("/repo/docs/site-src/core/api.md"), {}) is None


def test_section_generator_for_prefix_is_segment_bounded():
    # "core" must not match a sibling "core-extra" section.
    cfg = {
        "site": {
            "docs_dir": "docs/site-src",
            "sections": [
                {"key": "core-extra", "path": "core-extra/", "title": "X", "generator": "changelog"},
                {"key": "core", "path": "core/", "title": "Core", "generator": "agent-authored"},
            ],
        }
    }
    assert fc.section_generator_for(Path("/r/docs/site-src/core/a.md"), cfg) == "agent-authored"
    assert fc.section_generator_for(Path("/r/docs/site-src/core-extra/a.md"), cfg) == "changelog"
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python3 -m pytest tests/lint/test_frontmatter_contract.py -q`
Expected: FAIL — `AttributeError: module 'frontmatter_contract' has no attribute 'section_generator_for'`.

- [ ] **Step 3: Write the minimal implementation**

```python
# append to scripts/frontmatter_contract.py

def section_generator_for(page: Path | str, config: dict) -> str | None:
    """Return the generator of the site section that contains ``page``, or None.

    Matches the section whose ``docs_dir/path`` is a path-segment prefix of the
    page (longest match wins, so a nested section beats its parent). Returns
    None when there is no ``site:`` block, no ``docs_dir``, or no match — which
    yields the default field set. Never raises.
    """
    site = (config or {}).get("site") or {}
    docs_dir = str(site.get("docs_dir") or "").strip("/")
    sections = site.get("sections") or []
    if not docs_dir or not sections:
        return None
    page_posix = Path(page).as_posix()
    bounded = f"/{page_posix}/"  # segment-bounded haystack
    best_len = -1
    best_gen: str | None = None
    for s in sections:
        rel = str((s or {}).get("path") or "").strip("/")
        if not rel:
            continue
        full = str(PurePosixPath(docs_dir) / rel)  # e.g. docs/site-src/core
        if f"/{full}/" in bounded:
            if len(full) > best_len:
                best_len = len(full)
                best_gen = s.get("generator")
    return best_gen
```

- [ ] **Step 4: Run test to verify it passes**

Run: `python3 -m pytest tests/lint/test_frontmatter_contract.py -q`
Expected: PASS (8 passed).

- [ ] **Step 5: Commit**

```bash
git add scripts/frontmatter_contract.py tests/lint/test_frontmatter_contract.py
git commit -m "feat(CCE-26): section_generator_for — map page to section generator (C2 precursor)"
```

---

### Task 3: Make `frontmatter_schema` generator-aware

**Files:**

- Modify: `scripts/lint/frontmatter_schema.py:30-39` (`check_path`) and imports
- Test: `tests/lint/test_frontmatter_schema.py`
- Create: `tests/fixtures/frontmatter_schema/good_agent_authored.md`, `tests/fixtures/frontmatter_schema/site_core.yml`

- [ ] **Step 1: Write the failing tests + fixtures**

Create `tests/fixtures/frontmatter_schema/good_agent_authored.md`:

```markdown
---
description: The API layer
source_files:
  - backend/app/api/router.py
last_reviewed: 2026-05-26
status: draft
---

# API layer
```

Create `tests/fixtures/frontmatter_schema/site_core.yml`:

```yaml
site:
  docs_dir: tests/fixtures/frontmatter_schema
  sections:
    - key: core
      path: core/
      title: Core
      generator: agent-authored
```

Append to `tests/lint/test_frontmatter_schema.py`:

```python
def test_agent_authored_page_passes_with_new_fields(tmp_path):
    # A page under an agent-authored section requires the C2 field set.
    cfg = tmp_path / "c.yml"
    cfg.write_text(
        "site:\n"
        "  docs_dir: docs/site-src\n"
        "  sections:\n"
        "    - key: core\n"
        "      path: core/\n"
        "      title: Core\n"
        "      generator: agent-authored\n"
    )
    page = tmp_path / "docs/site-src/core/api.md"
    page.parent.mkdir(parents=True)
    page.write_text(
        "---\n"
        "description: The API layer\n"
        "source_files: [backend/app/api/router.py]\n"
        "last_reviewed: 2026-05-26\n"
        "status: draft\n"
        "---\n\n# API\n"
    )
    rc, out = _run([page], cfg)
    assert rc == 0
    assert all(r["ok"] for r in out["results"])


def test_agent_authored_page_missing_source_files_fails(tmp_path):
    cfg = tmp_path / "c.yml"
    cfg.write_text(
        "site:\n  docs_dir: docs/site-src\n  sections:\n"
        "    - {key: core, path: core/, title: Core, generator: agent-authored}\n"
    )
    page = tmp_path / "docs/site-src/core/api.md"
    page.parent.mkdir(parents=True)
    page.write_text(
        "---\ndescription: x\nlast_reviewed: 2026-05-26\nstatus: draft\n---\n\n# API\n"
    )
    rc, out = _run([page], cfg)
    assert rc == 1
    assert "source_files" in out["results"][0]["message"]


def test_agent_authored_rejects_old_default_fields(tmp_path):
    # An agent-authored page carrying ONLY the old set must now fail.
    cfg = tmp_path / "c.yml"
    cfg.write_text(
        "site:\n  docs_dir: docs/site-src\n  sections:\n"
        "    - {key: core, path: core/, title: Core, generator: agent-authored}\n"
    )
    page = tmp_path / "docs/site-src/core/api.md"
    page.parent.mkdir(parents=True)
    page.write_text("---\nstatus: draft\nsources: []\nsynthesized_into: []\n---\n\n# API\n")
    rc, out = _run([page], cfg)
    assert rc == 1
    msg = out["results"][0]["message"]
    assert "description" in msg and "source_files" in msg and "last_reviewed" in msg


def test_non_agent_authored_page_keeps_default_set(tmp_path):
    # A page under a non-agent-authored section still needs synthesized_into.
    cfg = tmp_path / "c.yml"
    cfg.write_text(
        "site:\n  docs_dir: docs/site-src\n  sections:\n"
        "    - {key: ops, path: operations/, title: Ops}\n"
    )
    page = tmp_path / "docs/site-src/operations/run.md"
    page.parent.mkdir(parents=True)
    page.write_text("---\nstatus: accepted\nsources: [a]\n---\n\n# Run\n")
    rc, out = _run([page], cfg)
    assert rc == 1
    assert "synthesized_into" in out["results"][0]["message"]
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `python3 -m pytest tests/lint/test_frontmatter_schema.py -q`
Expected: the four new tests FAIL — the rule currently checks the hardcoded default set for every page, so the agent-authored pages fail (missing `sources`/`synthesized_into`) and `test_agent_authored_rejects_old_default_fields` passes for the wrong reason (message says `synthesized_into`, not `description`).

- [ ] **Step 3: Make `check_path` generator-aware**

Replace the imports and `check_path` in `scripts/lint/frontmatter_schema.py`. Add the sibling-import shim near the top (after the existing imports):

```python
"""Lint rule: frontmatter_schema. Validates required YAML frontmatter fields."""

from __future__ import annotations
import argparse, json, sys
from pathlib import Path
from typing import Any
import yaml

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import frontmatter_contract as fc  # noqa: E402

RULE_NAME = "frontmatter_schema"
SEVERITY = "block"
```

Delete the module-level `REQUIRED_FIELDS = (...)` line (the contract owns it now) and rewrite `check_path`:

```python
def check_path(path: Path, config: dict[str, Any]) -> tuple[bool, str]:
    if not path.exists():
        return False, "file not found"
    fm = parse_frontmatter(path.read_text())
    if fm is None:
        return False, "no frontmatter or YAML parse error"
    generator = fc.section_generator_for(path, config)
    required = fc.required_fields(generator)
    missing = [f for f in required if f not in fm]
    if missing:
        return False, f"missing required field(s): {', '.join(missing)}"
    return True, "ok"
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `python3 -m pytest tests/lint/test_frontmatter_schema.py -q`
Expected: PASS — all original tests (`test_good`, `test_missing_field`, `test_no_frontmatter`) still green (default set unchanged when config is `{}`), plus the four new agent-authored tests.

- [ ] **Step 5: Commit**

```bash
git add scripts/lint/frontmatter_schema.py tests/lint/test_frontmatter_schema.py \
  tests/fixtures/frontmatter_schema/good_agent_authored.md \
  tests/fixtures/frontmatter_schema/site_core.yml
git commit -m "feat(CCE-26): frontmatter_schema requires fields by section generator (C2 precursor)"
```

---

### Task 4: Route the orchestrator's default-frontmatter literals through the contract

**Files:**

- Modify: `scripts/frontmatter_contract.py` (add two render helpers)
- Modify: `scripts/orchestrator_runner.py:783-792` and `:805-809`
- Test: `tests/lint/test_frontmatter_contract.py`

- [ ] **Step 1: Write the failing test for the render helpers**

```python
# append to tests/lint/test_frontmatter_contract.py

def test_default_frontmatter_dict_shape():
    d = fc.default_frontmatter_dict(["https://pr/1"])
    assert d == {"status": "draft", "sources": ["https://pr/1"], "synthesized_into": []}
    assert tuple(k for k in fc.DEFAULT_REQUIRED) == ("status", "sources", "synthesized_into")
    assert set(fc.DEFAULT_REQUIRED) <= set(d)


def test_default_frontmatter_text_is_valid_and_complete():
    import yaml as _yaml

    text = fc.default_frontmatter_text()
    assert text.startswith("---\n") and text.endswith("---\n")
    body = _yaml.safe_load(text.split("---", 2)[1])
    assert set(fc.DEFAULT_REQUIRED) <= set(body)
    assert body["status"] == "draft"
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python3 -m pytest tests/lint/test_frontmatter_contract.py -q`
Expected: FAIL — `default_frontmatter_dict` / `default_frontmatter_text` undefined.

- [ ] **Step 3: Add the render helpers**

```python
# append to scripts/frontmatter_contract.py

def default_frontmatter_dict(sources: list[str] | None = None) -> dict:
    """The default (non-agent-authored) frontmatter the orchestrator authors."""
    return {"status": "draft", "sources": list(sources or []), "synthesized_into": []}


def default_frontmatter_text() -> str:
    """The default frontmatter block for the dry-run page synthesizer."""
    return "---\nstatus: draft\nsources: []\nsynthesized_into: []\n---\n"
```

- [ ] **Step 4: Route the orchestrator through the helpers**

In `scripts/orchestrator_runner.py`, ensure the sibling import exists near the other sibling imports (e.g. alongside `import source_map`):

```python
import frontmatter_contract as fmc
```

Replace the inline `frontmatter_template` dict (currently lines ~783-792) so the `frontmatter_template` value is built from the helper:

```python
                "voice_samples": voice_samples,
                "frontmatter_template": fmc.default_frontmatter_dict(
                    [
                        pr.get("url")
                        for s in batch_summaries
                        for pr in prs
                        if pr.get("number") == s.get("pr_number")
                    ]
                ),
            },
```

Replace the dry-run synthesis string (currently lines ~805-809) so the frontmatter block comes from the helper:

```python
            if dry_run_dir and not target_path.exists():
                target_path.write_text(
                    fmc.default_frontmatter_text() + f"# {hint}\n\nGenerated by docs-agent.\n"
                )
```

- [ ] **Step 5: Run the orchestrator + integration tests to verify no behavior change**

Run: `python3 -m pytest tests/orchestrator -q`
Expected: PASS — the authored frontmatter is byte-identical to before (same default set), so pipeline/integration tests stay green.

- [ ] **Step 6: Commit**

```bash
git add scripts/frontmatter_contract.py scripts/orchestrator_runner.py tests/lint/test_frontmatter_contract.py
git commit -m "refactor(CCE-26): route orchestrator default frontmatter through frontmatter_contract (C2 precursor)"
```

---

### Task 5: Update the page-author contract doc

**Files:**

- Modify: `agents/page-author.md:29`

- [ ] **Step 1: Read the current line**

Run: `sed -n '27,30p' agents/page-author.md`
Expected: line 29 reads `- \`frontmatter_template\`: dict with required keys per spec §6.1 (\`status\`, \`sources\`, \`synthesized_into\`)`.

- [ ] **Step 2: Generalize the line**

Replace line 29 with:

```markdown
- `frontmatter_template`: dict of the frontmatter keys the caller wants written. The required set is generator-aware (see `scripts/frontmatter_contract.py`): the default authoring path uses `status`, `sources`, `synthesized_into`; `agent-authored` (Capability C2 core) pages use `description`, `source_files`, `last_reviewed`, `status`.
```

- [ ] **Step 3: Verify no other doc references the old hardcoded set**

Run: `grep -rn "synthesized_into" agents/ scripts/ | grep -v frontmatter_contract`
Expected: only `frontmatter_contract.py` (the single source of truth) and—if present—comments; no stray hardcoded required-set literals in `frontmatter_schema.py` or `orchestrator_runner.py`.

- [ ] **Step 4: Commit**

```bash
git add agents/page-author.md
git commit -m "docs(CCE-26): page-author frontmatter contract is generator-aware (C2 precursor)"
```

---

### Task 6: Full-suite verification

**Files:** none (verification only)

- [ ] **Step 1: Run the entire suite**

Run: `python3 -m pytest -q`
Expected: PASS — the prior green baseline (414 passed, 3 skipped) plus the new contract + schema tests; 0 failures. Confirm the count went up by the number of new tests and nothing regressed.

- [ ] **Step 2: Sanity-check the rule end-to-end via lint_runner against the dogfood config**

Run: `python3 scripts/lint/lint_runner.py --config .engineering-docs-agent/config.yml --paths docs/superpowers/specs/2026-05-26-cce-capability-c2-canonical-core-authoring-design.md --json | python3 -m json.tool`
Expected: the `frontmatter_schema` result for this spec page is unchanged from before this plan (the dogfood config has no `site:` block, so the default set applies) — i.e., the precursor did not alter behavior for existing pages.

- [ ] **Step 3: Commit any incidental fixes**

If Steps 1-2 surfaced anything, fix and commit with a `fix(CCE-26): ...` subject. Otherwise no commit.

---

## Self-review (completed by plan author)

**Spec coverage:** The spec's "Frontmatter contract and the precursor lint fix" requires: (a) generator-aware required fields — Task 3; (b) `agent-authored` → `{description, source_files, last_reviewed, status}` — Tasks 1+3; (c) default path keeps `{status, sources, synthesized_into}` — Tasks 1+3 (default branch) verified by existing tests + Task 3's `test_non_agent_authored_page_keeps_default_set`; (d) "rule, its test, its fixtures, and the orchestrator's two literals move together" — Tasks 3 (rule/test/fixtures) + 4 (orchestrator literals) + 5 (doc); (e) shared-helper contract, grep callers — Task 5 Step 3 grep + the single-source-of-truth module. Deferred items (`detect_core_manifest`, `run_bootstrap_core`, drift stage) are explicitly out of scope.

**Placeholder scan:** No TBD/TODO/"handle edge cases"/"similar to" — every code step shows complete code.

**Type consistency:** `required_fields(generator: str | None) -> tuple[str, ...]`, `section_generator_for(page, config) -> str | None`, `default_frontmatter_dict(sources) -> dict`, `default_frontmatter_text() -> str` — names and signatures are identical everywhere they appear (module, rule, orchestrator, tests).

---

## Execution coda

- **Execute via superpowers:subagent-driven-development** — fresh implementer per task; after each task, the two-stage review (spec-compliance, then code-quality). This is a small, mechanical, well-specified plan; a fast/cheap model suffices for the implementer, a capable model for reviews.
- **Branch:** off `main`, `feat/CCE-26-c2-frontmatter-precursor`. No direct commits to `main`. Materialize the C2 spec + this plan onto the branch (as the C1 PR carried its spec+plan).
- **Final whole-branch review** after all six tasks (dedicated reviewer over the full precursor diff `main..HEAD`).
- **`/ship` with full gate**, `--base main`; PR base **`main`**. Merge on a green _integrated_ suite (`git fetch`, confirm 0 behind `origin/main`, full `python3 -m pytest`), merge commit (not squash), prune the branch — gated on explicit user authorization, per repo convention.
- **Jira:** create a **C2 sub-task under CCE-26** (as C1 → CCE-27), title it for the frontmatter precursor, link the PR, comment on open; transition to Done only after merge.
