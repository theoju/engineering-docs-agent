---
status: draft
ticket: CCE-67
related: CCE-57, CCE-58, CCE-64
created: 2026-05-31
---

# CCE-67 — content-validator plugin-script path resolution

## Goal

Make the content-validator subagent invoke `lint_runner.py` at the **plugin** location, not the host's working directory. Restore Tier-1 lint validation on every onboarded host so the orchestrator's content-validation stage produces structured results instead of crashing on a missing file.

## Background

The 2026-05-31 smoke tests of both onboarded hosts (CCE-57 / claude-code-self-assessment and CCE-58 / advanced-data-import-system) caught the same crash:

```
lint_block: lint_runner crashed: python: can't open file
'/home/runner/work/<host>/<host>/scripts/lint/lint_runner.py': [Errno 2] No such file or directory
```

The content-validator subagent inherits its CWD from the orchestrator, which runs at the host repo root. The plugin's `scripts/` directory is checked out separately at `.docs-agent-plugin/scripts/` (per `templates/workflow-run.yml:40,52`). `agents/content-validator.md` lines 14 and 78 hardcode the host-relative path `scripts/lint/lint_runner.py`, so the lookup misses.

The orchestrator already resolves `_PLUGIN_ROOT` at module load (`scripts/orchestrator_runner.py:64`) and passes it to the claude CLI via `--plugin-dir`. It does NOT, however, expose this path to subagent inputs, so the agent has no way to construct the correct invocation.

CCE-41's forensics + partial-PR design caught this gracefully — both hosts opened partial PRs with `lint_block` in `partial_reasons` and the forensics artifact attached. No data was lost; the system surfaced the failure and continued. That's the design working under a real defect.

## Why this matters now

CCE-64 (framework=none first-class) is only proven by unit tests. Production proof — that `framework_build` emits `"framework=none; no build validation applicable"` on CCSA and that mkdocs build succeeds on ADIS — depends on the lint stage running. The smoke tests cannot validate CCE-64 until this is fixed.

## Approach

Pass `plugin_root` through to the content-validator subagent as an explicit input field, and update the agent contract to interpolate it.

Rejected alternatives:

- **(B) Bypass the subagent and invoke `lint_runner.py` directly from the orchestrator.** Cleaner: removes an LLM call for what is essentially a subprocess invocation. But content-validator also handles voice_consistency (LLM-judgment), and that mixing is the contract today. Separating them is a larger refactor (its own ticket, not this one). YAGNI for v0.1.
- **(C) Environment variable (`DOCS_AGENT_PLUGIN_ROOT`).** Works, but invisible in the agent contract — discoverability suffers. Subagent inputs are the documented interface; env-vars route around it.
- **(D) Run the agent with `cwd=plugin_root` instead of `cwd=repo_root`.** Breaks every other agent contract that reads `paths` and `config_path` as host-relative.

## What changes

### 1. Orchestrator — `scripts/orchestrator_runner.py`

At `scripts/orchestrator_runner.py:1194-1203`, the content-validator dispatch currently passes `paths`, `config_path`, `voice_samples`. Add a fourth field:

```python
validation, reasons = dispatch_validated(
    "content-validator",
    {
        "paths": authored,
        "config_path": str(cfg_path),
        "voice_samples": voice_samples,
        "plugin_root": str(_PLUGIN_ROOT),   # NEW — absolute path to the plugin checkout
    },
    dry_run_dir=dry_run_dir,
    cwd=repo_root,
)
```

`_PLUGIN_ROOT` is already computed at module load (line 64); no new resolution logic needed. The field is always an absolute path.

### 2. Agent contract — `agents/content-validator.md`

**Inputs block (lines 18-22):** add `plugin_root`:

```markdown
- `paths`: list of file paths the orchestrator just authored/edited
- `config_path`: path to the host's `.engineering-docs-agent/config.yml`
- `voice_samples`: voice sample bundle (only used if `voice_consistency` is enabled in tier 2)
- `plugin_root`: absolute path to the engineering-docs-agent plugin checkout. The lint runner lives at `{plugin_root}/scripts/lint/lint_runner.py`.
```

