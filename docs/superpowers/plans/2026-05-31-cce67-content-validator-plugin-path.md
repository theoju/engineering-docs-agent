# CCE-67 — content-validator plugin-script path resolution Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Pass `plugin_root` through the content-validator dispatch payload so the subagent invokes `lint_runner.py` at the absolute plugin path instead of the host repo root. Restores Tier-1 lint validation on every onboarded host and unblocks CCE-64 production proof.

**Architecture:** The orchestrator already resolves `_PLUGIN_ROOT` at module load (`scripts/orchestrator_runner.py:64`). It is currently passed to the claude CLI via `--plugin-dir` for plugin discovery but is NOT exposed in subagent input payloads. This change adds it as a fourth field of the content-validator input JSON and updates the agent contract to interpolate it into the `lint_runner.py` invocation. The other six agents are unchanged (audit confirmed only content-validator shells out to a plugin script).

**Tech Stack:** Python stdlib (`pathlib.Path`), pytest with monkeypatched dispatch, Markdown agent contracts. No new runtime dependencies.

**Test runner:** `python3 -m pytest`

**Commit trailer (required on every commit):** `Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>`

**Branch:** `fix/CCE-67-content-validator-plugin-path` (already checked out; spec commit at 9931891 above main 5ab1e94)

**Never use:** `-f`, `--force`, `--no-verify`, `--amend`.

**Spec:** `docs/superpowers/specs/2026-05-31-cce67-content-validator-plugin-path.md`

---

### Task 1: Failing regression test — orchestrator must inject `plugin_root` into content-validator payload

**Files:**

- Modify: `tests/orchestrator/test_pipeline_integration.py` (append new test function)

**Rationale:** Mirrors the proven pattern at lines 291-328 (`test_voice_samples_loaded_and_passed_to_authoring`) — monkeypatches `runner.dispatch_subagent`, captures the content-validator call, asserts the new field is present and resolves to a real file. This locks in the contract.

- [ ] **Step 1: Write the failing test**

Append to `tests/orchestrator/test_pipeline_integration.py`:

```python
def test_content_validator_dispatch_includes_plugin_root(tmp_path, monkeypatch):
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

    _init_host(tmp_path)
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
```

- [ ] **Step 2: Run the test to verify it fails**

Run: `python3 -m pytest tests/orchestrator/test_pipeline_integration.py::test_content_validator_dispatch_includes_plugin_root -v`

Expected: FAIL with `AssertionError: content-validator payload missing plugin_root`.

- [ ] **Step 3: Commit the failing test**

```bash
git add tests/orchestrator/test_pipeline_integration.py
git commit -m "$(cat <<'EOF'
test(CCE-67): failing regression for plugin_root in content-validator payload

Asserts the orchestrator dispatches content-validator with a plugin_root field
whose value is an absolute path resolving to scripts/lint/lint_runner.py.
Mirrors the test_voice_samples_loaded_and_passed_to_authoring pattern.
Currently failing — the production code does not pass plugin_root.

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>
EOF
)"
```

---

### Task 2: Orchestrator — inject `plugin_root` into content-validator dispatch

**Files:**

- Modify: `scripts/orchestrator_runner.py:1194-1203`

- [ ] **Step 1: Locate the dispatch site**

Open `scripts/orchestrator_runner.py`. Find the call to `dispatch_validated("content-validator", ...)` near line 1194.

- [ ] **Step 2: Add the field**

Edit the input dict to include `plugin_root` (use `_PLUGIN_ROOT` from `scripts/orchestrator_runner.py:64`):

```python
validation, reasons = dispatch_validated(
    "content-validator",
    {
        "paths": authored,
        "config_path": str(cfg_path),
        "voice_samples": voice_samples,
        "plugin_root": str(_PLUGIN_ROOT),
    },
    dry_run_dir=dry_run_dir,
    cwd=repo_root,
)
```

Use `str(_PLUGIN_ROOT)` for JSON serializability; `_PLUGIN_ROOT` is a `Path` object.

