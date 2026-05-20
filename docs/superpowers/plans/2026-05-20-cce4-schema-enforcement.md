# CCE-4 — Schema Enforcement + Agent Prompt Sharpening Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Wire `validate_and_parse` at the subagent dispatch boundary so off-contract LLM responses surface as a specific `schema_invalid:` reason in `partial_reasons` instead of being silently absorbed by `dict.get(...)` fallbacks, and embed canonical JSON Schemas inline in all seven agent system prompts to reduce the frequency of such drift.

**Architecture:** Add a thin `dispatch_validated(name, inputs, *, dry_run_dir, cwd) -> tuple[dict | None, list[str]]` wrapper in `scripts/orchestrator_runner.py` that composes the existing `dispatch_subagent` with `scripts/contracts.py:validate_and_parse`. Update all nine call sites (six in `orchestrator_runner.py`, three in `verify_runner.py`) to consume the tuple and append reasons to `state["current_run"]["partial_reasons"]`. Insert an `## Output schema (canonical)` section into each of the seven `agents/*.md` files containing the canonical JSON Schema. A new parameterized lint test asserts the `.md` schema block is JSON-equivalent to `agents/schemas/<name>.schema.json`.

**Tech Stack:** Python 3.11 stdlib + `jsonschema` 4.25.1 (already a runtime dep), `pytest` for tests. No new dependencies.

**Branch:** `feat/CCE-4-schema-enforcement` (already checked out, off main, design spec at `docs/superpowers/specs/2026-05-20-cce4-schema-enforcement-design.md` already committed at 111d8c9).

**Execution:** User has pre-authorized `/ship` per ticket once this plan is approved.

---

## File Structure

**Modify:**

- `scripts/orchestrator_runner.py` — add `dispatch_validated`; update 6 call sites (lines ~201, ~222, ~274, ~309, ~401, ~477).
- `scripts/verify_runner.py` — update 3 call sites (lines ~39, ~63, ~76).
- `agents/source-collector.md`, `pr-summarizer.md`, `page-author.md`, `content-validator.md`, `gap-detector.md`, `publish-verifier.md`, `notifier.md` — insert `## Output schema (canonical)` section.
- `CHANGELOG.md` — add v0.1.2 entry.

**Create:**

- `tests/orchestrator/test_dispatch_validated.py` — 4 boundary tests.
- `tests/orchestrator/test_schema_invalid_soft_fail.py` — 1 end-to-end test.
- `tests/orchestrator/fakes_schema_invalid/` — 7 fixture files (1 bad source-collector + 6 canonical).
- `tests/agents/__init__.py` — empty (new test package).
- `tests/agents/test_schema_md_sync.py` — parameterized drift-prevention lint (7 cases).

**Audit (potential modify, depending on findings):**

- `tests/orchestrator/test_pipeline_integration.py` — verify inline spy return values match canonical schemas; fix any that don't.
- `tests/orchestrator/test_verify_runner.py` — same audit for verify-side spies.

Total: ~395 lines added, no deletions.

---

## Phase A — Foundation: dispatch_validated wrapper

### Task 1: Write failing tests for `dispatch_validated`

**Files:**

- Create: `tests/orchestrator/test_dispatch_validated.py`

- [ ] **Step 1: Create the test file with all four boundary cases**

```python
# tests/orchestrator/test_dispatch_validated.py
from __future__ import annotations
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent.parent / "scripts"))
import orchestrator_runner  # noqa: E402


CANONICAL_SOURCE_COLLECTOR = {
    "prs": [
        {
            "number": 1,
            "url": "https://github.com/owner/repo/pull/1",
        }
    ],
    "jira_issues": [],
}


WRONG_SHAPE_SOURCE_COLLECTOR = {
    "status": "success",
    "modifications": [],
    "summary": "no work",
    "head_sha": "abc",
    "branches_scanned": [],
    "events_processed": 0,
    "verification": {},
}


def test_dispatch_validated_returns_raw_dict_on_schema_valid(monkeypatch, tmp_path):
    """Schema-valid response: returns (raw_dict, [])."""
    monkeypatch.setattr(
        orchestrator_runner,
        "dispatch_subagent",
        lambda name, inputs, *, dry_run_dir, cwd=None: dict(CANONICAL_SOURCE_COLLECTOR),
    )

    raw, reasons = orchestrator_runner.dispatch_validated(
        "source-collector", {}, dry_run_dir=None, cwd=tmp_path
    )

    assert raw == CANONICAL_SOURCE_COLLECTOR
    assert reasons == []


def test_dispatch_validated_returns_reason_on_schema_invalid(monkeypatch, tmp_path):
    """Schema-invalid response: returns (None, ['schema_invalid: <name>: ...'])."""
    monkeypatch.setattr(
        orchestrator_runner,
        "dispatch_subagent",
        lambda name, inputs, *, dry_run_dir, cwd=None: dict(WRONG_SHAPE_SOURCE_COLLECTOR),
    )

    raw, reasons = orchestrator_runner.dispatch_validated(
        "source-collector", {}, dry_run_dir=None, cwd=tmp_path
    )

    assert raw is None
    assert len(reasons) == 1
    assert reasons[0].startswith("schema_invalid: source-collector: "), reasons


def test_dispatch_validated_returns_empty_reasons_on_dispatch_none(monkeypatch, tmp_path):
    """Dispatch returned None (binary missing, nonzero rc, etc.): returns (None, [])."""
    monkeypatch.setattr(
        orchestrator_runner,
        "dispatch_subagent",
        lambda name, inputs, *, dry_run_dir, cwd=None: None,
    )

    raw, reasons = orchestrator_runner.dispatch_validated(
        "source-collector", {}, dry_run_dir=None, cwd=tmp_path
    )

    assert raw is None
    assert reasons == []


def test_dispatch_validated_returns_schema_missing_reason(monkeypatch, tmp_path):
    """Unknown agent name (schema file missing): returns (None, ['schema_missing: ...'])."""
    monkeypatch.setattr(
        orchestrator_runner,
        "dispatch_subagent",
        lambda name, inputs, *, dry_run_dir, cwd=None: {"anything": "valid"},
    )

    raw, reasons = orchestrator_runner.dispatch_validated(
        "no-such-agent", {}, dry_run_dir=None, cwd=tmp_path
    )

    assert raw is None
    assert reasons == ["schema_missing: no-such-agent"]
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `cd /Users/theo/Projects/engineering-docs-agent && python -m pytest tests/orchestrator/test_dispatch_validated.py -v`
Expected: 4 FAILED tests, all with `AttributeError: module 'orchestrator_runner' has no attribute 'dispatch_validated'`

- [ ] **Step 3: Commit the failing tests**

```bash
git add tests/orchestrator/test_dispatch_validated.py
git commit -m "$(cat <<'EOF'
test(CCE-4): add failing tests for dispatch_validated wrapper

