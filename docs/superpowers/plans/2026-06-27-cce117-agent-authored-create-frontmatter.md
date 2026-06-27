# CCE-117: generator-aware frontmatter on the incremental create path — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Make the nightly incremental authoring path write the agent-authored frontmatter set (`description`, `source_files`, `last_reviewed`, `status`) when it creates a page in an `agent-authored` section, so Tier-1 lint stops dropping those pages and the nightly run stops going partial.

**Architecture:** In `scripts/orchestrator_runner.py`'s authoring loop, branch on `fmc.section_generator_for(rel, config) == "agent-authored"` (create action only). A new pure helper `_synthesize_agent_description` deterministically builds a lint-passing description; `source_files` reuses the already-computed PR `grounding`; `last_reviewed` reuses the run's `now`. Both the production template (fed to the page-author) and the dry-run synth (used by tests) consume one shared `agent_fields` dict. Default sections keep today's behavior exactly.

**Tech Stack:** Python 3.11/3.12 stdlib + PyYAML; pytest; fixture-driven dry-run path (production CLI dispatch monkeypatched). Spec: `docs/superpowers/specs/2026-06-27-cce117-agent-authored-create-frontmatter-design.md` (committed `5013fec`).

---

## Critical context for the implementer

- **Work on branch `fix/CCE-117-agent-authored-create-frontmatter`** (already created off `main`; spec already committed). Do NOT branch again.
- **The bug is create-only.** Editing an existing agent-authored page already works (the page-author preserves existing frontmatter). Scope the new branch to `action == "create"` so the working edit path is untouched.
- **Two call sites, one shared value.** The production template (`orchestrator_runner.py:~1463`) and the dry-run synth (`~:1504-1508`) are in the _same_ loop iteration (`for i, ((lens, hint), batch_summaries) ...` starting `:1433`). Compute `agent_fields` once and reuse at both — never recompute.
- **`now` and `rel` are in scope.** `now = datetime.now(timezone.utc).isoformat()` is bound at `:1252` (same `run()` function); `now[:10]` → `YYYY-MM-DD`. `rel` (repo-relative target path) is bound at `:1454`.
- **`grounding` must move up.** It's currently computed at `:1474-1480`, _after_ the template. Move that block above the template branch so `source_files` can reuse it; the `source_paths=sorted(grounding)` use at `:1490` stays.
- **Run tests from the repo root:** `python3 -m pytest`.
- **The real lint consumers** are `scripts/lint/frontmatter_schema.py` and `scripts/lint/description_quality.py`; both expose `check_path(path: Path, config: dict) -> tuple[bool, str]` and no-op (return `(True, ...)`) for non-agent-authored sections. Use them directly in the integration test (CLAUDE.md: verify with the actual consumer, not `test -f`).
- **`description_quality` is mechanical** (`min_words: 6`, `forbid_equal_to_title` vs the page H1, `forbid_trailing_colon`). The helper must satisfy all three by construction.

---

## File structure

- **Modify:** `scripts/orchestrator_runner.py`
  - Add module-level helper `_synthesize_agent_description` (near `_synthesize_core_page`, ~`:930`).
  - Rework the authoring-loop template branch (~`:1462-1480`) and the dry-run synth (~`:1501-1508`).
- **Create:** `tests/orchestrator/test_synthesize_description.py` — unit tests for the helper.
- **Create:** `tests/orchestrator/test_agent_authored_create_frontmatter.py` — template-capture + integration (real-lint) + default-section regression.
- **Modify:** `CHANGELOG.md` — one `Fixed` line.

---

## Task 1: `_synthesize_agent_description` pure helper

**Files:**

- Modify: `scripts/orchestrator_runner.py` (add helper near `:930`)
- Test: `tests/orchestrator/test_synthesize_description.py` (create)

- [ ] **Step 1: Write the failing tests**

Create `tests/orchestrator/test_synthesize_description.py`:

```python
from __future__ import annotations
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent.parent / "scripts"))
import orchestrator_runner as runner  # noqa: E402

_syn = runner._synthesize_agent_description


def test_uses_what_changed_and_clears_min_words():
    out = _syn([{"pr_number": 1, "what_changed": "Adds a foo connector"}],
               hint="connectors/foo.md")
    assert len(out.split()) >= 6
    assert not out.endswith(":")


def test_not_equal_to_slug_title():
    # description_quality compares against the page H1 (`# {hint}`), parsed to
    # the hint string. The synthesized description must differ from it.
    hint = "connectors/foo.md"
    out = _syn([{"what_changed": "Adds a foo connector"}], hint=hint)
    assert out.strip().lower() != hint.strip().lower()


def test_trailing_colon_stripped_even_if_source_ends_in_colon():
    out = _syn([{"what_changed": "Refactors the loader:"}], hint="loader.md")
    assert not out.endswith(":")
    assert len(out.split()) >= 6


def test_empty_summaries_fall_back_and_still_pass_min_words():
    out = _syn([], hint="orchestrator/state-advancement.md")
    assert len(out.split()) >= 6
    assert not out.endswith(":")


def test_deterministic():
    args = ([{"what_changed": "Adds a foo connector"}], )
    a = _syn(*args, hint="connectors/foo.md")
    b = _syn(*args, hint="connectors/foo.md")
    assert a == b


def test_tolerates_malformed_entries():
    out = _syn(["not-a-dict", {"what_changed": None}, {"why": "Because reasons here"}],
               hint="x.md")
    assert isinstance(out, str) and len(out.split()) >= 6
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `python3 -m pytest tests/orchestrator/test_synthesize_description.py -q`
Expected: FAIL — `AttributeError: module 'orchestrator_runner' has no attribute '_synthesize_agent_description'`.

- [ ] **Step 3: Implement the helper**

In `scripts/orchestrator_runner.py`, add directly below `_synthesize_core_page` (~`:945`):

```python
def _synthesize_agent_description(summaries: list[dict], *, hint: str) -> str:
    """Deterministic one-line description for a freshly-created agent-authored
    page (CCE-117). Guarantees the description_quality invariants — >= 6 words,
    not equal to the slug-derived H1, no trailing colon — by construction.
    Pure; never raises on malformed input.
    """
    change = ""
    for s in summaries or []:
        if isinstance(s, dict):
            wc = s.get("what_changed") or s.get("why")
            if isinstance(wc, str) and wc.strip():
                change = wc.strip()
                break
    base = hint[:-3] if hint.endswith(".md") else hint
    topic = " ".join(
        base.replace("/", " ").replace("-", " ").replace("_", " ").split()
    ) or "this page"
    if change:
        desc = f"Documents {topic}: {change}"
    else:
        desc = f"Reference documentation for {topic} in this codebase"
    desc = desc.rstrip(":").strip()
    if len(desc.split()) < 6:
        desc = f"{desc} agent-authored reference for {topic}".rstrip(":").strip()
    return desc
```

- [ ] **Step 4: Run the tests to verify they pass**

Run: `python3 -m pytest tests/orchestrator/test_synthesize_description.py -q`
Expected: PASS (6 passed).

- [ ] **Step 5: Commit**

```bash
git add scripts/orchestrator_runner.py tests/orchestrator/test_synthesize_description.py
git commit -m "feat(CCE-117): add _synthesize_agent_description helper

Deterministic, lint-passing description for agent-authored page creation
(>= 6 words, != slug H1, no trailing colon). Pure helper + unit tests.

Co-Authored-By: Claude Opus 4.8 <noreply@anthropic.com>"
```

---

## Task 2: Production template is generator-aware (create + agent-authored)

**Files:**

- Modify: `scripts/orchestrator_runner.py:~1462-1480`
- Test: `tests/orchestrator/test_agent_authored_create_frontmatter.py` (create)

- [ ] **Step 1: Write the failing test**

Create `tests/orchestrator/test_agent_authored_create_frontmatter.py`:

```python
from __future__ import annotations
import sys
from pathlib import Path

import pytest
import yaml

sys.path.insert(0, str(Path(__file__).parent.parent.parent / "scripts"))

FAKES = Path(__file__).parent / "fakes"

# A host whose `core` lens maps into an `agent-authored` site section, so the
# fake summary's `core/connectors/foo.md` create resolves to agent-authored.
CONFIG_AGENT_AUTHORED = """
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


def test_agent_authored_create_uses_agent_template(tmp_path, init_host, monkeypatch):
    """The frontmatter_template handed to page-author for a create in an
    agent-authored section carries the agent-authored field set, not default."""
    init_host(_SEED_STATE, config_yaml=CONFIG_AGENT_AUTHORED)
    import orchestrator_runner as runner

    captured: dict = {}
    orig = runner.dispatch_validated

    def spy(name, payload, **kw):
        if name == "page-author":
            captured["fm"] = payload.get("frontmatter_template")
            captured["source_paths"] = payload.get("source_paths")
        return orig(name, payload, **kw)

    monkeypatch.setattr(runner, "dispatch_validated", spy)
    rc = runner.run(tmp_path, dry_run_dir=FAKES, no_pr=True)
    assert rc == 0
    fm = captured["fm"]
    assert set(fm) >= {"description", "source_files", "last_reviewed", "status"}, fm
    assert "sources" not in fm and "synthesized_into" not in fm, fm
    assert isinstance(fm["description"], str) and len(fm["description"].split()) >= 6
```

- [ ] **Step 2: Run the test to verify it fails**

Run: `python3 -m pytest tests/orchestrator/test_agent_authored_create_frontmatter.py::test_agent_authored_create_uses_agent_template -q`
Expected: FAIL — `fm` is the default set (`status`/`sources`/`synthesized_into`), so the `set(fm) >= {...}` assertion fails (`KeyError`-free assert failure on missing description).

- [ ] **Step 3: Rework the template branch**

In `scripts/orchestrator_runner.py`, replace the block that currently reads (starting ~`:1461`):

```python
            target_path.parent.mkdir(parents=True, exist_ok=True)
            action = "edit" if target_path.exists() else "create"
            fm_template = fmc.default_frontmatter_dict(
                [
                    pr.get("url")
                    for s in batch_summaries
                    for pr in prs
                    if pr.get("number") == s.get("pr_number")
                ]
            )
            _dk = doc_kind_by_target.get((lens, hint))
            if _dk:
                fm_template["doc_kind"] = _dk
            # CCE-110 layer 1: ground the author in the code the PRs touched.
            batch_prs = [
                pr_by_number[s.get("pr_number")]
                for s in batch_summaries
                if s.get("pr_number") in pr_by_number
            ]
            grounding = _pr_changed_files(batch_prs)
```

with:

```python
            target_path.parent.mkdir(parents=True, exist_ok=True)
            action = "edit" if target_path.exists() else "create"
            # CCE-110 layer 1: ground the author in the code the PRs touched.
            # Computed before the template so an agent-authored create can cite
            # the same files in source_files (CCE-117).
            batch_prs = [
                pr_by_number[s.get("pr_number")]
                for s in batch_summaries
                if s.get("pr_number") in pr_by_number
            ]
            grounding = _pr_changed_files(batch_prs)
            # CCE-117: agent-authored sections require description/source_files/
            # last_reviewed; the default template omits them, so Tier-1 lint
            # would drop the new page. Create-only — edits keep the existing
            # page's frontmatter. agent_fields is reused by the dry-run synth.
            agent_fields = None
            if (
                action == "create"
                and fmc.section_generator_for(rel, config) == "agent-authored"
            ):
                agent_fields = {
                    "description": _synthesize_agent_description(
                        batch_summaries, hint=hint
                    ),
                    "source_files": sorted(grounding),
                    "last_reviewed": now[:10],
                    "status": "draft",
                }
                fm_template = dict(agent_fields)
            else:
                fm_template = fmc.default_frontmatter_dict(
                    [
                        pr.get("url")
                        for s in batch_summaries
                        for pr in prs
                        if pr.get("number") == s.get("pr_number")
                    ]
                )
            _dk = doc_kind_by_target.get((lens, hint))
            if _dk:
                fm_template["doc_kind"] = _dk
```