- [ ] **Step 3: Run Task 1's test to verify it passes**

Run: `python3 -m pytest tests/orchestrator/test_pipeline_integration.py::test_content_validator_dispatch_includes_plugin_root -v`

Expected: PASS.

- [ ] **Step 4: Run the full test suite to verify no regressions**

Run: `python3 -m pytest`

Expected: all tests pass.

- [ ] **Step 5: Commit the orchestrator change**

```bash
git add scripts/orchestrator_runner.py
git commit -m "$(cat <<'EOF'
fix(CCE-67): inject plugin_root into content-validator dispatch payload

The orchestrator already resolves _PLUGIN_ROOT at module load (line 64) and
passes it to the claude CLI via --plugin-dir for plugin discovery. The
content-validator subagent, however, had no way to know where the plugin's
scripts/ directory lived — it inherits the orchestrator's CWD (host repo root)
and the agent contract hardcoded a host-relative path. In CI the plugin is
vendored at .docs-agent-plugin/scripts/, so every Tier-1 lint rule was
crashing on a missing file.

Pass _PLUGIN_ROOT explicitly in the dispatch payload. Agent contract update
in the following commit makes the subagent interpolate it.

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>
EOF
)"
```

---

### Task 3: Agent contract — interpolate `plugin_root` in `lint_runner.py` invocation

**Files:**

- Modify: `agents/content-validator.md:14,18-22,78`

- [ ] **Step 1: Update the Job block (line 14)**

Edit `agents/content-validator.md` line 14:

```markdown
Run `{plugin_root}/scripts/lint/lint_runner.py` on the given paths with the host config,
then run any LLM-based semantic checks not implementable as scripts
(voice_consistency from spec §6.2). Aggregate into one structured result.
```

- [ ] **Step 2: Update the Inputs block (lines 18-22)**

Add a fourth bullet for `plugin_root`:

```markdown
- `paths`: list of file paths the orchestrator just authored/edited
- `config_path`: path to the host's `.engineering-docs-agent/config.yml`
- `voice_samples`: voice sample bundle (only used if `voice_consistency` is enabled in tier 2)
- `plugin_root`: absolute path to the engineering-docs-agent plugin checkout. The lint runner lives at `{plugin_root}/scripts/lint/lint_runner.py`. The plugin is vendored separately from the host repo (e.g. at `.docs-agent-plugin/` in CI), so this path is not host-relative.
```

- [ ] **Step 3: Update the Procedure step (line 78)**

Rewrite step 1 of the Procedure block:

```markdown
1. Run `python {plugin_root}/scripts/lint/lint_runner.py --config <config_path> --paths <paths...> --json`.
   Substitute the literal value of `plugin_root` from the input — do not assume the runner is on `$PATH` or at a relative path. Quote the plugin_root path if it contains spaces.
```

- [ ] **Step 4: Update Failure handling (line 85) to include the attempted path**

For better diagnostics when the path is wrong (defense-in-depth — this should never happen now, but if it does, the message must say WHERE it looked):

```markdown
If `lint_runner.py` exits non-zero AND output is unparseable, return `{failed: [{path: "*", rule: "lint_runner", message: "runner crashed at {plugin_root}/scripts/lint/lint_runner.py: <stderr>", severity: "block"}]}`.
```

- [ ] **Step 5: Run the agent-contract schema-sync test**

Run: `python3 -m pytest tests/agents/test_schema_md_sync.py -v`

Expected: PASS. (The schema-sync test validates output schemas; the input change should not break it. If it does, investigate before proceeding.)

- [ ] **Step 6: Run the full test suite**

Run: `python3 -m pytest`

Expected: all tests pass.

- [ ] **Step 7: Commit the contract update**