Covers the four return paths the wrapper must produce:
- schema-valid: (raw_dict, [])
- schema-invalid: (None, ['schema_invalid: <name>: ...'])
- dispatch-None: (None, [])
- schema-missing: (None, ['schema_missing: <name>'])
EOF
)"
```

---

### Task 2: Implement `dispatch_validated`

**Files:**

- Modify: `scripts/orchestrator_runner.py:135` (insert just after `dispatch_subagent`'s closing `return None`)

- [ ] **Step 1: Add the wrapper function**

Open `scripts/orchestrator_runner.py`. Find the end of `dispatch_subagent` (the line `return None` after `except json.JSONDecodeError:`). Insert a blank line then the following function definition. Do **not** import `validate_and_parse` at the top of the file — the inline import inside the function keeps the import graph quiet during dry-run and matches the existing pattern in `verify_runner.py` (which does `from orchestrator_runner import ...` lazily).

```python
def dispatch_validated(
    name: str,
    inputs: dict,
    *,
    dry_run_dir: Path | None,
    cwd: Path | None = None,
) -> tuple[dict | None, list[str]]:
    """Compose dispatch_subagent with validate_and_parse.

    Returns:
      Schema-valid:   (raw_dict, [])
      Schema-invalid: (None, ["schema_invalid: <name>: <field-detail>"])
      Dispatch-None:  (None, [])  — caller adds its own generic reason
      Schema-missing: (None, ["schema_missing: <name>"]) — corrupted install
    """
    raw = dispatch_subagent(name, inputs, dry_run_dir=dry_run_dir, cwd=cwd)
    if raw is None:
        return None, []
    from contracts import validate_and_parse

    validated, reasons = validate_and_parse(name, raw)
    if validated is None:
        return None, reasons
    return raw, []
```

- [ ] **Step 2: Run the tests to verify they pass**

Run: `cd /Users/theo/Projects/engineering-docs-agent && python -m pytest tests/orchestrator/test_dispatch_validated.py -v`
Expected: 4 PASSED

- [ ] **Step 3: Run the full existing dispatch suite to confirm no regression**

Run: `cd /Users/theo/Projects/engineering-docs-agent && python -m pytest tests/orchestrator/test_dispatch_subagent.py -v`
Expected: 10 PASSED (the existing CCE-2 + CCE-3 tests)

- [ ] **Step 4: Commit the implementation**

```bash
git add scripts/orchestrator_runner.py
git commit -m "$(cat <<'EOF'
feat(CCE-4): add dispatch_validated wrapper

Composes dispatch_subagent with contracts.validate_and_parse.
Returns tuple[dict | None, list[str]] — caller threads reasons into
state.current_run.partial_reasons.