**Procedure step 1 (line 78):** rewrite to use `plugin_root`:

```markdown
1. Run `python {plugin_root}/scripts/lint/lint_runner.py --config <config_path> --paths <paths...> --json`.
   Substitute the literal value of `plugin_root` from the input — do not assume the runner is on `$PATH` or at a relative path.
```

**Job block (line 14):** mirror update so the prose matches:

```markdown
Run `{plugin_root}/scripts/lint/lint_runner.py` on the given paths with the host config, then run any LLM-based semantic checks not implementable as scripts (voice_consistency from spec §6.2). Aggregate into one structured result.
```

### 3. Schema — `agents/schemas/content-validator-input.json` (if it exists)

If there is a JSON schema for content-validator inputs in `agents/schemas/`, extend it: add `plugin_root` as a required string property. If no input schema exists, no change here (no schemas to drift out of sync).

### 4. Regression test — `tests/`

A new test asserts the orchestrator includes `plugin_root` in the dispatched payload AND that the path resolves to a real `lint_runner.py`. Use the fixture-driven dry-run path that all other orchestrator tests use.

Sketch:

```python
def test_content_validator_dispatch_includes_plugin_root(tmp_path, monkeypatch):
    captured: list[dict] = []

    def fake_dispatch(name, payload, *args, **kwargs):
        captured.append({"name": name, "payload": payload})
        return ({"passed": [{"path": "doc.md", "rules": ["frontmatter"]}], "failed": []}, [])

    monkeypatch.setattr(orchestrator_runner, "dispatch_validated", fake_dispatch)

    # ... set up host fixture with one authored page ...
    orchestrator_runner.main(...)

    validator_calls = [c for c in captured if c["name"] == "content-validator"]
    assert len(validator_calls) == 1
    payload = validator_calls[0]["payload"]
    assert "plugin_root" in payload
    plugin_root = Path(payload["plugin_root"])
    assert plugin_root.is_absolute()
    assert (plugin_root / "scripts" / "lint" / "lint_runner.py").exists()
```

This is the minimum to prevent the regression. The smoke-test re-run after merge proves the end-to-end path.

## What does NOT change

- The lint_runner itself (`scripts/lint/lint_runner.py`) — already takes `--config` and `--paths` as CLI args; no signature change.
- Tier-1 / Tier-2 lint rules — they keep their interfaces.
- The other six subagents — audit shows only content-validator shells out to a plugin script; references in `agents/page-author.md` and `agents/pr-summarizer.md` are prose (documentation paths in examples), not executed.
- The orchestrator's CWD for subagent dispatch — stays `repo_root` so `paths` and `config_path` keep their host-relative semantics.
- The content-validator output schema — unchanged.
- `templates/workflow-run.yml` — the vendored-checkout pattern stays; this spec adapts the agent contract to that reality, not the other way around.

## Data flow

```
orchestrator_runner
  └─→ _PLUGIN_ROOT = /home/runner/work/.../<host>/.docs-agent-plugin  (CI)
                  =  /Users/theo/Projects/engineering-docs-agent       (local dogfood)
  └─→ dispatch_validated("content-validator", {
        paths: [...],
        config_path: ".engineering-docs-agent/config.yml",
        voice_samples: {...},
        plugin_root: str(_PLUGIN_ROOT),
      }, cwd=repo_root)
       └─→ content-validator subagent (CWD = host repo root)
            └─→ python {plugin_root}/scripts/lint/lint_runner.py --config ... --paths ...
                 └─→ lint_runner imports its rules from {plugin_root}/scripts/lint/rules/
                 └─→ writes JSON to stdout
            └─→ parse + return structured result
```

## Error handling

- **Missing `plugin_root` in input** (unexpected): agent treats this as an input-contract violation and returns `{failed: [{path: "*", rule: "lint_runner", message: "input missing plugin_root", severity: "block"}]}`. Same severity as the current `runner crashed` fallback — preserves the existing partial-PR behavior.
- **`{plugin_root}/scripts/lint/lint_runner.py` missing**: same fallback. The agent's existing "Failure handling" block (line 85) covers this — message text changes from "No such file or directory" to a structured message including the attempted path.
- **`plugin_root` is relative**: agent still works (`python rel/scripts/...` is valid) but flags fragility. Orchestrator always passes an absolute path; the agent contract documents that expectation.