```bash
git add agents/content-validator.md
git commit -m "$(cat <<'EOF'
fix(CCE-67): content-validator interpolates plugin_root in lint_runner path

Updates the agent contract to read plugin_root from inputs and substitute it
into the lint_runner invocation. Documents that the plugin is vendored
separately from the host repo (e.g. .docs-agent-plugin/ in CI) so the path
is not host-relative. Adds the attempted path to the runner-crashed failure
message for diagnosability.

Pairs with the previous commit that adds plugin_root to the dispatch payload.

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>
EOF
)"
```

---

### Task 4: Defensive — agent payload validation for missing `plugin_root`

**Files:**

- Modify: `tests/orchestrator/test_pipeline_integration.py` (append second test)

**Rationale:** Lock in the failure mode so a future refactor that drops `plugin_root` gets a structured `lint_block` partial reason, not a silent regression. Tests the orchestrator's behavior; no production code change.

- [ ] **Step 1: Write the test**

Append to `tests/orchestrator/test_pipeline_integration.py`:

```python
def test_content_validator_payload_plugin_root_is_str_not_path(tmp_path, monkeypatch):
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

    _init_host(tmp_path)
    runner.run(tmp_path, dry_run_dir=FAKES, no_pr=True)

    assert captured
    plugin_root_value = captured[0]["plugin_root"]
    assert isinstance(plugin_root_value, str), (
        f"plugin_root must be a str for JSON, got {type(plugin_root_value).__name__}"
    )
```

- [ ] **Step 2: Run the test to verify it passes**

Run: `python3 -m pytest tests/orchestrator/test_pipeline_integration.py::test_content_validator_payload_plugin_root_is_str_not_path -v`

Expected: PASS (Task 2 used `str(_PLUGIN_ROOT)`).

- [ ] **Step 3: Run the full suite**

Run: `python3 -m pytest`

Expected: all tests pass.

- [ ] **Step 4: Commit**

```bash
git add tests/orchestrator/test_pipeline_integration.py
git commit -m "$(cat <<'EOF'
test(CCE-67): assert plugin_root is serialized as str in dispatch payload

Locks in the JSON-serializability contract: a future refactor that passes
Path instead of str would break the agent-side interpolation on platforms
where Path.__str__ differs (POSIX vs Windows).

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>
EOF
)"
```

---

### Task 5: Full pytest run + verify CCE-64 still green

**Files:** (no edits — verification only)

- [ ] **Step 1: Run full pytest suite**

Run: `python3 -m pytest -v 2>&1 | tail -40`

Expected: all tests pass. Pay particular attention to:

- `tests/orchestrator/test_pipeline_integration.py` — new tests + existing voice-samples test must all pass
- `tests/agents/test_schema_md_sync.py` — must pass (output schema unchanged)
- `tests/lint/test_framework_build.py` — CCE-64 must remain green
- `tests/test_preflight_host.py` — CCE-64 preflight tests must remain green
- `tests/test_config_schema.py` — CCE-64 schema enum test must remain green

- [ ] **Step 2: Verify branch state**

```bash
git log --oneline main..HEAD
git status --short
```

Expected: 4 commits ahead of main (spec, test, orchestrator fix, contract fix, defensive test). Working tree clean.

- [ ] **Step 3: No commit (verification step only)**

If everything is green, hand off to /ship. If anything fails, return to the failing task; do NOT proceed to /ship.

---

## Out of scope

- **Refactoring content-validator** to split lint dispatch from voice_consistency — own ticket.
- **Audit of OTHER subagents** for plugin-script invocations — already done in spec; only content-validator was affected today. If a future contract needs plugin scripts, follow this pattern.
- **CCE-66 (`app-id` → `client-id`)** — separate ticket, separate PR.
- **CCE-66 plugin-side root-cause for `dismissed_gap_flags`** — separate ticket.
- **Updating `templates/workflow-run.yml`** — stays out; the vendored-checkout pattern is correct, this PR adapts to it.

## After Task 5 — handoff

Surface ship-readiness to the controller. The controller will invoke `/ship` as a separate step. /ship will run pytest one more time, then push the branch, open a PR linked to CCE-67, and wait for CI/merge approval. Re-running the dual-host smoke tests is the verification step AFTER merge to main.