Returning the raw dict (not the dataclass) keeps existing
call-site dict.get(...) patterns unchanged.
EOF
)"
```

---

## Phase B — Pipeline test spy audit

This phase has to run _before_ the call-site swap. The integration tests in
`tests/orchestrator/test_pipeline_integration.py` use spy functions that
return canned dicts in place of real subagent dispatches. Once
`dispatch_validated` is wired into the call sites, every spy return that
fails its schema will surface a new `schema_invalid:` reason and break
unrelated assertions.

### Task 3: Audit and fix pipeline test spy return values

**Files:**

- Audit (and possibly modify): `tests/orchestrator/test_pipeline_integration.py`
- Audit (and possibly modify): `tests/orchestrator/test_verify_runner.py`
- Reference: `agents/schemas/*.schema.json` (already on disk)

- [ ] **Step 1: Find every spy that constructs a return dict inline**

Run: `cd /Users/theo/Projects/engineering-docs-agent && grep -n "def spying\|def fake_dispatch\|return {" tests/orchestrator/test_pipeline_integration.py tests/orchestrator/test_verify_runner.py`

Expected: a list of line numbers where spy functions are defined and where they construct return dicts. Each spy receives `(name, inputs, *, dry_run_dir, cwd=None)` and is monkeypatched onto `orchestrator_runner.dispatch_subagent`.

- [ ] **Step 2: For each inline-constructed return dict, validate it against its schema**

For each `name`-keyed return value (e.g. `if name == "source-collector": return {...}`), open `agents/schemas/<name>.schema.json` (with `-` → `_` in the filename) and confirm the returned dict satisfies the `required` fields. Required-field cheat sheet:

| Agent             | Required top-level keys              |
| ----------------- | ------------------------------------ |
| source-collector  | `prs`, `jira_issues`                 |
| pr-summarizer     | `pr_number`                          |
| page-author       | `ok`                                 |
| content-validator | `passed`, `failed`                   |
| gap-detector      | `pr_id`, `needs_spec`                |
| publish-verifier  | `verified`, `failed`, `build_status` |
| notifier          | `slack_ok`, `email_ok`               |

- [ ] **Step 3: Write a one-off probe to confirm each existing spy passes validation today**

Create a throwaway file (do not commit):

```python
# /tmp/probe_spy_validity.py
import json, sys
from pathlib import Path
sys.path.insert(0, "scripts")
from contracts import validate_and_parse

REPO = Path("/Users/theo/Projects/engineering-docs-agent")

# Paste each spy's return dict here, keyed by agent name, and run validate.
# Example:
candidates = {
    "source-collector": {"prs": [], "jira_issues": []},
}
for name, raw in candidates.items():
    validated, reasons = validate_and_parse(name, raw)
    print(name, "OK" if validated else f"INVALID: {reasons}")
```

Run: `python /tmp/probe_spy_validity.py`
Expected: every spy currently in the test suite prints `OK`. If any prints `INVALID`, that spy must be fixed in Step 4 before proceeding to Phase C — otherwise the Phase C commit makes existing tests red for unrelated reasons.

- [ ] **Step 4: Fix any spy that doesn't validate**

For any spy that printed `INVALID` in step 3, edit the spy's return dict in
`tests/orchestrator/test_pipeline_integration.py` or
`tests/orchestrator/test_verify_runner.py` to add the missing required
field. Use values that don't disrupt the assertion the test makes
(e.g. add an empty array, a zero, or `False` for booleans).

- [ ] **Step 5: Run the integration suite to confirm nothing changed**

Run: `cd /Users/theo/Projects/engineering-docs-agent && python -m pytest tests/orchestrator/test_pipeline_integration.py tests/orchestrator/test_verify_runner.py -v`
Expected: all tests still pass at the pre-CCE-4 count (~50 pipeline + 5 verify).

- [ ] **Step 6: Commit the audit results**

If step 4 didn't modify any files, skip this commit. Otherwise:

```bash
git add tests/orchestrator/test_pipeline_integration.py tests/orchestrator/test_verify_runner.py
git commit -m "$(cat <<'EOF'
test(CCE-4): align pipeline test spies with canonical schemas

Pre-condition for wiring dispatch_validated into call sites — any spy
that returned a non-canonical dict would surface a spurious
schema_invalid reason once the wrapper is live.
EOF
)"
```

- [ ] **Step 7: Delete the probe**

Run: `rm /tmp/probe_spy_validity.py`

---

## Phase C — Call-site integration

### Task 4: Switch `orchestrator_runner.py` call sites to `dispatch_validated`

**Files:**

- Modify: `scripts/orchestrator_runner.py` at six call sites:
  - L201 (`source-collector`)
  - L222 (`pr-summarizer`)
  - L274 (`page-author`)
  - L309 (`content-validator`)
  - L401 (`gap-detector`)
  - L477 (`notifier`)

- [ ] **Step 1: Update the source-collector call site**

Find the block starting at the current L201:

```python
    sources = dispatch_subagent(
        "source-collector", sc_inputs, dry_run_dir=dry_run_dir, cwd=repo_root
    )
    if sources is None:
        add_partial(state, "source_collector_invalid: returned None")
        sources = {"prs": [], "jira_issues": []}
```

Replace with:

```python
    sources, reasons = dispatch_validated(
        "source-collector", sc_inputs, dry_run_dir=dry_run_dir, cwd=repo_root
    )
    for r in reasons:
        add_partial(state, r)
    if sources is None:
        if not reasons:
            add_partial(state, "source_collector_invalid: returned None")
        sources = {"prs": [], "jira_issues": []}
```

The `if not reasons` guard ensures exactly one partial_reason line per failed dispatch — the specific schema reason if available, the generic `<name>_invalid: returned None` otherwise.

- [ ] **Step 2: Update the pr-summarizer call site**

Find the block at L222:

```python
        summary = dispatch_subagent(
            "pr-summarizer",
            {
                "pr": pr,
                "jira_context": jira_context,
                "lens_names": list(config.get("docs", {}).get("lens_paths", {}).keys()),
            },
            dry_run_dir=dry_run_dir,
            cwd=repo_root,
        )
        if summary is None:
            add_partial(state, f"pr_summarizer_invalid: pr={pr['number']}")
            continue
```

Replace with:

```python
        summary, reasons = dispatch_validated(
            "pr-summarizer",
            {
                "pr": pr,
                "jira_context": jira_context,
                "lens_names": list(config.get("docs", {}).get("lens_paths", {}).keys()),
            },
            dry_run_dir=dry_run_dir,
            cwd=repo_root,
        )
        for r in reasons:
            add_partial(state, r)
        if summary is None:
            if not reasons:
                add_partial(state, f"pr_summarizer_invalid: pr={pr['number']}")
            continue
```

- [ ] **Step 3: Update the page-author call site**

Find the block at L274:

```python
        out = dispatch_subagent(
            "page-author",
            {
                "target_path": str(target_path),
                ...
            },
            dry_run_dir=dry_run_dir,
            cwd=repo_root,
        )
        if out is None:
            add_partial(state, f"page_author_invalid: {rel}")
            continue
```

Replace with (preserving the existing `inputs` dict body verbatim):

```python
        out, reasons = dispatch_validated(
            "page-author",
            {
                "target_path": str(target_path),
                "action": action,
                "lens": lens,
                "summaries": batch_summaries,
                "voice_samples": voice_samples,
                "frontmatter_template": {
                    "status": "draft",
                    "sources": [
                        pr.get("url")
                        for s in batch_summaries
                        for pr in prs
                        if pr.get("number") == s.get("pr_number")
                    ],
                    "synthesized_into": [],
                },
            },
            dry_run_dir=dry_run_dir,
            cwd=repo_root,
        )
        for r in reasons:
            add_partial(state, r)
        if out is None:
            if not reasons:
                add_partial(state, f"page_author_invalid: {rel}")
            continue
```

- [ ] **Step 4: Update the content-validator call site**

Find the block at L309:

```python
        validation = dispatch_subagent(
            "content-validator",
            {
                "paths": authored,
                "config_path": str(cfg_path),
                "voice_samples": voice_samples,
            },
            dry_run_dir=dry_run_dir,
            cwd=repo_root,
        )
        if validation is None:
            add_partial(state, "content_validator_invalid: returned None")
            validation = {"failed": []}
```

Replace with:

```python
        validation, reasons = dispatch_validated(
            "content-validator",
            {
                "paths": authored,
                "config_path": str(cfg_path),
                "voice_samples": voice_samples,
            },
            dry_run_dir=dry_run_dir,
            cwd=repo_root,
        )
        for r in reasons:
            add_partial(state, r)
        if validation is None:
            if not reasons:
                add_partial(state, "content_validator_invalid: returned None")
            validation = {"failed": []}
```

- [ ] **Step 5: Update the gap-detector call site**

Find the block at L401:

```python
        verdict = dispatch_subagent(
            "gap-detector",
            {
                "pr_id": pr_id,
                "pr": pr,
                "config": {
                    ...
                },
                "dismissed_flags": list(dismissed),
            },
            dry_run_dir=dry_run_dir,
            cwd=repo_root,
        )
        if verdict is None:
            add_partial(state, f"gap_detector_invalid: pr_id={pr_id}")
            continue
```

Replace with:

```python
        verdict, reasons = dispatch_validated(
            "gap-detector",
            {
                "pr_id": pr_id,
                "pr": pr,
                "config": {
                    "allowlist_paths": config.get("gap_detection", {}).get(
                        "allowlist_paths", []
                    ),
                    "size_filter": config.get("gap_detection", {}).get(
                        "size_filter", {}
                    ),
                },
                "dismissed_flags": list(dismissed),
            },
            dry_run_dir=dry_run_dir,
            cwd=repo_root,
        )
        for r in reasons:
            add_partial(state, r)
        if verdict is None:
            if not reasons:
                add_partial(state, f"gap_detector_invalid: pr_id={pr_id}")
            continue
```

- [ ] **Step 6: Update the notifier call site**

Find the block at L477:

```python
    notifier_result = dispatch_subagent(
        "notifier",
        {
            "digest": digest,
            "slack_config": config.get("notifications", {}).get("slack", {}),
            "email_config": config.get("notifications", {}).get("email", {}),
            "mode": "run",
        },
        dry_run_dir=dry_run_dir,
        cwd=repo_root,
    )
    if notifier_result is None:
        add_partial(state, "notifier_invalid: returned None")
        state_path.write_text(json.dumps(state, indent=2))
    return 0
```

Replace with:

```python
    notifier_result, reasons = dispatch_validated(
        "notifier",
        {
            "digest": digest,
            "slack_config": config.get("notifications", {}).get("slack", {}),
            "email_config": config.get("notifications", {}).get("email", {}),
            "mode": "run",
        },
        dry_run_dir=dry_run_dir,
        cwd=repo_root,
    )
    for r in reasons:
        add_partial(state, r)
    if notifier_result is None:
        if not reasons:
            add_partial(state, "notifier_invalid: returned None")
        state_path.write_text(json.dumps(state, indent=2))
    return 0
```

- [ ] **Step 7: Run the orchestrator-side suite**

Run: `cd /Users/theo/Projects/engineering-docs-agent && python -m pytest tests/orchestrator/ -v`
Expected: all tests still pass — the spy fixtures from Phase B all validate cleanly, so no `schema_invalid` reasons are added in the existing test scenarios.

- [ ] **Step 8: Commit the orchestrator-side call-site swap**

```bash
git add scripts/orchestrator_runner.py
git commit -m "$(cat <<'EOF'
feat(CCE-4): wire dispatch_validated into 6 orchestrator call sites

source-collector, pr-summarizer, page-author, content-validator,
gap-detector, notifier all consume the (dict | None, reasons) tuple
and thread reasons into state.current_run.partial_reasons.

The 'if not reasons' guard ensures exactly one partial_reason line
per failed dispatch — the specific schema reason if available,
the generic <name>_invalid: returned None otherwise.
EOF
)"
```

---

### Task 5: Switch `verify_runner.py` call sites to `dispatch_validated`

**Files:**

- Modify: `scripts/verify_runner.py` at three call sites (L39 first notifier, L63 publish-verifier, L76 second notifier).

- [ ] **Step 1: Update the import**

At `scripts/verify_runner.py:10`, change:

```python
from orchestrator_runner import detect_repo, dispatch_subagent  # noqa: E402
```

to:

```python
from orchestrator_runner import detect_repo, dispatch_subagent, dispatch_validated  # noqa: E402
```

We keep `dispatch_subagent` in the import because the first notifier call in
the `gh failed` branch is fire-and-forget (no return value consumed, no
state to thread reasons into), so the existing unwrapped call is the simpler
fit there.

- [ ] **Step 2: Leave the first notifier (gh-failure branch) using dispatch_subagent**

At L39 the notifier is called as a fire-and-forget side effect when `gh
pr_view_files` fails. The return value is discarded and `state` isn't
written here (the function exits with `return 1` immediately after). Wrapping
it in `dispatch_validated` would just discard the reasons. Add a one-line
comment above the call so a future reader doesn't try to "fix" it:

Find the block starting at L37:

```python
    if not view.ok:
        if dry_run_dir is None:
            dispatch_subagent(
                "notifier",
                {
                    "digest": {
                        "pr_url": f"https://github.com/{repo['owner']}/{repo['name']}/pull/{pr_number}",
                        ...
                    },
                    ...
                },
                dry_run_dir=dry_run_dir,
                cwd=repo_root,
            )
            return 1
```

Insert a single comment line immediately above `dispatch_subagent(`:

```python
    if not view.ok:
        if dry_run_dir is None:
            # Fire-and-forget: return value discarded, no state to thread reasons into.
            dispatch_subagent(
                "notifier",
                ...
            )
            return 1
```

- [ ] **Step 3: Update the publish-verifier call site (inside try)**

Find the block at L62 inside `try:`:

```python
    try:
        verdict = dispatch_subagent(
            "publish-verifier",
            {
                "merged_pr_number": pr_number,
                "changed_paths": changed_paths,
                "publishing_config": cfg.get("publishing", {}),
                "repo": repo,
            },
            dry_run_dir=dry_run_dir,
            cwd=repo_root,
        )
        if verdict is None:
            verdict = {"verified": [], "failed": [], "build_status": "verifier_invalid"}
```

Replace with:

```python
    try:
        verdict, verify_reasons = dispatch_validated(
            "publish-verifier",
            {
                "merged_pr_number": pr_number,
                "changed_paths": changed_paths,
                "publishing_config": cfg.get("publishing", {}),
                "repo": repo,
            },
            dry_run_dir=dry_run_dir,
            cwd=repo_root,
        )
        for r in verify_reasons:
            state.setdefault("current_run", {}).setdefault("partial_reasons", []).append(r)
            state["current_run"]["partial"] = True
        if verdict is None:
            verdict = {"verified": [], "failed": [], "build_status": "verifier_invalid"}
```

Verify-runner does not import `add_partial`, so we inline the equivalent
two-line update (append reason + flip `partial` to True). `setdefault` is
defensive: if state was loaded without a `current_run`, this still works.

- [ ] **Step 4: Update the second notifier call site (inside try)**

Find the block at L76 inside the same `try:`:

```python
        dispatch_subagent(
            "notifier",
            {
                "digest": {
                    "pr_url": f"https://github.com/{repo['owner']}/{repo['name']}/pull/{pr_number}",
                    "verified": verdict.get("verified", []),
                    "failed_urls": verdict.get("failed", []),
                    "build_status": verdict.get("build_status"),
                },
                "slack_config": cfg.get("notifications", {}).get("slack", {}),
                "email_config": cfg.get("notifications", {}).get("email", {}),
                "mode": "verify",
            },
            dry_run_dir=dry_run_dir,
            cwd=repo_root,
        )
```

Replace with:

```python
        _notifier_result, notifier_reasons = dispatch_validated(
            "notifier",
            {
                "digest": {
                    "pr_url": f"https://github.com/{repo['owner']}/{repo['name']}/pull/{pr_number}",
                    "verified": verdict.get("verified", []),
                    "failed_urls": verdict.get("failed", []),
                    "build_status": verdict.get("build_status"),
                },
                "slack_config": cfg.get("notifications", {}).get("slack", {}),
                "email_config": cfg.get("notifications", {}).get("email", {}),
                "mode": "verify",
            },
            dry_run_dir=dry_run_dir,
            cwd=repo_root,
        )
        for r in notifier_reasons:
            state.setdefault("current_run", {}).setdefault("partial_reasons", []).append(r)
            state["current_run"]["partial"] = True
```

- [ ] **Step 5: Run the verify-runner suite**

Run: `cd /Users/theo/Projects/engineering-docs-agent && python -m pytest tests/orchestrator/test_verify_runner.py -v`
Expected: all 5 tests pass (the existing fakes_verify_ok / fakes_verify_fail fixtures all validate cleanly).

- [ ] **Step 6: Run the full suite to confirm Phase C is green**

Run: `cd /Users/theo/Projects/engineering-docs-agent && python -m pytest -v`
Expected: all 146 existing tests + 4 new dispatch_validated tests = 150 PASSED.

- [ ] **Step 7: Commit the verify_runner.py changes**

```bash
git add scripts/verify_runner.py
git commit -m "$(cat <<'EOF'
feat(CCE-4): wire dispatch_validated into 2 verify_runner call sites

publish-verifier and the post-verify notifier now thread schema
reasons into state.current_run.partial_reasons via the existing
try/finally state-write path.

The fire-and-forget notifier in the gh-failure branch stays on the
raw dispatch_subagent — its return value is discarded and there is no
state to write reasons into (the function returns 1 immediately after).
EOF
)"
```

---

## Phase D — Agent prompt sharpening + drift-prevention lint

### Task 6: Write failing drift-prevention lint test

**Files:**

- Create: `tests/agents/__init__.py` (empty)
- Create: `tests/agents/test_schema_md_sync.py`

- [ ] **Step 1: Create the empty package marker**

```bash
mkdir -p /Users/theo/Projects/engineering-docs-agent/tests/agents
touch /Users/theo/Projects/engineering-docs-agent/tests/agents/__init__.py
```

- [ ] **Step 2: Create the lint test file**

````python
# tests/agents/test_schema_md_sync.py
"""Drift-prevention: agents/<name>.md '## Output schema (canonical)' block
must be JSON-equivalent to agents/schemas/<name>.schema.json."""
from __future__ import annotations
import json
import re
from pathlib import Path

import pytest

AGENTS_DIR = Path(__file__).parent.parent.parent / "agents"
SCHEMA_BLOCK = re.compile(
    r"## Output schema \(canonical\)\s*\n+```json\s*\n(.+?)\n```", re.DOTALL
)


@pytest.mark.parametrize(
    "agent_name",
    [
        "source-collector",
        "pr-summarizer",
        "page-author",
        "content-validator",
        "gap-detector",
        "publish-verifier",
        "notifier",
    ],
)
def test_md_schema_block_matches_canonical_schema_file(agent_name: str):
    md_path = AGENTS_DIR / f"{agent_name}.md"
    schema_path = (
        AGENTS_DIR / "schemas" / f"{agent_name.replace('-', '_')}.schema.json"
    )
    assert md_path.exists(), f"missing {md_path}"
    assert schema_path.exists(), f"missing {schema_path}"

    md_text = md_path.read_text()
    schema_text = schema_path.read_text()

    match = SCHEMA_BLOCK.search(md_text)
    assert match, (
        f"{agent_name}.md is missing the '## Output schema (canonical)' block. "
        f"Add it between '## Inputs' and '## Procedure', containing the "
        f"contents of agents/schemas/{agent_name.replace('-', '_')}.schema.json "
        f"inside a ```json fenced block."
    )

    md_schema = json.loads(match.group(1))
    canonical = json.loads(schema_text)
    assert md_schema == canonical, (
        f"{agent_name}.md schema block has drifted from "
        f"agents/schemas/{agent_name.replace('-', '_')}.schema.json. "
        f"Either update the .md block or update the .json file — they must be "
        f"JSON-equivalent (compared after json.loads on both sides)."
    )
````

- [ ] **Step 3: Run the lint test to verify all 7 cases fail**

Run: `cd /Users/theo/Projects/engineering-docs-agent && python -m pytest tests/agents/test_schema_md_sync.py -v`
Expected: 7 FAILED — each with `AssertionError: <name>.md is missing the '## Output schema (canonical)' block.`

- [ ] **Step 4: Commit the failing lint**

```bash
git add tests/agents/__init__.py tests/agents/test_schema_md_sync.py
git commit -m "$(cat <<'EOF'
test(CCE-4): add failing drift-prevention lint for agent schema blocks

Asserts agents/<name>.md '## Output schema (canonical)' block is
JSON-equivalent to agents/schemas/<name>.schema.json for all 7 agents.
Currently fails because no agent .md contains the block yet — the next
task adds them.
EOF
)"
```

---

### Task 7: Add `## Output schema (canonical)` block to all 7 agent .md files

**Files:**

- Modify: `agents/source-collector.md`, `pr-summarizer.md`, `page-author.md`, `content-validator.md`, `gap-detector.md`, `publish-verifier.md`, `notifier.md`

Each `.md` file gets the same shape of insert: a new H2 section placed
between the existing `## Inputs` and `## Output contract` sections.

- [ ] **Step 1: Get the canonical schema for each agent**

For each agent, read its schema file. Example for source-collector:

```bash
cat /Users/theo/Projects/engineering-docs-agent/agents/schemas/source_collector.schema.json
```

You'll embed the verbatim contents of each schema file into the corresponding
`.md` file. Whitespace within the JSON doesn't matter for the lint test (it
parses both sides with `json.loads()`), so a faithful copy of the file
content is the easiest approach.

- [ ] **Step 2: Edit `agents/source-collector.md`**

Find the existing line:

```markdown
## Output contract
```

Insert ABOVE that line (preserve a blank line below the new block):

````markdown
## Output schema (canonical)

```json
{
  "$schema": "http://json-schema.org/draft-07/schema#",
  "title": "source-collector output",
  "type": "object",
  "required": ["prs", "jira_issues"],
  "properties": {
    "prs": {
      "type": "array",
      "items": {
        "type": "object",
        "required": ["number", "url"],
        "properties": {
          "number": { "type": "integer" },
          "url": { "type": "string" },
          "title": { "type": "string" },
          "body": { "type": ["string", "null"] },
          "merge_sha": { "type": "string" },
          "merged_at": { "type": "string" },
          "author": { "type": "string" },
          "files": { "type": "array" },
          "labels": { "type": "array" },
          "jira_keys": { "type": "array", "items": { "type": "string" } }
        }
      }
    },
    "jira_issues": { "type": "array" },
    "error": { "type": ["string", "null"] },
    "partial": { "type": "boolean" }
  }
}
```

Return ONLY a JSON object that validates against this schema. No prose, no markdown fences around the response, no commentary.
````

Then edit the existing line `## Output contract` line to insert (immediately
below the heading, before the existing `Return ONLY a JSON object matching:` line):

```markdown
The canonical schema is in §Output schema above. The shape described here is the same; the schema is authoritative if they disagree.
```

- [ ] **Step 3: Edit `agents/pr-summarizer.md`**

Read the schema: `cat /Users/theo/Projects/engineering-docs-agent/agents/schemas/pr_summarizer.schema.json`

Insert the same shape of `## Output schema (canonical)` block above the existing `## Output contract` heading. Body of the json fence is the verbatim file contents. Add the same "Return ONLY a JSON object..." line and the same "The canonical schema is in §Output schema above..." pointer line in the existing `## Output contract` section.

- [ ] **Step 4: Edit `agents/page-author.md`**

Read the schema: `cat /Users/theo/Projects/engineering-docs-agent/agents/schemas/page_author.schema.json`

In `agents/page-author.md`, find the existing line `## Output contract` and insert ABOVE it a new section: a level-2 heading `## Output schema (canonical)`, a blank line, a ` ```json ` fence containing the verbatim contents of `page_author.schema.json`, a closing ` ``` ` fence, a blank line, then the line `Return ONLY a JSON object that validates against this schema. No prose, no markdown fences around the response, no commentary.` followed by a blank line. Then in the existing `## Output contract` section, insert immediately below the heading (before any pre-existing prose) the line: `The canonical schema is in §Output schema above. The shape described here is the same; the schema is authoritative if they disagree.`

- [ ] **Step 5: Edit `agents/content-validator.md`**

Read the schema: `cat /Users/theo/Projects/engineering-docs-agent/agents/schemas/content_validator.schema.json`

In `agents/content-validator.md`, find the existing line `## Output contract` and insert ABOVE it a new section: a level-2 heading `## Output schema (canonical)`, a blank line, a ` ```json ` fence containing the verbatim contents of `content_validator.schema.json`, a closing ` ``` ` fence, a blank line, then the line `Return ONLY a JSON object that validates against this schema. No prose, no markdown fences around the response, no commentary.` followed by a blank line. Then in the existing `## Output contract` section, insert immediately below the heading (before any pre-existing prose) the line: `The canonical schema is in §Output schema above. The shape described here is the same; the schema is authoritative if they disagree.`

- [ ] **Step 6: Edit `agents/gap-detector.md`**

Read the schema: `cat /Users/theo/Projects/engineering-docs-agent/agents/schemas/gap_detector.schema.json`

In `agents/gap-detector.md`, find the existing line `## Output contract` and insert ABOVE it a new section: a level-2 heading `## Output schema (canonical)`, a blank line, a ` ```json ` fence containing the verbatim contents of `gap_detector.schema.json`, a closing ` ``` ` fence, a blank line, then the line `Return ONLY a JSON object that validates against this schema. No prose, no markdown fences around the response, no commentary.` followed by a blank line. Then in the existing `## Output contract` section, insert immediately below the heading (before any pre-existing prose) the line: `The canonical schema is in §Output schema above. The shape described here is the same; the schema is authoritative if they disagree.`

- [ ] **Step 7: Edit `agents/publish-verifier.md`**

Read the schema: `cat /Users/theo/Projects/engineering-docs-agent/agents/schemas/publish_verifier.schema.json`

In `agents/publish-verifier.md`, find the existing line `## Output contract` and insert ABOVE it a new section: a level-2 heading `## Output schema (canonical)`, a blank line, a ` ```json ` fence containing the verbatim contents of `publish_verifier.schema.json`, a closing ` ``` ` fence, a blank line, then the line `Return ONLY a JSON object that validates against this schema. No prose, no markdown fences around the response, no commentary.` followed by a blank line. Then in the existing `## Output contract` section, insert immediately below the heading (before any pre-existing prose) the line: `The canonical schema is in §Output schema above. The shape described here is the same; the schema is authoritative if they disagree.`

- [ ] **Step 8: Edit `agents/notifier.md`**

Read the schema: `cat /Users/theo/Projects/engineering-docs-agent/agents/schemas/notifier.schema.json`

In `agents/notifier.md`, find the existing line `## Output contract` and insert ABOVE it a new section: a level-2 heading `## Output schema (canonical)`, a blank line, a ` ```json ` fence containing the verbatim contents of `notifier.schema.json`, a closing ` ``` ` fence, a blank line, then the line `Return ONLY a JSON object that validates against this schema. No prose, no markdown fences around the response, no commentary.` followed by a blank line. Then in the existing `## Output contract` section, insert immediately below the heading (before any pre-existing prose) the line: `The canonical schema is in §Output schema above. The shape described here is the same; the schema is authoritative if they disagree.`

- [ ] **Step 9: Run the lint to verify all 7 cases pass**

Run: `cd /Users/theo/Projects/engineering-docs-agent && python -m pytest tests/agents/test_schema_md_sync.py -v`
Expected: 7 PASSED

- [ ] **Step 10: Run the full suite to confirm nothing regressed**

Run: `cd /Users/theo/Projects/engineering-docs-agent && python -m pytest -v`
Expected: 150 + 7 = 157 PASSED.

- [ ] **Step 11: Commit the agent prompt updates**

```bash
git add agents/*.md
git commit -m "$(cat <<'EOF'
feat(CCE-4): embed canonical JSON Schema in all 7 agent system prompts

Each agent .md gains an '## Output schema (canonical)' section containing
the verbatim contents of agents/schemas/<name>.schema.json plus a
'Return ONLY a JSON object that validates against this schema' instruction.

The pre-existing '## Output contract' prose stays but gains a pointer line:
the schema is authoritative if the two disagree.

Drift between .md and .json is now caught at lint time by
tests/agents/test_schema_md_sync.py.
EOF
)"
```

---

## Phase E — Schema-invalid integration test

### Task 8: Create `fakes_schema_invalid/` fixtures

**Files:**

- Create: `tests/orchestrator/fakes_schema_invalid/fake_source_collector.json`
- Create: `tests/orchestrator/fakes_schema_invalid/fake_pr_summarizer.json`
- Create: `tests/orchestrator/fakes_schema_invalid/fake_page_author.json`
- Create: `tests/orchestrator/fakes_schema_invalid/fake_content_validator.json`
- Create: `tests/orchestrator/fakes_schema_invalid/fake_gap_detector.json`
- Create: `tests/orchestrator/fakes_schema_invalid/fake_publish_verifier.json`
- Create: `tests/orchestrator/fakes_schema_invalid/fake_notifier.json`

The pipeline only loads fixtures for agents it actually dispatches. With
source-collector returning the wrong shape, `sources` becomes the empty
fallback and the per-PR loops (pr-summarizer, page-author, gap-detector) all
iterate over an empty list. content-validator only runs if `authored` is
non-empty (it won't be). Only the notifier runs unconditionally at the end.
So in this scenario, only `fake_source_collector.json` and
`fake_notifier.json` are strictly required.

We create all seven anyway for completeness and as a future-proofing baseline
— if someone modifies the pipeline to call additional agents during a
no-PRs run, the test won't silently start returning `None` for missing
fixtures.

- [ ] **Step 1: Create the bad source-collector fixture (the Mode B observed wrong shape)**

```bash
mkdir -p /Users/theo/Projects/engineering-docs-agent/tests/orchestrator/fakes_schema_invalid
```

Write `tests/orchestrator/fakes_schema_invalid/fake_source_collector.json`:

```json
{
  "status": "success",
  "modifications": [],
  "summary": "No source changes detected in the specified window.",
  "head_sha": "abc123def456",
  "branches_scanned": ["main"],
  "events_processed": 0,
  "verification": {
    "schema_compliance": "pass",
    "validation_errors": []
  }
}
```

This is the literal off-contract shape observed during the v0.1.1 Mode B
smoke run against ADIS that motivated CCE-4 — `status`/`modifications`/
`summary`/etc. with no `prs` or `jira_issues`.

- [ ] **Step 2: Create the canonical pr-summarizer fixture**

Write `tests/orchestrator/fakes_schema_invalid/fake_pr_summarizer.json`:

```json
{
  "pr_number": 1,
  "what_changed": "placeholder",
  "why": "placeholder",
  "breaking": false,
  "doc_targets": [],
  "notes": ""
}
```

- [ ] **Step 3: Create the canonical page-author fixture**

Write `tests/orchestrator/fakes_schema_invalid/fake_page_author.json`:

```json
{
  "ok": true,
  "path": "docs/site-src/placeholder.md",
  "action": "create",
  "diff_summary": "placeholder",
  "error": null
}
```

- [ ] **Step 4: Create the canonical content-validator fixture**

Write `tests/orchestrator/fakes_schema_invalid/fake_content_validator.json`:

```json
{
  "passed": [],
  "failed": []
}
```

- [ ] **Step 5: Create the canonical gap-detector fixture**

Write `tests/orchestrator/fakes_schema_invalid/fake_gap_detector.json`:

```json
{
  "pr_id": "owner/repo#1",
  "needs_spec": false,
  "reasoning": "placeholder",
  "confidence": "medium",
  "tier": "llm"
}
```

- [ ] **Step 6: Create the canonical publish-verifier fixture**

Write `tests/orchestrator/fakes_schema_invalid/fake_publish_verifier.json`:

```json
{
  "verified": [],
  "failed": [],
  "build_status": "success"
}
```

- [ ] **Step 7: Create the canonical notifier fixture**

Write `tests/orchestrator/fakes_schema_invalid/fake_notifier.json`:

```json
{
  "slack_ok": true,
  "email_ok": true,
  "errors": []
}
```

- [ ] **Step 8: Verify each fixture against its schema with a one-off probe**

Create a throwaway probe (do not commit):

```python
# /tmp/probe_fakes_schema_invalid.py
import json, sys
from pathlib import Path
sys.path.insert(0, "scripts")
from contracts import validate_and_parse

FIXTURES = Path("tests/orchestrator/fakes_schema_invalid")
mapping = {
    "source-collector": "fake_source_collector.json",  # expected INVALID
    "pr-summarizer": "fake_pr_summarizer.json",
    "page-author": "fake_page_author.json",
    "content-validator": "fake_content_validator.json",
    "gap-detector": "fake_gap_detector.json",
    "publish-verifier": "fake_publish_verifier.json",
    "notifier": "fake_notifier.json",
}
for name, fname in mapping.items():
    raw = json.loads((FIXTURES / fname).read_text())
    validated, reasons = validate_and_parse(name, raw)
    label = "INVALID" if validated is None else "OK"
    extra = f" [{reasons[0]}]" if reasons else ""
    print(f"{name}: {label}{extra}")
```

Run: `cd /Users/theo/Projects/engineering-docs-agent && python /tmp/probe_fakes_schema_invalid.py`
Expected:

```
source-collector: INVALID [schema_invalid: source-collector: 'prs' is a required property]
pr-summarizer: OK
page-author: OK
content-validator: OK
gap-detector: OK
publish-verifier: OK
notifier: OK
```

If anything other than `source-collector` is INVALID, fix that fixture
before proceeding.

- [ ] **Step 9: Delete the probe**

Run: `rm /tmp/probe_fakes_schema_invalid.py`

- [ ] **Step 10: Commit the fixtures**

```bash
git add tests/orchestrator/fakes_schema_invalid/
git commit -m "$(cat <<'EOF'
test(CCE-4): add fakes_schema_invalid fixtures for soft-fail integration test

fake_source_collector.json reproduces the literal off-contract shape
observed during the v0.1.1 Mode B smoke run against ADIS — status,
modifications, summary, head_sha, etc. with no prs or jira_issues.

The other six fixtures are canonical / valid so the test isolates the
source-collector validation path; if the pipeline starts calling more
agents during a no-PRs run, they won't surface unrelated failures.
EOF
)"
```

---

### Task 9: Write the schema-invalid soft-fail integration test

**Files:**

- Create: `tests/orchestrator/test_schema_invalid_soft_fail.py`

- [ ] **Step 1: Create the integration test**

```python
# tests/orchestrator/test_schema_invalid_soft_fail.py
"""End-to-end: when source-collector returns a schema-invalid response,
the pipeline records a specific schema_invalid reason in partial_reasons,
falls through to the empty-prs path, exits 0, and does NOT also append the
generic source_collector_invalid: returned None reason."""
from __future__ import annotations
import json
import os
import subprocess
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent.parent / "scripts"))

ORCH_RUNNER = (
    Path(__file__).parent.parent.parent / "scripts" / "orchestrator_runner.py"
)
FAKES_SCHEMA_INVALID = Path(__file__).parent / "fakes_schema_invalid"

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
lint: { tier1: default }
publishing:
  base_url: https://example.com
  build_workflow: deploy.yml
  url_map_rule: standard
  verify_timeout_seconds: 60
notifications:
  slack: { enabled: false }
  email: { enabled: false }
"""


def _init_host(tmp_path: Path) -> Path:
    (tmp_path / ".engineering-docs-agent").mkdir()
    (tmp_path / ".engineering-docs-agent" / "config.yml").write_text(CONFIG_YAML)
    state_path = tmp_path / ".engineering-docs-agent" / "state.json"
    state_path.write_text(json.dumps({"version": "1"}))
    subprocess.run(["git", "-C", str(tmp_path), "init", "-q"], check=True)
    subprocess.run(
        ["git", "-C", str(tmp_path), "config", "user.email", "test@example.com"],
        check=True,
    )
    subprocess.run(
        ["git", "-C", str(tmp_path), "config", "user.name", "Test"], check=True
    )
    (tmp_path / "README.md").write_text("init")
    subprocess.run(
        ["git", "-C", str(tmp_path), "add", "README.md"], check=True
    )
    subprocess.run(
        ["git", "-C", str(tmp_path), "commit", "-q", "-m", "init"], check=True
    )
    return state_path


def test_schema_invalid_source_collector_yields_specific_reason(tmp_path):
    """Bad source-collector shape → schema_invalid reason, no generic redundancy."""
    state_path = _init_host(tmp_path)

    env = {**os.environ, "GITHUB_REPOSITORY": "owner/repo"}
    r = subprocess.run(
        [
            sys.executable,
            str(ORCH_RUNNER),
            "--repo-root",
            str(tmp_path),
            "--no-pr",
            "--dry-run-subagents",
            str(FAKES_SCHEMA_INVALID),
        ],
        capture_output=True,
        text=True,
        env=env,
    )
    assert r.returncode == 0, (
        f"pipeline should exit 0 on schema-invalid soft-fail; "
        f"got rc={r.returncode}\nstdout={r.stdout}\nstderr={r.stderr}"
    )

    state = json.loads(state_path.read_text())
    reasons = state["current_run"]["partial_reasons"]

    schema_reasons = [r for r in reasons if r.startswith("schema_invalid: source-collector: ")]
    assert len(schema_reasons) == 1, (
        f"expected exactly one schema_invalid: source-collector: reason; got reasons={reasons}"
    )

    generic = [r for r in reasons if r == "source_collector_invalid: returned None"]
    assert generic == [], (
        f"specific schema reason should suppress the generic returned-None reason; got {reasons}"
    )

    assert state["current_run"]["partial"] is True
    assert state["current_run"]["pr_number"] is None
```

- [ ] **Step 2: Run the integration test**

Run: `cd /Users/theo/Projects/engineering-docs-agent && python -m pytest tests/orchestrator/test_schema_invalid_soft_fail.py -v`
Expected: 1 PASSED

If it fails, the most likely cause is the orchestrator picking up unexpected
behavior from the not-yet-loaded fixtures for un-dispatched agents — re-read
the assertion error to confirm the specific failure mode before debugging.

- [ ] **Step 3: Run the entire suite to verify the final test count**

Run: `cd /Users/theo/Projects/engineering-docs-agent && python -m pytest -v`
Expected: 146 (existing) + 4 (dispatch_validated) + 7 (schema_md_sync) + 1 (schema_invalid_soft_fail) = **158 PASSED**.

- [ ] **Step 4: Commit the integration test**

```bash
git add tests/orchestrator/test_schema_invalid_soft_fail.py
git commit -m "$(cat <<'EOF'
test(CCE-4): add end-to-end schema-invalid soft-fail integration test

Asserts that a Mode-B-style off-contract source-collector response:
- produces exactly one schema_invalid: source-collector: ... reason
- does NOT also append the generic source_collector_invalid: returned None
- still exits 0 (soft-fail contract preserved)
- sets partial: true on current_run
- emits no PR (pr_number is None)
EOF
)"
```

---

## Phase F — Finalization

### Task 10: Update CHANGELOG

**Files:**

- Modify: `CHANGELOG.md`

- [ ] **Step 1: Insert the v0.1.2 entry at the top**

At `CHANGELOG.md:1` find the existing first line `# Changelog` and the next line `## [0.1.1] — 2026-05-20`. Insert a new entry between them (immediately below `# Changelog`):

```markdown
# Changelog

## [0.1.2] — 2026-05-20

### Schema enforcement (CCE-4)

- New `dispatch_validated(name, inputs, *, dry_run_dir, cwd) -> tuple[dict | None, list[str]]` in `scripts/orchestrator_runner.py` composes `dispatch_subagent` with `contracts.validate_and_parse`. Off-contract LLM responses now surface as a specific `schema_invalid: <name>: <field-detail>` line in `state.current_run.partial_reasons` instead of being silently absorbed by `dict.get(...)` fallbacks.
- All nine subagent call sites (six in `orchestrator_runner.py`, two effective in `verify_runner.py`) consume the new tuple. The `if not reasons` guard ensures exactly one reason line per failed dispatch — specific schema reason if available, the existing generic `<name>_invalid: returned None` otherwise.
- All seven agent `.md` files gain an `## Output schema (canonical)` section containing the canonical JSON Schema from `agents/schemas/<name>.schema.json`. The schema is now authoritative in the agent system prompt itself, not just in code.
- New drift-prevention lint at `tests/agents/test_schema_md_sync.py` (parameterized over all 7 agents) asserts the `.md` schema block is JSON-equivalent to the `.json` file.
- New `dispatch_validated` boundary tests (4 cases) at `tests/orchestrator/test_dispatch_validated.py`.
- New end-to-end schema-invalid soft-fail integration test at `tests/orchestrator/test_schema_invalid_soft_fail.py` with `fakes_schema_invalid/` fixtures (the literal Mode-B observed wrong shape).
- No new runtime dependencies. No new configuration surfaces. Soft-fail contract from v0.1.1 preserved.

## [0.1.1] — 2026-05-20
```

- [ ] **Step 2: Verify the CHANGELOG renders sanely**

Run: `cd /Users/theo/Projects/engineering-docs-agent && head -30 CHANGELOG.md`
Expected: the new v0.1.2 entry sits between `# Changelog` and `## [0.1.1] — 2026-05-20`, with no duplicate headings.

- [ ] **Step 3: Commit the CHANGELOG**

```bash
git add CHANGELOG.md
git commit -m "$(cat <<'EOF'
docs(CCE-4): add v0.1.2 changelog entry for schema enforcement
EOF
)"
```

---

### Task 11: Final verification and PR open

**Files:**

- No file changes. Verification + push.

- [ ] **Step 1: Run the full test suite one final time**

Run: `cd /Users/theo/Projects/engineering-docs-agent && python -m pytest -v 2>&1 | tail -30`
Expected: `158 passed` (the +12 over the v0.1.1 baseline of 146).

- [ ] **Step 2: Confirm the diff against main matches the spec's "Files touched" table**

Run: `cd /Users/theo/Projects/engineering-docs-agent && git diff main --stat`
Expected files touched:

- `scripts/orchestrator_runner.py` (+wrapper, 6 call sites)
- `scripts/verify_runner.py` (+import, 2 effective call sites, 1 comment)
- `agents/*.md` × 7 (each: +canonical schema block, +pointer line)
- `tests/agents/__init__.py` (new, empty)
- `tests/agents/test_schema_md_sync.py` (new)
- `tests/orchestrator/test_dispatch_validated.py` (new)
- `tests/orchestrator/test_schema_invalid_soft_fail.py` (new)
- `tests/orchestrator/fakes_schema_invalid/*.json` (new × 7)
- `CHANGELOG.md` (+v0.1.2 entry)
- `docs/superpowers/specs/2026-05-20-cce4-schema-enforcement-design.md` (already committed at 111d8c9)
- `docs/superpowers/plans/2026-05-20-cce4-schema-enforcement.md` (this file)

- [ ] **Step 3: Push the branch and open the PR via /ship**

Per the user's pre-authorization, run `/ship` to execute the full chain (test → verify-agent → simplify → code-review → commit → push + PR → Jira update).

`/ship` will:

- Detect the test command via `~/.claude/skills/ship/lib/detect-test-cmd.sh`.
- Run the suite (must pass — already verified in Step 1).
- Dispatch verify-agent and (unless `--no-simplify`) simplify.
- Dispatch code-reviewer with `BASE_SHA=$(git merge-base HEAD main)` and `HEAD_SHA=$(git rev-parse HEAD)`.
- Push to remote and open the PR. Title format: `feat(CCE-4): schema enforcement + agent prompt sharpening`. Body summarizes the spec + plan + test count delta.
- Update CCE-4 in Jira via `extract-jira-key.sh` (it reads the branch name `feat/CCE-4-schema-enforcement` and finds `CCE-4`).

If `/ship` halts at any stage, address the surfaced issue and re-invoke. The lifecycle is idempotent; see `~/.claude/skills/ship/spokes/idempotency.md`.

- [ ] **Step 4: Confirm CCE-4 reaches Done in Jira**

After `/ship`'s Jira stage completes, open `https://designitright.atlassian.net/browse/CCE-4` and confirm the transition succeeded. If the auto-transition didn't fire (e.g. Jira workflow requires manual review), comment the PR URL on the ticket and transition manually.

---

## Test plan summary

| Test                                                   | Cases   | Phase  |
| ------------------------------------------------------ | ------- | ------ |
| `tests/orchestrator/test_dispatch_validated.py`        | 4       | A      |
| Pipeline spy audit (existing files, possibly modified) | ~50     | B      |
| Existing dispatch + verify suites unchanged            | 15      | A, C   |
| `tests/agents/test_schema_md_sync.py`                  | 7       | D      |
| `tests/orchestrator/test_schema_invalid_soft_fail.py`  | 1       | E      |
| **Net new test count**                                 | **+12** | total  |
| **Total after CCE-4**                                  | **158** | target |