## Testing

1. **Unit test on orchestrator dispatch** (new) — `tests/test_orchestrator_runner.py` extension: assert content-validator dispatch payload contains `plugin_root` and the path resolves to a real `lint_runner.py`.
2. **Existing tests must still pass** — all current `tests/lint/*` and `tests/test_orchestrator_runner*` tests run unchanged. The contract addition is additive; payload consumers that ignore the new field continue to work.
3. **Manual smoke verification** post-merge — re-trigger `docs-agent-nightly` on CCSA and ADIS. Verify:
   - Run conclusion stays `success` (already true before this fix).
   - `partial_reasons` no longer contains `lint_block` from the path crash.
   - For CCSA: log line contains `"framework=none; no build validation applicable"` proving CCE-64 framework_build path runs.
   - For ADIS: mkdocs build executes (framework_build does not skip).
4. **Forensics artifact** continues to upload on both — already proven by today's runs.

## Migration

No host-side migration. The change is plugin-internal: the orchestrator passes a new field to the agent contract; the agent's behavior changes accordingly. Existing host configs (CCSA, ADIS, dogfood) are unaffected. Nightly runs on those hosts will start succeeding once the plugin's main is updated.

## Out of scope

- **Separating lint dispatch from voice_consistency** — see "Approach" §B. Worth doing eventually; not now.
- **Plugin-root resolution for OTHER agents** — audit shows none of the other six need it today. If a future agent needs to shell out to plugin scripts, follow this pattern.
- **CCE-66 (`app-id` → `client-id` deprecation)** — separate ticket; surfaced as a non-blocking warning on both smoke-test runs but does not affect lint dispatch.
- **CCE-66 plugin-side root-cause for `dismissed_gap_flags`** — separate ticket; the state-shape fix (CCE-65) is already merged on both hosts and held during these runs.

## Risks

- **Contract drift if the orchestrator changes the input shape** — mitigated by the new regression test, which fails loudly if `plugin_root` is dropped from the payload.
- **Subagent CLI does not interpolate `{plugin_root}` literally** — the agent is an LLM, not a template engine; it must SUBSTITUTE the value from the input. The contract spells this out at line 78. Past contracts have correctly done this for other interpolated values (`<config_path>`, `<paths...>`), so the pattern is established.
- **Path with spaces on local dev** — `python "/path with space/scripts/lint/lint_runner.py"` works in bash but the agent must quote correctly. Mitigation: contract notes the path may contain spaces; the agent should treat it as a quoted argument.

## Success criteria

1. The next nightly run on CCSA completes with `framework_build` lint emitting its documented `"framework=none; no build validation applicable"` reason. CCE-64 production-proven.
2. The next nightly run on ADIS completes with mkdocs build executed by `framework_build` lint. CCE-58 production-proven.
3. Neither run has `lint_block` in `partial_reasons` (the runner doesn't crash).
4. Existing `python3 -m pytest` suite stays green.
5. The new regression test fails on any future PR that drops `plugin_root` from the dispatch payload.

## References

- `scripts/orchestrator_runner.py:64` — `_PLUGIN_ROOT` resolution
- `scripts/orchestrator_runner.py:435-436` — existing `--plugin-dir` flag passed to claude CLI
- `scripts/orchestrator_runner.py:1194-1203` — content-validator dispatch site
- `agents/content-validator.md:14,18-22,78,85` — agent contract sections that change
- `templates/workflow-run.yml:40,52` — vendored-checkout pattern this adapts to
- CCSA smoke test: https://github.com/theoju/claude-code-self-assessment/actions/runs/26726939558 (PR #103)
- ADIS smoke test: https://github.com/theoju/advanced-data-import-system/actions/runs/26727100978 (PR #393)
- CCE-41 forensics + partial-PR design (the safety net that caught this gracefully)
- CCE-64 spec — the production proof this unblocks
