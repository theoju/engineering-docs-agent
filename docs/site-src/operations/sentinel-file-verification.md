---
status: draft
sources:
  - https://github.com/theoju/engineering-docs-agent/pull/81
synthesized_into: []
doc_kind: architecture
---

# Sentinel File Verification

After every `run()` call — whether it succeeds or partially fails — the orchestrator writes a machine-readable sentinel file at `.engineering-docs-agent/last_run_invariant.json`. Your workflow can read this file to verify that state advancement behaved correctly without parsing the full run log.

## File location and schema

```
.engineering-docs-agent/last_run_invariant.json
```

```json
{
  "advanced": true,
  "reason": "clean run — all lenses completed"
}
```

`advanced` is a boolean. `reason` is a free-text string explaining why state did or did not advance.

The file is overwritten on every run. It is gitignored and is not included in the docs-agent PR.

## When state advances and when it does not

The runner enforces three invariants, each covered by a parametrized test in the orchestrator test suite:

**No advance on partial.** If any lens is partial — a subagent failed, a source was unreachable, or the run was aborted early — `advanced` is `false`. `state.json` is left at its previous SHA.

**Advance on clean.** If all lenses complete without errors, `advanced` is `true` and `state.json.last_successful_run.head_sha` moves forward to the current commit.

**No SHA regression.** The cursor never moves backward. Even if `advanced` is `false`, the SHA in `state.json` is never set to a value older than the one the run started with.

## Consuming the sentinel in a workflow

Read the sentinel after the runner exits and fail the workflow step if the invariant was violated unexpectedly.

```yaml
- name: Check state advancement
  run: |
    python3 - <<'EOF'
    import json, sys, pathlib
    sentinel = pathlib.Path(".engineering-docs-agent/last_run_invariant.json")
    if not sentinel.exists():
        print("ERROR: sentinel file missing — run() did not complete")
        sys.exit(1)
    data = json.loads(sentinel.read_text())
    print(f"advanced={data['advanced']}  reason={data['reason']}")
    # Fail if the run was expected to be clean but was not.
    if not data["advanced"]:
        print("WARNING: state did not advance — check run log for partial reasons")
        sys.exit(1)
    EOF
```

Adjust the exit condition to match your policy. Some workflows treat a partial run as a soft warning (open the PR anyway, mark it partial); others treat it as a hard failure that blocks the PR step.

## What the sentinel does not replace

The sentinel tells you _whether_ state advanced and why. It does not tell you which lenses were partial, which subagents failed, or what content was authored. For that detail, read `current_run.json` (written alongside the sentinel) or the full run log from `DOCS_AGENT_DEBUG_DIR`.

The sentinel is deliberately minimal so it stays parseable by a one-liner shell or Python snippet in any workflow environment.

## Relation to the invariant test suite

Three parametrized tests in the orchestrator runner test suite assert these invariants against a fixture-driven dry-run path. If you change the state-advancement logic in `scripts/orchestrator_runner.py`, run `python3 -m pytest tests/test_orchestrator_runner.py -k invariant` to verify all three still pass before opening a PR.