(Net effect: the `batch_prs`/`grounding` block moves above the template; the template gains the agent-authored branch; `source_paths=sorted(grounding)` at the dispatch call is unchanged.)

- [ ] **Step 4: Run the test to verify it passes**

Run: `python3 -m pytest tests/orchestrator/test_agent_authored_create_frontmatter.py::test_agent_authored_create_uses_agent_template -q`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add scripts/orchestrator_runner.py tests/orchestrator/test_agent_authored_create_frontmatter.py
git commit -m "fix(CCE-117): generator-aware frontmatter template on the create path

The incremental authoring path branched unconditionally on the default
template; agent-authored sections now get description/source_files/
last_reviewed/status (create-only). source_files reuses PR grounding.

Co-Authored-By: Claude Opus 4.8 <noreply@anthropic.com>"
```

---

## Task 3: Dry-run synth is generator-aware (+ real-lint integration + default regression)

**Files:**

- Modify: `scripts/orchestrator_runner.py:~1501-1508`
- Test: `tests/orchestrator/test_agent_authored_create_frontmatter.py` (append)

- [ ] **Step 1: Write the failing tests**

Append to `tests/orchestrator/test_agent_authored_create_frontmatter.py`:

```python
def _run_subprocess(tmp_path: Path):
    import subprocess
    runner_path = (
        Path(__file__).parent.parent.parent / "scripts" / "orchestrator_runner.py"
    )
    return subprocess.run(
        [
            sys.executable, str(runner_path),
            "--repo-root", str(tmp_path),
            "--dry-run-subagents", str(FAKES),
            "--no-pr",
        ],
        capture_output=True, text=True,
    )


def test_created_agent_authored_page_passes_tier1_lint(tmp_path, init_host):
    """End-to-end: the dry-run synth writes a page that the REAL lint
    consumers accept (verify with the consumer, not test -f)."""
    init_host(_SEED_STATE, config_yaml=CONFIG_AGENT_AUTHORED)
    r = _run_subprocess(tmp_path)
    assert r.returncode == 0, r.stderr
    page = tmp_path / "docs" / "site-src" / "core" / "connectors" / "foo.md"
    assert page.exists(), "agent-authored create should land in dry-run"

    import frontmatter_schema
    import description_quality

    config = yaml.safe_load(CONFIG_AGENT_AUTHORED)
    ok_fs, msg_fs = frontmatter_schema.check_path(page, config)
    ok_dq, msg_dq = description_quality.check_path(page, config)
    assert ok_fs, f"frontmatter_schema: {msg_fs}"
    assert ok_dq, f"description_quality: {msg_dq}"


def test_default_section_create_unaffected(tmp_path, init_host):
    """Regression: a host with NO agent-authored section still gets the default
    template and its page passes its own (default) required-field set."""
    default_cfg = CONFIG_AGENT_AUTHORED.replace(
        "    - {key: core, path: core/, title: Core, generator: agent-authored}\n",
        "    - {key: core, path: core/, title: Core}\n",
    )
    init_host(_SEED_STATE, config_yaml=default_cfg)
    r = _run_subprocess(tmp_path)
    assert r.returncode == 0, r.stderr
    page = tmp_path / "docs" / "site-src" / "core" / "connectors" / "foo.md"
    assert page.exists()
    text = page.read_text()
    assert "status:" in text and "sources:" in text and "synthesized_into:" in text
    assert "source_files:" not in text  # not the agent-authored set
```

- [ ] **Step 2: Run the tests to verify the integration test fails**

Run: `python3 -m pytest tests/orchestrator/test_agent_authored_create_frontmatter.py -q`
Expected: `test_created_agent_authored_page_passes_tier1_lint` FAILS — the dry-run synth still writes `default_frontmatter_text()`, so `frontmatter_schema` reports `missing required field(s): description, source_files, last_reviewed`. (`test_default_section_create_unaffected` already passes; `test_agent_authored_create_uses_agent_template` still passes.)

- [ ] **Step 3: Rework the dry-run synth**

In `scripts/orchestrator_runner.py`, replace the block that currently reads (~`:1504`):

```python
                if dry_run_dir and not target_path.exists():
                    target_path.write_text(
                        fmc.default_frontmatter_text()
                        + f"# {hint}\n\nGenerated by docs-agent.\n"
                    )
```

with:

```python
                if dry_run_dir and not target_path.exists():
                    # CCE-117: mirror the template branch so the dry-run synth
                    # writes the same generator-aware frontmatter the real
                    # page-author would, keeping tests on the real lint path.
                    fm_text = (
                        fmc.agent_authored_frontmatter_text(**agent_fields)
                        if agent_fields is not None
                        else fmc.default_frontmatter_text()
                    )
                    target_path.write_text(
                        fm_text + f"# {hint}\n\nGenerated by docs-agent.\n"
                    )
```

- [ ] **Step 4: Run the tests to verify they pass**

Run: `python3 -m pytest tests/orchestrator/test_agent_authored_create_frontmatter.py -q`
Expected: PASS (3 passed).

- [ ] **Step 5: Commit**

```bash
git add scripts/orchestrator_runner.py tests/orchestrator/test_agent_authored_create_frontmatter.py
git commit -m "fix(CCE-117): dry-run synth writes generator-aware frontmatter

Mirror the create-path template branch in the dry-run synthesizer so the
test/dry-run path produces pages the real Tier-1 lint accepts. Adds the
real-consumer integration test (RED before, GREEN now) and a default-
section regression.

Co-Authored-By: Claude Opus 4.8 <noreply@anthropic.com>"
```

---

## Task 4: CHANGELOG + full-suite verification

**Files:**

- Modify: `CHANGELOG.md`

- [ ] **Step 1: Add the CHANGELOG entry**

Under the `Fixed` heading of the current unreleased section in `CHANGELOG.md`, add:

```markdown
- **CCE-117:** the incremental nightly authoring path now writes the
  agent-authored frontmatter set (`description`, `source_files`,
  `last_reviewed`, `status`) when creating a page in an `agent-authored`
  section, so Tier-1 `frontmatter_schema`/`description_quality` no longer
  drops those pages and the nightly run stops going partial on them.
```

(If no unreleased `Fixed` heading exists, add one in the right place following the file's existing structure.)

- [ ] **Step 2: Run the full suite**

Run: `python3 -m pytest -q`
Expected: PASS — prior count (1063) + the new tests, 0 failures. Investigate any failure before proceeding.

- [ ] **Step 3: Commit**

```bash
git add CHANGELOG.md
git commit -m "docs(CCE-117): changelog entry for generator-aware create frontmatter

Co-Authored-By: Claude Opus 4.8 <noreply@anthropic.com>"
```

---

## Self-review (completed by plan author)

- **Spec coverage:** helper (Task 1), production template branch (Task 2), dry-run synth branch (Task 3), real-consumer verification + default regression (Task 3), suite green + changelog (Task 4) — all spec sections mapped. AC 4 (next-nightly observation) is post-merge, noted in the spec, not a task.
- **Placeholder scan:** none — every code/test step shows complete code and exact commands.
- **Type/name consistency:** `_synthesize_agent_description(summaries, *, hint)`, `agent_fields` (dict with keys `description`/`source_files`/`last_reviewed`/`status`), `fmc.section_generator_for`, `fmc.agent_authored_frontmatter_dict`/`_text`, `fmc.default_frontmatter_dict`/`_text` used consistently across tasks and matched against the real module APIs.
- **Edit-path safety:** the new branch is gated on `action == "create"`, so existing agent-authored edits are untouched.

```

```
